"""zentao.py — 禅道集成 REST API（M06 §5.2，T-053/T-054/T-055）。

前缀 /api/zentao，挂 RBAC + X-SG-Workspace 透传。

写动作闸门：
- 建故事：仅 product（冻结 delta 是唯一输入，未冻结 403）
- 故事点回写：仅 product（estimate 必须已 confirmed）
- 提 BUG 双入口：product/tester（入口① 要求 verdict=FAIL，SKIP/BLOCKED 被拒）
- 锚点登记：product/tester（仅登记引用，不触禅道）
story/bug 创建与回写不暴露 MCP（铁律 1：Agent 只建议，人拍板）。
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/zentao", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])

# SPQ 台账文件根（_mark_spq_filed 用；测试可 monkeypatch）
SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _sf_store():
    from workbench.backend.services.specflow import sf_refs_store
    return sf_refs_store


# ══════════════════════════════════════════════════════════
# 故事创建与故事点评估（T-053/T-054）
# ══════════════════════════════════════════════════════════

@router.post("/stories")
def create_story(
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """从冻结 delta 创建禅道故事（未冻结 403）。"""
    from workbench.backend.services.zentao import client as zt_client
    delta_id = body.get("delta_id", "")
    title = body.get("title", "")
    try:
        job = zt_client.create_story_job(
            workspace, delta_id, title, user.emp_no)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"job": job}


@router.get("/frozen-deltas")
def list_frozen_deltas(
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """列出已冻结 delta（一键建故事下拉数据源）。"""
    from workbench.backend.services.zentao import client as zt_client
    return {"deltas": zt_client.list_frozen_deltas()}


@router.post("/stories/from-draft")
def create_story_from_draft(
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """对话草案建故事（product 人拍板；草案必须 draft 态，幂等防重）。"""
    from workbench.backend.services.zentao import client as zt_client
    draft_id = body.get("draft_id")
    if not draft_id:
        raise HTTPException(status_code=400, detail="缺少 draft_id")
    try:
        job = zt_client.create_story_from_draft_job(
            workspace, int(draft_id), user.emp_no)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"job": job}


@router.get("/story-drafts")
def list_story_drafts(
    status: str = "",
    session_id: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """故事草案列表（对话产出待确认）。"""
    return {"drafts": _sf_store().list_story_drafts(
        workspace=workspace, status=status, session_id=session_id)}


@router.post("/story-drafts/{draft_id}/cancel")
def cancel_story_draft(
    draft_id: int,
    user: CurrentUser = Depends(require_role("product", "tester")),
    workspace: str = Depends(resolve_workspace),
):
    """取消草案（draft → cancelled，不触禅道）。"""
    if not _sf_store().cancel_story_draft(draft_id):
        raise HTTPException(status_code=403, detail=f"草案 {draft_id} 无法取消（不存在或已非 draft）")
    return {"ok": True, "draft_id": draft_id}


@router.post("/stories/{story_id}/estimate-points")
def estimate_points(
    story_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """故事点评估（skill 建议，恒 suggested 出生，不计入任何闸门）。"""
    from workbench.backend.services.zentao import estimator
    delta_id = body.get("delta_id", "")
    try:
        estimate = estimator.estimate_points(
            workspace, delta_id, story_id=story_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"estimate": estimate}


@router.post("/stories/{story_id}/writeback-points")
def writeback_points(
    story_id: str,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """故事点回写禅道（仅 product；estimate 必须已 confirmed）。"""
    from workbench.backend.services.zentao import client as zt_client
    estimate_id = body.get("estimate_id")
    if not estimate_id:
        raise HTTPException(status_code=400, detail="缺少 estimate_id")
    try:
        job = zt_client.writeback_points_job(workspace, int(estimate_id),
                                             user.emp_no)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"job": job}


@router.get("/estimates")
def list_estimates(
    delta_id: str = "",
    status: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """故事点评估记录列表。"""
    return {"estimates": _sf_store().list_estimates(
        workspace=workspace, delta_id=delta_id, status=status)}


@router.post("/estimates/{estimate_id}/confirm")
def confirm_estimate(
    estimate_id: int,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """产品确认/驳回评估（confirm 仅 product；驳回 product/tester）。"""
    from workbench.backend.services.zentao import estimator
    verdict = body.get("verdict", "")
    if verdict not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="verdict 必须为 confirm/reject")
    try:
        if verdict == "confirm":
            updated = estimator.confirm_estimate(estimate_id, user.emp_no)
        else:
            updated = estimator.reject_estimate(estimate_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"estimate": updated}


# ══════════════════════════════════════════════════════════
# 提 BUG 双入口（T-055）
# ══════════════════════════════════════════════════════════

@router.post("/bugs/from-run")
def create_bug_from_run(
    body: dict,
    user: CurrentUser = Depends(require_role("product", "tester")),
    workspace: str = Depends(resolve_workspace),
):
    """入口①：DAG 执行 FAIL 归因后一键提单（SKIP/BLOCKED 被拒）。"""
    from workbench.backend.services.zentao import client as zt_client
    run_id = body.get("run_id", "")
    scenario_id = body.get("scenario_id", "")
    severity = body.get("severity", 3)
    title = body.get("title", "")
    spq_id = body.get("spq_id", "")
    story_id = body.get("story_id", "")
    if not run_id or not scenario_id:
        raise HTTPException(status_code=400, detail="run_id 与 scenario_id 必填")
    try:
        job = zt_client.create_bug_from_run_job(
            workspace, run_id, scenario_id, severity, title, user.emp_no,
            spq_id=spq_id, story_id=story_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    # 提单成功且带 SPQ → 状态推进 zentao_filed（M06 §4.3 双向链接）
    if job.get("status") == "succeeded" and spq_id:
        _mark_spq_filed(spq_id)
    return {"job": job}


@router.post("/bugs/manual")
def create_bug_manual(
    body: dict,
    user: CurrentUser = Depends(require_role("product", "tester")),
    workspace: str = Depends(resolve_workspace),
):
    """入口②：手工录入复现步骤，同一作业/幂等/登记管线。"""
    from workbench.backend.services.zentao import client as zt_client
    title = body.get("title", "")
    steps = body.get("steps", "")
    severity = body.get("severity", 3)
    story_id = body.get("story_id", "")
    fr_ref = body.get("fr_ref", "")
    idem_key = body.get("idem_key", "")
    try:
        job = zt_client.create_bug_manual_job(
            workspace, title, steps, severity, user.emp_no,
            story_id=story_id, fr_ref=fr_ref, idem_key=idem_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"job": job}


@router.get("/bugs/{bug_id}/poll")
def poll_bug(
    bug_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """禅道 BUG 状态回查（纯读；resolved/closed → 回归建议）。"""
    from workbench.backend.services.zentao import client as zt_client
    try:
        return zt_client.poll_bug(workspace, bug_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"禅道回查失败: {e}")


# ══════════════════════════════════════════════════════════
# 作业与外部锚点（T-056）
# ══════════════════════════════════════════════════════════

@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """作业状态 + 终端回显（审计/幂等重入查看）。"""
    job = _sf_store().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"作业不存在: {job_id}")
    if job.get("workspace") and job["workspace"] != workspace:
        raise HTTPException(status_code=404, detail=f"作业不存在: {job_id}")
    return {"job": job}


@router.get("/jobs")
def list_jobs(
    kind: str = "",
    status: str = "",
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """作业列表（面板最近作业/审计）。"""
    jobs = _sf_store().list_jobs(workspace=workspace, kind=kind,
                                 status=status)
    return {"jobs": jobs[:limit]}


@router.get("/refs")
def list_refs(
    ref_type: str = "",
    ref: str = "",
    linked_type: str = "",
    linked: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """外部锚点列表（血缘链/面板数据源，M10 同表同源）。"""
    return {"refs": _sf_store().list_refs(
        workspace=workspace, ref_type=ref_type, ref=ref,
        linked_type=linked_type, linked=linked)}


@router.post("/refs")
def register_ref(
    body: dict,
    user: CurrentUser = Depends(require_role("product", "tester")),
    workspace: str = Depends(resolve_workspace),
):
    """手工登记外部资产引用（PR/单测等；仅登记，不触禅道）。"""
    ref_type = body.get("type", "")
    ref = body.get("ref", "")
    linked_type = body.get("linked_type", "")
    linked = body.get("linked", "")
    note = body.get("note", "")
    ref_url = body.get("ref_url", "")
    try:
        row = _sf_store().register_ref(
            workspace, ref_type, ref, linked_type, linked,
            ref_url=ref_url, note=note, registered_by=user.emp_no)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ref": row}


@router.post("/jobs/reconcile")
def reconcile(
    user: CurrentUser = Depends(require_role("admin")),
    workspace: str = Depends(resolve_workspace),
):
    """对账：succeeded 但缺锚点登记的作业补登记（崩溃窗口补账）。"""
    from workbench.backend.services.zentao import client as zt_client
    return {"fixed": zt_client.reconcile_refs(workspace)}


def _mark_spq_filed(spq_id: str, ledger_root: Path | None = None):
    """SPQ 状态推进 zentao_filed（已提禅道 BUG，M06 §4.3）。"""
    from feedback.ledger import FeedbackLedger
    root = ledger_root or SG_ROOT
    ledger = FeedbackLedger(root / "feedback" / "ledger.json")
    try:
        ledger.transition(spq_id, "zentao_filed")
    except (KeyError, ValueError):
        # SPQ 不存在或状态非法：不阻断提单主链路，登记侧由 sf_external_refs 兜底
        pass
