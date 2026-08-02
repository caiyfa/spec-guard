"""草稿区三道闸 API（D1 补齐）：评审 → 格式校验 → 发布门禁 → 入库。

端点：
  GET    /api/drafts                        草稿列表（含解析出的场景 id/标题）
  GET    /api/drafts/modules                可入库的模块目录（scenarios/ 下）
  GET    /api/drafts/suggest-deps           全部草稿的依赖建议（K-046，dep_suggest 确定性引擎）
  GET    /api/drafts/{filename}             草稿内容
  PUT    /api/drafts/{filename}             保存草稿内容（K-046，写前 .bak 备份 + 审计）
  POST   /api/drafts/{filename}/validate    格式校验（与 MCP validate 同一实现）
  POST   /api/drafts/{filename}/deps        草稿连线：文本外科手术加 depends_on（K-046）
  POST   /api/drafts/{filename}/trial-run   草稿试跑（K-046，与 MCP run_scenario 同一语义）
  POST   /api/drafts/{filename}/promote     入库：校验 → 移动 → 基线更新 → 发布门禁（失败回滚）
  POST   /api/drafts/{filename}/discard     废弃（移入 drafts/_trash/）

安全约束（与架构 D5 一致）：
- 仅 drafts/ 目录可读可写；filename 禁止路径分隔符与 ..
- 入库目标限定 scenarios/ 下已存在模块目录
- 发布门禁 release_check.py 失败自动回滚，不产生半截入库
- K-046：编辑/连线/试跑只作用于 drafts/ 沙箱，入库仍必须走 promote 三道闸
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import drafts_dir, get_workspace_root  # noqa: E402


def _drafts_root() -> Path:
    """获取草稿目录（动态解析当前工作区 .specguard/drafts/，无工作区回退 SG_ROOT/drafts/）。"""
    try:
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = SG_ROOT / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _scenarios_root() -> Path:
    """场景库目录（工作区 scenarios/ 存在则用，否则回退 SpecGuard 仓库 scenarios/）。

    K-016 修复：spec 工作区克隆通常没有 scenarios/（场景库在 SpecGuard 仓库根），
    与 services.draft_promote._scenarios_root 同一策略。
    """
    ws = get_workspace_root()
    if ws and (ws / "scenarios").is_dir():
        return ws / "scenarios"
    return SG_ROOT / "scenarios"


def _trash_dir() -> Path:
    """获取草稿回收站目录。"""
    return _drafts_root() / "_trash"


# ══════════════════════════════════════════════════════════
# 路径守卫
# ══════════════════════════════════════════════════════════

def _guard_filename(filename: str) -> Path:
    """校验草稿文件名并返回安全路径（越界/非法 → 400）。"""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail=f"非法文件名: {filename}")
    if not filename.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail=f"仅支持 YAML 草稿: {filename}")
    return _drafts_root() / filename


def _guard_module(module: str) -> Path:
    """校验入库模块目录（必须在 scenarios/ 之内；K-017：不存在时自动创建）。"""
    if not module or ".." in module or module.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail=f"非法模块路径: {module}")
    scenarios_root = _scenarios_root()
    target = (scenarios_root / module).resolve()
    try:
        target.relative_to(scenarios_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"模块路径越界: {module}")
    if not target.is_dir():
        # K-017：自动创建模块目录（而非报「模块目录不存在」）
        target.mkdir(parents=True, exist_ok=True)
    return target


# ══════════════════════════════════════════════════════════
# 草稿列表 / 读取
# ══════════════════════════════════════════════════════════

@router.get("")
def list_drafts():
    """列出草稿区全部 YAML 草稿（按修改时间倒序，含作者归属）。"""
    # 作者元数据（draft_writer 写入）
    drafts_root = _drafts_root()
    meta_path = drafts_root / "_meta.json"
    meta = {}
    if meta_path.is_file():
        try:
            import json as _json
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    drafts = []
    # K-013：场景关联的新鲜度缓存（同一 source_meta 只查一次）
    _freshness_cache: dict = {}

    def _stale_of(source_meta_id: str) -> bool:
        if not source_meta_id:
            return False
        if source_meta_id not in _freshness_cache:
            try:
                from services import info_pack_freshness
                _freshness_cache[source_meta_id] = (
                    info_pack_freshness.check_freshness(source_meta_id).get("stale_count", 0) > 0
                )
            except Exception:
                _freshness_cache[source_meta_id] = False
        return _freshness_cache[source_meta_id]

    if drafts_root.is_dir():
        for f in sorted(drafts_root.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            sid, title = "", ""
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                sid = str(raw.get("id", ""))
                title = str(raw.get("title", ""))
            except Exception:
                pass
            meta_entry = meta.get(f.name) or {}
            source_meta = meta_entry.get("scenario_id", "")  # K-013: SG-META 关联（注意与 YAML 的 id 字段区分）
            drafts.append({
                "filename": f.name,
                "scenario_id": sid,
                "title": title,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                "author": meta_entry.get("author", ""),
                "source_meta": source_meta,
                "stale": _stale_of(source_meta),
            })
    return {"drafts": drafts}


@router.get("/modules")
def list_modules():
    """列出 scenarios/ 下的模块目录（promote 目标选择）。"""
    scenarios_root = _scenarios_root()
    modules = []
    if scenarios_root.is_dir():
        for d in sorted(scenarios_root.rglob("*")):
            if d.is_dir() and any(c.suffix == ".yaml" for c in d.iterdir() if c.is_file()):
                modules.append(str(d.relative_to(scenarios_root)).replace("\\", "/"))
    return {"modules": modules}


@router.get("/suggest-deps")
def suggest_draft_deps():
    """全部草稿的依赖建议（K-046：dep_suggest 确定性引擎，纯读）。

    扫描草稿 + 场景库的 {{...}} 插值 needs 侧，匹配 save 生产者，
    返回建议边（含理由/置信度）；已声明/传递依赖、自依赖、会成环的自动剔除。
    """
    from services import dep_suggest
    return dep_suggest.suggest_deps(_scenarios_root(), _drafts_root(), drafts_only=True)


@router.get("/{filename}")
def read_draft(filename: str):
    """读取单个草稿内容。"""
    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}


# ══════════════════════════════════════════════════════════
# K-046：草稿微调 / 连线 / 试跑（沙箱内操作，不入库、不触发基线重建）
# ══════════════════════════════════════════════════════════

class DraftSaveBody(BaseModel):
    content: str


def _update_meta(filename: str) -> None:
    """更新 _meta.json 的 updated_at（保留既有 author/scenario_id 关联）。"""
    import json as _json
    meta_path = _drafts_root() / "_meta.json"
    meta = {}
    if meta_path.is_file():
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    entry = meta.get(filename) or {}
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta[filename] = entry
    meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


@router.put("/{filename}", dependencies=[Depends(require_role("admin", "tester"))])
def save_draft(filename: str, body: DraftSaveBody):
    """保存草稿内容（K-046：评审期可微调，不再只有「作废」一条路）。

    写前自动 .bak 备份（对齐 draft_writer patch 惯例，undo 可恢复）；
    仅写 drafts/ 沙箱——入库仍必须走 promote 三道闸。
    """
    from services.auth import current_emp_no
    from services import user_store

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    # 基本可解析性检查（完整格式校验交给 validate 闸，此处只防明显写坏）
    try:
        yaml.safe_load(body.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"YAML 解析失败，未写入: {e}")
    shutil.copy2(str(path), str(path) + ".bak")
    path.write_text(body.content, encoding="utf-8")
    _update_meta(filename)
    user_store.audit(current_emp_no(), "edit_draft", f"编辑草稿 {filename}")
    return {"ok": True, "filename": filename}


class DraftDepBody(BaseModel):
    dep_id: str
    mode: str = "shared"


@router.post("/{filename}/deps", dependencies=[Depends(require_role("admin", "tester"))])
def add_draft_dep(filename: str, body: DraftDepBody):
    """草稿连线（K-046）：deps_editor 文本外科手术加 depends_on，与库内场景同一语义。

    守卫：自依赖拒绝、dep 目标必须存在（库内场景或另一草稿）、环预检（草稿并入图）。
    """
    from services import deps_editor, dep_suggest
    from services.auth import current_emp_no
    from services import user_store

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    if body.mode not in ("shared", "exclusive"):
        raise HTTPException(status_code=400, detail=f"mode 非法: {body.mode}")

    nodes = dep_suggest.scan_nodes(_scenarios_root(), _drafts_root())
    by_id = {n.id: n for n in nodes}
    try:
        consumer_raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"草稿 YAML 解析失败: {e}")
    consumer_id = str(consumer_raw.get("id", "") or "")
    if not consumer_id:
        raise HTTPException(status_code=422, detail="草稿缺少 id 字段，无法连线")
    if body.dep_id == consumer_id:
        raise HTTPException(status_code=400, detail="不允许自依赖")
    dep = by_id.get(body.dep_id)
    if not dep:
        raise HTTPException(status_code=404, detail=f"依赖目标不存在: {body.dep_id}")

    # 环预检：草稿并入图后，consumer 若在 dep 的依赖闭包中则成环
    graph = dep_suggest._build_graph(_scenarios_root(), _drafts_root())
    if graph and consumer_id in graph.by_id and body.dep_id in graph.by_id:
        try:
            if consumer_id in graph.closure(body.dep_id):
                raise HTTPException(status_code=409,
                                    detail=f"会形成循环依赖: {consumer_id} → {body.dep_id} → … → {consumer_id}")
        except HTTPException:
            raise
        except Exception:
            pass

    shutil.copy2(str(path), str(path) + ".bak")
    try:
        deps_editor.add_dep(str(path), body.dep_id, body.mode, dep.version or "0.1")
    except deps_editor.DepsEditError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _update_meta(filename)
    user_store.audit(current_emp_no(), "edit_draft_dep",
                     f"草稿 {filename}({consumer_id}) 加依赖 {body.dep_id}({body.mode})")
    return {"ok": True, "consumer": consumer_id, "dep_id": body.dep_id, "mode": body.mode}


@router.post("/{filename}/trial-run", dependencies=[Depends(require_role("admin", "tester"))])
async def trial_run_draft(filename: str):
    """草稿试跑（K-046：与 MCP run_scenario 同一语义的 HTTP 化薄封装）。

    草稿并入依赖图 → in-process run_single 按闭包执行（真实环境联网调用）。
    未入库先验证，豁免 covers 闸（草稿可能尚未锚定 FR）；报告落 .specguard/reports/。
    """
    import asyncio
    from services.auth import current_emp_no
    from services import user_store

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")

    from mcp_server.tools.scenario_tools import _handle_run_scenario
    # MCP handler 返回 TextContent 列表；复用确保两套入口同一语义（asyncio.to_thread 透传工作区 contextvar）
    contents = await asyncio.to_thread(
        lambda: asyncio.run(_handle_run_scenario({"draft": filename})))
    import json as _json
    try:
        result = _json.loads(contents[0].text)
    except Exception:
        result = {"ok": False, "error": contents[0].text if contents else "未知错误"}
    if result.get("error", "").startswith("错误："):
        raise HTTPException(status_code=400, detail=result["error"])
    user_store.audit(current_emp_no(), "trial_run_draft",
                     f"试跑草稿 {filename} → {result.get('verdict', '?')}")
    return result


# ══════════════════════════════════════════════════════════
# 三道闸：① 格式校验 ② 发布门禁 ③ 入库
# ══════════════════════════════════════════════════════════

@router.post("/{filename}/validate", dependencies=[Depends(require_role("admin", "tester"))])
def validate_draft(filename: str):
    """格式校验（format + covers + 注册表引用，与 MCP validate 同一实现）。"""
    from mcp_server.tools.validator import validate_scenario_content

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    return validate_scenario_content(path.read_text(encoding="utf-8"))


class PromoteBody(BaseModel):
    module: str          # 目标模块目录（相对 scenarios/，如 employee/person-profile）
    skip_gate: bool = False  # 仅调试用途跳过发布门禁（默认 False，正常入库必须过门禁）
    replace: bool = False    # T-313：覆盖同名场景（Agent 更新已有场景；原文件备份+失败回滚）


@router.post("/{filename}/promote", dependencies=[Depends(require_role("admin", "tester"))])
def promote_draft(filename: str, body: PromoteBody):
    """入库：格式校验 PASS → 移入 scenarios/{module}/ → 更新契约基线 → 发布门禁。

    发布门禁失败自动回滚（文件移回 drafts/，基线还原）。
    T-313：replace=true 覆盖同名场景（更新已有场景的写入路径）。
    K-015：核心逻辑抽取至 services.draft_promote（MCP promote_draft 工具复用同一实现）。
    """
    from services import draft_promote
    from services.auth import current_emp_no
    try:
        return draft_promote.promote(filename, body.module, skip_gate=body.skip_gate,
                                     emp_no=current_emp_no(), replace=body.replace)
    except draft_promote.PromoteError as e:
        status = draft_promote.HTTP_STATUS.get(e.code, 500)
        raise HTTPException(status_code=status,
                            detail={"message": str(e), **(e.detail or {})} if e.detail else str(e))


@router.post("/{filename}/discard", dependencies=[Depends(require_role("admin", "tester"))])
def discard_draft(filename: str):
    """废弃草稿（移入 drafts/_trash/，可人工恢复）。"""
    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    trash = _trash_dir()
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    shutil.move(str(path), str(target))
    return {"ok": True, "trashed_to": str(target.relative_to(get_workspace_root() or SG_ROOT)).replace("\\", "/")}
