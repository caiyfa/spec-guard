"""agent.runtime — 核心循环 LLM⇄tools⇄stop。

max_turns=12 熔断；kill 后重跑可从 JSONL 续会话。
"""

import asyncio
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger("agent.runtime")

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.llm_client import LLMClient
from agent.session import SessionManager
from agent.events import EventBus
from agent.compactor import should_compact, compact
from agent.skill_loader import build_skills_xml, match_skills_hint
from agent.doc_read import build_doc_read

# T-602：工具模块单一注册（B1 修复——server 导出、runtime 复用，消除双写漂移；
# runtime 侧 include_info_pack=True（workbench Agent 需要 info_pack），stdio server 刻意排除）
from mcp_server.server import build_tool_modules
from mcp_server.tools import meta

TOOL_MODULES = build_tool_modules(include_info_pack=True)

# Meta 工具常驻所有模式（H-3/H-4）
META_TOOLS = meta.META_TOOL_NAMES

ALL_TOOLS = []
for mod in TOOL_MODULES:
    ALL_TOOLS.extend(mod.TOOLS)
TOOL_NAME_TO_MODULE = {}
for mod in TOOL_MODULES:
    for tool in mod.TOOLS:
        TOOL_NAME_TO_MODULE[tool.name] = mod

# T-403: 工具结果最大字符数（超限时截断 + 落盘引用）
_TOOL_RESULT_MAX_CHARS = 50000

# ══════════════════════════════════════════════════════════
# T-011: 三层交集工具白名单（resolve_tools）
# resolve_tools(session) = TOOL_REGISTRY ∩ purpose.tools ∩ rbac_visible_tools
# 全部为确定性过滤；LLM 请求越权工具 → 直接拒绝，不执行（铁律 2 运行时形态）
# ══════════════════════════════════════════════════════════

# RBAC 角色可见工具集（v1.8 角色集合并集语义）
# - admin/tester：全量（无额外收窄）
# - product：只读/校验/归因/台账查询工具（需求侧面试会话的可见面）
# - 工具名为空集时角色不可用 Agent（viewer 无菜单，后端同样拦截）
_RBAC_READONLY_TOOLS = frozenset({
    # spec_reader
    "read_spec", "list_spec_files", "sync_workspace",
    # scenario_tools（只读部分）
    "list_scenarios", "read_scenario", "next_scenario_id", "check_dag", "suggest_deps",
    # registry_query
    "query_registry",
    # validator
    "validate",
    # attribution（归因只读）
    "read_run_report", "read_run_log", "read_case_detail", "list_failures", "list_executions",
    # compliance
    "scan_compliance",
    # meta
    "todo_write",
    # specflow 面试工具集（product 需求面试用，只读+登记+门禁纯函数）
    "iv_open_topic", "iv_read_baseline", "iv_ask_question",
    "iv_next_question", "iv_record_answer", "iv_p0_clear_check", "iv_append_transcript",
    "sf_list_decisions", "sf_propose_decision", "sf_check_p0_gate",
    "sf_suggest_scores", "sf_read_score_gate",
    # 材料包工具
    "pack_assemble", "pack_read_section", "material_parse_status",
    "material_extract_topics", "pack_freshness_check",
    # info_pack 工具
    "read_info_pack", "add_to_info_pack", "list_info_pack_artifacts",
    # T-507/T-508 知识层（只读：技能正文/知识正文/格式规范章节按需取）
    "load_skill", "read_knowledge", "read_format_spec",
    # 飞书日程/会议纪要（需求面试场景材料收集用）
    "feishu_calendar_agenda", "feishu_meeting_notes",
    # 飞书文档/多维表格拉取 + 故事草案建议（S5 增补：对话分析建故事链路）
    "feishu_doc_read", "feishu_base_query", "sf_suggest_story_draft",
})

# 全量角色（语义 = 不额外收窄；与 _RBAC_TOOL_SETS 分离，避免 None 二义）
_RBAC_FULL_ROLES = frozenset({"admin", "tester"})

