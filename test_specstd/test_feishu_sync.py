"""test_feishu_sync.py — 飞书材料池拉取入库单测（飞书知识图谱一期 T4）。

覆盖：
- watch 配置读写（feishu_watch.yaml = 显式授权载体）
- sync_doc：docs +fetch 产物落池 + imgmap 初始 pending
- sync_chat：消息列表渲染 [HH:MM] 行格式落池
- sync_all：单通道失败记 errors 不中断（诚实呈现）
注：lark-cli 真实返回结构以实测为准微调，测试锁定落盘契约（mock _run_lark）。
"""

from pathlib import Path
from unittest.mock import patch

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
TEST_DIR = Path(__file__).resolve().parent

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
    assert loaded == {"chats": [], "docs": [], "users": [],
                      "minutes_days": 30, "chat_days": 7,
                      "chat_sync_minutes": 0}   # T-952：定时同步默认关

def test_watch_users_roundtrip(tmp_path):
    """watch v2：users 维度读写（open_id/name/scopes）。"""
    base = tmp_path / ".specflow" / "u1"
    cfg = {"chats": [{"chat_id": "oc_abc"}],
           "docs": [{"token": "FBxod"}],
           "users": [{"open_id": "ou_a", "name": "张三",
                      "scopes": ["group_sender", "minutes"]}],
           "minutes_days": 30, "chat_days": 7}
    svc.save_watch_config(base, cfg)
    loaded = svc.load_watch_config(base)
    assert loaded["users"][0]["open_id"] == "ou_a"
    assert loaded["users"][0]["scopes"] == ["group_sender", "minutes"]

def test_watch_users_legacy_config_default(tmp_path):
    """旧配置（无 users 字段）加载自动补齐 users: []。"""
    base = tmp_path / ".specflow" / "u1"
    base.mkdir(parents=True)
    (base / "feishu_watch.yaml").write_text(
        "chats: []\ndocs: []\nminutes_days: 30\nchat_days: 7\n", encoding="utf-8")
    loaded = svc.load_watch_config(base)
    assert loaded["users"] == []

def test_watch_users_scopes_filtered_and_dedup(tmp_path):
    """scopes 非法值丢弃；空 open_id 丢弃；按 open_id 去重（后写覆盖）。"""
    base = tmp_path / ".specflow" / "u1"
    cfg = {"users": [{"open_id": "ou_a", "name": "张三",
                      "scopes": ["group_sender", "bogus"]},
                     {"open_id": "", "name": "空", "scopes": ["docs"]},
                     {"open_id": "ou_a", "name": "张三2", "scopes": ["docs"]}]}
    saved = svc.save_watch_config(base, cfg)
    assert len(saved["users"]) == 1
    assert saved["users"][0]["name"] == "张三2"
    assert saved["users"][0]["scopes"] == ["docs"]

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
    """T-948：真实 CLI 契约（data.messages/字符串时间/嵌套 sender）→
    JSONL 事实源 + md 派生视图。"""
    from test_specstd.feishu_cli_contract import pull_messages
    base = tmp_path / ".specflow" / "u1"
    payload = {"ok": True, "data": {"messages": pull_messages()}}
    with patch.object(svc, "_run_lark", return_value=payload):
        rec = svc.sync_chat(base, chat_id="oc_8786450d43fc1c453beb1c147d947c03",
                            day="20260818")
    assert rec["messages"] == 2 and rec["file"] == f"chats/{rec['chat_sha8']}/20260818.md"
    md = (base / "feishu_pool" / "chats" / rec["chat_sha8"]
          / "20260818.md").read_text(encoding="utf-8")
    assert "[09:15] 蔡云飞: [图片#1]" in md
    assert "[14:07] 蔡云飞: @贺文君" in md
    # JSONL 事实源存在且行数一致（md 是派生视图）
    jsonl = base / "feishu_pool" / "chats" / rec["chat_sha8"] / "20260818.jsonl"
    assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 2
    # 图片 imgmap 同步生成（转述链路接手）
    assert (base / "feishu_pool" / "chats" / rec["chat_sha8"]
            / "20260818.imgmap.json").is_file()

def test_sync_chat_day_range_args(tmp_path):
    """T-948：按天拉取——--start/--end 圈定当日、--order asc、--page-all。"""
    base = tmp_path / ".specflow" / "u1"
    calls = []

    def _fake(args, timeout=90):
        calls.append(args)
        return {"ok": True, "data": {"messages": []}}

    with patch.object(svc, "_run_lark", side_effect=_fake):
        svc.sync_chat(base, chat_id="oc_abc", day="20260818")
    args = calls[0]
    assert "--start" in args and args[args.index("--start") + 1].startswith("2026-08-18")
    assert "--end" in args and args[args.index("--end") + 1].startswith("2026-08-18T23:59")
    assert args[args.index("--order") + 1] == "asc"
    assert "--page-all" in args

def test_sync_chat_empty_writes_nothing(tmp_path):
    """T-948 诚实性：0 条消息不写空文件，messages=0（消灭 0 字节假成功）。"""
    base = tmp_path / ".specflow" / "u1"
    with patch.object(svc, "_run_lark",
                      return_value={"ok": True, "data": {"messages": []}}):
        rec = svc.sync_chat(base, chat_id="oc_abc", day="20260818")
    assert rec["messages"] == 0 and rec["file"] is None
    assert not (base / "feishu_pool" / "chats").exists()

