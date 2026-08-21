"""audit.py — MCP 调用审计查询 REST API（T-082）。

前缀 /api/agent/audit。T-1000：放开「本人查自己」（emp==当前用户非 admin 可用，
越权查他人仍 403）；查他人/全量仍 admin。
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
    """审计记录列表（按 emp/session/tool 过滤，倒序）。

    T-1000：本人查自己放行（未带 emp 时非 admin 自动收窄为本人）；查他人须 admin。
    """
    if not user.is_admin:
        if emp and emp != user.emp_no:
            raise HTTPException(status_code=403, detail=f"无权查看他人审计记录: {emp}")
        emp = user.emp_no  # 未显式指定时收窄为本人（杜绝全量枚举）
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