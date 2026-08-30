"""test_flow_nudge.py — 路径纠正提示与自检工具测试（T-1042 三期）。

覆盖四块：
  1. sg_core.flow_nudge 纯函数（硬前置判定/文案/历史去重判定）
  2. 一致性钉：sg_core 预置前置族 ⊇ evals/flows JSON hard_order earlier 阶段
     全部工具候选——flow 定义变更未同步 sg_core 即红（防漂移）
  3. runtime 集成行为钉 5 条（ScriptedLLM 离线驱动真实 AgentRuntime 循环）：
     无 validate 先行→nudge；validate 在先→无；.sql 草稿→不触发；
     两次 draft write→仅一次（整会话去重）；结果成败不被 nudge 改写
  4. flow 自检工具：注册可见性（domain=meta/纯读/legacy 映射）+
     无会话上下文诚实降级 + 有会话文件时输出阶段四态
"""

from __future__ import annotations

import asyncio
import json

from sg_core import flow_nudge as fn
from sg_core.tool_units import normalize_tool_unit

# ── 1. 纯函数 ────────────────────────────────────────────────────────────

def test_gaps_empty_history_both_missing():
    assert fn.draft_write_prereq_gaps([]) == ["read_requirement", "validate"]


def test_gaps_validate_only_missing_requirement():
    units = [normalize_tool_unit("validate")]
    assert fn.draft_write_prereq_gaps(units) == ["read_requirement"]


def test_gaps_full_history_none():
    units = [normalize_tool_unit("read_spec"), normalize_tool_unit("validate")]
    assert fn.draft_write_prereq_gaps(units) == []


def test_gaps_legacy_and_new_forms_both_cover():
    """legacy（read_info_pack）与新形态（spec+action=read）都算满足前置。"""
    assert fn.draft_write_prereq_gaps([normalize_tool_unit("read_info_pack")]) == ["validate"]
    assert fn.draft_write_prereq_gaps(
        [normalize_tool_unit("spec", {"action": "read"})]) == ["validate"]


def test_build_nudge_marker_and_discretion():
    text = fn.build_flow_nudge(["read_requirement", "validate"])
    assert text.startswith(fn.NUDGE_MARKER)
    assert "无需补做" in text  # 诚实裁量：用户明确要求的跳过可说明即可
    assert "validate" in text and "读需求" in text
    assert fn.build_flow_nudge([]) == ""


def test_has_nudge_in_history():
    assert fn.has_nudge_in_history([{"role": "tool", "content": f"x\n\n{fn.NUDGE_MARKER} 路径提示"}])
    assert not fn.has_nudge_in_history([{"role": "tool", "content": "ok"}])


# ── 2. 一致性钉：sg_core 前置族 ⊇ flow JSON hard_order earlier 阶段 ──────

def test_prereq_families_cover_flow_hard_order():
    from evals.flowpath import load_flow

    defn = load_flow()
    assert defn.rebuilt_from_file, "flow 定义应来自 evals/flows JSON（内置兜底=文件丢了）"
    for earlier, _later in defn.hard_order:
        stage = defn.stage_by_key.get(earlier)
        assert stage is not None, f"hard_order 引用不存在的阶段 {earlier}"
        family = fn._PREREQ_FAMILIES.get(earlier)
        assert family is not None, f"sg_core 缺少阶段 {earlier} 的前置族——同步 flow 定义"
        for unit in stage.units:
            assert fn.family_hit(family, unit), \
                f"flow 阶段「{earlier}」候选 {unit} 不在 sg_core 前置族——build_flow 改定义后须同步 sg_core/flow_nudge.py"


# ── 3. runtime 集成行为钉（ScriptedLLM 离线驱动真实循环）─────────────────

from agent.runtime import AgentRuntime  # noqa: E402
from evals.harness import (  # noqa: E402
    MockToolModule,
    ScriptedLLM,
    _patch_user_store_audit,
    isolated_eval_context,
)


def _tc(call_id: str, name: str, args: dict | None = None) -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps(args or {}, ensure_ascii=False)}}


def _run_script(script: list[dict], mocks: dict[str, object]) -> list[dict]:
    llm = ScriptedLLM(script)
    with isolated_eval_context():
        rt = AgentRuntime(llm, max_turns=8)
        rt._record_audit = lambda *a, **k: None
        rt._take_snapshot_fingerprint = lambda: "eval-constant"
        _patch_user_store_audit(True)
        try:
            for name, spec in mocks.items():
                rt._tool_map[name] = MockToolModule(name, spec)
            return rt.run("（评测模式）测试助手。", "生成 FR-001 的测试场景")
        finally:
            _patch_user_store_audit(False)


def _tool_contents(messages: list[dict]) -> list[str]:
    return [m.get("content", "") for m in messages if m.get("role") == "tool"]


MOCKS = {
    "spec": {"text": "spec 内容"},
    "validate": {"text": '{"verdict": "PASS"}'},
    "draft": {"text": "已写入草稿"},
}


def test_nail_draft_without_validate_gets_nudge():
    """钉①：写 .yaml 草稿前无 validate → 结果尾含 [flow-nudge]。"""
    script = [
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c1", "draft", {"action": "write", "filename": "X-001.yaml", "content": "y"})]},
        {"role": "assistant", "content": "完成"},
    ]
    msgs = _run_script(script, MOCKS)
    tools = _tool_contents(msgs)
    assert any(fn.NUDGE_MARKER in c for c in tools), tools


