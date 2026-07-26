"""测试计划存储服务：plans/*.yaml 读写 + 场景过滤解析。

计划是持久化的场景分组，支持按标签/ID列表/模块过滤，关联环境配置。
执行报告按计划归档：reports/{plan_id}/{timestamp}/。
计划可从 spec delta 导入：解析 delta 的 FR → 匹配已有场景 → 生成计划。
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import get_active_workspace  # noqa: E402


def _get_spec_root() -> Optional[Path]:
    """获取当前激活工作区的根路径。"""
    ws = get_active_workspace()
    return ws.root if ws else None


PLANS_ROOT = SG_ROOT / "plans"
SCENARIOS_ROOT = SG_ROOT / "scenarios"
REPORTS_ROOT = SG_ROOT / "reports"


def _ensure_plans_dir():
    PLANS_ROOT.mkdir(parents=True, exist_ok=True)


def _load_all_scenarios() -> list[dict]:
    """加载全部场景 ID + tags（供过滤解析）"""
    from services.scenario_store import _scan_scenarios
    return _scan_scenarios()


def list_plans() -> list[dict]:
    """列出全部测试计划"""
    _ensure_plans_dir()
    plans = []
    for f in sorted(PLANS_ROOT.iterdir()):
        if not f.suffix in (".yaml", ".yml"):
            continue
        with open(f, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        plan = _normalize(raw, f.stem)
        plan["scenario_count"] = len(resolve_scenarios(plan))
        plans.append(plan)
    return plans


def get_plan(plan_id: str) -> Optional[dict]:
    """读取单个计划"""
    _ensure_plans_dir()
    for ext in (".yaml", ".yml"):
        path = PLANS_ROOT / f"{plan_id}{ext}"
        if path.is_file():
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            plan = _normalize(raw, plan_id)
            plan["resolved_scenarios"] = resolve_scenarios(plan)
            plan["scenario_count"] = len(plan["resolved_scenarios"])
            return plan
    return None


def save_plan(plan_id: str, data: dict) -> dict:
    """创建/更新计划"""
    _ensure_plans_dir()
    data["id"] = plan_id
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = PLANS_ROOT / f"{plan_id}.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return get_plan(plan_id) or data


def delete_plan(plan_id: str) -> bool:
    """删除计划"""
    for ext in (".yaml", ".yml"):
        path = PLANS_ROOT / f"{plan_id}{ext}"
        if path.is_file():
            path.unlink()
            return True
    return False


def resolve_scenarios(plan: dict) -> list[str]:
    """根据计划的过滤条件解析出实际要执行的场景 ID 列表

    过滤优先级：scenarios（显式列表）> tags（标签匹配）> modules（模块匹配）> 全部
    """
    filter_cfg = plan.get("filter") or {}

    # 显式场景列表
    explicit = filter_cfg.get("scenarios") or []
    if explicit:
        return explicit

    all_scenarios = _load_all_scenarios()

    # 按标签过滤
    tags = filter_cfg.get("tags") or []
    if tags:
        return [s["id"] for s in all_scenarios if any(t in s.get("tags", []) for t in tags)]

    # 按模块过滤
    modules = filter_cfg.get("modules") or []
    if modules:
        return [s["id"] for s in all_scenarios if any(m in s.get("module", "") for m in modules)]

    # 无过滤条件 → 全部
    return [s["id"] for s in all_scenarios]


def list_plan_history(plan_id: str, limit: int = 20) -> list[dict]:
    """计划的历史执行记录（读 reports/{plan_id}/ 目录）"""
    plan_reports = REPORTS_ROOT / plan_id
    if not plan_reports.is_dir():
        return []
    import json
    runs = []
    for d in sorted(plan_reports.iterdir(), reverse=True):
        run_json = d / "run.json"
        if run_json.is_file():
            with open(run_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            runs.append({
                "run_id": data.get("run_id", d.name),
                "env": data.get("env"),
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "stats": data.get("stats", {}),
            })
        if len(runs) >= limit:
            break
    return runs


def get_plan_report_dir(plan_id: str, run_id: str) -> Path:
    """计划报告目录：reports/{plan_id}/{run_id}/"""
    return REPORTS_ROOT / plan_id / run_id


def _normalize(raw: dict, fallback_id: str) -> dict:
    """归一化计划数据"""
    return {
        "id": raw.get("id", fallback_id),
        "name": raw.get("name", fallback_id),
        "description": raw.get("description", ""),
        "env": raw.get("env", "sit"),
        "strict_deps": bool(raw.get("strict_deps", False)),   # 严格依赖模式（DRIFT/ORPHANED → BLOCKED）
        "filter": raw.get("filter") or {},
        "tags": raw.get("tags", []) or [],
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
    }


# ══════════════════════════════════════════════════════════
# Delta 导入
# ══════════════════════════════════════════════════════════

FR_RE = re.compile(r"\*\*(FR-[\w]+)\*\*")
FR_HEADING_RE = re.compile(r"^#{2,4}\s+(FR-[\w]+)\s*[:：]", re.M)


def import_from_delta(delta_code: str) -> dict:
    """从 spec delta 导入生成测试计划

    流程：
    1. 读取 changes/{delta}/proposal.md 提取名称/描述
    2. 扫描 changes/{delta}/modules/*/delta-spec.md 提取全部 FR ID
    3. 匹配已有场景（通过 covers 字段）
    4. 生成计划文件 plans/{delta_code}.yaml
    """
    spec_root = _get_spec_root()
    if not spec_root:
        return {"ok": False, "error": "无激活的工作区"}
    delta_dir = spec_root / "changes" / delta_code
    if not delta_dir.is_dir():
        return {"ok": False, "error": f"delta 目录不存在: {delta_dir}"}

    # 1. 读取 proposal.md
    name = delta_code
    description = ""
    proposal_file = delta_dir / "proposal.md"
    if proposal_file.is_file():
        with open(proposal_file, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"^#\s+Delta\s+Proposal[:：]\s*(.+)$", text, re.M)
        if m:
            name = m.group(1).strip()
        m = re.search(r"^##\s+一、背景与动机\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
        if m:
            description = m.group(1).strip()[:200]

    # 2. 提取全部 FR ID
    all_frs = set()
    modules_dir = delta_dir / "modules"
    if modules_dir.is_dir():
        for md in sorted(modules_dir.iterdir()):
            if not md.is_dir():
                continue
            for spec_file in ("delta-spec.md", "spec.md"):
                sf = md / spec_file
                if sf.is_file():
                    with open(sf, "r", encoding="utf-8") as f:
                        text = f.read()
                    all_frs.update(FR_RE.findall(text))
                    all_frs.update(FR_HEADING_RE.findall(text))
                    break

    # 也扫 delta-specs/*.md（flat 形态）
    ds_dir = delta_dir / "delta-specs"
    if ds_dir.is_dir():
        for sf in sorted(ds_dir.glob("*.md")):
            with open(sf, "r", encoding="utf-8") as f:
                text = f.read()
            all_frs.update(FR_RE.findall(text))
            all_frs.update(FR_HEADING_RE.findall(text))

    # 3. 匹配已有场景
    all_scenarios = _load_all_scenarios()
    matched = []
    unmatched_frs = set(all_frs)
    for sc in all_scenarios:
        covers = set(sc.get("covers", []))
        if covers & all_frs:
            matched.append(sc["id"])
            unmatched_frs -= covers

    # 4. 生成计划
    plan_data = {
        "id": delta_code,
        "name": name,
        "description": description or f"从 delta {delta_code} 导入",
        "env": "sit",
        "tags": ["imported", delta_code],
        "filter": {
            "scenarios": matched,
        },
        "source_delta": delta_code,
        "source_frs": sorted(all_frs),
        "unmatched_frs": sorted(unmatched_frs),
    }

    plan = save_plan(delta_code, plan_data)
    plan["import_result"] = {
        "total_frs": len(all_frs),
        "matched_scenarios": len(matched),
        "unmatched_frs": sorted(unmatched_frs),
    }
    return {"ok": True, "plan": plan}


# ══════════════════════════════════════════════════════════
# 导入预览 + 工作副本
# ══════════════════════════════════════════════════════════

def import_preview(delta_code: str) -> dict:
    """导入预览：展示 delta 中的文件清单 + 格式校验 + unit/scenario 分类

    返回：
      files: [{path, module, type: unit/scenario, valid, errors, frs}]
      summary: {total, unit_count, scenario_count, valid_count, error_count}
      frs: 全部 FR ID
      proposal: {name, description}
    """
    spec_root = _get_spec_root()
    if not spec_root:
        return {"ok": False, "error": "无激活的工作区"}
    delta_dir = spec_root / "changes" / delta_code
    if not delta_dir.is_dir():
        return {"ok": False, "error": f"delta 目录不存在: {delta_dir}"}

    # 解析 proposal
    name = delta_code
    description = ""
    proposal_file = delta_dir / "proposal.md"
    if proposal_file.is_file():
        text = proposal_file.read_text(encoding="utf-8")
        m = re.search(r"^#\s+Delta\s+Proposal[:：]\s*(.+)$", text, re.M)
        if m:
            name = m.group(1).strip()
        m = re.search(r"^##\s+一、背景与动机\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
        if m:
            description = m.group(1).strip()[:200]

    files = []
    all_frs = set()

    # 扫描 test-cases/ 目录下的 YAML 测试用例文件
    tc_dir = delta_dir / "test-cases"
    if tc_dir.is_dir():
        for tf in sorted(tc_dir.rglob("*.yaml")) + sorted(tc_dir.rglob("*.yml")):
            entry = _preview_test_case(tf, delta_dir)
            all_frs.update(entry.get("frs", []))
            files.append(entry)

    # 也扫描 delta 根目录下的 YAML 测试用例（非 test-cases 子目录）
    for tf in sorted(delta_dir.glob("*.yaml")) + sorted(delta_dir.glob("*.yml")):
        if tf.name.startswith("_") or tf.name in ("api.yaml", "e2e-cases.yaml"):
            continue  # 跳过配置类和套件类 YAML
        entry = _preview_test_case(tf, delta_dir)
        all_frs.update(entry.get("frs", []))
        files.append(entry)

    # .md spec 文档单独提取 FR（不作为可导入的测试用例文件）
    modules_dir = delta_dir / "modules"
    if modules_dir.is_dir():
        for md in sorted(modules_dir.iterdir()):
            if not md.is_dir():
                continue
            for spec_file in ("delta-spec.md", "spec.md"):
                sf = md / spec_file
                if sf.is_file():
                    text = sf.read_text(encoding="utf-8")
                    all_frs.update(re.findall(r"\*\*(FR-[\w]+)\*\*", text))
                    all_frs.update(re.findall(r"^#{2,4}\s+(FR-[\w]+)\s*[:：]", text, re.M))
                    break
    ds_dir = delta_dir / "delta-specs"
    if ds_dir.is_dir():
        for sf in sorted(ds_dir.glob("*.md")):
            text = sf.read_text(encoding="utf-8")
            all_frs.update(re.findall(r"\*\*(FR-[\w]+)\*\*", text))
            all_frs.update(re.findall(r"^#{2,4}\s+(FR-[\w]+)\s*[:：]", text, re.M))

    # 匹配已有场景
    all_scenarios = _load_all_scenarios()
    matched_scenarios = []
    unmatched_frs = set(all_frs)
    for sc in all_scenarios:
        covers = set(sc.get("covers", []))
        if covers & all_frs:
            matched_scenarios.append({"id": sc["id"], "title": sc["title"], "covers": sorted(covers & all_frs)})
            unmatched_frs -= covers

    # 分类统计
    unit_files = [f for f in files if f.get("test_type") == "unit"]
    scenario_files = [f for f in files if f.get("test_type") != "unit"]
    valid_count = sum(1 for f in files if f.get("valid", True))
    error_count = sum(1 for f in files if not f.get("valid", True))

    return {
        "ok": True,
        "delta": delta_code,
        "proposal": {"name": name, "description": description},
        "files": files,
        "frs": sorted(all_frs),
        "matched_scenarios": matched_scenarios,
        "unmatched_frs": sorted(unmatched_frs),
        "summary": {
            "total_files": len(files),
            "unit_count": len(unit_files),
            "scenario_count": len(scenario_files),
            "valid_count": valid_count,
            "error_count": error_count,
            "total_frs": len(all_frs),
            "matched_scenarios": len(matched_scenarios),
        },
    }


def _preview_file(path: Path, module: str, delta_dir: Path) -> dict:
    """预览单个 spec 文件：提取 FR、推断类型、格式校验"""
    rel = str(path.relative_to(delta_dir))
    errors = []
    frs = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return {"path": rel, "module": module, "test_type": "scenario", "valid": False,
                "errors": [f"读取失败: {e}"], "frs": []}

    # 提取 FR
    frs = list(dict.fromkeys(
        re.findall(r"\*\*(FR-[\w]+)\*\*", text) +
        re.findall(r"^#{2,4}\s+(FR-[\w]+)\s*[:：]", text, re.M)
    ))

    # 格式校验
    if not frs:
        errors.append("未提取到 FR 编号")
    if "基线文件" not in text and "关联基线" not in text:
        errors.append("缺「基线文件」或「关联基线」头部声明")

    # 推断类型：有 VERIFY/验证步骤 → scenario；纯 FR 定义 → unit
    has_verify = bool(re.search(r"验证|verify|VERIFY", text))
    test_type = "scenario" if has_verify else "unit"

    return {
        "path": rel,
        "module": module,
        "test_type": test_type,
        "valid": len(errors) == 0,
        "errors": errors,
        "frs": frs,
        "size": path.stat().st_size,
    }


def _preview_test_case(path: Path, delta_dir: Path) -> dict:
    """预览单个 test-case YAML 文件"""
    rel = str(path.relative_to(delta_dir))
    errors = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        return {"path": rel, "module": "", "test_type": "scenario", "valid": False,
                "errors": [f"YAML 解析失败: {e}"], "frs": []}

    sid = raw.get("id", path.stem)
    test_type = raw.get("test_type", "scenario")
    flow = raw.get("flow") or []
    verify = raw.get("verify") or []
    deps = raw.get("depends_on") or []
    covers = (raw.get("doc") or {}).get("covers", [])

    if not flow and not verify:
        errors.append("flow/verify 均为空")
    if test_type == "scenario" and not deps and "prep" not in (raw.get("tags") or []):
        errors.append("scenario 类型无 depends_on（疑似孤立场景）")

    return {
        "path": rel,
        "module": "",
        "id": sid,
        "test_type": test_type,
        "valid": len(errors) == 0,
        "errors": errors,
        "frs": covers,
        "size": path.stat().st_size,
    }


def import_confirm(delta_code: str, selected_files: list[str]) -> dict:
    """确认导入：创建工作副本 + 生成计划

    工作副本存储在 plans/{delta_code}/scenarios/ 目录，
    每个副本文件头部标注源文件路径，编辑不影响源文件。
    """
    spec_root = _get_spec_root()
    if not spec_root:
        return {"ok": False, "error": "无激活的工作区"}
    delta_dir = spec_root / "changes" / delta_code
    if not delta_dir.is_dir():
        return {"ok": False, "error": f"delta 目录不存在"}

    # 先预览获取全部信息
    preview = import_preview(delta_code)
    if not preview["ok"]:
        return preview

    # 过滤选中的文件
    files_to_import = [f for f in preview["files"] if f["path"] in selected_files] if selected_files else preview["files"]

    # 创建工作副本目录
    plan_dir = PLANS_ROOT / delta_code
    scenarios_dir = plan_dir / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    imported = []
    for f in files_to_import:
        if not f.get("valid", True):
            continue  # 跳过格式不合格的文件
        src = delta_dir / f["path"]
        if not src.is_file():
            continue
        dst = scenarios_dir / Path(f["path"]).name
        # 复制文件并在头部标注源路径
        content = src.read_text(encoding="utf-8")
        header = f"# ── 工作副本（源文件: changes/{delta_code}/{f['path']}）──\n"
        dst.write_text(header + content, encoding="utf-8")
        imported.append({
            "path": f["path"],
            "copy": str(dst.relative_to(SG_ROOT)),
            "module": f.get("module", ""),
            "test_type": f.get("test_type", "scenario"),
            "frs": f.get("frs", []),
        })

    # 匹配已有场景
    all_scenarios = _load_all_scenarios()
    all_frs = set(preview["frs"])
    matched = [s["id"] for s in all_scenarios if set(s.get("covers", [])) & all_frs]

    # 生成计划
    plan_data = {
        "id": delta_code,
        "name": preview["proposal"]["name"],
        "description": preview["proposal"]["description"],
        "env": "sit",
        "tags": ["imported", delta_code],
        "filter": {"scenarios": matched},
        "source_delta": delta_code,
        "source_frs": preview["frs"],
        "unmatched_frs": preview["unmatched_frs"],
        "imported_files": imported,
        "breakpoints": [],
    }

    plan = save_plan(delta_code, plan_data)
    return {
        "ok": True,
        "plan": plan,
        "imported_count": len(imported),
        "matched_scenarios": len(matched),
    }


def get_plan_working_copy(plan_id: str, filename: str) -> Optional[str]:
    """读取计划的工作副本内容"""
    copy_path = PLANS_ROOT / plan_id / "scenarios" / filename
    if not copy_path.is_file():
        return None
    return copy_path.read_text(encoding="utf-8")


def save_plan_working_copy(plan_id: str, filename: str, content: str) -> bool:
    """保存工作副本（不影响源文件）"""
    copy_path = PLANS_ROOT / plan_id / "scenarios" / filename
    if not copy_path.parent.is_dir():
        return False
    copy_path.write_text(content, encoding="utf-8")
    return True


def list_plan_working_copies(plan_id: str) -> list[dict]:
    """列出计划的全部工作副本"""
    scenarios_dir = PLANS_ROOT / plan_id / "scenarios"
    if not scenarios_dir.is_dir():
        return []
    copies = []
    for f in sorted(scenarios_dir.iterdir()):
        if f.suffix in (".md", ".yaml", ".yml"):
            first_line = f.read_text(encoding="utf-8").split("\n")[0]
            source = ""
            if "源文件:" in first_line:
                source = first_line.split("源文件:")[1].strip().rstrip("）─ ")
            copies.append({
                "filename": f.name,
                "source": source,
                "size": f.stat().st_size,
            })
    return copies
