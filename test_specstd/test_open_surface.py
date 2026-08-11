"""S8 对外开放面测试（T-083 + T-085）。

覆盖：
- T-083：open/ 命名空间 L0 五模块注册、L2 写工具物理不存在、side_effect 全 none
- T-083：旗舰 e2e——get_frozen_spec（FR 锚点+SHALL+delta 契约）→ 查受影响场景（trace/query_graph）
         → 读执行报告（read_run_report）
- T-085：dev_context 三入口（by_zt_ref/by_anchor/by_fr）→ 六分区 pack + 聚合指纹
- T-085：草稿零泄漏（drafts/ 草稿物理不可达）；未冻结 delta 不可达
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from test_specstd.helpers import create_valid_workspace  # noqa: E402
from specstd.workspace import (  # noqa: E402
    register_local, unregister, set_context_workspace, reset_context_workspace,
)
from mcp_server.tools.open import (  # noqa: E402
    specflow_refs as open_refs,
    quality_query as open_quality,
    lineage_query as open_lineage,
    refs_query as open_refs_query,
    dev_context as open_devctx,
)
from mcp_server.tools.side_effect_registry import get_side_effect  # noqa: E402
from workbench.backend.services.specflow import sf_store, sf_refs_store  # noqa: E402


def _call(module, name, arguments):
    return asyncio.run(module.handle(name, arguments))


def _parse(result) -> dict:
    return json.loads(result[0].text)


# ══════════════════════════════════════════════════════════
# 环境：合规工作区 + 冻结 delta + 图谱 + 台账 + 报告
# ══════════════════════════════════════════════════════════

SPEC_FR12 = (
    "### FR-012: 作废级联删除 [delta:grid-rule-perf]\n"
    "作废九宫格规则时 SHALL 级联删除其下全部子规则。\n"
    "AC-101 作废父规则后子规则不可见\n"
    "AC-102 级联删除记录可审计\n"
)

DELTA_SPEC = (
    "# Delta: grid-rule-perf\n\n"
    "## ADDED Requirements\n\n"
    "### FR-012: 作废级联删除 [delta:grid-rule-perf]\n\n"
    "作废时 SHALL 级联删除子规则。\n\n"
    "→ task: TSK-101\n"
)

DELTA_MANIFEST = (
    "delta: grid-rule-perf\n"
    "specstd_version: \"1.0\"\n"
    "source_interview: IV-001\n"
    "base_spec: specs/inventory/grid-placement/spec.md\n"
    "base_spec_sha: \"abc123\"\n"
    "operations:\n"
    "  - op: ADDED\n"
    "    anchor: FR-012\n"
    "    version_mark: \"[delta:grid-rule-perf ADDED]\"\n"
    "freeze:\n"
    "  frozen_at: \"2026-08-11T10:00:00Z\"\n"
    "  gates: {product_confirm: pass, conformance: pass, p0_zero: pass}\n"
)

FREEZE_YAML = (
    "delta: grid-rule-perf\n"
    "interview_id: IV-001\n"
    "workspace: test-open\n"
    "frozen_by: E10001\n"
    "frozen_at: \"2026-08-11T10:00:00Z\"\n"
    "spec_sha: \"abc123\"\n"
    "gates:\n"
    "  product_confirm: {status: pass}\n"
    "  conformance: {status: pass}\n"
    "  p0_zero: {status: pass}\n"
)

PROPOSAL_MD = (
    "# Proposal: grid-rule-perf\n\n"
    "## 1. 为什么做\n\n作废规则需级联清理。\n\n"
    "## 2. 做什么\n\nFR-012 作废级联删除。\n\n"
    "## 3. 不做什么\n\n不处理历史数据迁移。\n\n"
    "## 4. 验收口径\n\nAC-101/AC-102 通过。\n"
)

SCENARIO_YAML = (
    "# ─────────── 人读层：doc ───────────\n"
    "id: ST-TEST-001\n"
    "title: 作废规则级联删除验证\n"
    "version: \"0.1\"\n"
    "priority: P0\n"
    "doc:\n"
    "  covers: [FR-012]\n"
    "  given: 存在父规则与子规则\n"
    "  when: 作废父规则\n"
    "  then: 子规则不可见且审计可查\n"
    "# ─────────── 机器读层 ───────────\n"
    "depends_on: [ST-PREP-001]\n"
    "flow:\n"
    "  - call:\n"
    "      method: DELETE\n"
    "      path: /api/grid-rules/{{ruleId}}\n"
    "      save: del_resp\n"
    "verify:\n"
    "  - json: {of: del_resp, path: \"$.data.effected\", eq: 3}\n"
)

PREP_YAML = (
    "id: ST-PREP-001\n"
    "title: 规则数据准备\n"
    "version: \"0.1\"\n"
    "doc:\n"
    "  given: 权限就绪\n"
    "  when: 创建父规则与子规则\n"
    "  then: 数据落库\n"
    "depends_on: []\n"
    "flow:\n"
    "  - call:\n"
    "      method: POST\n"
    "      path: /api/grid-rules\n"
    "      save: rule\n"
    "verify:\n"
    "  - status: {of: rule, eq: 201}\n"
)

PLAN_YAML = (
    "id: plan-7\n"
    "name: 作废级联验收计划\n"
    "env: sit\n"
    "filter:\n"
    "  scenarios: [ST-PREP-001, ST-TEST-001]\n"
    "breakpoints: [ST-TEST-001]\n"
    "source_delta: grid-rule-perf\n"
)

DRAFT_YAML = (
    "# 草稿（零泄漏验证目标）\n"
    "id: DR-LEAK-001\n"
    "title: 草稿泄漏探针场景\n"
    "doc:\n"
    "  covers: [FR-012]\n"
    "  when: 这是草稿不应出现在 dev-context-pack\n"
    "flow: []\n"
)

RUN_JSON = {
    "schema_version": "2.0",
    "run_id": "EX-abc123",
    "env": "sit",
    "stats": {"total": 1, "passed": 0, "failed": 1},
    "cases": [{"id": "ST-TEST-001", "verdict": "FAIL", "duration_ms": 120}],
}

CASE_JSON = {
    "scenario_id": "ST-TEST-001",
    "title": "作废规则级联删除验证",
    "covers": ["FR-012"],
    "verdict": "FAIL",
    "failure": {"category": "assert", "message": "$.data.effected 期望 3 实际 1"},
    "duration_ms": 120,
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离注册表/DB + 合规工作区 + 冻结 delta + 图谱 + 台账 + 报告 + 草稿。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    monkeypatch.setattr(sf_store, "DB_PATH", tmp_path / "workbench.db")

    ws = create_valid_workspace(tmp_path / "ws")

    # 基线 spec：inventory/grid-placement 模块（FR-012 + SHALL + AC）
    inv_dir = ws / "specs" / "inventory" / "grid-placement"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "spec.md").write_text(
        "# 九宫格落位\n\n## 一、功能描述\n\n" + SPEC_FR12, encoding="utf-8")

    # 冻结 delta（.specflow/changes/，S5 正式路径）
    changes = ws / ".specflow" / "changes" / "grid-rule-perf"
    changes.mkdir(parents=True, exist_ok=True)
    (changes / "FREEZE.yaml").write_text(FREEZE_YAML, encoding="utf-8")
    (changes / "delta.manifest.yaml").write_text(DELTA_MANIFEST, encoding="utf-8")
    (changes / "delta-spec.md").write_text(DELTA_SPEC, encoding="utf-8")
    (changes / "proposal.md").write_text(PROPOSAL_MD, encoding="utf-8")
    # 未冻结 delta（不可达验证）
    (ws / ".specflow" / "changes" / "wip-delta").mkdir(parents=True, exist_ok=True)
    (ws / ".specflow" / "changes" / "wip-delta" / "delta-spec.md").write_text(
        "# Delta: wip-delta\n", encoding="utf-8")

    # 场景库（工作区内，builder sg_root=ws → source_ref 相对工作区）
    sc_dir = ws / "scenarios" / "inventory" / "grid-placement"
    sc_dir.mkdir(parents=True, exist_ok=True)
    (sc_dir / "ST-PREP-001.yaml").write_text(PREP_YAML, encoding="utf-8")
    (sc_dir / "ST-TEST-001.yaml").write_text(SCENARIO_YAML, encoding="utf-8")

    # 计划 + 报告 + 草稿（草稿零泄漏验证目标）
    (ws / ".specguard" / "plans").mkdir(parents=True, exist_ok=True)
    (ws / ".specguard" / "plans" / "plan-7.yaml").write_text(PLAN_YAML, encoding="utf-8")
    (ws / ".specguard" / "reports" / "EX-abc123").mkdir(parents=True, exist_ok=True)
    (ws / ".specguard" / "reports" / "EX-abc123" / "run.json").write_text(
        json.dumps(RUN_JSON), encoding="utf-8")
    (ws / ".specguard" / "reports" / "EX-abc123" / "cases").mkdir(parents=True, exist_ok=True)
    (ws / ".specguard" / "reports" / "EX-abc123" / "cases" / "ST-TEST-001.json").write_text(
        json.dumps(CASE_JSON), encoding="utf-8")
    (ws / ".specguard" / "drafts").mkdir(parents=True, exist_ok=True)
    (ws / ".specguard" / "drafts" / "DR-LEAK-001.yaml").write_text(DRAFT_YAML, encoding="utf-8")

    # 台账：外部锚点 + 面试 + 决策（D-001 resolved + amendment 链）
    db = tmp_path / "workbench.db"
    sf_store.init_tables(db)
    sf_refs_store.init_tables(db)
    sf_refs_store.register_ref("test-open", "zt_story", "ZT-STORY-4821",
                               "delta", "grid-rule-perf",
                               registered_by="system:zentao-cli", db_path=db)
    sf_store.create_interview("IV-001", "test-open", "SESS-1",
                              "作废级联删除", "E10001", target_delta="grid-rule-perf",
                              db_path=db)
    from specflow.interview.decision_ledger import init_tables as ledger_init
    import sqlite3
    conn = sqlite3.connect(str(db))
    ledger_init(conn)
    conn.execute(
        "INSERT INTO sf_decisions (id, workspace, interview_id, priority, question, "
        "status, resolution, content_sha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("D-001", "test-open", "IV-001", "P0", "作废规则如何处理子规则？",
         "resolved", "级联删除并审计", "deadbeef"))
    conn.execute(
        "INSERT INTO sf_decision_links (decision_id, link_type, link_ref) "
        "VALUES ('D-001', 'fr_anchor', 'FR-012')")
    conn.commit()
    conn.close()

    # 图谱索引（确定性派生，sg_root=ws → source_ref 相对工作区）
    from graph_index.builder import build_index
    from graph_index.service import index_path
    build_index(ws, index_path(ws), scenarios_root=sc_dir, sg_root=ws, db_path=db)

    register_local("test-open", str(ws), "tdm", activate=True)
    tok = set_context_workspace("test-open")
    yield "test-open"
    reset_context_workspace(tok)
    unregister("test-open")


# ══════════════════════════════════════════════════════════
# T-083：注册与分层纪律
# ══════════════════════════════════════════════════════════

class TestOpenRegistration:
    OPEN_MODULES = [open_refs, open_quality, open_lineage, open_refs_query, open_devctx]

    def test_five_modules_sixteen_tools(self):
        names = sorted({t.name for mod in self.OPEN_MODULES for t in mod.TOOLS})
        assert names == [
            "dev_context_by_anchor", "dev_context_by_fr", "dev_context_by_zt_ref",
            "get_coverage_gaps", "get_delta_contract", "get_frozen_spec",
            "get_interview_status", "get_plan_status", "get_proposal",
            "get_test_debt", "lookup_external_ref", "query_decisions",
            "query_graph", "read_run_report", "trace_backward", "trace_forward",
        ]

    def test_l2_tools_absent_in_open(self):
        """L2 永不开放清单：promote/禅道写/平台管理/面试过程工具在 open/ 物理不存在。"""
        names = {t.name for mod in self.OPEN_MODULES for t in mod.TOOLS}
        l2 = {
            # 草稿晋升
            "promote_draft", "promote_drafts", "write_draft", "edit_dependency",
            # 禅道写
            "sf_register_external_ref", "sf_suggest_story_draft",
            "story_create", "bug_create",
            # 面试过程
            "iv_open_topic", "iv_record_answer", "iv_append_transcript",
            "iv_next_question", "iv_ask_question", "iv_p0_clear_check",
            # 测试数据制造 / 图谱索引构建 / 平台管理
            "fabricate_data", "graph_rebuild", "graph_snapshot", "pack_assemble",
            "run_scenario", "todo_write",
        }
        assert not (names & l2), f"L2 工具泄漏进 open/: {names & l2}"

    def test_all_open_tools_pure_read(self):
        """L0 纯读强制：open 工具 side_effect 全部 none（运行时指纹比对生效）。"""
        for mod in self.OPEN_MODULES:
            for t in mod.TOOLS:
                assert get_side_effect(t.name) == "none", f"{t.name} 非纯读"


# ══════════════════════════════════════════════════════════
# T-083：specflow_refs 五工具
# ══════════════════════════════════════════════════════════

class TestSpecflowRefs:
    def test_get_frozen_spec_anchors_shall_delta(self, env):
        r = _parse(_call(open_refs, "get_frozen_spec", {"module": "inventory"}))
        assert r["ok"] is True
        assert "FR-012" in r["anchors"]
        assert r["anchors"]["FR-012"]["ac_ids"] == ["AC-101", "AC-102"]
        # SHALL 强制条款
        assert any("SHALL" in s["text"] for s in r["shall_clauses"])
        # delta 标记 + 已冻结清单
        assert "grid-rule-perf" in r["delta_marks"]
        assert any(f["delta_id"] == "grid-rule-perf" for f in r["frozen_deltas"])
        # 基线 spec 全文（FR 锚点 + SHALL 段落）
        assert "FR-012" in r["spec_md"] and "SHALL" in r["spec_md"]

    def test_get_frozen_spec_module_missing_self_heal(self, env):
        r = _parse(_call(open_refs, "get_frozen_spec", {"module": "nope"}))
        assert r["ok"] is False
        assert "inventory" in r["available_modules"] or "module1" in r["available_modules"]

    def test_get_delta_contract(self, env):
        r = _parse(_call(open_refs, "get_delta_contract", {"delta_id": "grid-rule-perf"}))
        assert r["ok"] is True
        assert r["sections"]["ADDED"][0]["anchor"] == "FR-012"
        assert r["manifest"]["source_interview"] == "IV-001"
        assert r["freeze"]["frozen_at"] == "2026-08-11T10:00:00Z"
        assert r["contract_expectations"]["tool"] == "specguard-open-l0"
        assert r["contract_expectations"]["version"] == "1.0"

    def test_get_delta_contract_unfrozen_unreachable(self, env):
        r = _parse(_call(open_refs, "get_delta_contract", {"delta_id": "wip-delta"}))
        assert r["ok"] is False and "未冻结" in r["error"]

    def test_get_proposal_four_sections(self, env):
        r = _parse(_call(open_refs, "get_proposal", {"delta_id": "grid-rule-perf"}))
        assert r["ok"] is True
        assert r["sections"]["为什么做"] == "作废规则需级联清理。"
        assert r["sections"]["不做什么"] == "不处理历史数据迁移。"
        assert r["missing_sections"] == []

    def test_query_decisions_by_biz_ref(self, env):
        r = _parse(_call(open_refs, "query_decisions", {"biz_ref": "FR-012"}))
        assert r["ok"] is True
        assert r["count"] >= 1
        d = r["decisions"][0]
        assert d["id"] == "D-001" and d["status"] == "resolved"
        assert d["resolution"] == "级联删除并审计"

    def test_query_decisions_by_level(self, env):
        r = _parse(_call(open_refs, "query_decisions", {"level": "P0"}))
        assert r["count"] >= 1
        assert all(d["priority"] == "P0" for d in r["decisions"])

    def test_get_interview_status(self, env):
        r = _parse(_call(open_refs, "get_interview_status", {"iv_id": "IV-001"}))
        assert r["ok"] is True
        assert r["status"] == "opened"
        assert r["target_delta"] == "grid-rule-perf"
        assert "p0_cleared" in r


# ══════════════════════════════════════════════════════════
# T-083：quality_query 四工具
# ══════════════════════════════════════════════════════════

class TestQualityQuery:
    def test_get_coverage_gaps(self, env):
        r = _parse(_call(open_quality, "get_coverage_gaps", {"module": "inventory"}))
        assert r["ok"] is True
        assert "lanes" in r and "fingerprint" in r
        assert any(g["fr"] == "FR-012" for g in r["lanes"]["covered"])

    def test_get_test_debt(self, env):
        r = _parse(_call(open_quality, "get_test_debt", {}))
        assert r["ok"] is True and r["count"] >= 0
        # 草稿不计覆盖 → gap 或 draft 至少出现（DR-LEAK-001 草稿在 draft lane）
        states = {i["state"] for i in r["items"]}
        assert "draft_unreviewed" in states or "gap" in states

    def test_get_plan_status(self, env):
        r = _parse(_call(open_quality, "get_plan_status", {"plan_id": "plan#7"}))
        assert r["ok"] is True
        assert "ST-TEST-001" in r["scenarios"]
        assert r["breakpoints"] == ["ST-TEST-001"]
        assert r["dag_check"]["ok"] == "ok"
        assert r["delta_ref"] == "grid-rule-perf"

    def test_get_plan_status_unknown(self, env):
        r = _parse(_call(open_quality, "get_plan_status", {"plan_id": "plan#999"}))
        assert r["ok"] is False and "铁律 6" in r["hint"]

    def test_read_run_report(self, env):
        r = _parse(_call(open_quality, "read_run_report", {"run_id": "EX-abc123"}))
        assert r.get("ok", True) is not False
        assert r["run_id"] == "EX-abc123"


# ══════════════════════════════════════════════════════════
# T-083：lineage_query + refs_query
# ══════════════════════════════════════════════════════════

class TestLineageQuery:
    def test_trace_forward_fr_to_scenario(self, env):
        """Q1：FR-012 → 覆盖场景（向下游追）。"""
        r = _parse(_call(open_lineage, "trace_forward", {"ref": "FR-012"}))
        assert r["ok"] is True
        ids = {p["id"] for p in r["path"]}
        assert "FR-012" in ids and "ST-TEST-001" in ids
        assert "AC-101" in ids  # contains 边

    def test_trace_backward_scenario_to_fr(self, env):
        """Q2：场景 → FR（向上游追）。"""
        r = _parse(_call(open_lineage, "trace_backward", {"ref": "ST-TEST-001"}))
        assert r["ok"] is True
        ids = {p["id"] for p in r["path"]}
        assert "FR-012" in ids and "ST-TEST-001" in ids

    def test_trace_external_ref_normalize(self, env):
        """ZT-STORY-4821 → external_ref 节点（zt_story: 前缀归一化）。"""
        r = _parse(_call(open_lineage, "trace_backward", {"ref": "ZT-STORY-4821"}))
        assert r["ok"] is True
        assert r["node_id"] == "zt_story:ZT-STORY-4821"

    def test_trace_missing_node_self_heal(self, env):
        r = _parse(_call(open_lineage, "trace_forward", {"ref": "FR-999"}))
        assert r["ok"] is False and "节点不存在" in r["error"]

    def test_query_graph_node_backlink(self, env):
        r = _parse(_call(open_lineage, "query_graph", {"node_id": "FR-012"}))
        assert r["ok"] is True
        assert r["node"]["node_type"] == "fr"
        assert "ST-TEST-001" in r["backlink"]["covered_by"]

    def test_query_graph_l0_zoom(self, env):
        r = _parse(_call(open_lineage, "query_graph", {"zoom": "L0"}))
        assert r["ok"] is True and "l0mods" in r


class TestRefsQuery:
    def test_lookup_external_ref(self, env):
        r = _parse(_call(open_refs_query, "lookup_external_ref", {"ref": "ZT-STORY-4821"}))
        assert r["ok"] is True
        assert r["refs"][0]["linked_type"] == "delta"
        assert r["refs"][0]["linked"] == "grid-rule-perf"
        assert r["lineage_hint"]["in_graph"] is True

    def test_lookup_unknown_ref(self, env):
        r = _parse(_call(open_refs_query, "lookup_external_ref", {"ref": "ZT-STORY-9999"}))
        assert r["ok"] is False and "未登记" in r["error"]


# ══════════════════════════════════════════════════════════
# T-085：dev_context 三入口 + 六分区 pack
# ══════════════════════════════════════════════════════════

PACK_SECTIONS = ("identity", "spec_excerpt", "acceptance", "scenarios",
                 "data_contracts", "lineage_decisions")


def _assert_pack(pack: dict, ref: str, fr_id: str = "FR-012",
                 delta_id: str = "grid-rule-perf"):
    """六分区完整性 + 指纹 + 版本断言。"""
    assert set(pack) == set(PACK_SECTIONS), f"分区缺失: {set(PACK_SECTIONS) - set(pack)}"
    identity = pack["identity"]
    assert identity["pack_type"] == "dev-context-pack"
    assert identity["ref"] == ref
    assert identity["fr_id"] == fr_id
    assert identity["delta_id"] == delta_id
    assert identity["fingerprint"]
    assert len(identity["fingerprint"]) == 12  # sha256-12
    assert identity["frozen_version"]["delta_id"] == delta_id
    assert identity["frozen_version"]["frozen_at"] == "2026-08-11T10:00:00Z"
    # spec_excerpt：SHALL + 基线段 + delta 段
    assert "SHALL" in pack["spec_excerpt"]["excerpt"]
    assert "delta grid-rule-perf 冻结段" in pack["spec_excerpt"]["excerpt"]
    # acceptance
    assert pack["acceptance"]["ac_ids"] == ["AC-101", "AC-102"]
    # scenarios：doc 层 Gherkin
    assert any(s["scenario_id"] == "ST-TEST-001" for s in pack["scenarios"])
    s = next(s for s in pack["scenarios"] if s["scenario_id"] == "ST-TEST-001")
    assert "作废父规则" in s["when"]
    # data_contracts：call 摘要 + verify 断言
    dc = next(d for d in pack["data_contracts"] if d["scenario_id"] == "ST-TEST-001")
    assert dc["calls"][0]["method"] == "DELETE"
    assert dc["verify_asserts"][0]["path"] == "$.data.effected"
    assert dc["depends_on"] == ["ST-PREP-001"]
    # lineage_decisions：上下游 + D-xxx
    ld = pack["lineage_decisions"]
    assert any(d["id"] == "D-001" for d in ld["decisions"])


class TestDevContext:
    def test_by_zt_ref_e2e(self, env):
        """旗舰 e2e：从 ZT-STORY 号拿到六分区 pack（场景 A 接需求）。"""
        r = _parse(_call(open_devctx, "dev_context_by_zt_ref",
                         {"ref_type": "zt_story", "ref_id": "ZT-STORY-4821"}))
        assert r["ok"] is True
        _assert_pack(r["pack"], ref="zt_story:ZT-STORY-4821")

    def test_by_zt_ref_short_id(self, env):
        """ref_id 传纯数字（4821）前缀补全。"""
        r = _parse(_call(open_devctx, "dev_context_by_zt_ref",
                         {"ref_type": "zt_story", "ref_id": "4821"}))
        assert r["ok"] is True
        assert r["pack"]["identity"]["ref"] == "zt_story:ZT-STORY-4821"

    def test_by_zt_ref_unregistered(self, env):
        r = _parse(_call(open_devctx, "dev_context_by_zt_ref",
                         {"ref_type": "zt_story", "ref_id": "ZT-STORY-9999"}))
        assert r["ok"] is False and "未登记" in r["error"]

    def test_by_anchor_fr(self, env):
        """场景 B：FR 锚点入口（改前知震感）。"""
        r = _parse(_call(open_devctx, "dev_context_by_anchor", {"anchor": "FR-012"}))
        assert r["ok"] is True
        _assert_pack(r["pack"], ref="FR-012")

    def test_by_anchor_scenario(self, env):
        """场景 B：场景 ID 入口。"""
        r = _parse(_call(open_devctx, "dev_context_by_anchor", {"anchor": "ST-TEST-001"}))
        assert r["ok"] is True
        assert r["pack"]["identity"]["anchor_node"]["type"] == "scenario"

    def test_by_anchor_missing(self, env):
        r = _parse(_call(open_devctx, "dev_context_by_anchor", {"anchor": "API-NOPE"}))
        assert r["ok"] is False and "未命中" in r["error"]

    def test_by_fr_default_version(self, env):
        """by_fr 默认当前冻结版（基线段 + delta 段）。"""
        r = _parse(_call(open_devctx, "dev_context_by_fr", {"fr_id": "FR-012"}))
        assert r["ok"] is True
        _assert_pack(r["pack"], ref="fr:FR-012")

    def test_by_fr_with_delta(self, env):
        """精准取版：指定 delta。"""
        r = _parse(_call(open_devctx, "dev_context_by_fr",
                         {"fr_id": "FR-012", "delta_id": "grid-rule-perf"}))
        assert r["ok"] is True
        _assert_pack(r["pack"], ref="fr:FR-012")

    def test_by_fr_unfrozen_delta_unreachable(self, env):
        """三红线①：未冻结 delta 物理不可达。"""
        r = _parse(_call(open_devctx, "dev_context_by_fr",
                         {"fr_id": "FR-012", "delta_id": "wip-delta"}))
        assert r["ok"] is False and "未冻结" in r["error"]

    def test_pack_deterministic_fingerprint(self, env):
        """同源两次装配指纹一致（pack 是快照，可校验是否仍是当前版）。"""
        r1 = _parse(_call(open_devctx, "dev_context_by_fr", {"fr_id": "FR-012"}))
        r2 = _parse(_call(open_devctx, "dev_context_by_fr", {"fr_id": "FR-012"}))
        assert r1["pack"]["identity"]["fingerprint"] == r2["pack"]["identity"]["fingerprint"]

    def test_draft_zero_leak(self, env):
        """草稿零泄漏：drafts/ 草稿内容物理不出现在 pack 任何分区。"""
        r = _parse(_call(open_devctx, "dev_context_by_zt_ref",
                         {"ref_type": "zt_story", "ref_id": "ZT-STORY-4821"}))
        blob = json.dumps(r["pack"], ensure_ascii=False)
        assert "DR-LEAK-001" not in blob
        assert "草稿泄漏探针场景" not in blob
        assert "草稿不应出现在 dev-context-pack" not in blob
