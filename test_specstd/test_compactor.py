"""test_compactor — agent.compactor 单元测试（A-2 验收）。

覆盖验收标准：
1. should_compact 过滤逻辑正确（or→and 修复）
2. estimate_tokens 对中文正确
3. estimate_tokens 对英文正确
4. estimate_tokens 对中英文混合正确
5. max_context_tokens=0 时回退消息数阈值（向后兼容）
6. 构造 50K token 中文消息，触发压缩
7. estimate_message_tokens（含 content + tool_calls）
8. 压缩后保留的尾部消息 token ≤ max_context_tokens * 0.25
"""

import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.compactor import (
    estimate_tokens,
    estimate_message_tokens,
    should_compact,
    compact,
    _calc_keep_count,
    COMPACTION_RATIO,
    MIN_MESSAGES_BEFORE_COMPACT,
    COMPACTION_THRESHOLD,
)


# ══════════════════════════════════════════════════════════
# 验收 2: estimate_tokens 中文
# ══════════════════════════════════════════════════════════

class TestEstimateTokensChinese:
    """中文 token 估算（修正后）。"""

    def test_chinese_basic(self):
        """你好世界 → 4 字 × 1.5 = 6 token。"""
        assert estimate_tokens("你好世界") >= 4

    def test_chinese_exact(self):
        """4 个中文字 → int(4 * 1.5) = 6。"""
        assert estimate_tokens("你好世界") == 6

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_chinese_punctuation(self):
        """中文标点（、，。等）也按 1.5 token 计。"""
        text = "你好，世界。"  # 6 个 CJK 字符（含标点）
        assert estimate_tokens(text) >= 6  # 6 × 1.5 = 9

    def test_fullwidth(self):
        """全角字符按中文计。"""
        text = "ＡＢＣ"  # 3 个全角字符
        assert estimate_tokens(text) >= 3  # 3 × 1.5 = 4


# ══════════════════════════════════════════════════════════
# 验收 3: estimate_tokens 英文
# ══════════════════════════════════════════════════════════

class TestEstimateTokensEnglish:
    """英文 token 估算。"""

    def test_english_basic(self):
        """hello world → 11 chars / 4 = 2.75 → int = 2。"""
        assert estimate_tokens("hello world") == 2

    def test_english_short(self):
        """hi → 2 chars / 4 = 0.5 → int = 0, max(1, 0) = 1。"""
        assert estimate_tokens("hi") == 1

    def test_english_long(self):
        """long text → len/4。"""
        text = "a" * 100
        assert estimate_tokens(text) == 25  # 100/4 = 25


# ══════════════════════════════════════════════════════════
# 验收 4: estimate_tokens 中英文混合
# ══════════════════════════════════════════════════════════

class TestEstimateTokensMixed:
    """中英文混合 token 估算。"""

    def test_mixed_basic(self):
        """你好 hello → 2 中文 × 1.5 + 6 英文 / 4 = 3 + 1.5 = 4.5 → int = 4。"""
        result = estimate_tokens("你好 hello")
        assert result >= 4
        assert result == 4

    def test_mixed_with_punctuation(self):
        """你好，world！ → 中文部分（你好，！含全角）+ 英文部分。"""
        result = estimate_tokens("你好，world！")
        # 你好，！ = 4 CJK chars × 1.5 = 6
        # world = 5 chars / 4 = 1.25 → int = 1
        # total = int(6 + 1.25) = int(7.25) = 7
        assert result >= 6


# ══════════════════════════════════════════════════════════
# 验收 1: should_compact or→and bug 修复
# ══════════════════════════════════════════════════════════

def _make_messages(n_conversation: int) -> list[dict]:
    """构造消息列表：1 条 system 首条 + 1 条 compaction_summary + n 条对话消息。"""
    msgs = [
        {"role": "system", "content": "你是 SpecGuard 助手。"},
        {"role": "system", "_type": "compaction_summary", "content": "历史摘要..."},
    ]
    for i in range(n_conversation):
        msgs.append({"role": "user", "content": f"消息 {i}"})
    return msgs


