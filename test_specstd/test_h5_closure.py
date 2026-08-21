"""test_h5_closure — H-5 闭环衔接测试。

覆盖验收标准：
1. 漏洞 closed 状态机（close_vulnerability + close_vulnerabilities_by_location）
2. 漏洞统计摘要（get_vulnerability_summary）
3. pull 时间戳（specstd pull() 已记录，workspace /pull 端点返回）
"""

import json
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from feedback.ledger import FeedbackLedger


# ══════════════════════════════════════════════════════════
# H-5: close_vulnerability 测试
# ══════════════════════════════════════════════════════════

class TestCloseVulnerability:
    def test_close_from_pending(self, tmp_path):
        """pending → closed。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        closed = ledger.close_vulnerability(entry["spq_id"])
        assert closed["status"] == "closed"

    def test_close_from_in_progress(self, tmp_path):
        """in_progress → closed。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        ledger.transition(entry["spq_id"], "in_progress")
        closed = ledger.close_vulnerability(entry["spq_id"])
        assert closed["status"] == "closed"

    def test_close_with_note(self, tmp_path):
        """关闭时附带备注。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        closed = ledger.close_vulnerability(entry["spq_id"], "重新审计确认已修正")
        assert closed["status"] == "closed"
        # 验证备注事件
        close_events = [e for e in closed.get("events", []) if e.get("type") == "closed"]
        assert len(close_events) == 1
        assert close_events[0]["note"] == "重新审计确认已修正"

    def test_close_already_closed(self, tmp_path):
        """关闭已关闭的漏洞不报错（transition 幂等）。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        ledger.close_vulnerability(entry["spq_id"])
        # 再次关闭（closed → closed 是幂等的，transition 同状态直接返回）
        result = ledger.close_vulnerability(entry["spq_id"])
        assert result["status"] == "closed"

    def test_close_nonexistent(self, tmp_path):
        """关闭不存在的漏洞抛 KeyError。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        with pytest.raises(KeyError):
            ledger.close_vulnerability("SPQ-999")


# ══════════════════════════════════════════════════════════
# H-5: close_vulnerabilities_by_location 测试
# ══════════════════════════════════════════════════════════

class TestCloseByLocation:
    def test_close_by_location(self, tmp_path):
        """按位置批量关闭漏洞。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="问题1",
        )
        ledger.create_vulnerability(
            vtype="missing_info", severity="blocker",
            location="FR-001", summary="问题2",
        )
        ledger.create_vulnerability(
            vtype="logic_defect", severity="minor",
            location="FR-002", summary="问题3",
        )
        # 关闭 FR-001 的漏洞
        closed = ledger.close_vulnerabilities_by_location("FR-001")
        assert len(closed) == 2
        # FR-002 仍然 pending
        remaining = ledger.list_vulnerabilities(status="pending")
        assert len(remaining) == 1
        assert remaining[0]["location"] == "FR-002"

    def test_close_by_location_already_closed(self, tmp_path):
        """已关闭的漏洞不被重复关闭。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        e1 = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="问题1",
        )
        ledger.close_vulnerability(e1["spq_id"])
        # 再次按位置关闭
        closed = ledger.close_vulnerabilities_by_location("FR-001")
        assert len(closed) == 0  # 已经关闭，不再关闭

    def test_close_by_location_no_match(self, tmp_path):
        """无匹配位置返回空列表。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        closed = ledger.close_vulnerabilities_by_location("FR-999")
        assert len(closed) == 0

    def test_close_by_file_path(self, tmp_path):
        """按文件路径关闭漏洞。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create_vulnerability(
            vtype="spec_impl_mismatch", severity="major",
            location="specs/module1/feature1/spec.md", summary="test",
        )
        closed = ledger.close_vulnerabilities_by_location("specs/module1/feature1/spec.md")
        assert len(closed) == 1


# ══════════════════════════════════════════════════════════
# H-5: get_vulnerability_summary 测试
# ══════════════════════════════════════════════════════════

class TestVulnerabilitySummary:
    def test_empty_summary(self, tmp_path):
        """空台账摘要。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        summary = ledger.get_vulnerability_summary()
        assert summary == {"total": 0, "pending": 0, "in_progress": 0, "closed": 0}

    def test_summary_with_vulnerabilities(self, tmp_path):
        """有漏洞的摘要。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        e1 = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test1",
        )
        e2 = ledger.create_vulnerability(
            vtype="missing_info", severity="blocker",
            location="FR-002", summary="test2",
        )
        ledger.transition(e1["spq_id"], "in_progress")
        ledger.close_vulnerability(e2["spq_id"])
        summary = ledger.get_vulnerability_summary()
        assert summary["total"] == 2
        assert summary["pending"] == 0
        assert summary["in_progress"] == 1
        assert summary["closed"] == 1

    def test_summary_excludes_non_vulnerabilities(self, tmp_path):
        """摘要只统计漏洞条目（不含普通条目）。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create("普通条目", source="loop_b")
        ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        summary = ledger.get_vulnerability_summary()
        assert summary["total"] == 1
        assert summary["pending"] == 1


# ══════════════════════════════════════════════════════════
# H-5: 闭环流程集成测试
# ══════════════════════════════════════════════════════════

class TestClosureFlow:
    def test_full_closure_flow(self, tmp_path):
        """完整闭环流程：创建漏洞 → 关闭 → 摘要归零。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")

        # 1. audit 发现 3 条漏洞
        for i in range(3):
            ledger.create_vulnerability(
                vtype="logic_defect", severity="major",
                location=f"FR-00{i+1}", summary=f"漏洞{i+1}",
            )
        assert ledger.get_vulnerability_summary()["pending"] == 3

        # 2. 研发修正 FR-001 → Agent 重新审计 → 关闭 FR-001 漏洞
        closed = ledger.close_vulnerabilities_by_location("FR-001")
        assert len(closed) == 1
        assert ledger.get_vulnerability_summary()["pending"] == 2
        assert ledger.get_vulnerability_summary()["closed"] == 1

        # 3. 研发修正 FR-002, FR-003 → 批量关闭
        ledger.close_vulnerabilities_by_location("FR-002")
        ledger.close_vulnerabilities_by_location("FR-003")

        # 4. 漏洞清零
        summary = ledger.get_vulnerability_summary()
        assert summary["pending"] == 0
        assert summary["closed"] == 3
        assert ledger.count_vulnerabilities("pending") == 0
