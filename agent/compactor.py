"""agent.compactor — 会话上下文压缩器（G3-1）。

当对话超过 token 阈值（占 max_context_tokens 的 70%）时，自动压缩旧消息为摘要。
保留最近消息（按 token 预算动态计算），确保对话连续性。
摘要包含文件操作记录（读了哪些 spec、写了哪些 draft）。

压缩后的摘要消息标记为 _type: "compaction_summary"，存入 JSONL。
"""

from __future__ import annotations

import json
from typing import Optional

# 压缩阈值：超过此消息数时触发压缩（向后兼容：max_context_tokens=0 时回退到此阈值）
COMPACTION_THRESHOLD = 16  # 约 8 轮
# 保留最近 N 条原始消息（约 3-5 轮；向后兼容：无 max_context_tokens 时的默认值）
KEEP_RECENT = 10
# token 级阈值占比（占 max_context_tokens 的 70%）
COMPACTION_RATIO = 0.7
# 触发压缩的最低消息数（保底，防止消息太少时误触发）
MIN_MESSAGES_BEFORE_COMPACT = 8
# 文件操作记录中的关键工具
FILE_READ_TOOLS = {"read_spec", "read_info_pack", "list_spec_files", "read_scenario"}
FILE_WRITE_TOOLS = {"write_draft", "add_to_info_pack"}
VALIDATE_TOOLS = {"validate"}

# 摘要尾部标记（识别 resume 形态的摘要：session.load 会剥离 _type，只能靠内容标记）
SUMMARY_END_MARKER = "--- 以上为压缩摘要，以下是最近对话 ---"
# K-015: 历史段软上限（字符），防多次压缩嵌套膨胀
_HISTORY_CAP = 2000


def _is_summary_msg(m: dict) -> bool:
    """识别压缩摘要消息（兼容 resume 后 _type 被 session.load 剥离的形态）。

    K-015 修复：resume 后旧摘要无 _type，若只靠 _type 识别会被当普通内容——
    既丢失保留路径、又在后续压缩中被重复嵌套（生产会话 7 个空「历史摘要」头佐证）。
    """
    if m.get("_type") == "compaction_summary":
        return True
    return (m.get("role") == "system"
            and SUMMARY_END_MARKER in str(m.get("content", "")))


def estimate_tokens(text: str) -> int:
    """估算文本 token 数（区分中英文）。

    中文 1 字 ≈ 1.5 token（GPT 系列保守估计）
    英文/数字 4 字符 ≈ 1 token
    """
    if not text:
        return 0
    chinese_chars = sum(
        1 for c in text
        if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f' or '\uff00' <= c <= '\uffef'
    )
    non_chinese = len(text) - chinese_chars
    estimated = int(chinese_chars * 1.5 + non_chinese / 4)
    return max(1, estimated)


def estimate_message_tokens(message: dict) -> int:
    """估算单条消息的 token 数（含 content + tool_calls）。"""
    total = 4  # 每条消息的元数据开销
    content = message.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        for part in content:
            total += estimate_tokens(str(part))
    for tc in message.get("tool_calls", []) or []:
        args = tc.get("function", {}).get("arguments", "")
        total += estimate_tokens(args) if isinstance(args, str) else estimate_tokens(str(args))
    return total


def _calc_keep_count(conversation: list[dict], reserve_tokens: int) -> int:
    """从尾部累计，保留不超过 reserve_tokens 的消息数。"""
    acc = 0
    count = 0
    for m in reversed(conversation):
        t = estimate_message_tokens(m)
        if acc + t > reserve_tokens:
            break
        acc += t
        count += 1
    return max(count, 4)  # 至少保留 4 条（2 轮）


def should_compact(messages: list[dict], max_context_tokens: int = 0) -> bool:
    """判断是否需要压缩（token 级阈值 + 消息数保底）。

    Args:
        messages: 完整消息列表
        max_context_tokens: 模型上下文窗口大小（0 时回退消息数阈值）
    """
    # 【修复 bug】正确排除 system 首条与 compaction_summary（or → and）
    conversation_msgs = [
        m for m in messages
        if not (m.get("role") == "system" and m.get("_type") in (None, "compaction_summary"))
    ]
    if len(conversation_msgs) < MIN_MESSAGES_BEFORE_COMPACT:
        return False

    if max_context_tokens <= 0:
        # 回退：消息数阈值（向后兼容）
        return len(conversation_msgs) > COMPACTION_THRESHOLD

    estimated = sum(estimate_message_tokens(m) for m in messages)
    return estimated >= int(max_context_tokens * COMPACTION_RATIO)