class TestShouldCompactBugFix:
    """【bug 修复】普通 system 与 compaction_summary 被正确排除。"""

    def test_system_first_excluded_at_boundary(self):
        """16 条对话 + system 首条：修复后 16 not > 16 → 不触发。

        旧 bug：system 首条被错误计入 → 17 > 16 → 触发（错误）。
        修复后：system 首条被排除 → 16 not > 16 → 不触发（正确）。
        """
        msgs = _make_messages(16)
        assert not should_compact(msgs)

    def test_above_threshold_triggers(self):
        """17 条对话 > 16 → 触发。"""
        msgs = _make_messages(17)
        assert should_compact(msgs)

    def test_compaction_summary_excluded(self):
        """compaction_summary 被正确排除，不计入消息数。"""
        # 16 条对话 + 2 条 system（首条 + summary）
        # 修复后：16 not > 16 → 不触发
        msgs = _make_messages(16)
        assert not should_compact(msgs)

    def test_only_system_no_compact(self):
        """只有 system 消息不触发。"""
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "system", "_type": "compaction_summary", "content": "summary"},
        ]
        assert not should_compact(msgs)

    def test_min_messages_guard(self):
        """消息数 < MIN_MESSAGES_BEFORE_COMPACT 不触发。"""
        msgs = _make_messages(7)  # 7 < 8
        assert not should_compact(msgs)


# ══════════════════════════════════════════════════════════
# 验收 5: max_context_tokens=0 回退消息数阈值
# ══════════════════════════════════════════════════════════

class TestShouldCompactFallback:
    """max_context_tokens=0 时回退消息数阈值（向后兼容）。"""

    def test_fallback_above_threshold(self):
        """无 max_context_tokens 时用消息数阈值，超过触发。"""
        msgs = [{"role": "system", "content": "system"}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"msg {i}"})
        assert should_compact(msgs, max_context_tokens=0)

    def test_fallback_below_threshold(self):
        """消息数不足不触发。"""
        msgs = [{"role": "system", "content": "system"}]
        for i in range(10):
            msgs.append({"role": "user", "content": f"msg {i}"})
        assert not should_compact(msgs, max_context_tokens=0)

    def test_default_param_is_zero(self):
        """不传 max_context_tokens 时默认 0，回退消息数阈值。"""
        msgs = [{"role": "system", "content": "system"}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"msg {i}"})
        # 不传第二参数，应回退消息数阈值
        assert should_compact(msgs)

    def test_min_guard_with_tokens(self):
        """消息数 < 8 但 token 超标 → 仍不触发（保底）。"""
        msgs = [{"role": "system", "content": "system"}]
        for i in range(7):
            msgs.append({"role": "user", "content": "中" * 10000})
        # 7 条对话 < 8 → 不触发
        assert not should_compact(msgs, max_context_tokens=10000)


# ══════════════════════════════════════════════════════════
# 验收 6: 50K token 中文消息触发压缩
# ══════════════════════════════════════════════════════════

class TestTokenLevelCompaction:
    """token 级阈值触发压缩。"""

    def test_50k_chinese_triggers_compact(self):
        """构造 50K+ token 中文消息，触发压缩。"""
        max_ctx = 65536  # 64K context window
        threshold = int(max_ctx * COMPACTION_RATIO)  # 45875 tokens
        msgs = [{"role": "system", "content": "你是 SpecGuard 助手。"}]
        for i in range(10):
            msgs.append({"role": "user", "content": "中" * 4000})
            msgs.append({"role": "assistant", "content": "中" * 4000})
        # 20 conversation messages, each ~6004 tokens → ~120080 > 45875
        assert should_compact(msgs, max_context_tokens=max_ctx)

    def test_below_token_threshold_no_compact(self):
        """token 未达 70% 阈值不触发。"""
        max_ctx = 65536  # 70% = 45875
        msgs = [{"role": "system", "content": "system"}]
        for i in range(10):
            msgs.append({"role": "user", "content": f"short message {i}"})
        assert not should_compact(msgs, max_context_tokens=max_ctx)

    def test_exact_threshold(self):
        """恰好达到 70% 阈值触发。"""
        max_ctx = 1000
        threshold = int(max_ctx * COMPACTION_RATIO)  # 700
        msgs = [{"role": "system", "content": "system"}]
        # 8 messages × ~94 tokens = ~752 >= 700
        for i in range(8):
            msgs.append({"role": "user", "content": "中" * 60})  # 60 × 1.5 + 4 = 94
        assert should_compact(msgs, max_context_tokens=max_ctx)


