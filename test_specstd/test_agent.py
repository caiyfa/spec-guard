"""agent 包测试（薄 harness + CLI）。

验证：
1. llm_client mock 模式 + 缓存 + 计量
2. session JSONL 持久化 + 恢复
3. events 事件总线
4. runtime 核心循环 + max_turns 熔断 + 工具执行 + 会话持久化
5. build_system_prompt 构建
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.llm_client import LLMClient
from agent.session import SessionManager
from agent.events import EventBus
from agent.runtime import AgentRuntime, build_system_prompt


# ══════════════════════════════════════════════════════════
# Mock LLM（可控制响应序列）
# ══════════════════════════════════════════════════════════

class MockLLM:
    """可配置响应序列的 mock LLM。"""

    def __init__(self, responses: list[dict] = None):
        self.responses = responses or []
        self._call_count = 0
        self._total_tokens = 0

    @property
    def is_mock(self):
        return True

    def chat(self, messages, tools=None, temperature=0.7):
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
        else:
            resp = {"role": "assistant", "content": "（默认停止）"}
        self._call_count += 1
        self._total_tokens += 15
        return resp, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def set_metrics_file(self, path):
        pass

    def get_stats(self):
        return {"cache_hits": 0, "cache_misses": 1, "total_tokens": self._total_tokens,
                "is_mock": True, "model": "mock"}


# ══════════════════════════════════════════════════════════
# LLM Client
# ══════════════════════════════════════════════════════════

class TestLLMClient:
    @pytest.fixture(autouse=True)
    def _isolate_db_config(self, monkeypatch):
        """隔离真实 DB 的 model_config，避免环境数据污染 mock 测试（离线可靠）。"""
        monkeypatch.setattr(
            LLMClient, "_load_db_config",
            staticmethod(lambda model_id="": {}),
        )

    def test_mock_mode(self):
        """mock 模式返回模拟响应。"""
        llm = LLMClient(base_url="")
        assert llm.is_mock is True
        msg, usage = llm.chat([{"role": "user", "content": "test"}])
        assert "MOCK" in msg["content"]
        assert usage["total_tokens"] == 0

    def test_cache_detection(self):
        """system prompt 缓存检测。"""
        llm = LLMClient(base_url="")
        messages = [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "hi"}]
        llm.chat(messages)
        assert llm._cache_misses == 1
        assert llm._cache_hits == 0
        # 相同 system prompt → cache hit
        llm.chat(messages)
        assert llm._cache_hits == 1

    def test_metrics_recording(self, tmp_path):
        """计量数据落 JSONL。"""
        llm = LLMClient(base_url="")
        metrics_file = tmp_path / "metrics.jsonl"
        llm.set_metrics_file(metrics_file)
        llm.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        assert metrics_file.is_file()
        lines = metrics_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert "timestamp" in data
        assert data["model"] == "gpt-4o"

    def test_stats(self):
        """统计信息。"""
        llm = LLMClient(base_url="")
        stats = llm.get_stats()
        assert stats["is_mock"] is True
        assert "cache_hits" in stats
        assert "total_tokens" in stats


# ══════════════════════════════════════════════════════════
# Session
# ══════════════════════════════════════════════════════════

class TestSession:
    def test_save_load(self, tmp_path):
        """保存和加载会话。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        sm.save(sid, messages)
        loaded = sm.load(sid)
        assert loaded is not None
        assert len(loaded) == 3
        assert loaded[1]["content"] == "hello"

    def test_load_nonexistent(self, tmp_path):
        """加载不存在的会话返回 None。"""
        sm = SessionManager(tmp_path / "sessions")
        assert sm.load("nonexistent") is None

    def test_list_sessions(self, tmp_path):
        """列出会话。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "x"}])
        sessions = sm.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid

    def test_resume(self, tmp_path):
        """恢复会话。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "test"}])
        loaded = sm.resume(sid)
        assert loaded is not None
        assert loaded[0]["content"] == "test"

    def test_metrics_line_skipped(self, tmp_path):
        """metrics 行在 load 时被跳过。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "x"}], metrics={"total_tokens": 100})
        loaded = sm.load(sid)
        assert len(loaded) == 1  # metrics 行被跳过


# ══════════════════════════════════════════════════════════
# Events
# ══════════════════════════════════════════════════════════

class TestEvents:
    def test_subscribe_emit(self):
        """订阅和发布事件。"""
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))
        bus.emit("test", data="hello")
        assert len(received) == 1
        assert received[0]["type"] == "test"
        assert received[0]["data"] == "hello"

    def test_multiple_subscribers(self):
        """多订阅者。"""
        bus = EventBus()
        r1, r2 = [], []
        bus.subscribe(lambda e: r1.append(e))
        bus.subscribe(lambda e: r2.append(e))
        bus.emit("test")
        assert len(r1) == 1
        assert len(r2) == 1

    def test_subscriber_exception_no_crash(self):
        """订阅者异常不影响主循环。"""
        bus = EventBus()
        bus.subscribe(lambda e: (_ for _ in ()).throw(Exception("boom")))
        received = []
        bus.subscribe(lambda e: received.append(e))
        bus.emit("test")  # 不应崩溃
        assert len(received) == 1


# ══════════════════════════════════════════════════════════
# Runtime
# ══════════════════════════════════════════════════════════

class TestRuntime:
    def test_mock_run(self):
        """mock 模式运行核心循环。"""
        llm = LLMClient(base_url="")
        runtime = AgentRuntime(llm, max_turns=3)
        messages = runtime.run("system prompt", "hello")
        # system + user + assistant（mock 返回无 tool_calls → 立即停止）
        assert len(messages) >= 3
        assert messages[-1]["role"] == "assistant"

    def test_max_turns_fuse(self):
        """max_turns 熔断。"""
        # 始终返回 tool_calls → 永不 stop → 熔断
        tool_call = {"id": "c1", "type": "function",
                     "function": {"name": "list_scenarios", "arguments": "{}"}}
        mock = MockLLM([{"role": "assistant", "content": "", "tool_calls": [tool_call]}] * 10)
        runtime = AgentRuntime(mock, max_turns=3)
        messages = runtime.run("sys", "test")
        # 应在 3 轮后熔断
        fuse_msgs = [m for m in messages if "FUSE" in m.get("content", "")]
        assert len(fuse_msgs) > 0

    def test_tool_execution(self):
        """工具执行：list_scenarios 应返回场景列表。"""
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "list_scenarios", "arguments": "{}"}}
            ]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5)
        messages = runtime.run("sys", "list scenarios")
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        # list_scenarios 返回 JSON
        data = json.loads(tool_msgs[0]["content"])
        assert isinstance(data, list)
        assert len(data) > 0  # 至少有 PP-RC-001 等场景

    def test_session_persistence(self, tmp_path):
        """会话持久化：run 后可从 JSONL 恢复。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        llm = LLMClient(base_url="")
        runtime = AgentRuntime(llm, max_turns=3)
        runtime.run("sys", "hello", session=sm, session_id=sid)
        loaded = sm.load(sid)
        assert loaded is not None
        assert len(loaded) >= 3  # system + user + assistant

    def test_session_resume(self, tmp_path):
        """会话恢复：传入已有 session_id 恢复历史。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        # 先保存一些消息
        sm.save(sid, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "previous"},
            {"role": "assistant", "content": "prev reply"},
            {"role": "user", "content": "continue"},
        ])
        # 用已有 session_id 恢复
        llm = LLMClient(base_url="")
        runtime = AgentRuntime(llm, max_turns=3)
        messages = runtime.run("sys", "continue", session=sm, session_id=sid)
        # 应恢复历史消息
        assert any(m.get("content") == "prev reply" for m in messages)

    def test_event_emission(self):
        """事件发射：assistant 和 state 事件。"""
        events = []
        llm = LLMClient(base_url="")
        runtime = AgentRuntime(llm, max_turns=2)
        runtime.events.subscribe(lambda e: events.append(e))
        runtime.run("sys", "hello")
        types = [e["type"] for e in events]
        assert "state" in types
        assert "assistant" in types


# ══════════════════════════════════════════════════════════
# System Prompt
# ══════════════════════════════════════════════════════════

class TestSystemPrompt:
    def test_build_with_explicit_args(self):
        """用显式参数构建 system prompt。"""
        prompt = build_system_prompt(
            format_spec_text="FORMAT SPEC CONTENT",
            agents_md="AGENTS MD CONTENT",
        )
        assert "FORMAT SPEC CONTENT" in prompt
        assert "AGENTS MD CONTENT" in prompt
        assert "硬约束" in prompt

    def test_build_auto_load(self):
        """自动加载 format_spec 和 AGENTS.md。"""
        prompt = build_system_prompt()
        # 应包含 format_spec 内容（或回退消息）和工作区规则（或回退消息）
        assert "硬约束" in prompt
        assert "工作流程" in prompt
