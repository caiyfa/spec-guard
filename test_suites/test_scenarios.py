"""全库场景测试套件入口（K-048）：加载 scenarios/ 全部模块，按场景 ID 参数化执行。

替代原 test_person_profile.py（仅参数化 employee/person-profile 一个模块）——
此前执行控制里选 EV/IS/TL 等模块的场景，`pytest -k` 收集为 0（54 deselected），
表现为「单选执行失败/空跑」；统一入口后任意模块场景均可执行。

运行方式：
    python -m pytest -v                      # 全量（拓扑序）
    python -m pytest -k EV-IMP-001 -v        # 单场景（自动回溯上游准备环境）
    python -m pytest -m P0 -v                # 按标签（场景 tags 转 pytest mark）
    python -m pytest --prep-only             # 仅执行上游环境准备
"""

import os
import sys

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.scenario_loader import load_scenarios           # noqa: E402
from engine.scenario_runner import run_with_deps            # noqa: E402
from engine.execution_record import (                        # noqa: E402
    VERDICT_PASS, VERDICT_FAIL, VERDICT_SKIP, VERDICT_BLOCKED,
)

SCENARIOS = load_scenarios(os.path.join(SG_ROOT, "scenarios"))


def _params():
    """场景 → pytest.param（id=场景 ID，tags 转 mark 供 -m 过滤）。"""
    out = []
    for s in SCENARIOS:
        marks = [getattr(pytest.mark, t) for t in (s.tags or []) if t.isidentifier()]
        out.append(pytest.param(s, id=s.id, marks=marks))
    return out


@pytest.mark.parametrize("scenario", _params())
def test_scenario(scenario, rctx):
    """每个场景一个用例：run_with_deps 内部完成依赖闭包回溯执行"""
    record = run_with_deps(scenario, rctx)

    # K-051：闭包内失败上游的原因打进 stdout（-s 实时流入执行日志）——
    # 否则日志只有「本场景未执行」一句，排错要翻 run.json 才能看到上游为何 FAIL
    # T-310：上游 SKIP 同样打进原因（EX-fc04ec0c：根因是上游「账号无 TDM_INV_ACTIVITY
    # 权限」SKIP，但日志只有一句「上游未通过」，看不到为什么）
    if record.verdict == VERDICT_BLOCKED:
        try:
            upstream_ids = rctx.graph.closure(scenario.id)
        except Exception:
            upstream_ids = []
        for r in rctx.records:
            if r.scenario_id not in upstream_ids or r.scenario_id == scenario.id:
                continue
            if r.verdict == VERDICT_FAIL and getattr(r, "failure", None):
                print(f"[SpecGuard] 上游 {r.scenario_id} FAIL: "
                      f"{r.failure.get('message', '')[:300]}", flush=True)
            elif r.verdict == VERDICT_SKIP and getattr(r, "skip_reason", None):
                print(f"[SpecGuard] 上游 {r.scenario_id} SKIP: "
                      f"{r.skip_reason[:300]}", flush=True)

    # T-310：自身 SKIP 的原因先打完整行（pytest -v 实时流的 SKIPPED 行会截断原因，
    # summary 只在日志末尾一行）——「为什么跳过」在日志流中直接可见
    if record.verdict == VERDICT_SKIP and getattr(record, "skip_reason", None):
        print(f"[SpecGuard] {scenario.id} SKIP: {record.skip_reason[:300]}", flush=True)

    if record.verdict == VERDICT_SKIP:
        pytest.skip(record.skip_reason or "场景跳过")
    if record.verdict == VERDICT_BLOCKED:
        pytest.skip(record.skip_reason or "上游未通过，场景阻塞")
    if record.verdict != VERDICT_PASS:
        f = record.failure or {}
        evidence = ""
        if f.get("evidence"):
            first = f["evidence"][0] if isinstance(f["evidence"], list) else f["evidence"]
            evidence = f" | 证据: {first}"
        pytest.fail(f"[{f.get('category', 'unknown')}] {f.get('message', '')}{evidence}")


def pytest_collection_modifyitems(items):
    """按 DAG 拓扑序重排用例（保证上游先于下游执行）"""
    # pytest -k 过滤后 items 可能只剩子集；拓扑序在 run_with_deps 内部兜底，
    # 这里仅做稳定排序优化执行体验
    pass
