"""services.session_event_bus — 会话级事件总线（T-1021 运行中重连续传）。

run 事件不再桥接到发起连接的私有 queue，而是发布到会话频道：
  - fan-out：同会话多订阅者（发起连接 + attach 恢复的连接/第二标签页）同时收
  - 回放缓冲：per-session 缓冲保留当前 run 的全部事件，attach 时全量回放
    （前端配合截断到 baseline_len 基线后重放，天然去重；run_started 时缓冲清空）
  - 生命周期：run_started 重置频道与基线；done/error 广播后频道标记空闲，
    超过 IDLE_TTL 后由后续 run_started/attach 懒清理（防长期运行泄漏）

线程模型：所有方法只允许在 asyncio 主 loop 线程调用（runtime 工作线程的事件
由调用方用 loop.call_soon_threadsafe 包装后进入 publish）；内部不加锁。
缓冲超长保护：MAX_BUFFER 截断头部——回放不完整属极端场景（超长 run），
最终一致由前端 done 后全量 getSession 兜底。
"""

import asyncio
import time
from collections import deque

# 回放分批：单帧 replay_batch 携带的事件数上限（长 run 全量回放拆多帧）
REPLAY_BATCH = 100

# 单频道事件缓冲上限（超长 run 防内存爆，截断头部）
MAX_BUFFER = 50000

# run 结束后频道保留时长（秒）——给晚到的 attach 留 done 事件，超时懒清理
IDLE_TTL_SECONDS = 600


class Subscriber:
    """单个订阅者：事件队列 + 创建时的 event loop（跨 loop 投递防护用）。"""

    __slots__ = ("sid", "queue", "closed", "loop")

    def __init__(self, sid: str):
        self.sid = sid
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None  # 无运行 loop 的上下文（理论不发生，防御）


class _Channel:
    """会话频道：当前 run 的事件缓冲 + 订阅者表 + 生命周期标记。"""

    __slots__ = ("seq", "buffer", "baseline_len", "subscribers", "done", "done_at")

    def __init__(self, baseline_len: int):
        self.seq = 0
        self.buffer: deque = deque(maxlen=MAX_BUFFER)  # (seq, event)
        self.baseline_len = baseline_len
        self.subscribers: dict[int, Subscriber] = {}
        self.done = False
        self.done_at: float | None = None


class SessionEventBus:
    """会话级事件总线（模块级单例使用；进程内、不跨 worker——与 workers=1 约束一致）。"""

    def __init__(self):
        self._channels: dict[str, _Channel] = {}
        self._sub_seq = 0

    # ── 生命周期 ──

    def run_started(self, sid: str, baseline_len: int) -> None:
        """run 启动：重置频道（清缓冲、记基线）。发起方在 attach_live 之前调用。"""
        self._gc()
        self._channels[sid] = _Channel(baseline_len)

    def publish(self, sid: str, event: dict) -> None:
        """发布事件到会话频道：入缓冲 + fan-out 全部订阅者。

        done/error 事件标记频道空闲（attach 中的连接收到后自行退出订阅循环）。
        频道不存在（run 未登记/已清理）时静默忽略——防御性，正常时序不发生。

        跨 event loop 投递：订阅者可能挂在不同 loop（TestClient 每个 WS 连接
        独立 portal loop；生产单 loop 不触发）——直接 put_nowait 会从其它线程
        set future（未定义行为，实测终态事件可静默丢失），必须经
        call_soon_threadsafe 唤醒订阅方 loop。单订阅者投递异常不中断 fan-out。
        """
        ch = self._channels.get(sid)
        if ch is None:
            return
        ch.seq += 1
        ch.buffer.append((ch.seq, event))
        if event.get("type") in ("done", "error"):
            ch.done = True
            ch.done_at = time.monotonic()
        try:
            cur_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            cur_loop = None
        for sub in list(ch.subscribers.values()):
            if sub.closed:
                continue
            try:
                if sub.loop is not None and sub.loop is not cur_loop:
                    sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
                else:
                    sub.queue.put_nowait(event)
            except Exception:
                pass  # 单订阅者投递异常不中断 fan-out

    # ── 订阅 ──

    def attach(self, sid: str) -> tuple[Subscriber, list[dict], dict] | None:
        """订阅会话频道并回放当前 run 的已缓冲事件（attach 恢复连接用）。

        返回 (sub, replay_events, meta)；频道不存在（无 run 记录）返回 None。
        replay 为缓冲浅拷贝；订阅后新 publish 的事件进 sub.queue。
        """
        self._gc()
        ch = self._channels.get(sid)
        if ch is None:
            return None
        sub = self._attach_channel(ch)
        replay = [event for _seq, event in ch.buffer]
        meta = {"baseline_len": ch.baseline_len, "seq": ch.seq, "done": ch.done}
        return sub, replay, meta

    def attach_live(self, sid: str) -> Subscriber | None:
        """只订阅后续事件、不回放（发起 run 的连接用——它从 run 开始就在收）。

        注意：必须在 runtime.events.subscribe 注册之前调用，否则注册到订阅
        之间的事件会丢（发布进缓冲但不进本订阅者队列）。
        """
        ch = self._channels.get(sid)
        if ch is None:
            return None
        return self._attach_channel(ch)

    def detach(self, sid: str, sub: Subscriber) -> None:
        """退订（连接断开/用户切走）。频道与缓冲保留——run 可能仍在执行。"""
        sub.closed = True
        ch = self._channels.get(sid)
        if ch is not None:
            ch.subscribers.pop(id(sub), None)

    # ── 查询 ──

    def snapshot(self, sid: str) -> dict:
        """频道状态快照（REST getSession 附加字段用）。"""
        ch = self._channels.get(sid)
        if ch is None:
            return {"exists": False, "baseline_len": 0, "seq": 0, "done": True}
        return {"exists": True, "baseline_len": ch.baseline_len,
                "seq": ch.seq, "done": ch.done}

    # ── 内部 ──

    def _attach_channel(self, ch: _Channel) -> Subscriber:
        self._sub_seq += 1
        sub = Subscriber(f"{self._sub_seq}")
        ch.subscribers[id(sub)] = sub
        return sub

    def _gc(self) -> None:
        """懒清理：删除已结束且超时的频道（run_started/attach 时触发）。"""
        now = time.monotonic()
        stale = [sid for sid, ch in self._channels.items()
                 if ch.done and ch.done_at is not None
                 and now - ch.done_at > IDLE_TTL_SECONDS]
        for sid in stale:
            self._channels.pop(sid, None)