# ══════════════════════════════════════════════════════════
# 验收 7: estimate_message_tokens
# ══════════════════════════════════════════════════════════

class TestEstimateMessageTokens:
    """单条消息 token 估算。"""

    def test_simple_message(self):
        msg = {"role": "user", "content": "你好世界"}
        # 4 (metadata) + 6 (content) = 10
        assert estimate_message_tokens(msg) == 10

    def test_empty_content(self):
        msg = {"role": "assistant", "content": ""}
        assert estimate_message_tokens(msg) == 4

    def test_with_tool_calls(self):
        msg = {
            "role": "assistant",
            "content": "调用工具",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_spec",
                        "arguments": '{"path": "specs/module1/spec.md"}',
                    }
                }
            ],
        }
        tokens = estimate_message_tokens(msg)
        # 4 + estimate_tokens("调用工具") + estimate_tokens(arguments)
        assert tokens > 10

    def test_none_content(self):
        msg = {"role": "assistant", "content": None}
        assert estimate_message_tokens(msg) == 4


# ══════════════════════════════════════════════════════════
# 验收 8: compact 后尾部消息 token ≤ max_context_tokens * 0.25
# ══════════════════════════════════════════════════════════

class TestCompactKeepBudget:
    """compact() 压缩后保留的尾部消息 token ≤ max_context_tokens * 0.25。"""

    def test_keep_within_budget(self):
        """压缩后尾部消息 token 数不超过预算。"""
        max_ctx = 10000
        budget = int(max_ctx * 0.25)  # 2500 tokens
        msgs = [{"role": "system", "content": "system prompt"}]
        for i in range(30):
            msgs.append({"role": "user", "content": f"用户消息 {i} " + "中" * 200})
            msgs.append({"role": "assistant", "content": f"助手回复 {i} " + "中" * 200})
        result = compact(msgs, llm=None, max_context_tokens=max_ctx)

        kept = [
            m for m in result
            if not (m.get("role") == "system" and m.get("_type") in (None, "compaction_summary"))
        ]
        kept_tokens = sum(estimate_message_tokens(m) for m in kept)
        assert kept_tokens <= budget, f"保留 {kept_tokens} tokens 超预算 {budget}"

    def test_keep_at_least_4(self):
        """至少保留 4 条消息（2 轮）。"""
        max_ctx = 1000
        msgs = [{"role": "system", "content": "system"}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"msg {i}"})
            msgs.append({"role": "assistant", "content": f"reply {i}"})
        result = compact(msgs, llm=None, max_context_tokens=max_ctx)
        kept = [
            m for m in result
            if not (m.get("role") == "system" and m.get("_type") in (None, "compaction_summary"))
        ]
        assert len(kept) >= 4

    def test_system_preserved(self):
        """压缩后 system 首条保留。"""
        max_ctx = 1000
        msgs = [{"role": "system", "content": "original system prompt"}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"msg {i}"})
            msgs.append({"role": "assistant", "content": f"reply {i}"})
        result = compact(msgs, llm=None, max_context_tokens=max_ctx)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "original system prompt"
        assert "_type" not in result[0]

    def test_compaction_summary_present(self):
        """压缩后包含 compaction_summary。"""
        max_ctx = 100  # 小窗口让 token 阈值容易触发
        msgs = [{"role": "system", "content": "system"}]
        for i in range(20):
            msgs.append({"role": "user", "content": "中" * 10})  # ~19 tokens each
        # 20 × 19 = 380 tokens + system ~10 = 390 > 70 (70% of 100)
        result = compact(msgs, llm=None, max_context_tokens=max_ctx)
        summaries = [m for m in result if m.get("_type") == "compaction_summary"]
        assert len(summaries) == 1

    def test_no_compact_when_below_threshold(self):
        """消息不足时不压缩，原样返回。"""
        msgs = [{"role": "system", "content": "system"}]
        for i in range(5):
            msgs.append({"role": "user", "content": f"msg {i}"})
        result = compact(msgs, llm=None, max_context_tokens=10000)
        assert result == msgs  # 原样返回


# ══════════════════════════════════════════════════════════
# K-015：压缩摘要嵌套修复（生产佐证：7 个空「历史摘要」头 + 16 个嵌套「压缩摘要」）
# ══════════════════════════════════════════════════════════

