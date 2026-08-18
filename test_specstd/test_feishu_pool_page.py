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
    # T-939 补丁：file 必须是带目录前缀的相对路径（material-content 白名单 /
    # 前端 imgmapOfFile 推导都依赖；曾因裸文件名致详情弹层全部报非法路径）
    fm = {i["type"]: i for i in items}
    assert fm["feishu_doc"]["file"] == "docs/fd-tokA.md"
    assert fm["feishu_minutes"]["file"] == "minutes/fm-obcn1.json"
    assert fm["chat"]["file"].startswith("chats/")


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
    """群聊选择器数据源：全量仅拉 group（T-944：单聊不显示不再调 p2p）
    + data.chats 字段解析（实测）。"""
    types_seen: list = []

    def fake(args, timeout=90, emp=""):
        assert args[:2] == ["im", "+chat-list"]
        types_seen.append(args[args.index("--types") + 1])
        return {"ok": True, "data": {"chats": [
            {"chat_id": "oc_a", "name": "需求群", "chat_mode": "group"}]}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.list_my_chats()
    assert out["errors"] == []
    assert types_seen == ["group"]            # 不再拉 p2p（单聊不显示）
    assert out["items"][0] == {"chat_id": "oc_a", "name": "需求群",
                               "chat_mode": "group", "peer_open_id": ""}
    svc._chats_cache.clear()


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


# ══════════════════════════════════════════════════════════
# T-937：resolve_doc_link（链接/token → 文档标识）
# 实测定案：wiki +node-get 仅适用于 wiki 节点（普通云文档 404），
# docx 链接路径末段即 obj_token（本地解析零 CLI）。
# ══════════════════════════════════════════════════════════

_WIKI_URL = "https://fehorizon.feishu.cn/wiki/DLmdwrGg7i2caHkX9PtcFPa2nKh"


def test_resolve_doc_link_wiki_url():
    """wiki URL → wiki +node-get 解析 obj_token/title/owner（存 obj_token 非 node_token）。"""
    def fake(args, timeout=90):
        assert args[:2] == ["wiki", "+node-get"]
        assert _WIKI_URL in args
        return {"ok": True, "data": {
            "node_token": "DLmdwrGg7i2caHkX9PtcFPa2nKh",
            "obj_token": "HA5ldBzihoLR8bxi4eMcGcHWngg",
            "obj_type": "docx", "title": "总裁面-0810-迭代-ERD",
            "owner": "ou_owner1"}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.resolve_doc_link(_WIKI_URL)
    assert out["ok"] is True
    item = out["items"][0]
    assert item["token"] == "HA5ldBzihoLR8bxi4eMcGcHWngg"   # obj_token
    assert item["title"] == "总裁面-0810-迭代-ERD"
    assert item["doc_type"] == "docx"
    assert item["owner_open_id"] == "ou_owner1"
    assert item["url"] == _WIKI_URL


def test_resolve_doc_link_docx_url_local():
    """docx URL → 本地解析（零 CLI；?query 剥离）。"""
    calls: list = []
    with patch.object(svc, "_run_lark",
                      side_effect=lambda a, timeout=90: calls.append(a)):
        out = svc.resolve_doc_link(
            "https://fehorizon.feishu.cn/docx/NNSVdZKrBo3i09xG0BWcqSZNnzd?from=share")
    assert calls == []
    item = out["items"][0]
    assert item["token"] == "NNSVdZKrBo3i09xG0BWcqSZNnzd"
    assert item["url"].startswith("https://fehorizon.feishu.cn/docx/NNSV")


def test_resolve_doc_link_bare_token():
    """裸 token → 本地透传（兼容旧手填习惯；零 CLI）。"""
    with patch.object(svc, "_run_lark", side_effect=AssertionError("不应调 CLI")):
        out = svc.resolve_doc_link("FBxodQkaJoUicrxdk67cUkbhnwc")
    assert out["ok"] is True
    assert out["items"][0]["token"] == "FBxodQkaJoUicrxdk67cUkbhnwc"


def test_resolve_doc_link_rejects_non_doc():
    """minutes/base/非飞书域链接 → 明确错误（仅支持云文档 docx/wiki）。"""
    with patch.object(svc, "_run_lark", side_effect=AssertionError("不应调 CLI")):
        for bad in ["https://x.feishu.cn/minutes/obcn123",
                    "https://x.feishu.cn/base/b1?table=tb1",
                    "https://x.feishu.cn/sheets/s1",
                    "https://example.com/docx/tokX",
                    "带 空格 的输入"]:
            out = svc.resolve_doc_link(bad)
            assert out["ok"] is False, bad
            assert "云文档" in out["error"], bad


def test_resolve_doc_link_empty_input():
    out = svc.resolve_doc_link("  ")
    assert out["ok"] is False


def test_resolve_doc_link_cli_error():
    """node-get 失败（无权限/不存在）→ 错误诚实呈现。"""
    with patch.object(svc, "_run_lark",
                      side_effect=ValueError("lark-cli 调用失败: not found")):
        out = svc.resolve_doc_link(_WIKI_URL)
    assert out["ok"] is False
    assert "not found" in out["error"]


# ══════════════════════════════════════════════════════════
# T-937：list_my_chats TTL 缓存（弹层秒开配套；同工号 60s 内不重复调 CLI）
# ══════════════════════════════════════════════════════════


def test_list_my_chats_cache_hit():
    """同工号 TTL 内两次调用只打一次 CLI，结果一致。"""
    calls: list = []

    def fake(args, timeout=90, emp=""):
        calls.append(args)
        return {"ok": True, "data": {"chats": [
            {"chat_id": "oc_a", "name": "需求群", "chat_mode": "group"}]}}
    try:
        with patch.object(svc, "_run_lark", side_effect=fake), \
             patch.object(svc, "_chats_cache_key", return_value="u1"):
            out1 = svc.list_my_chats()
            out2 = svc.list_my_chats()
        assert len(calls) == 1                     # 全量单次（group only）
        assert out1 == out2 and out1["items"][0]["chat_id"] == "oc_a"
    finally:
        svc._chats_cache.clear()


def test_list_my_chats_cache_no_cache_errors():
    """失败结果不缓存——重试即时生效。"""
    seq = [ValueError("认证未就绪"),
           {"ok": True, "data": {"chats": [{"chat_id": "oc_a"}]}}]
    it = iter(seq)

    def fake(args, timeout=90, emp=""):
        v = next(it)
        if isinstance(v, Exception):
            raise v          # mock side_effect 仅对异常类自动 raise，实例需手动
        return v
    try:
        with patch.object(svc, "_run_lark", side_effect=fake), \
             patch.object(svc, "_chats_cache_key", return_value="u1"):
            out1 = svc.list_my_chats()   # 失败
            out2 = svc.list_my_chats()   # 重试成功
        assert out1["errors"] and out2["items"]
    finally:
        svc._chats_cache.clear()


def test_list_my_chats_cache_ttl_expiry(monkeypatch):
    """TTL 过期后重新调 CLI；不同工号不共享缓存。"""
    calls: list = []

    def fake(args, timeout=90, emp=""):
        calls.append(args)
        return {"ok": True, "data": {"chats": [{"chat_id": "oc_a"}]}}
    clock = {"t": 1000.0}
    monkeypatch.setattr(svc, "_now", lambda: clock["t"])
    try:
        with patch.object(svc, "_run_lark", side_effect=fake), \
             patch.object(svc, "_chats_cache_key", return_value="u1"):
            svc.list_my_chats()
            clock["t"] += svc._CHATS_CACHE_TTL + 1   # 越过 TTL
            svc.list_my_chats()
        assert len(calls) == 2                    # 两轮全量各一次（group only）
    finally:
        svc._chats_cache.clear()


# ══════════════════════════════════════════════════════════
# T-938：stale-while-revalidate + emp 身份隔离（后台预热配套）
# ══════════════════════════════════════════════════════════


def test_list_my_chats_stale_returns_old_and_triggers_refresh(monkeypatch):
    """缓存过期：立即返回旧值（stale=True）+ 触发后台刷新，不等 CLI。"""
    svc._chats_cache.clear()
    monkeypatch.setattr(svc, "_chats_cache_key", lambda: "u1")
    clock = {"t": 1000.0}
    monkeypatch.setattr(svc, "_now", lambda: clock["t"])
    try:
        with patch.object(svc, "_run_lark",
                          side_effect=lambda a, timeout=90, emp="":
                          {"ok": True, "data": {"items": [
                              {"chat_id": "oc_old", "name": "旧群",
                               "chat_mode": "group"}]}}):
            fresh = svc.list_my_chats()
        assert fresh["items"][0]["chat_id"] == "oc_old"
        assert not fresh.get("stale")
        clock["t"] += svc._CHATS_CACHE_TTL + 1            # 过期
        with patch.object(svc, "_refresh_chats_async") as ref:
            stale = svc.list_my_chats()
        assert ref.call_count == 1
        assert stale["items"][0]["chat_id"] == "oc_old"  # 旧值立即返回
        assert stale.get("stale") is True
    finally:
        svc._chats_cache.clear()


def test_list_my_chats_explicit_emp_separate_keys():
    """显式 emp 参数：独立缓存 key，各自调 CLI（后台预热 job 传入）。"""
    calls: list = []

    def fake(args, timeout=90, emp=""):
        calls.append(emp)
        return {"ok": True, "data": {"chats": [
            {"chat_id": f"oc_{emp}_{calls.count(emp)}", "name": "",
             "chat_mode": "group"}]}}
    try:
        with patch.object(svc, "_run_lark", side_effect=fake):
            svc.list_my_chats(emp="uA")
            svc.list_my_chats(emp="uB")
            svc.list_my_chats(emp="uA")    # 命中缓存
        assert calls == ["uA", "uB"]           # 每人全量一次（group only）
        assert svc._chats_cache["uA"][1]["items"][0]["chat_id"].startswith("oc_uA_")
    finally:
        svc._chats_cache.clear()


def test_list_my_chats_quick_limit():
    """T-944：limit 快速预览——单次 --page-size N（group only，无 page-all），
    不写缓存（预览不污染全量缓存），全量随后台/第二次调用补齐。"""
    calls: list = []

    def fake(args, timeout=90, emp=""):
        calls.append(args)
        assert "--page-all" not in args       # 快速路径不翻页
        assert args[args.index("--page-size") + 1] == "10"
        return {"ok": True, "data": {"chats": [
            {"chat_id": f"oc_{i}", "name": f"群{i}", "chat_mode": "group"}
            for i in range(3)]}}
    try:
        with patch.object(svc, "_run_lark", side_effect=fake), \
             patch.object(svc, "_chats_cache_key", return_value="u1"):
            out = svc.list_my_chats(limit=10)
        assert len(calls) == 1 and len(out["items"]) == 3
        assert "u1" not in svc._chats_cache   # 预览不写缓存
    finally:
        svc._chats_cache.clear()


# ══════════════════════════════════════════════════════════
# T-945：同步后自动聚类生成候选话题（链路闭环：落池→聚类→复核→图谱）
# ══════════════════════════════════════════════════════════


def test_cluster_once_no_text_model(monkeypatch):
    """未配置 text 模型 → 诚实跳过（不抛、不调聚类），与 vision 转述同模式。"""
    called = []
    monkeypatch.setattr("services.model_config.get_model", lambda mid: None)
    monkeypatch.setattr("specflow.feishu_pool.topic_cluster.cluster_chat_snapshots",
                        lambda *a, **k: called.append(a) or [])
    svc._cluster_once(Path("x"))
    assert called == []


def test_cluster_once_with_text_model(monkeypatch):
    """已配置 text 模型 → cluster_chat_snapshots 被调（LLM 客户端注入）。"""
    called = {}

    class _FakeLLM:
        def __init__(self, model_id="text"):
            called["model_id"] = model_id

    monkeypatch.setattr("services.model_config.get_model", lambda mid: {"model_id": "text"})
    monkeypatch.setattr("agent.llm_client.LLMClient", _FakeLLM)
    monkeypatch.setattr(
        "specflow.feishu_pool.topic_cluster.cluster_chat_snapshots",
        lambda base, llm, days=None: called.setdefault("args", (base, llm)) or [])
    svc._cluster_once(Path("/tmp/emp"))
    assert called["model_id"] == "text"
    assert called["args"][0] == Path("/tmp/emp")


def test_cluster_once_error_swallowed(monkeypatch):
    """聚类抛异常不外溢（异步线程内失败仅记日志，不阻断后续）。"""
    monkeypatch.setattr("services.model_config.get_model", lambda mid: {"model_id": "text"})
    monkeypatch.setattr("agent.llm_client.LLMClient", lambda model_id="text": None)
    monkeypatch.setattr(
        "specflow.feishu_pool.topic_cluster.cluster_chat_snapshots",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("LLM 超时")))
    svc._cluster_once(Path("x"))    # 不应抛


def test_sync_all_triggers_cluster(monkeypatch, tmp_path):
    """sync_all 完成后触发异步聚类（链路闭环的接线点）。"""
    emp = tmp_path / ".specflow" / "u1"
    svc.save_watch_config(emp, {"chats": [], "docs": [], "minutes_days": 0,
                                "chat_days": 0, "users": []})
    triggered = []
    monkeypatch.setattr(svc, "maybe_cluster_async",
                        lambda base: triggered.append(base))
    svc.sync_all(emp)
    assert triggered == [emp]


def test_lark_env_emp_injection():
    """_run_lark emp 身份隔离：USERPROFILE → SG_ROOT/.lark-cli/{emp}
    （watcher _spawn/_token_valid 同一约定）；空 emp → 不注入（现状兼容）。"""
    from specflow.feishu_pool import lark_cli
    env = lark_cli._lark_env("90000001")
    assert env["USERPROFILE"].replace("\\", "/").endswith(".lark-cli/90000001")
    assert lark_cli._lark_env("") == {}


# ══════════════════════════════════════════════════════════
# T-939：材料原文读取（详情弹层）+ 图片字节代理（内嵌展示）
# ══════════════════════════════════════════════════════════


def test_read_material_content_doc_with_imgmap(tmp_path):
    """doc：原文 + imgmap 条目列表（前端 [图片#N] 内嵌与描述编辑共用）。"""
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        emp, "tokA", "# 标题\n\n正文 [图片#1]\n",
        imgmap={"图片#1": {"media_key": "mk1", "caption": "架构图",
                           "caption_by": "vision_llm", "status": "done"}})
    out = svc.read_material_content(emp, "docs/fd-tokA.md")
    assert out["ok"] is True
    assert out["type"] == "feishu_doc"
    assert "# 标题" in out["content"]
    assert out["images"] == [{"placeholder": "图片#1", "media_key": "mk1",
                              "caption": "架构图", "caption_by": "vision_llm",
                              "status": "done"}]


