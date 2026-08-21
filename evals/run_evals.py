"""evals.run_evals — 评测入口（一条命令跑全量 eval）。

用法（仓库根目录）：
  python evals/run_evals.py                    # 跑 evals/cases/ 全部 golden case
  python evals/run_evals.py evals/cases/001-*.json   # 跑指定 case
  python evals/run_evals.py --list             # 只列 case 不跑

产物（evals/results/，不入 git）：
  metrics.jsonl   每次 case 一行，含工具维度（调用序列/成功率/步数/耗时），append
  report.md       本次运行全量断言报告，overwrite
退出码：全部通过 0，任一失败 1（可挂 CI / pre-push）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from evals.harness import load_case, run_golden_case  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _collect_cases(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    return sorted(CASES_DIR.glob("*.json"))


def _append_metrics(results_dir: Path, result) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "eval_id": result.case_id,
        "case_file": Path(result.case_file).name if result.case_file else "",
        "passed": result.passed,
        **result.metrics,
        "failures": [
            {"type": f.type, "name": f.name, "detail": f.detail}
            for f in result.failures
        ],
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "metrics.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _write_report(results_dir: Path, results, started_at: str) -> None:
    lines = [
        "# Agent 评测报告",
        "",
        f"- 运行时间：{started_at}",
        f"- 用例数：{len(results)}，通过 {sum(1 for r in results if r.passed)}，"
        f"失败 {sum(1 for r in results if not r.passed)}",
        "",
        "| 用例 | 结果 | 轮次 | 工具步数 | 工具序列 | 成功率 | 耗时ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m = r.metrics
        lines.append(
            f"| {r.case_id} | {'✅ PASS' if r.passed else '❌ FAIL'} "
            f"| {m.get('turns')} | {m.get('steps')} "
            f"| {'→'.join(m.get('tools_sequence') or []) or '（无）'} "
            f"| {m.get('tool_success_rate')} | {m.get('duration_ms')} |")
    for r in results:
        if r.passed:
            continue
        lines += [f"\n## {r.case_id} 失败明细", ""]
        for f in r.failures:
            lines.append(f"- **[{f.type}] {f.name}**：{f.detail}")
        dump = results_dir / f"{r.case_id}.messages.json"
        dump.write_text(json.dumps(r.messages, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        lines.append(f"- 完整消息链已落盘：`{dump}`")
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "report.md").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SpecGuard Agent 评测（T-980）")
    parser.add_argument("cases", nargs="*", help="golden case JSON 路径（缺省跑全部）")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR),
                        help="结果目录（默认 evals/results/）")
    parser.add_argument("--list", action="store_true", help="只列出 case 不执行")
    args = parser.parse_args(argv)

    case_paths = _collect_cases(args.cases)
    if not case_paths:
        print(f"未发现 golden case（{CASES_DIR}/*.json）")
        return 1
    if args.list:
        for p in case_paths:
            case = load_case(p)
            print(f"{case['id']}\t{case.get('name', '')}\t{p}")
        return 0

    started_at = datetime.now().isoformat(timespec="seconds")
    results = []
    for p in case_paths:
        case = load_case(p)
        result = run_golden_case(case)
        results.append(result)
        _append_metrics(Path(args.results_dir), result)
        m = result.metrics
        mark = "PASS" if result.passed else "FAIL"
        print(f"[{mark}] {result.case_id} {case.get('name', '')} "
              f"(turns={m['turns']}, steps={m['steps']}, "
              f"tools={'→'.join(m['tools_sequence']) or '无'}, "
              f"ok_rate={m['tool_success_rate']}, {m['duration_ms']}ms)")
        for f in result.failures:
            print(f"       └─ [{f.type}] {f.name}: {f.detail[:200]}")

    _write_report(Path(args.results_dir), results, started_at)
    n_pass = sum(1 for r in results if r.passed)
    print(f"\n合计：{n_pass}/{len(results)} 通过；"
          f"metrics → {Path(args.results_dir) / 'metrics.jsonl'}，"
          f"报告 → {Path(args.results_dir) / 'report.md'}")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
