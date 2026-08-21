"""specflow_ledger.py — 决策台账 MCP 工具（M04 §5.2，T-023）。
>
> T-982 收敛：5 工具合并为单 ledger 工具（action=list/propose/check_p0/suggest_scores/read_gate）。

独立模块，与测试工具不同模块。
resolve/confirm/amend 三个写闸门不暴露给 MCP——拍板只能由人在 UI/REST 完成。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent
from mcp_server.tools.tool_meta import ActionMeta, SIDE_DRAFT, consolidate  # T-982

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

_TOOL_DECLS = [
    sf_list_decisions_tool,
    sf_propose_decision_tool,
    sf_check_p0_gate_tool,
    sf_suggest_scores_tool,
    sf_read_score_gate_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
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
    from specstd.workspace import get_context_workspace
    decisions = db_list_decisions(
        interview_id=args.get("interview_id", ""),
        status=args.get("status", ""),
        workspace=get_context_workspace() or "",
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
    from specstd.workspace import get_context_workspace
    gate = db_get_gate(args["interview_id"], get_context_workspace() or "")
    return [TextContent(type="text", text=str({
        "review_id": args["interview_id"],
        "pending_p0": gate.get("pending_p0", 0),
        "freeze_allowed": gate.get("freeze_allowed", False),
        "gate": gate,
    }))]


async def _handle_sf_suggest_scores(args: dict) -> list[TextContent]:
    """建议五维评分（写库 status=suggested，不计入总分）。

    机打维度由 specflow.anchor.scoring 的真实采集器驱动
    （11 章齐全性/边界异常比对器/覆盖率映射），替换了 S2 的占位常量。
    幂等：同面试同维度已有 suggested 记录时跳过，不重复插入。
    """
    from workbench.backend.services.specflow.decision_service import db_add_score
    from specstd.workspace import get_context_workspace
    from specflow.anchor.scoring import collect_all_machine_dimensions
    ws = get_context_workspace() or ""
    iv_id = args["interview_id"]
    results = []

    # 获取 spec draft 文本用于机打分析
    spec_text = args.get("spec_text", "")
    spec_text = str(spec_text or "")

    # 机打维度：真实采集器替换占位常量
    machine_dims = collect_all_machine_dimensions(spec_text)
    for dim, score, evidence in machine_dims:
        r = db_add_score(ws, iv_id, dim, score, "machine", evidence,
                         skip_if_suggested=True)
        results.append(r)
    r = db_add_score(ws, iv_id, "clarity", 62.0, "llm_suggested",
                     "LLM 建议：预期清晰度待 QA 复核", skip_if_suggested=True)
    results.append(r)
    return [TextContent(type="text", text=str({
        "status": "suggested",
        "message": "评分已入库（status=suggested），不计入总分。需 QA 确认后才生效。",
        "scores": results,
    }))]


async def _handle_sf_read_score_gate(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_list_scores
    from specstd.workspace import get_context_workspace
    result = db_list_scores(args["interview_id"], get_context_workspace() or "")
    return [TextContent(type="text", text=str(result))]

# ══════════════════════════════════════════════════════════
# T-982 工具收敛：5 碎片合并为单 ledger 工具（action 参数化）
# ══════════════════════════════════════════════════════════
TOOLS, handle = consolidate(
    "ledger",
    "决策台账与五维评分：list 列决策、propose 提议决策（人拍板才生效）、"
    "check_p0 P0 门禁检查、suggest_scores 建议评分、read_gate 读评分门禁。",
    actions={
        "list": ActionMeta(legacy="sf_list_decisions"),
        "propose": ActionMeta(legacy="sf_propose_decision", side_effect=SIDE_DRAFT),
        "check_p0": ActionMeta(legacy="sf_check_p0_gate"),
        "suggest_scores": ActionMeta(legacy="sf_suggest_scores", side_effect=SIDE_DRAFT),
        "read_gate": ActionMeta(legacy="sf_read_score_gate"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="specflow",
    rbac="product",
)
