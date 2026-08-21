"""ENG-T05 渲染与断言防呆：插值残留扫描（ENG-BUG-006）/ poll 快速失败（ENG-BUG-008）/
poll 参数透传（ENG-BUG-014）。

全部离线（假客户端 mock，不触网）。

设计依据：docs/架构升级/ENG-T05-渲染与断言防呆.md §6。
"""

import os
import time
from types import SimpleNamespace

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engine.execution_record import CAT_SCENARIO  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.scenario_loader import Scenario  # noqa: E402
from engine.scenario_runner import (  # noqa: E402
    RenderError, RunContext, register_builtin_steps, run_scenario, render,
)


def _rctx(client=None, client_getter=None):
    reg = Registry()
    register_builtin_steps(reg)
    # T-972：default_service 由 env 声明（引擎不内置系统名）
    rc = RunContext(registry=reg, env_config={"default_service": "tdm"},
                    token_provider=None, graph=None, run_dir=".")
    if client_getter is not None:
        rc.http_client = client_getter
    elif client is not None:
        rc.http_client = lambda acc, service="tdm": client
    return rc


def _resp(obj=None, status=200):
    resp = SimpleNamespace(status_code=status, headers={}, text="")
    resp.json = lambda: obj if obj is not None else {"data": {"status": "RUNNING"}}
    return resp


# ══════════════════════════════════════════════════════════
# 1. 插值残留扫描（ENG-BUG-006，验收 1）
# ══════════════════════════════════════════════════════════

def test_render_residue_raises_render_error():
    """单元：残留 {{ 的渲染结果抛 RenderError（含缺右括号/空占位符/半合法混排）。"""
    ns = {"a": 1}
    for bad in ["{{ empno }", "{{}}", "前缀 {{a}} 后缀 {{b", "{{x"]:
        try:
            render(bad, ns)
        except RenderError as e:
            assert "未解析" in str(e), f"消息应指明未解析占位符: {e}"
        else:
            raise AssertionError(f"{bad!r} 应抛 RenderError")


def test_render_legal_unchanged():
    """合法插值不受影响：fullmatch 保类型、内嵌替换、无插值字符串直通。"""
    ns = {"a": 1, "b": {"c": [1, 2]}}
    assert render("{{a}}", ns) == 1
    assert render("{{ b.c }}", ns) == [1, 2]
    assert render("x={{a}} y={{a}}", ns) == "x=1 y=1"
    assert render("普通字符串", ns) == "普通字符串"
    assert render(None, ns) is None


def test_call_with_malformed_placeholder_fails_before_request():
    """验收1：path 写 {{ empno }（缺右括号）→ 明确报未解析占位符，请求不发出。"""
    calls = []

    def _fake_request(method, path, **kw):
        calls.append((method, path))
        return _resp({"ok": True})

    client = SimpleNamespace(request=_fake_request)
    sc = Scenario(id="T-RES", flow=[{"call": {
        "method": "GET", "path": "/api/emp/{{ empno }", "save": "r"}}],
        verify=[])
    rec = run_scenario(sc, _rctx(client))
    assert rec.verdict == "FAIL"
    assert rec.failure["category"] == CAT_SCENARIO, \
        f"残留占位符属场景编写错误，实际 {rec.failure['category']}"
    assert "未解析" in rec.failure["message"] and "RenderError" in rec.failure["message"]
    assert calls == [], "请求必须不发出"


# ══════════════════════════════════════════════════════════
# 2. poll until 快速失败（ENG-BUG-008，验收 4/5）
# ══════════════════════════════════════════════════════════

def _poll_scenario(sid, until, interval_ms=50, timeout_ms=8000, call_extra=None):
    call = {"method": "GET", "path": "/api/task"}
    call.update(call_extra or {})
    return Scenario(id=sid, flow=[{"poll": {
        "call": call, "until": until, "interval_ms": interval_ms,
        "timeout_ms": timeout_ms, "save": "p"}}], verify=[])


def test_poll_malformed_jsonpath_fails_fast():
    """验收4：until jsonpath 拼错 → 第一轮即 FAIL（scenario_error），消息含解析错误，不轮询至超时。"""
    n_calls = []

    def _fake_request(method, path, **kw):
        n_calls.append(1)
        return _resp()

    client = SimpleNamespace(request=_fake_request)
    sc = _poll_scenario("T-PF1", [{"json": {"path": "$.data..", "eq": "DONE"}}])
    t0 = time.monotonic()
    rec = run_scenario(sc, _rctx(client))
    elapsed = time.monotonic() - t0
    assert rec.verdict == "FAIL"
    assert rec.failure["category"] == CAT_SCENARIO, \
        f"配置错误应归 scenario_error（此前被当'未满足'轮询至超时），实际 {rec.failure['category']}"
    assert "poll until 条件配置错误" in rec.failure["message"]
    assert len(n_calls) == 1, f"第一轮即应中断，实际调了 {len(n_calls)} 次"
    assert elapsed < 3, f"不应轮询至超时（timeout_ms=8000），实际 {elapsed:.1f}s"


def test_poll_unsatisfied_condition_still_polls_to_timeout():
    """验收5：until 合法但不满足 → 行为不变（轮询至 timeout_ms 按 on_timeout 产出）。"""
    n_calls = []

    def _fake_request(method, path, **kw):
        n_calls.append(1)
        return _resp()

    client = SimpleNamespace(request=_fake_request)
    sc = _poll_scenario("T-PF2", [{"json": {"path": "$.data.status", "eq": "DONE"}}],
                        interval_ms=30, timeout_ms=200)
    rec = run_scenario(sc, _rctx(client))
    assert rec.verdict == "FAIL", "默认 on_timeout=fail"
    assert "poll 超时" in rec.failure["message"]
    assert len(n_calls) >= 2, "合法不满足应持续轮询"


