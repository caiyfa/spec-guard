"""test_feishu_pool.py — 飞书材料池落盘原语单测（飞书知识图谱一期 T1/T2/T8）。

覆盖：
- 私有区路径函数（docs/minutes/chats 三通道）
- 文档/妙记/群聊快照落盘 + sha 指纹 + imgmap 分离存储
- 共享区事实源读写（topics.yaml / material_links.yaml，确定性排序）
- 图片替身文本拼装（captions）
"""

import json

from specflow.feishu_pool import paths, pool_store


def test_pool_paths(tmp_path):
    base = tmp_path / ".specflow" / "caiyunfei"
    p = paths.pool_dirs(base)
    assert p["docs"] == base / "feishu_pool" / "docs"
    assert p["chats"] == base / "feishu_pool" / "chats"
    assert p["minutes"] == base / "feishu_pool" / "minutes"


def test_save_doc_snapshot_with_imgmap(tmp_path):
    base = tmp_path / ".specflow" / "caiyunfei"
    rec = pool_store.save_doc_snapshot(
        base, doc_token="FBxodQkaJoUicrxdk67cUkbhnwc",
        markdown="# PRD\n如图 [图片#1] 所示\n",
        imgmap={"图片#1": {"media_key": "img_v3_x", "caption": "",
                           "caption_by": "none", "status": "pending"}},
        source_url="https://fehorizon.feishu.cn/docx/FBxod...")
    assert rec["node_id"] == "fd:FBxodQkaJoUicrxdk67cUkbhnwc"
    assert len(rec["sha"]) == 12
    md = (base / "feishu_pool" / "docs" / "fd-FBxodQkaJoUicrxdk67cUkbhnwc.md")
    assert md.is_file() and "[图片#1]" in md.read_text(encoding="utf-8")
    im = (base / "feishu_pool" / "docs" / "fd-FBxodQkaJoUicrxdk67cUkbhnwc.imgmap.json")
    assert json.loads(im.read_text(encoding="utf-8"))["图片#1"]["status"] == "pending"


def test_save_snapshot_meta_sidecar(tmp_path):
    """T-940：meta 参数落 {stem}.meta.json sidecar（owner/source_url 归属与飞书直链）。"""
    base = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        base, "tokA", "# t\n", source_url="https://x.feishu.cn/docx/tokA",
        meta={"owner_open_id": "ou_a", "owner_name": "张三", "title": "PRD",
              "source_url": "https://x.feishu.cn/docx/tokA"})
    meta = json.loads((base / "feishu_pool" / "docs" / "fd-tokA.meta.json")
                      .read_text(encoding="utf-8"))
    assert meta["owner_open_id"] == "ou_a"
    assert meta["owner_name"] == "张三"
    assert meta["source_url"] == "https://x.feishu.cn/docx/tokA"
    pool_store.save_minutes_snapshot(
        base, "obcn1", {"minutes": []}, source_url="u",
        meta={"owner_open_id": "ou_b", "source_url": "https://x.feishu.cn/minutes/obcn1"})
    meta2 = json.loads((base / "feishu_pool" / "minutes" / "fm-obcn1.meta.json")
                       .read_text(encoding="utf-8"))
    assert meta2["owner_open_id"] == "ou_b"


def test_save_chat_snapshot_by_day(tmp_path):
    base = tmp_path / ".specflow" / "caiyunfei"
    rec = pool_store.save_chat_snapshot(
        base, chat_id="oc_26dc885ce8f4b0133ee5fdcc655adda3",
        day="20260807", markdown="[14:00] 张三: 讨论导出权限\n")
    assert rec["chat_sha8"] == pool_store.chat_sha8("oc_26dc885ce8f4b0133ee5fdcc655adda3")
    assert len(rec["chat_sha8"]) == 8
    f = base / "feishu_pool" / "chats" / rec["chat_sha8"] / "20260807.md"
    assert f.is_file()


# ══════════════════════════════════════════════════════════
# T2：共享区事实源读写器（topics.yaml / material_links.yaml）
# ══════════════════════════════════════════════════════════

