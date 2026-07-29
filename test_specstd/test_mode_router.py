"""test_mode_router — H-2 模式自动路由器单元测试。

覆盖三层信号路由：
  层 0：手动锁定
  层 1：工作台上下文信号
  层 2：消息意图
  层 3：默认 chat
"""

import pytest
from agent.mode_router import RouteContext, RouteResult, route_mode, INTENT_KEYWORDS


# ══════════════════════════════════════════════════════════
# 层 0：手动锁定
# ══════════════════════════════════════════════════════════

class TestManualLock:
    """手动锁定优先级最高，不自动路由。"""

    def test_locked_mode_takes_priority(self):
        """锁定模式时，所有上下文信号和意图都被忽略。"""
        ctx = RouteContext(
            message="生成一个场景",
            locked_mode="debug",
            current_page="execution",
            last_run_failed=True,
        )
        result = route_mode(ctx)
        assert result.mode == "debug"
        assert result.source == "manual"
        assert "锁定" in result.reason

    def test_locked_mode_ignores_intent(self):
        """锁定模式下，意图关键词不生效。"""
        ctx = RouteContext(
            message="审计一下 spec 有没有漏洞",
            locked_mode="generate",
        )
        result = route_mode(ctx)
        assert result.mode == "generate"
        assert result.source == "manual"

    def test_locked_mode_ignores_workspace_pulled(self):
        """锁定模式下，工作区拉取信号不生效。"""
        ctx = RouteContext(
            message="hello",
            locked_mode="chat",
            workspace_just_pulled=True,
        )
        result = route_mode(ctx)
        assert result.mode == "chat"
        assert result.source == "manual"

    def test_empty_locked_mode_not_treated_as_lock(self):
        """空字符串 locked_mode 不视为锁定。"""
        ctx = RouteContext(
            message="生成场景",
            locked_mode="",
        )
        result = route_mode(ctx)
        assert result.mode == "generate"
        assert result.source == "intent"


# ══════════════════════════════════════════════════════════
# 层 1：工作台上下文信号
# ══════════════════════════════════════════════════════════

class TestContextSignals:
    """工作台上下文信号（确定性最强）。"""

    def test_workspace_just_pulled_routes_to_audit(self):
        """工作区刚拉取 → 自动审计。"""
        ctx = RouteContext(
            message="hello",
            workspace_just_pulled=True,
        )
        result = route_mode(ctx)
        assert result.mode == "audit"
        assert result.source == "context"
        assert "拉取" in result.reason or "审计" in result.reason

    def test_execution_page_with_failed_run_routes_to_debug(self):
        """执行控制页 + 失败运行 → 自动调试。"""
        ctx = RouteContext(
            message="帮我看看",
            current_page="execution",
            last_run_failed=True,
        )
        result = route_mode(ctx)
        assert result.mode == "debug"
        assert result.source == "context"
        assert "失败" in result.reason or "调试" in result.reason

    def test_execution_page_without_failure_does_not_route_debug(self):
        """执行控制页但未失败 → 不路由到 debug。"""
        ctx = RouteContext(
            message="帮我看看",
            current_page="execution",
            last_run_failed=False,
        )
        result = route_mode(ctx)
        assert result.mode != "debug" or result.source != "context"

    def test_editing_never_run_scenario_routes_to_generate(self):
        """编辑从未运行的场景 → 自动生成。"""
        ctx = RouteContext(
            message="帮我看看",
            editing_scenario_id="PP-RC-001",
            scenario_never_run=True,
        )
        result = route_mode(ctx)
        assert result.mode == "generate"
        assert result.source == "context"
        assert "从未运行" in result.reason or "生成" in result.reason

    def test_editing_already_run_scenario_does_not_route_generate(self):
        """编辑已运行过的场景 → 不路由到 generate。"""
        ctx = RouteContext(
            message="帮我看看",
            editing_scenario_id="PP-RC-001",
            scenario_never_run=False,
        )
        result = route_mode(ctx)
        assert result.mode != "generate" or result.source != "context"

    def test_pending_vulns_on_feedback_page_routes_to_audit(self):
        """反馈页 + 有 pending 漏洞 → 继续审计。"""
        ctx = RouteContext(
            message="看看",
            current_page="feedback",
            pending_vulnerabilities=3,
        )
        result = route_mode(ctx)
        assert result.mode == "audit"
        assert result.source == "context"
        assert "漏洞" in result.reason or "审计" in result.reason

    def test_pending_vulns_not_on_feedback_page_does_not_route_audit(self):
        """pending 漏洞但不在反馈页 → 不路由到 audit（上下文）。"""
        ctx = RouteContext(
            message="看看",
            current_page="chat",
            pending_vulnerabilities=3,
        )
        result = route_mode(ctx)
        # 可能被意图匹配或其他逻辑处理，但不应是 context source 的 audit
        if result.source == "context":
            assert result.mode != "audit"

    def test_workspace_pulled_priority_over_failed_run(self):
        """工作区拉取优先于失败运行（先检查拉取信号）。"""
        ctx = RouteContext(
            message="hello",
            workspace_just_pulled=True,
            current_page="execution",
            last_run_failed=True,
        )
        result = route_mode(ctx)
        assert result.mode == "audit"
        assert result.source == "context"


