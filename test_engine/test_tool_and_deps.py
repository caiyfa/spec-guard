"""引擎离线单测：tool 信封分发 + 依赖版本仲裁（DRIFT/ORPHANED/optional/strict_deps）。"""

import os
import sys
from types import SimpleNamespace

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.execution_record import (  # noqa: E402
    ExecutionRecord, VERDICT_BLOCKED, VERDICT_DRIFT, VERDICT_ORPHANED, VERDICT_SKIP,
)
from engine.dependency_graph import DependencyGraph  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.scenario_runner import _check_dep_versions, step_tool  # noqa: E402
from engine.tool_registry import TOOLS  # noqa: E402


# ══════════════════════════════════════════════════════════
# tool 信封分发
# ══════════════════════════════════════════════════════════

def _fake_rctx_with_tool():
    reg = Registry()
    seen = {}

    def demo_handler(body, rctx, ns, record):
        seen["body"] = body
        return {"echo": body}

    reg.step("random", demo_handler)   # random 是内置 tool（元数据已注册）
    rctx = SimpleNamespace(registry=reg)
    return rctx, seen


def test_tool_dispatch_envelope_unwrap():
    """{use, with, save} 拆封后交给原 handler，save 注入 body"""
    rctx, seen = _fake_rctx_with_tool()
    record = ExecutionRecord(scenario_id="T-001")
    result = step_tool({"use": "random", "with": {"type": "uuid"}, "save": "r"}, rctx, {}, record)
    assert seen["body"] == {"type": "uuid", "save": "r"}
    assert result == {"echo": {"type": "uuid", "save": "r"}}


def test_tool_dispatch_without_save():
    rctx, seen = _fake_rctx_with_tool()
    record = ExecutionRecord(scenario_id="T-001")
    step_tool({"use": "random", "with": {"type": "number"}}, rctx, {}, record)
    assert seen["body"] == {"type": "number"}


def test_tool_unknown_rejected():
    rctx, _ = _fake_rctx_with_tool()
    record = ExecutionRecord(scenario_id="T-001")
    with pytest.raises(ValueError, match="未注册的 tool"):
        step_tool({"use": "no_such_tool"}, rctx, {}, record)


# ══════════════════════════════════════════════════════════
# set_var 顶层命名空间注入（K-051：format_spec §3.4 契约——无 save 裸名引用）
# ══════════════════════════════════════════════════════════

def test_set_var_merges_into_ns_without_save():
    """无 save 时 vars 注入顶层 ns（{{activity_name}} 裸名可解析）——规范契约"""
    from engine.scenario_runner import step_set_var
    ns = {"suffix": "001"}
    record = ExecutionRecord(scenario_id="T-002")
    result = step_set_var({"vars": {"activity_name": "SG-{{suffix}}", "corp_code": "1002"}},
                          SimpleNamespace(), ns, record)
    assert ns["activity_name"] == "SG-001"
    assert ns["corp_code"] == "1002"
    assert result["corp_code"] == "1002"  # 返回值保留（带 save 用法兼容）


def test_set_var_with_save_still_works():
    """带 save 用法不回归：ns[save] 由 flow 循环写入（此处模拟），顶层同样可用"""
    from engine.scenario_runner import step_set_var
    ns = {}
    record = ExecutionRecord(scenario_id="T-003")
    values = step_set_var({"vars": {"no": "90024713"}}, SimpleNamespace(), ns, record)
    # flow 循环的等价行为：save 名注入
    ns["emp"] = values
    assert ns["emp"]["no"] == "90024713"
    assert ns["no"] == "90024713"  # K-051 后顶层也可达（与规范一致，无副作用）


def test_tool_missing_use_rejected():
    rctx, _ = _fake_rctx_with_tool()
    record = ExecutionRecord(scenario_id="T-001")
    with pytest.raises(ValueError, match="缺少 use"):
        step_tool({"with": {}}, rctx, {}, record)


def test_builtin_tools_registered():
    """引擎内置 tool 元数据齐备（random/set_var）"""
    assert "random" in TOOLS
    assert "set_var" in TOOLS


# ══════════════════════════════════════════════════════════
# 依赖版本仲裁
# ══════════════════════════════════════════════════════════

def _scenario(sid, version="0.1", depends_on=None):
    return SimpleNamespace(
        id=sid, version=version, title="", priority="P1", tags=[],
        doc={}, depends_on=depends_on or [], flow=[], teardown=[],
        produces=[], verify=[], suite={}, path="",
        covers=[], depends_display=[],
    )


