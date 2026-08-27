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


# ── 运行时作用域（T-1032 父会话脉络感知）──
# runtime.run() 开头解析一次完整会话身份，_execute_tool 与 set_session_id 同点
# 注入；parent 等工具据此做门卫（仅辅助会话可用/只读本链接父会话）与路径定位。
# MCP stdio / 纯 API 无会话语境为 None → 工具诚实拒绝。
_CTX_RUNTIME_SCOPE: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "sg_runtime_scope", default=None)


def set_runtime_scope(scope: dict | None):
    return _CTX_RUNTIME_SCOPE.set(scope or None)


def reset_runtime_scope(token):
    _CTX_RUNTIME_SCOPE.reset(token)


def get_runtime_scope() -> dict | None:
    """当前运行时作用域快照。

    约定键：sid / kind / purpose / parent_sid / title /
    sessions_dir(str, SessionManager.sessions_dir)。
    """
    return _CTX_RUNTIME_SCOPE.get()