def test_poll_jsonpath_no_match_polls_not_fails():
    """jsonpath 无匹配（AssertionError）= 条件未满足语义 → 继续轮询而非快速失败。"""
    n_calls = []

    def _fake_request(method, path, **kw):
        n_calls.append(1)
        return _resp({"data": {}})     # $.data.status 无匹配

    client = SimpleNamespace(request=_fake_request)
    sc = _poll_scenario("T-PF3", [{"json": {"path": "$.data.status", "eq": "DONE"}}],
                        interval_ms=30, timeout_ms=150)
    rec = run_scenario(sc, _rctx(client))
    assert rec.verdict == "FAIL" and "poll 超时" in rec.failure["message"]
    assert len(n_calls) >= 2, "无匹配应按'未满足'轮询"


# ══════════════════════════════════════════════════════════
# 3. poll 参数透传（ENG-BUG-014，验收 6）
# ══════════════════════════════════════════════════════════

def test_poll_routes_service_and_custom_headers():
    """验收6：poll 配 service: hr_center + 自定义 headers → 请求带正确 service 路由与头。"""
    seen = {"service": None, "headers": None}

    def _http_client(account, service="tdm"):
        seen["service"] = service

        def _fake_request(method, path, **kw):
            seen["headers"] = kw.get("headers")
            seen["cookies"] = kw.get("cookies")
            return _resp({"data": {"status": "DONE"}})
        return SimpleNamespace(request=_fake_request)

    sc = _poll_scenario("T-PS1", [{"json": {"path": "$.data.status", "eq": "DONE"}}],
                        call_extra={"service": "hr_center",
                                    "headers": {"X-Trace": "poll-001"},
                                    "cookies": {"sid": "abc"}})
    rec = run_scenario(sc, _rctx(client_getter=_http_client))
    assert rec.verdict == "PASS"
    assert seen["service"] == "hr_center", f"poll 应路由到声明的 service，实际 {seen['service']}"
    assert seen["headers"] == {"X-Trace": "poll-001"}, f"自定义 headers 应透传，实际 {seen['headers']}"
    assert seen["cookies"] == {"sid": "abc"}


def test_poll_defaults_unchanged():
    """不声明 service/headers 时默认行为不变（service=tdm，无自定义头）。"""
    seen = {}

    def _http_client(account, service="tdm"):
        seen["service"] = service

        def _fake_request(method, path, **kw):
            seen["headers"] = kw.get("headers")
            return _resp({"data": {"status": "DONE"}})
        return SimpleNamespace(request=_fake_request)

    sc = _poll_scenario("T-PS2", [{"json": {"path": "$.data.status", "eq": "DONE"}}])
    rec = run_scenario(sc, _rctx(client_getter=_http_client))
    assert rec.verdict == "PASS"
    assert seen["service"] == "tdm"
    assert seen["headers"] is None


# ══════════════════════════════════════════════════════════
# 4. T9 断言对象显式化提示（ENG-BUG-007，验收 3）
# ══════════════════════════════════════════════════════════

def _validate_tc(tmp_path, files):
    backend = os.path.join(SG_ROOT, "workbench", "backend")
    from services.spec_validator import validate_test_cases
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return validate_test_cases(str(tmp_path))


_MULTI_SAVE_YAML = """id: MS-001
version: 0.1
title: 多save无of
flow:
  - call: {method: GET, path: /api/a, save: a}
  - db_query: {sql: "SELECT 1", save: rows}
verify:
  - json: {path: "$.data.x", eq: 1}
"""

_UP_YAML = """id: UP-EXISTS
version: 0.1
title: 上游
flow:
  - set_var: {vars: {x: 1}}
verify: []
"""


def test_t9_multi_save_without_of_warns(tmp_path):
    """验收3：call(save=a)+db_query(save=rows)+无 of 断言 → T9 WARN。"""
    result = _validate_tc(tmp_path, {"MS-001.yaml": _MULTI_SAVE_YAML, "UP.yaml": _UP_YAML})
    t9 = [f for f in result["findings"] if f["vid"] == "T9"]
    assert t9, f"多 save + 无 of 断言应报 T9 WARN: {result['findings']}"
    assert t9[0]["level"] == "WARN"
    assert "of" in t9[0]["message"]


def test_t9_no_warn_when_of_explicit_or_single_save(tmp_path):
    """显式 of 或仅单个 save 步骤 → 不报 T9（避免噪声）。"""
    explicit_of = _MULTI_SAVE_YAML.replace(
        '- json: {path: "$.data.x", eq: 1}',
        '- json: {of: a, path: "$.data.x", eq: 1}')
    single_save = """id: SS-001
version: 0.1
title: 单save
flow:
  - call: {method: GET, path: /api/a, save: a}
verify:
  - json: {path: "$.data.x", eq: 1}
"""
    result = _validate_tc(tmp_path, {"MS.yaml": explicit_of, "SS.yaml": single_save,
                                     "UP.yaml": _UP_YAML})
    t9 = [f for f in result["findings"] if f["vid"] == "T9"]
    assert not t9, f"显式 of / 单 save 不应报 T9: {t9}"
