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


def test_flow_selfcheck_excluded_as_benign(tmp_path):
    """flow 自检是设计内观察行为（技能 v1.2.0 明示引导），benign 剔除不进旁支。"""
    rows = _golden_rows("selfcheck")
    rows += [
        _asst("s1", "flow", {"action": "status"}), _tool("s1", "[flow 自检] …"),
        _asst("s2", "flow", {"action": "status"}), _tool("s2", "[flow 自检] …"),
    ]
    trace = trace_scan(scan_session(_write_session(tmp_path / "selfcheck.jsonl", rows)))
    assert trace.extras == [], f"flow 自检不应进计划外旁支: {trace.extras}"
    assert trace.deviations == []


def test_build_flow_check_immune_to_benign_new_tool(tmp_path):
    """--check 对 benign 新工具免疫（自检类元工具不进阶段、不算漂移）。"""
    from evals.build_flow import build_flow

    skill = tmp_path / "skill.md"
    skill.write_text(
        "---\nname: t\nversion: 1.0.0\n"
        "depends_tools: [spec(action=read), flow(action=status)]\n---\n正文\n",
        encoding="utf-8")
    flow_json = tmp_path / "t.flow.json"
    base = {"id": "t", "title": "t", "hard_order": [], "benign_bases": ["flow"],
            "stages": [{"key": "read_requirement", "label": "读需求",
                        "tools": ["spec(action=read)"], "required": True}]}
    flow_json.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    # 免疫：flow 基名在 benign_bases → 不漂移、不追加阶段
    assert build_flow(skill, flow_json, check=True) == 0
    after = json.loads(flow_json.read_text(encoding="utf-8"))
    assert [s["key"] for s in after["stages"]] == ["read_requirement"]
    # 非空转对照：benign 摘除 flow → 同一技能报漂移
    base["benign_bases"] = []
    flow_json.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    assert build_flow(skill, flow_json, check=True) == 1


# ── 网状拓扑：历程边热力 / 问题调用角标 / 门穿透 / 野跳 / 约束边 ─────────────

def _rows_with_verdicts(sid, calls):
    """calls: [(tool, args, verdict)]——assistant 声明 + tool 结果成败配对（失败按真实错误前缀形态）。"""
    rows = [_meta(sid), {"role": "user", "content": "生成场景"}]
    for i, (tool, args, verdict) in enumerate(calls):
        cid = f"c{i}"
        rows.append(_asst(cid, tool, args))
        rows.append(_tool(cid, '{"ok": true}' if verdict == "ok" else "错误：模拟失败"))
    return rows


def test_edge_hits_and_gate_through(tmp_path):
    """相邻阶段对推边热力；无直接边的相邻对单跳门穿透（find_reference→validate 穿过规划门）。"""
    calls = [("spec", {"action": "read"}, "ok"), ("scenario", {"action": "next_id"}, "ok"),
             ("query_registry", {}, "ok"), ("scenario", {"action": "list"}, "ok"),
             ("validate", {}, "ok"), ("draft", {"action": "write"}, "ok")]
    trace = trace_scan(scan_session(_write_session(tmp_path / "e.jsonl", _rows_with_verdicts("e", calls))))
    assert trace.edge_hits[("read_requirement", "get_id")] == 1
    assert trace.edge_hits[("find_reference", "validate")] == 1  # 原始相邻对（穿透前）
    mm = render_flow_mermaid(trace)
    # 门穿透后：G1 入边与「确认规划」出边各 ×1
    assert 'G1{"规划确认"}' in mm
    assert '"确认规划 ×1"' in mm


