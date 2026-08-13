"""test_feishu_review.py — 关联复核服务与提升闸门单测（飞书知识图谱一期 T5）。

覆盖：
- 确认 → 共享区 materials 副本 + material_links.yaml（confirmed）+ 队列状态
- 拒绝 → 共享区 material_links.yaml（status=rejected，工作区级防重复建议）
- 复核队列按 emp 隔离（私有区属主才能复核自己的材料）
- invalid（evidence 校验失败）条目不可确认
"""

import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
for p in (str(SG_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from services.specflow import feishu_review_service as rev  # noqa: E402
from specflow.feishu_pool import facts, pool_store  # noqa: E402


def _prepare(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".specguard").mkdir(parents=True)
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(emp, "tokA", "# 导出 PRD\n含 FR-012 提及\n",
                                 source_url="u")
    return ws, emp


def test_confirm_promotes_to_shared(tmp_path):
    ws, emp = _prepare(tmp_path)
    sugg = {"src": "fd:tokA", "dst": "FR-012", "confidence": 0.9,
            "evidence": "FR-012 提及", "valid": True, "suggested_by": "u1"}
    rev.enqueue_suggestions(emp, "u1", [sugg])
    out = rev.confirm_suggestions(emp, ws, "u1", [("fd:tokA", "FR-012")])
    assert out["confirmed"] == 1
    # 提升：共享区 materials 副本 + material_links.yaml
    assert (ws / ".specguard" / "feishu" / "materials" / "fd-tokA.md").is_file()
    links = facts.load_links(ws)
    assert links[0]["status"] == "confirmed" and links[0]["confirmed_by"] == "u1"
    # 队列状态置 confirmed
    item = rev.list_queue(emp)[0]
    assert item["status"] == "confirmed"


def test_reject_writes_shared_rejected_trace(tmp_path):
    ws, emp = _prepare(tmp_path)
    sugg = {"src": "fd:tokA", "dst": "FR-009", "confidence": 0.5,
            "evidence": "x", "valid": True, "suggested_by": "u1"}
    rev.enqueue_suggestions(emp, "u1", [sugg])
    out = rev.reject_suggestions(emp, ws, "u1", [("fd:tokA", "FR-009")])
    assert out["rejected"] == 1
    assert facts.is_rejected(ws, "fd:tokA", "FR-009") is True
    # rejected 不产生共享区材料副本（无提升）
    assert not (ws / ".specguard" / "feishu" / "materials").exists() or \
        not list((ws / ".specguard" / "feishu" / "materials").iterdir())


def test_cannot_review_others_material(tmp_path):
    ws, emp1 = _prepare(tmp_path)
    rev.enqueue_suggestions(emp1, "u1", [
        {"src": "fd:tokA", "dst": "FR-012", "confidence": 0.9,
         "evidence": "FR-012 提及", "valid": True, "suggested_by": "u1"}])
    emp2 = tmp_path / ".specflow" / "u2"
    assert rev.list_queue(emp2) == []   # u2 看不到 u1 的复核队列


def test_invalid_suggestion_not_confirmable(tmp_path):
    ws, emp = _prepare(tmp_path)
    sugg = {"src": "fd:tokA", "dst": "FR-012", "confidence": 0.7,
            "evidence": "伪造依据", "valid": False, "suggested_by": "u1"}
    rev.enqueue_suggestions(emp, "u1", [sugg])
    out = rev.confirm_suggestions(emp, ws, "u1", [("fd:tokA", "FR-012")])
    assert out["confirmed"] == 0 and out["skipped"] == 1
    assert facts.load_links(ws) == []   # invalid 不落事实源


def test_topic_promotion_writes_topics_yaml(tmp_path):
    ws, emp = _prepare(tmp_path)
    # 候选话题（私有区）
    import yaml
    cand = emp / "feishu_pool" / "_candidate_topics.yaml"
    cand.parent.mkdir(parents=True, exist_ok=True)
    cand.write_text(yaml.safe_dump({"version": 1, "topics": [{
        "id": "tp:3f9a2c-20260807-01", "title": "导出权限", "summary": "按 corpCode",
        "chat_sha8": "3f9a2c", "window": ["2026-08-07T14:00", "2026-08-07T14:01"],
        "message_count": 2, "participants_count": 2,
        "source": "chats/3f9a2c/20260807.md"}]},
        allow_unicode=True), encoding="utf-8")
    rev.enqueue_suggestions(emp, "u1", [
        {"src": "tp:3f9a2c-20260807-01", "dst": "FR-012", "confidence": 0.8,
         "evidence": "按 corpCode", "valid": True, "suggested_by": "u1"}])
    out = rev.confirm_suggestions(emp, ws, "u1", [("tp:3f9a2c-20260807-01", "FR-012")])
    assert out["confirmed"] == 1
    topics = facts.load_topics(ws)
    assert topics[0]["id"] == "tp:3f9a2c-20260807-01"
    assert topics[0]["title"] == "导出权限"