# 有限可见集角色；不在此表 = 未注册角色（H1：fail-closed 视为空集，绝不视为全量）
_RBAC_TOOL_SETS = {
    "product": _RBAC_READONLY_TOOLS,
    "viewer": frozenset(),  # 空集 = 不可用 Agent
}


def rbac_visible_tools(user_roles: list) -> Optional[set[str]]:
    """角色可见工具集（v1.8 并集语义）：任一角色可见的工具并集。

    H1 修复：未注册角色 fail-closed——贡献空集并 WARNING，不再与 admin/tester
    的全量语义混同。此前 _RBAC_TOOL_SETS.get(未知角色) 返回 None 即被当作全量，
    用户角色集混入任意未注册角色（如用途定义引用的 dev）即可击穿 product 只读收窄。
    """
    if not user_roles:
        return set()
    visible: set[str] = set()
    for role in user_roles:
        if role in _RBAC_FULL_ROLES:
            return None  # admin/tester 之一 → 全量
        rset = _RBAC_TOOL_SETS.get(role)
        if rset is None:
            _log.warning(
                "rbac: 未注册角色 %r 视为空集（fail-closed）——"
                "请检查 VALID_ROLES 与 _RBAC_TOOL_SETS 配置是否一致", role)
            continue
        visible |= rset
    return visible


def resolve_tools(purpose_tools: list, user_roles: list) -> list:
    """T-011：三层交集过滤——TOOL_REGISTRY ∩ purpose.tools ∩ rbac_visible_tools。

    - purpose_tools 为空 = 用途不额外收窄（test_workbench 全量测试工具）
    - rbac 全量（admin/tester）= 角色层不额外收窄
    - 返回过滤后的 Tool 列表（保持 ALL_TOOLS 顺序）
    """
    rbac_set = rbac_visible_tools(user_roles)
    if rbac_set is not None and not rbac_set:
        return []  # 角色无任何可见工具（viewer）
    purpose_set = set(purpose_tools or [])
    result = []
    for tool in ALL_TOOLS:
        if rbac_set is not None and tool.name not in rbac_set:
            continue
        if purpose_set and tool.name not in purpose_set:
            continue
        result.append(tool)
    # meta 工具常驻（todo_write 在 _execute_tool 拦截，不参与白名单过滤）
    for name in META_TOOLS:
        if all(t.name != name for t in result):
            result.append(next((t for t in ALL_TOOLS if t.name == name), None))
    return [t for t in result if t is not None]


def _parse_tc_arguments(tool_call: dict) -> dict:
    """解析 tool_call.function.arguments（容错：解析失败返回空 dict）。"""
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    try:
        return json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError:
        return {}


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


