"""草稿入库服务（K-015：从 routers/drafts.py 抽取，供 API 与 MCP 工具复用）。

三道闸：① 格式校验 → ② 移动入库 + 契约基线更新 → ③ 发布门禁（失败自动回滚）。
异常：PromoteError（code 语义码 + detail），由调用方映射为 HTTP 状态或工具错误文本。
"""

import shutil
import subprocess
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import drafts_dir, get_workspace_root  # noqa: E402


class PromoteError(Exception):
    """入库失败（code: invalid_filename / draft_not_found / invalid_module /
    module_not_found / conflict / validation_failed / baseline_failed / gate_failed）。"""

    def __init__(self, code: str, message: str, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


# HTTP 状态码映射（routers/drafts.py 用）
HTTP_STATUS = {
    "invalid_filename": 400, "invalid_module": 400,
    "draft_not_found": 404, "module_not_found": 404,
    "conflict": 409, "validation_failed": 422,
    "baseline_failed": 500, "gate_failed": 502,
}


def _drafts_root() -> Path:
    """草稿目录（当前工作区 .specguard/drafts/，无工作区回退 SG_ROOT/drafts/）。"""
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

    K-016 修复：spec 工作区克隆通常没有 scenarios/（场景库在 SpecGuard 仓库根，
    scenario_store/DagEditor/plan_executor 都读 SG_ROOT/scenarios），
    此前解析到不存在的目录 → /drafts/modules 返回空 → 入库按钮静默无反应。
    """
    ws = get_workspace_root()
    if ws and (ws / "scenarios").is_dir():
        return ws / "scenarios"
    return SG_ROOT / "scenarios"


def _guard_filename(filename: str) -> Path:
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise PromoteError("invalid_filename", f"非法文件名: {filename}")
    if not filename.endswith((".yaml", ".yml")):
        raise PromoteError("invalid_filename", f"仅支持 YAML 草稿: {filename}")
    return _drafts_root() / filename


def _guard_module(module: str) -> Path:
    if not module or ".." in module or module.startswith(("/", "\\")):
        raise PromoteError("invalid_module", f"非法模块路径: {module}")
    scenarios_root = _scenarios_root()
    target = (scenarios_root / module).resolve()
    try:
        target.relative_to(scenarios_root.resolve())
    except ValueError:
        raise PromoteError("invalid_module", f"模块路径越界: {module}")
    if not target.is_dir():
        # K-017：模块目录不存在时自动创建（目录是廉价资源，不应让用户手工建目录）
        target.mkdir(parents=True, exist_ok=True)
    return target


def _rebuild_baseline():
    """重建契约基线（新场景入库后 T6 基线同步）。"""
    from engine.scenario_loader import load_scenarios
    from engine.versioning import build_baseline, save_baseline

    scenarios = load_scenarios(str(_scenarios_root()))
    baseline = build_baseline(scenarios)
    save_baseline(str(SG_ROOT), baseline)


def _run_release_gate() -> dict:
    """运行发布门禁 release_check.py，返回 {ok, output}。"""
    try:
        result = subprocess.run(
            [sys.executable, "release_check.py"],
            cwd=str(SG_ROOT), capture_output=True, text=True, timeout=180,
        )
        output = (result.stdout + result.stderr)[-3000:]
        return {"ok": result.returncode == 0, "output": output, "skipped": False}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "release_check 超时（180s）", "skipped": False}
    except Exception as e:
        return {"ok": False, "output": f"release_check 执行异常: {e}", "skipped": False}


def _display_target(target: Path) -> str:
    """入库目标展示路径（相对工作区或 SG_ROOT，仅用于返回值展示）。

    K-019 修复：K-016 回退场景下（工作区激活但无 scenarios/，target 落在 SG_ROOT 侧）
    target.relative_to(工作区根) 抛 ValueError——且在 return 语句才炸，此时文件已移动、
    基线已重建、门禁已通过，实际入库成功却报错「失败」（生产会话导出佐证）。
    展示路径计算不得抛出，且必须在副作用之前算好。
    """
    for base in (get_workspace_root(), SG_ROOT):
        if base:
            try:
                return str(target.relative_to(base)).replace("\\", "/")
            except ValueError:
                continue
    return str(target)


def _ensure_suite_yaml(module_dir: Path, module: str):
    """K-026：目标模块目录无 _suite.yaml 时自动创建（module 元信息）。

    此前 promote 到新建目录后场景 module=''——DAG 编排/场景列表按模块分组时
    新场景无归属（90 节点里找不到），用户反馈「入库后在 DAG 编排里选不到」。
    """
    suite = module_dir / "_suite.yaml"
    if suite.exists():
        return
    feature = module_dir.name
    suite.write_text(
        f"# 套件元信息（promote 自动创建，K-026）\n"
        f"feature: {feature}\n"
        f"module: {module}\n",
        encoding="utf-8",
    )


def _record_lineage(filenames: list[str], scenario_ids: list[str], module: str):
    """K-026：promote 成功后把草稿→场景血缘写入信息包 sidecar。

    草稿的 scenario_id（SG-META-xxxx）来自 drafts/_meta.json（write_draft K-013 记录）。
    """
    try:
        import json as _json
        meta_path = _drafts_root() / "_meta.json"
        if not meta_path.is_file():
            return
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        from services import scenario_meta
        for fn, sc_id in zip(filenames, scenario_ids):
            sid = (meta.get(fn) or {}).get("scenario_id", "")
            if sid:
                scenario_meta.record_promotion(sid, sc_id, module, fn)
    except Exception:
        pass  # 血缘记录失败不影响入库主流程


def promote(filename: str, module: str, skip_gate: bool = False, emp_no: str = "") -> dict:
    """入库：格式校验 PASS → 移入 scenarios/{module}/ → 更新契约基线 → 发布门禁。

    发布门禁失败自动回滚（文件移回 drafts/，基线还原）。
    成功返回 {ok, scenario_id, target, validate, gate}；失败抛 PromoteError。
    """
    from mcp_server.tools.validator import validate_scenario_content

    path = _guard_filename(filename)
    if not path.is_file():
        raise PromoteError("draft_not_found", f"草稿不存在: {filename}")
    module_dir = _guard_module(module)
    target = module_dir / filename
    if target.exists():
        raise PromoteError("conflict", f"目标已存在同名场景: {module}/{filename}")
    # K-019：展示路径在副作用前算好（该计算曾抛 ValueError 导致「成功报失败」）
    display_target = _display_target(target)

    # 闸 1：格式校验
    report = validate_scenario_content(path.read_text(encoding="utf-8"))
    if report["verdict"] != "PASS":
        raise PromoteError("validation_failed", "格式校验未通过，禁止入库",
                           detail={"findings": report["findings"]})

    # 入库：移动文件 + 更新契约基线
    shutil.move(str(path), str(target))
    try:
        _rebuild_baseline()
    except Exception as e:
        shutil.move(str(target), str(path))  # 回滚
        raise PromoteError("baseline_failed", f"契约基线更新失败，已回滚: {e}")

    # 闸 2：发布门禁（release_check.py）
    gate = {"skipped": True}
    if not skip_gate:
        gate = _run_release_gate()
        if not gate["ok"]:
            # 回滚：文件移回 + 基线还原
            shutil.move(str(target), str(path))
            try:
                _rebuild_baseline()
            except Exception:
                pass
            raise PromoteError("gate_failed", "发布门禁未通过，已回滚",
                               detail={"gate_output": gate.get("output", "")})

    # 审计：草稿入库留痕（M6 审计要求）
    try:
        from services import user_store
        user_store.audit(emp_no, "promote_draft", filename, module)
    except Exception:
        pass

    # K-026：模块元信息 + 入库血缘（信息包 → 场景正向链路）
    _ensure_suite_yaml(module_dir, module)
    _record_lineage([filename], [report.get("scenario", "")], module)

    return {
        "ok": True,
        "scenario_id": report.get("scenario", ""),
        "target": display_target,
        "validate": report,
        "gate": gate,
    }


def promote_batch(filenames: list[str] | None, module: str,
                  skip_gate: bool = False, emp_no: str = "") -> dict:
    """批量入库（K-021⑥：65 份草稿逐份 promote = 65 次全量发布门禁，实际不可用）。

    语义：逐份格式校验 + 冲突检查（不合格的单份跳过并记录原因，不拖垮整批）
    → 合格批次一次移动 → 一次契约基线重建 → 一次发布门禁（失败整批回滚）。
    filenames 为空时入库 drafts/ 全部 YAML 草稿。
    """
    from mcp_server.tools.validator import validate_scenario_content

    module_dir = _guard_module(module)

    if not filenames:
        d = _drafts_root()
        filenames = sorted(f.name for f in d.glob("*.yaml")) + sorted(f.name for f in d.glob("*.yml"))

    # 闸 1：逐份校验 + 冲突检查（不合格单份跳过）
    qualified: list[tuple] = []
    skipped: list[dict] = []
    for fn in filenames:
        try:
            path = _guard_filename(fn)
        except PromoteError as e:
            skipped.append({"file": fn, "reason": str(e)})
            continue
        if not path.is_file():
            skipped.append({"file": fn, "reason": "草稿不存在"})
            continue
        target = module_dir / fn
        if target.exists():
            skipped.append({"file": fn, "reason": f"目标已存在同名场景: {module}/{fn}"})
            continue
        report = validate_scenario_content(path.read_text(encoding="utf-8"))
        if report["verdict"] != "PASS":
            skipped.append({"file": fn, "reason": "格式校验未通过",
                            "findings": [f for f in report["findings"]
                                         if f.get("level") == "ERROR"][:5]})
            continue
        qualified.append((path, target, fn, report))

    if not qualified:
        return {"ok": False, "promoted": [], "skipped": skipped,
                "error": "无合格草稿可入库（详见 skipped）"}

    # 入库：整批移动
    moved: list[dict] = []
    for path, target, fn, report in qualified:
        shutil.move(str(path), str(target))
        moved.append({"file": fn, "scenario_id": report.get("scenario", ""),
                      "target": _display_target(target)})

    def _rollback():
        for path, target, _fn, _report in qualified:
            if target.exists():
                shutil.move(str(target), str(path))

    # 基线一次重建（失败整批回滚）
    try:
        _rebuild_baseline()
    except Exception as e:
        _rollback()
        raise PromoteError("baseline_failed", f"契约基线更新失败，已整批回滚: {e}")

    # 闸 2：发布门禁一次（失败整批回滚 + 基线还原）
    gate = {"skipped": True}
    if not skip_gate:
        gate = _run_release_gate()
        if not gate["ok"]:
            _rollback()
            try:
                _rebuild_baseline()
            except Exception:
                pass
            raise PromoteError("gate_failed", "发布门禁未通过，已整批回滚",
                               detail={"gate_output": gate.get("output", "")})

    # 审计：批量入库留痕
    try:
        from services import user_store
        user_store.audit(emp_no, "promote_drafts", f"{len(moved)}份", module)
    except Exception:
        pass

    # K-026：模块元信息 + 入库血缘（信息包 → 场景正向链路）
    _ensure_suite_yaml(module_dir, module)
    _record_lineage([m["file"] for m in moved], [m["scenario_id"] for m in moved], module)

    return {
        "ok": True,
        "promoted": moved,
        "skipped": skipped,
        "gate": gate,
        "summary": f"入库 {len(moved)} 份，跳过 {len(skipped)} 份（module={module}）",
    }
