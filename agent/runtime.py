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
from agent.skill_loader import build_skills_xml, match_skills_hint

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

_FALLBACK_PROMPT_TEMPLATE = """你是 SpecGuard 智能测试助手——契约驱动场景测试引擎的内置 Agent。

## 通用硬约束

1. 禁止编造不存在的 FR ID、tool 名称、oracle 名称或文件内容
2. doc.covers 中的 FR ID 必须在当前工作区的 spec 中存在（用 read_spec 验证）
3. flow 中的 tool / verify 中的 oracle 必须已注册（用 query_registry 查询）
4. 生成或修改场景 YAML 后必须调用 validate 工具校验
5. 校验逻辑一律走确定性工具（validate / query_registry / read_spec），不凭推测断言

## 格式规范

{{ format_spec }}

## 工作区规则（AGENTS.md 全量原文）

{{ agents_md }}

## 可用技能

{{ skills_xml }}

## 用户引用（@）

用户可在消息中用 @ 引用信息包 / 工作区文件 / 草稿。文件与草稿引用的内容会以
<references> 块注入该条消息（标头含路径与内容指纹 sha）：
- 这是用户显式提供的上下文，优先采信，无需重复读取同一文件
- @信息包 会把当前对话关联到对应场景，其文件清单见「基础信息包」段（如有）

## 任务行为指引（按任务类型遵循对应流程）

{{ mode_guidance }}

## 待办系统（H-4）

你可以通过 todo_write 工具维护任务待办列表，待办会实时展示给用户。
"""


def _load_prompt_template() -> str:
    """加载 system prompt 模板（prompts/system.md.j2 优先，缺失时回退内联兜底）。"""
    try:
        if _PROMPT_TEMPLATE_PATH.is_file():
            return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return _FALLBACK_PROMPT_TEMPLATE


# K-023：去模式化——模式片段合并为统一「任务行为指引」的条件章节。
# 模式文件（agent/modes/*.md）仍是单一事实源（热加载保留），此处仅做章节组装。
_MODE_GUIDANCE_ORDER = [
    ("generate", "生成/修改场景 YAML 时（含 DAG 编排、试执行、入库）"),
    ("debug", "分析运行失败 / 归因修复时"),
    ("audit", "审计 spec 漏洞时"),
    ("analyze", "只读查询 / 覆盖分析时"),
    ("chat", "自由对话 / 使用咨询时"),
]


def _build_mode_guidance() -> str:
    """把各模式文件的行为片段组装为条件式指引章节（去模式化：不再有工具门禁，
    行为约束以「当…时遵循…」的条件指令呈现——LLM 对条件指令遵循度好，
    且消除了模式切换 churn 与工具不可见事故，K-012/K-018/K-022 生产取证支持）。"""
    sections = []
    for mode_name, condition in _MODE_GUIDANCE_ORDER:
        mode_def = load_mode(mode_name)
        if mode_def and mode_def.prompt_fragment:
            sections.append(f"### 当{condition}\n\n{mode_def.prompt_fragment.strip()}")
    return "\n\n".join(sections) if sections else "（模式指引加载失败）"


