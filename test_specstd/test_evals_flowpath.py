"""test_evals_flowpath.py — 路径重放（§16.1 golden flow 比对）单测（T-1042）。

离线可跑（tmp_path 合成会话）。覆盖：四态判定（in_order/out_of_order/missing/
skipped）、硬顺序约束证据（步号）、新（基名+action）/旧（legacy）两形态命中、
计划外工具与 benign 剔除、着色 mermaid 渲染、批量索引排序。
非空转证明：缺失/乱序与完整路径成对翻案；新旧形态各测一遍同一路径。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.baseline import scan_session
from evals.flowpath import (
    render_flow_mermaid,
    render_trace_markdown,
    trace_all_generate,
    trace_scan,
    trace_session,
)


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
         "function": {"name": tool,
                      "arguments": json.dumps(args or {}, ensure_ascii=False)}}]}


def _tool(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _golden_rows(sid="golden"):
    """教科书级完整路径（legacy 形态）：读需求→ID→注册表→参照→校验→草稿。"""
    return [
        _meta(sid),
        {"role": "user", "content": "生成 FR-001 的测试场景"},
        _asst("a", "read_spec"), _tool("a", "{}"),
        _asst("b", "next_scenario_id"), _tool("b", "S1"),
        _asst("c", "query_registry"), _tool("c", "{}"),
        _asst("d", "list_scenarios"), _tool("d", "[]"),
        _asst("e", "validate"), _tool("e", '{"verdict":"PASS"}'),
        _asst("f", "write_draft"), _tool("f", "ok"),
    ]


def _state(trace, key):
    return next(s for s in trace.stages if s.key == key)


# ── 完整路径：全绿无跑偏 ─────────────────────────────────────────────────

def test_golden_path_all_in_order(tmp_path):
    f = _write_session(tmp_path / "golden.jsonl", _golden_rows())
    trace = trace_session(f)
    assert trace is not None
    assert trace.is_generate is True
    assert trace.deviations == []
    for key in ("read_requirement", "get_id", "query_registry",
                "find_reference", "validate", "write_draft"):
        assert _state(trace, key).status == "in_order", key
    # 步号与次数正确
    assert _state(trace, "read_requirement").first_step == 1
    assert _state(trace, "write_draft").first_step == 6


def test_golden_path_new_form_base_plus_action(tmp_path):
    """T-982 后新形态（基名+arguments.action）走同一路径同样全绿（非空转对照）。"""
    rows = [
        _meta("newform"),
        {"role": "user", "content": "生成场景"},
        _asst("a", "spec", {"action": "read", "path": "specs/x/spec.md"}), _tool("a", "{}"),
        _asst("b", "scenario", {"action": "next_id"}), _tool("b", "S1"),
        _asst("c", "query_registry", {}), _tool("c", "{}"),
        _asst("d", "scenario", {"action": "list"}), _tool("d", "[]"),
        _asst("e", "validate", {}), _tool("e", '{"verdict":"PASS"}'),
        _asst("f", "draft", {"action": "write", "path": "d/x.yaml", "content": "y"}), _tool("f", "ok"),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "newform.jsonl", rows)))
    assert trace.deviations == []
    for key in ("read_requirement", "get_id", "find_reference", "validate", "write_draft"):
        assert _state(trace, key).status == "in_order", key


# ── 乱序：写草稿先于校验/读需求 ──────────────────────────────────────────

def test_draft_before_validate_out_of_order(tmp_path):
    rows = [
        _meta("ooo"),
        {"role": "user", "content": "生成场景"},
        _asst("a", "read_spec"), _tool("a", "{}"),
        _asst("b", "write_draft"), _tool("b", "ok"),
        _asst("c", "validate"), _tool("c", '{"verdict":"PASS"}'),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "ooo.jsonl", rows)))
    assert _state(trace, "write_draft").status == "out_of_order"
    assert any("先于" in d and "validate 校验" in d for d in trace.deviations)
    # 证据带步号：写草稿第 2 步、校验第 3 步
    assert any("第 2 步" in d and "第 3 步" in d for d in trace.deviations)
    assert _state(trace, "validate").status == "in_order"  # 校验自身位置无违例


def test_draft_before_read_requirement_out_of_order(tmp_path):
    rows = [
        _meta("ooo2"),
        {"role": "user", "content": "生成场景"},
        _asst("a", "validate"), _tool("a", '{"verdict":"PASS"}'),
        _asst("b", "write_draft"), _tool("b", "ok"),
        _asst("c", "read_spec"), _tool("c", "{}"),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "ooo2.jsonl", rows)))
    assert _state(trace, "write_draft").status == "out_of_order"
    assert any("读需求" in d for d in trace.deviations)


# ── 缺失必需阶段 ─────────────────────────────────────────────────────────

def test_missing_validate_flagged(tmp_path):
    rows = [
        _meta("nov"),
        {"role": "user", "content": "生成场景"},
        _asst("a", "read_spec"), _tool("a", "{}"),
        _asst("b", "next_scenario_id"), _tool("b", "S1"),
        _asst("c", "write_draft"), _tool("c", "ok"),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "nov.jsonl", rows)))
    st = _state(trace, "validate")
    assert st.status == "missing"
    assert any("缺失必需阶段「validate 校验」" in d for d in trace.deviations)
    # 未跳过读需求：读需求→写草稿顺序 OK，不误报乱序
    assert _state(trace, "read_requirement").status == "in_order"


# ── 可选阶段：跳过不报差异 ───────────────────────────────────────────────

def test_optional_skipped_not_deviation(tmp_path):
    f = _write_session(tmp_path / "g.jsonl", _golden_rows("noskill"))
    trace = trace_session(f)
    assert _state(trace, "read_skill").status == "skipped"
    assert _state(trace, "permission_precheck").status == "skipped"
    assert all("read_skill" not in d and "权限预检" not in d for d in trace.deviations)


def test_optional_hit_when_dag_check_present(tmp_path):
    rows = _golden_rows("dag")
    rows.insert(5, _asst("d2", "check_dag"))
    rows.insert(6, _tool("d2", "无环"))
    trace = trace_scan(scan_session(_write_session(tmp_path / "dag.jsonl", rows)))
    assert _state(trace, "dag_design").status == "in_order"
    assert _state(trace, "dag_design").times == 1


# ── 计划外工具与 benign 剔除 ─────────────────────────────────────────────

def test_extras_listed_and_benign_excluded(tmp_path):
    rows = _golden_rows("extras")
    rows += [
        _asst("x1", "sync_workspace"), _tool("x1", "ok"),
        _asst("x2", "todo_write"), _tool("x2", "待办已更新"),
        _asst("x3", "sync_workspace"), _tool("x3", "ok"),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "extras.jsonl", rows)))
    # sync_workspace 是 legacy 名，归一为 spec(action=sync)——展示带 action 不与 read_spec 混淆
    assert "spec(sync)×2" in trace.extras
    assert all("todo_write" not in e for e in trace.extras)
    # 计划外不算差异（deviations 只含阶段级跑偏）
    assert trace.deviations == []


def test_promote_maps_to_stage_not_extra(tmp_path):
    rows = _golden_rows("promo")
    rows += [_asst("p", "promote_draft"), _tool("p", "入库成功")]
    trace = trace_scan(scan_session(_write_session(tmp_path / "promo.jsonl", rows)))
    assert _state(trace, "promote").status == "in_order"
    assert all("promote" not in e for e in trace.extras)


# ── 渲染：mermaid 着色 + markdown 差异表 ─────────────────────────────────

def test_mermaid_renders_status_classes(tmp_path):
    rows = [
        _meta("m"), {"role": "user", "content": "x"},
        _asst("a", "write_draft"), _tool("a", "ok"),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "m.jsonl", rows)))
    mm = render_flow_mermaid(trace)
    assert "flowchart TD" in mm
    assert "classDef hit" in mm and "classDef missing" in mm and "classDef warn" in mm
    assert "✗" in mm  # 缺失 glyph（validate 等）
    md = render_trace_markdown(trace)
    assert "# 会话路径重放：m" in md
    assert "跑偏点" in md
    assert "缺失必需阶段" in md


def test_mermaid_clean_path_no_missing(tmp_path):
    f = _write_session(tmp_path / "g2.jsonl", _golden_rows("g2"))
    trace = trace_session(f)
    md = render_trace_markdown(trace)
    assert "无跑偏" in md
    assert "缺失必需阶段" not in md


# ── 批量：索引按差异数降序 ────────────────────────────────────────────────

def test_trace_all_generate_index_sorted(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root / "a" / "good.jsonl", _golden_rows("good"))
    bad = _golden_rows("bad")
    # 去掉 validate + 乱序写草稿 → 差异更多
    bad = [r for r in bad if not (r.get("role") == "assistant"
                                  and r.get("tool_calls", [{}])[0].get("function", {}).get("name") == "validate")]
    bad = [bad[0], bad[1]] + [bad[-2], bad[-1]]  # meta/user + write_draft + tool（乱序简化）
    _write_session(root / "a" / "bad.jsonl", bad)
    _write_session(root / "a" / "query.jsonl", [
        _meta("query"), _asst("a", "query_registry"), _tool("a", "{}")])

    summary = trace_all_generate(root, tmp_path / "traces")
    assert summary["traced"] == 2  # good + bad，query 非生成会话被过滤
    ids = [r["session_id"] for r in summary["index"]]
    assert set(ids) == {"good", "bad"}
    # 降序：bad（有差异）在前
    assert summary["index"][0]["session_id"] == "bad"
    assert (tmp_path / "traces" / "index.md").exists()
    assert (tmp_path / "traces" / "good.md").exists()


def test_trace_session_bad_file_returns_none(tmp_path):
    f = tmp_path / "broken.jsonl"
    f.write_text("{not json", encoding="utf-8")
    assert trace_session(f) is None
