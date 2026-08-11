"""specflow_freeze.py — 冻结三闸 REST API（M05，T-042）。

前缀 /api/specflow/freeze，挂 RBAC。
冻结/归档/闸① 写操作仅 product 角色可调。
闸② 合规校验调 specstd/conformance 确定性纯读。
闸③ P0 清零转发 M04 gate API。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/specflow/freeze", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])


@router.post("/changes/{delta_id}/gates/1-product-confirm")
def gate1_product_confirm(
    delta_id: str,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """闸① 产品确认（仅 product 角色）。"""
    from workbench.backend.services.specflow.freeze_gate import product_confirm
    interview_id = body.get("interview_id", "")
    result = product_confirm(
        delta_id, workspace, user.emp_no, interview_id=interview_id)
    return result


@router.post("/changes/{delta_id}/gates/2-conformance")
def gate2_conformance(
    delta_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """闸② specstd 合规校验（确定性，纯读）。"""
    from workbench.backend.services.specflow.freeze_gate import conformance_check
    spec_text = body.get("spec_text", "")
    result = conformance_check(workspace, delta_id, spec_text)
    return result


@router.get("/changes/{delta_id}/gates")
def get_all_gates(
    delta_id: str,
    interview_id: str = "",
    spec_text: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """三闸全量状态聚合。"""
    from workbench.backend.services.specflow.freeze_gate import check_all_gates
    return check_all_gates(workspace, interview_id, delta_id, spec_text)


@router.post("/changes/{delta_id}/freeze")
def freeze_delta(
    delta_id: str,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """执行冻结（三闸全 pass 才放行，否则 409）。"""
    from workbench.backend.services.specflow.freeze_gate import freeze_delta as _freeze
    interview_id = body.get("interview_id", "")
    spec_sha = body.get("spec_sha", "")
    spec_text = body.get("spec_text", "")
    result = _freeze(
        workspace, interview_id, delta_id,
        spec_sha=spec_sha, frozen_by=user.emp_no,
        spec_text=spec_text)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/changes/{delta_id}/archive")
def archive_delta(
    delta_id: str,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """归档 delta（product 角色，冻结后可归档）。"""
    from workbench.backend.services.specflow.freeze_gate import archive_delta as _archive
    result = _archive(workspace, delta_id, archive_by=user.emp_no)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/changes/{delta_id}/export")
def export_delta_pack(
    delta_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """导出 delta 交付包（proposal.md + delta-spec.md + manifest）。"""
    from specstd.workspace import specflow_dir
    from specflow.delta.manifest import load_manifest
    sf = specflow_dir()
    changes_dir = sf / "changes" / delta_id
    if not changes_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"delta {delta_id} 不存在")

    result = {"delta_id": delta_id, "workspace": workspace}

    proposal_path = changes_dir / "proposal.md"
    if proposal_path.is_file():
        result["proposal"] = proposal_path.read_text(encoding="utf-8")

    delta_spec_path = changes_dir / "delta-spec.md"
    if delta_spec_path.is_file():
        result["delta_spec"] = delta_spec_path.read_text(encoding="utf-8")

    manifest_path = changes_dir / "delta.manifest.yaml"
    if manifest_path.is_file():
        manifest = load_manifest(str(manifest_path))
        if manifest:
            result["manifest"] = {
                "delta": manifest.delta,
                "source_interview": manifest.source_interview,
                "operations": manifest.operations,
            }
    return result