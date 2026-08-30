"""test_evals_replay.py — 通道 A 轨迹重放打分单测（T-1042）。

离线可跑（tmp_path 合成会话），不依赖主库真实数据。
覆盖：generate-scenario 会话识别（新/旧工具名形态）、阶段命中（合并 action 形态
与 legacy 逻辑 id）、序列合理性、五维信号、批量重放报告、诚实空态。
非空转证明：识别/序列/禁用等判定均成对翻案（生成 vs 非生成、合理 vs 乱序）。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.baseline import scan_session
from evals.replay import (
    _check_sequence,
    _stage_hit,
    is_generate_scenario_session,
    replay_report,
    replay_session,
    score_trajectory,
)


def _write_session(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def _meta(sid="s1"):
    return {"_type": "session_meta", "session_id": sid, "purpose": "test_workbench",
            "workspace": "tdm", "emp_no": "90000001"}


def _asst(call_id, tool):
    return {"role": "assistant", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": tool, "arguments": "{}"}}]}


def _tool(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _make_scan(tmp_path, tools_with_results, sid="s1", extra_rows=()):
    """tools_with_results: [(tool_name, result_text), ...] 按序展开成 assistant+tool 行。"""
    rows = [_meta(sid=sid)] + list(extra_rows)
    for i, (name, res) in enumerate(tools_with_results):
        cid = f"c{i}"
        rows.append(_asst(cid, name))
        rows.append(_tool(cid, res))
    f = _write_session(tmp_path / f"{sid}.jsonl", rows)
    return scan_session(f), f


# ── _stage_hit：新/旧形态都命中 ──────────────────────────────────────────

def test_stage_hit_merged_action_form():
    assert _stage_hit("get_id", ["scenario(action=next_id)"]) is True
    assert _stage_hit("write_draft", ["draft(action=write)"]) is True


def test_stage_hit_legacy_form():
    assert _stage_hit("get_id", ["next_scenario_id"]) is True
    assert _stage_hit("write_draft", ["write_draft"]) is True
    assert _stage_hit("read_requirement", ["read_spec"]) is True


def test_stage_hit_base_name_matches_action_variant():
    # 候选是 base 名（info_pack）时，应命中 info_pack(action=read)
    assert _stage_hit("read_requirement", ["info_pack(action=read)"]) is True


def test_stage_hit_negative():
    assert _stage_hit("get_id", ["query_registry"]) is False
    assert _stage_hit("write_draft", ["validate"]) is False


# ── is_generate_scenario_session 识别 ───────────────────────────────────

def test_identify_generate_by_write_draft(tmp_path):
    scan, _ = _make_scan(tmp_path, [
        ("read_spec", "{}"), ("next_scenario_id", "S1"),
        ("validate", '{"verdict":"PASS"}'), ("write_draft", "ok"),
    ])
    assert is_generate_scenario_session(scan) is True


def test_identify_generate_by_validate_and_next_id(tmp_path):
    scan, _ = _make_scan(tmp_path, [
        ("validate", '{"verdict":"PASS"}'), ("next_scenario_id", "S1"),
    ])
    assert is_generate_scenario_session(scan) is True


def test_not_identify_pure_query_session(tmp_path):
    """只读问答会话（无草稿无 next_id）不识别为生成会话（非空转翻案）。"""
    scan, _ = _make_scan(tmp_path, [
        ("read_spec", "{}"), ("query_registry", "{}"), ("read_scenario", "{}"),
    ])
    assert is_generate_scenario_session(scan) is False


# ── _check_sequence：关键阶段顺序 ───────────────────────────────────────

def test_sequence_ok_read_before_draft():
    used = ["read_spec", "next_scenario_id", "validate", "write_draft"]
    assert _check_sequence(used) is True


def test_sequence_bad_draft_before_validate():
    """写草稿先于校验 → 乱序（非空转翻案）。"""
    used = ["read_spec", "write_draft", "validate"]
    assert _check_sequence(used) is False


def test_sequence_insufficient_returns_none():
    assert _check_sequence(["query_registry"]) is None


# ── score_trajectory：五维信号 ──────────────────────────────────────────

def test_score_generate_full_trajectory(tmp_path):
    scan, _ = _make_scan(tmp_path, [
        ("read_spec", "{}"), ("next_scenario_id", "S1"), ("query_registry", "{}"),
        ("list_scenarios", "[]"), ("validate", '{"verdict":"PASS"}'), ("write_draft", "ok"),
    ])
    sc = score_trajectory(scan)
    assert sc.is_generate_scenario is True
    assert sc.draft_written is True
    assert sc.validate_passed is True
    # 命中 read_requirement/get_id/query_registry/find_reference/validate/write_draft
    assert sc.stage_coverage == 1.0
    assert sc.sequence_ok is True


def test_score_whitelist_denied_via_tool_results(tmp_path):
    scan, f = _make_scan(tmp_path, [
        ("read_spec", "{}"), ("validate", '{"verdict":"PASS"}'),
        ("write_draft", "ok"), ("draft(action=promote)", "[越权拒绝] 需要确认"),
    ])
    from evals.replay import extract_tool_results
    sc = score_trajectory(scan, extract_tool_results(f))
    assert sc.whitelist_denied == 1


def test_score_side_effect_violation(tmp_path):
    scan, f = _make_scan(tmp_path, [
        ("validate", '{"verdict":"PASS"}'), ("next_scenario_id", "S1"),
        ("spec", "[SIDE_EFFECT_VIOLATION] 纯读工具产生副作用"),
    ])
    from evals.replay import extract_tool_results
    sc = score_trajectory(scan, extract_tool_results(f))
    assert sc.side_effect_violation == 1


def test_score_fused(tmp_path):
    rows = [_meta(), {"role": "system", "content": "[FUSE] 熔断"}]
    f = _write_session(tmp_path / "fz.jsonl", rows)
    scan = scan_session(f)
    sc = score_trajectory(scan)
    assert sc.fused is True


# ── replay_session / replay_report 批量 ─────────────────────────────────

def test_replay_session_end_to_end(tmp_path):
    scan, f = _make_scan(tmp_path, [
        ("read_spec", "{}"), ("next_scenario_id", "S1"),
        ("validate", '{"verdict":"PASS"}'), ("write_draft", "ok"),
    ])
    sc = replay_session(f)
    assert sc is not None
    assert sc.is_generate_scenario is True


def test_replay_report_aggregates(tmp_path):
    root = tmp_path / "sessions"
    # 一个完整生成会话 + 一个纯查询会话 + 一个 smoke
    _write_session(root / "e" / "tdm" / "gen.jsonl", [
        _meta("gen"),
        _asst("a", "read_spec"), _tool("a", "{}"),
        _asst("b", "next_scenario_id"), _tool("b", "S1"),
        _asst("c", "validate"), _tool("c", '{"verdict":"PASS"}'),
        _asst("d", "write_draft"), _tool("d", "ok"),
        {"_type": "metrics", "total_tokens": 500, "model": "m"},
    ])
    _write_session(root / "e" / "tdm" / "query.jsonl", [
        _meta("query"),
        _asst("a", "query_registry"), _tool("a", "{}"),
    ])
    _write_session(root / "e" / "smoke" / "sm.jsonl", [_meta("sm"), {"role": "user", "content": "x"}])

    rep = replay_report(root)
    assert rep["sessions_replayed"] == 3
    assert rep["generate_scenario_sessions"] == 1
    assert rep["dimensions"]["D3_task_outcome"]["validate_pass_rate"] == 1.0
    assert rep["dimensions"]["D3_task_outcome"]["draft_written_rate"] == 1.0


def test_replay_report_only_generate_filter(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root / "gen.jsonl", [
        _meta("gen"),
        _asst("a", "validate"), _tool("a", '{"verdict":"PASS"}'),
        _asst("b", "next_scenario_id"), _tool("b", "S1"),
        _asst("c", "write_draft"), _tool("c", "ok"),
    ])
    _write_session(root / "query.jsonl", [
        _meta("query"), _asst("a", "query_registry"), _tool("a", "{}"),
    ])
    rep = replay_report(root, only_generate=True)
    assert rep["sessions_replayed"] == 1
    assert rep["generate_scenario_sessions"] == 1


def test_replay_report_empty_honest(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    rep = replay_report(root)
    assert rep["sessions_replayed"] == 0
    assert rep["dimensions"]["D5_safety"]["fuse_rate"] is None  # 诚实空态
