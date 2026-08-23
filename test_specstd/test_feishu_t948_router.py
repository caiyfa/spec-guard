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


# ══════════════════════════════════════════════════════════
# T-993：跨群关联端点（relate 确认/忽略 + relations 清单）
# ══════════════════════════════════════════════════════════

def _mk_two_topic_file(emp: Path):
    (emp / "feishu_pool").mkdir(parents=True, exist_ok=True)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:aaaaaa-20260807-01\n    title: 产研群讨论\n    summary: s\n"
        "    chat_sha8: aaaaaa\n    status: confirmed\n    rev: 1\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T15:00']\n"
        "    message_count: 5\n    participants_count: 2\n"
        "    source: chats/aaaaaa/20260807.md\n"
        "  - id: tp:bbbbbb-20260807-01\n    title: 测试群跟进\n    summary: s\n"
        "    chat_sha8: bbbbbb\n    status: draft\n    rev: 1\n"
        "    window: ['2026-08-07T15:00', '2026-08-07T16:00']\n"
        "    message_count: 4\n    participants_count: 2\n"
        "    source: chats/bbbbbb/20260807.md\n", encoding="utf-8")


def test_relate_topics_confirm_writes_edge(tmp_path):
    """确认关联 → facts 落 relates confirmed 边（键规范化小 id 在前）。"""
    from specflow.feishu_pool import facts
    emp = tmp_path / ".specflow" / "u1"
    ws = tmp_path / "ws"
    _mk_two_topic_file(emp)
    body = rp.RelateRequest(a="tp:bbbbbb-20260807-01",
                            b="tp:aaaaaa-20260807-01", confirmed=True)
    with patch.object(rp, "_sf_base", return_value=emp), \
         patch.object(rp, "_material_base", return_value=emp), \
         patch.object(rp, "_ws_root", return_value=ws):
        out = rp.relate_topics(body, user=_USER, workspace="tdm")
    assert out["status"] == "confirmed"
    assert out["a"] == "tp:aaaaaa-20260807-01"     # 排序规范化
    links = facts.load_links(ws)
    assert links[0]["edge"] == "relates"
    assert links[0]["status"] == "confirmed"
    assert links[0]["confirmed_by"] == "90000001"


def test_relate_topics_reject_leaves_trace(tmp_path):
    """忽略关联 → rejected 留痕（防重复推荐）。"""
    from specflow.feishu_pool import facts
    emp = tmp_path / ".specflow" / "u1"
    ws = tmp_path / "ws"
    _mk_two_topic_file(emp)
    body = rp.RelateRequest(a="tp:aaaaaa-20260807-01",
                            b="tp:bbbbbb-20260807-01", confirmed=False)
    with patch.object(rp, "_sf_base", return_value=emp), \
         patch.object(rp, "_material_base", return_value=emp), \
         patch.object(rp, "_ws_root", return_value=ws):
        rp.relate_topics(body, user=_USER, workspace="tdm")
    links = facts.load_links(ws)
    assert links[0]["status"] == "rejected"
    # relations 端点只回 confirmed
    with patch.object(rp, "_sf_base", return_value=emp), \
         patch.object(rp, "_material_base", return_value=emp), \
         patch.object(rp, "_ws_root", return_value=ws):
        out = rp.topic_relations(user=_USER, workspace="tdm")
    assert out["items"] == []


