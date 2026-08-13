"""specflow_gate_dock.py — 对话操作台（GateDock）只读汇总 API（一期）。

前缀 /api/specflow/gate-dock，挂 RBAC。
按 session_id / interview_id 反查当前面试上下文，聚合待办闸门卡片，
供 AgentChat「操作台」页签渲染（二期供 Agent 推卡共用数据源）。

铁律：本端点纯读、零写副作用；闸门写操作仍走原面板 REST（人拍板）。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, resolve_workspace

router = APIRouter(prefix="/api/specflow/gate-dock", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])


@router.get("")
def gate_dock(
    session_id: str = "",
    interview_id: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """当前上下文待办闸门汇总（纯读）。

    优先 interview_id 直查；否则 session_id 反查（sf_interviews 按
    UNIQUE(workspace, session_id) 绑定 Agent 会话）。两者皆无 → 400；
    会话未绑定面试 → 200 空卡片（前端显示空态引导，不算错误）。
    """
    from workbench.backend.services.specflow import sf_store
    from workbench.backend.services.specflow.gate_dock_service import (
        build_gate_dock)

    if not interview_id and not session_id:
        raise HTTPException(
            status_code=400, detail="session_id 与 interview_id 至少传一个")

    iv = None
    if interview_id:
        iv = sf_store.get_interview(interview_id)
        if not iv or iv.get("workspace") != workspace:
            raise HTTPException(status_code=404, detail=f"面试不存在: {interview_id}")
    else:
        rows = sf_store.list_interviews_db(
            workspace=workspace, session_id=session_id)
        iv = rows[0] if rows else None

    if not iv:
        return {"interview": None, "cards": []}

    return build_gate_dock(workspace, iv)
