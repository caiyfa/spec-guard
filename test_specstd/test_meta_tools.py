"""test_meta_tools — H-3/H-4 meta 工具测试。

覆盖验收标准：
H-4:
1. todo_write 后事件 emit（todo_update）
2. 会话恢复后待办状态还原
3. todo_write 持久化到 JSONL
4. 模式切换时待办状态自动流转

H-3:
1. switch_mode 后工具白名单变化
2. 首条 system prompt 不被修改
3. 切换时注入新 system 消息
4. mode_switch 事件正确 emit
5. 5 个模式都能调用 switch_mode 和 todo_write
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.runtime import AgentRuntime, META_TOOLS
from agent.session import SessionManager
from agent.mode_loader import clear_cache
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
        """无效 status 返回错误。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("todo_write", {"todos": [
            {"id": "1", "title": "test", "status": "invalid"},
        ]}))
        assert "错误" in result

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
# H-3: switch_mode 测试
# ══════════════════════════════════════════════════════════

class TestSwitchMode:
    def test_switch_mode_changes_mode_name(self):
        """switch_mode 后 mode_name 变化。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "草稿完成，开始审计",
        }))
        assert "audit" in result
        assert runtime.mode_name == "audit"

    def test_switch_mode_changes_tools(self):
        """切换后工具白名单变化（audit 无 write_draft）。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        tool_names_before = {t.name for t in runtime.tools}
        assert "write_draft" in tool_names_before  # generate 有 write_draft
        runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "test",
        }))
        tool_names_after = {t.name for t in runtime.tools}
        assert "write_draft" not in tool_names_after  # audit 无 write_draft
        assert "write_audit_report" in tool_names_after  # audit 有审计工具

    def test_switch_mode_first_system_unchanged(self):
        """首条 system prompt 不被修改（prompt cache 保护）。"""
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("switch_mode", {"mode": "audit", "reason": "test"}),
            ]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5, mode_name="generate")
        messages = runtime.run("ORIGINAL_SYSTEM_PROMPT", "hello")
        # 首条 system prompt 不变
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "ORIGINAL_SYSTEM_PROMPT"

    def test_switch_mode_injects_notice(self):
        """切换时注入新 system 消息声明新约束。"""
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("switch_mode", {"mode": "audit", "reason": "草稿完成"}),
            ]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5, mode_name="generate")
        messages = runtime.run("sys", "hello")
        # 应有注入的 system 消息（含【模式切换】）
        switch_msgs = [m for m in messages
                       if m.get("role") == "system" and "模式切换" in m.get("content", "")]
        assert len(switch_msgs) >= 1
        assert "generate" in switch_msgs[0]["content"]
        assert "audit" in switch_msgs[0]["content"]
        assert "草稿完成" in switch_msgs[0]["content"]

    def test_switch_mode_emits_event(self):
        """mode_switch 事件正确 emit（from/to/reason/auto）。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "test reason",
        }))
        switch_events = [e for e in events if e["type"] == "mode_switch"]
        assert len(switch_events) == 1
        assert switch_events[0]["from_mode"] == "generate"
        assert switch_events[0]["to_mode"] == "audit"
        assert switch_events[0]["reason"] == "test reason"
        assert switch_events[0]["auto"] is True

    def test_switch_mode_unknown_mode(self):
        """未知模式返回错误。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "nonexistent", "reason": "test",
        }))
        assert "错误" in result
        assert runtime.mode_name == "generate"  # 未变

    def test_switch_mode_same_mode(self):
        """同模式返回提示。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "generate", "reason": "test",
        }))
        assert "无需切换" in result

    def test_switch_mode_missing_reason(self):
        """缺少 reason 返回错误。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        result = runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit",
        }))
        assert "错误" in result

    def test_switch_mode_tools_dirty_rebuild(self):
        """切换后 _tools_dirty 标记触发工具集重建。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        assert not runtime._tools_dirty
        runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "test",
        }))
        assert runtime._tools_dirty  # 标记为脏


# ══════════════════════════════════════════════════════════
# H-3: meta 工具常驻所有模式
# ══════════════════════════════════════════════════════════

class TestMetaToolsAllModes:
    @pytest.mark.parametrize("mode_name", ["generate", "debug", "analyze", "chat", "audit"])
    def test_meta_tools_in_all_modes(self, mode_name):
        """5 个模式都包含 switch_mode 和 todo_write。"""
        clear_cache()
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name=mode_name)
        tool_names = {t.name for t in runtime.tools}
        assert "switch_mode" in tool_names
        assert "todo_write" in tool_names

    def test_chat_mode_has_only_meta_tools(self):
        """chat 模式 tools=[] 但仍有 meta 工具。"""
        clear_cache()
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="chat")
        tool_names = {t.name for t in runtime.tools}
        # chat 模式只有 meta 工具
        assert tool_names == META_TOOLS

    def test_meta_tools_in_openai_format(self):
        """meta 工具出现在 OpenAI function calling 格式中。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="chat")
        openai_tools = runtime._to_openai_tools()
        names = {t["function"]["name"] for t in openai_tools}
        assert "switch_mode" in names
        assert "todo_write" in names