def test_read_material_content_minutes_readable(tmp_path):
    """minutes：可读化文本（title/summary）+ raw JSON 附带（折叠展示）。"""
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_minutes_snapshot(
        emp, "obcn1", {"minutes": [
            {"title": "评审会", "artifacts": {"summary": "讨论导出"}}]})
    out = svc.read_material_content(emp, "minutes/fm-obcn1.json")
    assert out["ok"] is True and out["type"] == "feishu_minutes"
    assert "评审会" in out["content"] and "讨论导出" in out["content"]
    assert "minutes" in out["raw"]


def test_read_material_content_chat(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    saved = pool_store.save_chat_snapshot(
        emp, "oc_a", "20260818", "[10:00] 张三: hi\n")
    out = svc.read_material_content(emp, saved["file"])
    assert out["ok"] is True and out["type"] == "chat"
    assert "张三: hi" in out["content"]
    assert out["images"] == []


def test_read_material_content_rejects_traversal(tmp_path):
    """路径白名单 + 防穿越（私有区文件不外泄）。"""
    for bad in ["../evil.md", "other/x.md", "docs/../../evil.md",
                "docs/fd-x.exe", "", "docs/"]:
        out = svc.read_material_content(tmp_path, bad)
        assert out["ok"] is False, bad


def test_read_material_content_not_found(tmp_path):
    out = svc.read_material_content(tmp_path / ".specflow" / "u1",
                                    "docs/fd-none.md")
    assert out["ok"] is False


_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16     # PNG 魔数


def test_fetch_material_image_with_cache(tmp_path, monkeypatch):
    """图片代理：下载 → 磁盘缓存 → 二次命中零下载。"""
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        emp, "tokA", "x",
        imgmap={"图片#1": {"media_key": "mk1", "caption": "",
                           "caption_by": "none", "status": "pending"}})
    calls: list = []

    def fake_dl(media_key):
        calls.append(media_key)
        return _PNG
    monkeypatch.setattr(svc, "_download_image", fake_dl)
    r1 = svc.fetch_material_image(emp, "docs/fd-tokA.imgmap.json", "图片#1")
    assert r1["ok"] is True and r1["data"] == _PNG
    assert r1["mime"] == "image/png"
    r2 = svc.fetch_material_image(emp, "docs/fd-tokA.imgmap.json", "图片#1")
    assert calls == ["mk1"]                  # 二次走缓存
    assert r2["data"] == _PNG


