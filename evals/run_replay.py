#!/usr/bin/env python3
"""evals/run_replay.py — 通道 A 生产会话轨迹重放打分 CLI（T-1042）。

一条命令对生产会话做轨迹重放打分（不重跑只打分）+ 路径重放（flow 图比对）+ 反向导出：

  python evals/run_replay.py                                    # 全量五维打分，控制台+落盘
  python evals/run_replay.py --sessions-root <主库会话目录>      # 指定会话根
  python evals/run_replay.py --only-generate                    # 只统计「创建测试用例」会话
  python evals/run_replay.py --limit 50                         # 只扫前 50 个（快速试跑）
  python evals/run_replay.py --json                             # 只输出 JSON（机器消费）
  python evals/run_replay.py --trace <会话.jsonl>               # 单会话路径重放（§16.1 flow 图比对，mermaid+差异表）
  python evals/run_replay.py --trace-all                        # 全部生成会话批量路径重放落盘 traces/
  python evals/run_replay.py --export <会话jsonl> --export-out <case.json>  # 反向导出 golden case
  python evals/run_replay.py --no-write                         # 不落盘，只打印

产物（evals/results/，不入 git）：
  replay_report.json     五维信号结构化报告（overwrite）
  replay_report.md       Markdown 报告（overwrite）
  traces/{sid}.md        路径重放报告（--trace-all；含着色 mermaid + 差异明细）
  traces/index.md        按差异数降序的索引

与 evals/run_evals.py（通道 B golden case 回放门禁）分工：本脚本是回顾性度量
（读真实会话打分），退出码恒 0 不挂门禁；通道 B 是前瞻性守门（退出码 0/1 挂 CI）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from evals.export_case import export_to_file  # noqa: E402
from evals.flowpath import render_trace_markdown, trace_all_generate, trace_session  # noqa: E402
from evals.replay import render_replay_markdown, replay_report  # noqa: E402


def _default_sessions_root() -> Path:
    return SG_ROOT / "agent" / "sessions"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="通道 A：生产会话轨迹重放打分（五维）+ 路径重放（§16.1 flow 图比对）+ 反向导出")
    ap.add_argument("--sessions-root", default=str(_default_sessions_root()),
                    help="会话根目录（默认 agent/sessions；wt 里跑时指向主库）")
    ap.add_argument("--only-generate", action="store_true",
                    help="只统计识别为「创建测试用例」的会话")
    ap.add_argument("--limit", type=int, default=None, help="只扫前 N 个会话")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 报告")
    ap.add_argument("--no-write", action="store_true", help="不落盘只打印")
    ap.add_argument("--trace", metavar="SESSION_JSONL", default=None,
                    help="单会话路径重放：对照 §16.1 flow 图逐节点比对，输出着色 mermaid + 差异明细")
    ap.add_argument("--trace-all", action="store_true",
                    help="全部生成会话批量路径重放（落盘 evals/results/traces/，索引按差异数降序）")
    ap.add_argument("--export", metavar="SESSION_JSONL", default=None,
                    help="反向导出指定会话为 golden case（配合 --export-out）")
    ap.add_argument("--export-out", metavar="CASE_JSON", default=None,
                    help="golden case 输出路径（配合 --export）")
    ap.add_argument("--export-id", default=None, help="导出 case 的 ID（可选）")
    args = ap.parse_args(argv)

    # 单会话路径重放
    if args.trace:
        trace = trace_session(args.trace)
        if trace is None:
            print(f"错误：会话解析失败: {args.trace}", file=sys.stderr)
            return 2
        print(render_trace_markdown(trace))
        return 0

    # 批量路径重放
    if args.trace_all:
        out_dir = SG_ROOT / "evals" / "results" / "traces"
        summary = trace_all_generate(args.sessions_root, out_dir, limit=args.limit)
        print(f"[trace-all] 已重放 {summary['traced']} 个生成会话 → {out_dir}\\index.md"
              f"（按差异数降序，最跑偏的排最前）")
        for r in summary["index"][:10]:
            print(f"  {r['session_id']}  差异 {r['deviations']}（缺失 {r['missing']} / 乱序 {r['out_of_order']}）")
        return 0

    # 反向导出模式
    if args.export:
        if not args.export_out:
            print("错误：--export 需配合 --export-out 指定输出路径", file=sys.stderr)
            return 2
        out = export_to_file(args.export, args.export_out, case_id=args.export_id)
        print(f"[export] golden case 已导出: {out}")
        print("[export] ⚠ 导出即起点：请人工评审（删错误步骤/收紧 expect/标注 verdict）后再入 evals/cases/")
        return 0

    report = replay_report(args.sessions_root,
                           only_generate=args.only_generate, limit=args.limit)
    md = render_replay_markdown(report)

    if not args.no_write:
        out_dir = SG_ROOT / "evals" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "replay_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "replay_report.md").write_text(md, encoding="utf-8")
        if not args.json:
            print(f"[replay] 报告已落盘: {out_dir / 'replay_report.md'}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
