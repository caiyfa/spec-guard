"""草稿区三道闸 API（D1 补齐）：评审 → 格式校验 → 发布门禁 → 入库。

端点：
  GET    /api/drafts                        草稿列表（含解析出的场景 id/标题）
  GET    /api/drafts/modules                可入库的模块目录（scenarios/ 下）
  GET    /api/drafts/{filename}             草稿内容
  POST   /api/drafts/{filename}/validate    格式校验（与 MCP validate 同一实现）
  POST   /api/drafts/{filename}/promote     入库：校验 → 移动 → 基线更新 → 发布门禁（失败回滚）
  POST   /api/drafts/{filename}/discard     废弃（移入 drafts/_trash/）

安全约束（与架构 D5 一致）：
- 仅 drafts/ 目录可读可写；filename 禁止路径分隔符与 ..
- 入库目标限定 scenarios/ 下已存在模块目录
- 发布门禁 release_check.py 失败自动回滚，不产生半截入库
"""

import shutil
import subprocess
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
    """获取场景库目录（工作区 scenarios/，无工作区回退 SG_ROOT/scenarios/）。"""
    ws = get_workspace_root()
    return (ws / "scenarios") if ws else (SG_ROOT / "scenarios")


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
    """校验入库模块目录（必须为 scenarios/ 下已存在的目录）。"""
    if not module or ".." in module or module.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail=f"非法模块路径: {module}")
    scenarios_root = _scenarios_root()
    target = (scenarios_root / module).resolve()
    try:
        target.relative_to(scenarios_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"模块路径越界: {module}")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"模块目录不存在: {module}")
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
    if drafts_root.is_dir():
        for f in sorted(drafts_root.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            sid, title = "", ""
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                sid = str(raw.get("id", ""))
                title = str(raw.get("title", ""))
            except Exception:
                pass
            drafts.append({
                "filename": f.name,
                "scenario_id": sid,
                "title": title,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                "author": (meta.get(f.name) or {}).get("author", ""),
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


@router.get("/{filename}")
def read_draft(filename: str):
    """读取单个草稿内容。"""
    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}


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


@router.post("/{filename}/promote", dependencies=[Depends(require_role("admin", "tester"))])
def promote_draft(filename: str, body: PromoteBody):
    """入库：格式校验 PASS → 移入 scenarios/{module}/ → 更新契约基线 → 发布门禁。

    发布门禁失败自动回滚（文件移回 drafts/，基线还原）。
    """
    from mcp_server.tools.validator import validate_scenario_content

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    module_dir = _guard_module(body.module)
    target = module_dir / filename
    if target.exists():
        raise HTTPException(status_code=409, detail=f"目标已存在同名场景: {body.module}/{filename}")

    # 闸 1：格式校验
    report = validate_scenario_content(path.read_text(encoding="utf-8"))
    if report["verdict"] != "PASS":
        raise HTTPException(status_code=422, detail={
            "message": "格式校验未通过，禁止入库",
            "findings": report["findings"],
        })

    # 入库：移动文件 + 更新契约基线
    shutil.move(str(path), str(target))
    try:
        _rebuild_baseline()
    except Exception as e:
        shutil.move(str(target), str(path))  # 回滚
        raise HTTPException(status_code=500, detail=f"契约基线更新失败，已回滚: {e}")

    # 闸 2：发布门禁（release_check.py）
    gate = {"skipped": True}
    if not body.skip_gate:
        gate = _run_release_gate()
        if not gate["ok"]:
            # 回滚：文件移回 + 基线还原
            shutil.move(str(target), str(path))
            try:
                _rebuild_baseline()
            except Exception:
                pass
            raise HTTPException(status_code=502, detail={
                "message": "发布门禁未通过，已回滚",
                "gate_output": gate.get("output", ""),
            })

    # 审计：草稿入库留痕（M6 审计要求）
    try:
        from services.auth import current_emp_no
        from services import user_store
        user_store.audit(current_emp_no(), "promote_draft", filename, body.module)
    except Exception:
        pass

    return {
        "ok": True,
        "scenario_id": report.get("scenario", ""),
        "target": str(target.relative_to(get_workspace_root() or SG_ROOT)).replace("\\", "/"),
        "validate": report,
        "gate": gate,
    }


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


# ══════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════

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
