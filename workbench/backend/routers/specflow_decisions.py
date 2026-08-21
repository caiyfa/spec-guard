"""specflow_decisions.py — 决策台账 REST API（T-023，M04）。

前缀 /api/specflow/decisions，挂 RBAC。
resolve/amend/confirm 写操作不暴露 MCP，仅 UI/REST 通道（人拍板闸门）。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/specflow/decisions", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])


@router.get("")
def list_decisions(
    interview_id: str = "",
    status: str = "",
    priority: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """决策台账列表（按工作区隔离）。"""
    from workbench.backend.services.specflow.decision_service import db_list_decisions
    decisions = db_list_decisions(
        interview_id=interview_id, status=status,
        priority=priority, workspace=workspace)
    return {"decisions": decisions}


@router.post("")
def propose_decision(
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """登记决策候选（Agent/人登记，永远 pending 出生）。"""
    from workbench.backend.services.specflow.decision_service import db_propose_decision
    dec = db_propose_decision(
        workspace=workspace,
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
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """人拍板确认决策（闸门：仅 product 角色可调）。"""
    from specflow.interview.decision_ledger import get_decision
    from workbench.backend.services.specflow.decision_service import db_resolve_decision
    from workbench.backend.services.specflow.sf_store import _connect

    conn = _connect()
    try:
        dec = get_decision(conn, d_id)
    finally:
        conn.close()
    if not dec:
        raise HTTPException(status_code=404, detail=f"决策不存在: {d_id}")
    if dec["workspace"] != workspace:
        raise HTTPException(status_code=404, detail=f"决策不存在: {d_id}")

    resolution = body.get("resolution", "")
    if not resolution:
        raise HTTPException(status_code=400, detail="resolution 不能为空")

    try:
        resolved = db_resolve_decision(d_id, resolution, user.emp_no)
        return {"decision": resolved}
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
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """增补决策（生成新 D-xxx，原条目标 superseded 只读）。"""
    from specflow.interview.decision_ledger import get_decision
    from workbench.backend.services.specflow.decision_service import db_amend_decision
    from workbench.backend.services.specflow.sf_store import _connect

    conn = _connect()
    try:
        dec = get_decision(conn, d_id)
    finally:
        conn.close()
    if not dec or dec["workspace"] != workspace:
        raise HTTPException(status_code=404, detail=f"决策不存在: {d_id}")

    try:
        result = db_amend_decision(
            d_id=d_id,
            new_priority=body["new_decision"]["priority"],
            new_question=body["new_decision"]["question"],
            new_resolution=body["new_decision"]["resolution"],
            reason=body.get("reason", ""),
            created_by=user.emp_no,
            workspace=workspace,
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
    workspace: str = Depends(resolve_workspace),
):
    """P0 清零门禁聚合（M05 第③闸调用，按工作区隔离）。"""
    from workbench.backend.services.specflow.decision_service import db_get_gate
    return {"gate": db_get_gate(interview_id, workspace)}


@router.post("/gate/impact-confirm")
def confirm_impact(
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """影响面人工确认（人拍板级动作，仅 product 角色）。"""
    from workbench.backend.services.specflow.decision_service import db_confirm_impact
    result = db_confirm_impact(
        workspace=workspace,
        interview_id=body["interview_id"],
        actor=user.emp_no,
        affected_frs=body.get("affected_frs"),
        snapshot_path=body.get("snapshot_path", ""),
    )
    return {"evidence": result}


# ── 评分端点（置于 /{d_id} 之前注册，避免路径遮蔽）──

@router.get("/scores")
def list_scores(
    interview_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """五维评分列表（按工作区隔离）。"""
    from workbench.backend.services.specflow.decision_service import db_list_scores
    return db_list_scores(interview_id, workspace)


@router.post("/scores/evaluate")
def evaluate_scores(
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """触发机打维度采集 + LLM 预打分，返回 suggested 集合（幂等）。

    机打维度由 specflow.anchor.scoring 的真实采集器驱动
    （11 章齐全性/边界异常比对器/覆盖率映射），替换了 S2 的占位常量。
    """
    from workbench.backend.services.specflow.decision_service import db_add_score
    from specflow.anchor.scoring import collect_all_machine_dimensions
    interview_id = body["interview_id"]
    spec_sha = body.get("spec_sha", "")
    spec_text = body.get("spec_text", "")

    results = []
    # 机打维度：真实采集器替换占位常量
    machine_dims = collect_all_machine_dimensions(str(spec_text or ""))
    for dim, score, evidence in machine_dims:
        r = db_add_score(workspace, interview_id, dim, score, "machine",
                         evidence, spec_sha, skip_if_suggested=True)
        results.append(r)

    # T-964：clarity 假分数清理——不再硬编码 62.0 占位入库，诚实降级为「待人工评分」
    results.append({"id": None, "dimension": "clarity", "score": None,
                    "source": "llm_suggested", "status": "pending_manual",
                    "note": "clarity 无机打/LLM 真评通道，待 QA 人工评分后入库"})

    return {"scores": results}


@router.post("/scores/{score_id}/confirm")
def confirm_score(
    score_id: int,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """QA/产品确认或驳回评分（status=suggested → confirmed/rejected，闸门）。"""
    from workbench.backend.services.specflow.decision_service import db_confirm_score
    verdict = body.get("verdict", "")
    if verdict not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="verdict 必须为 confirm/reject")
    try:
        updated = db_confirm_score(score_id, verdict, user.emp_no, workspace=workspace)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"score": updated}


@router.get("/{d_id}")
def get_decision_by_id(
    d_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """按 D-xxx 查询决策（按工作区隔离）。"""
    from specflow.interview.decision_ledger import get_decision
    from workbench.backend.services.specflow.sf_store import _connect
    conn = _connect()
    try:
        dec = get_decision(conn, d_id)
    finally:
        conn.close()
    if not dec or dec["workspace"] != workspace:
        raise HTTPException(status_code=404, detail=f"决策不存在: {d_id}")
    return {"decision": dec}