def test_fetch_material_image_rejects(tmp_path):
    """无 media_key（占位符扫描产物）/未知占位符 → 明确错误。"""
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        emp, "tokA", "x",
        imgmap={"图片#1": {"media_key": "mk1", "caption": "",
                           "caption_by": "none", "status": "pending"},
                "图片#2": {"media_key": "", "caption": "",
                           "caption_by": "none", "status": "pending"}})
    out = svc.fetch_material_image(emp, "docs/fd-tokA.imgmap.json", "图片#2")
    assert out["ok"] is False and "media_key" in out["error"]
    out2 = svc.fetch_material_image(emp, "docs/fd-tokA.imgmap.json", "图片#9")
    assert out2["ok"] is False
    out3 = svc.fetch_material_image(emp, "../evil", "图片#1")
    assert out3["ok"] is False


# ══════════════════════════════════════════════════════════
# T-940：owner/meta 落盘（材料按监听用户切换）+ 飞书原文直链
# ══════════════════════════════════════════════════════════


def test_sync_minutes_single_owner_meta(tmp_path):
    """单 owner 检索：meta 落 owner_open_id；source_url 取 meta_data.app_link（实测结构）。"""
    def fake(args, timeout=90, emp=""):
        if args[:2] == ["minutes", "+search"]:
            return {"ok": True, "data": {"items": [
                {"token": "obcnX",
                 "meta_data": {"app_link": "https://x.feishu.cn/minutes/obcnX"}}]}}
        assert args[:2] == ["minutes", "+detail"]
        return {"ok": True, "data": {"minutes": [{"title": "T"}]}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        svc.sync_minutes(tmp_path, days=3, owner_ids=["ou_zhang"])
    meta = json.loads((tmp_path / "feishu_pool" / "minutes" / "fm-obcnX.meta.json")
                      .read_text(encoding="utf-8"))
    assert meta["owner_open_id"] == "ou_zhang"
    assert meta["source_url"] == "https://x.feishu.cn/minutes/obcnX"


def test_sync_user_docs_owner_meta(tmp_path):
    """按用户搜文档：落盘 meta 带 owner（材料归属 + 列表直链）。"""
    def fake(args, timeout=90, emp=""):
        assert args[:2] == ["docs", "+search"]
        return {"ok": True, "data": {"results": [
            {"title_highlighted": "张三方案",
             "result_meta": {"owner_id": "ou_zhang", "token": "tokD",
                             "url": "https://x.feishu.cn/docx/tokD",
                             "owner_name": "张三"}}]}}

    def fake_fetch(args, timeout=90, emp=""):
        assert args[:2] == ["docs", "+fetch"]
        return {"ok": True, "data": {"content": "# 方案"}}
    seq = [fake, fake_fetch]
    it = iter(seq)
    with patch.object(svc, "_run_lark",
                      side_effect=lambda a, timeout=90, emp="": next(it)(a, timeout, emp)):
        out = svc._sync_user_docs(tmp_path, "ou_zhang", "方案")
    assert out["docs"] == 1
    meta = json.loads((tmp_path / "feishu_pool" / "docs" / "fd-tokD.meta.json")
                      .read_text(encoding="utf-8"))
    assert meta["owner_open_id"] == "ou_zhang"
    assert meta["owner_name"] == "张三"
    assert meta["source_url"] == "https://x.feishu.cn/docx/tokD"


def test_list_pool_materials_meta_fields(tmp_path):
    """list 返 source_url/owner_*（meta sidecar）；无 meta 存量诚实降级空串；
    minutes glob 不得把 fm-*.meta.json 当材料。"""
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        emp, "tokA", "# T\n",
        meta={"owner_open_id": "ou_zhang", "owner_name": "张三",
              "source_url": "https://x.feishu.cn/docx/tokA", "title": "PRD"})
    pool_store.save_minutes_snapshot(
        emp, "obcnY", {"minutes": [{"title": "旧会"}]},
        meta={"owner_open_id": "ou_zhang", "source_url": "u2"})
    # 存量无 meta
    pool_store.save_minutes_snapshot(emp, "obcnOld", {"minutes": []})
    items = svc.list_pool_materials(emp)
    doc = next(i for i in items if i["type"] == "feishu_doc")
    assert doc["source_url"] == "https://x.feishu.cn/docx/tokA"
    assert doc["owner_open_id"] == "ou_zhang"
    assert doc["owner_name"] == "张三"
    fms = [i for i in items if i["type"] == "feishu_minutes"]
    assert len(fms) == 2                    # meta.json 未被当材料
    fm_y = next(i for i in fms if "obcnY" in i["id"])
    assert fm_y["owner_open_id"] == "ou_zhang"
    fm_old = next(i for i in fms if "obcnOld" in i["id"])
    assert fm_old["source_url"] == "" and fm_old["owner_open_id"] == ""


