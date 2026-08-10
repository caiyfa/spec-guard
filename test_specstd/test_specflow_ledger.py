"""specflow 决策台账单元测试（T-023/T-024）。

覆盖：决策创建/落锤/增补、门禁聚合、评分操作、权限隔离。
"""

import pytest
import sqlite3

from specflow.interview.decision_ledger import (
    init_tables, create_decision, resolve_decision, amend_decision,
    get_decision, list_decisions, count_pending_p0,
    add_gate_evidence, get_impact_confirmed,
    add_score, confirm_score, list_scores, calculate_total_score,
    export_ledger,
)
from specflow.interview.gate import gate_aggregate, check_p0_clear


@pytest.fixture
def conn():
    """内存 SQLite 测试用连接。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_tables(c)
    return c


class TestDecisionLedger:
    """决策台账测试。"""

    def test_create_decision(self, conn):
        dec = create_decision(conn, "tdm", "IV-001", "P0",
                              "调整范围：仅绩效域？")
        assert dec["id"].startswith("D-")
        assert dec["priority"] == "P0"
        assert dec["status"] == "pending"
        assert dec["content_sha"]  # 指纹应存在

    def test_create_decision_with_links(self, conn):
        dec = create_decision(conn, "tdm", "IV-001", "P0", "Q1",
                              links=[{"type": "fr_anchor", "ref": "FR-006"}])
        assert dec["id"]
        # 不直接测试 links 表，but 不抛异常

    def test_resolve_decision(self, conn):
        dec = create_decision(conn, "tdm", "IV-001", "P0", "Q1")
        resolved = resolve_decision(conn, dec["id"], "仅绩效域", "pm.zhang")
        assert resolved["status"] == "resolved"
        assert resolved["resolution"] == "仅绩效域"
        assert resolved["resolved_by"] == "pm.zhang"

    def test_resolve_non_pending_rejected(self, conn):
        dec = create_decision(conn, "tdm", "IV-001", "P0", "Q1")
        resolve_decision(conn, dec["id"], "RES", "pm.zhang")
        with pytest.raises(PermissionError):
            resolve_decision(conn, dec["id"], "Again", "pm.zhang")

    def test_amend_decision(self, conn):
        dec = create_decision(conn, "tdm", "IV-001", "P0", "原问题")
        resolve_decision(conn, dec["id"], "原决策", "pm.zhang")
        old, new = amend_decision(
            conn, dec["id"], "P0", "新问题", "新决策",
            "需求变更", "pm.zhang", "tdm", "IV-001")
        assert old["status"] == "superseded"
        assert old["superseded_by"] == new["id"]
        assert new["status"] == "resolved"
        assert new["resolution"] == "新决策"

    def test_amend_non_resolved_rejected(self, conn):
        dec = create_decision(conn, "tdm", "IV-001", "P0", "问题")
        with pytest.raises(ValueError, match="仅 resolved"):
            amend_decision(conn, dec["id"], "P0", "新", "新",
                           "test", "user", "tdm", "IV-001")

    def test_list_decisions(self, conn):
        create_decision(conn, "tdm", "IV-001", "P0", "Q1")
        create_decision(conn, "tdm", "IV-001", "P1", "Q2")
        create_decision(conn, "tdm", "IV-002", "P0", "Q3")
        assert len(list_decisions(conn)) == 3
        assert len(list_decisions(conn, interview_id="IV-001")) == 2
        assert len(list_decisions(conn, priority="P0")) == 2
        assert len(list_decisions(conn, status="pending")) == 3

    def test_count_pending_p0(self, conn):
        create_decision(conn, "tdm", "IV-001", "P0", "Q1")
        create_decision(conn, "tdm", "IV-001", "P0", "Q2")
        create_decision(conn, "tdm", "IV-001", "P1", "Q3")
        assert count_pending_p0(conn, "IV-001") == 2
        # resolve 一个 P0
        decs = list_decisions(conn, interview_id="IV-001", priority="P0")
        resolve_decision(conn, decs[0]["id"], "RES", "pm.zhang")
        assert count_pending_p0(conn, "IV-001") == 1

    def test_gate_evidence(self, conn):
        r = add_gate_evidence(conn, "tdm", "IV-001", "impact_confirm",
                              "pass", actor="pm.zhang")
        assert r["gate_item"] == "impact_confirm"
        assert get_impact_confirmed(conn, "IV-001") is True

    def test_gate_evidence_not_confirmed(self, conn):
        assert get_impact_confirmed(conn, "IV-001") is False

    def test_add_and_list_scores(self, conn):
        r = add_score(conn, "tdm", "IV-001", "logic", 78, "machine",
                      "11 章齐全")
        assert r["status"] == "suggested"
        scores = list_scores(conn, "IV-001")
        assert len(scores) == 1

    def test_confirm_score(self, conn):
        r = add_score(conn, "tdm", "IV-001", "logic", 78, "machine")
        confirmed = confirm_score(conn, r["id"], "confirm", "qa.zhang")
        assert confirmed["status"] == "confirmed"
        assert confirmed["confirmed_by"] == "qa.zhang"

    def test_reject_score(self, conn):
        r = add_score(conn, "tdm", "IV-001", "clarity", 62, "llm_suggested")
        rejected = confirm_score(conn, r["id"], "reject", "qa.zhang")
        assert rejected["status"] == "rejected"

    def test_calculate_total_score(self, conn):
        add_score(conn, "tdm", "IV-001", "logic", 78, "machine")
        add_score(conn, "tdm", "IV-001", "coverage", 85, "machine")
        # 尚未 confirmed，总分应为 0
        assert calculate_total_score(conn, "IV-001") == 0.0

    def test_calculate_total_score_confirmed(self, conn):
        r1 = add_score(conn, "tdm", "IV-001", "logic", 78, "machine")
        r2 = add_score(conn, "tdm", "IV-001", "coverage", 85, "machine")
        confirm_score(conn, r1["id"], "confirm", "qa")
        confirm_score(conn, r2["id"], "confirm", "qa")
        total = calculate_total_score(conn, "IV-001")
        # (78 + 85) / 5 = 32.6（等权均分）
        assert total == pytest.approx(32.6, rel=0.1)

    def test_export_ledger(self, conn):
        create_decision(conn, "tdm", "IV-001", "P0", "Q1")
        create_decision(conn, "tdm", "IV-001", "P1", "Q2")
        ledger = export_ledger(conn, "IV-001")
        assert "decisions" in ledger
        assert "p0_gate" in ledger
        assert ledger["p0_gate"]["pending_p0"] == 1

    def test_get_decision_not_found(self, conn):
        assert get_decision(conn, "D-999") is None


class TestDecisionService:
    """决策服务集成测试（gate 纯函数+决策联动）。"""

    def test_gate_with_real_decisions(self, conn):
        create_decision(conn, "tdm", "IV-001", "P0", "Q1 pending")
        create_decision(conn, "tdm", "IV-001", "P0", "Q2 pending")
        p0 = count_pending_p0(conn, "IV-001")
        assert p0 == 2
        result = gate_aggregate(p0_pending_count=p0,
                                impact_confirmed=False, total_score=68)
        assert result.freeze_allowed is False
        assert len(result.gaps) >= 2  # P0 + 影响面 + 评分（影响面未确认）

    def test_full_flow(self, conn):
        """完整流程：创建 → resolve → gate 状态变化。"""
        d1 = create_decision(conn, "tdm", "IV-001", "P0", "Q1")
        resolve_decision(conn, d1["id"], "RES1", "pm")
        assert count_pending_p0(conn, "IV-001") == 0
        # gate 应通过
        result = gate_aggregate(p0_pending_count=0,
                                impact_confirmed=True, total_score=75)
        assert result.freeze_allowed is True