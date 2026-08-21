"""test_meta_tools — H-4 meta 工具测试（T-601：switch_mode 已随 modes 体系退役）。

覆盖验收标准：
H-4:
1. todo_write 后事件 emit（todo_update）
2. 会话恢复后待办状态还原
3. todo_write 持久化到 JSONL
4. 全量工具常驻（mode_name 遗留标签不影响工具集）

T-601:
1. switch_mode 不再是 meta 工具（未知工具报错）
2. META_TOOL_NAMES 只剩 todo_write
"""

import asyncio
import json
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from agent.runtime import AgentRuntime, META_TOOLS
from agent.session import SessionManager
from agent.skill_loader import clear_cache
from mcp_server.tools import meta
from mcp_server.server import ALL_TOOLS as SERVER_ALL_TOOLS


# ══════════════════════════════════════════════════════════
# Mock LLM
# ══════════════════════════════════════════════════════════

class MockLLM:
    """可配置响应序列的 mock LLM。"""

    def __init__(self, responses=None):
        self.responses = responses or []
        self._call_count = 0
        self._total_tokens = 0
        self.max_context_tokens = 0

    @property
    def is_mock(self):
        return True

    def chat(self, messages, tools=None, temperature=0.7, on_delta=None):
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


def _make_tool_call(name, args):
    """构造一个 tool_call 字典。"""
    return {
        "id": f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


# ══════════════════════════════════════════════════════════
# H-4: todo_write 测试
# ══════════════════════════════════════════════════════════

class TestTodoWrite:
    def test_todo_write_updates_todos(self):
        """todo_write 后 _todos 被更新。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        todos = [
            {"id": "1", "title": "生成场景", "status": "in_progress", "mode": "generate"},
            {"id": "2", "title": "审计漏洞", "status": "pending", "mode": "audit"},
        ]
        result = runtime._execute_tool(_make_tool_call("todo_write", {"todos": todos}))
        assert "待办已更新" in result
        assert len(runtime._todos) == 2
        assert runtime._todos[0]["id"] == "1"

    def test_todo_write_emits_event(self):
        """todo_write 后 emit todo_update 事件。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        runtime._execute_tool(_make_tool_call("todo_write", {"todos": [
            {"id": "1", "title": "test", "status": "pending"},
        ]}))
        todo_events = [e for e in events if e["type"] == "todo_update"]
        assert len(todo_events) == 1
        assert len(todo_events[0]["todos"]) == 1

    def test_todo_write_invalid_status(self):
        """无效 status 返回错误（K-020：报错必须列合法值——LLM 曾猜 "completed"
        被拒后只能靠猜重试，真实会话导出佐证）。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("todo_write", {"todos": [
            {"id": "1", "title": "test", "status": "completed"},
        ]}))
        assert "错误" in result
        assert "pending" in result and "in_progress" in result and "done" in result

    def test_todo_write_missing_id(self):
        """缺少 id 返回错误。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("todo_write", {"todos": [
            {"title": "test", "status": "pending"},
        ]}))
        assert "错误" in result

    def test_todo_write_not_list(self):
        """todos 不是数组返回错误。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("todo_write", {"todos": "not a list"}))
        assert "错误" in result

    def test_todo_write_all_valid_statuses(self):
        """4 种状态都合法。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        for status in ["pending", "in_progress", "done", "blocked"]:
            result = runtime._execute_tool(_make_tool_call("todo_write", {"todos": [
                {"id": "1", "title": "test", "status": status},
            ]}))
            assert "待办已更新" in result


# ══════════════════════════════════════════════════════════
# H-4: 待办持久化测试
# ══════════════════════════════════════════════════════════

class TestTodoPersistence:
    def test_save_load_todos(self, tmp_path):
        """save(todos=) + load_todos 往返。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        todos = [
            {"id": "1", "title": "步骤一", "status": "done"},
            {"id": "2", "title": "步骤二", "status": "in_progress"},
        ]
        sm.save(sid, [{"role": "user", "content": "hi"}], todos=todos)
        loaded = sm.load_todos(sid)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["id"] == "1"
        assert loaded[1]["status"] == "in_progress"

    def test_load_todos_none(self, tmp_path):
        """无待办时返回 None。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "hi"}])
        assert sm.load_todos(sid) is None

    def test_load_todos_last(self, tmp_path):
        """取最后一行 todo_list。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "hi"}],
                todos=[{"id": "1", "title": "old", "status": "done"}])
        sm.save_todos(sid, [{"id": "2", "title": "new", "status": "pending"}])
        loaded = sm.load_todos(sid)
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["id"] == "2"

    def test_load_skips_todo_list(self, tmp_path):
        """load 跳过 todo_list 行（不当消息处理）。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "hi"}],
                todos=[{"id": "1", "title": "test", "status": "pending"}])
        messages = sm.load(sid)
        # 只应有 1 条消息（user），todo_list 被跳过
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_session_resume_todos(self, tmp_path):
        """会话恢复后待办状态还原。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        todos = [
            {"id": "1", "title": "生成", "status": "done", "mode": "generate"},
            {"id": "2", "title": "审计", "status": "in_progress", "mode": "audit"},
        ]
        sm.save(sid, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "done"},
        ], todos=todos)

        # 新 runtime 恢复会话
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        assert len(runtime._todos) == 0  # 初始为空
        runtime.run("sys", "continue", session=sm, session_id=sid)
        assert len(runtime._todos) == 2  # 恢复后有待办
        assert runtime._todos[1]["status"] == "in_progress"

    def test_todo_write_persists_via_session(self, tmp_path):
        """todo_write 工具调用后通过 session 持久化。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("todo_write", {"todos": [
                    {"id": "1", "title": "test", "status": "in_progress"},
                ]}),
            ]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5, mode_name="generate")
        runtime.run("sys", "hello", session=sm, session_id=sid)
        # 从 JSONL 恢复待办
        loaded = sm.load_todos(sid)
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["id"] == "1"

    def test_export_session_includes_todos(self, tmp_path):
        """export_session 包含待办数据。"""
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        todos = [{"id": "1", "title": "test", "status": "pending"}]
        sm.save(sid, [{"role": "user", "content": "hi"}], todos=todos)
        exported = sm.export_session(sid)
        assert exported["todos"] is not None
        assert len(exported["todos"]) == 1
        assert exported["summary"]["has_todos"] is True


