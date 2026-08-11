"""Agent 对话 API：WebSocket 实时对话 + 会话管理。

事件流三类型齐全：assistant / tool_call+tool_result / state。
"""  # reload-trigger

import asyncio
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

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
from agent.runtime import AgentRuntime, build_system_prompt, resolve_tools
from agent.purpose_loader import load_purpose, visible_purposes

SESSIONS_ROOT = SG_ROOT / "agent" / "sessions"

# K-015: 会话级互斥——同一 session_id 只允许一个活跃 run
# （session.save 是全量覆盖写，两个并发 run 会互相冲掉对方内容，last-writer-wins；
#  用户真实会话导出文件取证：同 sid 的标签生成与草稿问答两段对话互相覆盖）
_ACTIVE_RUNS: dict[str, "asyncio.Task"] = {}

# T-402: 会话运行时追踪（供 cancel 端点查找并设置取消标志）
_ACTIVE_RUNTIMES: dict[str, "AgentRuntime"] = {}


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
    from specstd.workspace import safe_resolve, remote_file_marks
    paths = [e.get("path", "") if isinstance(e, dict) else str(e) for e in files]
    try:
        remote_marks = remote_file_marks(paths)
    except Exception:
        remote_marks = {}
    lines = []
    for e, path in zip(files, paths):
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
        rm = remote_marks.get(path, "")
        if rm == "[远程已更新]":
            mark += "（远程已更新）"
        elif rm == "[远程不存在]":
            mark += "（远程不存在）"
        lines.append(f"  - {path}{mark}")
    file_list = "\n".join(lines)
    stale_hint = ("\n注意：标记（已变更）/（已删除）的文件与信息包记录时不一致，"
                  "请以当前内容为准，并提醒用户信息包需要更新；"
                  "标记（远程已更新）/（远程不存在）表示远程仓库与本地不同步，"
                  "建议用户先在工作区中心「同步」后重新读取。") if any("（" in ln for ln in lines) else ""
    return (
        f"当前场景：{scenario_id}（{meta.get('name', '')}）\n"
        f"模块：{meta.get('module', '')}\n"
        f"基础信息包文件：\n{file_list}\n"
        f"请用 read_info_pack 工具读取上述文件内容。{stale_hint}"
    )


