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
    """场景库目录（工作区 scenarios/，无工作区回退 SG_ROOT/scenarios/）。"""
    ws = get_workspace_root()
    return (ws / "scenarios") if ws else (SG_ROOT / "scenarios")


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
        raise PromoteError("module_not_found", f"模块目录不存在: {module}")
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

    return {
        "ok": True,
        "scenario_id": report.get("scenario", ""),
        "target": str(target.relative_to(get_workspace_root() or SG_ROOT)).replace("\\", "/"),
        "validate": report,
        "gate": gate,
    }