class TestFacts:
    def test_links_roundtrip_sorted(self, tmp_path):
        ws = tmp_path / "ws"
        from specflow.feishu_pool import facts
        facts.append_link(ws, src="tp:b-0807-01", dst="FR-002", edge="mentions",
                          confidence=0.7, evidence="原文b", confirmed_by="u1")
        facts.append_link(ws, src="fd:tokA", dst="FR-001", edge="mentions",
                          confidence=0.9, evidence="原文a", confirmed_by="u1")
        links = facts.load_links(ws)
        # 确定性：按 (src, dst) 排序落盘与读取
        assert [lk["src"] for lk in links] == ["fd:tokA", "tp:b-0807-01"]
        assert links[0]["status"] == "confirmed"
        assert links[0]["confirmed_at"]  # 自动填时间

    def test_rejected_pair_filtered(self, tmp_path):
        ws = tmp_path / "ws"
        from specflow.feishu_pool import facts
        facts.append_link(ws, src="fd:tokA", dst="FR-001", edge="mentions",
                          confidence=0.5, evidence="x", confirmed_by="u1",
                          status="rejected")
        assert facts.is_rejected(ws, "fd:tokA", "FR-001") is True
        assert facts.is_rejected(ws, "fd:tokA", "FR-002") is False

    def test_topics_upsert_keeps_id(self, tmp_path):
        ws = tmp_path / "ws"
        from specflow.feishu_pool import facts
        t = {"id": "tp:3f9a2c-0807-01", "title": "导出权限", "summary": "v1",
             "chat_sha8": "3f9a2c", "window": ["2026-08-07T14:00", "2026-08-07T15:30"],
             "message_count": 23, "participants_count": 4,
             "source": "chats/3f9a2c/20260807.md"}
        facts.upsert_topic(ws, t)
        t2 = dict(t, summary="v2 修订", message_count=30)
        facts.upsert_topic(ws, t2)   # 同 id 覆盖而非追加
        topics = facts.load_topics(ws)
        assert len(topics) == 1 and topics[0]["summary"] == "v2 修订"


# ══════════════════════════════════════════════════════════
# T8：图片替身文本拼装（captions）
# ══════════════════════════════════════════════════════════

class TestCaptions:
    def test_compose_text_with_captions(self):
        from specflow.feishu_pool import captions
        md = "如图 [图片#1] 所示\n"
        imgmap = {"图片#1": {"media_key": "k", "caption": "架构图：三层",
                             "caption_by": "manual", "status": "done"}}
        out = captions.compose_text(md, imgmap)
        assert "[图片#1: 架构图：三层]" in out

    def test_pending_caption_keeps_placeholder(self):
        from specflow.feishu_pool import captions
        out = captions.compose_text("见 [图片#2]",
            {"图片#2": {"media_key": "k", "caption": "",
                        "caption_by": "none", "status": "pending"}})
        assert "[图片#2]" in out   # 无替身 → 原占位符不变

    def test_update_caption_writes_imgmap(self, tmp_path):
        from specflow.feishu_pool import captions
        md_file = tmp_path / "fd-tokA.md"
        md_file.write_text("如图 [图片#1]\n", encoding="utf-8")
        img_file = tmp_path / "fd-tokA.imgmap.json"
        img_file.write_text(json.dumps(
            {"图片#1": {"media_key": "k", "caption": "",
                        "caption_by": "none", "status": "pending"}},
            ensure_ascii=False), encoding="utf-8")
        captions.update_caption(img_file, "图片#1", "人工补写：权限矩阵图", by="manual")
        saved = json.loads(img_file.read_text(encoding="utf-8"))
        assert saved["图片#1"]["caption"] == "人工补写：权限矩阵图"
        assert saved["图片#1"]["caption_by"] == "manual"
        assert saved["图片#1"]["status"] == "done"


# ══════════════════════════════════════════════════════════
# T-925：事件直写原语（append_chat_lines / 去重 / 发送人缓存）
# ══════════════════════════════════════════════════════════

class TestDirectWrite:
    def test_append_chat_lines_format(self, tmp_path):
        emp = tmp_path / ".specflow" / "u1"
        pool_store.append_chat_lines(
            emp, "oc_abc", "20260814",
            ["[20:40] 张三: 直写消息一", "[20:41] 李四: 直写消息二"])
        pool_store.append_chat_lines(emp, "oc_abc", "20260814",
                                     ["[20:42] 张三: 追加"])
        f = next((emp / "feishu_pool" / "chats").rglob("20260814.md"))
        text = f.read_text(encoding="utf-8")
        assert "直写消息一" in text and "追加" in text
        assert text.count("\n[20:") >= 2           # 追加非覆盖

    def test_event_dedup(self, tmp_path):
        emp = tmp_path / ".specflow" / "u1"
        assert pool_store.mark_event_seen(emp, "e1") is True
        assert pool_store.mark_event_seen(emp, "e1") is False   # 重复事件不双写

    def test_sender_name_fallback(self, tmp_path):
        from unittest.mock import patch as _patch
        emp = tmp_path / ".specflow" / "u1"
        with _patch.object(pool_store, "_resolve_sender", return_value=""):
            name = pool_store.sender_display(emp, "ou_abcdef123456")
        assert name == "…123456"                   # 解析失败用 open_id 尾 6 位

    def test_sender_name_cached(self, tmp_path):
        from unittest.mock import patch as _patch
        emp = tmp_path / ".specflow" / "u1"
        with _patch.object(pool_store, "_resolve_sender", return_value="张三") as m:
            n1 = pool_store.sender_display(emp, "ou_abc")
            n2 = pool_store.sender_display(emp, "ou_abc")
        assert n1 == "张三" and n2 == "张三"
        assert m.call_count == 1                     # 第二次命中缓存不再解析
