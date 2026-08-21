"""emp_context — 当前操作人工号的进程级上下文。

原 services/auth.py 的 _CTX_EMP_NO 下沉（T-975）：current_emp_no 是纯
contextvar 读取，无 FastAPI 依赖；auth（会话/SSO）与 mcp_server/agent
工具（作者归属）共同消费，定义在 sg_core 保证双向可达且单一实例。
"""

import contextvars

_CTX_EMP_NO: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sg_ctx_emp_no", default="")


def current_emp_no() -> str:
    """当前请求的操作人工号（未认证/无上下文时为空串）。"""
    return _CTX_EMP_NO.get()
