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

# 默认使用 MCP server 的全部工具
from mcp_server.tools import (
    spec_reader, scenario_tools, registry_query, draft_writer, validator, attribution,
)

TOOL_MODULES = [spec_reader, scenario_tools, registry_query, draft_writer, validator, attribution]
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

_SYSTEM_PROMPT_TEMPLATE = """你是 SpecGuard 场景生成助手。你的任务是根据用户需求，使用提供的工具生成合规的测试场景 YAML。

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


def build_system_prompt(format_spec_text: str = "", agents_md: str = "") -> str:
    """构建 system prompt：format_spec + 工作区 AGENTS.md 全量注入。"""
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

    return (_SYSTEM_PROMPT_TEMPLATE
            .replace("{{ format_spec }}", format_spec_text)
            .replace("{{ agents_md }}", agents_md))


# ══════════════════════════════════════════════════════════
# Agent Runtime
# ══════════════════════════════════════════════════════════

class AgentRuntime:
    """核心循环：LLM → tools → LLM → ... → stop。"""

    def __init__(self, llm: LLMClient, tools: list = None, max_turns: int = 12):
        self.llm = llm
        self.max_turns = max_turns
        self.events = EventBus()
        self.tools = tools if tools is not None else ALL_TOOLS
        self._tool_map = dict(TOOL_NAME_TO_MODULE)

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
            self.events.emit("state", turn=turn, max_turns=self.max_turns)

            message, usage = self.llm.chat(messages, openai_tools)
            messages.append(message)

            self.events.emit("assistant", message=message, turn=turn, usage=usage)

            # 检查是否有 tool_calls
            tool_calls = message.get("tool_calls")
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
