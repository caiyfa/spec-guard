"""feishu_watcher.py — 飞书事件监听托管器（飞书知识图谱二期 F1，T-917~T-919）。

架构：workbench 后端 startup 拉起（复刻 scheduler 进程内托管先例），
3 路 lark-cli event consume 子进程（IM bot / minutes user / vc user）。

单用户守卫（二期边界）：.lark-cli/{emp} × feishu_watch.yaml × token 有效，
恰好 1 人才启动（0 静默 / >1 告警不启动）；多用户编排三期再议。

子进程纪律（lark-event 契约）：
- stdin=PIPE 保活（unbounded run 下 stdin EOF 即优雅退出——stop 先关 stdin）
- stderr 阻塞等 `[event] ready event_key=` 就绪标记，再读 stdout
- 禁 kill -9（minutes/vc 退出时 OAPI 退订，强杀泄漏服务端订阅）
- 非零退出 → 指数退避重启；连续 5 次崩溃 → 停摆 ERROR 告警（不静默自愈）

事件→材料转化（D1）：事件只作触发器——节流合并后调一期 sync 服务重拉落池，
材料池格式与手动同步完全一致（单一代码路径）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

EVENT_KEYS = [
    ("im.message.receive_v1", "bot"),
    ("minutes.minute.generated_v1", "user"),
    ("vc.note.generated_v1", "user"),
]

THROTTLE_SECONDS = 300        # 5min 滑动窗口（测试可 patch）
BACKOFF_BASE = 1.0            # 指数退避基数（秒）
BACKOFF_MAX = 300.0
MAX_CONSEC_CRASH = 5
READY_TIMEOUT = 20            # stderr ready 等待上限（秒）


# ══════════════════════════════════════════════════════════
# 单用户守卫
# ══════════════════════════════════════════════════════════

def _token_valid(sg_root: Path, emp: str) -> bool:
    """lark-cli auth status（USERPROFILE 注入该用户配置目录），ready 即有效。"""
    env = dict(os.environ)
    env["USERPROFILE"] = str(Path(sg_root) / ".lark-cli" / emp)
    cmd = (["cmd", "/c", "lark-cli"] if sys.platform == "win32" else ["lark-cli"])
    try:
        proc = subprocess.run(
            cmd + ["auth", "status", "--format", "json"],
            capture_output=True, text=True, timeout=15, env=env,
            encoding="utf-8", errors="replace")
        return '"ready"' in (proc.stdout or "")
    except Exception:
        return False


def resolve_watch_user(sg_root: Path) -> str | None:
    """单用户守卫：恰好 1 个「watch 配置 + token 有效」用户 → emp_no；否则 None。"""
    root = Path(sg_root)
    lark_root = root / ".lark-cli"
    if not lark_root.is_dir():
        return None
    cands = []
    for d in sorted(lark_root.iterdir()):
        if not d.is_dir():
            continue
        if (root / ".specflow" / d.name / "feishu_watch.yaml").is_file():
            cands.append(d.name)
    valid = [e for e in cands if _token_valid(root, e)]
    if len(valid) > 1:
        log.warning("feishu_watcher: %d 个用户满足监听条件，二期单用户边界——不启动",
                    len(valid))
        return None
    return valid[0] if valid else None


# ══════════════════════════════════════════════════════════
# 托管器
# ══════════════════════════════════════════════════════════

class FeishuWatcher:
    def __init__(self, sg_root: Path):
        self.sg_root = Path(sg_root)
        self.emp: str | None = None
        self._procs: list = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._last_pull: dict[str, float] = {}

    # ── 生命周期 ──

    def start(self) -> bool:
        """启动监听（守卫不满足 → False 静默/告警）。"""
        self.emp = resolve_watch_user(self.sg_root)
        if not self.emp:
            return False
        self._stop.clear()
        self._catch_up()
        for key, identity in EVENT_KEYS:
            self._launch(key, identity)
        log.info("feishu_watcher 已启动（emp=%s，%d 路事件）", self.emp, len(EVENT_KEYS))
        return True

    def stop(self):
        """优雅停：先关 stdin（EOF 触发优雅退出），10s 超时再 terminate。禁 kill。"""
        self._stop.set()
        for proc in self._procs:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
        deadline = time.time() + 10
        for proc in self._procs:
            try:
                proc.wait(timeout=max(0.1, deadline - time.time()))
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _catch_up(self):
        """启动 catch-up：全量补拉一次（补离线窗口；幂等覆盖写）。"""
        try:
            from services.specflow import feishu_sync_service as svc
            svc.sync_all(self.sg_root / ".specflow" / self.emp)
        except Exception as e:
            log.warning("feishu_watcher catch-up 失败（不阻断监听）: %s", e)

    # ── 子进程托管 ──

    def _launch(self, event_key: str, identity: str):
        t = threading.Thread(target=self._supervise, args=(event_key, identity),
                             daemon=True, name=f"feishu-watch-{event_key}")
        t.start()
        self._threads.append(t)

    def _spawn(self, event_key: str, identity: str):
        """拉起 consume 子进程（USERPROFILE 注入该用户配置；stdin=PIPE 保活）。"""
        env = dict(os.environ)
        env["USERPROFILE"] = str(self.sg_root / ".lark-cli" / self.emp)
        cmd = (["cmd", "/c", "lark-cli"] if sys.platform == "win32" else ["lark-cli"])
        return subprocess.Popen(
            cmd + ["event", "consume", event_key, "--as", identity],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", env=env)

    def _supervise(self, event_key: str, identity: str):
        backoff = BACKOFF_BASE
        crashes = 0
        while not self._stop.is_set():
            try:
                proc = self._spawn(event_key, identity)
            except Exception as e:
                log.error("feishu_watcher %s 拉起失败: %s", event_key, e)
                return
            self._procs.append(proc)
            if not self._wait_ready(proc, event_key):
                proc.wait()
                crashes += 1
                if crashes >= MAX_CONSEC_CRASH:
                    log.error("feishu_watcher %s 连续崩溃 %d 次，停摆告警",
                              event_key, crashes)
                    return
                time.sleep(min(backoff, BACKOFF_MAX))
                backoff *= 2
                continue
            crashes = 0
            backoff = BACKOFF_BASE
            self._consume(proc, event_key)
            rc = proc.wait()
            if self._stop.is_set():
                break
            log.warning("feishu_watcher %s 退出 rc=%s，退避重启", event_key, rc)
            time.sleep(min(backoff, BACKOFF_MAX))
            backoff *= 2

    def _wait_ready(self, proc, event_key: str) -> bool:
        """阻塞读 stderr 至 [event] ready（超时 READY_TIMEOUT 判失败）。"""
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline and not self._stop.is_set():
            line = proc.stderr.readline()
            if f"[event] ready event_key={event_key}" in line:
                return True
            if line == "" and proc.poll() is not None:
                return False
        return False

    def _consume(self, proc, event_key: str):
        for line in proc.stdout:
            if self._stop.is_set():
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._on_event(event_key, ev)

    # ── 事件 → 节流 → 重拉 ──

    def _on_event(self, event_key: str, ev: dict):
        if event_key == "im.message.receive_v1":
            chat_id = ev.get("chat_id", "")
            if chat_id:
                self._throttled(f"chat:{chat_id}", kind="chat", chat_id=chat_id)
        elif event_key in ("minutes.minute.generated_v1", "vc.note.generated_v1"):
            token = ev.get("minute_token") or ev.get("note_token") or ""
            if token:
                self._throttled(f"minutes:{token}", kind="minutes", token=token)

    def _throttled(self, key: str, **pull_kw):
        now = time.time()
        if now - self._last_pull.get(key, 0) < THROTTLE_SECONDS:
            return
        self._last_pull[key] = now
        self._trigger_pull(**pull_kw)

    def _trigger_pull(self, kind: str, **kw):
        """重拉（复用一期 sync 服务，单一代码路径）。"""
        from services.specflow import feishu_sync_service as svc
        emp_base = self.sg_root / ".specflow" / self.emp
        try:
            if kind == "chat":
                svc.sync_chat(emp_base, kw["chat_id"],
                              datetime.now().strftime("%Y%m%d"))
            elif kind == "minutes":
                svc.sync_minutes(emp_base, days=3)
        except Exception as e:
            log.warning("feishu_watcher 重拉失败 %s: %s", kw, e)


# ══════════════════════════════════════════════════════════
# 模块级单例（main.py startup/shutdown 接线用）
# ══════════════════════════════════════════════════════════

_WATCHER: FeishuWatcher | None = None


def start_background(sg_root: Path) -> bool:
    """启动全局 watcher（幂等：已启动/守卫不满足则跳过）。"""
    global _WATCHER
    if _WATCHER is not None:
        return False
    w = FeishuWatcher(sg_root)
    if not w.start():
        return False
    _WATCHER = w
    return True


def stop_background():
    """停止全局 watcher（幂等）。"""
    global _WATCHER
    if _WATCHER is None:
        return
    try:
        _WATCHER.stop()
    finally:
        _WATCHER = None
