"""test_feishu_t949_shared.py — T-949 共享化迁移测试（方案 A 全通道）。

核心语义（设计 §D2）：
- chats/docs/minutes 快照与话题库/历史落**共享材料区**（material_base，工作台
  传 specflow_dir("") 即 {ws}/.specflow/）；多用户重复拉取靠 message_id 幂等合并
  无害化——同一群全工作区只有一份快照。
- watch 配置、话题草案留**私有区**（个人拉取范围与个人工作产物）。
"""

import sys
from pathlib import Path
from unittest.mock import patch

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
TEST_DIR = Path(__file__).resolve().parent
for p in (str(SG_ROOT), str(BACKEND_DIR), str(TEST_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from feishu_cli_contract import pull_messages  # noqa: E402
from services.specflow import feishu_sync_service as svc  # noqa: E402

from specflow.feishu_pool import topic_cluster as tc  # noqa: E402


def _fake_lark_with_msgs(msgs):
    def _fake(args, timeout=90):
        if args[:2] == ["im", "+chat-messages-list"]:
            return {"ok": True, "data": {"messages": msgs}}
        if "docs" in args:
            return {"ok": True, "data": {"content": "正文", "images": []}}
        return {"ok": True, "data": {}}
    return _fake


def test_sync_all_routes_materials_to_shared_base(tmp_path):
    """sync_all(material_base=共享根)：chats/docs/minutes 落共享区，
    watch 配置仍在私有区读取。"""
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"          # 共享区根（specflow_dir("") 形状）
    svc.save_watch_config(emp, {"chats": [{"chat_id": "oc_abc"}],
                                "docs": [{"token": "tokA"}],
                                "minutes_days": 0, "chat_days": 1})
    with patch.object(svc, "_run_lark",
                      side_effect=_fake_lark_with_msgs(pull_messages())), \
         patch.object(svc, "maybe_cluster_async") as mc:
        out = svc.sync_all(emp, material_base=shared)
    assert out["chats"] == 1
    assert (shared / "feishu_pool" / "chats").is_dir()          # 快照在共享区
    assert (emp / "feishu_pool" / "chats").exists() is False    # 私有区无快照
    assert (shared / "feishu_pool" / "docs" / "fd-tokA.md").is_file()
    mc.assert_called_once_with(emp, material_base=shared)       # 聚类也走共享区


def test_two_users_sync_same_chat_idempotent(tmp_path):
    """两用户先后同步同群同消息 → 共享 JSONL 无重复（幂等合并红利）。"""
    from datetime import datetime

    from specflow.feishu_pool import chat_store as cs
    from specflow.feishu_pool import pool_store
    emp1 = tmp_path / ".specflow" / "u1"
    emp2 = tmp_path / ".specflow" / "u2"
    shared = tmp_path / ".specflow"
    for emp in (emp1, emp2):
        svc.save_watch_config(emp, {"chats": [{"chat_id": "oc_abc"}],
                                    "minutes_days": 0, "chat_days": 1})
    fake = _fake_lark_with_msgs(pull_messages())
    with patch.object(svc, "_run_lark", side_effect=fake), \
         patch.object(svc, "maybe_cluster_async"):
        svc.sync_all(emp1, material_base=shared)
        svc.sync_all(emp2, material_base=shared)
    today = datetime.now().strftime("%Y%m%d")
    jsonl = (shared / "feishu_pool" / "chats" / pool_store.chat_sha8("oc_abc")
             / f"{today}.jsonl")
    rows = cs.load_chat_jsonl(jsonl)
    assert len(rows) == 2                                # 契约快照 2 条消息
    ids = [r["message_id"] for r in rows]
    assert len(ids) == len(set(ids))                     # 无重复


def test_topic_store_on_shared_base(tmp_path):
    """话题库/历史随 material_base 落共享区（多用户加工同一份卡片）。"""
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    out = tc.commit_drafts(emp, "3f9a2c", "20260819",
                           [{"title": "共享话题", "summary": "s",
                             "window": ["2026-08-19T14:00", "2026-08-19T14:01"],
                             "message_count": 2, "participants_count": 2,
                             "source": "chats/3f9a2c/20260819.md"}],
                           author={"emp": "u1", "name": "甲"},
                           material_base=shared)
    assert (shared / "feishu_pool" / "_topics.yaml").is_file()
    assert (shared / "feishu_pool" / "_topic_history.jsonl").is_file()
    assert not (emp / "feishu_pool" / "_topics.yaml").exists()
    # 用户 u2 在共享库上编辑（留痕协作）
    t = tc.edit_candidate(emp, out[0]["id"], title="协作改题", base_rev=1,
                          editor={"emp": "u2", "name": "乙"},
                          material_base=shared)
    assert t["rev"] == 2
    hist = tc.list_history(emp, out[0]["id"], material_base=shared)
    assert {h["editor"]["emp"] for h in hist} == {"u1", "u2"}


def test_drafts_stay_private_chats_read_shared(tmp_path):
    """draft：chats 从共享区读，_topic_drafts.yaml 落私有区（个人工作产物）。"""
    from unittest.mock import MagicMock

    from specflow.feishu_pool import chat_store as cs
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    day_file = shared / "feishu_pool" / "chats" / "3f9a2c" / "20260819.jsonl"
    cs.merge_chat_jsonl(day_file, [{
        "message_id": "om_a", "position": "1", "sender_id": "ou_1",
        "sender_name": "张三", "ts": "2026-08-19T14:00:00", "msg_type": "text",
        "content": "导出要按平台过滤吗", "image_key": "", "reply_to": "",
        "mentions": [], "origin": "pull"}])
    llm = MagicMock()
    llm.chat.return_value = {"content":
                             '{"topics": [{"title": "t", "summary": "s",'
                             ' "msg_lines": [1], "msg_range": ["[14:00]", "[14:00]"],'
                             ' "participants_count": 1}]}'}
    out = tc.draft_chat_segments(emp, llm, "3f9a2c", ["20260819"],
                                 material_base=shared)
    assert out[0]["message_ids"] == ["om_a"]              # 读到共享区事实源
    assert (emp / "feishu_pool" / "_topic_drafts.yaml").is_file()   # 草案私有
    assert not (shared / "feishu_pool" / "_topic_drafts.yaml").exists()


# ══════════════════════════════════════════════════════════
# T-949 T2：docs/minutes 权限元数据拉取（perm meta sidecar）
# ══════════════════════════════════════════════════════════

def _read_meta(emp: Path, name: str) -> dict:
    import json as _json
    return _json.loads(
        (emp / "feishu_pool" / "docs" / f"{name}.meta.json").read_text(
            encoding="utf-8"))


def test_sync_doc_pulls_perm_meta(tmp_path):
    """权限接口成功：meta.perm 落 public + member_users + member_chats。"""
    from feishu_cli_contract import MEMBER_LIST_OK, SETTING_OK
    base = tmp_path / ".specflow" / "u1"

    def _fake(args, timeout=90):
        if "+member-list" in args:
            return MEMBER_LIST_OK
        if "+permission-get-setting" in args:
            return SETTING_OK
        return {"ok": True, "data": {"content": "正文", "images": []}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        svc.sync_doc(base, doc_token="tokP", url="https://x")
    perm = _read_meta(base, "fd-tokP")["perm"]
    assert perm["pulled_at"] is not None
    assert perm["member_users"] == ["ou_owner"]
    assert perm["member_chats"] == ["oc_group"]
    assert perm["public"] is True        # link_share_entity=tenant_readable


def test_sync_doc_missing_scope_no_block(tmp_path):
    """missing_scope（2026-08-19 实测形状）：正文照常落盘，perm 诚实记缺失。"""
    from feishu_cli_contract import perm_missing_payloads
    base = tmp_path / ".specflow" / "u1"
    miss_member, miss_setting = perm_missing_payloads()

    def _fake(args, timeout=90):
        if "+member-list" in args:
            raise ValueError(f"lark-cli 调用失败: {miss_member['error']['message']}")
        if "+permission-get-setting" in args:
            raise ValueError(f"lark-cli 调用失败: {miss_setting['error']['message']}")
        return {"ok": True, "data": {"content": "正文", "images": []}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        svc.sync_doc(base, doc_token="tokQ", url="https://x")
    assert (base / "feishu_pool" / "docs" / "fd-tokQ.md").is_file()  # 不阻断
    perm = _read_meta(base, "fd-tokQ")["perm"]
    assert perm["pulled_at"] is None
    assert "permission.member:retrieve" in perm["error"]


def test_sync_minutes_perm_meta(tmp_path):
    """妙记同步同样落 perm meta（owner 归属 + 权限元数据同构）。"""
    from feishu_cli_contract import MEMBER_LIST_OK, SETTING_OK

    def _fake(args, timeout=90):
        if "+member-list" in args:
            return MEMBER_LIST_OK
        if "+permission-get-setting" in args:
            return SETTING_OK
        if args[:2] == ["minutes", "+search"]:
            return {"ok": True, "data": {"items": [
                {"minute_token": "obcnP",
                 "meta_data": {"app_link": "u"}}]}}
        return {"ok": True, "data": {"summary": "s"}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        svc.sync_minutes(tmp_path / ".specflow" / "u1", days=30)
    import json as _json
    meta = _json.loads(
        (tmp_path / ".specflow" / "u1" / "feishu_pool" / "minutes"
         / "fm-obcnP.meta.json").read_text(encoding="utf-8"))
    assert meta["perm"]["member_users"] == ["ou_owner"]


# ══════════════════════════════════════════════════════════
# T-949 T3：材料可见性过滤（跟随飞书权限）
# ══════════════════════════════════════════════════════════

def _mk_doc_item(perm=None, owner=""):
    return {"id": "fd:tokV", "type": "feishu_doc", "title": "文档", "file": "docs/fd-tokV.md",
            "owner_open_id": owner, "perm": perm}


def test_visibility_chat_always_visible():
    """群聊快照：拉取者必在群内（办公转述语义）→ 工作区全员可见。"""
    item = {"id": "chat:aaa/1", "type": "chat", "perm": None, "owner_open_id": ""}
    assert svc.material_visible(item, "", set()) is True


def test_visibility_perm_member_user():
    """perm 有效：被授权用户可见；无关用户不可见。"""
    ok_perm = {"pulled_at": "2026-08-19T09:00:00", "public": False,
               "member_users": ["ou_a"], "member_chats": []}
    assert svc.material_visible(_mk_doc_item(ok_perm), "ou_a", set()) is True
    assert svc.material_visible(_mk_doc_item(ok_perm), "ou_b", set()) is False


def test_visibility_perm_member_chat():
    """群授权：viewer 所在群 ∩ member_chats → 可见。"""
    ok_perm = {"pulled_at": "2026-08-19T09:00:00", "public": False,
               "member_users": [], "member_chats": ["oc_x"]}
    assert svc.material_visible(_mk_doc_item(ok_perm), "ou_b", {"oc_x"}) is True
    assert svc.material_visible(_mk_doc_item(ok_perm), "ou_b", {"oc_y"}) is False


def test_visibility_public_and_owner():
    """public 材料/owner 本人始终可见。"""
    pub = {"pulled_at": "t", "public": True, "member_users": [], "member_chats": []}
    assert svc.material_visible(_mk_doc_item(pub), "ou_any", set()) is True
    miss = {"pulled_at": None, "public": False, "member_users": [], "member_chats": []}
    assert svc.material_visible(_mk_doc_item(miss, owner="ou_own"), "ou_own", set()) is True


def test_visibility_perm_missing_conservative():
    """perm 缺失（missing_scope）：非 owner 不可见（保守——推用户补授权）。"""
    miss = {"pulled_at": None, "public": False, "member_users": ["ou_a"],
            "member_chats": [], "error": "missing_scope"}
    assert svc.material_visible(_mk_doc_item(miss), "ou_a", set()) is False


def test_list_pool_materials_viewer_filter(tmp_path):
    """清单层：viewer 过滤生效；viewer=None 不过滤（兼容）。"""
    import json as _json
    base = tmp_path / ".specflow"
    docs = base / "feishu_pool" / "docs"
    docs.mkdir(parents=True)
    (docs / "fd-tokP.md").write_text("# 文档P", encoding="utf-8")
    (docs / "fd-tokP.meta.json").write_text(_json.dumps(
        {"owner_open_id": "ou_own", "perm": {"pulled_at": "t", "public": False,
         "member_users": ["ou_b"], "member_chats": []}}), encoding="utf-8")
    (docs / "fd-tokQ.md").write_text("# 文档Q", encoding="utf-8")
    (docs / "fd-tokQ.meta.json").write_text(_json.dumps(
        {"owner_open_id": "", "perm": {"pulled_at": None, "public": False,
         "member_users": [], "member_chats": [], "error": "missing_scope"}}),
        encoding="utf-8")
    all_items = svc.list_pool_materials(base)
    assert len(all_items) == 2                        # 无 viewer：不过滤
    bob = svc.list_pool_materials(base, viewer={"open_id": "ou_b", "chats": set()})
    assert {i["id"] for i in bob} == {"fd:tokP"}      # 仅被授权的 P 可见
    owner = svc.list_pool_materials(base, viewer={"open_id": "ou_own", "chats": set()})
    assert {i["id"] for i in owner} == {"fd:tokP"}    # owner 可见 P；Q 无 owner 且 perm 缺失不可见


# ══════════════════════════════════════════════════════════
# T-949 T4：confirm 联动图谱事实源 + 存量私有区迁移
# ══════════════════════════════════════════════════════════

def test_confirm_reject_sync_facts(tmp_path):
    """confirm → facts.topics_yaml 含 v2 卡片；reject 已确认卡 → facts 移除。"""
    ws = tmp_path / "ws"
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    out = tc.commit_drafts(emp, "3f9a2c", "20260819",
                           [{"title": "图谱联动", "summary": "s",
                             "window": ["2026-08-19T14:00", "2026-08-19T14:01"],
                             "message_count": 2, "participants_count": 1,
                             "source": "chats/3f9a2c/20260819.md"}],
                           material_base=shared)
    tid = out[0]["id"]
    from specflow.feishu_pool import facts
    # confirmed → upsert facts（图谱派生源；v2 字段经白名单保留）
    tc.set_topic_status(emp, tid, "confirmed",
                        editor={"emp": "u1", "name": "甲"}, material_base=shared)
    facts.upsert_topic(ws, tc._load_candidates(shared)[0])
    confirmed = facts.load_topics(ws)
    assert any(t["id"] == tid and t.get("keywords") == [] for t in confirmed)
    # rejected → facts 移除（图谱一致性）
    facts.remove_topic(ws, tid)
    assert all(t["id"] != tid for t in facts.load_topics(ws))


def test_migrate_legacy_private_pool(tmp_path):
    """存量迁移：私有区 chats/_topics/_history → 共享区；幂等可重跑。"""
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    chats = emp / "feishu_pool" / "chats" / "3f9a2c"
    chats.mkdir(parents=True)
    (chats / "20260819.md").write_text("[14:00] 张三: 旧私有一条\n", encoding="utf-8")
    (emp / "feishu_pool" / "_candidate_topics.yaml").write_text(
        "version: 1\ntopics:\n  - id: tp:3f9a2c-20260819-01\n    title: 存量卡\n"
        "    summary: s\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-19T14:00', '2026-08-19T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260819.md\n", encoding="utf-8")
    out = svc.migrate_legacy_pool(emp, material_base=shared)
    assert out["chats_files"] == 1 and out["topic_store"] is True
    assert (shared / "feishu_pool" / "chats" / "3f9a2c" / "20260819.md").is_file()
    assert not (chats / "20260819.md").exists()
    assert (shared / "feishu_pool" / "_topics.yaml").is_file()      # 旧候选文件迁移+改名
    cards = tc._load_candidates(shared)
    assert cards and cards[0]["title"] == "存量卡" and cards[0]["status"] == "draft"
    # 幂等重跑：无残留可迁，不报错不覆盖
    out2 = svc.migrate_legacy_pool(emp, material_base=shared)
    assert out2["chats_files"] == 0 and out2["topic_store"] is False


# ══════════════════════════════════════════════════════════
# T-951b：模型用途别名解析（设置页建的模型可被 text/vision 链路命中）
# ══════════════════════════════════════════════════════════

def test_model_purpose_alias_resolution(tmp_path, monkeypatch):
    """get_model("text")：id 精确命中优先；无则按 name 别名回退（设置页建
    模型 name 填 text/vision 即绑定用途——否则自动 id 永远无法命中）。"""
    import sys
    backend = str(SG_ROOT / "workbench" / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from services import model_config as mc
    from services import user_store
    # 隔离 DB（_connect 默认读 user_store.DB_PATH 模块全局；避免污染真实 workbench.db）
    monkeypatch.setattr(user_store, "DB_PATH", tmp_path / "test_models.db")
    mc.create_model({"name": "minimax-m3", "base_url": "https://api.minimaxi.com",
                     "api_key": "sk-test", "model": "MiniMax-M3"})
    # ① id 精确查找（现有行为不变）
    assert mc.get_model("model-001")["model"] == "MiniMax-M3"
    assert mc.get_model("text") is None                    # 无别名时诚实 None
    # ② name 别名：新建 name=text 的模型 → get_model("text") 命中
    mc.create_model({"name": "text", "base_url": "https://api.minimaxi.com",
                     "api_key": "sk-test-2", "model": "MiniMax-M3"})
    got = mc.get_model("text")
    assert got is not None and got["model"] == "MiniMax-M3"
    # ③ id 优先于 name（若存在 id=text 行则精确命中不歧义）
    import sqlite3
    with sqlite3.connect(tmp_path / "test_models.db") as conn:
        conn.execute("UPDATE model_configs SET name='text' WHERE id='model-001'")
    assert mc.get_model("text")["model"] == "MiniMax-M3"   # id=text 优先


# ══════════════════════════════════════════════════════════
# T-951c：介入工作台多日窗口（跨天话题支持）
# ══════════════════════════════════════════════════════════

def _mk_two_day_jsonl(tmp_path):
    """两日 JSONL 事实源：18 日两条（跨零点话题起始）+ 19 日一条（延续）。"""
    from specflow.feishu_pool import chat_store as cs
    emp = tmp_path / ".specflow" / "u1"
    rows = {
        "20260818": [
            {"message_id": "om_d1", "position": "1", "sender_id": "ou_1",
             "sender_name": "张三", "ts": "2026-08-18T23:50:00", "msg_type": "text",
             "content": "导出权限今晚要定方案", "image_key": "", "reply_to": "",
             "mentions": [], "origin": "pull"},
            {"message_id": "om_d2", "position": "2", "sender_id": "ou_2",
             "sender_name": "李四", "ts": "2026-08-18T23:58:00", "msg_type": "text",
             "content": "按 corpCode 过滤", "image_key": "", "reply_to": "",
             "mentions": [], "origin": "pull"},
        ],
        "20260819": [
            {"message_id": "om_d3", "position": "3", "sender_id": "ou_1",
             "sender_name": "张三", "ts": "2026-08-19T00:05:00", "msg_type": "text",
             "content": "早上定稿 corpCode+groupLevel", "image_key": "", "reply_to": "",
             "mentions": [], "origin": "pull"},
        ],
    }
    for day, rws in rows.items():
        f = emp / "feishu_pool" / "chats" / "3f9a2c" / f"{day}.jsonl"
        cs.merge_chat_jsonl(f, rws)
        cs.rebuild_views(f)
    return emp


def test_draft_multi_day_window(tmp_path):
    """多日分段：msg_lines 跨日行号锚定 → window 用真实 ts 跨日表达 + days 字段。"""
    from unittest.mock import MagicMock
    emp = _mk_two_day_jsonl(tmp_path)
    llm = MagicMock()
    llm.chat.return_value = {"content":
        '{"topics": [{"title": "导出权限方案", "summary": "跨零点定稿",'
        ' "msg_lines": [1, 2, 3], "participants_count": 2}]}'}
    out = tc.draft_chat_segments(emp, llm, "3f9a2c",
                                 ["20260818", "20260819"])
    seg = out[0]
    assert seg["message_ids"] == ["om_d1", "om_d2", "om_d3"]
    assert seg["window"] == ["2026-08-18T23:50:00", "2026-08-19T00:05:00"]
    assert seg["days"] == ["20260818", "20260819"]
    assert seg["message_count"] == 3


def test_draft_multi_day_skips_missing(tmp_path):
    """窗口含无快照日：跳过不炸；全无快照诚实 FileNotFoundError。"""
    from unittest.mock import MagicMock
    emp = _mk_two_day_jsonl(tmp_path)
    llm = MagicMock()
    llm.chat.return_value = {"content": '{"topics": [{"title": "t", "summary": "s",'
                             ' "msg_lines": [1], "participants_count": 1}]}'}
    # 含一个无快照日（20260817）→ 跳过，仍能出段
    out = tc.draft_chat_segments(emp, llm, "3f9a2c",
                                 ["20260817", "20260818", "20260819"])
    assert out and out[0]["days"] == ["20260818", "20260819"]
    # 全无快照 → FileNotFoundError
    import pytest as _pytest
    with _pytest.raises(FileNotFoundError):
        tc.draft_chat_segments(emp, llm, "3f9a2c", ["20260801"])


def test_commit_multi_day_clears_window(tmp_path):
    """窗口提交：清理窗口内各日旧卡（跨天话题不残留单日旧卡）。"""
    emp = _mk_two_day_jsonl(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260818-01\n    title: 18日旧卡\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    status: draft\n    rev: 1\n"
        "    window: ['2026-08-18T10:00', '2026-08-18T11:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260818.md\n"
        "  - id: tp:3f9a2c-20260819-01\n    title: 19日旧卡\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    status: draft\n    rev: 1\n"
        "    window: ['2026-08-19T09:00', '2026-08-19T10:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260819.md\n", encoding="utf-8")
    out = tc.commit_drafts(emp, "3f9a2c", "20260818",
                           [{"title": "跨日新卡", "summary": "s",
                             "days": ["20260818", "20260819"],
                             "window": ["2026-08-18T23:50", "2026-08-19T00:05"],
                             "message_count": 3, "participants_count": 2,
                             "source": "chats/3f9a2c/20260818.md"}],
                           days=["20260818", "20260819"])
    assert out[0]["id"].startswith("tp:3f9a2c-20260818-")
    saved = tc._load_candidates(emp)
    by_id = {t["id"]: t for t in saved}
    assert by_id["tp:3f9a2c-20260818-01"]["status"] == "rejected"
    assert by_id["tp:3f9a2c-20260819-01"]["status"] == "rejected"  # 窗口内他日也清理
    assert by_id[out[0]["id"]]["status"] == "draft"


def test_regen_multi_day_topic(tmp_path):
    """跨日卡 regen：按 days 拼接窗口内容重提炼（不再只有首日）。"""
    from unittest.mock import MagicMock
    emp = _mk_two_day_jsonl(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260818-01\n    title: 跨日卡\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    status: draft\n    rev: 1\n"
        "    days: ['20260818', '20260819']\n"
        "    window: ['2026-08-18T23:50', '2026-08-19T00:05']\n"
        "    message_count: 3\n    participants_count: 2\n"
        "    source: chats/3f9a2c/20260818.md\n", encoding="utf-8")
    seen = {}

    def fake_chat(msgs):
        seen["content"] = msgs[0]["content"]
        return {"content": '{"topics": [{"title": "重提炼跨日", "summary": "新",'
                ' "msg_lines": [2], "participants_count": 1}]}'}

    llm = MagicMock()
    llm.chat.side_effect = fake_chat
    t = tc.regen_candidate(emp, llm, "tp:3f9a2c-20260818-01")
    # prompt 内容含两日消息（跨日拼接），非仅首日
    assert "早上定稿" in seen["content"]
    assert t["title"] == "重提炼跨日"


# ══════════════════════════════════════════════════════════
# T-952b：单群同步 + 图片按 key 直取 + chats 附 imgmap
# ══════════════════════════════════════════════════════════

def test_sync_all_single_chat(tmp_path):
    """chat_id 指定时只拉该群（docs/minutes 跳过）——介入工作台「更新本群」。"""
    emp = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(emp, {
        "chats": [{"chat_id": "oc_a"}, {"chat_id": "oc_b"}],
        "docs": [{"token": "tokA"}], "minutes_days": 30, "chat_days": 1})
    pulled = []

    def _fake(args, timeout=90):
        if args[:2] == ["im", "+chat-messages-list"]:
            cid = args[args.index("--chat-id") + 1]
            pulled.append(cid)
            return {"ok": True, "data": {"messages": pull_messages()}}
        if "docs" in args:
            raise AssertionError("单群模式不应拉 docs")
        if args[:2] == ["minutes", "+search"]:
            raise AssertionError("单群模式不应拉 minutes")
        return {"ok": True, "data": {}}

    with patch.object(svc, "_run_lark", side_effect=_fake), \
         patch.object(svc, "maybe_cluster_async"):
        out = svc.sync_all(emp, material_base=tmp_path / ".specflow",
                           chat_id="oc_a")
    assert pulled == ["oc_a"]                       # 只有 oc_a
    assert out["chats"] == 1 and out["docs"] == 0 and out["minutes"] == 0


def test_fetch_image_by_key_cached(tmp_path):
    """图片按 (message_id, media_key) 经 im 通道下载（CLI 落 cwd 临时名→读回删）；
    二次同 key 走缓存（T-955b：旧 docs --media-key 为臆断契约，实测不存在该 flag）。"""
    import os
    cwd_before = os.getcwd()
    os.chdir(tmp_path)                       # 隔离 CLI --output 相对路径落点
    try:
        calls = []
        emps = []

        def _fake(args, timeout=90, emp=""):
            calls.append(list(args))
            emps.append(emp)
            assert args[0] == "im" and args[1] == "+messages-resources-download"
            assert args[args.index("--message-id") + 1] == "om_img_001"
            assert args[args.index("--type") + 1] == "image"
            out = args[args.index("--output") + 1]
            Path(out).write_bytes(b"\x89PNG fake")
            return {"ok": True, "data": {"saved_path": out}}

        base = tmp_path / ".specflow"
        with patch.object(svc, "_run_lark", side_effect=_fake):
            r1 = svc.fetch_image_by_key(base, "om_img_001", "img_v3_test_1",
                                         emp="u1")
            r2 = svc.fetch_image_by_key(base, "om_img_001", "img_v3_test_1",
                                         emp="u1")
        assert r1["ok"] and r1["mime"] == "image/png"
        assert r2["ok"] and len(calls) == 1          # 二次缓存命中
        assert emps == ["u1"]                        # emp 透传身份隔离
        assert not list(tmp_path.glob("tmp-dl-*"))   # CLI 临时文件已清理
    finally:
        os.chdir(cwd_before)


def test_material_content_chats_attaches_imgmap(tmp_path):
    """material-content 对 chats 快照附 imgmap images（前端 key→caption 映射）。"""
    import json as _json
    from specflow.feishu_pool import chat_store as cs
    from feishu_cli_contract import POST_MESSAGE
    base = tmp_path / ".specflow"
    f = base / "feishu_pool" / "chats" / "3f9a2c" / "20260818.jsonl"
    cs.merge_chat_jsonl(f, [cs.normalize_pull_message(POST_MESSAGE)])
    cs.rebuild_views(f)
    out = svc.read_material_content(base, "chats/3f9a2c/20260818.md")
    assert out["ok"] and out["type"] == "chat"
    keys = {i["media_key"] for i in out["images"]}
    assert "img_v3_0214l_f94ffa17-8f78-4319-a049-c7a5bb5dc7fg" in keys


# ══════════════════════════════════════════════════════════
# T-952c：同步后自动转述 + 定时同步可配置
# ══════════════════════════════════════════════════════════

def test_sync_all_triggers_transcribe(tmp_path):
    """sync_all 尾部自动触发图片转述（vision 未配置时诚实跳过不报错）。"""
    emp = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(emp, {"chats": [], "minutes_days": 0, "chat_days": 1})
    calls = []
    with patch.object(svc, "_run_lark", return_value={"ok": True, "data": {}}), \
         patch.object(svc, "maybe_cluster_async"), \
         patch.object(svc, "maybe_transcribe_async",
                      side_effect=lambda base, material_base=None:
                          calls.append((base, material_base))):
        svc.sync_all(emp)
    assert calls == [(emp, emp)]                     # 转述与聚类同模式触发


def test_maybe_transcribe_skips_without_vision(tmp_path):
    """vision 模型未配置 → 跳过（不抛错、不调 LLM）——与聚类同模式。"""
    from services import model_config
    with patch.object(model_config, "get_model", return_value=None):
        out = svc._transcribe_once(tmp_path)         # 未配置：静默返回
    assert out is None


def test_maybe_transcribe_runs_with_vision(tmp_path):
    """vision 配置时：transcribe_images 被调用（材料区透传）。"""
    from services import model_config
    from specflow.feishu_pool import captions
    m = model_config.get_model  # 引用保底
    called = []
    with patch.object(model_config, "get_model",
                      return_value={"id": "vision", "model": "vm"}), \
         patch.object(svc, "LLMClient", create=True), \
         patch("agent.llm_client.LLMClient", create=True), \
         patch.object(captions, "transcribe_images",
                      side_effect=lambda base, llm_vision=None:
                          called.append(base)):
        svc._transcribe_once(tmp_path)
    assert called == [tmp_path]


# ══════════════════════════════════════════════════════════
# T-955：聊天文件下载（消息附件可打开）
# ══════════════════════════════════════════════════════════

def test_fetch_chat_file_cached(tmp_path):
    """文件按 message_id+file_key 下载（CLI 落 cwd 临时名→读回删）；二次走缓存。"""
    import os
    cwd_before = os.getcwd()
    os.chdir(tmp_path)                       # 隔离 CLI --output 相对路径落点
    try:
        calls = []
        emps = []

        def _fake(args, timeout=90, emp=""):
            calls.append(list(args))
            emps.append(emp)
            out = args[args.index("--output") + 1]
            Path(out).write_bytes(b"PK\x03\x04 xlsx-bytes")
            return {"ok": True, "data": {"path": out}}

        base = tmp_path / ".specflow"
        with patch.object(svc, "_run_lark", side_effect=_fake):
            r1 = svc.fetch_chat_file(base, "om_file_001",
                                     "file_v3_abc", "report.xlsx", emp="u1")
            r2 = svc.fetch_chat_file(base, "om_file_001",
                                     "file_v3_abc", "report.xlsx", emp="u1")
        assert r1["ok"] and r1["data"] == b"PK\x03\x04 xlsx-bytes"
        assert r2["ok"] and len(calls) == 1          # 二次缓存命中
        assert emps == ["u1"]                        # emp 透传身份隔离
        assert not list(tmp_path.glob("tmp-dl-*"))   # CLI 临时文件已清理
    finally:
        os.chdir(cwd_before)