# ══════════════════════════════════════════════════════════
# H-3+H-4: 模式切换时待办自动流转
# ══════════════════════════════════════════════════════════

class TestTodoAutoTransition:
    def test_switch_mode_todo_transition(self):
        """切换时 in_progress → done, pending → in_progress。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        # 设置初始待办
        runtime._todos = [
            {"id": "1", "title": "生成场景", "status": "in_progress", "mode": "generate"},
            {"id": "2", "title": "审计漏洞", "status": "pending", "mode": "audit"},
            {"id": "3", "title": "反馈研发", "status": "pending", "mode": "chat"},
        ]
        runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "草稿完成",
        }))
        # generate 的 in_progress → done
        assert runtime._todos[0]["status"] == "done"
        # audit 的第一个 pending → in_progress
        assert runtime._todos[1]["status"] == "in_progress"
        # chat 的 pending 不变
        assert runtime._todos[2]["status"] == "pending"

    def test_switch_mode_todo_emits_update(self):
        """切换时待办变更 emit todo_update 事件。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        runtime._todos = [
            {"id": "1", "title": "生成", "status": "in_progress", "mode": "generate"},
            {"id": "2", "title": "审计", "status": "pending", "mode": "audit"},
        ]
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "test",
        }))
        todo_events = [e for e in events if e["type"] == "todo_update"]
        assert len(todo_events) >= 1
        assert todo_events[-1]["todos"][0]["status"] == "done"
        assert todo_events[-1]["todos"][1]["status"] == "in_progress"

    def test_switch_mode_no_todos_no_error(self):
        """无待办时切换不报错。"""
        runtime = AgentRuntime(MockLLM(), max_turns=1, mode_name="generate")
        assert len(runtime._todos) == 0
        result = runtime._execute_tool(_make_tool_call("switch_mode", {
            "mode": "audit", "reason": "test",
        }))
        assert "audit" in result


# ══════════════════════════════════════════════════════════
# H-3+H-4: 集成测试（通过 MockLLM + run()）
# ══════════════════════════════════════════════════════════

class TestIntegration:
    def test_todo_then_switch_in_run(self):
        """在 run() 中先 todo_write 再 switch_mode。"""
        mock = MockLLM([
            # 第一轮：更新待办
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("todo_write", {"todos": [
                    {"id": "1", "title": "生成场景", "status": "in_progress", "mode": "generate"},
                    {"id": "2", "title": "审计漏洞", "status": "pending", "mode": "audit"},
                ]}),
            ]},
            # 第二轮：切换模式
            {"role": "assistant", "content": "", "tool_calls": [
                _make_tool_call("switch_mode", {"mode": "audit", "reason": "草稿完成"}),
            ]},
            # 第三轮：最终回复
            {"role": "assistant", "content": "任务完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=10, mode_name="generate")
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        messages = runtime.run("sys", "生成场景并审计")

        # 验证模式已切换
        assert runtime.mode_name == "audit"
        # 验证待办状态流转
        assert runtime._todos[0]["status"] == "done"  # generate → done
        assert runtime._todos[1]["status"] == "in_progress"  # audit → in_progress
        # 验证事件
        todo_events = [e for e in events if e["type"] == "todo_update"]
        assert len(todo_events) >= 2  # 至少 2 次（todo_write + switch_mode 自动更新）
        switch_events = [e for e in events if e["type"] == "mode_switch"]
        assert len(switch_events) == 1
        assert switch_events[0]["from_mode"] == "generate"
        assert switch_events[0]["to_mode"] == "audit"
        # 验证首条 system 不变
        assert messages[0]["content"] == "sys"
        # 验证注入了切换通知
        switch_msgs = [m for m in messages
                       if m.get("role") == "system" and "模式切换" in m.get("content", "")]
        assert len(switch_msgs) >= 1


# ══════════════════════════════════════════════════════════
# meta.py 模块测试
# ══════════════════════════════════════════════════════════

class TestMetaModule:
    def test_meta_tool_names(self):
        """META_TOOL_NAMES 包含两个工具名。"""
        assert "switch_mode" in meta.META_TOOL_NAMES
        assert "todo_write" in meta.META_TOOL_NAMES
        assert len(meta.META_TOOL_NAMES) == 2

    def test_meta_tools_count(self):
        """meta 模块有 2 个工具。"""
        assert len(meta.TOOLS) == 2

    def test_meta_handle_standalone(self):
        """MCP server 独立模式返回提示信息。"""
        result = asyncio.run(meta.handle("todo_write", {}))
        assert "仅在 Agent 运行时中可用" in result[0].text

    def test_meta_tools_in_server_all_tools(self):
        """meta 工具出现在 server.py 的 ALL_TOOLS 中。"""
        names = {t.name for t in SERVER_ALL_TOOLS}
        assert "switch_mode" in names
        assert "todo_write" in names