# ══════════════════════════════════════════════════════════
# T-941：文档名全局搜索（与按用户检索解耦）+ 授权错误人话化
# ══════════════════════════════════════════════════════════


def test_search_docs_global():
    """按文档名全局搜索：不过滤 owner，结果带产出人标注。"""
    def fake(args, timeout=90, emp=""):
        assert args[:2] == ["docs", "+search"]
        assert "ERD" in args
        return {"ok": True, "data": {"results": [
            {"title_highlighted": "<em>ERD</em>评审",
             "result_meta": {"owner_id": "ou_a", "token": "tokA",
                             "url": "uA", "doc_types": "DOCX",
                             "owner_name": "张三"}},
            {"title_highlighted": "他人文档",
             "result_meta": {"owner_id": "ou_b", "token": "tokB",
                             "url": "uB", "doc_types": "DOCX",
                             "owner_name": "李四"}}]}}
    with patch.object(svc, "_run_lark", side_effect=fake):
        out = svc.search_docs("ERD")
    assert [i["token"] for i in out["items"]] == ["tokA", "tokB"]  # 不过滤
    assert out["items"][0]["title"] == "ERD评审"
    assert out["items"][0]["owner_name"] == "张三"


def test_search_docs_empty_query_shortcircuit():
    out = svc.search_docs("  ")
    assert out == {"items": [], "errors": []}


def test_missing_scope_error_friendly():
    """授权类错误 → 纯人话一句（不拼 lark-cli 技术原文，用户实锄只要提示）；其余原样。"""
    raw = ('lark-cli 调用失败: {"error": {"subtype": "missing_scope", '
           '"message": "missing required scope(s): contactuser:search"}}')
    msg = svc._friendly_lark_error(ValueError(raw))
    assert msg == "飞书授权缺少权限——请点击弹层顶部「重新授权」补全后重试"
    unbound = svc._friendly_lark_error(ValueError("飞书认证未就绪：请先执行 lark-cli auth login"))
    assert msg != unbound and "绑定飞书" in unbound
    assert svc._friendly_lark_error(ValueError("网络超时")) == "网络超时"


def test_search_users_missing_scope_friendly():
    """选择器 errors 通道走人话包装（截图实锤：缺 contactuser:search）。"""
    with patch.object(svc, "_run_lark",
                      side_effect=ValueError(
                          '{"subtype": "missing_scope", '
                          '"missing required scope(s): contactuser:search"}')):
        out = svc.search_users("张三")
    assert out["items"] == []
    assert out["errors"] == ["飞书授权缺少权限——请点击弹层顶部「重新授权」补全后重试"]
