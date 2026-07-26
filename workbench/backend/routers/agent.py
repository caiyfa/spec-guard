"""Agent 对话 API：WebSocket 实时对话 + 会话管理。

事件流三类型齐全：assistant / tool_call+tool_result / state。
"""

import asyncio
import sys
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter(prefix="/api/agent", tags=["agent"])

# 确保仓库根在 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.llm_client import LLMClient
from agent.session import SessionManager
from agent.runtime import AgentRuntime, build_system_prompt

SESSIONS_DIR = SG_ROOT / "agent" / "sessions"


# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════

@router.get("/sessions")
def list_sessions():
    """列出全部会话。"""
    sm = SessionManager(SESSIONS_DIR)
    return {"sessions": sm.list_sessions()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    """获取会话详情。"""
    sm = SessionManager(SESSIONS_DIR)
    messages = sm.load(session_id)
    if messages is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": messages}


class ChatBody(BaseModel):
    message: str
    session_id: str = ""
    max_turns: int = 12


@router.post("/chat")
async def chat(body: ChatBody):
    """同步对话（非 WebSocket，适合短交互）。"""
    llm = LLMClient()
    sm = SessionManager(SESSIONS_DIR)
    sid = body.session_id or sm.create()
    llm.set_metrics_file(SESSIONS_DIR / f"{sid}_metrics.jsonl")

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
async def agent_ws(websocket: WebSocket):
    """WebSocket 实时对话。

    前端发送：{"message": "用户消息", "session_id": "可选会话ID"}
    后端推送事件：assistant / tool_call / state / done
    """
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            session_id = data.get("session_id", "")
            max_turns = data.get("max_turns", 12)

            if not message:
                await websocket.send_json({"type": "error", "message": "缺少 message 参数"})
                continue

            # 初始化
            llm = LLMClient()
            sm = SessionManager(SESSIONS_DIR)
            sid = session_id or sm.create()
            llm.set_metrics_file(SESSIONS_DIR / f"{sid}_metrics.jsonl")

            await websocket.send_json({"type": "state", "status": "started", "session_id": sid})

            # 构建 system prompt
            system_prompt = build_system_prompt()
            runtime = AgentRuntime(llm, max_turns=max_turns)

            # 在线程中运行 agent，收集事件后推送
            events = []
            runtime.events.subscribe(lambda e: events.append(e))

            messages = await asyncio.to_thread(
                runtime.run, system_prompt, message, sm, sid
            )

            # 推送所有事件
            for event in events:
                await websocket.send_json(event)

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
