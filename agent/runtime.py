"""agent.runtime — 核心循环 LLM⇄tools⇄stop。

max_turns=12 熔断；kill 后重跑可从 JSONL 续会话。
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.llm_client import LLMClient
from agent.session import SessionManager
from agent.events import EventBus
from agent.mode_loader import load_mode, ModeDef
from agent.compactor import should_compact, compact
from agent.skill_loader import build_skills_xml

# 默认使用 MCP server 的全部工具
from mcp_server.tools import (
    spec_reader, scenario_tools, registry_query, draft_writer, validator, attribution, audit,
)

TOOL_MODULES = [spec_reader, scenario_tools, registry_query, draft_writer, validator, attribution, audit]

# info_pack 工具（G2-1）：延迟导入，避免循环依赖
try:
    from mcp_server.tools import info_pack as _info_pack_mod
    TOOL_MODULES.append(_info_pack_mod)
except ImportError:
    pass
ALL_TOOLS = []
for mod in TOOL_MODULES:
    ALL_TOOLS.extend(mod.TOOLS)
TOOL_NAME_TO_MODULE = {}
for mod in TOOL_MODULES:
    for tool in mod.TOOLS:
        TOOL_NAME_TO_MODULE[tool.name] = mod


# ══════════════════════════════════════════════════════════
# System Prompt 构建
# ══════════════════════════════════════════════════════════

# D8 修复：模板唯一事实源为 prompts/system.md.j2（原为内联副本，j2 文件成死文件）
_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "system.md.j2"

_FALLBACK_PROMPT_TEMPLATE = """你是 SpecGuard 场景生成助手。你的任务是根据用户需求，使用提供的工具生成合规的测试场景 YAML。

## 硬约束

1. 场景 YAML 必须符合格式规范（见下方）
2. doc.covers 中的 FR ID 必须在当前工作区的 spec.md 中存在（用 read_spec 验证）
3. flow 中的 tool 名称必须已注册（用 query_registry 查询）
4. verify 中的 oracle 名称必须已注册
5. 生成后必须调用 validate 工具校验
6. 校验通过后用 write_draft 写入 drafts/ 目录
7. 禁止编造不存在的 FR ID、tool 名称或 oracle 名称

## 格式规范

{{ format_spec }}

## 工作区规则（AGENTS.md 全量原文）

{{ agents_md }}

## 工作流程

