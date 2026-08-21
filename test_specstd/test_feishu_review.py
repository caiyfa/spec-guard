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


# ══════════════════════════════════════════════════════════
# T-927：确认可选入包（suggest_ivs）
# ══════════════════════════════════════════════════════════

def test_confirm_returns_suggest_ivs(tmp_path):
    from unittest.mock import patch
    ws, emp = _prepare(tmp_path)
    with patch.object(rev, "_find_active_ivs_for_fr", return_value=[
            {"iv_id": "IV-001", "title": "导出功能面试"}]):
        rev.enqueue_suggestions(emp, "u1", [{"src": "fd:tokA", "dst": "FR-012",
            "confidence": 0.9, "evidence": "FR-012 提及", "valid": True,
            "suggested_by": "u1"}])
        out = rev.confirm_suggestions(emp, ws, "u1", [("fd:tokA", "FR-012")])
    assert out["suggest_ivs"] == [{"iv_id": "IV-001", "title": "导出功能面试"}]


def test_confirm_no_iv_returns_empty(tmp_path):
    from unittest.mock import patch
    ws, emp = _prepare(tmp_path)
    with patch.object(rev, "_find_active_ivs_for_fr", return_value=[]):
        rev.enqueue_suggestions(emp, "u1", [{"src": "fd:tokA", "dst": "FR-012",
            "confidence": 0.9, "evidence": "FR-012 提及", "valid": True,
            "suggested_by": "u1"}])
        out = rev.confirm_suggestions(emp, ws, "u1", [("fd:tokA", "FR-012")])
    assert out["suggest_ivs"] == []


# ══════════════════════════════════════════════════════════
# T-991：复核队列共享可选（scope=shared → 共享材料区队列）
# ══════════════════════════════════════════════════════════

def test_shared_scope_queue_visible_across_users(tmp_path):
    """共享队列：u1 入队共享 base，u2 经 scope=shared 可见（服务层 base 参数化）。"""
    ws, emp1 = _prepare(tmp_path)
    shared = tmp_path / ".specflow"          # 共享材料区根（specflow_dir("")）
    rev.enqueue_suggestions(shared, "u1", [
        {"src": "fd:tokA", "dst": "FR-012", "confidence": 0.9,
         "evidence": "FR-012 提及", "valid": True, "suggested_by": "u1"}])
    emp2 = tmp_path / ".specflow" / "u2"
    # 默认 mine：u2 私有队列为空（隔离不变）
    assert rev.list_queue(emp2) == []
    # shared：u2 可见共享队列
    items = rev.list_queue(shared)
    assert len(items) == 1 and items[0]["src"] == "fd:tokA"


def test_router_review_queue_scope_routing(tmp_path):
    """路由层 scope 路由：mine → _sf_base；shared → _material_base。"""
    from types import SimpleNamespace
    from unittest.mock import patch
    from routers import feishu_pool as rp

    ws, emp1 = _prepare(tmp_path)
    shared = tmp_path / ".specflow"
    rev.enqueue_suggestions(shared, "u1", [
        {"src": "fd:tokA", "dst": "FR-012", "confidence": 0.9,
         "evidence": "FR-012 提及", "valid": True, "suggested_by": "u1"}])
    user = SimpleNamespace(emp_no="90000002", name="王二")
    emp2 = tmp_path / ".specflow" / "u2"
    with patch.object(rp, "_sf_base", return_value=emp2), \
         patch.object(rp, "_material_base", return_value=shared):
        out_mine = rp.review_queue(scope="mine", user=user, workspace="tdm")
        assert out_mine["items"] == [] and out_mine["scope"] == "mine"
        out_shared = rp.review_queue(scope="shared", user=user, workspace="tdm")
        assert len(out_shared["items"]) == 1 and out_shared["scope"] == "shared"
