"""Agent 对话 API：WebSocket 实时对话 + 会话管理。

事件流三类型齐全：assistant / tool_call+tool_result / state。
"""  # reload-trigger

import asyncio
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.auth import CurrentUser, get_current_user, require_role, require_role_ws

# Agent 能力整体对 tester+ 开放（viewer 无此菜单，后端同样拦截）。
# 注意：本路由含 WebSocket 端点，Request 型依赖在 WS 上无法注入，
# 因此角色门禁放在端点级（HTTP 用 require_role，WS 用 require_role_ws）。
router = APIRouter(prefix="/api/agent", tags=["agent"])

# 确保仓库根在 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.llm_client import LLMClient
from agent.session import SessionManager, _validate_session_id
from agent.runtime import AgentRuntime, build_system_prompt
from agent.mode_loader import list_modes
from agent.skill_loader import list_skills

SESSIONS_ROOT = SG_ROOT / "agent" / "sessions"

# K-015: 会话级互斥——同一 session_id 只允许一个活跃 run
# （session.save 是全量覆盖写，两个并发 run 会互相冲掉对方内容，last-writer-wins；
#  用户真实会话导出文件取证：同 sid 的标签生成与草稿问答两段对话互相覆盖）
_ACTIVE_RUNS: dict[str, "asyncio.Task"] = {}


def _run_in_progress(session_id: str) -> bool:
    task = _ACTIVE_RUNS.get(session_id)
    return task is not None and not task.done()


def _build_scenario_context(scenario_id: str) -> str:
    """构建场景上下文字符串（基础信息包提示）。"""
    if not scenario_id:
        return ""
    try:
        BACKEND_DIR = SG_ROOT / "workbench" / "backend"
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))
        from services import scenario_meta
        meta = scenario_meta.get_meta(scenario_id)
    except Exception:
        return ""
    if not meta:
        return ""
    files = meta.get("info_pack", [])
    if not files:
        return f"当前场景：{scenario_id}（{meta.get('name', '')}）。基础信息包为空，请用 read_spec 工具读取工作区文件。"
    # K-013：信息包清单附新鲜度标记（每条消息重建 context，天然实时感知变更）
    from specstd.workspace import safe_resolve
    lines = []
    for e in files:
        path = e.get("path", "") if isinstance(e, dict) else str(e)
        stored = e.get("sha", "") if isinstance(e, dict) else ""
        mark = ""
        try:
            resolved = safe_resolve(path)
            if not resolved or not resolved.is_file():
                mark = "（已删除）"
            elif stored and scenario_meta.file_sha(resolved) != stored:
                mark = "（已变更）"
        except Exception:
            pass
        lines.append(f"  - {path}{mark}")
    file_list = "\n".join(lines)
    stale_hint = ("\n注意：标记（已变更）/（已删除）的文件与信息包记录时不一致，"
                  "请以当前内容为准，并提醒用户信息包需要更新。") if any("（" in ln for ln in lines) else ""
    return (
        f"当前场景：{scenario_id}（{meta.get('name', '')}）\n"
        f"模块：{meta.get('module', '')}\n"
        f"基础信息包文件：\n{file_list}\n"
        f"请用 read_info_pack 工具读取上述文件内容。{stale_hint}"
    )


def _sessions_dir(emp_no: str) -> Path:
    """按用户隔离的会话目录（M7）：agent/sessions/{emp_no}/。"""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", emp_no or "_anonymous")
    return SESSIONS_ROOT / safe


# ══════════════════════════════════════════════════════════
# K-013: @引用处理（信息包关联 / 文件与草稿内容注入）
# ══════════════════════════════════════════════════════════

_REF_MAX_FILE = 20 * 1024    # 单文件注入上限 20KB
_REF_MAX_TOTAL = 60 * 1024   # 全部引用注入上限 60KB
_REF_MAX_COUNT = 10          # 单条消息最多引用数


