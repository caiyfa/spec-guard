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
    spec_reader, scenario_tools, registry_query, draft_writer, validator, attribution, audit, meta,
)

TOOL_MODULES = [spec_reader, scenario_tools, registry_query, draft_writer, validator, attribution, audit, meta]

# Meta 工具常驻所有模式（H-3/H-4）
META_TOOLS = meta.META_TOOL_NAMES

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

        # H-4: 待办状态
        self._todos: list[dict] = []
        # H-3: 模式切换注入 + 工具集重建标记
        self._pending_mode_notice: str = ""
        self._tools_dirty: bool = False
        # 会话引用（供 meta 工具持久化用）
        self._session: Optional[SessionManager] = None
        self._session_id: Optional[str] = None

        # 按模式过滤工具（meta 工具常驻所有模式）
        if tools is not None:
            # 显式传入优先
            self.tools = tools
        elif mode_name:
            mode_def = load_mode(mode_name)
            if mode_def:
                # meta 工具常驻所有模式（含 tools=[] 的 chat 模式）
                allowed = set(mode_def.tools) | META_TOOLS
                self.tools = [t for t in ALL_TOOLS if t.name in allowed]
            else:
                self.tools = ALL_TOOLS
        else:
            self.tools = ALL_TOOLS

        # 重建 tool_map（meta 工具在 _execute_tool 中拦截，不映射到模块）
        self._tool_map = {}
        self._rebuild_tool_map()

    def run(self, system_prompt: str, user_message: str,
            session: Optional[SessionManager] = None,
            session_id: Optional[str] = None) -> list[dict]:
        """执行核心循环，返回完整 messages 列表。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        self._session = session
        self._session_id = session_id

        # 恢复历史会话
        if session and session_id:
            history = session.load(session_id)
            if history:
                messages = history
                # H-4: 恢复待办状态
                todos = session.load_todos(session_id)
                if todos is not None:
                    self._todos = todos
                self.events.emit("state", resumed=True, session_id=session_id)

        openai_tools = self._to_openai_tools()

        for turn in range(self.max_turns):
            # H-3: 模式切换后重建工具集
            if self._tools_dirty:
                openai_tools = self._to_openai_tools()
                self._tools_dirty = False

            # H-3: 注入模式切换通知（不动首条 system prompt）
            if self._pending_mode_notice:
                messages.append({"role": "system", "content": self._pending_mode_notice})
                self._pending_mode_notice = None

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
                session.save(session_id, messages, todos=self._todos)
        else:
            # G3-1: 熔断前也尝试压缩
            if should_compact(messages, self.llm.max_context_tokens):
                messages = compact(messages, self.llm, self.llm.max_context_tokens)
                self.events.emit("compaction", message_count=len(messages))
            messages.append({"role": "system", "content": f"[FUSE] 已达到 max_turns={self.max_turns}，自动停止。"})
            self.events.emit("state", fused=True, max_turns=self.max_turns)

        # 最终保存
        if session and session_id:
            session.save(session_id, messages, metrics=self.llm.get_stats(), todos=self._todos)

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

        # ── Meta 工具特殊处理（不通过 mod.handle）──
        if name == "todo_write":
            return self._handle_todo_write(arguments)
        if name == "switch_mode":
            return self._handle_switch_mode(arguments)

        # ── 常规工具 ──
        mod = self._tool_map.get(name)
        if not mod:
            return f"未知工具: {name}"

        try:
            result = asyncio.run(mod.handle(name, arguments))
            return result[0].text if result else "（无输出）"
        except Exception as e:
            return f"工具执行异常: {e}"

    # ══════════════════════════════════════════════════════════
    # H-3/H-4: Meta 工具处理 + 模式切换
    # ══════════════════════════════════════════════════════════

    def _rebuild_tool_map(self):
        """重建 tool_map（meta 工具在 _execute_tool 中拦截，不映射到模块）。"""
        self._tool_map = {}
        for tool in self.tools:
            if tool.name in META_TOOLS:
                continue  # meta 工具在 _execute_tool 中拦截
            for mod in TOOL_MODULES:
                if tool in mod.TOOLS:
                    self._tool_map[tool.name] = mod
                    break

    def _handle_todo_write(self, arguments: dict) -> str:
        """H-4: 处理 todo_write — 更新待办 + emit 事件 + 持久化。"""
        todos = arguments.get("todos", [])
        if not isinstance(todos, list):
            return "错误：todos 必须是数组"

        # 校验每条待办
        for todo in todos:
            if not isinstance(todo, dict):
                return "错误：每条待办必须是对象"
            if not todo.get("id") or not todo.get("title"):
                return "错误：每条待办必须包含 id 和 title"
            status = todo.get("status", "pending")
            if status not in ("pending", "in_progress", "done", "blocked"):
                return f"错误：无效的 status: {status}"

        self._todos = todos
        self.events.emit("todo_update", todos=self._todos)

        # 持久化到会话 JSONL
        if self._session and self._session_id:
            try:
                self._session.save_todos(self._session_id, self._todos)
            except Exception:
                pass  # 持久化失败不影响运行时

        return f"待办已更新（{len(self._todos)} 项）"

    def _handle_switch_mode(self, arguments: dict) -> str:
        """H-3: 处理 switch_mode — mid-run 模式切换。"""
        new_mode = arguments.get("mode", "")
        reason = arguments.get("reason", "")

        if not new_mode:
            return "错误：缺少 mode 参数"
        if not reason:
            return "错误：缺少 reason 参数"

        # 验证模式存在
        mode_def = load_mode(new_mode)
        if not mode_def:
            return f"错误：未知模式: {new_mode}"

        if new_mode == self.mode_name:
            return f"已在 {new_mode} 模式，无需切换"

        old_mode = self.mode_name
        self._switch_mode(new_mode, reason, mode_def)

        return f"已切换到 {new_mode} 模式。{reason}"

    def _switch_mode(self, new_mode: str, reason: str, mode_def=None):
        """mid-run 模式切换：注入新 system 消息 + 重建工具白名单 + 待办流转。

        关键设计：不改首条 system prompt（保护 prompt cache），而是注入新 system 消息。
        """
        if mode_def is None:
            mode_def = load_mode(new_mode)
        if not mode_def:
            return

        old_mode = self.mode_name

        # 1. 重建工具集（新白名单 + meta 工具常驻）
        allowed = set(mode_def.tools) | META_TOOLS
        self.tools = [t for t in ALL_TOOLS if t.name in allowed]
        self._rebuild_tool_map()
        self._tools_dirty = True  # 下一轮 LLM 调用前重建 openai_tools

        # 2. 注入新模式约束（作为新 system 消息，不动首条）
        switch_notice = (
            f"【模式切换】{old_mode} → {new_mode}\n"
            f"原因：{reason}\n\n"
            f"新模式行为约束：\n{mode_def.prompt_fragment}"
        )
        self._pending_mode_notice = switch_notice

        # 3. 自动更新待办：当前模式的 in_progress 项 → done，
        #    新模式的第一个 pending 项 → in_progress
        for todo in self._todos:
            if todo.get("mode") == old_mode and todo.get("status") == "in_progress":
                todo["status"] = "done"
        for todo in self._todos:
            if todo.get("mode") == new_mode and todo.get("status") == "pending":
                todo["status"] = "in_progress"
                break

        # 4. 事件 + 状态
        self.mode_name = new_mode
        self.events.emit("mode_switch",
                         from_mode=old_mode, to_mode=new_mode,
                         source="agent", reason=reason, auto=True)

        # 待办变更也 emit + 持久化
        if self._todos:
            self.events.emit("todo_update", todos=self._todos)
            if self._session and self._session_id:
                try:
                    self._session.save_todos(self._session_id, self._todos)
                except Exception:
                    pass
