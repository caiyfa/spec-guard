"""Spec 校验 + TestCase 格式校验服务。

Spec 校验：包装 verify_delta_merge.py 的检查逻辑为可调用的 API。
TestCase 校验：验证测试 YAML 的格式合规性（类型声明/产出声明/连通性）。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from engine.versioning import check_t6, fingerprint_from_raw, load_baseline  # noqa: E402

PROJECT_ROOT = SG_ROOT.parent.parent
SPEC_ROOT = PROJECT_ROOT / "raw" / "spec"
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_delta_merge.py"


# ══════════════════════════════════════════════════════════
# Spec 校验（包装 verify_delta_merge.py）
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
    """列出全部可用的 delta（changes/ 目录）"""
    changes_dir = SPEC_ROOT / "changes"
    if not changes_dir.is_dir():
        return []
    deltas = []
    for d in sorted(changes_dir.iterdir()):
        if not d.is_dir():
            continue
        # 检测是否有 delta 内容
        has_proposal = (d / "proposal.md").is_file()
        has_specs = (d / "delta-specs").is_dir() or (d / "delta-spec.md").is_file()
        has_modules = (d / "modules").is_dir()
        if has_proposal or has_specs or has_modules:
            deltas.append({
                "id": d.name,
                "has_proposal": has_proposal,
                "has_specs": has_specs,
                "has_modules": has_modules,
                "has_yaml_testcases": _has_yaml_testcases(d),
                "path": str(d),
            })
    return deltas


def get_current_delta() -> str:
    """读取 .current-delta 文件"""
    p = PROJECT_ROOT / ".current-delta"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return ""


def run_spec_validation(delta_code: str, mode: str = "create") -> dict:
    """运行 verify_delta_merge.py 并解析输出为结构化结果

    mode: create / pre / post
    返回: {verdict, findings: [{level, vid, message, feature}], raw_output, report_path}
    """
    if not VERIFY_SCRIPT.is_file():
        return {"verdict": "ERROR", "findings": [], "raw_output": f"校验脚本不存在: {VERIFY_SCRIPT}"}

    cmd = [
        sys.executable, str(VERIFY_SCRIPT), mode,
        "--delta", delta_code,
        "--report",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {"verdict": "TIMEOUT", "findings": [], "raw_output": "校验超时（60s）"}
    except Exception as e:
        return {"verdict": "ERROR", "findings": [], "raw_output": str(e)}

    output = proc.stdout + proc.stderr
    findings = _parse_verify_output(output)

    n_err = sum(1 for f in findings if f["level"] == "ERROR")
    n_warn = sum(1 for f in findings if f["level"] == "WARN")
    verdict = "PASS" if n_err == 0 else "REJECT"

    # 找报告路径
    report_path = ""
    delta_dir = SPEC_ROOT / "changes" / delta_code
    latest_report = delta_dir / f"verify-report-{mode}.md"
    if latest_report.is_file():
        report_path = str(latest_report)

    return {
        "verdict": verdict,
        "delta": delta_code,
        "mode": mode,
        "exit_code": proc.returncode,
        "findings": findings,
        "summary": {"error": n_err, "warn": n_warn, "info": sum(1 for f in findings if f["level"] == "INFO")},
        "raw_output": output,
        "report_path": report_path,
    }


def read_validation_report(report_path: str) -> Optional[str]:
    """读取校验报告 MD 内容"""
    if not report_path or not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_verify_output(output: str) -> list[dict]:
    """解析 verify_delta_merge.py 的输出为结构化 findings"""
    findings = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("[FAIL]"):
            findings.append(_parse_finding_line(line, "ERROR"))
        elif line.startswith("[WARN]"):
            findings.append(_parse_finding_line(line, "WARN"))
        elif line.startswith("[INFO]"):
            findings.append(_parse_finding_line(line, "INFO"))
    return findings


def _parse_finding_line(line: str, level: str) -> dict:
    """解析单行 finding: [FAIL] V1 message"""
    # [FAIL] V1 tag: message
    parts = line.split(" ", 2)
    vid = parts[1] if len(parts) > 1 else ""
    message = parts[2] if len(parts) > 2 else line
    return {"level": level, "vid": vid, "message": message}


# ══════════════════════════════════════════════════════════
# TestCase 格式校验
# ══════════════════════════════════════════════════════════

def validate_test_cases(scenarios_root: Optional[str] = None) -> dict:
    """校验全部测试 YAML 的格式合规性

    检查项：
    T1 格式基本：YAML 可解析，有 id/flow 或 verify
    T2 类型声明：test_type 必须为 unit/scenario（缺省推断为 scenario）
    T3 产出声明：unit 类型必须有 output 或 save 声明
    T4 连通性：scenario 类型的 depends_on 必须能解析到已存在的场景
    T5 无孤例：scenario 类型若无 depends_on 且非 prep 标签，告警（疑似孤立场景）
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

        # T2 类型声明
        test_type = raw.get("test_type", "scenario")
        if test_type not in ("unit", "scenario"):
            findings.append({"level": "WARN", "vid": "T2", "scenario": sid,
                             "message": f"test_type='{test_type}' 非法（应为 unit/scenario），按 scenario 处理"})
            test_type = "scenario"

        # T3 产出声明（unit 类型）
        if test_type == "unit":
            has_output = raw.get("output") or raw.get("produces")
            has_save = any(
                isinstance(step, dict) and any(
                    isinstance(body, dict) and body.get("save")
                    for body in step.values()
                )
                for step in flow
            )
            if not has_output and not has_save:
                findings.append({"level": "WARN", "vid": "T3", "scenario": sid,
                                 "message": "unit 类型无 output/produces 声明，也无 save 变量——下游无法引用产出"})

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

        # T5 无孤例（scenario 类型无依赖且非 prep 标签）
        tags = raw.get("tags") or []
        if test_type == "scenario" and not deps and "prep" not in tags:
            findings.append({"level": "WARN", "vid": "T5", "scenario": sid,
                             "message": "scenario 类型无 depends_on 且非 prep 标签——疑似孤立场景，建议声明依赖或标记 prep"})

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