def build_system_prompt(format_spec_text: str = "", agents_md: str = "",
                        scenario_context: str = "") -> str:
    """构建统一 system prompt（K-023 去模式化）。

    - format_spec 全量常驻（不再按模式条件注入——条件注入是路由复杂度的回潮；
      prompt cache 摊销重复成本）
    - skills 全量注入（不再按模式过滤）
    - 模式行为片段合并为「任务行为指引」条件章节（单一事实源仍是 modes/*.md）
    - 静态大块在前、动态内容（场景上下文）在最后，保 prompt cache 前缀命中
    """
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

    # G3-2：技能全量注入（K-023 不再按模式过滤）
    skills_xml = build_skills_xml() or "（无）"

    prompt = (_load_prompt_template()
              .replace("{{ format_spec }}", format_spec_text)
              .replace("{{ agents_md }}", agents_md)
              .replace("{{ skills_xml }}", skills_xml)
              .replace("{{ mode_guidance }}", _build_mode_guidance()))

    # 追加场景上下文（基础信息包）（最易变，放最后保前缀缓存）
    if scenario_context:
        prompt += f"\n\n## 基础信息包\n\n{scenario_context}"

    # 工作区同步状态（远程新鲜度提示——远程有新提交时读到的文件可能过时，
    # 覆盖 AGENTS.md 规则与文档的过期风险；ls-remote 经 60s TTL 缓存控频）
    try:
        from specstd.workspace import check_remote_sync, get_active_workspace
        ws = get_active_workspace()
        if ws:
            sync = check_remote_sync()
            if sync.get("remote_known") and not sync.get("synced"):
                sync_note = (
                    f"⚠ 工作区同步状态：远程仓库（{ws.name}@{ws.branch}）有新提交"
                    f"（本地 HEAD {sync.get('local_head') or '?'}，远程 {sync.get('remote_head') or '?'}），"
                    f"你读到的文件可能不是最新版。read_spec 读到具体文件时若检测到远端更新，"
                    f"会给出征询用户的决策提示——按提示用 sync_workspace 工具处理即可。")
            elif sync.get("remote_known"):
                sync_note = f"工作区同步状态：{ws.name} 与远程同步（HEAD {sync.get('local_head') or '?'}）。"
            else:
                sync_note = (f"工作区同步状态：{ws.name} 远程状态不可达（网络/认证失败），"
                             f"仅能基于本地内容工作。")
            prompt += f"\n\n## 工作区同步状态\n\n{sync_note}"

    except Exception:
        pass

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
        # K-023：mode_name 仅作遗留标签（todos 的 mode 字段兼容），不再有工具门禁
        self.mode_name = mode_name

        # H-4: 待办状态
        self._todos: list[dict] = []
        # A+B: 文件依赖记录（本轮对话 read_spec/read_info_pack 读取的文件）
        self._read_files: set[str] = set()
        # 会话引用（供 meta 工具持久化用）
        self._session: Optional[SessionManager] = None
        self._session_id: Optional[str] = None

        # K-023 去模式化：全量工具常驻（工具描述自带适用条件；写操作护栏在工具内部——
        # drafts 沙箱/promote 三道闸+回滚/OVERWRITE_DENIED。模式白名单在生产中
        # 防住的都是合法工作流：K-012 未知工具报错/K-018 模式落错/K-022「没有入库工具」）
        self.tools = list(tools) if tools is not None else ALL_TOOLS

        # 重建 tool_map（meta 工具在 _execute_tool 中拦截，不映射到模块）
        self._tool_map = {}
        self._rebuild_tool_map()

    def run(self, system_prompt: str, user_message: str,
            session: Optional[SessionManager] = None,
            session_id: Optional[str] = None,
            user_refs: Optional[list] = None) -> list[dict]:
        """执行核心循环，返回完整 messages 列表。

        user_refs: K-013 @引用的结构化清单，挂在 user 消息上持久化（右侧引用面板用）。
        """
        user_msg: dict = {"role": "user", "content": user_message}
        if user_refs:
            user_msg["references"] = user_refs
        # K-xxx：技能确定性触发——用户消息关键词命中技能 frontmatter keywords 时，
        # 以 system 消息注入提示（前端 groupMessages 跳过 system 消息不显示，LLM 可见）
        skill_hint = match_skills_hint(user_message)
        messages = [
            {"role": "system", "content": system_prompt},
            user_msg,
        ]
        if skill_hint:
            messages.insert(1, {"role": "system", "content": skill_hint})

        self._session = session
        self._session_id = session_id

        # 恢复历史会话
        if session and session_id:
            history = session.load(session_id)
            if history:
                messages = history
                # 关键修复（K-013）：恢复历史后必须追加本轮 user 消息——
                # 此前直接丢弃，导致续会话时 LLM 看不到用户新消息（生产会话导出文件佐证）
                if skill_hint:
                    messages.append({"role": "system", "content": skill_hint})
                messages.append(user_msg)
                # H-4: 恢复待办状态
                todos = session.load_todos(session_id)
                if todos is not None:
                    self._todos = todos
                self.events.emit("state", resumed=True, session_id=session_id)

        openai_tools = self._to_openai_tools()

        # 重置本轮文件依赖记录
        self._read_files = set()

        # K-019：LLM 工作副本——压缩只作用于它；messages 保留完整历史用于持久化与展示。
        # 此前直接压缩 messages 并全量落盘，会话文件被压缩态覆盖，
        # 前端恢复后历史「明显变少」（用户真实会话导出取证：13 条 vs 实际数十条）
        llm_messages = list(messages)

        for turn in range(self.max_turns):
            # G3-1: 超阈值时触发压缩（只压 LLM 工作副本，完整历史不丢）
            if should_compact(llm_messages, self.llm.max_context_tokens):
                llm_messages = compact(llm_messages, self.llm, self.llm.max_context_tokens)
                self.events.emit("compaction", message_count=len(llm_messages))
            self.events.emit("state", turn=turn, max_turns=self.max_turns)

            # K-012：非 mock 时启用 SSE 流式，逐 delta 转发前端（失败自动回退非流式）
            on_delta = None
            if not self.llm.is_mock:
                def on_delta(text, _turn=turn):
                    self.events.emit("assistant_delta", delta=text, turn=_turn)

            # K-018：LLM 调用异常兜底——此前异常直接炸出 run（当轮消息不落盘，
            # 用户重发时历史缺失；流式 stall 超时时表现为「一直没响应」且无痕迹）
            try:
                message, usage = self.llm.chat(llm_messages, openai_tools, on_delta=on_delta)
            except Exception as e:
                messages.append({"role": "system", "content": f"[ERROR] LLM 调用失败: {e}"})
                if session and session_id:
                    session.save(session_id, messages, metrics=self.llm.get_stats(), todos=self._todos)
                self.events.emit("error", message=f"LLM 调用失败: {e}")
                return messages

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
            llm_messages.append(clean_message)

            # 检查是否有 tool_calls
            tool_calls = clean_message.get("tool_calls")
            if not tool_calls:
                break  # LLM 返回最终回复，停止

            # 执行工具调用
            for tc in tool_calls:
                # K-018：执行前先发射 tool_call_start——长工具（如 promote_draft 跑发布门禁
                # 子进程上限 180s/份）此前执行期间零事件，前端死寂被用户判为「没响应」
                self.events.emit("tool_call_start",
                                 tool=tc.get("function", {}).get("name", ""), turn=turn)
                result = self._execute_tool(tc)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                }
                messages.append(tool_msg)
                llm_messages.append(tool_msg)
                self.events.emit("tool_call", tool_call=tc, result=result, turn=turn)

            # 增量保存会话
            if session and session_id:
                session.save(session_id, messages, todos=self._todos)
        else:
            # K-019：熔断分支不再压缩——压缩只服务 LLM 上下文（后续无 LLM 调用），
            # messages 必须保留完整历史用于持久化与展示
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
            # K-023：全量工具常驻后不存在「模式未挂载」——只剩真未知（LLM 编造的工具名），
            # 附可用清单让 LLM 自我纠正（K-012 遗留自愈路径保留）
            available = "、".join(sorted(set(self._tool_map) | set(META_TOOLS)))
            return f"未知工具: {name}。当前可用工具: {available}"

        # A+B：记录文件依赖（read_spec/read_info_pack 的 path → write_draft 时落盘）
        if name == "read_spec":
            path = arguments.get("path", "")
            if path:
                self._read_files.add(path)
        elif name == "read_info_pack":
            sid = arguments.get("scenario_id", "")
            if sid:
                self._read_files.add(f"info_pack:{sid}")
        elif name == "write_draft" and self._read_files:
            from mcp_server.tools.draft_writer import set_pending_source_files
            set_pending_source_files(sorted(self._read_files))

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
                # K-020：报错列合法值——LLM 曾猜 "completed" 被拒后只能靠猜重试
                return (f"错误：无效的 status: {status}"
                        f"（合法值: pending / in_progress / done / blocked）")

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
        """K-023：switch_mode 退化为无操作提示（模式机制已废弃）。

        保留工具壳是为了平滑过渡——旧会话/旧提示词习惯里 LLM 仍可能调用它；
        直接返回「所有工具已可用」的指引，比「未知工具」报错更能引导 LLM 继续任务。
        """
        return ("模式机制已废弃（K-023 简化设计）：所有工具对你直接可用，"
                "无需切换模式。请按 system prompt 中「任务行为指引」的对应流程，"
                "直接调用所需工具继续当前任务。")