def test_nail_validate_before_draft_no_nudge():
    """钉②：validate 在先 → 无 nudge。"""
    script = [
        {"role": "assistant", "content": "", "tool_calls": [_tc("c1", "validate")]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"verdict": "PASS"}'},
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c2", "draft", {"action": "write", "filename": "X-001.yaml", "content": "y"})]},
        {"role": "assistant", "content": "完成"},
    ]
    msgs = _run_script(script, MOCKS)
    assert not any(fn.NUDGE_MARKER in c for c in _tool_contents(msgs))


def test_nail_sql_draft_not_nudged():
    """钉③：.sql 等其他草稿不走 generate-scenario 纪律。"""
    script = [
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c1", "draft", {"action": "write", "filename": "q.sql", "content": "select 1"})]},
        {"role": "assistant", "content": "完成"},
    ]
    msgs = _run_script(script, MOCKS)
    assert not any(fn.NUDGE_MARKER in c for c in _tool_contents(msgs))


def test_nail_nudge_fires_once_per_session():
    """钉④：两次 draft write 仅首触（整会话去重）。"""
    script = [
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c1", "draft", {"action": "write", "filename": "X.yaml", "content": "y"})]},
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c2", "draft", {"action": "write", "filename": "Y.yaml", "content": "y"})]},
        {"role": "assistant", "content": "完成"},
    ]
    msgs = _run_script(script, MOCKS)
    assert sum(c.count(fn.NUDGE_MARKER) for c in _tool_contents(msgs)) == 1


def test_nail_nudge_does_not_change_result_verdict():
    """钉⑤：nudge 只追加不改写——结果正文保持原样（读需求在先时仅有 read 缺失之外的组合不再触发）。"""
    script = [
        {"role": "assistant", "content": "", "tool_calls": [_tc("c1", "spec", {"action": "read"})]},
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c2", "draft", {"action": "write", "filename": "X.yaml", "content": "y"})]},
        {"role": "assistant", "content": "完成"},
    ]
    msgs = _run_script(script, MOCKS)
    tool_texts = _tool_contents(msgs)
    draft_msg = [c for c in tool_texts if "已写入草稿" in c][0]
    assert draft_msg.startswith("已写入草稿"), "原结果必须原样保留，nudge 只追加尾部"
    assert fn.NUDGE_MARKER in draft_msg and "validate" in draft_msg


def test_nail_legacy_write_draft_form_also_fires():
    """旧形态 write_draft 同样触发（归一层覆盖）。"""
    script = [
        {"role": "assistant", "content": "", "tool_calls": [
            _tc("c1", "write_draft", {"filename": "L.yaml", "content": "y"})]},
        {"role": "assistant", "content": "完成"},
    ]
    msgs = _run_script(script, MOCKS)
    assert any(fn.NUDGE_MARKER in c for c in _tool_contents(msgs))


# ── 4. flow 自检工具 ─────────────────────────────────────────────────────

def test_flow_tool_registered_meta_readonly():
    from mcp_server.server import TOOL_NAME_TO_MODULE
    from mcp_server.tools.tool_meta import _TOOL_META, legacy_owner

    assert "flow" in TOOL_NAME_TO_MODULE
    meta = _TOOL_META["flow"]
    assert meta.domain == "meta"          # 全 purpose 常驻
    assert meta.side_effect == "none"     # 纯读
    assert legacy_owner("flow_status") == ("flow", "status")


def test_flow_tool_without_session_context_degrades():
    from mcp_server.tools import flow_status
    from sg_core import session_context as sc

    tok_sid = sc._CTX_SESSION_ID.set("")
    tok_scope = sc.set_runtime_scope(None)
    try:
        [tc] = asyncio.run(flow_status.handle("flow", {"action": "status"}))
        assert "不在会话上下文" in tc.text
    finally:
        sc.reset_runtime_scope(tok_scope)
        sc.reset_session_id(tok_sid)


def test_flow_tool_with_session_file_reports_stages(tmp_path):
    from mcp_server.tools import flow_status
    from sg_core import session_context as sc

    sid = "20260830_100000_flowtest1"
    rows = [
        {"_type": "session_meta", "session_id": sid, "purpose": "test_workbench",
         "workspace": "tdm", "emp_no": "x"},
        {"role": "user", "content": "生成场景"},
        {"role": "assistant", "tool_calls": [_tc("a", "spec", {"action": "read"})]},
        {"role": "tool", "tool_call_id": "a", "content": "spec 内容"},
        {"role": "assistant", "tool_calls": [
            _tc("b", "draft", {"action": "write", "filename": "X.yaml", "content": "y"})]},
        {"role": "tool", "tool_call_id": "b", "content": "已写入"},
    ]
    (tmp_path / f"{sid}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    tok_sid = sc._CTX_SESSION_ID.set(sid)
    tok_scope = sc.set_runtime_scope({"sid": sid, "sessions_dir": str(tmp_path)})
    try:
        [tc] = asyncio.run(flow_status.handle("flow", {"action": "status"}))
        text = tc.text
    finally:
        sc.reset_runtime_scope(tok_scope)
        sc.reset_session_id(tok_sid)

    assert "[flow 自检]" in text
    assert "读需求" in text and "顺序正确" in text
    assert "缺失" in text        # get_id/query_registry 等未走
    assert "仅供参考" in text    # 诚实裁量声明