def test_relate_topics_unknown_id_404(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    _mk_two_topic_file(emp)
    body = rp.RelateRequest(a="tp:not-exist", b="tp:aaaaaa-20260807-01")
    with patch.object(rp, "_sf_base", return_value=emp), \
         patch.object(rp, "_material_base", return_value=emp), \
         pytest.raises(Exception) as ei:
        rp.relate_topics(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404


def test_update_card_reassociate_messages(tmp_path):
    """T-1001 F4：CardUpdate 带 message_ids/window/days → edit_candidate 透传。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:3f9a2c-20260807-01",
                         message_ids=["om_x", "om_y"],
                         window=["2026-08-07T14:00", "2026-08-07T14:20"],
                         days=["20260807"], base_rev=3)
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp):
        t = rp.update_topic_card(body, user=_USER, workspace="tdm")
    assert t["message_ids"] == ["om_x", "om_y"]
    assert t["window"] == ["2026-08-07T14:00", "2026-08-07T14:20"]
    assert t["days"] == ["20260807"]
    assert t["rev"] == 4


def test_update_card_empty_message_ids_400(tmp_path):
    """空 message_ids → 400（至少关联一条）。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_topic_file(emp)
    body = rp.CardUpdate(id="tp:3f9a2c-20260807-01", message_ids=[], base_rev=3)
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp), \
         pytest.raises(Exception) as ei:
        rp.update_topic_card(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 400
    assert "message_ids" in str(ei.value.detail)


# ══════════════════════════════════════════════════════════
# T-1002：勾选原文生成话题路由（/topics/compose）
# ══════════════════════════════════════════════════════════

def _mk_chat_jsonl(emp: Path):
    """造 JSONL 事实源（compose 反查 message_id 所属日用）。"""
    from specflow.feishu_pool import chat_store as cs
    day_file = emp / "feishu_pool" / "chats" / "3f9a2c" / "20260807.jsonl"
    rows = []
    for i, (mid, hhmm, sender) in enumerate(
            [("om_a", "14:00", "张三"), ("om_b", "14:01", "李四")], start=1):
        rows.append({"message_id": mid, "position": str(i),
                     "sender_id": f"ou_{i}", "sender_name": sender,
                     "ts": f"2026-08-07T{hhmm}:00", "msg_type": "text",
                     "content": f"内容{i}", "image_key": "", "reply_to": "",
                     "mentions": [], "origin": "pull"})
    cs.merge_chat_jsonl(day_file, rows)
    cs.rebuild_views(day_file)


def test_compose_manual_fields_no_llm_needed(tmp_path):
    """title/summary/keywords 全填 → 未配置 text 模型也可生成（不调 LLM）。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_chat_jsonl(emp)
    body = rp.ComposeRequest(chat_sha8="3f9a2c", days=["20260807"],
                             message_ids=["om_a", "om_b"],
                             title="手动标题", summary="手动摘要",
                             keywords=["手动词"], extra_context="")
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp):
        out = rp.compose_topic(body, user=_USER, workspace="tdm")
    assert out["title"] == "手动标题"
    assert out["message_ids"] == ["om_a", "om_b"]
    assert out["message_count"] == 2


def test_compose_empty_ids_400(tmp_path):
    """空 message_ids → 400（至少勾选一条）。"""
    emp = tmp_path / ".specflow" / "u1"
    body = rp.ComposeRequest(chat_sha8="3f9a2c", days=["20260807"],
                             message_ids=[])
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp),          pytest.raises(Exception) as ei:
        rp.compose_topic(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 400


def test_compose_missing_id_404(tmp_path):
    """message_id 不在快照 → 404（防静默丢关联；全填字段免 LLM 依赖）。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_chat_jsonl(emp)
    body = rp.ComposeRequest(chat_sha8="3f9a2c", days=["20260807"],
                             message_ids=["om_a", "om_ghost"],
                             title="t", summary="s", keywords=["k"])
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp),          pytest.raises(Exception) as ei:
        rp.compose_topic(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404


def test_compose_llm_needed_but_unconfigured_400(tmp_path):
    """留空字段需 LLM 补全但 text 模型未配置 → 400（前端弹层就地配置）。
    get_model 打桩隔离——真实库有无配置/密钥可用不影响断言。"""
    emp = tmp_path / ".specflow" / "u1"
    _mk_chat_jsonl(emp)
    body = rp.ComposeRequest(chat_sha8="3f9a2c", days=["20260807"],
                             message_ids=["om_a"], title="", summary="")
    with patch.object(rp, "_sf_base", return_value=emp), _patch_bases(emp),          patch("services.model_config.get_model", return_value=None),          pytest.raises(Exception) as ei:
        rp.compose_topic(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 400
    assert "未配置 text 模型" in str(ei.value.detail)
