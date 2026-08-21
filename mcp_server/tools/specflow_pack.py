"""specflow_pack.py — 材料包/信息包 MCP 工具（M03 §5.2，T-030/T-031/T-032）。
>
> T-982 收敛：6 工具合并为单 pack 工具（action=assemble/read_section/parse_status/extract_topics/read_material/freshness）。

工具：
  pack_assemble            六分区装配 → info_pack.yaml（确定性，零 LLM）
  pack_read_section        读单分区（面试官按需取上下文）
  material_parse_status    材料状态机快照（纯读）
  material_extract_topics  议题候选提取（LLM 在 Agent 侧，工具落库 confirmed=0）
  read_material            读材料解析产物三视图：summary 概览/topics 候选/raw 分页原文（T-934）
  pack_freshness_check     新鲜度校验（纯读）

约束：写域仅 .specflow/（材料/信息包）；解析产物 _parsed/ 为派生物可重建。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent
from mcp_server.tools.tool_meta import ActionMeta, SIDE_DRAFT, consolidate  # T-982

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

read_material_tool = Tool(
    name="read_material",
    description="读材料解析产物（summary 概览 / topics 议题候选 / raw 原文分页）。"
                "面试官引用材料原文做证据用；未解析或文件缺失时诚实报错。",
    inputSchema={
        "type": "object",
        "properties": {
            "material_id": {"type": "string", "description": "材料 ID MAT-xxx"},
            "section": {"type": "string", "enum": ["summary", "topics", "raw"],
                        "description": "视图：summary=概览+头部摘要（默认）"
                                       "/topics=议题候选清单/raw=解析原文分页"},
            "offset": {"type": "integer", "minimum": 0,
                       "description": "raw 分页起始字符偏移（默认 0）"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20000,
                      "description": "raw 分页每页字符数（默认 4000，上限 20000）"},
        },
        "required": ["material_id"],
    },
)

_TOOL_DECLS = [
    pack_assemble_tool,
    pack_read_section_tool,
    material_parse_status_tool,
    material_extract_topics_tool,
    read_material_tool,
    pack_freshness_check_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "pack_assemble": _handle_pack_assemble,
        "pack_read_section": _handle_pack_read_section,
        "material_parse_status": _handle_material_parse_status,
        "material_extract_topics": _handle_material_extract_topics,
        "read_material": _handle_read_material,
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


async def _handle_read_material(args: dict) -> list[TextContent]:
    """读材料解析产物三视图（T-934）：summary 概览 / topics 候选 / raw 分页原文。

    摘要为解析文本头部派生（材料本体无 summary 字段，不编造）；
    解析产物缺失时回退原文预览，两者皆无 → 诚实报错。
    """
    try:
        import json
        from pathlib import Path
        from workbench.backend.services.specflow.materials_service import (
            _db_conn, db_list_topics)
        from specflow.materials import store
        ws, sf_base = _ctx()
        if not ws:
            return [TextContent(type="text", text="读取失败: 缺少工作区上下文")]
        mid = str(args["material_id"])
        section = str(args.get("section") or "summary")
        if section not in ("summary", "topics", "raw"):
            return [TextContent(type="text",
                                text="读取失败: section 仅支持 summary|topics|raw")]

        conn = _db_conn()
        try:
            m = store.get_material(conn, mid)
        finally:
            conn.close()
        if not m or m["workspace"] != ws:
            return [TextContent(type="text", text=f"读取失败: 材料不存在: {mid}")]

        iv_dir = Path(sf_base) / "interviews" / m["iv_id"]
        stem = Path(m["filename"]).stem or mid
        parsed_dir = iv_dir / "materials" / "_parsed"

        if section == "topics":
            topics = db_list_topics(m["iv_id"], ws, material_id=mid)
            return [TextContent(type="text", text=str({
                "material_id": mid, "count": len(topics),
                "topics": [{"topic_id": t["topic_id"], "title": t["title"],
                            "confirmed": t["confirmed"],
                            "priority_hint": t.get("priority_hint", ""),
                            "prd_section": t.get("prd_section", "")}
                           for t in topics],
            }))]

        text = ""
        source = "parsed"
        extract = parsed_dir / f"{stem}.extract.txt"
        if extract.is_file():
            text = extract.read_text(encoding="utf-8")
        else:
            raw_file = iv_dir / "materials" / m["filename"]
            if raw_file.is_file():
                from workbench.backend.services.file_preview import preview_text
                text, _fmt = preview_text(raw_file)
                source = "raw"
        if not text:
            return [TextContent(type="text", text=str({
                "material_id": mid, "filename": m["filename"],
                "status": m["status"],
                "error": "解析产物缺失且原文不可读（failed 材料无产物，"
                         "parse_error: " + str(m.get("parse_error") or "") + "）",
            }))]

        if section == "summary":
            chunks_n = 0
            chunks_file = parsed_dir / f"{stem}.chunks.json"
            if chunks_file.is_file():
                try:
                    chunks_n = len(json.loads(chunks_file.read_text(encoding="utf-8")))
                except Exception:
                    chunks_n = 0
            head = " ".join(text[:600].split())
            if len(text) > 600:
                head += "…"
            return [TextContent(type="text", text=str({
                "material_id": mid, "iv_id": m["iv_id"],
                "filename": m["filename"], "fmt": m["fmt"],
                "status": m["status"], "pack_included": m["pack_included"],
                "source": source, "total_chars": len(text), "chunks": chunks_n,
                "summary": head,
                "hint": "原文分页读取用 section=raw（offset/limit）",
            }))]

        # raw 分页（offset/limit 字符切片，has_more 提示翻页）
        offset = max(0, int(args.get("offset") or 0))
        limit = min(20000, max(1, int(args.get("limit") or 4000)))
        return [TextContent(type="text", text=str({
            "material_id": mid, "section": "raw", "source": source,
            "offset": offset, "limit": limit, "total_chars": len(text),
            "has_more": offset + limit < len(text),
            "text": text[offset:offset + limit],
        }))]
    except Exception as e:
        return [TextContent(type="text", text=f"读取失败: {e}")]


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


# ══════════════════════════════════════════════════════════
# T-982 工具收敛：6 碎片合并为单 pack 工具（action 参数化）
# ══════════════════════════════════════════════════════════
TOOLS, handle = consolidate(
    "pack",
    "材料包与材料解析：assemble 组装材料包、read_section 读包章节、parse_status 材料解析状态、"
    "extract_topics 提取话题、read_material 读材料解析产物（summary/topics/raw 三视图）、"
    "freshness 新鲜度检查。",
    actions={
        "assemble": ActionMeta(legacy="pack_assemble", side_effect=SIDE_DRAFT),
        "read_section": ActionMeta(legacy="pack_read_section"),
        "parse_status": ActionMeta(legacy="material_parse_status"),
        "extract_topics": ActionMeta(legacy="material_extract_topics"),
        "read_material": ActionMeta(legacy="read_material"),
        "freshness": ActionMeta(legacy="pack_freshness_check"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="specflow",
    rbac="product",
)
