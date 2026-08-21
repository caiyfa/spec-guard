"""evals 包测试（T-980 Agent 评测体系）。

覆盖：
1. ScriptedLLM：脚本回放/耗尽判定/请求记录/接口对齐
2. MockToolModule：json/text/error/多次调用序列
3. 轨迹断言引擎：sequence/required/forbidden/tool_result/artifact_validate
4. golden case 回归：3 个入库 case 全通过（pytest 侧守门）
5. 非空转证明：篡改期望必变红（评测系统能失败，不是恒绿摆设）
6. 工作区隔离：评测上下文内 get_active_workspace 确定为 None
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from evals.harness import (  # noqa: E402
    AssertionResult,
    MockToolModule,
    ScriptedLLM,
    ToolCallRecord,
    evaluate_assertions,
    isolated_eval_context,
    load_case,
    run_golden_case,
    tool_result_ok,
)

CASES_DIR = SG_ROOT / "evals" / "cases"


# ══════════════════════════════════════════════════════════
# ScriptedLLM
# ══════════════════════════════════════════════════════════

class TestScriptedLLM:
    def test_replay_in_order(self):
        llm = ScriptedLLM([
            {"role": "assistant", "content": "第一"},
            {"role": "assistant", "content": "第二"},
        ])
        msg1, _ = llm.chat([{"role": "user", "content": "u"}])
        msg2, _ = llm.chat([{"role": "user", "content": "u"}])
        assert msg1["content"] == "第一"
        assert msg2["content"] == "第二"
        assert llm.call_count == 2
        assert not llm.exhausted
        assert llm.leftover == 0

    def test_exhaustion_detected(self):
        llm = ScriptedLLM([{"role": "assistant", "content": "唯一"}])
        llm.chat([{"role": "user", "content": "u"}])
        llm.chat([{"role": "user", "content": "u"}])  # 第 2 次无脚本
        assert llm.exhausted
        assert llm.leftover == 0

    def test_leftover_detected(self):
        llm = ScriptedLLM([{"role": "assistant", "content": "a"},
                           {"role": "assistant", "content": "b"}])
        llm.chat([{"role": "user", "content": "u"}])
        assert not llm.exhausted
        assert llm.leftover == 1

    def test_arguments_dict_normalized_to_json_string(self):
        llm = ScriptedLLM([{"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "validate", "arguments": {"content": "id: X"}}}
        ]}])
        msg, _ = llm.chat([{"role": "user", "content": "u"}])
        args = msg["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)
        assert json.loads(args) == {"content": "id: X"}

    def test_requests_recorded(self):
        llm = ScriptedLLM([{"role": "assistant", "content": "ok"}])
        llm.chat([{"role": "user", "content": "u"}],
                 tools=[{"type": "function",
                         "function": {"name": "list_scenarios"}}])
        assert llm.requests[0]["message_count"] == 1
        assert llm.requests[0]["tool_names"] == ["list_scenarios"]

    def test_interface_parity(self):
        """与 LLMClient/MockLLM 接口对齐（runtime 依赖这些成员）。"""
        llm = ScriptedLLM([])
        assert llm.is_mock is True
        assert llm.max_context_tokens == 0
        llm.set_metrics_file(Path("x.jsonl"))  # no-op 不炸
        stats = llm.get_stats()
        assert stats["is_mock"] is True and "total_tokens" in stats


# ══════════════════════════════════════════════════════════
# MockToolModule
# ══════════════════════════════════════════════════════════

class TestMockToolModule:
    def test_json_spec(self):
        mod = MockToolModule("read_spec", {"json": {"content": "FR-1"}})
        out = asyncio.run(mod.handle("read_spec", {"path": "spec.md"}))
        assert json.loads(out[0].text) == {"content": "FR-1"}
        assert mod.calls == [{"path": "spec.md"}]

    def test_text_spec(self):
        mod = MockToolModule("t", {"text": "plain"})
        out = asyncio.run(mod.handle("t", {}))
        assert out[0].text == "plain"

    def test_error_spec_raises(self):
        mod = MockToolModule("t", {"error": "boom"})
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(mod.handle("t", {}))

    def test_sequenced_specs(self):
        mod = MockToolModule("t", [{"text": "一"}, {"text": "二"}])
        assert asyncio.run(mod.handle("t", {}))[0].text == "一"
        assert asyncio.run(mod.handle("t", {}))[0].text == "二"
        assert asyncio.run(mod.handle("t", {}))[0].text == "二"  # 末个重复


# ══════════════════════════════════════════════════════════
# 成败判定
# ══════════════════════════════════════════════════════════

class TestToolResultOk:
    @pytest.mark.parametrize("prefix", [
        "错误：参数", "[越权拒绝] 工具 x", "未知工具: fetch_emp_magic",
        "工具执行异常: boom", "[SIDE_EFFECT_VIOLATION] 纯读工具",
        "[拒绝] 工具 x 属于 external-write",
    ])
    def test_error_prefixes_fail(self, prefix):
        assert tool_result_ok(prefix) is False

    def test_normal_result_ok(self):
        assert tool_result_ok('{"verdict": "PASS"}') is True


# ══════════════════════════════════════════════════════════
# 断言引擎（单元级，用伪造 records）
# ══════════════════════════════════════════════════════════

def _rec(tool, result='{"ok": true}', args=None, ok=True):
    return ToolCallRecord(tool=tool, arguments=args or {}, result=result,
                          ok=ok, turn=0)


GOOD_YAML = "id: T-EVAL-1\ntitle: t\nversion: 0.1\nflow:\n  - tool:\n      use: select_emp\n      with:\n        empNo: \"1\"\n"
BAD_YAML = "id: T-EVAL-2\ntitle: t\nversion: 0.1\nflow:\n  - tool:\n      use: no_such_tool\n"


class TestAssertionEngine:
    def test_sequence_exact_and_ignore(self):
        recs = [_rec("todo_write"), _rec("validate"), _rec("write_draft")]
        r1 = evaluate_assertions(
            [{"type": "tool_sequence", "expect": ["validate", "write_draft"],
              "ignore": ["todo_write"]}], recs)[0]
        assert r1.passed
        r2 = evaluate_assertions(
            [{"type": "tool_sequence", "expect": ["validate"]}], recs)[0]
        assert not r2.passed

    def test_required_subset(self):
        recs = [_rec("read_spec"), _rec("write_draft")]
        r = evaluate_assertions(
            [{"type": "tools_required", "expect": ["write_draft"]}], recs)[0]
        assert r.passed
        r2 = evaluate_assertions(
            [{"type": "tools_required", "expect": ["validate"]}], recs)[0]
        assert not r2.passed and "validate" in r2.detail

    def test_forbidden(self):
        recs = [_rec("read_spec"), _rec("promote_draft")]
        r = evaluate_assertions(
            [{"type": "tools_forbidden", "expect": ["promote_draft"]}], recs)[0]
        assert not r.passed and "promote_draft" in r.detail
        r2 = evaluate_assertions(
            [{"type": "tools_forbidden", "expect": ["commit_delta_changes"]}],
            recs)[0]
        assert r2.passed

    def test_tool_result_jsonpath(self):
        recs = [_rec("validate", result=json.dumps(
            {"verdict": "REJECT", "summary": {"error": 2}}))]
        cases = [
            ({"jsonpath": "$.verdict", "equals": "REJECT"}, True),
            ({"jsonpath": "$.verdict", "equals": "PASS"}, False),
            ({"jsonpath": "$.summary.error", "min": 1}, True),
            ({"jsonpath": "$.summary.error", "min": 3}, False),
            ({"jsonpath": "$.no_such_key", "equals": "x"}, False),
        ]
        for exp, want in cases:
            r = evaluate_assertions(
                [{"type": "tool_result", "tool": "validate", **exp}], recs)[0]
            assert r.passed is want, exp

    def test_tool_result_contains_and_missing_tool(self):
        recs = [_rec("validate", result="未注册的 tool: fetch_emp_magic")]
        r = evaluate_assertions(
            [{"type": "tool_result", "tool": "validate",
              "contains": "fetch_emp_magic"}], recs)[0]
        assert r.passed
        r2 = evaluate_assertions(
            [{"type": "tool_result", "tool": "read_spec",
              "contains": "x"}], recs)[0]
        assert not r2.passed and "未被调用" in r2.detail

    def test_artifact_validate_good_and_bad(self):
        good = [_rec("write_draft", args={"content": GOOD_YAML})]
        bad = [_rec("write_draft", args={"content": BAD_YAML})]
        r = evaluate_assertions(
            [{"type": "artifact_validate", "expect_verdict": "PASS"}], good)[0]
        assert r.passed, r.detail
        r2 = evaluate_assertions(
            [{"type": "artifact_validate", "expect_verdict": "PASS"}], bad)[0]
        assert not r2.passed and "REJECT" in r2.detail

    def test_artifact_validate_missing_content(self):
        recs = [_rec("write_draft", args={"filename": "x.yaml"})]
        r = evaluate_assertions([{"type": "artifact_validate"}], recs)[0]
        assert not r.passed and "content" in r.detail

    def test_unknown_assertion_type_fails(self):
        r = evaluate_assertions([{"type": "no_such_type"}], [])[0]
        assert not r.passed and "未知断言类型" in r.detail


# ══════════════════════════════════════════════════════════
# 工作区隔离
# ══════════════════════════════════════════════════════════

class TestIsolatedEvalContext:
    def test_workspace_none_inside_restored_after(self, monkeypatch):
        from specstd import workspace as ws_mod
        monkeypatch.setenv("SG_WORKSPACE", "whatever")
        outside = ws_mod.get_active_workspace()
        with isolated_eval_context():
            import os
            assert os.environ.get("SG_WORKSPACE") is None
            assert ws_mod.get_active_workspace() is None
        assert ws_mod.get_active_workspace() == outside
        assert ws_mod._load_registry() != {"active": "", "workspaces": {}}


# ══════════════════════════════════════════════════════════
# Golden case 回归 + 非空转证明
# ══════════════════════════════════════════════════════════

class TestGoldenCases:
    @pytest.mark.parametrize("case_file", sorted(CASES_DIR.glob("*.json")),
                             ids=lambda p: p.stem)
    def test_case_passes(self, case_file):
        result = run_golden_case(load_case(case_file))
        assert result.passed, "\n".join(
            f"[{f.type}] {f.name}: {f.detail}" for f in result.failures)

    def test_at_least_three_cases_in_repo(self):
        assert len(list(CASES_DIR.glob("*.json"))) >= 3

    def test_metrics_tool_dimensions(self):
        result = run_golden_case(load_case(CASES_DIR / "001-list-scenarios.json"))
        m = result.metrics
        for key in ("tools_sequence", "tool_calls_total", "tool_calls_ok",
                    "tool_calls_failed", "tool_success_rate", "steps",
                    "turns", "duration_ms", "llm_calls"):
            assert key in m, f"metrics 缺工具维度字段 {key}"
        assert m["tools_sequence"] == ["list_scenarios"]

    def _run_tampered(self, case_file: str, mutate) -> AssertionResult:
        case = load_case(CASES_DIR / case_file)
        mutate(case)
        result = run_golden_case(case)
        assert not result.passed, "篡改期望后仍通过——评测空转！"
        return result.failures[0]

    def test_negative_control_wrong_sequence(self):
        f = self._run_tampered(
            "001-list-scenarios.json",
            lambda c: c["expect"].__setitem__(
                0, {"type": "tool_sequence", "expect": ["query_registry"]}))
        assert f.type == "tool_sequence"

    def test_negative_control_tool_not_called(self):
        f = self._run_tampered(
            "001-list-scenarios.json",
            lambda c: c["expect"].__setitem__(
                1, {"type": "tools_required", "expect": ["read_spec"]}))
        assert f.type == "tools_required"

    def test_negative_control_bad_artifact(self):
        """把草稿产物换成含幻觉工具的 YAML——artifact_validate 必须红。"""
        def mutate(case):
            bad = case["llm_script"][1]["tool_calls"][0]["function"]["arguments"]
            bad["content"] = BAD_YAML
            # validate 真实工具也会跟着红（同步换掉序列断言以聚焦产物断言）
            case["expect"] = [e for e in case["expect"]
                              if e["type"] != "tool_sequence"]
        f = self._run_tampered("003-draft-write-validate.json", mutate)
        assert f.type == "artifact_validate"

    def test_negative_control_short_script_fuse(self):
        """max_turns=1 提前熔断 → 脚本剩余判失败（脚本未完整消费）。"""
        def mutate(case):
            case["max_turns"] = 1
        f = self._run_tampered("003-draft-write-validate.json", mutate)
        assert f.type == "script_usage"
        assert "剩余" in f.detail

    def test_allow_leftover_opt_in(self):
        """熔断场景显式 allow_leftover: true 时只警告不判死。"""
        case = load_case(CASES_DIR / "003-draft-write-validate.json")
        case["max_turns"] = 1
        case["allow_leftover"] = True
        case["expect"] = [{"type": "tools_required", "expect": ["read_spec"]}]
        result = run_golden_case(case)
        assert result.passed, [f.detail for f in result.failures]
        assert result.metrics["fused"] is True
