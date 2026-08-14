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
            "chats: []\ndocs: []\n", encoding="utf-8")


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
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines))
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
    def test_throttle_merges_same_chat(self, tmp_path):
        _mk_user(tmp_path, "u1")
        events = [{"chat_id": "oc_a", "event_id": "e1"},
                  {"chat_id": "oc_a", "event_id": "e2"},
                  {"chat_id": "oc_b", "event_id": "e3"}]
        pulled = []
        with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
             patch.object(fw, "_token_valid", return_value=True), \
             patch.object(fw.FeishuWatcher, "_spawn",
                          new=lambda self, k, i: _FakeProc(events)), \
             patch.object(fw.FeishuWatcher, "_trigger_pull",
                          new=lambda self, **kw: pulled.append(kw)), \
             patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
             patch.object(fw, "THROTTLE_SECONDS", 60):
            w = fw.FeishuWatcher(tmp_path)
            w.start()
            time.sleep(0.3)
            w.stop()
        chats = [p for p in pulled if p.get("kind") == "chat"]
        # oc_a 两事件节流合并为 1 次重拉，oc_b 1 次
        assert len(chats) == 2

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
    from services.specflow import feishu_sync_service as svc
    from services.specflow import feishu_review_service as rev
    from specflow.feishu_pool import link_suggest as ls
    from specflow.feishu_pool import topic_cluster as tc

    _mk_user(tmp_path, "u1")
    events = [{"chat_id": "oc_a", "event_id": "e1"},
              {"chat_id": "oc_a", "event_id": "e2"}]   # 同群两事件 → 节流一次重拉

    def _fake_lark(args, timeout=90):
        return {"ok": True, "data": {"items": [
            {"create_time_ms": "1691498400000", "sender_name": "张三",
             "msg_type": "text", "text": "作废会话后级联删除人员"}]}}

    with patch.object(fw, "EVENT_KEYS", _ONE_KEY), \
         patch.object(fw, "_token_valid", return_value=True), \
         patch.object(fw.FeishuWatcher, "_spawn",
                      new=lambda self, k, i: _FakeProc(events)), \
         patch.object(fw.FeishuWatcher, "_catch_up", new=lambda self: None), \
         patch.object(fw, "THROTTLE_SECONDS", 60), \
         patch.object(svc, "_run_lark", side_effect=_fake_lark):
        w = fw.FeishuWatcher(tmp_path)
        w.start()
        time.sleep(0.3)
        w.stop()

    # 事件触发重拉落池（真实 sync_chat 被调）
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
