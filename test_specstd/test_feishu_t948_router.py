"""test_feishu_t948_router.py — T-948 路由层单测（编辑 API + messages 端点）。

路由函数直调（不走 TestClient——认证/workspace 中间件与 RBAC 另有测试覆盖），
patch _sf_base 指向 tmp 私有区。核心业务逻辑在 test_feishu_topic_cluster 已覆盖，
此处聚焦 HTTP 语义转换（409 乐观锁 / 404 / 状态翻转端点 / JSONL 读取）。
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from routers import feishu_pool as rp  # noqa: E402

_USER = SimpleNamespace(emp_no="90000001", name="王测试")

def _patch_bases(emp: Path):
    """T-949：双 base patch（单用户模式——材料区与私有区同路径）。"""
    return patch.object(rp, "_material_base", return_value=emp)

def _mk_topic_file(emp: Path):
    (emp / "feishu_pool").mkdir(parents=True, exist_ok=True)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 原标题\n    summary: 原摘要\n"
        "    keywords: [权限]\n    chat_sha8: 3f9a2c\n    rev: 3\n    status: draft\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")

def test_update_card_rev_conflict_returns_409(tmp_path):
    """base_rev 落后 → 409 + detail 携带最新卡片（前端冲突提示载荷）。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:3f9a2c-20260807-01", title="抢写",
                         base_rev=1)
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp), \
         pytest.raises(Exception) as ei:
        rp.update_topic_card(body, user=_USER, workspace="tdm")
    exc = ei.value
    assert getattr(exc, "status_code", None) == 409
    assert exc.detail["topic"]["rev"] == 3
    assert "已被他人编辑" in exc.detail["message"]

def test_update_card_keywords_ok(tmp_path):
    """编辑 keywords 成功路径：卡片更新 + editor 身份落痕。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:3f9a2c-20260807-01", keywords=["导出", "数据权限"],
                         base_rev=3)
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp):
        t = rp.update_topic_card(body, user=_USER, workspace="tdm")
    assert t["keywords"] == ["导出", "数据权限"]
    assert t["rev"] == 4
    assert t["last_edited_by"]["emp"] == "90000001"

def test_update_card_404(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:not-exist")
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp), \
         pytest.raises(Exception) as ei:
        rp.update_topic_card(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404

def test_confirm_reject_endpoints(tmp_path):
    """confirm/reject 端点：状态翻转 + editor 留痕 + facts 图谱联动（T-949）。"""
    emp = tmp_path / ".specflow" / "u1"
    ws = tmp_path / "ws"
    _mk_topic_file(emp)
    body = rp.TopicIdRequest(id="tp:3f9a2c-20260807-01")
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp), \
         patch.object(rp, "_ws_root", return_value=ws):
        t = rp.confirm_topic(body, user=_USER, workspace="tdm")
        assert t["status"] == "confirmed"
        t2 = rp.reject_topic(body, user=_USER, workspace="tdm")
        assert t2["status"] == "rejected"
        items = rp.topic_history("tp:3f9a2c-20260807-01",
                                 user=_USER, workspace="tdm")["items"]
    actions = [h["action"] for h in items]
    assert actions[0] == "reject" and actions[1] == "confirm"
    assert items[0]["editor"]["name"] == "王测试"
    # T-949 图谱事实源联动：confirm 提升、reject 移除
    from specflow.feishu_pool import facts
    assert facts.load_topics(ws) == []               # reject 后图谱无残留

def test_chat_messages_endpoint(tmp_path):
    """/chat-messages：返回 JSONL 事实源数组（精确高亮数据源）。"""
    from specflow.feishu_pool import chat_store as cs
    emp = tmp_path / ".specflow" / "u1"
    day_file = emp / "feishu_pool" / "chats" / "3f9a2c" / "20260807.jsonl"
    cs.merge_chat_jsonl(day_file, [{
        "message_id": "om_1", "position": "1", "sender_id": "ou_a",
        "sender_name": "张三", "ts": "2026-08-07T14:00:00", "msg_type": "text",
        "content": "消息", "image_key": "", "reply_to": "", "mentions": [],
        "origin": "pull"}])
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp):
        out = rp.chat_messages(sha8="3f9a2c", day="20260807",
                               user=_USER, workspace="tdm")
    assert out["file"] == "chats/3f9a2c/20260807.jsonl"
    assert out["items"][0]["message_id"] == "om_1"
    # 路径穿越防护：sha8 带斜杠 → 404
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp), \
         pytest.raises(Exception) as ei:
        rp.chat_messages(sha8="../..", day="20260807",
                         user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404


# ══════════════════════════════════════════════════════════
# T-991：卡片编辑 category/priority（schema v3）
# ══════════════════════════════════════════════════════════

def test_update_card_category_priority_ok(tmp_path):
    """编辑分类/优先级成功：卡片更新 + rev 推进。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:3f9a2c-20260807-01", category="test",
                         priority="high", base_rev=3)
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp):
        t = rp.update_topic_card(body, user=_USER, workspace="tdm")
    assert t["category"] == "test" and t["priority"] == "high"
    assert t["rev"] == 4


def test_update_card_invalid_category_400(tmp_path):
    """非法枚举 → 400（诚实报错，不静默归默认）。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:3f9a2c-20260807-01", category="bogus",
                         base_rev=3)
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp), \
         pytest.raises(Exception) as ei:
        rp.update_topic_card(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 400
    assert "category" in str(ei.value.detail)
