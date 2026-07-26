"""全景档案测试套件入口：加载 scenarios/employee/person-profile/，按 DAG 序参数化执行。

运行方式：
    pytest tests/specguard                      # 全量（拓扑序）
    pytest tests/specguard -k PP-RC-005         # 单场景（自动回溯上游准备环境）
    pytest tests/specguard --prep-only          # 仅执行上游环境准备
"""

import os
import sys

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.scenario_loader import load_module_scenarios   # noqa: E402
from engine.scenario_runner import run_with_deps           # noqa: E402
from engine.execution_record import (                       # noqa: E402
    VERDICT_PASS, VERDICT_SKIP, VERDICT_BLOCKED,
)

MODULE_PATH = os.path.join("employee", "person-profile")
SCENARIOS = load_module_scenarios(os.path.join(SG_ROOT, "scenarios"), MODULE_PATH)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_person_profile_scenario(scenario, rctx):
    """每个场景一个用例：run_with_deps 内部完成依赖闭包回溯执行"""
    record = run_with_deps(scenario, rctx)

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
