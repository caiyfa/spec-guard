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
    file_list = "\n".join(f"  - {f}" for f in files)
    return (
        f"当前场景：{scenario_id}（{meta.get('name', '')}）\n"
        f"模块：{meta.get('module', '')}\n"
        f"基础信息包文件：\n{file_list}\n"
        f"请用 read_info_pack 工具读取上述文件内容。"
    )


def _sessions_dir(emp_no: str) -> Path:
    """按用户隔离的会话目录（M7）：agent/sessions/{emp_no}/。"""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", emp_no or "_anonymous")
    return SESSIONS_ROOT / safe


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
    mode: str = "generate"
    scenario_id: str = ""
    model_id: str = ""


@router.get("/modes")
def get_modes(user: CurrentUser = Depends(require_role("admin", "tester"))):
    """列出可用的工作模式。"""
    modes = list_modes()
    return {"modes": [
        {
            "name": m.name,
            "temperature": m.temperature,
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

    # 设置工作区上下文（HTTP 请求可能由中间件设置，但 body.workspace 是显式传入的更可靠）
    from specstd.workspace import set_context_workspace, reset_context_workspace
    _ctx_token = set_context_workspace(workspace or None)

    # 构建场景上下文（基础信息包）
    scenario_context = _build_scenario_context(body.scenario_id)
    system_prompt = build_system_prompt(mode=body.mode, scenario_context=scenario_context)
    runtime = AgentRuntime(llm, max_turns=body.max_turns, mode_name=body.mode)

    events = []
    runtime.events.subscribe(lambda e: events.append(e))

    messages = await asyncio.to_thread(
        runtime.run, system_prompt, body.message, sm, sid
    )

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
            mode_name = data.get("mode", "generate")
            scenario_id = data.get("scenario_id", "")
            model_id = data.get("model_id", "")

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

            await websocket.send_json({"type": "state", "status": "started", "session_id": sid, "mode": mode_name})

            # 构建 system prompt（含模式 + 场景上下文）
            scenario_context = _build_scenario_context(scenario_id)
            system_prompt = build_system_prompt(mode=mode_name, scenario_context=scenario_context)
            runtime = AgentRuntime(llm, max_turns=max_turns, mode_name=mode_name)

            # V7 修复：事件经 asyncio 队列桥接实时推送（原实现跑完后批量推，无实时性）
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            runtime.events.subscribe(
                lambda e: loop.call_soon_threadsafe(queue.put_nowait, e)
            )

            run_task = asyncio.create_task(
                asyncio.to_thread(runtime.run, system_prompt, message, sm, sid)
            )
            while True:
                if run_task.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.2)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    continue
            messages = await run_task  # 运行异常在此抛出，进外层 except

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