def build_system_prompt(format_spec_text: str = "", agents_md: str = "",
                        scenario_context: str = "") -> str:
    """构建统一 system prompt（K-023 去模式化 + T-601 技能单一事实源）。

    - format_spec 全量常驻（不再按模式条件注入——条件注入是路由复杂度的回潮；
      prompt cache 摊销重复成本）
    - skills 全量注入（T-601：modes 正文并入 skills 后唯一事实源，不再有 mode_guidance 章节）
    - 静态大块在前、动态内容（场景上下文）在最后，保 prompt cache 前缀命中
    """
    if not format_spec_text:
        try:
            BACKEND_DIR = SG_ROOT / "workbench" / "backend"
            if str(BACKEND_DIR) not in sys.path:
                sys.path.insert(0, str(BACKEND_DIR))
            # T-507 激进档（定档 2026-08-11）：骨架常驻 + read_format_spec 按需取细节
            from services.format_spec import generate_format_spec_skeleton
            format_spec_text = generate_format_spec_skeleton()
        except Exception:
            format_spec_text = "（format_spec 加载失败，请用 query_registry 查询可用工具）"

    if not agents_md:
        try:
            from specstd.workspace import read_agents_md
            agents_md = read_agents_md() or "（无激活工作区或 AGENTS.md 不存在）"
        except Exception:
            agents_md = "（工作区未激活）"

    # G3-2：技能全量注入（K-023 不再按模式过滤；T-601：modes 正文已并入 skills，
    # 技能为任务行为指引的唯一事实源——不再组装 mode_guidance 条件章节）
    skills_xml = build_skills_xml() or "（无）"

    prompt = (_load_prompt_template()
              .replace("{{ format_spec }}", format_spec_text)
              .replace("{{ agents_md }}", agents_md)
              .replace("{{ skills_xml }}", skills_xml))

    # 追加场景上下文（基础信息包）（最易变，放最后保前缀缓存）
    if scenario_context:
        prompt += f"\n\n## 基础信息包\n\n{scenario_context}"

    # 工作区同步状态（远程新鲜度提示——远程有新提交时读到的文件可能过时，
    # 覆盖 AGENTS.md 规则与文档的过期风险；ls-remote 经 60s TTL 缓存控频）
    # 非阻塞：首次/缓存过期时用默认提示 + 后台异步刷新，不阻塞 system prompt 构建
    try:
        from specstd.workspace import get_cached_remote_sync, refresh_remote_sync_async, get_active_workspace
        ws = get_active_workspace()
        if ws:
            sync = get_cached_remote_sync()
            if sync is None:
                # 缓存未命中——用默认提示，后台异步刷新（下次即命中）
                sync_note = (f"工作区同步状态：{ws.name} 远程状态检查中，"
                             f"首次响应后自动更新。")
                refresh_remote_sync_async()
            elif sync.get("remote_known") and not sync.get("synced"):
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
    """核心循环：LLM → tools → LLM → ... → stop。

    T-402：支持 cancellation 检查点——用户打断后不再推进轮次且不再写会话。
    """

    def __init__(self, llm: LLMClient, tools: list = None, max_turns: int = 12,
                 mode_name: str = ""):
        self.llm = llm
        self.max_turns = max_turns
        self.events = EventBus()
        # K-023：mode_name 仅作遗留标签（todos 的 mode 字段兼容），不再有工具门禁
        self.mode_name = mode_name

        # T-402: 取消事件（线程安全，跨 asyncio.to_thread 边界）
        self._cancel_event = threading.Event()

        # H-4: 待办状态
        self._todos: list[dict] = []
        # A+B: 文件依赖记录（本轮对话 read_spec/read_info_pack 读取的文件）
        self._read_files: set[str] = set()
        # 会话引用（供 meta 工具持久化用）
        self._session: Optional[SessionManager] = None
        self._session_id: Optional[str] = None

        # T-508：会话级知识 nudge（每篇每会话一次、总量 ≤4KB；懒初始化——
        # 无激活工作区/词典缺失时静默降级为不投递）
        self._knowledge_nudger = None

        # K-023 去模式化：全量工具常驻（工具描述自带适用条件；写操作护栏在工具内部——
        # drafts 沙箱/promote 三道闸+回滚/OVERWRITE_DENIED。模式白名单在生产中
        # 防住的都是合法工作流：K-012 未知工具报错/K-018 模式落错/K-022「没有入库工具」）
        self.tools = list(tools) if tools is not None else ALL_TOOLS

        # T-011：白名单工具集（resolve_tools 过滤结果；LLM 请求白名单外的工具 → 确定性拒绝）
        self._tool_whitelist = {t.name for t in self.tools}

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

        # T-508：用户消息入口知识 nudge（每篇每会话一次、总量 ≤4KB）
        nudge = self._nudge_for_user(user_message)
        if nudge:
            # 追加到用户消息尾部（LLM 可见，前端展示无侵入）
            user_msg["content"] = user_message + "\n\n" + nudge

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
            # T-402: 检查 cancellation 检查点——用户打断后停止推进轮次且不再写会话
            if self._cancel_event.is_set():
                messages.append({"role": "system",
                                 "content": "[CANCEL] 用户已打断当前会话。"})
                self.events.emit("state", cancelled=True, turn=turn,
                                 max_turns=self.max_turns)
                break

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
                # T-511 依据透明：读型文档工具补发 doc_read（path/摘要/大小/hunks/思考文本），
                # 前端 📖 阅读页签汇聚阅读足迹；写型/查询型工具与失败结果不上足迹
                doc_evt = build_doc_read(
                    tc.get("function", {}).get("name", ""),
                    _parse_tc_arguments(tc),
                    result, turn,
                    thinking=clean_message.get("content", ""))
                if doc_evt is not None:
                    self.events.emit("doc_read", **doc_evt)
                
                # T-508：工具结果尾部知识 nudge（挂 T-403 统一出口）
                if not result.startswith("[SIDE_EFFECT_VIOLATION]"):
                    nudge = self._nudge_for_tool(
                        tc.get("function", {}).get("name", ""),
                        _parse_tc_arguments(tc),
                        result)
                    if nudge:
                        tool_msg["content"] = result + "\n\n" + nudge
                        # 同步 LLM 工作副本（llm_messages 中的 tool_msg 需一致）
                        if llm_messages and llm_messages[-1].get("role") == "tool":
                            llm_messages[-1]["content"] = tool_msg["content"]

            # 增量保存会话
            if session and session_id:
                session.save(session_id, messages, todos=self._todos)
        else:
            # K-019：熔断分支不再压缩——压缩只服务 LLM 上下文（后续无 LLM 调用），
            # messages 必须保留完整历史用于持久化与展示
            messages.append({"role": "system", "content": f"[FUSE] 已达到 max_turns={self.max_turns}，自动停止。"})
            self.events.emit("state", fused=True, max_turns=self.max_turns)

        # 最终保存（T-402：cancelled 时不写会话——打断后不保留不完整产物）
        if session and session_id and not self._cancel_event.is_set():
            session.save(session_id, messages, metrics=self.llm.get_stats(), todos=self._todos)

        return messages

    def cancel(self):
        """T-402：线程安全地请求取消当前运行。

        检查点在每轮 LLM 调用前，设置后当前轮次 tool 执行完即停止（不推进下一轮），
        且不再写会话文件。
        """
        self._cancel_event.set()

    def _get_nudger(self):
        """懒初始化会话级知识 nudger（T-508）。无激活工作区/词典缺失时静默降级。"""
        if self._knowledge_nudger is None:
            try:
                from specstd.workspace import get_active_workspace
                from specstd.knowledge_index import build_index, KnowledgeNudger
                ws = get_active_workspace()
                if ws:
                    system_dir = (SG_ROOT / "systems" / ws.system / "config")
                    idx = build_index(ws.root, system_dir=system_dir, name=ws.name)
                    if idx.entries:
                        self._knowledge_nudger = KnowledgeNudger(idx)
            except Exception:
                pass
        return self._knowledge_nudger

    def _nudge_for_user(self, user_message: str) -> str:
        """用户消息入口知识 nudge（T-508 通道二 + T-510 经验检索注入）。

        T-510：用户消息含纠正关键词 → 检索相关经验（≤2KB 封顶）注入；
        无纠正关键词时走常规关键词匹配。经验检索独立于词典 nudger（
        无词典时经验注入仍可用）。
        """
        parts = []
        # T-510：纠正关键词 → 经验飞轮检索注入（recency×hit_count，≤2KB 封顶）
        try:
            from services.experience_store import detect_correction, search_experiences
            from specstd.workspace import get_workspace_root
            if detect_correction(user_message):
                root = get_workspace_root()
                if root is not None:
                    hits = search_experiences(root, user_message[:200])
                    if hits:
                        exp_lines = ["<experience_refs>（经验飞轮：相关历史失败经验）"]
                        for h in hits:
                            exp_lines.append(
                                f"- [{h['token']}] hit×{h['hit_count']}：{h['text'][:200]}")
                        exp_lines.append("</experience_refs>")
                        parts.append("\n".join(exp_lines))
        except Exception:
            pass

        # T-508：常规词典 nudge（无词典时静默跳过）
        nudger = self._get_nudger()
        if nudger:
            try:
                nudge = nudger.compose(user_text=user_message)
                if nudge:
                    parts.append(nudge)
            except Exception:
                pass
        return "\n\n".join(parts)

    def _nudge_for_tool(self, tool_name: str, arguments: dict, result: str) -> str:
        """工具结果尾部知识 nudge（T-508 通道一：结构化字段为主）。"""
        nudger = self._get_nudger()
        if not nudger:
            return ""
        try:
            # 工具通道上下文：scenario_id/错误文本（非文本扫描，结构化字段优先）
            ctx = str(arguments.get("scenario_id", "") or "")
            if not ctx and "error" in result[:200].lower():
                ctx = result[:500]
            return nudger.compose(tool_context=ctx, user_text="")
        except Exception:
            return ""

    def _truncate_tool_result(self, result: str, tool_name: str) -> str:
        """T-403：工具结果统一截断——超限落盘 + 回喂引用。"""
        if len(result) <= _TOOL_RESULT_MAX_CHARS:
            return result
        truncated = result[:_TOOL_RESULT_MAX_CHARS]
        note = (
            f"\n\n[截断] 工具 {tool_name} 返回 {len(result)} 字符，"
            f"超过 {_TOOL_RESULT_MAX_CHARS} 限制。"
            f"完整结果已保存至会话目录。")
        if self._session and self._session_id:
            try:
                trunc_dir = self._session.sessions_dir / "_truncated"
                trunc_dir.mkdir(parents=True, exist_ok=True)
                import datetime as _dt
                ts = _dt.datetime.now().strftime("%H%M%S%f")[:10]
                ref_path = trunc_dir / f"{tool_name}_{ts}.txt"
                ref_path.write_text(result, encoding="utf-8")
            except Exception:
                pass
        return truncated + note

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
        """执行单个工具调用，返回结果文本。

        T-081：side_effect 检查——none 级工具执行后做指纹比对，变化即报错。
        T-082：每次调用落审计日志。
        """
        name = tool_call.get("function", {}).get("name", "")
        raw_args = tool_call.get("function", {}).get("arguments", "{}")

        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            return f"错误：参数 JSON 解析失败: {raw_args}"

        # ── Meta 工具特殊处理（不通过 mod.handle；T-082：同样落审计）──
        if name == "todo_write":
            result = self._handle_todo_write(arguments)
            from mcp_server.tools.side_effect_registry import get_side_effect as _gse
            self._record_audit(name, "ok", raw_args, result, _gse(name))
            return result

        verdict = "ok"
        side_effect = "none"

        # ── 常规工具 ──
        # T-011：白名单强制——越权工具确定性拒绝（不执行，附可用清单自愈）
        # 判断顺序：先查全局注册（真未知 vs 白名单外），再查白名单
        if name not in META_TOOLS:
            if name in TOOL_NAME_TO_MODULE and name not in self._tool_whitelist:
                available = "、".join(sorted(self._tool_whitelist))
                verdict = "denied-whitelist"
                # T-011：越权留 WARNING 审计
                try:
                    from specstd.workspace import get_context_emp_no
                    _bd = SG_ROOT / "workbench" / "backend"
                    if str(_bd) not in sys.path:
                        sys.path.insert(0, str(_bd))
                    from services import user_store as _us
                    _emp = get_context_emp_no() or ""
                    _us.audit(_emp, "tool_denied", name,
                              detail=f"session={self._session_id or ''}; purpose 白名单外工具被拒绝",
                              db_path=_us.DB_PATH)
                except Exception:
                    _log.warning("tool_denied 审计写入失败（tool=%s, session=%s）",
                                 name, self._session_id or "")
                # T-082：越权审计记录
                self._record_audit(name, verdict, raw_args, "", side_effect)
                return (f"[越权拒绝] 工具 {name} 不在本会话用途白名单内。"
                        f"当前会话可用工具: {available}")

        mod = self._tool_map.get(name)
        if not mod:
            available = "、".join(sorted(set(self._tool_map) | set(META_TOOLS)))
            # T-082：未知工具审计
            self._record_audit(name, "warn", raw_args, "", side_effect)
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

        # T-081：查询 side_effect 级别
        from mcp_server.tools.side_effect_registry import (
            get_side_effect, is_pure_read)
        side_effect = get_side_effect(name)

        # T-081：external-write 级确定性拒绝（外部写不进 MCP）
        if side_effect == "external-write":
            verdict = "denied-side-effect"
            self._record_audit(name, verdict, raw_args, "", side_effect)
            return (f"[拒绝] 工具 {name} 属于 external-write 级别，"
                    f"当前不允许直接调用（外部写不进 MCP 通则）")

        # T-081：none 级工具执行前记录初始指纹
        pre_fp = ""
        if is_pure_read(name):
            pre_fp = self._take_snapshot_fingerprint()

        try:
            result = asyncio.run(mod.handle(name, arguments))
            raw = result[0].text if result else "（无输出）"

            # T-081：none 级工具执行后比对指纹
            if is_pure_read(name) and pre_fp:
                post_fp = self._take_snapshot_fingerprint()
                if pre_fp != post_fp:
                    verdict = "denied-side-effect"
                    self._record_audit(name, verdict, raw_args, raw, side_effect)
                    return (f"[SIDE_EFFECT_VIOLATION] 纯读工具 {name} 产生了副作用，"
                            f"调用已被拦截并记审计。结果摘要: {raw[:200]}")

            self._record_audit(name, verdict, raw_args, raw, side_effect)
            return self._truncate_tool_result(raw, name)
        except Exception as e:
            err_msg = f"工具执行异常: {e}"
            self._record_audit(name, "warn", raw_args, err_msg, side_effect)
            return err_msg

    def _take_snapshot_fingerprint(self) -> str:
        """T-081：取关键目录快照指纹（mtime+size 聚合），校验纯读工具无副作用。

        覆盖 SpecGuard 仓库关键目录 + 工作区产物（T-014 emp 私有区/共享区）+
        台账 DB——纯读工具写工作区草稿/落库均会被检出。
        """
        import hashlib as _hl
        parts = []
        roots: list[tuple[str, Path]] = []
        for sub in ("specs", "scenarios", "agent/skills",
                    "mcp_server/tools", "drafts", "feedback"):
            d = SG_ROOT / sub
            if d.is_dir():
                roots.append((f"root:{sub}", d))
        # 工作区产物（私有区 + 共享区）——纯读工具不得写草稿/计划
        try:
            from specstd.workspace import specguard_dir
            roots.append(("ws:private", specguard_dir()))
            roots.append(("ws:shared", specguard_dir(emp="")))
        except Exception:
            pass
        # 台账/审计 DB（纯读工具不得落库）
        for db_rel in ("workbench/backend/data/workbench.db",
                       "feedback/ledger.json", "feedback/registry.json"):
            f = SG_ROOT / db_rel
            if f.is_file():
                st = f.stat()
                parts.append(f"db:{db_rel}:{st.st_size}:{int(st.st_mtime)}")
        for label, d in roots:
            if not d.is_dir():
                continue
            entries = []
            try:
                for p in sorted(d.rglob("*")):
                    if p.is_file():
                        st = p.stat()
                        entries.append(f"{p.relative_to(d)}:{st.st_size}:{int(st.st_mtime)}")
            except Exception:
                pass
            if entries:
                parts.append(label + "=" + "|".join(entries))
        return _hl.sha256("||".join(parts).encode()).hexdigest()[:16]

    def _record_audit(self, tool_name: str, verdict: str,
                      args_raw: str, result_raw: str,
                      side_effect: str = "none"):
        """T-082：记录 MCP 调用审计（失败静默，不阻断工具执行）。"""
        try:
            from specstd.workspace import get_context_emp_no, get_context_workspace
            emp = get_context_emp_no() or ""
            ws = get_context_workspace() or ""
            purpose = getattr(getattr(self, '_session', None), 'purpose', '') or ''
            from services.audit_store import record_call as _rc
            _rc(
                tool_name=tool_name,
                verdict=verdict,
                emp_no=emp,
                session_id=self._session_id or "",
                purpose=purpose,
                workspace=ws,
                side_effect=side_effect,
                args_raw=args_raw,
                result_raw=result_raw,
            )
        except Exception:
            # 审计写入失败不阻断工具执行
            pass

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

