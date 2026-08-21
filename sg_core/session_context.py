"""session_context — 当前 Agent 会话 ID 的进程级上下文（T-1000）。

与 emp_context 同构：agent runtime 执行 MCP 工具时注入，写路径钩子
（product_index.record_product）读取，把产物反挂到产出会话。
MCP stdio / 纯 API 写路径无会话概念，读取为空串（诚实留空）。
"""

import contextvars

_CTX_SESSION_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sg_ctx_session_id", default="")


def current_session_id() -> str:
    """当前工具调用的产出会话 ID（无会话上下文时为空串）。"""
    return _CTX_SESSION_ID.get()


def set_session_id(session_id: str):
    return _CTX_SESSION_ID.set(session_id or "")


def reset_session_id(token):
    _CTX_SESSION_ID.reset(token)
