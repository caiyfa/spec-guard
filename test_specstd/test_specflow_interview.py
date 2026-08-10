"""specflow 面试模块单元测试（T-020/T-021/T-024）。

覆盖：议题卡 topic.yaml 创建/加载/校验、IV 生命周期状态机、
P0 清零门禁纯函数、提问维度库。
"""

import pytest
from pathlib import Path
from datetime import datetime

from specflow.interview.topic import (
    Topic, SourceRef, BaselineRef, create_topic, load_topic,
    VALID_SOURCE_TYPES,
)
from specflow.interview.iv_lifecycle import (
    transition_status, validate_transition, VALID_STATUSES,
    append_transcript, read_transcript,
)
from specflow.interview.gate import (
    check_p0_clear, gate_aggregate, GateResult, validate_freeze_request,
)
from specflow.interview.question_bank import (
    generate_scan_questions, generate_spq_questions, generate_score_gap_questions,
)


class TestTopic:
    """议题卡单元测试。"""

    def test_create_source_ref(self):
        s = SourceRef(type="prd_section", ref="PRD v3.2 §2.7")
        assert s.validate() is None

    def test_invalid_source_type(self):
        s = SourceRef(type="invalid_type", ref="xxx")
        err = s.validate()
        assert err is not None
        assert "非法 source 类型" in err

    def test_empty_ref(self):
        s = SourceRef(type="spq", ref="")
        err = s.validate()
        assert err is not None

    def test_valid_source_types_all(self):
        for t in VALID_SOURCE_TYPES:
            s = SourceRef(type=t, ref="test-ref")
            assert s.validate() is None, f"type={t} should be valid"

    def test_topic_validate_empty_iv_id(self):
        t = Topic(iv_id="", title="Test",
                  initiator={"emp": "u20001", "role": "product"},
                  opened_at="2026-07-31T10:00:00")
        errors = t.validate()
        assert len(errors) >= 1

    def test_topic_validate_no_source(self):
        t = Topic(iv_id="IV-001", title="Test", source=[],
                  initiator={"emp": "u20001", "role": "product"},
                  opened_at="2026-07-31T10:00:00")
        errors = t.validate()
        assert any("至少有一个 source" in e for e in errors)

    def test_topic_validate_ok(self):
        t = Topic(iv_id="IV-001", title="Test",
                  source=[SourceRef(type="spq", ref="SPQ-001")],
                  initiator={"emp": "u20001", "role": "product"},
                  opened_at="2026-07-31T10:00:00")
        errors = t.validate()
        assert errors == []

    def test_topic_to_yaml_roundtrip(self):
        t = Topic(
            iv_id="IV-007",
            title="九宫格落位规则调整",
            initiator={"emp": "u20001", "role": "product"},
            opened_at="2026-07-31T10:07:00+08:00",
            source=[SourceRef(type="prd_section", ref="PRD v3.2 §2.7")],
            target_delta="grid-rule-perf",
            baseline_refs=[BaselineRef(fr="FR-003", file="specs/spec.md")],
            history_decisions=["D-012"],
            status="interviewing",
        )
        yaml_str = t.to_yaml()
        restored = Topic.from_yaml(yaml_str)
        assert restored.iv_id == t.iv_id
        assert restored.title == t.title
        assert len(restored.source) == 1
        assert restored.source[0].type == "prd_section"
        assert len(restored.baseline_refs) == 1
        assert restored.baseline_refs[0].fr == "FR-003"

    def test_create_topic_with_fs(self, tmp_path):
        specflow_base = tmp_path / ".specflow"
        specflow_base.mkdir()
        topic = create_topic(
            title="Test Topic",
            initiator_emp="u20001",
            initiator_role="product",
            source=[SourceRef(type="spq", ref="SPQ-001")],
            target_delta="test-delta",
            specflow_base=specflow_base,
        )
        assert topic.iv_id == "IV-001"
        assert topic.status == "opened"
        # 文件应已写入
        iv_dir = specflow_base / "interviews" / "IV-001"
        assert iv_dir.is_dir()
        assert (iv_dir / "topic.yaml").is_file()
        assert (iv_dir / "materials").is_dir()

    def test_load_topic(self, tmp_path):
        # 先创建再加载
        specflow_base = tmp_path / ".specflow"
        specflow_base.mkdir()
        original = create_topic(
            title="Load Test",
            initiator_emp="u20001",
            initiator_role="product",
            source=[SourceRef(type="feishu_doc", ref="doc_token")],
            specflow_base=specflow_base,
        )
        loaded = load_topic("IV-001", specflow_base)
        assert loaded is not None
        assert loaded.title == "Load Test"
        assert loaded.iv_id == "IV-001"

    def test_load_topic_not_found(self, tmp_path):
        specflow_base = tmp_path / ".specflow"
        specflow_base.mkdir()
        assert load_topic("IV-999", specflow_base) is None

    def test_create_topic_without_source_rejected(self, tmp_path):
        specflow_base = tmp_path / ".specflow"
        specflow_base.mkdir()
        with pytest.raises(ValueError, match="至少有一个 source"):
            create_topic(
                title="No Source",
                initiator_emp="u20001",
                initiator_role="product",
                source=[],
                specflow_base=specflow_base,
            )


