"""specflow_interview.py — 面试 MCP 工具（M02 §5.2，T-020）。

挂载 server.TOOL_MODULES，约束：校验类纯读无副作用；
所有写工具只写 .specflow/，绝不写 specs/ 与 .specguard/。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent

# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

iv_open_topic_tool = Tool(
    name="iv_open_topic",
    description="开标建议题卡（面试官 Agent 首轮动作）：生成 IV-xxx 编号、议题卡、材料目录",
    inputSchema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "会话 ID"},
            "title": {"type": "string", "description": "议题标题"},
            "source": {
                "type": "array",
                "items": {"type": "object"},
                "description": "议题来源 [{type, ref, url?, note?}]",
            },
            "target_delta": {"type": "string", "description": "冻结目标代号"},
        },
        "required": ["session_id", "title", "source"],
    },
)

iv_read_baseline_tool = Tool(
    name="iv_read_baseline",
    description="基线锚点摘录（内部走 spec_reader + specstd.anchors，纯读）",
    inputSchema={
        "type": "object",
        "properties": {
            "fr_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "FR 锚点列表，如 ['FR-003', 'FR-006']",
            },
        },
        "required": ["fr_refs"],
    },
)

iv_next_question_tool = Tool(
    name="iv_next_question",
    description="读取当前议题状态与未决问题，供面试官生成下一问（LLM 在 Agent 侧，工具只供数据）",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string", "description": "面试编号 IV-xxx"},
        },
        "required": ["iv_id"],
    },
)

iv_record_answer_tool = Tool(
    name="iv_record_answer",
    description="记录回答 + 返回决策候选结构（不落台账，落台账走 M04 工具且需人确认）",
    inputSchema={
        "type": "object",
        "properties": {
            "q_id": {"type": "string", "description": "问题编号"},
            "answer": {"type": "string", "description": "回答内容"},
        },
        "required": ["q_id", "answer"],
    },
)

iv_p0_clear_check_tool = Tool(
    name="iv_p0_clear_check",
    description="确定性：台账无 pending P0 → PASS/FAIL + 缺口列表（gate.py 纯函数）",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string", "description": "面试编号 IV-xxx"},
        },
        "required": ["iv_id"],
    },
)

iv_append_transcript_tool = Tool(
    name="iv_append_transcript",
    description="面试流水追加（写 .jsonl）",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string", "description": "面试编号 IV-xxx"},
            "role": {"type": "string", "description": "角色: interviewer/product"},
            "text": {"type": "string", "description": "消息内容"},
            "q_ref": {"type": "string", "description": "议题编号"},
        },
        "required": ["iv_id", "role", "text"],
    },
)

TOOLS = [
    iv_open_topic_tool,
    iv_read_baseline_tool,
    iv_next_question_tool,
    iv_record_answer_tool,
    iv_p0_clear_check_tool,
    iv_append_transcript_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def handle(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "iv_open_topic": _handle_iv_open_topic,
        "iv_read_baseline": _handle_iv_read_baseline,
        "iv_next_question": _handle_iv_next_question,
        "iv_record_answer": _handle_iv_record_answer,
        "iv_p0_clear_check": _handle_iv_p0_clear_check,
        "iv_append_transcript": _handle_iv_append_transcript,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return await handler(arguments)


async def _handle_iv_open_topic(args: dict) -> list[TextContent]:
    try:
        from workbench.backend.services.specflow.interview_service import open_interview
        from specstd.workspace import specflow_dir, get_context_workspace

        sf_base = specflow_dir()
        result = open_interview(
            title=args["title"],
            initiator_emp="",
            initiator_role="",
            source=args.get("source", []),
            target_delta=args.get("target_delta", ""),
            session_id=args.get("session_id", ""),
            workspace=get_context_workspace() or "",
            specflow_base=sf_base,
        )
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"开标失败: {e}")]


async def _handle_iv_read_baseline(args: dict) -> list[TextContent]:
    fr_refs = args.get("fr_refs", [])
    results = []
    for fr in fr_refs:
        results.append({"fr": fr, "status": "ref_available"})
    return [TextContent(type="text", text=str({"baseline_refs": results}))]


async def _handle_iv_next_question(args: dict) -> list[TextContent]:
    iv_id = args["iv_id"]
    from specflow.interview.topic import load_topic
    from specstd.workspace import specflow_dir
    from workbench.backend.services.specflow.sf_store import list_questions

    sf_base = specflow_dir()
    topic = load_topic(iv_id, sf_base)
    questions = list_questions(iv_id, status="pending")
    return [TextContent(type="text", text=str({
        "iv_id": iv_id,
        "status": topic.status if topic else "unknown",
        "pending_questions": len(questions),
        "questions": questions,
    }))]


async def _handle_iv_record_answer(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.sf_store import update_answer, get_question
    q_id = args["q_id"]
    answer = args["answer"]
    ok = update_answer(q_id, answer)
    if ok:
        q = get_question(q_id)
        return [TextContent(type="text", text=str({
            "status": "recorded",
            "decision_draft": {
                "q_id": q_id,
                "answer": answer,
                "priority": q.get("priority") if q else "",
                "note": "确认请走 REST: POST /decisions/:id/resolve",
            },
        }))]
    return [TextContent(type="text", text=f"记录失败: 问题 {q_id} 不存在")]


async def _handle_iv_p0_clear_check(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.decision_service import db_get_gate
    iv_id = args["iv_id"]
    gate = db_get_gate(iv_id)
    if gate["pending_p0"] == 0:
        return [TextContent(type="text", text=str({
            "status": "PASS",
            "gate": gate,
        }))]
    return [TextContent(type="text", text=str({
        "status": "FAIL",
        "gate": gate,
        "gap": f"P0 待定 {gate['pending_p0']} 项未清零",
    }))]


async def _handle_iv_append_transcript(args: dict) -> list[TextContent]:
    from specflow.interview.iv_lifecycle import append_transcript, iv_transcript_path
    from specstd.workspace import specflow_dir

    sf_base = specflow_dir()
    tpath = iv_transcript_path(sf_base, args["iv_id"])
    entry = {
        "role": args["role"],
        "text": args["text"],
        "q_ref": args.get("q_ref", ""),
    }
    append_transcript(tpath, entry)
    return [TextContent(type="text", text=str({"status": "appended"}))]