def _process_references(references: list, scenario_id: str) -> tuple[str, str, list]:
    """处理 @引用，返回 (scenario_id, 引用内容块, 结构化引用清单)。

    - info_pack：关联为当前场景（不注入内容，走 _build_scenario_context 标准流程）
    - file / draft：读取内容（截断保护）拼 <references> 块前缀到 user message，
      同时返回含引用时 sha 的结构化清单（挂 user 消息持久化，供右侧引用面板比对新鲜度）
    """
    import hashlib
    if not references:
        return scenario_id, "", []

    from specstd.workspace import safe_resolve

    structured: list[dict] = []
    blocks: list[str] = []
    total = 0

    for ref in references[:_REF_MAX_COUNT]:
        if not isinstance(ref, dict):
            continue
        rtype = ref.get("type", "")
        rid = str(ref.get("id") or ref.get("path") or "")
        if not rid:
            continue

        if rtype == "info_pack":
            # 关联语义：当前对话未关联场景时接管 scenario_id
            if not scenario_id:
                scenario_id = rid
            structured.append({"type": "info_pack", "path": rid, "sha": ""})
            continue

        content, sha = "", ""
        try:
            if rtype == "file":
                resolved = safe_resolve(rid)
                if resolved and resolved.is_file():
                    raw = resolved.read_bytes()
                    sha = hashlib.sha256(raw).hexdigest()[:12]
                    content = raw.decode("utf-8", errors="replace")
            elif rtype == "draft":
                # 草稿文件名守卫（与 draft_writer 一致：禁路径分隔符和 ..）
                name = rid.replace("/", "").replace("\\", "").replace("..", "")
                from specstd.workspace import drafts_dir
                p = drafts_dir() / name
                if p.is_file():
                    raw = p.read_bytes()
                    sha = hashlib.sha256(raw).hexdigest()[:12]
                    content = raw.decode("utf-8", errors="replace")
        except Exception:
            continue

        if not content:
            blocks.append(f"--- {rid} ---\n[文件不存在或不可读]")
            structured.append({"type": rtype, "path": rid, "sha": "", "missing": True})
            continue

        truncated = False
        if len(content) > _REF_MAX_FILE:
            content = content[:_REF_MAX_FILE]
            truncated = True
        if total + len(content) > _REF_MAX_TOTAL:
            content = content[:max(0, _REF_MAX_TOTAL - total)]
            truncated = True
        total += len(content)
        blocks.append(f"--- {rid} (sha:{sha}) ---\n{content}" + ("\n[截断]" if truncated else ""))
        structured.append({"type": rtype, "path": rid, "sha": sha})

    block_text = ""
    if blocks:
        block_text = "<references>\n" + "\n\n".join(blocks) + "\n</references>\n\n"
    return scenario_id, block_text, structured


def _iter_all_session_dirs() -> list[Path]:
    """全部用户会话目录（admin 视图）。"""
    if not SESSIONS_ROOT.is_dir():
        return []
    return [d for d in sorted(SESSIONS_ROOT.iterdir()) if d.is_dir() and not d.name.startswith("_")]