class TestSummaryNesting:
    def _big_msgs(self, n=20):
        msgs = [{"role": "system", "content": "system"}]
        for i in range(n):
            msgs.append({"role": "user", "content": "中" * 10})  # ~19 tokens each
        return msgs

    def test_repeated_compaction_single_history_header(self):
        """连续两次压缩：只保留一个「## 历史摘要」头、一个「## 压缩摘要」段。"""
        r1 = compact(self._big_msgs(), llm=None, max_context_tokens=100)
        msgs = r1 + [{"role": "user", "content": "中" * 10} for _ in range(15)]
        r2 = compact(msgs, llm=None, max_context_tokens=100)
        summaries = [m for m in r2 if m.get("_type") == "compaction_summary"]
        assert len(summaries) == 1
        content = summaries[0]["content"]
        assert content.count("## 历史摘要") == 1
        assert content.count("## 压缩摘要") == 1

    def test_resumed_summary_detected_without_type(self):
        """resume 形态（_type 被 session.load 剥离）的摘要仍被识别保留，不当普通内容丢弃。"""
        r1 = compact(self._big_msgs(), llm=None, max_context_tokens=100)
        # 模拟 session.load：剥离 _type，compaction_summary 角色改 system
        loaded = []
        for m in r1:
            m = dict(m)
            if m.pop("_type", None) == "compaction_summary":
                m["role"] = "system"
            loaded.append(m)
        msgs = loaded + [{"role": "user", "content": "中" * 10} for _ in range(15)]
        r2 = compact(msgs, llm=None, max_context_tokens=100)
        summaries = [m for m in r2 if m.get("_type") == "compaction_summary"]
        assert len(summaries) == 1
        # 旧摘要经历史段保留（而非被静默丢弃或重复嵌套）
        assert summaries[0]["content"].count("## 历史摘要") == 1

    def test_history_cap(self):
        """历史段超过软上限时截断（防嵌套膨胀）。"""
        from agent.compactor import _generate_summary, _HISTORY_CAP
        existing = {"role": "system", "_type": "compaction_summary",
                    "content": "## 历史摘要\n\n## 压缩摘要\n" + "长" * 5000}
        text = _generate_summary([], existing, None)
        assert text.count("## 历史摘要") == 1
        assert len(text) < _HISTORY_CAP + 500


# ══════════════════════════════════════════════════════════
# _calc_keep_count
# ══════════════════════════════════════════════════════════

class TestCalcKeepCount:
    """动态保留消息数计算。"""

    def test_within_budget(self):
        """消息 token 总和未超预算 → 全部保留（需 >4 条绕过 min 4）。"""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "hey"},
            {"role": "assistant", "content": "yo"},
            {"role": "user", "content": "ok"},
        ]
        # 5 messages, each ~5 tokens, reserve 100 → all fit, count=5, max(5,4)=5
        assert _calc_keep_count(msgs, 100) == 5

    def test_exceeds_budget(self):
        """消息 token 超预算 → 从尾部截断（需 >4 条验证截断）。"""
        msgs = [
            {"role": "user", "content": "中" * 100},      # ~154 tokens
            {"role": "assistant", "content": "中" * 100},  # ~154 tokens
            {"role": "user", "content": "中" * 100},      # ~154 tokens
            {"role": "assistant", "content": "短"},        # ~5 tokens
            {"role": "user", "content": "短"},             # ~5 tokens
            {"role": "assistant", "content": "短"},        # ~5 tokens
            {"role": "user", "content": "短"},             # ~5 tokens
            {"role": "assistant", "content": "短"},        # ~5 tokens
        ]
        # reserve 160: 短(5)→5, 短(5)→10, 短(5)→15, 短(5)→20, 短(5)→25
        # next 中*100(154): 25+154=179 > 160 → stop; count=5, max(5,4)=5
        assert _calc_keep_count(msgs, 160) == 5

    def test_min_4(self):
        """至少返回 4（即使没消息能放入预算）。"""
        msgs = [
            {"role": "user", "content": "中" * 1000},
            {"role": "assistant", "content": "中" * 1000},
        ]
        result = _calc_keep_count(msgs, 100)
        assert result >= 4  # max(count, 4)
