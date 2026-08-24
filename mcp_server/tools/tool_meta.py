"""tool_meta — MCP 工具元数据单一事实源（T-982 工具收敛）。

每个工具在声明处（本模块 consolidate/declare 调用）登记元数据，下游全部派生，
消灭手工登记缺口（T-935 read_material 漏登记 _RBAC_READONLY_TOOLS 的教训）：

- side_effect  —— none（纯读，默认）/ draft（写内部存储）/ external-write（触外部系统，
  红线为空集）。side_effect_registry 从此处派生，新增写工具漏登记不再可能：
  未声明的工具默认 none（纯读 + 指纹校验），写工具必须显式声明否则会被指纹闸拦下。
- rbac         —— ""（派生默认：纯读 product 可见，写 staff 限定）/ product / staff。
- domain       —— 领域分组（spec/scenario/run/draft/specflow/feishu/graph/knowledge/
  quality/meta/open）。purpose 按 domain 选领域子集（单会话可见 ≤15）。
- doc_track    —— ""（不上足迹）/ read（阅读足迹）/ write（更新足迹）。
- legacy       —— 合并工具每个 action 对应的收敛前工具名（逻辑 id）。doc 事件、
  文件依赖追踪、前端分组等存量逻辑以此为锚，行为零变化。

合并工具（action 参数化）由 consolidate() 构建：原 Tool 声明逐字保留为 _TOOL_DECLS
（描述/schema 零漂移），合并出单个 Tool（action 枚举 + 属性并集），handle 包装
原派发——legacy 工具名仍可直接 handle（测试/脚本兼容），但不出现在 TOOLS 表面。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mcp.types import TextContent, Tool

_log = logging.getLogger("tool_meta")

# ── side_effect 级别（与 side_effect_registry 口径一致，此处为定义源头）──
SIDE_NONE = "none"
SIDE_DRAFT = "draft"
SIDE_EXTERNAL_WRITE = "external-write"
VALID_SIDES = frozenset({SIDE_NONE, SIDE_DRAFT, SIDE_EXTERNAL_WRITE})

# ── rbac 可见性 ──
RBAC_PRODUCT = "product"   # product 角色可见（需求侧只读+受限起草面）
RBAC_STAFF = "staff"       # 仅全量角色（admin/tester）可见


@dataclass(frozen=True)
class ActionMeta:
    """合并工具单 action 的元数据（空字段继承工具级默认）。"""
    legacy: str = ""             # 收敛前工具名（逻辑 id，事件/足迹锚点）
    side_effect: str = ""        # "" = 继承工具级
    rbac: str = ""               # "" = 继承工具级
    doc_track: str = ""          # "" = 继承工具级；read/write 上足迹
    params: dict = field(default_factory=dict)
                                  # 委派 legacy handler 时注入的固定参数（T-982b：
                                  # legacy 工具自带 action 参数名碰撞时，由合并层
                                  # 声明注入值，如 spec(sync/dismiss)→sync_workspace)


@dataclass(frozen=True)
class ToolMeta:
    """工具级元数据；actions 非空 = 合并工具（action 参数化）。"""
    domain: str = "general"
    side_effect: str = SIDE_NONE
    rbac: str = ""               # "" = 派生（none→product；draft/external→staff）
    doc_track: str = ""
    actions: dict[str, ActionMeta] = field(default_factory=dict)


# ── 注册表（声明处写入，工具名唯一）──
_TOOL_META: dict[str, ToolMeta] = {}


def get_meta(tool_name: str) -> ToolMeta:
    """工具元数据（未声明 → 全默认：纯读/product 可见/general 域）。"""
    return _TOOL_META.get(tool_name) or ToolMeta()


def get_action_meta(tool_name: str, action: str = "") -> ActionMeta:
    """解析 (tool, action) 的最终元数据（action 级覆盖工具级）。"""
    meta = get_meta(tool_name)
    am = (meta.actions or {}).get(action or "") if meta.actions else None
    if am is None:
        return ActionMeta(legacy=tool_name, side_effect=meta.side_effect,
                          rbac=meta.rbac, doc_track=meta.doc_track)
    return ActionMeta(
        legacy=am.legacy or tool_name,
        side_effect=am.side_effect or meta.side_effect,
        rbac=am.rbac or meta.rbac,
        doc_track=am.doc_track or meta.doc_track,
    )


def logical_id(tool_name: str, action: str = "") -> str:
    """(tool, action) → 逻辑 id（合并工具 = 收敛前工具名；未合并 = 工具名本身）。

    doc 事件 payload、文件依赖追踪等存量逻辑以此为锚，收敛前后行为零变化。
    """
    return get_action_meta(tool_name, action).legacy or tool_name


def legacy_owner(legacy_name: str) -> tuple[str, str] | None:
    """legacy 工具名 → 所属 (tool, action)；未注册返回 None。

    工具名本身优先（未合并工具 legacy 即自身）；其次查合并工具的 action legacy。
    side_effect_registry/doc 事件等以 legacy 名为键的存量消费方经此归一。
    """
    if legacy_name in _TOOL_META and not _TOOL_META[legacy_name].actions:
        return (legacy_name, "")
    for name, meta in _TOOL_META.items():
        for a, am in (meta.actions or {}).items():
            if am.legacy == legacy_name:
                return (name, a)
    if legacy_name in _TOOL_META:
        return (legacy_name, "")
    return None


def resolve_side_effect(tool_name: str, action: str = "") -> str:
    """(tool, action) 的副作用级别。"""
    se = get_action_meta(tool_name, action).side_effect
    if se not in VALID_SIDES:
        _log.warning("工具 %s action=%r side_effect %r 非法，按 none 处理",
                     tool_name, action, se)
        return SIDE_NONE
    return se


def resolve_rbac(tool_name: str, action: str = "") -> str:
    """(tool, action) 的 RBAC 可见性（显式声明优先；缺省派生：纯读 product / 写 staff）。"""
    am = get_action_meta(tool_name, action)
    if am.rbac in (RBAC_PRODUCT, RBAC_STAFF):
        return am.rbac
    return RBAC_PRODUCT if am.side_effect == SIDE_NONE else RBAC_STAFF


def product_visible_units(all_tools: list[Tool]) -> set[str]:
    """product 角色可见单元集（派生自元数据，替代 runtime 手工 _RBAC_READONLY_TOOLS）。

    单元形态：无 actions 工具 → "name"；合并工具按 action 逐个判定 →
    全可见 "name"，部分可见 {"name.action", ...}，全不可见则不出现。
    """
    units: set[str] = set()
    for t in all_tools:
        meta = get_meta(t.name)
        if not meta.actions:
            if resolve_rbac(t.name) == RBAC_PRODUCT:
                units.add(t.name)
            continue
        visible = [a for a in meta.actions
                   if resolve_rbac(t.name, a) == RBAC_PRODUCT]
        if len(visible) == len(meta.actions):
            units.add(t.name)
        else:
            units.update(f"{t.name}.{a}" for a in visible)
    return units


def domain_tools(all_tools: list[Tool], domains: list[str]) -> set[str]:
    """领域 → 工具名集（purpose 领域子集选择）。"""
    wanted = set(domains or [])
    return {t.name for t in all_tools if get_meta(t.name).domain in wanted}


def list_domains(all_tools: list[Tool]) -> dict[str, list[str]]:
    """领域 → 工具名清单（文档/调试用）。"""
    out: dict[str, list[str]] = {}
    for t in all_tools:
        out.setdefault(get_meta(t.name).domain, []).append(t.name)
    return out


def filter_tool_actions(tool: Tool, allowed_units: set[str]) -> Tool | None:
    """按可见单元裁剪工具 action 枚举（RBAC/purpose 部分可见时收窄 schema）。

    单元含 "name" → 全 action 可见原样返回；含 "name.action" → 裁剪枚举；
    无任何单元 → None（工具不可见）。无 actions 工具按单元在否全有或全无。
    """
    meta = get_meta(tool.name)
    if not meta.actions:
        return tool if tool.name in allowed_units else None
    if tool.name in allowed_units:
        return tool
    visible = [a for a in meta.actions if f"{tool.name}.{a}" in allowed_units]
    if not visible:
        return None
    schema = dict(tool.inputSchema or {})
    props = dict(schema.get("properties") or {})
    action_prop = dict(props.get("action") or {})
    action_prop["enum"] = visible
    props["action"] = action_prop
    schema["properties"] = props
    return Tool(name=tool.name, description=tool.description, inputSchema=schema)


def unit_allowed(units: set[str], tool_name: str, action: str = "") -> bool:
    """白名单单元判定：工具整体在册，或 (tool, action) 单元在册。"""
    if tool_name in units:
        return True
    return bool(action) and f"{tool_name}.{action}" in units


def intersect_units(a: set[str], b: set[str]) -> set[str]:
    """单元集交（"name" 表工具全 action；"name.action" 表单 action，混合粒度正确相交）。"""
    whole_a = {u for u in a if "." not in u}
    whole_b = {u for u in b if "." not in u}
    out = set(whole_a & whole_b)
    for u in b - whole_b:
        if u.split(".", 1)[0] in whole_a:
            out.add(u)
    for u in a - whole_a:
        if u.split(".", 1)[0] in whole_b:
            out.add(u)
    out |= (a - whole_a) & (b - whole_b)
    return out


def tool_units(tool: Tool) -> set[str]:
    """从（可能被裁剪过 action 枚举的）Tool schema 反推可见单元集。

    无 actions 或枚举未被裁剪 → {"name"}；部分可见 → {"name.action", ...}。
    runtime 据此构建白名单单元集，与下发 LLM 的 schema 同源不漂移。
    """
    meta = get_meta(tool.name)
    if not meta.actions:
        return {tool.name}
    enum = (((tool.inputSchema or {}).get("properties") or {})
            .get("action") or {}).get("enum")
    if not enum or set(enum) == set(meta.actions):
        return {tool.name}
    return {f"{tool.name}.{a}" for a in enum}


# ══════════════════════════════════════════════════════════
# 声明 API
# ══════════════════════════════════════════════════════════

def declare(names, meta: ToolMeta | None = None, *, domain: str = "",
            side_effect: str = "", rbac: str = "", doc_track: str = ""):
    """为未合并工具登记元数据（单名或名单）；缺省项取 ToolMeta 默认。"""
    if isinstance(names, str):
        names = [names]
    m = meta or ToolMeta(
        domain=domain or "general",
        side_effect=side_effect or SIDE_NONE,
        rbac=rbac, doc_track=doc_track)
    for n in names:
        if n in _TOOL_META:
            _log.warning("工具元数据重复声明: %s（后者覆盖）", n)
        _TOOL_META[n] = m


def consolidate(name: str, description: str, *,
                actions: dict[str, ActionMeta],
                decls: list[Tool],
                legacy_handle,
                domain: str = "general",
                side_effect: str = SIDE_NONE,
                rbac: str = "",
                doc_track: str = ""):
    """CRUD 碎片合并（action 参数化）：多 Tool 声明 → 单 Tool + action 派发。

    Args:
        name:         合并后工具名（资源名，如 draft/interview/pack）
        description:  工具级一句话描述（后接自动生成的 action 明细段）
        actions:      {action名: ActionMeta}——legacy 必填（指向 decls 中的原工具名）
        decls:        原 Tool 声明列表（逐字保留，schema/描述零漂移的来源）
        legacy_handle: 模块原 handle(name, arguments) 派发函数
        domain/side_effect/rbac/doc_track: 工具级默认（action 级可覆盖）

    Returns:
        (TOOLS, handle)——模块末尾 `TOOLS, handle = consolidate(...)` 一行接管。
        handle 同时接受合并名（按 arguments.action 派发）与 legacy 工具名
        （直接派发，测试/脚本兼容通道；不出现在 TOOLS 表面）。
    """
    by_legacy = {t.name: t for t in decls}
    for a, am in actions.items():
        if am.legacy not in by_legacy:
            raise ValueError(
                f"consolidate({name}): action {a!r} 的 legacy {am.legacy!r} "
                f"不在 decls 中（{sorted(by_legacy)}）")

    # ── 合并 inputSchema：action 枚举 + 各 action 属性并集（同名取首见）──
    props: dict = {"action": {
        "type": "string", "enum": list(actions),
        "description": "要执行的操作（各 action 的参数与必填项见工具描述）"}}
    for am in actions.values():
        schema = by_legacy[am.legacy].inputSchema or {}
        for pn, pd in (schema.get("properties") or {}).items():
            if pn not in props:
                props[pn] = pd
    merged_schema = {"type": "object", "properties": props, "required": ["action"]}

    # ── 合并 description：工具级一句话 + 每 action 首行描述与必填项 ──
    lines = [description, "", "action 明细："]
    for a, am in actions.items():
        decl = by_legacy[am.legacy]
        first = (decl.description or "").strip().split("\n")[0]
        schema = decl.inputSchema or {}
        req = [r for r in (schema.get("required") or []) if r != "action"]
        lines.append(f"- {a}: {first}" + (f"（必填：{'、'.join(req)}）" if req else ""))
    merged_tool = Tool(name=name, description="\n".join(lines),
                       inputSchema=merged_schema)

    # ── 元数据登记 ──
    _TOOL_META[name] = ToolMeta(
        domain=domain, side_effect=side_effect, rbac=rbac,
        doc_track=doc_track, actions=dict(actions))

    # ── handle 包装：合并名按 action 派发；legacy 名直通（兼容通道）──
    async def handle(tool_name: str, arguments: dict) -> list[TextContent]:
        args = dict(arguments or {})
        if tool_name == name:
            action = str(args.pop("action", "") or "")
            am = actions.get(action)
            if am is None:
                return [TextContent(type="text", text=(
                    f"错误：未知 action: {action!r}；"
                    f"可用: {'、'.join(actions)}"))]
            # T-982b：params 注入——legacy 工具自带 action 参数名碰撞时，
            # 合并层 pop 掉的 action 键需按声明回填（用户显式传参优先）
            for k, v in am.params.items():
                args.setdefault(k, v)
            return await legacy_handle(am.legacy, args)
        # legacy 工具名直通（测试/脚本兼容通道）；未知名由 legacy_handle 返回 []
        return await legacy_handle(tool_name, args)

    return [merged_tool], handle
