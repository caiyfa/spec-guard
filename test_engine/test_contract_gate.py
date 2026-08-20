"""ENG-T02 契约版本门禁强化：传递依赖仲裁 / strict 语义 / DRIFT 消息。

覆盖 ENG-BUG-002③④（传递依赖不校验 / DRIFT 消息为空与 strict 语义反了）+
ENG-BUG-010（传递孤儿依赖运行期崩溃）。全部离线（内存 Scenario + DependencyGraph，
无网络/DB）。

设计依据：docs/架构升级/ENG-T02-契约版本门禁强化.md §6。
"""

import os
import sys

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.dependency_graph import DependencyGraph
from engine.execution_record import (  # noqa: E402
    VERDICT_BLOCKED, VERDICT_DRIFT, VERDICT_FAIL, VERDICT_ORPHANED,
)
from engine.registry import Registry  # noqa: E402
from engine.scenario_loader import Scenario  # noqa: E402
from engine.scenario_runner import RunContext, register_builtin_steps, run_with_deps  # noqa: E402
from engine.versioning import check_t6, contract_fingerprint  # noqa: E402


def _make_rctx(graph, strict=False):
    reg = Registry()
    register_builtin_steps(reg)
    return RunContext(
        registry=reg, env_config={}, token_provider=None, graph=graph,
        run_dir=".", strict_deps=strict,
    )


def _dep(sid, version=None, optional=False):
    return {"id": sid, "mode": "shared", "version": version, "optional": optional}


def _sc(sid, version="0.1", depends_on=None):
    return Scenario(id=sid, title=sid, version=version,
                    depends_on=depends_on or [],
                    flow=[{"set_var": {"vars": {"ok": 1}}}], verify=[])


# ══════════════════════════════════════════════════════════
# 1. 链 A→B→C（C 不存在）→ 跑 A：B 得 ORPHANED 记录（含 failure.message），A BLOCKED，无异常
# ══════════════════════════════════════════════════════════

def test_transitive_orphan_propagates_blocked_not_crash():
    a = _sc("A", depends_on=[_dep("B")])
    b = _sc("B", depends_on=[_dep("C")])
    rctx = _make_rctx(DependencyGraph([a, b]))
    rec = run_with_deps(a, rctx)   # 此前：_acquire_instance 里 by_id[C] → 裸 KeyError 冒泡（pytest ERROR）
    assert rec.verdict == VERDICT_BLOCKED, f"A 应 BLOCKED，实际 {rec.verdict}"
    b_recs = [r for r in rctx.records if r.scenario_id == "B"]
    assert b_recs, "B 应留下 ORPHANED 记录（此前直接崩溃无记录）"
    assert b_recs[0].verdict == VERDICT_ORPHANED
    assert b_recs[0].failure and "C" in b_recs[0].failure["message"], \
        f"B 的 failure.message 应指明 C 缺失: {b_recs[0].failure}"
    assert b_recs[0].upstream_of == "A"


# ══════════════════════════════════════════════════════════
# 2. 链 A→B→C，B 对 C 声明 ^2 而 C 实为 v1 → B 得 DRIFT 记录，A BLOCKED
# ══════════════════════════════════════════════════════════

def test_transitive_drift_recorded_consumer_blocked():
    c = _sc("C", version="1.0")
    b = _sc("B", depends_on=[_dep("C", version="^2")])
    a = _sc("A", depends_on=[_dep("B")])
    rctx = _make_rctx(DependencyGraph([c, b, a]))
    rec = run_with_deps(a, rctx)   # 此前：深层漂移完全不被检查（B 直接执行）
    assert rec.verdict == VERDICT_BLOCKED
    b_recs = [r for r in rctx.records if r.scenario_id == "B"]
    assert b_recs and b_recs[0].verdict == VERDICT_DRIFT, \
        f"B 应留下 DRIFT 记录，实际 {[r.verdict for r in rctx.records]}"
    assert b_recs[0].failure["category"] == "contract_drift"
    assert "^2" in b_recs[0].failure["message"]


# ══════════════════════════════════════════════════════════
# 3. strict_deps=True 时 MAJOR 漂移 → verdict=FAIL（category=contract_drift）而非 BLOCKED
# ══════════════════════════════════════════════════════════

def test_strict_major_drift_becomes_fail():
    b = _sc("B", version="1.0")
    a = _sc("A", depends_on=[_dep("B", version="^2")])
    rctx = _make_rctx(DependencyGraph([b, a]), strict=True)
    rec = run_with_deps(a, rctx)
    assert rec.verdict == VERDICT_FAIL, \
        f"strict 下漂移应 FAIL（此前 BLOCKED 走 pytest.skip 反而放过漂移），实际 {rec.verdict}"
    assert rec.failure["category"] == "contract_drift"
    assert "^2" in rec.failure["message"]


# ══════════════════════════════════════════════════════════
# 4. 非 strict 时 DRIFT verdict 的 record.failure.message 非空（pytest [unknown] 消息消失）
# ══════════════════════════════════════════════════════════

def test_drift_verdict_has_failure_message():
    b = _sc("B", version="1.0")
    a = _sc("A", depends_on=[_dep("B", version="^2")])
    rctx = _make_rctx(DependencyGraph([b, a]))
    rec = run_with_deps(a, rctx)
    assert rec.verdict == VERDICT_DRIFT
    assert rec.failure and rec.failure["message"].strip(), \
        "DRIFT 记录必须带完整失败消息（此前 _verdict_record 不填 failure → pytest 只打 [unknown]）"
    assert "^2" in rec.failure["message"]


# ══════════════════════════════════════════════════════════
# 5. 改 verify 一条断言的预期 → contract_fingerprint 变化；check_t6 对旧基线报 ERROR
# ══════════════════════════════════════════════════════════

def test_fingerprint_sensitive_to_verify_change():
    flow = [{"call": {"method": "GET", "path": "/api/x", "save": "resp"}}]
    sc_null = Scenario(id="FP-1", flow=flow, doc={"covers": ["FR-001"]},
                       verify=[{"json": {"of": "resp", "path": "$.data.status", "eq": None}}])
    sc_zero = Scenario(id="FP-1", flow=flow, doc={"covers": ["FR-001"]},
                       verify=[{"json": {"of": "resp", "path": "$.data.status", "eq": 0}}])
    fp_null, fp_zero = contract_fingerprint(sc_null), contract_fingerprint(sc_zero)
    assert fp_null != fp_zero, "改断言预期必须改变契约指纹（此前 eq:null→eq:0 指纹不变，T6 漏报）"
    level, msg = check_t6("FP-1", fp_zero, "0.1",
                          {"FP-1": {"version": "0.1", "fingerprint": fp_null}})
    assert level == "ERROR" and "未 bump" in msg
