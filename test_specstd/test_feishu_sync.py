"""test_feishu_sync.py — 飞书材料池拉取入库单测（飞书知识图谱一期 T4）。

覆盖：
- watch 配置读写（feishu_watch.yaml = 显式授权载体）
- sync_doc：docs +fetch 产物落池 + imgmap 初始 pending
- sync_chat：消息列表渲染 [HH:MM] 行格式落池
- sync_all：单通道失败记 errors 不中断（诚实呈现）
注：lark-cli 真实返回结构以实测为准微调，测试锁定落盘契约（mock _run_lark）。
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
for p in (str(SG_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from services.specflow import feishu_sync_service as svc  # noqa: E402


def test_watch_config_roundtrip(tmp_path):
    base = tmp_path / ".specflow" / "u1"
    cfg = {"chats": [{"chat_id": "oc_abc", "name": "需求讨论群"}],
           "docs": [{"token": "FBxod", "url": "https://..."}],
           "minutes_days": 30, "chat_days": 7}
    svc.save_watch_config(base, cfg)
    loaded = svc.load_watch_config(base)
    assert loaded["chats"][0]["chat_id"] == "oc_abc"
    assert loaded["minutes_days"] == 30


def test_watch_config_default_when_missing(tmp_path):
    loaded = svc.load_watch_config(tmp_path / ".specflow" / "u1")
    assert loaded == {"chats": [], "docs": [], "minutes_days": 30, "chat_days": 7}


def test_sync_doc_to_pool(tmp_path):
    base = tmp_path / ".specflow" / "u1"
    payload = {"ok": True, "data": {"content": "# PRD 正文 [图片#1]",
                                    "images": [{"placeholder": "图片#1",
                                                "media_key": "img_v3_x"}]}}
    with patch.object(svc, "_run_lark", return_value=payload):
        rec = svc.sync_doc(base, doc_token="FBxod", url="https://...")
    assert rec["node_id"] == "fd:FBxod"
    assert (base / "feishu_pool" / "docs" / "fd-FBxod.md").is_file()
    assert (base / "feishu_pool" / "docs" / "fd-FBxod.imgmap.json").is_file()


def test_sync_chat_renders_timeline(tmp_path):
    base = tmp_path / ".specflow" / "u1"
    payload = {"ok": True, "data": {"items": [
        {"create_time_ms": "1691498400000", "sender_name": "张三",
         "msg_type": "text", "text": "导出要按平台过滤吗"},
        {"create_time_ms": "1691498460000", "sender_name": "李四",
         "msg_type": "text", "text": "按 corpCode+groupLevel"},
    ]}}
    with patch.object(svc, "_run_lark", return_value=payload):
        rec = svc.sync_chat(base, chat_id="oc_abc", day="20230808")
    f = base / "feishu_pool" / "chats" / rec["chat_sha8"] / "20230808.md"
    text = f.read_text(encoding="utf-8")
    from datetime import datetime
    t1 = datetime.fromtimestamp(1691498400000 / 1000).strftime("%H:%M")
    t2 = datetime.fromtimestamp(1691498460000 / 1000).strftime("%H:%M")
    assert f"[{t1}] 张三: 导出要按平台过滤吗" in text
    assert f"[{t2}] 李四: 按 corpCode+groupLevel" in text


def test_sync_all_collects_errors(tmp_path):
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [{"chat_id": "oc_abc"}],
                                 "docs": [{"token": "FBxod"}],
                                 "minutes_days": 0, "chat_days": 1})

    def _fake(args, timeout=90):
        if "docs" in args:
            raise ValueError("无权限，请点击链接申请权限")
        return {"ok": True, "data": {"items": []}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        out = svc.sync_all(base)
    assert out["errors"] and "无权限" in out["errors"][0]   # 诚实呈现
    assert "docs" in out and "chats" in out                  # 不中断


def test_sync_recent_docs_intersection(tmp_path):
    """T-922：drive +search 近1天编辑 ∩ watch.docs 授权清单 → 仅交集落池。"""
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [], "minutes_days": 0, "chat_days": 1,
                                 "docs": [{"token": "tokAuth"}]})
    found = {"ok": True, "data": {"items": [
        {"token": "tokAuth", "title": "授权内文档"},
        {"token": "tokOther", "title": "未授权文档"}]}}

    def _fake(args, timeout=90):
        if "+search" in args:
            return found
        return {"ok": True, "data": {"content": "正文", "images": []}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        out = svc.sync_recent_docs(base, days=1)
    assert out["docs"] == 1                                    # tokOther 被交集过滤
    assert (base / "feishu_pool" / "docs" / "fd-tokAuth.md").is_file()
    assert not (base / "feishu_pool" / "docs" / "fd-tokOther.md").exists()


# ══════════════════════════════════════════════════════════
# T-916：端到端贯通（全 mock：同步→聚类→建议→确认→图谱→焦点子图）
# ══════════════════════════════════════════════════════════

def test_e2e_pipeline(tmp_path):
    from unittest.mock import MagicMock
    from specflow.feishu_pool import link_suggest as ls
    from specflow.feishu_pool import topic_cluster as tc
    from specstd.anchors import scan_anchors
    from services.specflow import feishu_review_service as rev
    from graph_index.builder import build_index
    from graph_index.service import focus_subgraph, index_path
    from graph_index.store import GraphStore

    emp = tmp_path / ".specflow" / "u1"
    ws = tmp_path / "ws"
    (ws / "specs" / "inventory" / "grid-placement").mkdir(parents=True)
    (ws / "specs" / "inventory" / "grid-placement" / "spec.md").write_text(
        "### FR-012: 作废级联删除\n作废会话后级联删除人员。\n", encoding="utf-8")
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()

    # ① 同步（mock lark 三通道）
    svc.save_watch_config(emp, {"chats": [{"chat_id": "oc_abc"}],
                                "docs": [{"token": "tokA"}],
                                "minutes_days": 0, "chat_days": 1})

    def _fake(args, timeout=90):
        if "docs" in args:
            return {"ok": True, "data": {"content": "作废会话后级联删除人员", "images": []}}
        if "chat-messages-list" in " ".join(args):
            return {"ok": True, "data": {"items": [
                {"create_time_ms": "1691498400000", "sender_name": "张三",
                 "msg_type": "text", "text": "作废会话后级联删除人员"}]}}
        return {"ok": True, "data": {"items": []}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        out = svc.sync_all(emp)
    assert out["docs"] == 1 and out["chats"] == 1

    # ② 话题聚类（mock LLM；msg_range 取快照实际渲染时间戳）
    import json as _json
    chat_file = next((emp / "feishu_pool" / "chats").rglob("*.md"))
    ts = chat_file.read_text(encoding="utf-8").split("]")[0] + "]"
    llm = MagicMock()
    llm.chat.return_value = {"content": _json.dumps({"topics": [{
        "title": "级联删除讨论", "summary": "作废会话后级联删除人员",
        "msg_range": [ts, ts], "participants_count": 1}]}, ensure_ascii=False)}
    produced = tc.cluster_chat_snapshots(emp, llm)
    assert len(produced) == 1
    topic_id = produced[0]["id"]

    # ③ 建边建议（mock LLM；evidence 为原文子串）
    anchors = scan_anchors(ws)
    llm2 = MagicMock()
    llm2.chat.return_value = {"content": (
        '{"links": [{"fr_id": "FR-012", "confidence": 0.9,'
        ' "evidence": "作废会话后级联删除人员"}]}')}
    doc_text = (emp / "feishu_pool" / "docs" / "fd-tokA.md").read_text(encoding="utf-8")
    sug_doc = ls.suggest_links_for_material("fd:tokA", doc_text, anchors, llm2,
                                            workspace_root=ws)
    sug_tp = ls.suggest_links_for_material(topic_id, produced[0]["summary"],
                                           anchors, llm2, workspace_root=ws)
    assert len(sug_doc) == 1 and len(sug_tp) == 1

    # ④ 入队 + 人拍板确认（提升共享区）
    rev.enqueue_suggestions(emp, "u1", sug_doc + sug_tp)
    out = rev.confirm_suggestions(emp, ws, "u1",
                                  [("fd:tokA", "FR-012"), (topic_id, "FR-012")])
    assert out["confirmed"] == 2

    # ⑤ 图谱派生 + 焦点子图
    build_index(ws, index_path(ws), scenarios_root=scenarios, sg_root=tmp_path)
    with GraphStore(index_path(ws)) as store:
        assert store.get_node("fd:tokA")["node_type"] == "feishu_doc"
        assert store.get_node(topic_id)["node_type"] == "topic"
        assert len(store.list_edges("mentions")) == 2
        sub = focus_subgraph(store, "FR-012", depth=1)
        ids = {n["id"] for n in sub["nodes"]}
        assert {"fd:tokA", topic_id} <= ids
