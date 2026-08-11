"""specflow_refs.py — 外部锚点/禅道作业 MCP 工具（M06 §5.3，T-056）。

sf_list_external_refs  纯读：外部锚点查询（M10 血缘链数据源）
sf_register_external_ref 写但低风险：仅登记引用，不触禅道
sf_get_zentao_job      纯读：作业状态查询

story/bug 创建与故事点回写**不暴露 MCP**——触外部系统的写动作必须
人在 UI/REST 确认（铁律 1/4）。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

sf_list_external_refs_tool = Tool(
    name="sf_list_external_refs",
    description="查询外部锚点登记（禅道故事/BUG/PR 等，纯读）",
    inputSchema={
        "type": "object",
        "properties": {
            "linked_type": {"type": "string",
                            "description": "关联类型 delta/fr_anchor/spq/scenario/run/interview"},
            "linked": {"type": "string", "description": "关联对象编号，如 grid-rule-perf"},
            "ref_type": {"type": "string",
                         "description": "外部资产类型 zt_story/zt_bug/zt_task/pr/unit_test_report"},
        },
    },
)

sf_register_external_ref_tool = Tool(
    name="sf_register_external_ref",
    description="登记外部资产引用（仅登记不触禅道；已存在返回原行）",
    inputSchema={
        "type": "object",
        "properties": {
            "type": {"type": "string",
                     "enum": ["zt_story", "zt_bug", "zt_task", "pr", "unit_test_report"]},
            "ref": {"type": "string", "description": "外部编号，如 ZT-STORY-4821 / PR#482"},
            "linked_type": {"type": "string",
                            "enum": ["delta", "fr_anchor", "spq", "scenario", "run", "interview"]},
            "linked": {"type": "string", "description": "关联对象编号"},
            "ref_url": {"type": "string", "description": "外部可跳转 URL（可选）"},
            "note": {"type": "string", "description": "备注（可选）"},
        },
        "required": ["type", "ref", "linked_type", "linked"],
    },
)

sf_get_zentao_job_tool = Tool(
    name="sf_get_zentao_job",
    description="查询禅道写作业状态（幂等重入/审计，纯读）",
    inputSchema={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "作业 ID（ZTJ-xxx）"},
        },
        "required": ["job_id"],
    },
)

TOOLS = [
    sf_list_external_refs_tool,
    sf_register_external_ref_tool,
    sf_get_zentao_job_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def _handle_sf_list_external_refs(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow import sf_refs_store
    from specstd.workspace import get_context_workspace
    ws = get_context_workspace() or ""
    rows = sf_refs_store.list_refs(
        workspace=ws,
        ref_type=args.get("ref_type", ""),
        linked_type=args.get("linked_type", ""),
        linked=args.get("linked", ""))
    return [TextContent(type="text", text=str({
        "workspace": ws,
        "count": len(rows),
        "refs": rows,
    }))]


async def _handle_sf_register_external_ref(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow import sf_refs_store
    from specstd.workspace import get_context_workspace
    ws = get_context_workspace() or ""
    row = sf_refs_store.register_ref(
        ws, args["type"], args["ref"], args["linked_type"], args["linked"],
        ref_url=args.get("ref_url", ""),
        note=args.get("note", ""),
        registered_by="agent:mcp")
    return [TextContent(type="text", text=str({
        "workspace": ws,
        "registered": True,
        "duplicate": row.get("duplicate", False),
        "ref": {k: row[k] for k in ("type", "ref", "linked_type", "linked")
                if k in row},
    }))]


async def _handle_sf_get_zentao_job(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow import sf_refs_store
    job = sf_refs_store.get_job(args["job_id"])
    if job is None:
        return [TextContent(type="text", text=str({
            "found": False, "job_id": args["job_id"],
        }))]
    return [TextContent(type="text", text=str({
        "found": True,
        "job": {k: job.get(k) for k in
                ("job_id", "kind", "status", "zt_ref", "attempt",
                 "created_by", "created_at", "finished_at")},
    }))]


HANDLERS = {
    "sf_list_external_refs": _handle_sf_list_external_refs,
    "sf_register_external_ref": _handle_sf_register_external_ref,
    "sf_get_zentao_job": _handle_sf_get_zentao_job,
}
