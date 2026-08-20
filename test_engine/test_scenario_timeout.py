"""ENG-T03 场景级软看门狗：SG_SCENARIO_TIMEOUT（秒，默认 300）。

覆盖验收 §6.6：多步骤场景在步骤边界被 ScenarioTimeout 中断（verdict=FAIL、
env_error、消息带超时提示）；poll 轮询同样受场景阈值约束；阈值随场景恢复不跨场景泄漏。
全部离线（python 步骤 + 假客户端 poll）。

设计依据：docs/架构升级/ENG-T03-HTTP重试与超时看门狗.md §3.3/§6.6。
"""

import os
import sys
import time
from types import SimpleNamespace

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.execution_record import CAT_ENV  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.scenario_loader import Scenario  # noqa: E402
from engine.scenario_runner import RunContext, register_builtin_steps, run_scenario  # noqa: E402
from engine import scenario_runner  # noqa: E402


def _rctx(client=None):
    reg = Registry()
    register_builtin_steps(reg)
    rc = RunContext(registry=reg, env_config={}, token_provider=None, graph=None, run_dir=".")
    if client is not None:
        rc.http_client = lambda acc, service="tdm": client
    return rc


_SLEEP_STEP = {"python": {"script": "import time as _t; _t.sleep(0.6)"}}


def test_timeout_interrupts_at_step_boundary(monkeypatch):
    """三个 0.6s 步骤 + 阈值 1s → 第 2 步后的边界触发 ScenarioTimeout，第 3 步不执行。"""
    monkeypatch.setenv("SG_SCENARIO_TIMEOUT", "1")
    sc = Scenario(id="T-WD1", title="软看门狗",
                  flow=[dict(_SLEEP_STEP), dict(_SLEEP_STEP), dict(_SLEEP_STEP)],
                  verify=[])
    rec = run_scenario(sc, _rctx())
    assert rec.verdict == "FAIL"
    assert rec.failure["category"] == CAT_ENV, \
        f"超时归 env_error（环境/未知），实际 {rec.failure['category']}"
    assert "ScenarioTimeout" in rec.failure["message"] and "超过" in rec.failure["message"], \
        f"消息须带超时提示: {rec.failure['message']}"
    python_steps = [s for s in rec.steps if s.type == "python"]
    assert len(python_steps) == 2, f"第 3 步不应执行（步骤边界中断），实际执行 {len(python_steps)} 步"


def test_timeout_in_poll_loop(monkeypatch):
    """poll until 永不满足 + 场景阈值 1s < poll 自身 timeout_ms=60s → 按场景阈值中断。"""
    monkeypatch.setenv("SG_SCENARIO_TIMEOUT", "1")

    def _fake_request(method, path, **kw):
        resp = SimpleNamespace(status_code=200, headers={}, text="")
        resp.json = lambda: {"status": "RUNNING"}
        return resp

    client = SimpleNamespace(request=_fake_request)
    sc = Scenario(id="T-WD2", title="poll 看门狗",
                  flow=[{"poll": {
                      "call": {"method": "GET", "path": "/api/task"},
                      "until": [{"json": {"path": "$.status", "eq": "DONE"}}],
                      "interval_ms": 100, "timeout_ms": 60000, "save": "p"}}],
                  verify=[])
    t0 = time.monotonic()
    rec = run_scenario(sc, _rctx(client))
    elapsed = time.monotonic() - t0
    assert rec.verdict == "FAIL"
    assert rec.failure["category"] == CAT_ENV
    assert "ScenarioTimeout" in rec.failure["message"] and "超过" in rec.failure["message"], \
        f"应按场景阈值中断而非 poll 自身超时: {rec.failure['message']}"
    assert "poll 超时" not in rec.failure["message"]
    assert elapsed < 5, f"应在场景阈值（1s）附近中断，实际 {elapsed:.1f}s"


def test_timeout_threshold_from_env(monkeypatch):
    """阈值解析：缺省 300；合法数值生效；非法值回退默认。"""
    monkeypatch.delenv("SG_SCENARIO_TIMEOUT", raising=False)
    assert scenario_runner._scenario_timeout_sec() == 300.0
    monkeypatch.setenv("SG_SCENARIO_TIMEOUT", "2.5")
    assert scenario_runner._scenario_timeout_sec() == 2.5
    monkeypatch.setenv("SG_SCENARIO_TIMEOUT", "abc")
    assert scenario_runner._scenario_timeout_sec() == 300.0


def test_deadline_not_leaking_across_scenarios(monkeypatch):
    """超时场景结束后阈值恢复——同 rctx 的下一个快场景正常 PASS（不误伤）。"""
    monkeypatch.setenv("SG_SCENARIO_TIMEOUT", "1")
    rctx = _rctx()
    slow = Scenario(id="T-SLOW", flow=[dict(_SLEEP_STEP)] * 3, verify=[])
    rec_slow = run_scenario(slow, rctx)
    assert rec_slow.verdict == "FAIL"
    fast = Scenario(id="T-FAST", flow=[{"set_var": {"vars": {"x": 1}}}], verify=[])
    rec_fast = run_scenario(fast, rctx)
    assert rec_fast.verdict == "PASS", \
        f"前场景的超时 deadline 不得泄漏到下一场景: {rec_fast.failure}"


def test_default_threshold_allows_normal_scenario(monkeypatch):
    """默认 300s 阈值下普通场景不受影响（回归保护）。"""
    monkeypatch.delenv("SG_SCENARIO_TIMEOUT", raising=False)
    sc = Scenario(id="T-NORM", flow=[{"set_var": {"vars": {"x": 1}}}], verify=[])
    rec = run_scenario(sc, _rctx())
    assert rec.verdict == "PASS"