# ══════════════════════════════════════════════════════════
# 层 2：消息意图
# ══════════════════════════════════════════════════════════

class TestIntentRouting:
    """消息意图关键词路由（零 LLM 调用）。"""

    def test_generate_intent(self):
        """生成相关关键词 → generate。"""
        for kw in ["生成", "创建", "新建", "写场景", "generate", "单元测试"]:
            ctx = RouteContext(message=kw)
            result = route_mode(ctx)
            assert result.mode == "generate", f"关键词 '{kw}' 应路由到 generate"
            assert result.source == "intent"

    def test_debug_intent(self):
        """调试相关关键词 → debug。"""
        for kw in ["为什么失败", "报错", "debug", "排查"]:
            ctx = RouteContext(message=kw)
            result = route_mode(ctx)
            assert result.mode == "debug", f"关键词 '{kw}' 应路由到 debug"
            assert result.source == "intent"

    def test_audit_intent(self):
        """审计相关关键词 → audit。"""
        for kw in ["审计", "漏洞", "audit", "一致性"]:
            ctx = RouteContext(message=kw)
            result = route_mode(ctx)
            assert result.mode == "audit", f"关键词 '{kw}' 应路由到 audit"
            assert result.source == "intent"

    def test_analyze_intent(self):
        """分析相关关键词 → analyze。"""
        for kw in ["分析", "解释", "梳理", "analyze"]:
            ctx = RouteContext(message=kw)
            result = route_mode(ctx)
            assert result.mode == "analyze", f"关键词 '{kw}' 应路由到 analyze"
            assert result.source == "intent"

    def test_intent_case_insensitive(self):
        """意图匹配不区分大小写。"""
        ctx = RouteContext(message="DEBUG this issue")
        result = route_mode(ctx)
        assert result.mode == "debug"
        assert result.source == "intent"

    def test_multiple_keywords_picks_best(self):
        """多个模式都有匹配时，选择命中关键词最多的。"""
        ctx = RouteContext(message="生成一个场景然后审计漏洞")
        result = route_mode(ctx)
        # "生成" + "场景" = generate 2 hits; "审计" + "漏洞" = audit 2 hits
        # 平局时取第一个（dict 顺序，generate 在前）
        assert result.source == "intent"
        assert result.mode in ("generate", "audit")

    def test_intent_hits_in_reason(self):
        """路由原因中包含命中关键词数。"""
        ctx = RouteContext(message="生成创建新建")
        result = route_mode(ctx)
        assert "关键词" in result.reason
        assert "3" in result.reason  # 3 个命中


# ══════════════════════════════════════════════════════════
# 层 3：默认
# ══════════════════════════════════════════════════════════

