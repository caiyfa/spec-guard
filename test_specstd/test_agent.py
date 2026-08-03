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
        self.max_context_tokens = 0  # 回退消息数阈值（与 LLMClient 接口对齐）

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
        # list_scenarios 返回 JSON（K-xxx：{total, summary, scenarios}，summary 含分类计数）
        data = json.loads(tool_msgs[0]["content"])
        assert isinstance(data, dict)
        assert data["total"] > 0  # 至少有 PP-RC-001 等场景
        assert len(data["scenarios"]) == data["total"]
        assert data["summary"]["by_module"]

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

    def test_session_resume_appends_new_user_message(self, tmp_path):
        """K-013 修复：续会话时本轮 user 消息必须追加（此前被 history 整体替换丢弃）。

        生产佐证：真实会话导出文件中 assistant 在「自问自答」——LLM 看不到用户新消息。
        """
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        sm.save(sid, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "previous"},
            {"role": "assistant", "content": "prev reply"},
        ])
        llm = LLMClient(base_url="")
        runtime = AgentRuntime(llm, max_turns=3)
        messages = runtime.run("sys", "本轮新消息", session=sm, session_id=sid)
        user_contents = [m.get("content") for m in messages if m.get("role") == "user"]
        assert user_contents[-1] == "本轮新消息"
        # 持久化后也应在（save 全量写）
        loaded = sm.load(sid)
        assert any(m.get("role") == "user" and m.get("content") == "本轮新消息" for m in loaded)

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

    def test_tool_call_start_event(self):
        """K-018：工具执行前必须发射 tool_call_start（长工具执行期间前端不再死寂）。

        生产佐证：promote_draft 跑发布门禁子进程（上限 180s/份）执行期间零事件，
        用户等待数分钟无任何反馈判为「一直没响应」。
        """
        mock = MockLLM([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "list_scenarios", "arguments": "{}"}}
            ]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5)
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        runtime.run("sys", "list")
        types = [e["type"] for e in events]
        assert "tool_call_start" in types
        assert types.index("tool_call_start") < types.index("tool_call")
        start_evt = next(e for e in events if e["type"] == "tool_call_start")
        assert start_evt["tool"] == "list_scenarios"

    def test_compaction_preserves_full_history(self, tmp_path):
        """K-019：压缩只作用 LLM 工作副本——会话文件必须保留完整历史（页面展示不丢）。

        生产佐证：用户真实会话导出仅 13 条（压缩态覆盖落盘），页面显示「明显变少」。
        """
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        # 构造超过压缩阈值的历史（COMPACTION_THRESHOLD=16 条对话消息）
        history = [{"role": "system", "content": "sys"}]
        for i in range(20):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})
        sm.save(sid, history)

        received = []

        class RecordingLLM(MockLLM):
            def chat(self, messages, tools=None, temperature=0.7, on_delta=None):
                received.append(len(messages))
                return super().chat(messages, tools, temperature, on_delta)

        # max_context_tokens=0 → 消息数阈值回退（>16 触发压缩）
        runtime = AgentRuntime(RecordingLLM(), max_turns=2)
        runtime.run("sys", "继续", session=sm, session_id=sid)

        # ① LLM 收到的是压缩后的上下文（全量 42 条 → 压缩后约 12 条）
        assert received and received[0] < 20
        # ② 会话文件保留完整历史（全部 20 轮 + 本轮新消息），无压缩摘要覆盖
        loaded = sm.load(sid)
        contents = [str(m.get("content", "")) for m in loaded]
        for i in range(20):
            assert f"问题{i}" in contents and f"回答{i}" in contents
        assert "继续" in contents

    def test_llm_exception_graceful(self, tmp_path):
        """K-018：LLM 调用异常兜底——落盘 + error 事件 + 优雅返回。

        此前异常直接炸出 run：当轮消息不落盘，会话文件无痕迹，
        用户重发时历史缺失（重启后「确认入库没响应」会话导出佐证）。
        """
        class RaisingLLM(MockLLM):
            def chat(self, messages, tools=None, temperature=0.7, on_delta=None):
                raise RuntimeError("网关连接超时")

        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create()
        runtime = AgentRuntime(RaisingLLM(), max_turns=3)
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        messages = runtime.run("sys", "hello", session=sm, session_id=sid)
        assert any("[ERROR] LLM 调用失败" in str(m.get("content", "")) for m in messages)
        assert any(e["type"] == "error" and "网关连接超时" in e.get("message", "") for e in events)
        # 已落盘（重发/导出可见痕迹）
        loaded = sm.load(sid)
        assert any("[ERROR] LLM 调用失败" in str(m.get("content", "")) for m in loaded)


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
        assert "通用硬约束" in prompt
        assert "格式规范" in prompt


class TestPromptOptimization:
    """K-023：统一提示词（去模式化）——全量规范 + 全量技能 + 条件式任务指引。"""

    def test_unified_prompt_full_spec_and_skills(self):
        """统一 prompt：全量 format_spec 常驻 + 全量技能注入（不再按模式裁剪）。"""
        p = build_system_prompt()
        assert "未注入全量格式规范" not in p  # 全量常驻
        assert "generate-scenario" in p and "debug-failure" in p  # 全量技能

    def test_mode_guidance_conditional_sections(self):
        """模式片段合并为「任务行为指引」条件章节（单一事实源仍是 modes/*.md）。"""
        p = build_system_prompt()
        assert "任务行为指引" in p
        assert "当生成/修改场景" in p      # generate 流程
        assert "DAG 拓扑设计" in p          # K-021 设计步并入
        assert "当审计 spec 漏洞时" in p    # audit 职责
        assert "当前模式" not in p          # 不再有模式态

    def test_no_mode_switch_instruction(self):
        """模板不再指导 switch_mode（机制已废弃，仅工具壳平滑过渡）。"""
        p = build_system_prompt()
        assert "切到 generate 模式" not in p
        assert "切换到「场景生成」模式" not in p

    def test_references_section_present(self):
        """P2：@引用语义说明注入（LLM 不再靠猜 <references> 块）。"""
        prompt = build_system_prompt()
        assert "用户引用" in prompt
        assert "<references>" in prompt

    def test_skills_xml_all_skills(self):
        """K-023：build_skills_xml 全量返回（mode 参数兼容但无效）。"""
        from agent.skill_loader import build_skills_xml
        all_xml = build_skills_xml()
        assert "generate-scenario" in all_xml
        assert "debug-failure" in all_xml
        assert "validate-conformance" in all_xml
        # mode 参数不再过滤
        assert build_skills_xml("chat") == all_xml