1. 用 next_scenario_id 获取可用 ID
2. 用 read_spec / list_spec_files 了解需求对应的 FR
3. 用 query_registry 查询可用的 tool / oracle
4. 用 list_scenarios / read_scenario 参考已有场景
5. 生成场景 YAML
6. 用 validate 校验
7. 校验通过后用 write_draft 写入草稿
"""


def _load_prompt_template() -> str:
    """加载 system prompt 模板（prompts/system.md.j2 优先，缺失时回退内联兜底）。"""
    try:
        if _PROMPT_TEMPLATE_PATH.is_file():
            return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return _FALLBACK_PROMPT_TEMPLATE


def build_system_prompt(format_spec_text: str = "", agents_md: str = "",
                         mode: str = "", scenario_context: str = "") -> str:
    """构建 system prompt：format_spec + 工作区 AGENTS.md + 模式片段 + 场景上下文。"""
    if not format_spec_text:
        try:
            BACKEND_DIR = SG_ROOT / "workbench" / "backend"
            if str(BACKEND_DIR) not in sys.path:
                sys.path.insert(0, str(BACKEND_DIR))
            from services.format_spec import generate_format_spec_md
            format_spec_text = generate_format_spec_md()
        except Exception:
            format_spec_text = "（format_spec 加载失败，请用 query_registry 查询可用工具）"

    if not agents_md:
        try:
            from specstd.workspace import read_agents_md
            agents_md = read_agents_md() or "（无激活工作区或 AGENTS.md 不存在）"
        except Exception:
            agents_md = "（工作区未激活）"

    prompt = (_load_prompt_template()
              .replace("{{ format_spec }}", format_spec_text)
              .replace("{{ agents_md }}", agents_md))

    # 追加模式 prompt 片段
    if mode:
        mode_def = load_mode(mode)
        if mode_def and mode_def.prompt_fragment:
            prompt += f"\n\n## 当前模式：{mode}\n\n{mode_def.prompt_fragment}"

    # 追加场景上下文（基础信息包）
    if scenario_context:
        prompt += f"\n\n## 基础信息包\n\n{scenario_context}"

    # G3-2: 注入技能 XML 块
    skills_xml = build_skills_xml()
    if skills_xml:
        prompt += f"\n\n## 可用技能\n\n{skills_xml}"

    return prompt


# ══════════════════════════════════════════════════════════
# Agent Runtime
# ══════════════════════════════════════════════════════════

class AgentRuntime:
    """核心循环：LLM → tools → LLM → ... → stop。"""

    def __init__(self, llm: LLMClient, tools: list = None, max_turns: int = 12,
                 mode_name: str = ""):
        self.llm = llm
        self.max_turns = max_turns
        self.events = EventBus()
        self.mode_name = mode_name

        # 按模式过滤工具
        if tools is not None:
            # 显式传入优先
            self.tools = tools
        elif mode_name:
            mode_def = load_mode(mode_name)
            if mode_def and mode_def.tools:
                # 按白名单过滤
                self.tools = [t for t in ALL_TOOLS if t.name in mode_def.tools]
            elif mode_def and mode_def.tools == []:
                # 空列表 = 无工具（纯对话）
                self.tools = []
            else:
                self.tools = ALL_TOOLS
        else:
            self.tools = ALL_TOOLS

        # 重建 tool_map（只包含过滤后的工具）
        self._tool_map = {}
        for tool in self.tools:
            for mod in TOOL_MODULES:
                if tool in mod.TOOLS:
                    self._tool_map[tool.name] = mod
                    break

    def run(self, system_prompt: str, user_message: str,
            session: Optional[SessionManager] = None,
            session_id: Optional[str] = None) -> list[dict]:
        """执行核心循环，返回完整 messages 列表。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 恢复历史会话
        if session and session_id:
            history = session.load(session_id)
            if history:
                messages = history
                self.events.emit("state", resumed=True, session_id=session_id)

        openai_tools = self._to_openai_tools()

        for turn in range(self.max_turns):
            # G3-1: 超阈值时触发压缩
            if should_compact(messages, self.llm.max_context_tokens):
                messages = compact(messages, self.llm, self.llm.max_context_tokens)
                self.events.emit("compaction", message_count=len(messages))
            self.events.emit("state", turn=turn, max_turns=self.max_turns)

            message, usage = self.llm.chat(messages, openai_tools)

            # 发射事件（保留 reasoning_content 供前端显示）
            self.events.emit("assistant", message=message, turn=turn, usage=usage)

            # 清理消息格式后再追加到 messages（避免回传时 API 400）
            clean_message = {k: v for k, v in message.items() if k != "reasoning_content"}
            # 确保 content 是字符串（某些 API 返回 null）
            if clean_message.get("content") is None:
                clean_message["content"] = ""
            # 清理 tool_calls 格式（移除 index 等非标准字段）
            if clean_message.get("tool_calls"):
                cleaned_tc = []
                for tc in clean_message["tool_calls"]:
                    cleaned_tc.append({
                        "id": tc.get("id", ""),
                        "type": tc.get("type", "function"),
                        "function": tc.get("function", {}),
                    })
                clean_message["tool_calls"] = cleaned_tc
            messages.append(clean_message)

            # 检查是否有 tool_calls
            tool_calls = clean_message.get("tool_calls")
            if not tool_calls:
                break  # LLM 返回最终回复，停止

            # 执行工具调用
            for tc in tool_calls:
                result = self._execute_tool(tc)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                }
                messages.append(tool_msg)
                self.events.emit("tool_call", tool_call=tc, result=result, turn=turn)

            # 增量保存会话
            if session and session_id:
                session.save(session_id, messages)
        else:
            # G3-1: 熔断前也尝试压缩
            if should_compact(messages, self.llm.max_context_tokens):
                messages = compact(messages, self.llm, self.llm.max_context_tokens)
                self.events.emit("compaction", message_count=len(messages))
            messages.append({"role": "system", "content": f"[FUSE] 已达到 max_turns={self.max_turns}，自动停止。"})
            self.events.emit("state", fused=True, max_turns=self.max_turns)

        # 最终保存
        if session and session_id:
            session.save(session_id, messages, metrics=self.llm.get_stats())

        return messages

    def _to_openai_tools(self) -> list[dict]:
        """将 MCP Tool 转换为 OpenAI function calling 格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                }
            }
            for tool in self.tools
        ]

    def _execute_tool(self, tool_call: dict) -> str:
        """执行单个工具调用，返回结果文本。"""
        name = tool_call.get("function", {}).get("name", "")
        raw_args = tool_call.get("function", {}).get("arguments", "{}")

        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            return f"错误：参数 JSON 解析失败: {raw_args}"

        mod = self._tool_map.get(name)
        if not mod:
            return f"未知工具: {name}"

        try:
            result = asyncio.run(mod.handle(name, arguments))
            return result[0].text if result else "（无输出）"
        except Exception as e:
            return f"工具执行异常: {e}"
