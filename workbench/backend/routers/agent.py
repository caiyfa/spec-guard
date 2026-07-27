"""Agent 对话 API：WebSocket 实时对话 + 会话管理。

事件流三类型齐全：assistant / tool_call+tool_result / state。
"""

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

SESSIONS_ROOT = SG_ROOT / "agent" / "sessions"


def _sessions_dir(emp_no: str) -> Path:
    """按用户隔离的会话目录（M7）：agent/sessions/{emp_no}/。"""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", emp_no or "_anonymous")
    return SESSIONS_ROOT / safe


def _iter_all_session_dirs() -> list[Path]:
    """全部用户会话目录（admin 视图）。"""
    if not SESSIONS_ROOT.is_dir():
        return []
    return [d for d in sorted(SESSIONS_ROOT.iterdir()) if d.is_dir() and not d.name.startswith("_")]


# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════

@router.get("/sessions")
def list_sessions(user: CurrentUser = Depends(require_role("admin", "tester"))):
    """列出会话：本人目录；admin 聚合全部用户目录。"""
    if user.is_admin:
        sessions = []
        for d in _iter_all_session_dirs():
            for s in SessionManager(d).list_sessions():
                s["owner"] = d.name
                sessions.append(s)
        return {"sessions": sessions}
    sm = SessionManager(_sessions_dir(user.emp_no))
    return {"sessions": sm.list_sessions()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: CurrentUser = Depends(require_role("admin", "tester"))):
    """获取会话详情（本人会话；admin 可查全部）。"""
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    dirs = _iter_all_session_dirs() if user.is_admin else [_sessions_dir(user.emp_no)]
    for d in dirs:
        messages = SessionManager(d).load(session_id)
        if messages is not None:
            return {"session_id": session_id, "messages": messages, "owner": d.name}
    raise HTTPException(status_code=404, detail="会话不存在")


class ChatBody(BaseModel):
    message: str
    session_id: str = ""
    max_turns: int = 12


@router.post("/chat")
async def chat(body: ChatBody, user: CurrentUser = Depends(require_role("admin", "tester"))):
    """同步对话（非 WebSocket，适合短交互）。"""
    if body.session_id:
        try:
            _validate_session_id(body.session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法 session_id")
    llm = LLMClient()
    sessions_dir = _sessions_dir(user.emp_no)
    sm = SessionManager(sessions_dir)
    sid = body.session_id or sm.create()
    llm.set_metrics_file(sessions_dir / f"{sid}_metrics.jsonl")

    system_prompt = build_system_prompt()
    runtime = AgentRuntime(llm, max_turns=body.max_turns)

    events = []
    runtime.events.subscribe(lambda e: events.append(e))

    messages = await asyncio.to_thread(
        runtime.run, system_prompt, body.message, sm, sid
    )

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

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            session_id = data.get("session_id", "")
            max_turns = data.get("max_turns", 12)

            if not message:
                await websocket.send_json({"type": "error", "message": "缺少 message 参数"})
                continue
            if session_id:
                try:
                    _validate_session_id(session_id)
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "非法 session_id"})
                    continue

            # 初始化（会话按用户隔离）
            emp_no = _ws_emp_no or "_anonymous"
            llm = LLMClient()
            sessions_dir = _sessions_dir(emp_no)
            sm = SessionManager(sessions_dir)
            sid = session_id or sm.create()
            llm.set_metrics_file(sessions_dir / f"{sid}_metrics.jsonl")

            await websocket.send_json({"type": "state", "status": "started", "session_id": sid})

            # 构建 system prompt
            system_prompt = build_system_prompt()
            runtime = AgentRuntime(llm, max_turns=max_turns)

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

            # 推送完成
            await websocket.send_json({
                "type": "done",
                "session_id": sid,
                "messages": messages,
                "stats": llm.get_stats(),
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
