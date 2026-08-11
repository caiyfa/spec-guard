"""specflow_interview.py — 面试 REST API（T-020，M02）。

前缀 /api/specflow/interviews，挂 RBAC。
冻结/影响面确认为人拍板级动作，仅 product 角色可调。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/specflow/interviews", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])


@router.get("/{iv_id}")
def get_interview(
    iv_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """面试详情：议题卡 + 问题列表 + 门禁状态（按工作区隔离）。"""
    from specflow.interview.topic import load_topic
    from workbench.backend.services.specflow.sf_store import (
        get_interview as db_get_iv, list_questions,
    )
    from workbench.backend.services.specflow.decision_service import db_get_gate

    try:
        topic = load_topic(iv_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not topic:
        raise HTTPException(status_code=404, detail=f"面试不存在: {iv_id}")

    db_iv = db_get_iv(iv_id) or {}
    gate = db_get_gate(iv_id, workspace)
    questions = list_questions(iv_id, workspace=workspace)

    return {
        "iv_id": iv_id,
        "topic": {
            "title": topic.title,
            "initiator": topic.initiator,
            "opened_at": topic.opened_at,
            "source": [s.__dict__ for s in topic.source],
            "target_delta": topic.target_delta,
            "baseline_refs": [r.__dict__ for r in topic.baseline_refs],
            "history_decisions": topic.history_decisions,
            "status": topic.status,
        },
        "db_interview": db_iv,
        "questions": questions,
        "gate": gate,
    }


@router.get("/{iv_id}/questions")
def list_interview_questions(
    iv_id: str,
    status: str = "",
    priority: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """问题列表（按工作区隔离）。"""
    from workbench.backend.services.specflow.sf_store import list_questions
    return {"questions": list_questions(iv_id, status, priority, workspace=workspace)}


@router.post("/{iv_id}/questions/{q_id}/answer")
def record_answer(
    iv_id: str,
    q_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """记录产品回答 + 追加面试流水。

    归属校验：q_id 必须属于当前 iv_id（防跨面试覆盖回答）。
    """
    from workbench.backend.services.specflow.sf_store import update_answer, get_question
    from workbench.backend.services.specflow.interview_service import record_transcript

    q = get_question(q_id)
    if not q or q["iv_id"] != iv_id or q.get("workspace", "") != workspace:
        raise HTTPException(status_code=404, detail=f"问题不存在: {q_id}")

    answer = body.get("answer", "")
    decision_ref = body.get("decision_ref", "")

    ok = update_answer(q_id, answer, decision_ref)
    if not ok:
        raise HTTPException(status_code=404, detail=f"问题不存在: {q_id}")

    record_transcript(iv_id, "product", answer, q_ref=q_id)
    return {"question": get_question(q_id)}


@router.post("/{iv_id}/impact-confirm")
def confirm_impact(
    iv_id: str,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """P0 影响面人工确认（人拍板级动作，仅 product 角色）。"""
    from workbench.backend.services.specflow.interview_service import confirm_impact as ci

    result = ci(
        iv_id=iv_id,
        actor=user.emp_no,
        affected_frs=body.get("affected_frs"),
        snapshot_path=body.get("snapshot_path", ""),
        workspace=workspace,
    )
    return {"evidence": result}


@router.get("/{iv_id}/gate")
def get_gate(
    iv_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """冻结门禁聚合（确定性，按工作区隔离）。"""
    from workbench.backend.services.specflow.decision_service import db_get_gate
    return {"gate": db_get_gate(iv_id, workspace)}


@router.post("/{iv_id}/freeze")
def freeze_interview(
    iv_id: str,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """申请冻结：门禁全绿才放行，否则 409 + 缺口清单（仅 product 角色）。

    状态机推进：interviewing → p0_cleared（门禁已过，自动推进）→ frozen；
    终态/异常状态一律 409，不产生 500。
    """
    from workbench.backend.services.specflow.decision_service import db_get_gate
    from specflow.interview.iv_lifecycle import transition_status
    from specflow.interview.gate import validate_freeze_request, GateResult
    from specstd.workspace import specflow_dir
    from specflow.interview.topic import load_topic
    from specflow.interview.decision_ledger import export_ledger

    # 先校验面试存在（404 优先于门禁 409，避免不存在的面试被当清零放行）
    sf_base = specflow_dir()
    try:
        topic = load_topic(iv_id, sf_base)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not topic:
        raise HTTPException(status_code=404, detail=f"面试不存在: {iv_id}")

    gate = db_get_gate(iv_id, workspace)
    gr = GateResult(**gate)
    error = validate_freeze_request(gr)
    if error:
        raise HTTPException(status_code=409, detail=error)

    # 状态机推进（确定性校验，非法流转 409 而非 500）
    try:
        if topic.status == "interviewing":
            # 门禁已全绿：自动推进 p0_cleared 中间态（面试→清零→冻结全链）
            transition_status(topic.status, "p0_cleared")
            topic.status = "p0_cleared"
        if topic.status == "p0_cleared":
            transition_status(topic.status, "frozen")
            topic.status = "frozen"
        else:
            raise HTTPException(
                status_code=409,
                detail=f"当前状态 {topic.status} 不可冻结（终态/未开标）")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    topic.write(sf_base / "interviews" / topic.iv_id)

    from workbench.backend.services.specflow.sf_store import update_interview_status
    update_interview_status(iv_id, "frozen")

    # 导出台账快照（按工作区隔离）
    ledger = export_ledger(_get_conn(), iv_id, workspace)
    import yaml
    decisions_dir = sf_base / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / f"{iv_id}.ledger.yaml").write_text(
        yaml.dump(ledger, allow_unicode=True, indent=2, sort_keys=False),
        encoding="utf-8",
    )

    return {"iv_id": iv_id, "status": "frozen", "gate": gate}


def _get_conn():
    from workbench.backend.services.specflow.sf_store import _connect
    return _connect()