class TestDefaultRouting:
    """无明确意图时默认 chat。"""

    def test_no_signal_defaults_to_chat(self):
        """无任何信号 → 默认 chat。"""
        ctx = RouteContext(message="hello world")
        result = route_mode(ctx)
        assert result.mode == "chat"
        assert result.source == "default"

    def test_empty_message_defaults_to_chat(self):
        """空消息 → 默认 chat。"""
        ctx = RouteContext(message="")
        result = route_mode(ctx)
        assert result.mode == "chat"
        assert result.source == "default"

    def test_greeting_defaults_to_chat(self):
        """问候语 → 默认 chat。"""
        ctx = RouteContext(message="你好，今天天气怎么样？")
        result = route_mode(ctx)
        assert result.mode == "chat"
        assert result.source == "default"


# ══════════════════════════════════════════════════════════
# 层间优先级
# ══════════════════════════════════════════════════════════

class TestPriorityOrder:
    """层间优先级：锁定 > 上下文 > 意图 > 默认。"""

    def test_lock_beats_context(self):
        """锁定优先于上下文。"""
        ctx = RouteContext(
            message="hello",
            locked_mode="analyze",
            workspace_just_pulled=True,
        )
        result = route_mode(ctx)
        assert result.source == "manual"

    def test_context_beats_intent(self):
        """上下文优先于意图。"""
        ctx = RouteContext(
            message="生成一个场景",
            current_page="execution",
            last_run_failed=True,
        )
        result = route_mode(ctx)
        assert result.mode == "debug"
        assert result.source == "context"

    def test_intent_beats_default(self):
        """意图优先于默认。"""
        ctx = RouteContext(message="生成场景")
        result = route_mode(ctx)
        assert result.mode == "generate"
        assert result.source == "intent"


# ══════════════════════════════════════════════════════════
# RouteResult 结构
# ══════════════════════════════════════════════════════════

class TestRouteResult:
    """RouteResult 数据结构完整性。"""

    def test_result_has_all_fields(self):
        """RouteResult 包含 mode/source/reason 三个字段。"""
        ctx = RouteContext(message="hello")
        result = route_mode(ctx)
        assert hasattr(result, "mode")
        assert hasattr(result, "source")
        assert hasattr(result, "reason")
        assert isinstance(result.mode, str)
        assert isinstance(result.source, str)
        assert isinstance(result.reason, str)

    def test_source_values(self):
        """source 只能是 manual/context/intent/default 之一。"""
        valid_sources = {"manual", "context", "intent", "default"}
        # 测试各种场景
        for ctx in [
            RouteContext(message="hello", locked_mode="chat"),
            RouteContext(message="hello", workspace_just_pulled=True),
            RouteContext(message="生成"),
            RouteContext(message="hello"),
        ]:
            result = route_mode(ctx)
            assert result.source in valid_sources


# ══════════════════════════════════════════════════════════
# RouteContext 默认值
# ══════════════════════════════════════════════════════════

class TestRouteContext:
    """RouteContext 默认值正确性。"""

    def test_defaults(self):
        """所有可选字段有合理默认值。"""
        ctx = RouteContext(message="test")
        assert ctx.message == "test"
        assert ctx.locked_mode == ""
        assert ctx.current_page == ""
        assert ctx.last_run_failed is False
        assert ctx.workspace_just_pulled is False
        assert ctx.editing_scenario_id == ""
        assert ctx.scenario_never_run is False
        assert ctx.pending_vulnerabilities == 0


# ══════════════════════════════════════════════════════════
# INTENT_KEYWORDS 完整性
# ══════════════════════════════════════════════════════════

class TestIntentKeywords:
    """意图关键词表完整性。"""

    def test_all_modes_have_keywords(self):
        """4 个可路由模式都有关键词。"""
        for mode in ["generate", "debug", "audit", "analyze"]:
            assert mode in INTENT_KEYWORDS
            assert len(INTENT_KEYWORDS[mode]) > 0

    def test_chat_not_in_keywords(self):
        """chat 不在意图关键词表中（是默认兜底）。"""
        assert "chat" not in INTENT_KEYWORDS
