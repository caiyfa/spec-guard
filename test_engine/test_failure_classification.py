"""ENG-T01 失败归类体系改造：7 个离线（mock）失败测试。

覆盖 ENG-BUG-001（分类常量大半闲置 / 场景错误误归因 env）/ ENG-BUG-012（断言 of 写错中断全部断言）。
全部不依赖网络/DB，使用最小 RunContext + 内存场景对象。

设计依据：docs/架构升级/ENG-T01-失败归类体系改造.md §6。
"""

import os
import sys

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

import pytest

from engine.execution_record import (
    ExecutionRecord,
    VERDICT_FAIL, VERDICT_SKIP, VERDICT_BLOCKED,
    CAT_SCENARIO, CAT_UPSTREAM,   # CAT_SCENARIO 为新增常量；CAT_UPSTREAM 改造后实际赋值
)
from engine.scenario_loader import Scenario
from engine.scenario_runner import (
    run_scenario, run_with_deps, RunContext, register_builtin_steps,
    SkipScenario, ScenarioScriptError,
)
from engine.registry import Registry


# ══════════════════════════════════════════════════════════
# 最小运行上下文（离线，无网络/DB）
# ══════════════════════════════════════════════════════════

def _make_rctx(http_client=None, dbs=None, db=None, graph=None):
    """构造最小 RunContext：注册内置步骤，无 DB/网络。

    http_client: 可选假客户端（call/poll 步骤用）；不传则仅支持 set_var/tool/db_query(缺失→SKIP)。
    graph:       可选假依赖图（run_with_deps 用）。
    """
    reg = Registry()
    register_builtin_steps(reg)
    rc = RunContext(
        registry=reg, env_config={}, token_provider=None,
        graph=graph, run_dir=".", dbs=dbs if dbs is not None else {}, db=db,
    )
    if http_client is not None:
        rc.http_client = lambda account, service="tdm": http_client
    return rc


# ══════════════════════════════════════════════════════════
# 1. 未定义变量 → scenario_error（不是 env_error）
# ══════════════════════════════════════════════════════════

def test_undefined_variable_classified_scenario_error():
    rctx = _make_rctx()
    sc = Scenario(id="T1", title="未定义变量",
                  flow=[{"set_var": {"vars": {"v": "{{nonexistent.x}}"}}}],
                  verify=[])
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_FAIL
    assert rec.failure["category"] == CAT_SCENARIO, (
        f"未定义变量应归 scenario_error，实际 {rec.failure['category']}")


# ══════════════════════════════════════════════════════════
# 2. 未注册 tool → scenario_error
# ══════════════════════════════════════════════════════════

def test_unregistered_tool_classified_scenario_error():
    rctx = _make_rctx()
    sc = Scenario(id="T2", title="未注册 tool",
                  flow=[{"tool": {"use": "not_a_real_tool"}}],
                  verify=[])
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_FAIL
    assert rec.failure["category"] == CAT_SCENARIO, (
        f"未注册 tool 应归 scenario_error，实际 {rec.failure['category']}")


# ══════════════════════════════════════════════════════════
# 3. json 断言 jsonpath 拼错 → 该断言 FAIL 落 trace，verdict=FAIL，category=scenario_error
# ══════════════════════════════════════════════════════════

def test_json_assertion_malformed_path_scenario_error():
    rctx = _make_rctx()
    sc = Scenario(id="T3", title="jsonpath 拼错",
                  flow=[{"set_var": {"vars": {"resp": {"json": {"data": {"status": "DONE"}},
                                                        "status": 200}}}}],
                  verify=[{"json": {"of": "resp", "path": "$.data..", "eq": "DONE"}}])
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_FAIL
    assert rec.failure["category"] == CAT_SCENARIO, (
        f"jsonpath 语法错误应归 scenario_error，实际 {rec.failure['category']}")
    # 断言原地落 trace（不是整个场景只剩一条 env_error）
    assert len(rec.assertions) == 1, f"应落 1 条断言 trace，实际 {len(rec.assertions)}"
    assert rec.assertions[0].passed is False


# ══════════════════════════════════════════════════════════
# 4. 断言 of 写错 → 该断言 FAIL + scenario_error，且同场景后续断言照常执行（不中断）
# ══════════════════════════════════════════════════════════