def _list_sessions_in_dir(base_dir: Path, workspace: str = "") -> list[dict]:
    """在指定目录下列出会话（支持工作区子目录）。"""
    from agent.session import SessionManager
    sessions = []
    if workspace:
        # 指定工作区：只查该子目录
        ws_dir = base_dir / workspace
        if ws_dir.is_dir():
            sm = SessionManager(base_dir, workspace=workspace)
            sessions.extend(sm.list_sessions())
    else:
        # 未指定工作区：查根目录（旧会话）+ 所有工作区子目录
        sm = SessionManager(base_dir)
        sessions.extend(sm.list_sessions())
        for sub in sorted(base_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith("_") and not sub.name.startswith("."):
                ws_sm = SessionManager(base_dir, workspace=sub.name)
                for s in ws_sm.list_sessions():
                    sessions.append(s)
    return sessions


# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════

@router.get("/sessions")
def list_sessions(workspace: str = "", user: CurrentUser = Depends(require_role("admin", "tester"))):
    """列出会话：本人目录；admin 聚合全部用户目录。支持按工作区筛选。"""
    if user.is_admin:
        sessions = []
        for d in _iter_all_session_dirs():
            for s in _list_sessions_in_dir(d, workspace=workspace):
                s["owner"] = d.name
                sessions.append(s)
        return {"sessions": sessions}
    sm_dir = _sessions_dir(user.emp_no)
    return {"sessions": _list_sessions_in_dir(sm_dir, workspace=workspace)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, workspace: str = "", user: CurrentUser = Depends(require_role("admin", "tester"))):
    """获取会话详情（本人会话；admin 可查全部）。支持工作区子目录。"""
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    dirs = _iter_all_session_dirs() if user.is_admin else [_sessions_dir(user.emp_no)]
    for d in dirs:
        # 尝试工作区子目录 + 根目录
        sm = SessionManager(d, workspace=workspace)
        messages = sm.load(session_id)
        if messages is not None:
            return {"session_id": session_id, "messages": messages, "owner": d.name, "workspace": workspace}
        # 如果指定工作区未找到，也尝试无工作区（兼容旧会话）
        if workspace:
            sm2 = SessionManager(d)
            messages = sm2.load(session_id)
            if messages is not None:
                return {"session_id": session_id, "messages": messages, "owner": d.name, "workspace": ""}
    raise HTTPException(status_code=404, detail="会话不存在")


def _generate_session_title(llm: LLMClient, messages: list[dict]) -> str:
    """用 LLM 生成会话标题（首条用户消息 + 首条助手回复 → 简短标题）。

    mock 模式下回退为用户消息截断。
    """
    user_msg = next((m for m in messages if m.get("role") == "user"), None)
    assistant_msg = next((m for m in messages if m.get("role") == "assistant"), None)
    if not user_msg:
        return "新会话"
    user_content = str(user_msg.get("content", ""))[:200]
    if llm.is_mock:
        # mock 模式：截取用户消息前 15 字符
        title = user_content[:15].replace("\n", " ").strip()
        return title or "新会话"
    try:
        prompt_msgs = [
            {"role": "system", "content": "请用10个字以内概括以下对话的主题，只输出标题文字，不要加引号或标点。"},
            {"role": "user", "content": f"用户：{user_content}\n助手：{str(assistant_msg.get('content', ''))[:200] if assistant_msg else ''}"},
        ]
        msg, _ = llm.chat(prompt_msgs, tools=None)
        title = str(msg.get("content", "")).strip().replace("\n", " ")[:20]
        return title or "新会话"
    except Exception:
        return user_content[:15].replace("\n", " ").strip() or "新会话"


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str, workspace: str = "", user: CurrentUser = Depends(require_role("admin", "tester"))):
    """导出会话为 JSON（元数据 + 消息 + 指标），便于排查问题。"""
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    dirs = _iter_all_session_dirs() if user.is_admin else [_sessions_dir(user.emp_no)]
    for d in dirs:
        sm = SessionManager(d, workspace=workspace)
        data = sm.export_session(session_id)
        if data is not None:
            return data
        if workspace:
            sm2 = SessionManager(d)
            data = sm2.export_session(session_id)
            if data is not None:
                return data
    raise HTTPException(status_code=404, detail="会话不存在")


class ChatBody(BaseModel):
    message: str
    session_id: str = ""
    max_turns: int = 12
    workspace: str = ""
    scenario_id: str = ""
    model_id: str = ""
    references: list = []  # K-013: @引用（info_pack/file/draft）
    context: dict = {}  # 前端路由上下文（K-023 后仅透传保留，不再驱动模式路由）


@router.get("/modes")
def get_modes(user: CurrentUser = Depends(require_role("admin", "tester"))):
    """列出可用的工作模式。"""
    modes = list_modes()
    return {"modes": [
        {
            "name": m.name,
            "tools": m.tools,
            "description": m.description,
            "prompt_fragment": m.prompt_fragment[:200] + "..." if len(m.prompt_fragment) > 200 else m.prompt_fragment,
        }
        for m in modes
    ]}


