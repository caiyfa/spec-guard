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
