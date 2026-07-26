"""发布检查（delta 归档前置人工确认清单）。

输出三类待办：
1. 快照场景清单（version 0.x）——归档时需 bump 到 1.0 冻结
2. 未解决的版本漂移/缺失（DRIFT/ORPHANED）——归档前必须清零
3. T6 契约基线一致性——契约变更未 bump version 的场景

用法：
    python release_check.py           # 打印报告；存在阻塞项时退出码 1
"""

import os
import sys

SG_ROOT = os.path.dirname(os.path.abspath(__file__))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.dependency_graph import DependencyGraph  # noqa: E402
from engine.scenario_loader import load_scenarios  # noqa: E402
from engine.versioning import (  # noqa: E402
    check_t6, contract_fingerprint, is_snapshot, load_baseline,
)

SCENARIOS_ROOT = os.path.join(SG_ROOT, "scenarios")


def main():
    scenarios = load_scenarios(SCENARIOS_ROOT)
    graph = DependencyGraph(scenarios)
    baseline = load_baseline(SG_ROOT)

    blockers = 0

    # ── 1. 快照场景（0.x 待冻结）──
    snapshots = [s for s in scenarios if is_snapshot(s.version)]
    print(f"① 快照场景（0.x，归档时需 bump 1.0）: {len(snapshots)} 个")
    for s in snapshots:
        print(f"   - {s.id} v{s.version}  {s.title[:40]}")

    # ── 2. 版本漂移/缺失 ──
    drifts = [i for i in graph.drift_report() if i["status"] in ("major_drift", "orphan")]
    print(f"\n② 未解决的 DRIFT/ORPHANED: {len(drifts)} 条（归档前必须清零）")
    for i in drifts:
        blockers += 1
        hint = "上游已删除/改名，请修正 depends_on" if i["status"] == "orphan" \
            else "请核对上游契约后 bump 期望版本或回退上游变更"
        print(f"   ✗ {i['consumer']} → {i['id']}（期望 {i['expected'] or '(未声明)'} / "
              f"实际 {i['actual'] or '缺失'}）[{i['status']}] {hint}")

    # ── 3. T6 契约基线一致性 ──
    print("\n③ T6 契约基线校验:")
    t6_issues = 0
    for s in scenarios:
        result = check_t6(s.id, contract_fingerprint(s), s.version, baseline)
        if result:
            level, message = result
            if level == "ERROR":
                blockers += 1
                t6_issues += 1
            print(f"   [{level}] {message}")
    if not t6_issues:
        print("   全部通过")

    print(f"\n{'═' * 50}")
    if blockers:
        print(f"发布检查: REJECT（{blockers} 个阻塞项）")
        sys.exit(1)
    print("发布检查: PASS（可归档）")


if __name__ == "__main__":
    main()