@router.get("/skills")
def get_skills(user: CurrentUser = Depends(require_role("admin", "tester"))):
    """列出可用的技能。"""
    skills = list_skills()
    return {"skills": [
        {
            "name": s.name,
            "description": s.description,
            "trigger": s.trigger,
            "content": s.content[:300] + "..." if len(s.content) > 300 else s.content,
        }
        for s in skills
    ]}


@router.post("/chat")
async def chat(body: ChatBody, user: CurrentUser = Depends(require_role("admin", "tester"))):
    """同步对话（非 WebSocket，适合短交互）。"""
    if body.session_id:
        try:
            _validate_session_id(body.session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法 session_id")
    llm = LLMClient(model_id=body.model_id) if body.model_id else LLMClient()
    sessions_dir = _sessions_dir(user.emp_no)
    workspace = body.workspace or ""
    sm = SessionManager(sessions_dir, workspace=workspace)
    sid = body.session_id or sm.create(emp_no=user.emp_no, workspace=workspace)
    llm.set_metrics_file(sessions_dir / (f"{workspace}/" if workspace else "") / f"{sid}_metrics.jsonl")

    # K-015: 同会话并发写防护
    if _run_in_progress(sid):
        raise HTTPException(status_code=409, detail="该会话正在执行中，请稍后重试")

    # 设置工作区上下文（HTTP 请求可能由中间件设置，但 body.workspace 是显式传入的更可靠）
    from specstd.workspace import set_context_workspace, reset_context_workspace
    _ctx_token = set_context_workspace(workspace or None)

    events = []

    # K-023 去模式化：统一 system prompt（全量工具 + 全量指引，无路由无切换）
    scenario_context = _build_scenario_context(body.scenario_id)
    system_prompt = build_system_prompt(scenario_context=scenario_context)
    runtime = AgentRuntime(llm, max_turns=body.max_turns)

    # K-013: @引用处理（info_pack 关联场景 / file+draft 内容注入）
    scenario_id, ref_block, structured_refs = _process_references(body.references, body.scenario_id)
    if scenario_id != body.scenario_id:
        scenario_context = _build_scenario_context(scenario_id)
        system_prompt = build_system_prompt(scenario_context=scenario_context)
    chat_message = f"{ref_block}{body.message}" if ref_block else body.message

    # K-012：assistant_delta 流式增量事件对 HTTP 同步调用无意义，不收集（避免响应体膨胀）
    runtime.events.subscribe(
        lambda e: None if e.get("type") == "assistant_delta" else events.append(e)
    )

    run_task = asyncio.create_task(
        asyncio.to_thread(runtime.run, system_prompt, chat_message, sm, sid,
                          structured_refs or None)
    )
    _ACTIVE_RUNS[sid] = run_task  # K-015: 登记活跃 run（并发防护）
    try:
        messages = await run_task
    finally:
        _ACTIVE_RUNS.pop(sid, None)

    # 恢复上下文
    reset_context_workspace(_ctx_token)

    return {
        "session_id": sid,
        "messages": messages,
        "events": events,
        "stats": llm.get_stats(),
    }


# ══════════════════════════════════════════════════════════
# WebSocket 端点
# ══════════════════════════════════════════════════════════

@router.websocket("/ws")
async def agent_ws(websocket: WebSocket,
                   _user: CurrentUser = Depends(require_role_ws("admin", "tester"))):
    """WebSocket 实时对话（WS 专用角色依赖；token 经 query 参数传入）。

    前端发送：{"message": "用户消息", "session_id": "可选会话ID"}
    后端推送事件：assistant / tool_call / state / done
    """
    await websocket.accept()
    # 连接级用户身份（路由级 require_role 已完成认证，身份经 contextvar 传入）
    from services.auth import current_emp_no
    _ws_emp_no = current_emp_no()

    # 从查询参数读取工作区并设置上下文（浏览器 WebSocket 不支持自定义 header）
    from specstd.workspace import set_context_workspace, reset_context_workspace
    _ws_query_workspace = websocket.query_params.get("workspace", "")
    _ws_ctx_token = set_context_workspace(_ws_query_workspace or None)

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            session_id = data.get("session_id", "")
            max_turns = data.get("max_turns", 12)
            workspace = data.get("workspace", "")
            scenario_id = data.get("scenario_id", "")
            model_id = data.get("model_id", "")
            references = data.get("references", [])  # K-013: @引用

            if not message:
                await websocket.send_json({"type": "error", "message": "缺少 message 参数"})
                continue
            if session_id:
                try:
                    _validate_session_id(session_id)
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "非法 session_id"})
                    continue

            # 初始化（会话按用户隔离 + 工作区）
            emp_no = _ws_emp_no or "_anonymous"
            llm = LLMClient(model_id=model_id) if model_id else LLMClient()
            sessions_dir = _sessions_dir(emp_no)
            sm = SessionManager(sessions_dir, workspace=workspace)
            is_new_session = not session_id
            sid = session_id or sm.create(emp_no=emp_no, workspace=workspace)
            llm.set_metrics_file(sessions_dir / (f"{workspace}/" if workspace else "") / f"{sid}_metrics.jsonl")

            # K-015: 同会话并发写防护（另一连接/标签页正在执行同一会话时拒绝）
            if _run_in_progress(sid):
                await websocket.send_json({
                    "type": "error",
                    "message": "该会话正在执行中，请等待当前执行完成（或点击停止后再发送）",
                })
                continue

            await websocket.send_json({"type": "state", "status": "started", "session_id": sid})

            # K-023 去模式化：统一 system prompt（全量工具 + 全量指引）
            scenario_context = _build_scenario_context(scenario_id)
            system_prompt = build_system_prompt(scenario_context=scenario_context)
            runtime = AgentRuntime(llm, max_turns=max_turns)

            # K-013: @引用处理（info_pack 关联场景 / file+draft 内容注入 user message）
            scenario_id, ref_block, structured_refs = _process_references(references, scenario_id)
            if ref_block or structured_refs:
                # info_pack 关联可能改变了 scenario_id → 重建场景上下文与 system prompt
                if scenario_id != data.get("scenario_id", ""):
                    scenario_context = _build_scenario_context(scenario_id)
                    system_prompt = build_system_prompt(scenario_context=scenario_context)
            ws_message = f"{ref_block}{message}" if ref_block else message

            # V7 修复：事件经 asyncio 队列桥接实时推送（原实现跑完后批量推，无实时性）
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            runtime.events.subscribe(
                lambda e: loop.call_soon_threadsafe(queue.put_nowait, e)
            )

            run_task = asyncio.create_task(
                asyncio.to_thread(runtime.run, system_prompt, ws_message, sm, sid,
                                  structured_refs or None)
            )
            _ACTIVE_RUNS[sid] = run_task  # K-015: 登记活跃 run（并发防护）
            try:
                while True:
                    if run_task.done() and queue.empty():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.2)
                        await websocket.send_json(event)
                    except asyncio.TimeoutError:
                        continue
                messages = await run_task  # 运行异常在此抛出，进外层 except
            finally:
                _ACTIVE_RUNS.pop(sid, None)

            # G4: 新会话首条回复后用 LLM 生成标题
            session_title = ""
            if is_new_session and messages:
                try:
                    session_title = _generate_session_title(llm, messages)
                    sm.update_title(sid, session_title)
                except Exception:
                    pass

            # 推送完成
            await websocket.send_json({
                "type": "done",
                "session_id": sid,
                "messages": messages,
                "stats": llm.get_stats(),
                "title": session_title,
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # 记录错误到会话 JSONL（用于导出和排查）
        try:
            if 'sm' in dir() and 'sid' in dir() and sm and sid:
                sm.record_error(sid, str(e), type(e).__name__)
        except Exception:
            pass
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # 恢复工作区上下文
        if _ws_ctx_token:
            reset_context_workspace(_ws_ctx_token)
