"""场景管理 API：列表 / DAG / YAML 读写 / 校验 / 依赖编辑 / 漂移报告"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from services.auth import require_role, resolve_workspace
from services.scenario_store import (
    list_scenarios, get_dag, get_scenario_yaml,
    save_scenario_yaml, validate_dag, get_drift_report,
)
from services import deps_editor, scenario_meta

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("")
def api_list_scenarios():
    """场景列表（含依赖关系、标签、优先级）"""
    scenarios = list_scenarios()
    # 移除 abs_path（不暴露给前端）
    return [{k: v for k, v in s.items() if k != "abs_path"} for s in scenarios]


@router.get("/dag")
def api_get_dag():
    """DAG 图数据（React Flow 格式：nodes + edges）"""
    return get_dag()


@router.get("/validate")
def api_validate_dag():
    """循环依赖检测"""
    return validate_dag()


@router.get("/drift")
def api_drift_report():
    """版本漂移/缺失报告（DRIFT/ORPHANED 清单）"""
    return get_drift_report()


# ══════════════════════════════════════════════════════════
# 场景创建向导（G2-1）
# ══════════════════════════════════════════════════════════

class CreateScenarioBody(BaseModel):
    name: str
    module: str = ""


@router.post("/create", dependencies=[Depends(require_role("admin", "tester"))])
def api_create_scenario(body: CreateScenarioBody, ws_name: str = Depends(resolve_workspace)):
    """创建场景元数据（向导 Step 1）。"""
    meta = scenario_meta.create_meta(
        name=body.name, module=body.module or "", workspace=ws_name or "",
    )
    return meta


@router.get("/meta-list", dependencies=[Depends(require_role("admin", "tester"))])
def api_list_scenario_meta(ws_name: str = Depends(resolve_workspace)):
    """列出场景元数据（按工作区筛选）。"""
    metas = scenario_meta.list_meta(workspace=ws_name or "")
    return {"metas": metas}


class UpdateInfoPackBody(BaseModel):
    files: list[str]


@router.put("/{scenario_id}/info-pack", dependencies=[Depends(require_role("admin", "tester"))])
def api_update_info_pack(scenario_id: str, body: UpdateInfoPackBody):
    """更新基础信息包文件列表（向导 Step 2）。"""
    result = scenario_meta.update_info_pack(scenario_id, body.files)
    if result is None:
        raise HTTPException(status_code=404, detail=f"场景元数据不存在: {scenario_id}")
    return result


_UPLOAD_MAX_BYTES = 20 * 1024 * 1024  # 20MB


def _sanitize_upload(filename: str | None, data: bytes) -> str:
    """上传文件通用校验：剥离客户端路径 + 拒绝隐藏/空/超限文件，返回安全文件名。"""
    from pathlib import Path as _Path
    name = _Path(filename or "").name  # 剥离客户端路径
    if not name or name.startswith(".") or ".." in name:
        raise HTTPException(status_code=400, detail=f"非法文件名: {filename}")
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > _UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20MB 上限")
    return name


def _save_to_uploads(filename: str, data: bytes):
    """落盘 .specguard/uploads/（重名 -1/-2 去重不覆盖），返回工作区相对路径。"""
    from specstd.workspace import specguard_dir
    sg_dir = specguard_dir()
    uploads = sg_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    target = uploads / filename
    stem, suffix = target.stem, target.suffix
    n = 1
    while target.exists():
        target = uploads / f"{stem}-{n}{suffix}"
        n += 1
    target.write_bytes(data)
    return str(target.relative_to(sg_dir.parent)).replace("\\", "/")


@router.post("/info-pack/auto-create", dependencies=[Depends(require_role("admin", "tester"))])
async def api_auto_create_info_pack(
    files: list[UploadFile] = File(...),
    name: str = Form(""),
    ws_name: str = Depends(resolve_workspace),
):
    """K-034：聊天框上传附件 → 自动创建信息包（无需先走创建向导）。

    多个文件一次成一个信息包：落盘 .specguard/uploads/ + create_meta + 条目化，
    返回完整 meta，前端据此加入 info_pack 引用 chip（发送时才关联会话）。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    rel_paths: list[str] = []
    for f in files:
        data = await f.read()
        rel_paths.append(_save_to_uploads(_sanitize_upload(f.filename, data), data))
    pack_name = name.strip() or rel_paths[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    meta = scenario_meta.create_meta(name=pack_name, module="", workspace=ws_name or "")
    updated = scenario_meta.update_info_pack(meta["id"], rel_paths)
    return updated or meta


@router.post("/{scenario_id}/info-pack/upload", dependencies=[Depends(require_role("admin", "tester"))])
async def api_upload_info_pack_file(scenario_id: str, file: UploadFile = File(...)):
    """K-033：直接上传材料到信息包（不再只能 git 拉取工作区文件）。

    文件落盘 .specguard/uploads/{filename}（工作区内，safe_resolve 可读、
    git diff 变更发现已过滤 .specguard 不产生噪音），路径加入信息包条目
    （sha 指纹由 update_info_pack 归一化时自动计算）。重名自动 -1/-2 去重。
    """
    meta = scenario_meta.get_meta(scenario_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"场景元数据不存在: {scenario_id}")

    data = await file.read()
    rel = _save_to_uploads(_sanitize_upload(file.filename, data), data)
    files = [e.get("path") for e in (meta.get("info_pack") or []) if isinstance(e, dict)]
    if rel not in files:
        files.append(rel)
    updated = scenario_meta.update_info_pack(scenario_id, files)
    return updated or meta


@router.get("/{scenario_id}/info-pack/freshness", dependencies=[Depends(require_role("admin", "tester"))])
def api_info_pack_freshness(scenario_id: str):
    """K-013：信息包新鲜度（逐文件 hash 比对）+ git 变更发现（信息包外相关新文件）。"""
    from services import info_pack_freshness
    if scenario_meta.get_meta(scenario_id) is None:
        raise HTTPException(status_code=404, detail=f"场景元数据不存在: {scenario_id}")
    freshness = info_pack_freshness.check_freshness(scenario_id)
    discovery = info_pack_freshness.discover_related_changes(scenario_id)
    return {**freshness, "inside_stale": discovery.get("inside_stale", []),
            "outside_changes": discovery.get("outside_changes", [])}


@router.get("/{scenario_id}/meta", dependencies=[Depends(require_role("admin", "tester"))])
def api_get_scenario_meta(scenario_id: str):
    """获取场景元数据 + 基础信息包。"""
    meta = scenario_meta.get_meta(scenario_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"场景元数据不存在: {scenario_id}")
    return meta


# ══════════════════════════════════════════════════════════
# 场景 YAML 读写
# ══════════════════════════════════════════════════════════

@router.get("/{scenario_id}")
def api_get_scenario(scenario_id: str):
    """获取场景 YAML 原文"""
    content = get_scenario_yaml(scenario_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"场景 {scenario_id} 不存在")
    return {"id": scenario_id, "content": content}


class SaveScenarioBody(BaseModel):
    content: str


@router.put("/{scenario_id}", dependencies=[Depends(require_role("admin", "tester"))])
def api_save_scenario(scenario_id: str, body: SaveScenarioBody):
    """保存场景 YAML（校验后写入）"""
    result = save_scenario_yaml(scenario_id, body.content)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ══════════════════════════════════════════════════════════
# 依赖编辑（画布连线 → depends_on 文本外科手术）
# ══════════════════════════════════════════════════════════

class DepEditBody(BaseModel):
    action: str          # add | remove
    dep_id: str
    mode: str = "shared"  # shared | exclusive（add 时生效）


@router.post("/{scenario_id}/deps", dependencies=[Depends(require_role("admin", "tester"))])
def api_edit_dep(scenario_id: str, body: DepEditBody):
    """增删场景依赖（行级外科手术，保注释；add 前服务端环校验）"""
    if body.action not in ("add", "remove"):
        raise HTTPException(status_code=400, detail=f"action 非法: {body.action}（仅支持 add/remove）")
    if body.mode not in ("shared", "exclusive"):
        raise HTTPException(status_code=400, detail=f"mode 非法: {body.mode}")
    if scenario_id == body.dep_id:
        raise HTTPException(status_code=400, detail="不允许自依赖")

    scenarios = {s["id"]: s for s in list_scenarios()}
    if scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"场景 {scenario_id} 不存在")
    if body.action == "add" and body.dep_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"依赖目标 {body.dep_id} 不存在")

    if body.action == "add":
        # 环校验：dep 的依赖闭包中若已含本场景，新增边将成环
        from engine.scenario_loader import load_scenarios
        from engine.dependency_graph import DependencyGraph
        from services.scenario_store import SCENARIOS_ROOT
        graph = DependencyGraph(load_scenarios(str(SCENARIOS_ROOT)))
        if scenario_id in graph.closure(body.dep_id):
            raise HTTPException(
                status_code=409,
                detail=f"会形成循环依赖: {scenario_id} → {body.dep_id} → … → {scenario_id}")
        try:
            deps_editor.add_dep(
                scenarios[scenario_id]["abs_path"], body.dep_id, body.mode,
                scenarios[body.dep_id]["version"])
        except deps_editor.DepsEditError as e:
            raise HTTPException(status_code=409, detail=str(e))
    else:
        try:
            deps_editor.remove_dep(scenarios[scenario_id]["abs_path"], body.dep_id)
        except deps_editor.DepsEditError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # 返回该场景最新依赖列表（含版本仲裁状态）
    dag = get_dag()
    updated = next((n for n in dag["nodes"] if n["id"] == scenario_id), None)
    edges = [e for e in dag["edges"] if e["target"] == scenario_id]
    return {"ok": True, "scenario": updated, "depends_on": edges}