def _graph(scenarios):
    return DependencyGraph(scenarios)


def _rctx(graph, strict=False):
    return SimpleNamespace(graph=graph, strict_deps=strict)


def test_orphan_collected_not_raised():
    """上游缺失不再建图期崩溃，记入 orphans"""
    s = _scenario("A", depends_on=[{"id": "GHOST", "mode": "shared", "version": None, "optional": False}])
    g = _graph([s])
    assert g.orphans == {"A": ["GHOST"]}
    assert g.dep_status["A"][0]["status"] == "orphan"


def test_dep_status_version_matrix():
    up = _scenario("UP", version="1.2")
    down_match = _scenario("D1", depends_on=[{"id": "UP", "mode": "shared", "version": "^1", "optional": False}])
    down_drift = _scenario("D2", depends_on=[{"id": "UP", "mode": "shared", "version": "^2", "optional": False}])
    down_minor = _scenario("D3", depends_on=[{"id": "UP", "mode": "shared", "version": "1.0", "optional": False}])
    g = _graph([up, down_match, down_drift, down_minor])
    assert g.dep_status["D1"][0]["status"] == "match"
    assert g.dep_status["D2"][0]["status"] == "major_drift"
    assert g.dep_status["D3"][0]["status"] == "minor_drift"


def test_check_drift_verdict():
    up = _scenario("UP", version="2.0")
    down = _scenario("DOWN", depends_on=[{"id": "UP", "mode": "shared", "version": "^1", "optional": False}])
    g = _graph([up, down])
    verdict, reason = _check_dep_versions(down, _rctx(g))
    assert verdict == VERDICT_DRIFT
    assert "UP" in reason and "^1" in reason


def test_check_drift_strict_becomes_blocked():
    up = _scenario("UP", version="2.0")
    down = _scenario("DOWN", depends_on=[{"id": "UP", "mode": "shared", "version": "^1", "optional": False}])
    g = _graph([up, down])
    verdict, _ = _check_dep_versions(down, _rctx(g, strict=True))
    assert verdict == VERDICT_BLOCKED


def test_check_orphan_verdict():
    down = _scenario("DOWN", depends_on=[{"id": "GHOST", "mode": "shared", "version": None, "optional": False}])
    g = _graph([down])
    verdict, _ = _check_dep_versions(down, _rctx(g))
    assert verdict == VERDICT_ORPHANED


def test_check_orphan_strict_becomes_blocked():
    down = _scenario("DOWN", depends_on=[{"id": "GHOST", "mode": "shared", "version": None, "optional": False}])
    g = _graph([down])
    verdict, _ = _check_dep_versions(down, _rctx(g, strict=True))
    assert verdict == VERDICT_BLOCKED


def test_check_optional_missing_skips():
    down = _scenario("DOWN", depends_on=[{"id": "GHOST", "mode": "shared", "version": None, "optional": True}])
    g = _graph([down])
    verdict, reason = _check_dep_versions(down, _rctx(g))
    assert verdict == VERDICT_SKIP
    assert "optional" in reason


def test_check_match_passes():
    up = _scenario("UP", version="1.2")
    down = _scenario("DOWN", depends_on=[{"id": "UP", "mode": "shared", "version": "^1", "optional": False}])
    g = _graph([up, down])
    verdict, _ = _check_dep_versions(down, _rctx(g))
    assert verdict is None


def test_check_minor_drift_passes_with_note():
    up = _scenario("UP", version="1.5")
    down = _scenario("DOWN", depends_on=[{"id": "UP", "mode": "shared", "version": "1.2", "optional": False}])
    g = _graph([up, down])
    verdict, _ = _check_dep_versions(down, _rctx(g))
    assert verdict is None
    assert "MINOR" in down._minor_drift_note


def test_drift_report_only_abnormal():
    up = _scenario("UP", version="2.0")
    ok = _scenario("OK", depends_on=[{"id": "UP", "mode": "shared", "version": "^2", "optional": False}])
    bad = _scenario("BAD", depends_on=[{"id": "UP", "mode": "shared", "version": "^1", "optional": False}])
    g = _graph([up, ok, bad])
    report = g.drift_report()
    assert len(report) == 1
    assert report[0]["consumer"] == "BAD"
    assert report[0]["status"] == "major_drift"