def compact(messages: list[dict], llm=None, max_context_tokens: int = 0) -> list[dict]:
    """压缩会话消息列表。

    1. 保留 system 首条（原始 system prompt）
    2. 保留已有的 compaction_summary（如有）
    3. 生成新的 compaction_summary（汇总被压缩的消息）
    4. 保留最近消息（按 token 预算动态计算，回退 KEEP_RECENT）

    Args:
        messages: 完整消息列表
        llm: 可选的 LLMClient（用于生成摘要；None 时用启发式摘要）
        max_context_tokens: 模型上下文窗口大小（0 时回退固定 KEEP_RECENT）

    Returns:
        压缩后的消息列表
    """
    if not should_compact(messages, max_context_tokens):
        return messages

    # 分离 system 首条
    system_msg = None
    rest = []
    for m in messages:
        if m.get("role") == "system" and not m.get("_type"):
            if system_msg is None:
                system_msg = m
                continue
        rest.append(m)

    # 找到已有的 compaction_summary（K-015：兼容 resume 形态）
    existing_summary = None
    conversation = []
    for m in rest:
        if _is_summary_msg(m):
            existing_summary = m
        else:
            conversation.append(m)

    # 分割：旧消息（待压缩）+ 最近消息（保留）
    # 按 token 预算动态计算保留条数（无 max_context_tokens 时回退固定值）
    if max_context_tokens > 0:
        reserve_tokens = int(max_context_tokens * 0.25)
        keep_count = _calc_keep_count(conversation, reserve_tokens)
    else:
        keep_count = KEEP_RECENT

    if len(conversation) <= keep_count:
        return messages  # 不需要压缩

    # 调整分割点到安全边界：确保不在 assistant→tool 配对中间断开
    # 安全边界 = 前一条不是带 tool_calls 的 assistant，且当前位置不是 tool 消息
    split_idx = len(conversation) - keep_count
    while split_idx > 0:
        curr = conversation[split_idx]
        prev = conversation[split_idx - 1] if split_idx > 0 else None
        # 如果当前位置是 tool 消息，向前移到对应的 assistant
        if curr.get("role") == "tool":
            split_idx -= 1
            continue
        # 如果前一条是带 tool_calls 的 assistant，向前移到该 assistant 之前
        if prev and prev.get("role") == "assistant" and prev.get("tool_calls"):
            split_idx -= 1
            continue
        # 安全分割点
        break

    to_compress = conversation[:split_idx]
    to_keep = conversation[split_idx:]

    # 生成摘要
    summary_text = _generate_summary(to_compress, existing_summary, llm)

    # 构建压缩后的消息列表
    result = []
    if system_msg:
        result.append(system_msg)

    # 写入 compaction_summary
    result.append({
        "role": "system",
        "_type": "compaction_summary",
        "content": summary_text,
    })

    # 保留最近消息
    result.extend(to_keep)

    # 后置验证：修复 compaction 可能导致的 tool/assistant 配对断裂
    # DeepSeek API 要求：
    # 1. 每个 tool 消息前必须有带 tool_calls 的 assistant 消息
    # 2. 每个带 tool_calls 的 assistant 消息后必须有足够的 tool 消息
    # 用计数器跟踪待匹配的 tool 消息数，正确处理多个 tool 消息的情况
    validated = []
    pending_tc = 0  # 前一个 assistant 还需要多少个 tool 消息
    for i, m in enumerate(result):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            # 检查后续连续 tool 消息数量
            tc_count = len(m["tool_calls"])
            tool_count = 0
            for j in range(i + 1, len(result)):
                if result[j].get("role") == "tool":
                    tool_count += 1
                else:
                    break
            if tool_count < tc_count:
                # 缺少 tool 消息，移除 tool_calls（转为普通 assistant）
                m = {k: v for k, v in m.items() if k != "tool_calls"}
                if not m.get("content"):
                    m["content"] = "（工具调用已省略）"
                pending_tc = 0
            else:
                pending_tc = tc_count
            validated.append(m)
        elif m.get("role") == "tool":
            if pending_tc > 0:
                # 属于前一个 assistant 的 tool 消息
                pending_tc -= 1
                validated.append(m)
            else:
                # 孤立的 tool 消息，转为 system 消息
                validated.append({
                    "role": "system",
                    "content": f"[工具结果] {str(m.get('content', ''))[:300]}",
                })
        else:
            pending_tc = 0
            validated.append(m)

    return validated


