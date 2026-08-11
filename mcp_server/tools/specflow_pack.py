"""specflow_pack.py — 材料包/信息包 MCP 工具（M03 §5.2，T-030/T-031/T-032）。

工具：
  pack_assemble            六分区装配 → info_pack.yaml（确定性，零 LLM）
  pack_read_section        读单分区（面试官按需取上下文）
  material_parse_status    材料状态机快照（纯读）
  material_extract_topics  议题候选提取（LLM 在 Agent 侧，工具落库 confirmed=0）
  pack_freshness_check     新鲜度校验（纯读）

约束：写域仅 .specflow/（材料/信息包）；解析产物 _parsed/ 为派生物可重建。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent

# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

pack_assemble_tool = Tool(
    name="pack_assemble",
    description="材料包六分区装配（议题卡/材料/基线/SPQ/上轮报告/历史决策 → info_pack.yaml）。"
                "确定性装配零 LLM；人拍板入包（include）与确认候选（confirm）后才纳入。",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string", "description": "面试编号 IV-xxx"},
        },
        "required": ["iv_id"],
    },
)

pack_read_section_tool = Tool(
    name="pack_read_section",
    description="读信息包单分区（topic_card/materials/baseline/open_spq/last_report/"
                "history_decisions），面试官按需取上下文。",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string"},
            "section": {"type": "string",
                        "description": "分区名: topic_card|materials|baseline|open_spq|last_report|history_decisions"},
        },
        "required": ["iv_id", "section"],
    },
)

material_parse_status_tool = Tool(
    name="material_parse_status",
    description="材料解析状态机快照（uploaded/parsing/parsed/indexed/packed/failed，纯读）。",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string"},
        },
        "required": ["iv_id"],
    },
)

material_extract_topics_tool = Tool(
    name="material_extract_topics",
    description="登记议题候选（Agent 从材料抽取的建议，confirmed=0 出生——"
                "人拍板 confirm 前不进面试上下文）。",
    inputSchema={
        "type": "object",
        "properties": {
            "material_id": {"type": "string", "description": "材料 ID MAT-xxx"},
            "iv_id": {"type": "string"},
            "title": {"type": "string", "description": "议题候选标题"},
            "priority_hint": {"type": "string", "enum": ["P0", "P1", "P2"]},
            "fr_hints": {"type": "array", "items": {"type": "string"},
                         "description": "候选 FR 锚点（词表命中）"},
            "prd_section": {"type": "string", "description": "如 §2.7"},
        },
        "required": ["material_id", "iv_id", "title"],
    },
)

pack_freshness_check_tool = Tool(
    name="pack_freshness_check",
    description="信息包新鲜度校验（基线指纹比对；stale=true 表示基线已变更，材料可能过期）。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string"},
        },
        "required": ["iv_id"],
    },
)

TOOLS = [
    pack_assemble_tool,
    pack_read_section_tool,
    material_parse_status_tool,
    material_extract_topics_tool,
    pack_freshness_check_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def handle(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "pack_assemble": _handle_pack_assemble,
        "pack_read_section": _handle_pack_read_section,
        "material_parse_status": _handle_material_parse_status,
        "material_extract_topics": _handle_material_extract_topics,
        "pack_freshness_check": _handle_pack_freshness_check,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return await handler(arguments)


def _ctx():
    """返回 (workspace, specflow_base)；workspace 缺失时 (空, None) 表示写路径拒绝。"""
    from specstd.workspace import specflow_dir, get_context_workspace, get_context_emp_no
    ws = get_context_workspace() or ""
    if not ws:
        return "", None
    emp = get_context_emp_no() or ""
    return ws, specflow_dir(emp=emp)


def _validate_iv(iv_id: str) -> str:
    from specflow.interview.iv_lifecycle import validate_iv_id
    err = validate_iv_id(iv_id)
    if err:
        return err
    return ""


async def _handle_pack_assemble(args: dict) -> list[TextContent]:
    try:
        from workbench.backend.services.specflow.materials_service import db_assemble_pack
        ws, sf_base = _ctx()
        if not ws:
            return [TextContent(type="text", text="装配失败: 缺少工作区上下文")]
        iv_id = args["iv_id"]
        err = _validate_iv(iv_id)
        if err:
            return [TextContent(type="text", text=f"装配失败: {err}")]
        result = db_assemble_pack(iv_id, ws, sf_base)
        return [TextContent(type="text", text=str({
            "status": "assembled",
            "iv_id": iv_id,
            "sections_available": result.get("sections_available", []),
            "path": result.get("_path", ""),
        }))]
    except Exception as e:
        return [TextContent(type="text", text=f"装配失败: {e}")]


async def _handle_pack_read_section(args: dict) -> list[TextContent]:
    try:
        from workbench.backend.services.specflow.materials_service import db_read_pack_section
        from pathlib import Path
        ws, sf_base = _ctx()
        iv_id = args["iv_id"]
        err = _validate_iv(iv_id)
        if err:
            return [TextContent(type="text", text=f"错误: {err}")]
        result = db_read_pack_section(iv_id, args["section"], Path(sf_base))
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"读取失败: {e}")]


async def _handle_material_parse_status(args: dict) -> list[TextContent]:
    try:
        from workbench.backend.services.specflow.materials_service import db_list_materials
        ws, sf_base = _ctx()
        iv_id = args["iv_id"]
        err = _validate_iv(iv_id)
        if err:
            return [TextContent(type="text", text=f"错误: {err}")]
        materials = db_list_materials(iv_id, ws)
        return [TextContent(type="text", text=str({
            "iv_id": iv_id,
            "materials": [{
                "material_id": m["material_id"],
                "filename": m["filename"],
                "fmt": m["fmt"],
                "status": m["status"],
                "pack_included": m["pack_included"],
                "parse_error": m.get("parse_error", ""),
            } for m in materials],
        }))]
    except Exception as e:
        return [TextContent(type="text", text=f"查询失败: {e}")]


async def _handle_material_extract_topics(args: dict) -> list[TextContent]:
    """登记议题候选（LLM 在 Agent 侧；confirmed=0 出生，人拍板后生效）。"""
    try:
        from workbench.backend.services.specflow.materials_service import db_add_topic
        ws, sf_base = _ctx()
        if not ws:
            return [TextContent(type="text", text="登记失败: 缺少工作区上下文")]
        topic = db_add_topic(
            material_id=args["material_id"],
            iv_id=args["iv_id"],
            workspace=ws,
            title=args["title"],
            priority_hint=args.get("priority_hint", ""),
            fr_hints=args.get("fr_hints"),
            prd_section=args.get("prd_section", ""),
        )
        return [TextContent(type="text", text=str({
            "status": "suggested",
            "topic_id": topic["topic_id"],
            "title": topic["title"],
            "confirmed": topic["confirmed"],
            "note": "候选已登记（confirmed=0）。需人拍板确认后才进面试上下文："
                    "REST POST /materials/{mid}/topics/{tid}/confirm",
        }))]
    except Exception as e:
        return [TextContent(type="text", text=f"登记失败: {e}")]


async def _handle_pack_freshness_check(args: dict) -> list[TextContent]:
    try:
        from workbench.backend.services.specflow.materials_service import db_freshness_check
        from pathlib import Path
        ws, sf_base = _ctx()
        iv_id = args["iv_id"]
        err = _validate_iv(iv_id)
        if err:
            return [TextContent(type="text", text=f"错误: {err}")]
        result = db_freshness_check(iv_id, ws, Path(sf_base))
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"校验失败: {e}")]