class TestIVLifecycle:
    """IV 生命周期状态机测试。"""

    def test_valid_statuses(self):
        assert "opened" in VALID_STATUSES
        assert "archived" in VALID_STATUSES
        assert "closed" in VALID_STATUSES

    def test_transition_opened_to_interviewing(self):
        assert transition_status("opened", "interviewing") == "interviewing"

    def test_transition_interviewing_to_p0_cleared(self):
        assert transition_status("interviewing", "p0_cleared") == "p0_cleared"

    def test_transition_p0_cleared_to_frozen(self):
        assert transition_status("p0_cleared", "frozen") == "frozen"

    def test_transition_frozen_to_archived(self):
        assert transition_status("frozen", "archived") == "archived"

    def test_transition_invalid(self):
        with pytest.raises(ValueError, match="非法状态流转"):
            transition_status("opened", "frozen")

    def test_transition_closed_to_anything(self):
        with pytest.raises(ValueError, match="终态"):
            transition_status("closed", "opened")

    def test_transition_archived_to_anything(self):
        with pytest.raises(ValueError, match="终态"):
            transition_status("archived", "opened")

    def test_validate_transition_ok(self):
        assert validate_transition("opened", "interviewing") is None

    def test_validate_transition_invalid_current(self):
        err = validate_transition("invalid", "opened")
        assert err is not None
        assert "非法当前状态" in err

    def test_append_and_read_transcript(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        append_transcript(transcript, {"role": "interviewer", "text": "Q1"})
        append_transcript(transcript, {"role": "product", "text": "A1"})
        entries = read_transcript(transcript)
        assert len(entries) == 2
        assert entries[0]["role"] == "interviewer"
        assert entries[1]["role"] == "product"


class TestGate:
    """P0 清零门禁测试。"""

    def test_check_p0_clear_pending(self):
        assert check_p0_clear(0) is True
        assert check_p0_clear(1) is False
        assert check_p0_clear(3) is False

    def test_gate_all_pass(self):
        result = gate_aggregate(p0_pending_count=0, impact_confirmed=True, total_score=75)
        assert result.freeze_allowed is True
        assert result.gaps == []

    def test_gate_p0_pending(self):
        result = gate_aggregate(p0_pending_count=2, impact_confirmed=True, total_score=75)
        assert result.freeze_allowed is False
        assert any("P0" in g for g in result.gaps)

    def test_gate_impact_not_confirmed(self):
        result = gate_aggregate(p0_pending_count=0, impact_confirmed=False, total_score=75)
        assert result.freeze_allowed is False
        assert any("影响面" in g for g in result.gaps)

    def test_gate_score_below_threshold(self):
        result = gate_aggregate(p0_pending_count=0, impact_confirmed=True, total_score=68)
        assert result.freeze_allowed is False
        assert any("五维评分" in g for g in result.gaps)

    def test_gate_all_gaps(self):
        result = gate_aggregate(p0_pending_count=1, impact_confirmed=False, total_score=50)
        assert result.freeze_allowed is False
        assert len(result.gaps) == 3

    def test_gate_default_threshold_custom(self):
        result = gate_aggregate(p0_pending_count=0, impact_confirmed=True,
                                total_score=60, score_threshold=60)
        assert result.freeze_allowed is True

    def test_gate_result_to_dict(self):
        result = gate_aggregate(p0_pending_count=0, impact_confirmed=True, total_score=80)
        d = result.to_dict()
        assert d["freeze_allowed"] is True
        assert d["pending_p0"] == 0

    def test_validate_freeze_request_pass(self):
        result = GateResult(pending_p0=0, impact_confirmed=True,
                            score_pass=True, total_score=80)
        assert validate_freeze_request(result) is None

    def test_validate_freeze_request_fail(self):
        result = GateResult(pending_p0=1, impact_confirmed=True,
                            score_pass=True, total_score=80)
        err = validate_freeze_request(result)
        assert err is not None
        assert "未满足" in err


class TestQuestionBank:
    """提问维度库测试。"""

    def test_generate_scan_questions(self):
        questions = generate_scan_questions("Test Topic", "绩效域", "三域")
        assert len(questions) > 0
        # 应有 P0/P1/P2 混合
        priorities = {q["priority"] for q in questions}
        assert "P0" in priorities
        assert "P1" in priorities
        assert "P2" in priorities
        # 所有问题应有内容
        for q in questions:
            assert q["question"]
            assert 1 <= q["chapter"] <= 11

    def test_generate_spq_questions(self):
        spq_entries = [{"spq_id": "SPQ-005", "title": "落位后名单未刷新"}]
        questions = generate_spq_questions(spq_entries)
        assert len(questions) > 0
        for q in questions:
            assert q["spq_ref"] == "SPQ-005"
            assert q["priority"] == "P1"

    def test_generate_score_gap_questions(self):
        gaps = [{"dimension": "boundary", "score": 55, "gap_desc": "规则切换中落位"}]
        questions = generate_score_gap_questions(gaps)
        assert len(questions) > 0
        for q in questions:
            assert "55" in q["question"]
            assert q["priority"] == "P1"