def _generate_summary(to_compress: list[dict],
                      existing_summary: Optional[dict],
                      llm=None) -> str:
    """生成压缩摘要。

    启发式方法（无需 LLM 调用）：
    - 提取文件操作记录（读了哪些文件、写了哪些草稿、做了哪些校验）
    - 提取用户意图和关键决策
    - 保留已有的摘要内容
    """
    parts = []

    # 保留已有摘要（K-015：合并为单一历史段——剥离历轮叠加的标题行与尾部标记，
    # 软上限防嵌套膨胀；修复前每轮压缩多叠一个「## 历史摘要」空头）
    if existing_summary and existing_summary.get("content"):
        prev = str(existing_summary["content"]).replace(SUMMARY_END_MARKER, "")
        prev_lines = [ln for ln in prev.splitlines()
                      if ln.strip() not in ("## 历史摘要", "## 压缩摘要")]
        prev = "\n".join(prev_lines).strip()
        if prev:
            if len(prev) > _HISTORY_CAP:
                prev = "……（更早历史已截断）\n" + prev[-_HISTORY_CAP:]
            parts.append("## 历史摘要\n")
            parts.append(prev)
            parts.append("")

    # 提取文件操作
    files_read = []
    files_written = []
    validations = []
    tool_summaries = []

    for msg in to_compress:
        role = msg.get("role", "")

        # 提取工具调用
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg.get("tool_calls", []):
                tool_name = tc.get("function", {}).get("name", "")
                raw_args = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                # T-982：合并工具按 action 归一为逻辑 id（收敛前词汇），
                # 历史会话消息（legacy 名）经 logical_id 原样透传
                from mcp_server.tools.tool_meta import logical_id as _lid
                tool_name = _lid(tool_name, str(args.get("action", "") or ""))

                if tool_name in FILE_READ_TOOLS:
                    path = args.get("path", args.get("scenario_id", ""))
                    if path and path not in files_read:
                        files_read.append(f"{tool_name}({path})")
                elif tool_name in FILE_WRITE_TOOLS:
                    fname = args.get("filename", args.get("path", ""))
                    if fname and fname not in files_written:
                        files_written.append(f"{tool_name}({fname})")
                elif tool_name in VALIDATE_TOOLS:
                    validations.append(tool_name)
                else:
                    tool_summaries.append(tool_name)

        # 提取工具结果中的关键信息
        if role == "tool":
            content = str(msg.get("content", ""))
            # 检查是否包含错误
            if "错误" in content or "ERROR" in content or "FAIL" in content:
                tool_summaries.append(f"工具返回错误: {content[:100]}")

    # 构建摘要文本
    parts.append("## 压缩摘要\n")

    if files_read:
        parts.append("### 已读文件")
        for f in files_read:
            parts.append(f"- {f}")
        parts.append("")

    if files_written:
        parts.append("### 已写文件")
        for f in files_written:
            parts.append(f"- {f}")
        parts.append("")

    if validations:
        parts.append(f"### 校验操作：{', '.join(validations)}")
        parts.append("")

    if tool_summaries:
        unique_tools = list(dict.fromkeys(tool_summaries))
        parts.append(f"### 其他工具调用：{', '.join(unique_tools[:10])}")
        parts.append("")

    # 提取用户消息摘要
    user_messages = [
        m for m in to_compress
        if m.get("role") == "user" and m.get("content")
    ]
    if user_messages:
        parts.append("### 用户意图")
        for i, m in enumerate(user_messages, 1):
            content = str(m.get("content", ""))[:200]
            parts.append(f"{i}. {content}")
        parts.append("")

    # 提取助手关键回复
    assistant_replies = [
        m for m in to_compress
        if m.get("role") == "assistant" and m.get("content")
        and not m.get("tool_calls")  # 只取纯文本回复
    ]
    if assistant_replies:
        parts.append("### 助手关键回复")
        for i, m in enumerate(assistant_replies, 1):
            content = str(m.get("content", ""))[:200]
            parts.append(f"{i}. {content}")
        parts.append("")

    parts.append(SUMMARY_END_MARKER)

    return "\n".join(parts)
