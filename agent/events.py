"""agent.events — 事件总线。

复用 runner broadcast 通道的事件类型：
  - assistant: LLM 返回消息
  - tool_call + tool_result: 工具调用与结果
  - state: 状态变更（turn/max_turns/熔断）
"""

from typing import Callable


class EventBus:
    """轻量事件总线（同步，支持多订阅者）。"""

    def __init__(self):
        self._subscribers: list[Callable] = []

    def subscribe(self, callback: Callable):
        """订阅事件。callback(event: dict) -> None。"""
        self._subscribers.append(callback)

    def emit(self, event_type: str, **data):
        """发射事件。"""
        event = {"type": event_type, **data}
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:
                pass  # 订阅者异常不影响主循环

    def unsubscribe(self, callback: Callable):
        """取消订阅。"""
        self._subscribers = [cb for cb in self._subscribers if cb is not callback]
