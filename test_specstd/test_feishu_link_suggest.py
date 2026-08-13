"""test_feishu_link_suggest.py — LLM 建边建议与防幻觉后处理单测（飞书知识图谱一期 T7）。

覆盖（设计 §6.2 三重防线）：
- 幻觉 fr_id（不在 anchors 扫描结果）直接丢弃，不进复核队列
- evidence 非材料原文子串 → valid=False（展示但不可确认）
- 已 rejected 的 (src,dst) 不再重复建议
"""

from unittest.mock import MagicMock

from specflow.feishu_pool import facts, link_suggest as ls


def _anchors():
    return {
        "FR-012": MagicMock(title="作废级联删除", module="inventory",
                            feature="grid-placement", ac_ids=["AC-001"]),
        "FR-009": MagicMock(title="名单过滤", module="inventory",
                            feature="person-list", ac_ids=[]),
    }


def _llm_returning(payload: str):
    llm = MagicMock()
    llm.chat.return_value = {"content": payload}
    return llm


def test_hallucinated_fr_dropped():
    llm = _llm_returning(
        '{"links": ['
        '{"fr_id": "FR-012", "confidence": 0.9, "evidence": "级联删除人员"},'
        '{"fr_id": "FR-999", "confidence": 0.8, "evidence": "级联删除"}]}')
    material_text = "作废会话后级联删除人员/快照/结果表"
    out = ls.suggest_links_for_material("fd:tokA", material_text, _anchors(), llm)
    assert [l["dst"] for l in out] == ["FR-012"]       # FR-999 被丢弃
    assert out[0]["src"] == "fd:tokA"
    assert out[0]["valid"] is True


def test_evidence_not_substring_marked_invalid():
    llm = _llm_returning(
        '{"links": [{"fr_id": "FR-012",'
        ' "confidence": 0.7, "evidence": "原文里根本没有这句话"}]}')
    out = ls.suggest_links_for_material("fd:tokA", "作废会话后级联删除人员",
                                        _anchors(), llm)
    assert out[0]["valid"] is False    # evidence 非原文子串 → invalid（展示但不可确认）


def test_rejected_pairs_excluded(tmp_path):
    ws = tmp_path / "ws"
    facts.append_link(ws, src="fd:tokA", dst="FR-012", edge="mentions",
                      confidence=0.5, evidence="x", confirmed_by="u1",
                      status="rejected")
    llm = _llm_returning(
        '{"links": ['
        '{"fr_id": "FR-012", "confidence": 0.9, "evidence": "级联删除人员"},'
        '{"fr_id": "FR-009", "confidence": 0.6, "evidence": "级联删除"}]}')
    out = ls.suggest_links_for_material(
        "fd:tokA", "作废会话后级联删除人员", _anchors(), llm, workspace_root=ws)
    assert [l["dst"] for l in out] == ["FR-009"]       # 已拒绝的 FR-012 不再建议