# ══════════════════════════════════════════════════════════
# T-601: switch_mode 已随 modes 体系退役（工具壳一并删除）
# ══════════════════════════════════════════════════════════

class TestMetaToolsDeprecated:
    """T-601：switch_mode 删除后，meta 工具只剩 todo_write；全量工具常驻不变。"""

    def test_all_tools_regardless_of_legacy_mode(self):
        """K-023 核心：mode_name 遗留标签不影响工具集——不再有白名单门禁。

        生产取证：模式白名单防住的都是合法工作流（K-012 未知工具报错 /
        K-018 resume 模式落错 / K-022 audit 模式「没有入库工具」）。
        """
        for mode_name in ("generate", "debug", "analyze", "chat", "audit", ""):
            runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name=mode_name)
            tool_names = {t.name for t in runtime.tools}
            # T-982：合并工具面（draft/scenario/attribution/audit/info_pack 全 action 可见）
            for t in ("draft", "validate", "attribution",
                      "scenario", "audit", "info_pack"):
                assert t in tool_names, f"mode={mode_name!r} 应有 {t}"

    def test_meta_tools_in_openai_format(self):
        """meta 工具出现在 OpenAI function calling 格式中（switch_mode 已删除）。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1)
        openai_tools = runtime._to_openai_tools()
        names = {t["function"]["name"] for t in openai_tools}
        assert "switch_mode" not in names
        assert "todo_write" in names

    def test_no_mode_switch_events(self):
        """run 中调用 switch_mode 不再产生 mode_switch 事件/通知注入。"""
        mock = MockLLM([
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5)
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        messages = runtime.run("sys", "hello")
        assert not [e for e in events if e["type"] == "mode_switch"]
        assert not [m for m in messages
                    if m.get("role") == "system" and "模式切换" in str(m.get("content", ""))]

    def test_switch_mode_unknown_tool(self):
        """T-601：switch_mode 不再是 meta 工具——按未知工具报错并列出可用工具。"""
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("switch_mode", {"mode": "audit", "reason": "test"}),
            ]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5)
        messages = runtime.run("sys", "切换模式")
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "未知工具" in tool_msgs[0]["content"]


# ══════════════════════════════════════════════════════════
# H-4: 集成测试（todo_write 在 run() 中工作）
# ══════════════════════════════════════════════════════════

class TestIntegration:
    def test_todo_write_in_run(self):
        """在 run() 中 todo_write 更新待办并 emit 事件（K-023 后无模式流转）。"""
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("todo_write", {"todos": [
                    {"id": "1", "title": "生成场景", "status": "in_progress"},
                    {"id": "2", "title": "审计漏洞", "status": "pending"},
                ]}),
            ]},
            {"role": "assistant", "content": "任务完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=10)
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        messages = runtime.run("sys", "生成场景并审计")

        # 待办按写入原样保留（无模式自动流转）
        assert runtime._todos[0]["status"] == "in_progress"
        assert runtime._todos[1]["status"] == "pending"
        todo_events = [e for e in events if e["type"] == "todo_update"]
        assert len(todo_events) >= 1
        assert not [e for e in events if e["type"] == "mode_switch"]
        assert messages[0]["content"] == "sys"


# ══════════════════════════════════════════════════════════
# meta.py 模块测试
# ══════════════════════════════════════════════════════════

class TestMetaModule:
    def test_meta_tool_names(self):
        """T-601：META_TOOL_NAMES 只剩 todo_write（switch_mode 已退役）。"""
        assert "switch_mode" not in meta.META_TOOL_NAMES
        assert "todo_write" in meta.META_TOOL_NAMES
        assert len(meta.META_TOOL_NAMES) == 1

    def test_meta_tools_count(self):
        """T-601：meta 模块只剩 1 个工具（switch_mode 已删除）。"""
        assert len(meta.TOOLS) == 1

    def test_meta_handle_standalone(self):
        """MCP server 独立模式返回提示信息。"""
        result = asyncio.run(meta.handle("todo_write", {}))
        assert "仅在 Agent 运行时中可用" in result[0].text

    def test_meta_tools_in_server_all_tools(self):
        """meta 工具出现在 server.py 的 ALL_TOOLS 中（switch_mode 已删除）。"""
        names = {t.name for t in SERVER_ALL_TOOLS}
        assert "switch_mode" not in names
        assert "todo_write" in names
