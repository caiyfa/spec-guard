"""specflow_materials.py — 材料包/信息包 REST API（T-030/T-031/T-032，M03 §5.1）。

前缀 /api/specflow，挂 RBAC。
人拍板级动作（候选 confirm / 材料 include / 装配）仅 product 角色；
上传/列表/预览为读写混合，登录即可（写域仅 .specflow/）。
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/specflow", tags=["specflow"],
                   dependencies=[Depends(get_current_user)])

_MAX_UPLOAD = 20 * 1024 * 1024  # 20MB（M03 §5.1）


def _sf_base():
    from specstd.workspace import specflow_dir, get_context_emp_no
    return specflow_dir(emp=get_context_emp_no() or "")


# ══════════════════════════════════════════════════════════
# T-030：材料上传/列表/预览
# ══════════════════════════════════════════════════════════

@router.post("/interviews/{iv_id}/materials")
async def upload_material(
    iv_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """上传材料（multipart，≤20MB）→ 落盘 + 解析管线 → 状态机。"""
    from specflow.interview.iv_lifecycle import validate_iv_id
    from workbench.backend.services.specflow.materials_service import db_upload_material

    err = validate_iv_id(iv_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    content = await file.read()
    if len(content) > _MAX_UPLOAD:
        raise HTTPException(status_code=400,
                            detail=f"文件超过 {_MAX_UPLOAD // (1024 * 1024)}MB 上限")
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")

    filename = file.filename or "unnamed"
    try:
        result = db_upload_material(iv_id, workspace, filename, content,
                                    user.emp_no, _sf_base())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/interviews/{iv_id}/materials")
def list_materials(
    iv_id: str,
    status: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """材料列表（含解析状态徽标 + sha256_12）。"""
    from specflow.interview.iv_lifecycle import validate_iv_id
    from workbench.backend.services.specflow.materials_service import db_list_materials

    err = validate_iv_id(iv_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"materials": db_list_materials(iv_id, workspace, status)}


@router.get("/materials/{mid}/preview")
def preview_material(
    mid: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """材料预览：优先 _parsed 抽取文本，无则读原文（file_preview 语义）。"""
    from workbench.backend.services.specflow.materials_service import _db_conn
    from specflow.materials import store

    conn = _db_conn()
    try:
        m = store.get_material(conn, mid)
    finally:
        conn.close()
    if not m or m["workspace"] != workspace:
        raise HTTPException(status_code=404, detail=f"材料不存在: {mid}")

    iv_dir = _sf_base() / "interviews" / m["iv_id"]
    stem = __import__("pathlib").Path(m["filename"]).stem or mid
    parsed = iv_dir / "materials" / "_parsed" / f"{stem}.extract.txt"
    if parsed.is_file():
        return {"material_id": mid, "source": "parsed",
                "text": parsed.read_text(encoding="utf-8")[:20000]}
    raw = iv_dir / "materials" / m["filename"]
    if raw.is_file():
        from workbench.backend.services.file_preview import preview_text
        text, fmt = preview_text(raw)
        return {"material_id": mid, "source": "raw", "fmt": fmt, "text": text}
    raise HTTPException(status_code=404, detail=f"材料文件缺失: {m['filename']}")


# ══════════════════════════════════════════════════════════
# T-031：议题候选 + 人拍板确认闸门
# ══════════════════════════════════════════════════════════

@router.get("/materials/{mid}/topics")
def list_topics(
    mid: str,
    confirmed_only: bool = False,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """议题候选列表（默认全量；confirmed_only=true 只取已拍板）。"""
    from workbench.backend.services.specflow.materials_service import _db_conn
    from specflow.materials import store

    conn = _db_conn()
    try:
        topics = store.list_topics(conn, material_id=mid, workspace=workspace,
                                   confirmed_only=confirmed_only)
    finally:
        conn.close()
    return {"topics": topics}


@router.post("/materials/{mid}/topics/{tid}/confirm")
def confirm_topic(
    mid: str,
    tid: str,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """人拍板：议题候选生效（confirmed=1 → 供面试官提问消费；未确认不进上下文）。"""
    from workbench.backend.services.specflow.materials_service import db_confirm_topic
    confirmed = 0 if body.get("confirmed") is False else 1
    try:
        topic = db_confirm_topic(tid, workspace, confirmed)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if topic["material_id"] != mid:
        raise HTTPException(status_code=404, detail=f"议题候选不存在: {tid}")
    return {"topic": topic}


# ══════════════════════════════════════════════════════════
# T-032：入包闸门 + 信息包装配
# ══════════════════════════════════════════════════════════

@router.post("/interviews/{iv_id}/materials/{mid}/include")
def include_material(
    iv_id: str,
    mid: str,
    body: dict,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """人拍板：材料入信息包（pack_included=1 → 重新装配时纳入）。"""
    from workbench.backend.services.specflow.materials_service import (
        db_include_material, db_assemble_pack)
    included = 1 if body.get("included", True) else 0
    try:
        m = db_include_material(mid, workspace, included)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if m["iv_id"] != iv_id:
        raise HTTPException(status_code=404, detail=f"材料不存在: {mid}")
    # 入包后自动重装配（保持 info_pack.yaml 与闸门状态一致）
    pack = db_assemble_pack(iv_id, workspace, _sf_base())
    return {"material": m, "pack": {"sections_available": pack.get("sections_available", [])}}


@router.get("/interviews/{iv_id}/pack")
def get_pack(
    iv_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """读取装配后信息包（含 freshness）。"""
    from specflow.materials.pack_assembler import read_pack
    pack = read_pack(iv_id, _sf_base())
    if not pack:
        raise HTTPException(status_code=404, detail=f"面试 {iv_id} 尚无信息包（请先装配）")
    return pack


@router.post("/interviews/{iv_id}/pack/reassemble")
def reassemble_pack(
    iv_id: str,
    user: CurrentUser = Depends(require_role("product")),
    workspace: str = Depends(resolve_workspace),
):
    """六分区重新装配（材料/SPQ/报告/基线变更后调用）。"""
    from specflow.interview.iv_lifecycle import validate_iv_id
    from workbench.backend.services.specflow.materials_service import db_assemble_pack
    err = validate_iv_id(iv_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    result = db_assemble_pack(iv_id, workspace, _sf_base())
    return {"status": "assembled",
            "sections_available": result.get("sections_available", [])}
