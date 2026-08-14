"""test_feishu_pool_page.py — 材料池总览页后端端点用例（三期 T-929）。

覆盖：材料池清单 / 话题清单（候选+已确认）/ caption 人工补写端点语义。
"""

import json
import sys
from pathlib import Path

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
