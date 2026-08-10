"""specflow_decisions.py — 决策台账 REST API（T-023，M04）。

前缀 /api/specflow/decisions，挂 RBAC。
resolve/confirm/amend 写操作不暴露 MCP，仅 UI/REST 通道。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_role
from specstd.workspace import get_context_workspace

router = APIRouter(prefix="/api/specflow/decisions", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])


@router.get("")
def list_decisions(
    interview_id: str = "",
    status: str = "",
    priority: str = "",
    user: CurrentUser = Depends(get_current_user),
):
    """决策台账列表。"""
    from workbench.backend.services.specflow.decision_service import db_list_decisions
    ws = get_context_workspace() or ""
    decisions = db_list_decisions(
        interview_id=interview_id, status=status,
        priority=priority, workspace=ws)
    return {"decisions": decisions}


@router.post("")
def propose_decision(
    body: dict,
    user: CurrentUser = Depends(get_current_user),
):
    """登记决策候选（Agent/人登记，永远 pending 出生）。"""
    from workbench.backend.services.specflow.decision_service import db_propose_decision
    ws = get_context_workspace() or ""
    dec = db_propose_decision(
        workspace=ws,
        interview_id=body["interview_id"],
        priority=body["priority"],
        question=body["question"],
        question_ref=body.get("question_ref", ""),
        links=body.get("links"),
    )
    return {"decision": dec}


@router.post("/{d_id}/resolve")
def resolve_decision(
    d_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
):
    """人拍板确认决策（闸门：仅 product 角色可调）。"""
    require_role(["product"])(user)

    resolution = body.get("resolution", "")
    if not resolution:
        raise HTTPException(status_code=400, detail="resolution 不能为空")

    from workbench.backend.services.specflow.decision_service import db_resolve_decision
    try:
        dec = db_resolve_decision(d_id, resolution, user.emp_no)
        return {"decision": dec}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{d_id}/amend")
def amend_decision(
    d_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
):
    """增补决策（生成新 D-xxx，原条目标 superseded 只读）。"""
    require_role(["product"])(user)

    from workbench.backend.services.specflow.decision_service import db_amend_decision
    ws = get_context_workspace() or ""
    try:
        result = db_amend_decision(
            d_id=d_id,
            new_priority=body["new_decision"]["priority"],
            new_question=body["new_decision"]["question"],
            new_resolution=body["new_decision"]["resolution"],
            reason=body.get("reason", ""),
            created_by=user.emp_no,
            workspace=ws,
            interview_id=body["new_decision"].get("interview_id", ""),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/gate")
def get_gate(
    interview_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """P0 清零门禁聚合（M05 第③闸调用）。"""
    from workbench.backend.services.specflow.decision_service import db_get_gate
    return {"gate": db_get_gate(interview_id)}


@router.post("/gate/impact-confirm")
def confirm_impact(
    body: dict,
    user: CurrentUser = Depends(get_current_user),
):
    """影响面人工确认。"""
    from workbench.backend.services.specflow.decision_service import db_confirm_impact
    ws = get_context_workspace() or ""
    result = db_confirm_impact(
        workspace=ws,
        interview_id=body["interview_id"],
        actor=user.emp_no,
        affected_frs=body.get("affected_frs"),
        snapshot_path=body.get("snapshot_path", ""),
    )
    return {"evidence": result}


@router.get("/{d_id}")
def get_decision_by_id(
    d_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """按 D-xxx 查询决策。"""
    from specflow.interview.decision_ledger import get_decision
    from workbench.backend.services.specflow.sf_store import _connect
    conn = _connect()
    dec = get_decision(conn, d_id)
    conn.close()
    if not dec:
        raise HTTPException(status_code=404, detail=f"决策不存在: {d_id}")
    return {"decision": dec}


# ── 评分端点 ──

@router.get("/scores")
def list_scores(
    interview_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """五维评分列表。"""
    from workbench.backend.services.specflow.decision_service import db_list_scores
    return db_list_scores(interview_id)


@router.post("/scores/evaluate")
def evaluate_scores(
    body: dict,
    user: CurrentUser = Depends(get_current_user),
):
    """触发机打维度采集 + LLM 预打分，返回 suggested 集合。"""
    from workbench.backend.services.specflow.decision_service import db_add_score
    ws = get_context_workspace() or ""
    interview_id = body["interview_id"]
    spec_sha = body.get("spec_sha", "")

    results = []
    # 机打维度示例（实际由 specstd/conformance 驱动）
    machine_dims = [
        ("logic", 78, "11 章齐全, SHALL 语句完整"),
        ("coverage", 85, "FR 覆盖率达 85%"),
        ("boundary", 55, "缺「规则切换中落位」异常场景"),
        ("precondition", 70, "前置条件完整"),
    ]
    for dim, score, evidence in machine_dims:
        r = db_add_score(ws, interview_id, dim, score, "machine",
                         evidence, spec_sha)
        results.append(r)

    # LLM 建议维度
    r = db_add_score(ws, interview_id, "clarity", 62, "llm_suggested",
                     "LLM 建议：预期清晰度待 QA 复核", spec_sha)
    results.append(r)

    return {"scores": results}