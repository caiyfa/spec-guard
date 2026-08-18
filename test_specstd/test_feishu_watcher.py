"""test_feishu_watcher.py — 事件监听托管器单测（二期 T-917/T-918/T-919）。

覆盖：
- 单用户守卫三态：0 静默 / 1 启动 / >1 告警不启动
- 子进程节流合并（同窗同 key 一次重拉）
- 优雅停先关 stdin；崩溃退避重启
- start/stop_background 幂等
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
for p in (str(SG_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from services.specflow import feishu_watcher as fw  # noqa: E402


def _mk_user(root: Path, emp: str, with_watch=True):
    (root / ".lark-cli" / emp).mkdir(parents=True)
    (root / ".lark-cli" / emp / "config.json").write_text("{}", encoding="utf-8")
    if with_watch:
        sf = root / ".specflow" / emp
        sf.mkdir(parents=True)
        (sf / "feishu_watch.yaml").write_text(
            "chats:\n  - chat_id: oc_a\ndocs: []\n", encoding="utf-8")


class TestSingleUserGuard:
    def test_zero_user_skip(self, tmp_path):
        assert fw.resolve_watch_user(tmp_path) is None

    def test_one_user_ok(self, tmp_path):
        _mk_user(tmp_path, "u1")
        with patch.object(fw, "_token_valid", return_value=True):
            assert fw.resolve_watch_user(tmp_path) == "u1"

    def test_multi_user_warn_skip(self, tmp_path):
        _mk_user(tmp_path, "u1")
        _mk_user(tmp_path, "u2")
        with patch.object(fw, "_token_valid", return_value=True):
            assert fw.resolve_watch_user(tmp_path) is None  # 二期边界：告警不启动


# ══════════════════════════════════════════════════════════
# T-918：子进程托管核心（节流/优雅停/崩溃退避）
# ══════════════════════════════════════════════════════════

class _FakeProc:
    """假 consume 子进程：stderr 给 ready 行，stdout 给预设 NDJSON。"""

    def __init__(self, lines, ready_key="im.message.receive_v1"):
        import io
        self.stderr = io.StringIO(f"[event] ready event_key={ready_key}\n")
        self.stdout = io.StringIO(
            "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in lines))
        self.stdin = MagicMock()
        self.returncode = None

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return None

    def terminate(self):
        self.returncode = 0


_ONE_KEY = [("im.message.receive_v1", "bot")]


class TestConsumeLoop:
    def test_im_event_direct_write(self, tmp_path):
        """T-925：IM 事件直写（二期节流重拉语义已被直写替代）。"""
        _mk_user(tmp_path, "u1")
        events = [{"chat_id": "oc_a", "event_id": "e1", "sender_id": "ou_x1",
                   "create_time": "1691498400000", "message_type": "text",
                   "content": "直写一"},
                  {"chat_id": "oc_a", "event_id": "e2", "sender_id": "ou_x1",
                   "create_time": "1691498460000", "message_type": "text",
                   "content": "直写二"},
                  {"chat_id": "oc_a", "event_id": "e1", "sender_id": "ou_x1",
                   "create_time": "1691498400000", "message_type": "text",
                   "content": "直写一"}]   # 重复 event_id → 不双写
        from specflow.feishu_pool import pool_store
        with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
             patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "_spawn",
                          new=lambda self, k, i: _FakeProc(events)), \
             patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
             patch.object(fw.FeishuWatcher, "_schedule_doc_poll", new=lambda self: None), \
             patch.object(fw.FeishuWatcher, "_schedule_chat_proofread", new=lambda self: None), \
             patch.object(fw.FeishuWatcher, "_schedule_user_materials", new=lambda self: None), \
             patch.object(fw.FeishuWatcher, "_schedule_chats_warmup", new=lambda self: None), \
             patch.object(pool_store, "_resolve_sender", return_value="张三"):
            w = fw.FeishuWatcher(tmp_path)
            w.start()
            time.sleep(0.3)
            w.stop()
        emp = tmp_path / ".specflow" / "u1"
        chat_file = next((emp / "feishu_pool" / "chats").rglob("*.md"))
        text = chat_file.read_text(encoding="utf-8")
        assert "直写一" in text and "直写二" in text
        assert text.count("直写一") == 1            # 去重生效

    def test_graceful_stop_closes_stdin_first(self, tmp_path):
        _mk_user(tmp_path, "u1")
        holder = {}
        def _spawn(self, k, i):
            holder["proc"] = _FakeProc([])
            return holder["proc"]
        with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
             patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "_spawn", new=_spawn), \
             patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None):
            w = fw.FeishuWatcher(tmp_path)
            w.start()
            time.sleep(0.2)
            w.stop()
        holder["proc"].stdin.close.assert_called()   # 先关 stdin（EOF 优雅退出）

    def test_crash_restart_with_backoff(self, tmp_path):
        _mk_user(tmp_path, "u1")
        calls = []

        class CrashProc(_FakeProc):
            def wait(self, timeout=None):
                return 1                        # 非零退出 = 崩溃

        def _spawn(self, k, i):
            calls.append(1)
            return CrashProc([])

        with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
             patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "_spawn", new=_spawn), \
             patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
             patch.object(fw, "BACKOFF_BASE", 0.05):
            w = fw.FeishuWatcher(tmp_path)
            w.start()
            time.sleep(0.4)
            w.stop()
        assert len(calls) >= 2                  # 崩溃后重启过


# ══════════════════════════════════════════════════════════
# T-919：模块级单例（main.py startup/shutdown 接线）
# ══════════════════════════════════════════════════════════

class TestBackgroundSingleton:
    def teardown_method(self):
        fw.stop_background()

    def test_start_skip_without_user(self, tmp_path):
        assert fw.start_background(tmp_path) is False   # 无配置用户静默跳过
        assert fw._REGISTRY is not None                  # T-924：注册表常驻（空）
        assert fw._REGISTRY.status()["count"] == 0

    def test_start_stop_idempotent(self, tmp_path):
        _mk_user(tmp_path, "u1")
        with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
             patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "_spawn",
                          new=lambda self, k, i: _FakeProc([])), \
             patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None):
            assert fw.start_background(tmp_path) is True
            assert fw.start_background(tmp_path) is False   # 幂等：重复启动跳过
            fw.stop_background()
            fw.stop_background()                            # 幂等：重复停止安全
            assert fw._REGISTRY is None


# ══════════════════════════════════════════════════════════
# T-923：e2e 贯通（事件 NDJSON → 节流 → 重拉落池 → 聚类 → 建议入队）
# ══════════════════════════════════════════════════════════

def test_e2e_event_to_review_queue(tmp_path):
    from services.specflow import feishu_review_service as rev

    from specflow.feishu_pool import link_suggest as ls
    from specflow.feishu_pool import topic_cluster as tc

    _mk_user(tmp_path, "u1")
    events = [{"chat_id": "oc_a", "event_id": "e1", "sender_id": "ou_x1",
               "create_time": "1691498400000", "message_type": "text",
               "content": "作废会话后级联删除人员"},
              {"chat_id": "oc_a", "event_id": "e2", "sender_id": "ou_x1",
               "create_time": "1691498460000", "message_type": "text",
               "content": "下午继续讨论权限过滤"}]

    from specflow.feishu_pool import pool_store
    with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
         patch.object(fw, "_token_valid", return_value=True), \
         patch.object(fw.FeishuWatcher, "_spawn",
                      new=lambda self, k, i: _FakeProc(events)), \
         patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_doc_poll", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_chat_proofread", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_user_materials", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_chats_warmup", new=lambda self: None), \
         patch.object(pool_store, "_resolve_sender", return_value="张三"):
        w = fw.FeishuWatcher(tmp_path)
        w.start()
        time.sleep(0.3)
        w.stop()

    # 事件直写落池（T-925 直写路径）
    emp = tmp_path / ".specflow" / "u1"
    chat_files = list((emp / "feishu_pool" / "chats").rglob("*.md"))
    assert len(chat_files) == 1
    assert "级联删除" in chat_files[0].read_text(encoding="utf-8")

    # 落池 → 聚类 → 建议入复核队列（mock LLM）
    import json as _json
    llm = MagicMock()
    ts = chat_files[0].read_text(encoding="utf-8").split("]")[0] + "]"
    llm.chat.return_value = {"content": _json.dumps({"topics": [{
        "title": "级联删除", "summary": "作废会话后级联删除人员",
        "msg_range": [ts, ts], "participants_count": 1}]}, ensure_ascii=False)}
    produced = tc.cluster_chat_snapshots(emp, llm)
    assert len(produced) == 1

    anchors = {"FR-012": MagicMock(title="作废级联删除", module="inventory",
                                   feature="grid-placement", ac_ids=[])}
    llm2 = MagicMock()
    llm2.chat.return_value = {"content": _json.dumps({"links": [{
        "fr_id": "FR-012", "confidence": 0.88,
        "evidence": "作废会话后级联删除人员"}]}, ensure_ascii=False)}
    sug = ls.suggest_links_for_material(
        produced[0]["id"], produced[0]["summary"], anchors, llm2,
        workspace_root=tmp_path / "ws")
    assert len(sug) == 1
    rev.enqueue_suggestions(emp, "u1", sug)
    queue = rev.list_queue(emp)
    assert queue[0]["status"] == "pending" and queue[0]["dst"] == "FR-012"


def test_direct_write_drops_unauthorized_chat(tmp_path):
    """未授权 chat 的消息不直写（D5）。"""
    _mk_user(tmp_path, "u1")   # fixture 授权 oc_a
    events = [{"chat_id": "oc_other", "event_id": "e1", "sender_id": "ou_x1",
               "create_time": "1691498400000", "message_type": "text",
               "content": "未授权群消息"}]
    with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
         patch.object(fw, "_token_valid", return_value=True), \
         patch.object(fw.FeishuWatcher, "_spawn",
                      new=lambda self, k, i: _FakeProc(events)), \
         patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_doc_poll", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_chat_proofread", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_user_materials", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_chats_warmup", new=lambda self: None):
        w = fw.FeishuWatcher(tmp_path)
        w.start()
        time.sleep(0.3)
        w.stop()
    emp = tmp_path / ".specflow" / "u1"
    assert list((emp / "feishu_pool" / "chats").rglob("*.md")) == []


def test_direct_write_group_sender_filter(tmp_path):
    """group_sender 过滤：命中 sender 直写 / 未命中丢弃（D4，仅直写）。"""
    root = tmp_path
    (root / ".lark-cli" / "u1").mkdir(parents=True)
    (root / ".lark-cli" / "u1" / "config.json").write_text("{}", encoding="utf-8")
    sf = root / ".specflow" / "u1"
    sf.mkdir(parents=True)
    (sf / "feishu_watch.yaml").write_text(
        "chats:\n  - chat_id: oc_a\ndocs: []\n"
        "users:\n  - open_id: ou_x1\n    name: 张三\n"
        "    scopes: [group_sender]\n", encoding="utf-8")
    events = [{"chat_id": "oc_a", "event_id": "e1", "sender_id": "ou_x1",
               "create_time": "1691498400000", "message_type": "text",
               "content": "关注人的消息"},
              {"chat_id": "oc_a", "event_id": "e2", "sender_id": "ou_y",
               "create_time": "1691498460000", "message_type": "text",
               "content": "其他人的消息"}]
    from specflow.feishu_pool import pool_store
    with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
         patch.object(fw, "_token_valid", return_value=True), \
         patch.object(fw.FeishuWatcher, "_spawn",
                      new=lambda self, k, i: _FakeProc(events)), \
         patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_doc_poll", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_chat_proofread", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_user_materials", new=lambda self: None), \
         patch.object(fw.FeishuWatcher, "_schedule_chats_warmup", new=lambda self: None), \
         patch.object(pool_store, "_resolve_sender", return_value="张三"):
        w = fw.FeishuWatcher(tmp_path)
        w.start()
        time.sleep(0.3)
        w.stop()
    chat_files = list((sf / "feishu_pool" / "chats").rglob("*.md"))
    assert len(chat_files) == 1
    content = chat_files[0].read_text(encoding="utf-8")
    assert "关注人的消息" in content
    assert "其他人的消息" not in content


def test_user_materials_job_calls_sync(tmp_path):
    """模块级 job：委托 sync_user_materials（APScheduler 可序列化铁律）。"""
    emp = tmp_path / ".specflow" / "u1"
    emp.mkdir(parents=True)
    called = []
    with patch("services.specflow.feishu_sync_service.sync_user_materials",
               side_effect=lambda b: called.append(b)
               or {"minutes": 0, "docs": 0, "errors": []}):
        fw.user_materials_job(str(emp))
    assert called == [emp]


def test_chats_warmup_job_calls_list():
    """T-938 模块级预热 job：委托 list_my_chats(emp=...)（身份隔离 + 可序列化铁律）。"""
    called = []
    with patch("services.specflow.feishu_sync_service.list_my_chats",
               side_effect=lambda emp="": called.append(emp)
               or {"items": [], "errors": []}):
        fw.chats_warmup_job("u1")
    assert called == ["u1"]


def test_chats_warmup_job_tolerates_errors():
    """预热失败不抛（job 内 log.warning，不炸 scheduler 线程）。"""
    with patch("services.specflow.feishu_sync_service.list_my_chats",
               return_value={"items": [], "errors": ["认证未就绪"]}):
        fw.chats_warmup_job("u1")   # 不应抛异常


# ══════════════════════════════════════════════════════════
# T-924：WatcherRegistry 多用户编排
# ══════════════════════════════════════════════════════════

class TestRegistry:
    def teardown_method(self):
        fw.stop_background()

    def test_multi_users_all_started(self, tmp_path):
        _mk_user(tmp_path, "u1")
        _mk_user(tmp_path, "u2")
        with patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "start", return_value=True):
            reg = fw.WatcherRegistry(tmp_path)
            started = reg.start_all()
        assert sorted(started) == ["u1", "u2"]        # 二期 >1 告警不启动已退役
        assert reg.status()["count"] == 2

    def test_soft_cap_rejects_overflow(self, tmp_path):
        for i in range(5):
            _mk_user(tmp_path, f"u{i:02d}")
        with patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "start", return_value=True), \
             patch.object(fw, "MAX_WATCHERS", 3):
            reg = fw.WatcherRegistry(tmp_path)
            started = reg.start_all()
        assert len(started) == 3                      # 软上限拒绝超出
        assert reg.status()["count"] == 3

    def test_start_stop_user_idempotent(self, tmp_path):
        _mk_user(tmp_path, "u1")
        with patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "start", return_value=True), \
             patch.object(fw.FeishuWatcher, "stop", return_value=None):
            reg = fw.WatcherRegistry(tmp_path)
            assert reg.start_user("u1") is True
            assert reg.start_user("u1") is False      # 幂等：已在跑跳过
            assert reg.stop_user("u1") is True
            assert reg.stop_user("u1") is False      # 幂等：未在跑跳过

    def test_status_persisted(self, tmp_path):
        _mk_user(tmp_path, "u1")
        with patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "start", return_value=True):
            reg = fw.WatcherRegistry(tmp_path)
            reg.start_all()
        ws = tmp_path / "ws"
        st_path = reg.persist_status(ws)
        import json as _j
        st = _j.loads(st_path.read_text(encoding="utf-8"))
        assert st["watchers"][0]["emp"] == "u1"
        assert "started_at" in st["watchers"][0]
        fw.stop_background()


# ══════════════════════════════════════════════════════════
# T-928：三期 e2e 贯通（多用户事件→直写→聚类 continues→图谱 evolves→确认 suggest_ivs）
# ══════════════════════════════════════════════════════════

def test_p3_e2e_pipeline(tmp_path):
    from services.specflow import feishu_review_service as rev

    from graph_index.builder import build_index
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    from specflow.feishu_pool import facts, pool_store
    from specflow.feishu_pool import link_suggest as ls
    from specflow.feishu_pool import topic_cluster as tc

    # 多用户注册表启动（u1/u2 均拉起）
    _mk_user(tmp_path, "u1")
    _mk_user(tmp_path, "u2")
    with patch.object(fw, "_token_valid", return_value=True), \
         patch.object(fw.FeishuWatcher, "start", return_value=True):
        reg = fw.WatcherRegistry(tmp_path)
        started = reg.start_all()
    assert sorted(started) == ["u1", "u2"]

    # u1 事件直写落池（模拟 watcher 直写路径）
    emp = tmp_path / ".specflow" / "u1"
    events = [
        {"chat_id": "oc_a", "event_id": "e1", "sender_id": "ou_x",
         "create_time": "1691498400000", "message_type": "text",
         "content": "作废会话后级联删除人员"},
        {"chat_id": "oc_a", "event_id": "e2", "sender_id": "ou_x",
         "create_time": "1691498460000", "message_type": "text",
         "content": "下午继续讨论权限过滤"},
    ]
    with patch.object(pool_store, "_resolve_sender", return_value="张三"):
        w = fw.FeishuWatcher(tmp_path)
        w.emp = "u1"
        for ev in events:
            w._direct_write_chat(ev)
    chat_files = list((emp / "feishu_pool" / "chats").rglob("*.md"))
    assert len(chat_files) == 1

    # 预置昨日话题 → 今日聚类 LLM 判延续（continues）
    import json as _json
    cand = emp / "feishu_pool" / "_candidate_topics.yaml"
    cand.write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:9b9e9d-20260813-01\n    title: 级联删除\n"
        "    summary: 作废级联删除人员\n    chat_sha8: 9b9e9d\n"
        "    window: ['2026-08-13T14:00', '2026-08-13T14:30']\n"
        "    message_count: 2\n    participants_count: 1\n"
        "    source: chats/9b9e9d/20260813.md\n", encoding="utf-8")
    ts = chat_files[0].read_text(encoding="utf-8").split("]")[0] + "]"
    llm = MagicMock()
    llm.chat.return_value = {"content": _json.dumps({"topics": [{
        "title": "级联删除续谈", "summary": "作废会话后级联删除人员",
        "continues": "tp:9b9e9d-20260813-01",
        "msg_range": [ts, ts], "participants_count": 1}]}, ensure_ascii=False)}
    produced = tc.cluster_chat_snapshots(emp, llm)
    assert produced[0].get("continues") == "tp:9b9e9d-20260813-01"

    # 复核确认 → 共享区（话题含 continues 提升）+ suggest_ivs
    ws = tmp_path / "ws"
    (ws / ".specguard").mkdir(parents=True)
    (ws / "specs" / "inventory" / "grid-placement").mkdir(parents=True)
    (ws / "specs" / "inventory" / "grid-placement" / "spec.md").write_text(
        "### FR-012: 作废级联删除\n作废会话后级联删除人员。\n", encoding="utf-8")
    llm2 = MagicMock()
    llm2.chat.return_value = {"content": _json.dumps({"links": [{
        "fr_id": "FR-012", "confidence": 0.9,
        "evidence": "作废会话后级联删除人员"}]}, ensure_ascii=False)}
    anchors = {"FR-012": MagicMock(title="作废级联删除", module="inventory",
                                   feature="grid-placement", ac_ids=[])}
    # 旧话题先确认入共享区（演进链两端均须在图中）
    facts.upsert_topic(ws, {"id": "tp:9b9e9d-20260813-01", "title": "级联删除",
                            "summary": "作废级联删除人员", "chat_sha8": "9b9e9d",
                            "window": ["2026-08-13T14:00", "2026-08-13T14:30"],
                            "message_count": 2, "participants_count": 1,
                            "source": "chats/9b9e9d/20260813.md"})
    sug = ls.suggest_links_for_material(
        produced[0]["id"], produced[0]["summary"], anchors, llm2, workspace_root=ws)
    rev.enqueue_suggestions(emp, "u1", sug)
    with patch.object(rev, "_find_active_ivs_for_fr",
                      return_value=[{"iv_id": "IV-001", "title": "导出面试"}]):
        out = rev.confirm_suggestions(emp, ws, "u1",
                                      [(produced[0]["id"], "FR-012")])
    assert out["confirmed"] == 1
    assert out["suggest_ivs"][0]["iv_id"] == "IV-001"

    # 图谱：evolves 边 + mentions 边同图
    build_index(ws, index_path(ws), scenarios_root=tmp_path / "scenarios",
                sg_root=tmp_path)
    with GraphStore(index_path(ws)) as store:
        evolves = store.list_edges("evolves")
        assert any(e["src"] == produced[0]["id"]
                   and e["dst"] == "tp:9b9e9d-20260813-01" for e in evolves)
        mentions = store.list_edges("mentions")
        assert any(e["src"] == produced[0]["id"] and e["dst"] == "FR-012"
                   for e in mentions)
