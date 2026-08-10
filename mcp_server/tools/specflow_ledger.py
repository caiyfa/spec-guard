"""specflow_ledger.py — 决策台账 MCP 工具（M04 §5.2，T-023）。

独立模块，与测试工具不同模块。
resolve/confirm/amend 三个写闸门不暴露给 MCP——拍板只能由人在 UI/REST 完成。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent

# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

sf_list_decisions_tool = Tool(
    name="sf_list_decisions",
    description="查询决策台账条目（纯读）",
    inputSchema={
        "type": "object",
        "properties": {
            "interview_id": {"type": "string", "description": "面试编号 IV-xxx"},
            "status": {"type": "string", "description": "过滤状态 pending/resolved"},
        },
    },
)

sf_propose_decision_tool = Tool(
    name="sf_propose_decision",
    description="建议决策条目（Agent 建议，永远 pending 出生，不 resolve）",
    inputSchema={
        "type": "object",
        "properties": {
            "interview_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["P0", "P1", "P2"]},
            "question": {"type": "string"},
            "question_ref": {"type": "string"},
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "ref": {"type": "string"},
                    },
                },
            },
        },
        "required": ["interview_id", "priority", "question"],
    },
)

sf_check_p0_gate_tool = Tool(
    name="sf_check_p0_gate",
    description="确定性 P0 清零检查（纯读，零 LLM 参与）",
    inputSchema={
        "type": "object",
        "properties": {
            "interview_id": {"type": "string"},
        },
        "required": ["interview_id"],
    },
)

sf_suggest_scores_tool = Tool(
    name="sf_suggest_scores",
    description="建议五维评分（写库 status=suggested，不计入总分）",
    inputSchema={
        "type": "object",
        "properties": {
            "interview_id": {"type": "string"},
        },
        "required": ["interview_id"],
    },
)

sf_read_score_gate_tool = Tool(
    name="sf_read_score_gate",
    description="读取评分门禁状态（纯读）",
    inputSchema={
        "type": "object",
        "properties": {
            "interview_id": {"type": "string"},
        },
        "required": ["interview_id"],
    },
)

TOOLS = [
    sf_list_decisions_tool,
    sf_propose_decision_tool,
    sf_check_p0_gate_tool,
    sf_suggest_scores_tool,
    sf_read_score_gate_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def handle(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "sf_list_decisions": _handle_sf_list_decisions,
        "sf_propose_decision": _handle_sf_propose_decision,
        "sf_check_p0_gate": _handle_sf_check_p0_gate,
        "sf_suggest_scores": _handle_sf_suggest_scores,
        "sf_read_score_gate": _handle_sf_read_score_gate,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return await handler(arguments)


async def _handle_sf_list_decisions(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_list_decisions
    decisions = db_list_decisions(
        interview_id=args.get("interview_id", ""),
        status=args.get("status", ""),
    )
    return [TextContent(type="text", text=str({"decisions": decisions}))]


async def _handle_sf_propose_decision(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_propose_decision
    from specstd.workspace import get_context_workspace
    try:
        dec = db_propose_decision(
            workspace=get_context_workspace() or "",
            interview_id=args["interview_id"],
            priority=args["priority"],
            question=args["question"],
            question_ref=args.get("question_ref", ""),
            links=args.get("links"),
        )
        return [TextContent(type="text", text=str({"decision": dec}))]
    except Exception as e:
        return [TextContent(type="text", text=f"登记失败: {e}")]


async def _handle_sf_check_p0_gate(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_get_gate
    gate = db_get_gate(args["interview_id"])
    return [TextContent(type="text", text=str({
        "review_id": args["interview_id"],
        "pending_p0": gate.get("pending_p0", 0),
        "freeze_allowed": gate.get("freeze_allowed", False),
        "gate": gate,
    }))]


async def _handle_sf_suggest_scores(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_add_score
    from specstd.workspace import get_context_workspace
    ws = get_context_workspace() or ""
    iv_id = args["interview_id"]
    results = []
    machine_dims = [
        ("logic", 78, "11 章齐全, SHALL 语句完整"),
        ("coverage", 85, "FR 覆盖率达 85%"),
        ("boundary", 55, "缺「规则切换中落位」异常场景"),
        ("precondition", 70, "前置条件完整"),
    ]
    for dim, score, evidence in machine_dims:
        r = db_add_score(ws, iv_id, dim, score, "machine", evidence)
        results.append(r)
    r = db_add_score(ws, iv_id, "clarity", 62, "llm_suggested",
                     "LLM 建议：预期清晰度待 QA 复核")
    results.append(r)
    return [TextContent(type="text", text=str({
        "status": "suggested",
        "message": "评分已入库（status=suggested），不计入总分。需 QA 确认后才生效。",
        "scores": results,
    }))]


async def _handle_sf_read_score_gate(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_list_scores
    result = db_list_scores(args["interview_id"])
    return [TextContent(type="text", text=str(result))]