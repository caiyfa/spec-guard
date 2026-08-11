"""audit.py — MCP 调用审计查询 REST API（T-082）。

前缀 /api/agent/audit，仅 admin 可查（审计日志敏感）。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_role

router = APIRouter(prefix="/api/agent/audit", tags=["agent"],
                   dependencies=[Depends(get_current_user)])


@router.get("")
def list_audit(
    emp: str = "",
    session: str = "",
    tool: str = "",
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    """审计记录列表（按 emp/session/tool 过滤，倒序）。仅 admin 可查。"""
    require_role(user, "admin")
    from services.audit_store import query_calls
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    return {
        "calls": query_calls(
            emp_no=emp, session_id=session, tool_name=tool,
            limit=limit, offset=offset,
        ),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{call_id}")
def get_audit_call(
    call_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    """单条审计详情。仅 admin 可查。"""
    require_role(user, "admin")
    from services.audit_store import get_call
    record = get_call(call_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"审计记录不存在: {call_id}")
    return {"call": record}