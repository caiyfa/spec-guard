#!/usr/bin/env python3
"""evals/run_baseline.py — Phase 0 基线仪表盘 CLI（T-1042）。

一条命令聚合已落盘信号（会话 JSONL + metrics + audit 库）出七指标基线报告：
  python evals/run_baseline.py                          # 默认主库数据，控制台 + 落盘
  python evals/run_baseline.py --sessions-root <路径>    # 指定会话根
  python evals/run_baseline.py --db <路径>               # 指定 workbench.db
  python evals/run_baseline.py --limit 50                # 只扫前 50 个会话（快速试跑）
  python evals/run_baseline.py --json                    # 只输出 JSON（机器消费）
  python evals/run_baseline.py --no-write                # 不落盘，只打印

产物（evals/results/，不入 git）：
  baseline_report.json    七指标结构化报告（overwrite）
  baseline_report.md      Markdown 仪表盘（overwrite）

默认数据路径：相对仓库根的主库布局（agent/sessions + workbench/backend/data/workbench.db）。
在 worktree 里跑时，--sessions-root/--db 指向主库实际路径即可只读聚合生产数据。
退出码恒 0（这是只读报告器，不是门禁——红绿判断留给 evals/run_evals.py）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from evals.baseline import build_baseline_report, render_markdown  # noqa: E402


def _default_sessions_root() -> Path:
    return SG_ROOT / "agent" / "sessions"


def _default_db() -> Path:
    return SG_ROOT / "workbench" / "backend" / "data" / "workbench.db"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Phase 0 基线仪表盘：聚合已落盘信号出七指标报告（纯读，离线）")
    ap.add_argument("--sessions-root", default=str(_default_sessions_root()),
                    help="会话根目录（默认 agent/sessions；wt 里跑时指向主库该目录）")
    ap.add_argument("--db", default=str(_default_db()),
                    help="workbench.db 路径（含 sf_mcp_call_audit/agent_sessions/audit_log）")
    ap.add_argument("--limit", type=int, default=None,
                    help="只扫前 N 个会话（快速试跑用）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 报告（机器消费）")
    ap.add_argument("--no-write", action="store_true", help="不落盘，只打印")
    args = ap.parse_args(argv)

    report = build_baseline_report(
        sessions_root=args.sessions_root, db_path=args.db, limit=args.limit)
    md = render_markdown(report)

    if not args.no_write:
        out_dir = SG_ROOT / "evals" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "baseline_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "baseline_report.md").write_text(md, encoding="utf-8")
        if not args.json:
            print(f"[baseline] 报告已落盘: {out_dir / 'baseline_report.md'}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
