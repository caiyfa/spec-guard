"""test_evals_baseline.py — Phase 0 基线聚合器单测（T-1042）。

离线可跑（tmp_path 合成会话 JSONL + 临时 sqlite），不依赖主库真实数据。
覆盖：行结构解析、工具成败判定、validate 一次通过率、纠正关键词、熔断检出、
smoke 隔离区排除、审计 verdict 聚合、七指标汇总、诚实空态（无数据给 None 不造假）。

非空转证明：每个断言都先有「篡改输入必翻案」的反向用例（test_scan_* 系列里
ok/fail、PASS/REJECT、有/无关键词成对出现）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from evals.baseline import (
    build_baseline_report,
    render_markdown,
    scan_audit,
    scan_metrics_files,
    scan_session,
    _tool_result_ok,
    _validate_verdict,
)


# ── 工具函数：合成会话 JSONL ─────────────────────────────────────────────

def _write_session(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def _meta(sid="s1", purpose="test_workbench", workspace="tdm", emp="90000001"):
    return {"_type": "session_meta", "session_id": sid, "purpose": purpose,
            "workspace": workspace, "emp_no": emp}


def _asst_tool(call_id, tool):
    return {"role": "assistant", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": tool, "arguments": "{}"}}]}


def _tool_row(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# ── 工具结果成败判定（与 harness 同源前缀）─────────────────────────────────

def test_tool_result_ok_normal():
    assert _tool_result_ok("待办已更新（2 项）") is True
    assert _tool_result_ok('{"verdict": "PASS"}') is True


def test_tool_result_ok_error_prefixes():
    for prefix in ("错误：", "[越权拒绝]", "未知工具:", "工具执行异常:",
                   "[SIDE_EFFECT_VIOLATION]", "[拒绝]"):
        assert _tool_result_ok(prefix + "boom") is False, prefix


# ── validate verdict 提取 ────────────────────────────────────────────────

def test_validate_verdict_json():
    assert _validate_verdict('{"verdict": "PASS", "summary": {}}') == "PASS"
    assert _validate_verdict('{"verdict": "REJECT"}') == "REJECT"


def test_validate_verdict_text_and_none():
    assert _validate_verdict("校验完成 verdict: PASS 无错误") == "PASS"
    assert _validate_verdict("一些没有 verdict 的输出") is None
    assert _validate_verdict("") is None


# ── scan_session：行结构解析与信号提取 ───────────────────────────────────

def test_scan_session_tool_counts(tmp_path):
    f = _write_session(tmp_path / "s1.jsonl", [
        _meta(),
        {"role": "user", "content": "生成场景"},
        _asst_tool("c1", "scenario(action=list)"),
        _tool_row("c1", "共 5 个场景"),
        _asst_tool("c2", "validate"),
        _tool_row("c2", "错误：参数缺失"),
        {"_type": "metrics", "total_tokens": 1234, "model": "gpt-4o"},
    ])
    s = scan_session(f)
    assert s is not None
    assert s.n_tool_calls == 2
    assert s.n_tool_ok == 1 and s.n_tool_fail == 1
    assert s.total_tokens == 1234
    assert s.model == "gpt-4o"
    assert s.purpose == "test_workbench"


def test_scan_session_fuse_and_correction(tmp_path):
    f = _write_session(tmp_path / "s2.jsonl", [
        _meta(),
        {"role": "user", "content": "你搞错了，应该是 FR-001"},
        {"role": "system", "content": "[FUSE] 达到最大轮次"},
    ])
    s = scan_session(f)
    assert s.fused is True
    assert s.had_correction is True


def test_scan_session_no_correction_when_clean(tmp_path):
    f = _write_session(tmp_path / "s3.jsonl", [
        _meta(),
        {"role": "user", "content": "帮我生成一个场景"},
    ])
    s = scan_session(f)
    assert s.had_correction is False
    assert s.fused is False


def test_scan_session_validate_first_pass(tmp_path):
    f = _write_session(tmp_path / "s4.jsonl", [
        _meta(),
        _asst_tool("c1", "validate"),
        _tool_row("c1", '{"verdict": "PASS"}'),
    ])
    s = scan_session(f)
    assert s.validate_calls == 1
    assert s.validate_first_pass is True
    assert s.validate_pass == 1


def test_scan_session_validate_first_reject(tmp_path):
    """首次 REJECT → 一次通过率 False（非空转：与 PASS 用例成对翻案）。"""
    f = _write_session(tmp_path / "s5.jsonl", [
        _meta(),
        _asst_tool("c1", "validate"),
        _tool_row("c1", '{"verdict": "REJECT"}'),
        _asst_tool("c2", "validate"),
        _tool_row("c2", '{"verdict": "PASS"}'),
    ])
    s = scan_session(f)
    assert s.validate_calls == 2
    assert s.validate_first_pass is False
    assert s.validate_pass == 1


def test_scan_session_smoke_flagged_by_path(tmp_path):
    f = _write_session(tmp_path / "smoke" / "s6.jsonl", [_meta(), {"role": "user", "content": "x"}])
    s = scan_session(f)
    assert s.purpose == "__smoke__"


def test_scan_session_empty_file_returns_none(tmp_path):
    f = _write_session(tmp_path / "empty.jsonl", [])
    assert scan_session(f) is None


def test_scan_session_bad_json_returns_none(tmp_path):
    f = tmp_path / "bad.jsonl"
    f.write_text("{not json}\n{broken", encoding="utf-8")
    assert scan_session(f) is None


# ── scan_metrics_files ───────────────────────────────────────────────────

def test_scan_metrics_files_aggregates(tmp_path):
    d = tmp_path / "emp" / "tdm"
    d.mkdir(parents=True)
    (d / "a_metrics.jsonl").write_text(
        '{"timestamp":"t","model":"m1","total_tokens":100,"cache_hits":1,"cache_misses":0}\n'
        '{"timestamp":"t","model":"m1","total_tokens":300,"cache_hits":0,"cache_misses":1}\n',
        encoding="utf-8")
    (d / "b_metrics.jsonl").write_text(
        '{"timestamp":"t","model":"m2","total_tokens":200,"cache_hits":0,"cache_misses":0}\n',
        encoding="utf-8")
    agg = scan_metrics_files(tmp_path)
    assert agg["files"] == 2
    assert agg["turns_with_tokens"] == 3
    assert agg["avg_total_tokens"] == 200.0
    assert agg["cache_hit_rate"] == 0.5
    assert agg["models"] == {"m1": 2, "m2": 1}


def test_scan_metrics_files_empty(tmp_path):
    agg = scan_metrics_files(tmp_path)
    assert agg["files"] == 0
    assert agg["avg_total_tokens"] is None  # 诚实空态


# ── scan_audit ───────────────────────────────────────────────────────────

def _make_audit_db(path: Path, rows: list[tuple]) -> Path:
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE sf_mcp_call_audit (tool_name TEXT, verdict TEXT, created_at TEXT)")
    c.execute("CREATE TABLE audit_log (action TEXT, created_at TEXT)")
    c.executemany("INSERT INTO sf_mcp_call_audit VALUES (?,?,?)", rows)
    c.commit()
    c.close()
    return path


def test_scan_audit_verdict_distribution(tmp_path):
    db = _make_audit_db(tmp_path / "w.db", [
        ("scenario", "ok", "t"), ("validate", "ok", "t"),
        ("draft", "denied-whitelist", "t"), ("spec", "warn", "t"),
    ])
    agg = scan_audit(db)
    assert agg["available"] is True
    assert agg["total_calls"] == 4
    assert agg["denied_whitelist"] == 1
    assert agg["denied_whitelist_rate"] == 0.25
    assert agg["verdicts"]["ok"] == 2


def test_scan_audit_missing_db(tmp_path):
    agg = scan_audit(tmp_path / "nonexistent.db")
    assert agg["available"] is False  # 诚实空态，不炸


# ── build_baseline_report：七指标汇总 ────────────────────────────────────

def _seed_sessions(root: Path):
    """构造两个生产会话（一 PASS 一熔断）+ 一个 smoke 会话。"""
    _write_session(root / "90000001" / "tdm" / "ok.jsonl", [
        _meta(sid="ok"),
        {"role": "user", "content": "生成场景"},
        _asst_tool("c1", "validate"),
        _tool_row("c1", '{"verdict": "PASS"}'),
        {"_type": "metrics", "total_tokens": 1000, "model": "m"},
    ])
    _write_session(root / "90000001" / "tdm" / "fused.jsonl", [
        _meta(sid="fused"),
        {"role": "user", "content": "不对，重做"},
        _asst_tool("c2", "scenario(action=list)"),
        _tool_row("c2", "[越权拒绝] 无权限"),
        {"role": "system", "content": "[FUSE] 熔断"},
        {"_type": "metrics", "total_tokens": 3000, "model": "m"},
    ])
    _write_session(root / "90000001" / "smoke" / "smoke1.jsonl", [
        _meta(sid="smoke1"), {"role": "user", "content": "测试"}])


def test_build_report_excludes_smoke_and_counts(tmp_path):
    root = tmp_path / "sessions"
    _seed_sessions(root)
    db = _make_audit_db(tmp_path / "w.db", [("validate", "ok", "t")])
    rep = build_baseline_report(root, db)
    src = rep["data_sources"]
    assert src["session_files"] == 3
    assert src["production_sessions"] == 2
    assert src["smoke_sessions_excluded"] == 1

    ind = rep["indicators"]
    # 熔断率：2 个生产会话中 1 个熔断
    assert ind["3_fuse_rate"]["value"] == 0.5
    # 纠正触发率：1/2
    assert ind["6_correction_trigger_rate"]["value"] == 0.5
    # validate 一次通过率：仅 ok 会话有 validate 且 PASS → 1.0
    assert ind["5_validate_first_pass_rate"]["value"] == 1.0
    # 工具成功率：ok(1) / (ok 1 + fail 1) = 0.5
    assert ind["1_tool_call_success_rate"]["value"] == 0.5
    # token 均值：(1000+3000)/2 = 2000
    assert ind["7_avg_tokens_per_task"]["value"] == 2000.0


def test_build_report_empty_root_honest(tmp_path):
    root = tmp_path / "empty_sessions"
    root.mkdir()
    db = _make_audit_db(tmp_path / "w.db", [])
    rep = build_baseline_report(root, db)
    ind = rep["indicators"]
    # 无会话 → 各指标诚实 None，不造假数字
    assert ind["3_fuse_rate"]["value"] is None
    assert ind["6_correction_trigger_rate"]["value"] is None
    assert ind["7_avg_tokens_per_task"]["value"] is None


def test_render_markdown_smoke(tmp_path):
    root = tmp_path / "sessions"
    _seed_sessions(root)
    db = _make_audit_db(tmp_path / "w.db", [("validate", "ok", "t")])
    rep = build_baseline_report(root, db)
    md = render_markdown(rep)
    assert "# SpecGuard Agent Phase 0 基线仪表盘" in md
    assert "工具调用成功率" in md
    assert "越权拒绝率" in md
    assert "生产会话 2 个" in md
    assert "smoke 隔离区 1 个" in md