def _sessions_dir(emp_no: str) -> Path:
    """按用户隔离的会话目录（M7）：agent/sessions/{emp_no}/。

    L4 修复：净化规则与 specstd.workspace._emp_subdir 对齐（允许 . 与 -，
    strip 前导点）——此前规则不一致导致含 . 工号的会话目录与产物私有区目录错位。
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", emp_no or "_anonymous").strip(".")
    return SESSIONS_ROOT / (safe or "_anonymous")


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
                    # K-030：办公文档（xlsx/docx/pdf）经 file_preview 转文本——
                    # 此前 errors="replace" 解码出乱码注入，Agent 读不懂信息包里的 xlsx
                    from services import file_preview
                    if file_preview.is_office_doc(resolved):
                        _fmt, content = file_preview.preview_text(resolved)
                    else:
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

        # 远程新鲜度检查（只对工作区文件：远程有更新/远程不存在时标注入引用标头）
        remote_mark = ""
        if rtype == "file":
            try:
                from specstd.workspace import remote_file_marks
                rm = remote_file_marks([rid]).get(rid, "")
                if rm == "[远程已更新]":
                    remote_mark = " [远程已更新]"
                elif rm == "[远程不存在]":
                    remote_mark = " [远程不存在]"
            except Exception:
                pass

        truncated = False
        if len(content) > _REF_MAX_FILE:
            content = content[:_REF_MAX_FILE]
            truncated = True
        if total + len(content) > _REF_MAX_TOTAL:
            content = content[:max(0, _REF_MAX_TOTAL - total)]
            truncated = True
        total += len(content)
        blocks.append(f"--- {rid} (sha:{sha}){remote_mark} ---\n{content}" + ("\n[截断]" if truncated else ""))
        structured.append({"type": rtype, "path": rid, "sha": sha})

    block_text = ""
    if blocks:
        block_text = "<references>\n" + "\n\n".join(blocks) + "\n</references>\n\n"
    return scenario_id, block_text, structured


def _iter_all_session_dirs() -> list[Path]:
    """全部用户会话目录（admin 视图）。"""
    if not SESSIONS_ROOT.is_dir():
        return []
    return [d for d in sorted(SESSIONS_ROOT.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_"))]


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


def _find_session_owner(session_id: str) -> str:
    """查找会话归属目录名（非 admin 取消/读取时的归属校验用；未找到返回空串）。"""
    _validate_session_id(session_id)
    for d in _iter_all_session_dirs():
        if SessionManager(d).load(session_id) is not None:
            return d.name
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")):
                if SessionManager(d, workspace=sub.name).load(session_id) is not None:
                    return d.name
    return ""


# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════

@router.get("/purposes")
def list_purposes_api(user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """T-012/T-013：当前用户可见用途清单（角色集合并集过滤；多用途用户多卡）。"""
    purposes = visible_purposes(user.roles)
    return {"purposes": [{
        "id": p.id,
        "title": p.title,
        "icon": p.icon,
        "color": p.color,
        "chips": p.chips,
        "description": p.description,
        "panels": p.panels,
    } for p in purposes]}


@router.post("/sessions")
def create_session(body: dict, user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """T-010：创建会话——唯一可写 purpose 的入口（创建期锁定，不可中途变更）。

    入参：{purpose, workspace, title?}
    purpose 非法（未定义）或无权限（角色不可见）→ 403。
    """
    purpose = str(body.get("purpose", "") or "").strip()
    workspace = str(body.get("workspace", "") or "").strip()
    title = str(body.get("title", "") or "").strip()
    if not purpose:
        raise HTTPException(status_code=400, detail="purpose 必填")
    # 用途合法性 + 角色可见性（二次鉴权）
    pdef = load_purpose(purpose)
    if pdef is None:
        raise HTTPException(status_code=403, detail=f"用途不存在或不可见: {purpose}")
    if not (set(user.roles) & set(pdef.roles)):
        raise HTTPException(status_code=403, detail=f"当前角色无权限使用用途: {purpose}")
    # L2 修复：workspace 非法（ValueError → 500）与未授权（绕过 resolve_workspace）
    # 统一前置为 4xx
    if workspace and not user.is_admin:
        from services import user_store as _us
        if not _us.has_grant(user.emp_no, workspace):
            raise HTTPException(status_code=403, detail=f"未授权工作区: {workspace}")
    try:
        sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"非法 workspace: {e}")
    # 创建会话（emp 隔离 + workspace 子目录 + purpose 锁定）
    sid = sm.create(emp_no=user.emp_no, workspace=workspace, purpose=purpose)
    # 索引投影（失败静默）
    try:
        from services import agent_session_store
        agent_session_store.upsert_session(sid, user.emp_no, workspace, purpose, title)
    except Exception:
        pass
    meta = sm.list_sessions()
    created = next((s for s in meta if s["id"] == sid), {})
    return {"ok": True, "session_id": sid, "session": created}


@router.patch("/sessions/{session_id}")
def patch_session(session_id: str, body: dict,
                  workspace: str = "",
                  user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """T-010：改标题/归档；请求体含 purpose → 409（用途创建即锁定）。"""
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    if "purpose" in body:
        raise HTTPException(status_code=409, detail="用途创建即锁定，不可中途变更（换用途 = 新建会话）")
    sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    if not sm.load(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    title = str(body.get("title", "") or "").strip()
    if title:
        sm.update_title(session_id, title)
        try:
            from services import agent_session_store
            agent_session_store.update_title(session_id, title)
        except Exception:
            pass
    return {"ok": True, "session_id": session_id}


@router.get("/sessions")
def list_sessions(workspace: str = "", purpose: str = "", user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """列出会话：本人目录；admin 聚合全部用户目录。支持按工作区/用途筛选。"""
    if user.is_admin:
        sessions = []
        for d in _iter_all_session_dirs():
            for s in _list_sessions_in_dir(d, workspace=workspace):
                s["owner"] = d.name
                sessions.append(s)
        if purpose:
            sessions = [s for s in sessions if s.get("purpose") == purpose]
        return {"sessions": sessions}
    sm_dir = _sessions_dir(user.emp_no)
    sessions = _list_sessions_in_dir(sm_dir, workspace=workspace)
    if purpose:
        sessions = [s for s in sessions if s.get("purpose") == purpose]
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, workspace: str = "", user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """获取会话详情（本人会话；admin 可查全部）。支持工作区子目录。

    M3 修复：product 加入读取权限（多角色扩展遗漏——product 能建会话却读不到自己历史）。
    非 admin 目录限定本人（_sessions_dir(user.emp_no)），天然隔离他人会话。
    """
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
def export_session(session_id: str, workspace: str = "", user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """导出会话为 JSON（元数据 + 消息 + 指标），便于排查问题。M3：product 可导出本人会话。"""
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


@router.post("/cancel/{session_id}")
async def cancel_agent(session_id: str,
                       user: CurrentUser = Depends(require_role("admin", "tester", "product"))):
    """T-402：取消指定会话的当前运行（真打断）。

    设置运行时 cancellation 标志 → 当前轮次 tool 执行完即停止，不再推进下一轮，
    且不再写会话文件。M3：product 新增可取消权；非 admin 归属校验——只能取消自己的会话。
    """
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")

    runtime = _ACTIVE_RUNTIMES.get(session_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="该会话没有活跃的运行")

    # M3：归属校验（_ACTIVE_RUNTIMES 为全局表，不能只靠会话存在性放行）
    if not user.is_admin:
        owner = _find_session_owner(session_id)
        if owner != _sessions_dir(user.emp_no).name:
            raise HTTPException(status_code=403, detail="无权取消他人会话")

    runtime.cancel()
    return {"ok": True, "session_id": session_id, "message": "已请求取消"}


# ══════════════════════════════════════════════════════════
# WebSocket 端点
# ══════════════════════════════════════════════════════════

@router.websocket("/ws")
async def agent_ws(websocket: WebSocket,
                   _user: CurrentUser = Depends(require_role_ws("admin", "tester", "product"))):
    """WebSocket 实时对话（WS 专用角色依赖；token 经 query 参数传入）。

    前端发送：{"message": "用户消息", "session_id": "可选会话ID"}
    后端推送事件：assistant / tool_call / state / done
    """
    await websocket.accept()
    # 连接级用户身份（路由级 require_role 已完成认证，身份经 contextvar 传入）
    from services.auth import current_emp_no
    _ws_emp_no = current_emp_no()
    # T-013: 连接级角色集（白名单装配用；require_role_ws 已认证）
    _ws_roles = list(_user.roles or [])

    # 从查询参数读取工作区并设置上下文（浏览器 WebSocket 不支持自定义 header）
    from specstd.workspace import set_context_workspace, reset_context_workspace
    _ws_query_workspace = websocket.query_params.get("workspace", "")
    # 授权检查：非 admin 用户必须已被授权该工作区
    if _ws_query_workspace and not _user.is_admin:
        from services import user_store as _auth_store
        if not _auth_store.has_grant(_user.emp_no, _ws_query_workspace):
            await websocket.close(code=4403)
            return
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
            purpose = data.get("purpose", "")  # T-010: 新建会话时可选传入用途
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
            # T-010: 新建会话时校验并透传 purpose（非法/无权限 403 语义；已有会话读锁定值）
            session_purpose = purpose or ""
            session_tools_snapshot = None  # M5：已建会话的创建期 tool_whitelist 快照
            if is_new_session and session_purpose:
                pdef = load_purpose(session_purpose)
                if pdef is None or not (set(_ws_roles) & set(pdef.roles)):
                    await websocket.send_json({
                        "type": "error",
                        "message": f"用途不存在或无权限: {session_purpose}",
                    })
                    continue
            elif not is_new_session:
                try:
                    metas = sm.list_sessions()
                    meta = next((s for s in metas if s["id"] == session_id), {})
                    session_purpose = meta.get("purpose", "")
                    # M5：优先取创建期快照（purpose 定义热更新/文件变更不回流已建会话）；
                    # 旧会话无快照时才回退 load_purpose 现解
                    session_tools_snapshot = meta.get("tool_whitelist") or None
                except Exception:
                    session_purpose = ""
                    session_tools_snapshot = None
            sid = session_id or sm.create(emp_no=emp_no, workspace=workspace, purpose=session_purpose)
            llm.set_metrics_file(sessions_dir / (f"{workspace}/" if workspace else "") / f"{sid}_metrics.jsonl")
            # T-010: 会话索引投影（失败静默）
            try:
                from services import agent_session_store
                agent_session_store.upsert_session(sid, emp_no, workspace, session_purpose or "")
            except Exception:
                pass

            # K-015: 同会话并发写防护（另一连接/标签页正在执行同一会话时拒绝）
            if _run_in_progress(sid):
                await websocket.send_json({
                    "type": "error",
                    "message": "该会话正在执行中，请等待当前执行完成（或点击停止后再发送）",
                })
                continue

            await websocket.send_json({"type": "state", "status": "started", "session_id": sid})

            # K-013: @引用处理（先处理，避免后续 system prompt 重建）
            scenario_id, ref_block, structured_refs = _process_references(references, scenario_id)

            # 首字响应优化：发送 preparing 状态让前端即时反馈；
            # system prompt 构建移入子线程——不阻塞事件循环
            # （check_remote_sync 已非阻塞化，本地 IO 为毫秒级）
            await websocket.send_json({"type": "state", "status": "preparing"})

            def _build_prompt(sid_val: str) -> str:
                ctx = _build_scenario_context(sid_val)
                return build_system_prompt(scenario_context=ctx)

            system_prompt = await asyncio.to_thread(_build_prompt, scenario_id)
            # T-011: 三层交集白名单装配——TOOL_REGISTRY ∩ purpose.tools ∩ rbac_visible_tools
            # （meta 工具 todo_write 常驻；全量用户 admin/tester 角色层不额外收窄）
            # M5：已建会话用创建期 tool_whitelist 快照（定义热更新不回流）；
            # 快照缺失（旧会话）才回退 load_purpose 现解
            if session_tools_snapshot is not None:
                purpose_tools = session_tools_snapshot
            else:
                pdef_now = load_purpose(session_purpose) if session_purpose else None
                purpose_tools = list(pdef_now.tools if pdef_now else [])
            whitelist_tools = resolve_tools(
                purpose_tools=purpose_tools,
                user_roles=list(_ws_roles or []),
            )
            # M4：空白名单显式拒绝——绝不能回退全量（原 `or None` 会让空列表
            # 静默变成 ALL_TOOLS，防御纵深被破坏）
            if not whitelist_tools:
                await websocket.send_json({
                    "type": "error",
                    "message": "当前角色无可用的工具白名单（不允许 Agent 运行）",
                })
                continue
            runtime = AgentRuntime(llm, tools=whitelist_tools, max_turns=max_turns)
            ws_message = f"{ref_block}{message}" if ref_block else message

            # V7 修复：事件经 asyncio 队列桥接实时推送（原实现跑完后批量推，无实时性）
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            runtime.events.subscribe(
                lambda e: loop.call_soon_threadsafe(queue.put_nowait, e)
            )

            # T-402: 登记运行时供 cancel 端点查找
            _ACTIVE_RUNTIMES[sid] = runtime
            run_task = asyncio.create_task(
                asyncio.to_thread(runtime.run, system_prompt, ws_message, sm, sid,
                                  structured_refs or None)
            )
            _ACTIVE_RUNS[sid] = run_task  # K-015: 登记活跃 run（并发防护）
            try:
                heartbeat_tick = 0
                while True:
                    if run_task.done() and queue.empty():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.2)
                        await websocket.send_json(event)
                        heartbeat_tick = 0  # 有事件输出，重置心跳
                    except asyncio.TimeoutError:
                        heartbeat_tick += 1
                        if heartbeat_tick >= 50:  # 10 秒无事件（0.2s × 50）
                            # TCP 半开连接防护：定期 heartbeat 保持代理/NAT 不超时断连，
                            # 同时让前端知道后端仍活着；send_json 若失败说明连接已断，异常上抛退出循环
                            await websocket.send_json({"type": "heartbeat"})
                            heartbeat_tick = 0
                        continue
                messages = await run_task  # 运行异常在此抛出，进外层 except
            finally:
                _ACTIVE_RUNS.pop(sid, None)
                _ACTIVE_RUNTIMES.pop(sid, None)

            # 首字响应优化：先推送 done（前端立即解除 loading），标题异步生成后单独推送
            await websocket.send_json({
                "type": "done",
                "session_id": sid,
                "messages": messages,
                "stats": llm.get_stats(),
                "title": "",
            })

            # G4: 新会话标题异步生成（不阻塞 done 事件）
            if is_new_session and messages:
                async def _gen_title():
                    try:
                        title = await asyncio.to_thread(_generate_session_title, llm, messages)
                        if title:
                            sm.update_title(sid, title)
                            await websocket.send_json({
                                "type": "title_update",
                                "session_id": sid,
                                "title": title,
                            })
                    except Exception:
                        pass
                asyncio.create_task(_gen_title())

    except WebSocketDisconnect:
        # T-xxx：WS 断连取消活跃运行（防 ghost run —— LLM/工具继续执行写同一 JSONL 致文件交织损坏）
        if 'run_task' in dir() and run_task and not run_task.done():
            run_task.cancel()
        if 'runtime' in dir() and runtime:
            try:
                runtime.cancel()
            except Exception:
                pass
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
