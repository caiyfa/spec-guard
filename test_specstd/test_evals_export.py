"""test_evals_export.py — 真实会话反向导出 golden case 单测（T-1042）。

离线可跑（tmp_path 合成会话）。覆盖：legacy 工具名归一（→基名+action）、
助记形态归一、tool_mocks 累积、expect 生成、端到端导出后可被 harness 回放。
非空转证明：归一前后工具名形态成对断言；导出 case 经 harness 回放必过。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.export_case import _resolve_current_tool, export_golden_case, export_to_file


def _write_session(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def _meta(sid="s1"):
    return {"_type": "session_meta", "session_id": sid, "purpose": "test_workbench",
            "workspace": "tdm", "emp_no": "90000001"}


def _asst(call_id, tool, args=None):
    return {"role": "assistant", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": tool, "arguments": json.dumps(args or {}, ensure_ascii=False)}}]}


def _tool(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# ── _resolve_current_tool：三种形态归一 ─────────────────────────────────

def test_resolve_legacy_to_base_and_action():
    base, act = _resolve_current_tool("list_spec_files")
    assert base == "spec" and act == "list"
    base, act = _resolve_current_tool("write_draft")
    assert base == "draft" and act == "write"
    base, act = _resolve_current_tool("next_scenario_id")
    assert base == "scenario" and act == "next_id"


def test_resolve_mnemonic_form():
    base, act = _resolve_current_tool("spec(action=read)")
    assert base == "spec" and act == "read"


def test_resolve_already_base():
    base, act = _resolve_current_tool("query_registry")
    assert base == "query_registry" and act == ""


def test_resolve_unknown_passthrough():
    base, act = _resolve_current_tool("nonexistent_tool_xyz")
    assert base == "nonexistent_tool_xyz" and act == ""  # 诚实原样，harness 回放时报未注册


# ── export_golden_case：结构与归一 ───────────────────────────────────────

def _seed_generate_session(tmp_path, sid="gen1"):
    return _write_session(tmp_path / f"{sid}.jsonl", [
        _meta(sid),
        {"role": "user", "content": "帮我生成 FR-001 的测试场景"},
        _asst("c0", "list_spec_files"), _tool("c0", '{"files": []}'),
        _asst("c1", "read_spec"), _tool("c1", "spec 内容"),
        _asst("c2", "next_scenario_id"), _tool("c2", "UT-001"),
        _asst("c3", "validate"), _tool("c3", '{"verdict": "PASS"}'),
        _asst("c4", "write_draft"), _tool("c4", "ok"),
        {"role": "assistant", "content": "场景已生成"},
    ])


def test_export_normalizes_legacy_tools(tmp_path):
    f = _seed_generate_session(tmp_path)
    case = export_golden_case(f)
    # tool_mocks 键归一到基名
    assert set(case["tool_mocks"].keys()) == {"spec", "scenario", "validate", "draft"}
    # llm_script 的 tool_call 名字是基名，arguments 补 action
    first_call = case["llm_script"][0]["tool_calls"][0]["function"]
    assert first_call["name"] == "spec"
    assert first_call["arguments"]["action"] == "list"
    # write_draft → draft + action=write
    draft_calls = [e for e in case["llm_script"] if e.get("tool_calls")
                   and e["tool_calls"][0]["function"]["name"] == "draft"]
    assert draft_calls and draft_calls[0]["tool_calls"][0]["function"]["arguments"]["action"] == "write"


def test_export_extracts_task_prompt_and_meta(tmp_path):
    f = _seed_generate_session(tmp_path)
    case = export_golden_case(f)
    assert case["task_prompt"] == "帮我生成 FR-001 的测试场景"
    assert "test_workbench" in case["description"]
    assert case["expect"][0]["type"] == "tools_required"
    assert set(case["expect"][0]["expect"]) == {"spec", "scenario", "validate", "draft"}


def test_export_json_and_text_mock_forms(tmp_path):
    f = _seed_generate_session(tmp_path)
    case = export_golden_case(f)
    # validate 结果是 JSON 文本 → {"json": ...}
    assert "json" in case["tool_mocks"]["validate"][0]
    # read_spec 结果是纯文本 → {"text": ...}
    assert "text" in case["tool_mocks"]["spec"][1]  # 第 2 次 spec 调用（read）


def test_export_multi_call_accumulates_in_order(tmp_path):
    """同一基名多次调用按序累积（query_registry 调两次）。"""
    f = _write_session(tmp_path / "multi.jsonl", [
        _meta("multi"),
        {"role": "user", "content": "x"},
        _asst("a", "query_registry"), _tool("a", "第一次"),
        _asst("b", "query_registry"), _tool("b", "第二次"),
        {"role": "assistant", "content": "done"},
    ])
    case = export_golden_case(f)
    assert len(case["tool_mocks"]["query_registry"]) == 2
    assert case["tool_mocks"]["query_registry"][0]["text"] == "第一次"
    assert case["tool_mocks"]["query_registry"][1]["text"] == "第二次"


def test_export_empty_session_raises(tmp_path):
    f = _write_session(tmp_path / "empty.jsonl", [])
    with pytest.raises(ValueError):
        export_golden_case(f)


def test_export_no_assistant_raises(tmp_path):
    f = _write_session(tmp_path / "noasst.jsonl", [_meta(), {"role": "user", "content": "x"}])
    with pytest.raises(ValueError):
        export_golden_case(f)


# ── 端到端：导出的 case 可被 harness 回放 ────────────────────────────────

def test_exported_case_replays_through_harness(tmp_path):
    """导出即起点，但结构必须能被 T-980 harness 离线回放（链路打通证明）。"""
    from evals.harness import load_case, run_golden_case
    f = _seed_generate_session(tmp_path)
    out = export_to_file(f, tmp_path / "case.json", case_id="GC-TEST-REPLAY")
    case = load_case(out)
    res = run_golden_case(case)
    # 结构合法 + 脚本消费完整 + 工具全集命中（不要求真实 verdict，mock 固化）
    assert res.metrics["steps"] == 5
    script_ok = any(a.type == "script_usage" and a.passed for a in res.assertions)
    assert script_ok, f"script_usage 未过: {[(a.type, a.detail) for a in res.assertions]}"
