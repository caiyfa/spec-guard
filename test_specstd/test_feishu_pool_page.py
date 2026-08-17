"""test_feishu_pool_page.py — 材料池总览页后端端点用例（三期 T-929）。

覆盖：材料池清单 / 话题清单（候选+已确认）/ caption 人工补写端点语义。
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
for p in (str(SG_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from services.specflow import feishu_sync_service as svc  # noqa: E402
from specflow.feishu_pool import pool_store  # noqa: E402


def test_list_pool_materials(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(emp, "tokA", "# PRD\n", source_url="u")
    pool_store.save_minutes_snapshot(emp, "obcn1", {"summary": "s"}, source_url="u")
    pool_store.save_chat_snapshot(emp, "oc_abc", "20260814", "[10:00] 张三: 早\n")
    items = svc.list_pool_materials(emp)
    types = {i["type"] for i in items}
    assert types == {"feishu_doc", "feishu_minutes", "chat"}
    doc = next(i for i in items if i["type"] == "feishu_doc")
    assert doc["id"] == "fd:tokA" and len(doc["sha"]) == 12
    assert doc["mtime"] > 0


def test_list_pool_materials_title_summary(tmp_path):
    """材料清单可读性：title/summary 提取（minutes JSON / docs 首行标题 / chats 群名+首行）。"""
    emp = tmp_path / ".specflow" / "u1"
    # 妙记：minutes 数组带 title + artifacts.summary
    pool_store.save_minutes_snapshot(emp, "obcn1", {"minutes": [
        {"minute_token": "obcn1", "title": "需求评审会",
         "artifacts": {"summary": "讨论了导出过滤"}}]}, source_url="u")
    # 文档：首行 markdown 标题 + 首段正文
    pool_store.save_doc_snapshot(emp, "tokA", "# 导出 PRD\n\n按 corpCode 过滤\n", source_url="u")
    # 群聊：watch 配置带群名 → sha8 反查
    svc.save_watch_config(emp, {"chats": [{"chat_id": "oc_abc", "name": "需求讨论群"}],
                                 "docs": [], "minutes_days": 30, "chat_days": 7})
    pool_store.save_chat_snapshot(emp, "oc_abc", "20260814",
                                  "[10:00] 张三: 作废会话后级联删除人员\n")
    items = {i["type"]: i for i in svc.list_pool_materials(emp)}
    fm = items["feishu_minutes"]
    assert fm["title"] == "需求评审会" and "导出过滤" in fm["summary"]
    fd = items["feishu_doc"]
    assert fd["title"] == "导出 PRD" and "corpCode" in fd["summary"]
    chat = items["chat"]
    assert chat["title"] == "需求讨论群" and "级联删除" in chat["summary"]


def test_list_pool_topics(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    cand_dir = emp / "feishu_pool"
    cand_dir.mkdir(parents=True)
    (cand_dir / "_candidate_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:aaa-0814-01\n    title: 候选话题\n    summary: s\n"
        "    chat_sha8: aaa\n    window: ['2026-08-14T10:00', '2026-08-14T11:00']\n"
        "    message_count: 3\n    participants_count: 2\n"
        "    source: chats/aaa/20260814.md\n", encoding="utf-8")
    ws = tmp_path / "ws"
    from specflow.feishu_pool import facts
    facts.upsert_topic(ws, {"id": "tp:aaa-0813-01", "title": "已确认话题",
                            "summary": "s", "chat_sha8": "aaa",
                            "window": ["2026-08-13T10:00", "2026-08-13T11:00"],
                            "message_count": 5, "participants_count": 2,
                            "source": "chats/aaa/20260813.md"})
    out = svc.list_pool_topics(emp, ws)
    assert [t["id"] for t in out["candidates"]] == ["tp:aaa-0814-01"]
    assert [t["id"] for t in out["confirmed"]] == ["tp:aaa-0813-01"]


def test_update_caption_endpoint_semantics(tmp_path):
    """caption 人工补写服务函数（路由层薄包装，核心在 captions.update_caption）。"""
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        emp, "tokA", "如图 [图片#1]\n",
        imgmap={"图片#1": {"media_key": "k", "caption": "",
                           "caption_by": "none", "status": "pending"}})
    out = svc.update_image_caption(emp, "fd-tokA", "图片#1", "人工描述")
    assert out["status"] == "done"
    img = json.loads((emp / "feishu_pool" / "docs" / "fd-tokA.imgmap.json")
                     .read_text(encoding="utf-8"))
    assert img["图片#1"]["caption"] == "人工描述"
    assert img["图片#1"]["caption_by"] == "manual"


# ══════════════════════════════════════════════════════════
# 选择器数据源（同步设置弹层；mock _run_lark）
# ══════════════════════════════════════════════════════════

def test_list_my_chats(tmp_path):
    """群聊选择器数据源：chat_id/name/chat_mode 解析；p2p 附带 peer_open_id。"""
    def fake(args, timeout=90):
        assert args[:2] == ["im", "+chat-list"]
        return {"ok": True, "data": {"items": [
            {"chat_id": "oc_a", "name": "需求群", "chat_mode": "group"},
            {"chat_id": "oc_p", "name": "", "chat_mode": "p2p",
             "p2p_target_id": "ou_x"}]}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.list_my_chats()
    assert out["errors"] == []
    assert out["items"][0] == {"chat_id": "oc_a", "name": "需求群",
                               "chat_mode": "group", "peer_open_id": ""}
    assert out["items"][1]["chat_mode"] == "p2p"
    assert out["items"][1]["peer_open_id"] == "ou_x"


def test_search_users_empty_query_shortcircuit():
    """query 为空 → 空列表且不调 CLI（不扫全量）。"""
    calls = []
    with patch.object(svc, "_run_lark",
                      side_effect=lambda a, timeout=90: calls.append(a)):
        out = svc.search_users("  ")
    assert out == {"items": [], "errors": []} and calls == []


def test_search_users_parse(tmp_path):
    def fake(args, timeout=90):
        assert args[:2] == ["contact", "+search-user"]
        return {"ok": True, "data": {"users": [
            {"open_id": "ou_a", "name": "张三",
             "enterprise_email": "zs@x.com", "department": "研发"}]}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.search_users("张三")
    assert out["items"][0]["open_id"] == "ou_a"
    assert out["items"][0]["email"] == "zs@x.com"


def test_search_user_docs_owner_filter_and_error(tmp_path):
    """应用侧 owner 过滤 + CLI 失败 errors 通道。"""
    def fake(args, timeout=90):
        assert args[:2] == ["docs", "+search"]
        return {"ok": True, "data": {"results": [
            {"title_highlighted": "张三<em>方案</em>",
             "result_meta": {"owner_id": "ou_a", "token": "tokA",
                             "url": "uA", "doc_types": "DOCX",
                             "owner_name": "张三"}},
            {"title_highlighted": "他人文档",
             "result_meta": {"owner_id": "ou_b", "token": "tokB"}}]}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.search_user_docs("ou_a", "方案")
    assert [i["token"] for i in out["items"]] == ["tokA"]
    assert out["items"][0]["title"] == "张三方案"   # em 高亮标签剥离
    with patch.object(svc, "_run_lark",
                      side_effect=ValueError("认证未就绪")):
        out2 = svc.search_user_docs("ou_a", "")
    assert out2["items"] == [] and out2["errors"]
