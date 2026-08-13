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
