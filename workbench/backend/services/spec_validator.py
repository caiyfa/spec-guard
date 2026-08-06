"""Spec 校验 + TestCase 格式校验服务。

Spec 校验：调用 specstd.conformance 原生合规校验器（V1–V6 原生重写）。
TestCase 校验：验证测试 YAML 的格式合规性（类型声明/产出声明/连通性）。
"""

import os
import sys
from pathlib import Path
from typing import Optional

import yaml

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from engine.versioning import check_t6, fingerprint_from_raw, load_baseline  # noqa: E402
from specstd.workspace import get_active_workspace  # noqa: E402
from specstd.conformance import check_conformance  # noqa: E402


def _get_spec_root() -> Optional[Path]:
    """获取当前激活工作区的根路径。"""
    ws = get_active_workspace()
    return ws.root if ws else None


# ══════════════════════════════════════════════════════════
# Spec 校验（specstd.conformance 原生实现）
# ══════════════════════════════════════════════════════════

def _has_yaml_testcases(delta_dir: Path) -> bool:
    """检测 delta 目录是否包含 YAML 测试用例文件"""
    # test-cases/ 子目录
    tc = delta_dir / "test-cases"
    if tc.is_dir() and (list(tc.rglob("*.yaml")) or list(tc.rglob("*.yml"))):
        return True
    # 根目录 YAML（排除配置类）
    for f in delta_dir.glob("*.yaml"):
        if not f.name.startswith("_") and f.name not in ("api.yaml", "e2e-cases.yaml"):
            return True
    return False


def list_deltas() -> list[dict]:
    """列出全部可用的 delta（当前工作区 changes/ 目录）"""
    spec_root = _get_spec_root()
    if not spec_root:
        return []
    changes_dir = spec_root / "changes"
    if not changes_dir.is_dir():
        return []
    deltas = []
    for d in sorted(changes_dir.iterdir()):
        if not d.is_dir():
            continue
        has_proposal = (d / "proposal.md").is_file()
        has_delta_spec = (d / "delta-spec.md").is_file()
        has_manifest = (d / "delta.manifest.yaml").is_file()
        if has_proposal or has_delta_spec or has_manifest:
            deltas.append({
                "id": d.name,
                "has_proposal": has_proposal,
                "has_delta_spec": has_delta_spec,
                "has_manifest": has_manifest,
                "has_yaml_testcases": _has_yaml_testcases(d),
                "path": str(d),
            })
    return deltas


def get_current_delta() -> str:
    """读取 .current-delta 文件（当前工作区根）"""
    spec_root = _get_spec_root()
    if not spec_root:
        return ""
    p = spec_root / ".current-delta"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return ""


def run_spec_validation(delta_code: str = "", mode: str = "create") -> dict:
    """运行合规校验（specstd.conformance 原生实现，含 V1–V6）

    mode 参数保留兼容性，实际全量校验。
    返回: {verdict, findings, summary, raw_output, report_path}
    """
    ws = get_active_workspace()
    if not ws:
        return {"verdict": "ERROR", "findings": [], "raw_output": "无激活的工作区"}

    report = check_conformance(ws.root, ws.name)

    # 如果指定了 delta_code，过滤只保留该 delta 的 findings
    if delta_code:
        delta_findings = [
            f for f in report.findings
            if delta_code in f.path or delta_code in str(f.detail)
        ]
    else:
        delta_findings = report.findings

    return {
        "verdict": report.verdict,
        "delta": delta_code,
        "mode": mode,
        "findings": [f.to_dict() for f in delta_findings],
        "summary": report.summary,
        "raw_output": "",
        "report_path": "",
    }


def read_validation_report(report_path: str) -> Optional[str]:
    """读取校验报告 MD 内容"""
    if not report_path or not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return f.read()



# ══════════════════════════════════════════════════════════
# TestCase 格式校验
# ══════════════════════════════════════════════════════════

def validate_test_cases(scenarios_root: Optional[str] = None) -> dict:
    """校验全部测试 YAML 的格式合规性

    检查项：
    T1 格式基本：YAML 可解析，有 id/flow 或 verify
    T4 连通性：depends_on 必须能解析到已存在的场景
    T5 无孤例：无 depends_on 且非 prep 标签，告警（疑似孤立场景）
    """
    root = scenarios_root or str(SG_ROOT / "scenarios")
    if not os.path.isdir(root):
        return {"verdict": "ERROR", "findings": [], "message": f"场景目录不存在: {root}"}

    # 先收集全部场景 ID
    all_ids = set()
    scenarios = []
    for dirpath, _dirs, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                scenarios.append({"path": path, "id": fn, "error": f"YAML 解析失败: {e}"})
                continue
            sid = raw.get("id", fn)
            all_ids.add(sid)
            scenarios.append({"path": path, "id": sid, "raw": raw})

    findings = []

    for sc in scenarios:
        sid = sc["id"]
        rel_path = os.path.relpath(sc["path"], root)

        # T1 格式基本
        if "error" in sc:
            findings.append({"level": "ERROR", "vid": "T1", "scenario": sid, "message": sc["error"]})
            continue

        raw = sc["raw"]
        flow = raw.get("flow") or []
        verify = raw.get("verify") or []

        if not flow and not verify:
            findings.append({"level": "ERROR", "vid": "T1", "scenario": sid,
                             "message": "flow/verify 均为空，场景不可执行"})

        # T4 连通性：depends_on 引用必须存在
        deps = raw.get("depends_on") or []
        for d in deps:
            dep_id = d if isinstance(d, str) else d.get("id", "")
            if dep_id and dep_id not in all_ids:
                findings.append({"level": "ERROR", "vid": "T4", "scenario": sid,
                                 "message": f"depends_on 引用不存在的场景: {dep_id}"})

        # T7 版本期望提示：依赖未声明 version（接受任意版本，建议显式锁定）
        for d in deps:
            if isinstance(d, str):
                findings.append({"level": "WARN", "vid": "T7", "scenario": sid,
                                 "message": f"依赖 {d} 未声明版本期望（接受任意版本），建议补 version: ^X"})
            elif isinstance(d, dict) and d.get("id") and d.get("version") is None:
                findings.append({"level": "WARN", "vid": "T7", "scenario": sid,
                                 "message": f"依赖 {d['id']} 未声明版本期望（接受任意版本），建议补 version: ^X"})

        # T5 无孤例（无依赖且非 prep 标签）
        tags = raw.get("tags") or []
        if not deps and "prep" not in tags:
            findings.append({"level": "WARN", "vid": "T5", "scenario": sid,
                             "message": "无 depends_on 且非 prep 标签——疑似孤立场景，建议声明依赖或标记 prep"})

    # T6 契约指纹与版本一致性（契约变更必须 bump version）
    baseline = load_baseline(str(SG_ROOT))
    for sc in scenarios:
        if "raw" not in sc or "error" in sc:
            continue
        raw = sc["raw"]
        result = check_t6(
            sc["id"],
            fingerprint_from_raw(raw),
            str(raw.get("version", "0.1")),
            baseline,
        )
        if result:
            level, message = result
            findings.append({"level": level, "vid": "T6", "scenario": sc["id"], "message": message})

    n_err = sum(1 for f in findings if f["level"] == "ERROR")
    n_warn = sum(1 for f in findings if f["level"] == "WARN")
    verdict = "PASS" if n_err == 0 else "REJECT"

    return {
        "verdict": verdict,
        "total_scenarios": len(scenarios),
        "findings": findings,
        "summary": {"error": n_err, "warn": n_warn},
    }