def test_assertion_of_typo_does_not_abort_others():
    rctx = _make_rctx()
    flow = [{"set_var": {"vars": {"resp": {"json": {"data": {"status": "DONE"}},
                                                   "status": 200}}}}]
    verify = [
        {"json": {"of": "typo_var", "path": "$.data.status", "eq": "DONE"}},  # of 写错 → KeyError
        {"json": {"of": "resp", "path": "$.data.status", "eq": "DONE"}},       # 应正常通过
    ]
    sc = Scenario(id="T4", title="of 写错不中断", flow=flow, verify=verify)
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_FAIL
    assert rec.failure["category"] == CAT_SCENARIO, (
        f"of 写错应归 scenario_error，实际 {rec.failure['category']}")
    # 关键：两条断言都应落 trace，后续断言不中断
    assert len(rec.assertions) == 2, f"两条断言都应落 trace，实际 {len(rec.assertions)}"
    assert rec.assertions[0].passed is False
    assert rec.assertions[1].passed is True


# ══════════════════════════════════════════════════════════
# 5. python 步骤脚本异常 → scenario_error；脚本内 SkipScenario → 仍为 SKIP
# ══════════════════════════════════════════════════════════

def test_python_step_runtime_error_scenario_error():
    rctx = _make_rctx()
    sc = Scenario(id="T5a", title="python 脚本异常",
                  flow=[{"python": {"script": "raise RuntimeError('boom')"}}],
                  verify=[])
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_FAIL
    assert rec.failure["category"] == CAT_SCENARIO, (
        f"python 脚本异常应归 scenario_error，实际 {rec.failure['category']}")


def test_python_step_skip_scenario_still_skip():
    rctx = _make_rctx()
    sc = Scenario(id="T5b", title="python 内 SkipScenario",
                  flow=[{"python": {"script": "raise SkipScenario('无候选', category='pool_empty')"}}],
                  verify=[])
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_SKIP
    assert rec.skip_reason == "无候选"
    assert rec.skip_category == "pool_empty"


# ══════════════════════════════════════════════════════════
# 6. 上游 FAIL 的场景 → verdict=BLOCKED 且 skip_category == upstream_blocked
# ══════════════════════════════════════════════════════════

class _FakeGraph:
    """最小依赖图：仅提供 by_id 与 dep_status（run_with_deps 所需）。"""
    dep_status = {}

    def __init__(self, by_id):
        self.by_id = by_id


def test_upstream_failure_marks_blocked_with_upstream_category():
    reg = Registry()
    register_builtin_steps(reg)
    # 上游场景：引用未定义变量 → FAIL
    upstream = Scenario(id="UP-FAIL", title="上游失败",
                        flow=[{"set_var": {"vars": {"x": "{{undefined.var}}"}}}],
                        verify=[])
    target = Scenario(id="T6", title="依赖上游",
                      depends_on=[{"id": "UP-FAIL", "mode": "shared"}],
                      flow=[{"set_var": {"vars": {"y": 1}}}],
                      verify=[])
    graph = _FakeGraph({"UP-FAIL": upstream, "T6": target})
    rctx = _make_rctx(graph=graph)
    rec = run_with_deps(target, rctx)
    assert rec.verdict == VERDICT_BLOCKED
    assert rec.skip_category == CAT_UPSTREAM, (
        f"上游失败应置 upstream_blocked，实际 {rec.skip_category}")


# ══════════════════════════════════════════════════════════
# 7. DB 连接缺失的 db_query → 仍为 SKIP / db_unavailable（诚实语义回归保护）
# ══════════════════════════════════════════════════════════

def test_db_query_without_connection_stays_skip():
    rctx = _make_rctx(dbs={}, db=None)   # 无 default 连接 → 诚实 SKIP
    sc = Scenario(id="T7", title="DB 缺失",
                  flow=[{"db_query": {"sql": "SELECT 1", "save": "rows"}}],
                  verify=[])
    rec = run_scenario(sc, rctx)
    assert rec.verdict == VERDICT_SKIP
    assert rec.skip_category == "db_unavailable"