def test_loop_edges_and_fail_badges(tmp_path):
    """validate 失败重试 → 自环回边 ×1 + 节点 ⚠1 角标；试跑 FAIL 归因 → trial_run 自环。"""
    calls = [("spec", {"action": "read"}, "ok"), ("scenario", {"action": "next_id"}, "ok"),
             ("query_registry", {}, "ok"), ("scenario", {"action": "list"}, "ok"),
             ("validate", {}, "fail"), ("validate", {}, "ok"),
             ("draft", {"action": "write"}, "ok"), ("scenario", {"action": "suggest_deps"}, "ok"),
             ("scenario", {"action": "run"}, "fail"), ("attribution", {}, "ok")]
    trace = trace_scan(scan_session(_write_session(tmp_path / "l.jsonl", _rows_with_verdicts("l", calls))))
    assert trace.edge_hits[("validate", "validate")] == 1
    assert trace.edge_hits[("trial_run", "trial_run")] == 1
    assert _state(trace, "validate").fails == 1
    assert _state(trace, "trial_run").fails == 1
    mm = render_flow_mermaid(trace)
    assert "重新生成再校 ×1" in mm
    assert "归因重跑 ×1" in mm
    assert "⚠1" in mm  # 问题调用角标


def test_self_loop_undefined_not_wild(tmp_path):
    """拓扑未定义的自环（连读两次需求）不算野跳——阶段内重复由节点 ×N 表达。"""
    calls = [("spec", {"action": "read"}, "ok"), ("spec", {"action": "search"}, "ok"),
             ("scenario", {"action": "next_id"}, "ok")]
    trace = trace_scan(scan_session(_write_session(tmp_path / "s.jsonl", _rows_with_verdicts("s", calls))))
    assert trace.edge_hits[("read_requirement", "read_requirement")] == 1
    mm = render_flow_mermaid(trace)
    assert "×2" in mm  # 节点次数表达
    # 不出现野跳边样式（自环豁免；野跳独有 dasharray 4 3，约束边 2 3/回边 3 3 不撞）
    assert "stroke-dasharray:4 3" not in mm


def test_wild_jump_rendered(tmp_path):
    """拓扑未定义的跨阶段跳（写草稿直接试跑，跳过依赖建议）→ 琥珀野跳虚线。"""
    calls = [("spec", {"action": "read"}, "ok"), ("scenario", {"action": "next_id"}, "ok"),
             ("query_registry", {}, "ok"), ("scenario", {"action": "list"}, "ok"),
             ("validate", {}, "ok"), ("draft", {"action": "write"}, "ok"),
             ("scenario", {"action": "run"}, "ok")]
    trace = trace_scan(scan_session(_write_session(tmp_path / "w.jsonl", _rows_with_verdicts("w", calls))))
    assert trace.edge_hits[("write_draft", "trial_run")] == 1
    mm = render_flow_mermaid(trace)
    assert "stroke:#f0b429" in mm  # 野跳边样式（低频档退为背景纹理）
    assert "opacity:0.45" in mm


def test_hard_order_constraint_edge(tmp_path):
    """前置约束显式成边：正常淡灰，乱序（写草稿先于 validate）红色加粗。"""
    rows = [_meta("ho"), {"role": "user", "content": "x"},
            _asst("a", "write_draft"), _tool("a", "ok"),
            _asst("b", "validate"), _tool("b", "ok")]
    trace = trace_scan(scan_session(_write_session(tmp_path / "ho.jsonl", rows)))
    mm = render_flow_mermaid(trace)
    assert "须先 validate 校验" in mm and "须先 读需求" in mm
    assert "stroke:#eb5757,stroke-width:2.2px" in mm  # 违例红
    mm2 = render_flow_mermaid(trace_session(_write_session(tmp_path / "g.jsonl", _golden_rows("g"))))
    assert "stroke:#eb5757,stroke-width:2.2px" not in mm2  # 全绿无违例红


def test_legacy_def_without_topology_linear_fallback():
    """旧定义（无 topology）装载时按阶段序线性兜底。"""
    from evals.flowpath import FlowStage, _linear_topology
    stages = (FlowStage("a", "A", (("x", ""),), True), FlowStage("b", "B", (("y", ""),), True))
    topo = _linear_topology(stages)
    assert [(e.from_key, e.to_key, e.kind) for e in topo] == [("a", "b", "main")]


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