def test_sync_all_chat_days_window(tmp_path):
    """T-948：sync_all 按群拉 chat_days 天窗口（历史补拉能力）+ days_pulled 反馈。"""
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [{"chat_id": "oc_abc"}],
                                 "minutes_days": 0, "chat_days": 3})
    starts = []

    def _fake(args, timeout=90):
        if args[:2] == ["im", "+chat-messages-list"]:
            starts.append(args[args.index("--start") + 1][:10].replace("-", ""))
            return {"ok": True, "data": {"messages": []}}
        return {"ok": True, "data": {}}

    with patch.object(svc, "_run_lark", side_effect=_fake), \
         patch.object(svc, "maybe_cluster_async"):
        out = svc.sync_all(base)
    today = _dt.now().strftime("%Y%m%d")
    assert out["days_pulled"] == 3
    assert starts == [today,                      # 今天、昨天、前天（升序）
                      (_dt.now() - _td(days=1)).strftime("%Y%m%d"),
                      (_dt.now() - _td(days=2)).strftime("%Y%m%d")]
    assert out["chats"] == 0 and out["chats_empty"] == 3   # 3 天全空，诚实计数

def test_sync_all_chats_counts_messages(tmp_path):
    """T-948：有消息的天计入 chats，空天计入 chats_empty。"""
    from test_specstd.feishu_cli_contract import pull_messages
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [{"chat_id": "oc_abc"}],
                                 "minutes_days": 0, "chat_days": 1})

    def _fake(args, timeout=90):
        if args[:2] == ["im", "+chat-messages-list"]:
            return {"ok": True, "data": {"messages": pull_messages()}}
        return {"ok": True, "data": {}}

    with patch.object(svc, "_run_lark", side_effect=_fake), \
         patch.object(svc, "maybe_cluster_async"):
        out = svc.sync_all(base)
    assert out["chats"] == 1 and out["chats_empty"] == 0

def test_sync_all_collects_errors(tmp_path):
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [{"chat_id": "oc_abc"}],
                                 "docs": [{"token": "FBxod"}],
                                 "minutes_days": 0, "chat_days": 1})

    def _fake(args, timeout=90):
        if "docs" in args:
            raise ValueError("无权限，请点击链接申请权限")
        return {"ok": True, "data": {"messages": []}}

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

def test_sync_minutes_owner_ids_passthrough(tmp_path):
    """sync_minutes：owner_ids 透传 --owner-ids（None → me 保持现状）。

    T-949：minutes 同步附带 perm 元数据拉取（member-list/get-setting 插在
    search 与 detail 之间），断言改为按调用类型过滤而非位置索引。
    """
    base = tmp_path / ".specflow" / "u1"
    calls = []

    def fake(args, timeout=90):
        calls.append(args)
        if args[:2] == ["minutes", "+search"]:
            return {"ok": True, "data": {"items": [
                {"minute_token": "obcn1", "url": "u"}]}}
        return {"ok": True, "data": {"summary": "s"}}

    with patch.object(svc, "_run_lark", side_effect=fake):
        svc.sync_minutes(base, days=30, owner_ids=["ou_a", "ou_b"])
        svc.sync_minutes(base, days=30)
    searches = [c for c in calls if c[:2] == ["minutes", "+search"]]
    assert searches[0][searches[0].index("--owner-ids") + 1] == "ou_a,ou_b"
    assert searches[1][searches[1].index("--owner-ids") + 1] == "me"

def test_sync_user_materials_minutes_branch(tmp_path):
    """sync_user_materials：scopes 含 minutes 的用户按其 open_id 拉妙记落池。"""
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [], "docs": [],
                                 "users": [{"open_id": "ou_a", "name": "张三",
                                            "scopes": ["minutes"]}],
                                 "minutes_days": 30, "chat_days": 7})
    calls = []

    def fake(args, timeout=90):
        calls.append(args)
        if args[:2] == ["minutes", "+search"]:
            return {"ok": True, "data": {"items": [
                {"minute_token": "obcn1", "url": "u"}]}}
        return {"ok": True, "data": {"summary": "s"}}

    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.sync_user_materials(base)
    assert out["minutes"] == 1 and out["errors"] == []
    assert any("--owner-ids" in c and "ou_a" in c for c in calls)
    assert (base / "feishu_pool" / "minutes" / "fm-obcn1.json").is_file()

def test_sync_user_docs_owner_filter(tmp_path):
    """用户文档轮询：docs +search 结果按 owner_id 应用侧过滤后落池。"""
    base = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(base, {"chats": [], "docs": [],
                                 "users": [{"open_id": "ou_a", "name": "张三",
                                            "scopes": ["docs"]}],
                                 "minutes_days": 30, "chat_days": 7})

    def fake(args, timeout=90):
        if args[:2] == ["docs", "+search"]:
            return {"ok": True, "data": {"results": [
                {"title_highlighted": "张三的文档",
                 "result_meta": {"owner_id": "ou_a", "token": "tokA",
                                 "url": "uA", "doc_types": "DOCX"}},
                {"title_highlighted": "别人的文档",
                 "result_meta": {"owner_id": "ou_b", "token": "tokB",
                                 "url": "uB", "doc_types": "DOCX"}}]}}
        return {"ok": True, "data": {"content": "# 文档\n"}}

    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.sync_user_materials(base)
    assert out["docs"] == 1 and out["errors"] == []
    assert (base / "feishu_pool" / "docs" / "fd-tokA.md").is_file()
    assert not (base / "feishu_pool" / "docs" / "fd-tokB.md").exists()

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
            from test_specstd.feishu_cli_contract import pull_messages
            msgs = pull_messages()
            msgs[0]["content"] = "作废会话后级联删除人员"
            return {"ok": True, "data": {"messages": msgs}}
        return {"ok": True, "data": {"messages": []}}

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
