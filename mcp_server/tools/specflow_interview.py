"""specflow_interview.py — 面试 MCP 工具（M02 §5.2，T-020）。
>
> T-982 收敛：7 工具合并为单 interview 工具（action=open/read_baseline/ask/next/record/p0_check/append）。

挂载 server.TOOL_MODULES，约束：校验类纯读无副作用；
所有写工具只写 .specflow/，绝不写 specs/ 与 .specguard/。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent
from mcp_server.tools.tool_meta import ActionMeta, SIDE_DRAFT, consolidate  # T-982

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
    description="基线锚点摘录（内部走 specstd.anchors 扫描当前工作区 specs/，纯读）",
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

iv_ask_question_tool = Tool(
    name="iv_ask_question",
    description="登记分级问题（面试官 Agent 生成问题后入库，供产品回答；仅写 .specflow 侧 DB）",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string", "description": "面试编号 IV-xxx"},
            "priority": {"type": "string", "enum": ["P0", "P1", "P2"]},
            "question": {"type": "string", "description": "问题原文"},
            "chapter": {"type": "integer", "description": "11 章维度编号 1-11"},
            "spq_ref": {"type": "string", "description": "SPQ 反哺引用"},
            "fr_refs": {"type": "string", "description": "关联 FR 锚点（逗号分隔）"},
        },
        "required": ["iv_id", "priority", "question"],
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

_TOOL_DECLS = [
    iv_open_topic_tool,
    iv_read_baseline_tool,
    iv_ask_question_tool,
    iv_next_question_tool,
    iv_record_answer_tool,
    iv_p0_clear_check_tool,
    iv_append_transcript_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "iv_open_topic": _handle_iv_open_topic,
        "iv_read_baseline": _handle_iv_read_baseline,
        "iv_ask_question": _handle_iv_ask_question,
        "iv_next_question": _handle_iv_next_question,
        "iv_record_answer": _handle_iv_record_answer,
        "iv_p0_clear_check": _handle_iv_p0_clear_check,
        "iv_append_transcript": _handle_iv_append_transcript,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return await handler(arguments)


def _require_workspace() -> tuple[str, str]:
    """获取工作区/emp 上下文；缺失时返回错误提示（写路径 fail-closed）。"""
    from specstd.workspace import get_context_workspace, get_context_emp_no
    ws = get_context_workspace() or ""
    emp = get_context_emp_no() or ""
    if not ws:
        return "", "缺少工作区上下文（SG_WORKSPACE/认证链未注入）"
    return ws, ""


async def _handle_iv_open_topic(args: dict) -> list[TextContent]:
    try:
        from workbench.backend.services.specflow.interview_service import open_interview
        from specstd.workspace import specflow_dir, get_context_workspace, get_context_emp_no

        ws = get_context_workspace() or ""
        if not ws:
            return [TextContent(type="text",
                                text="开标失败: 缺少工作区上下文（写路径需要 SG_WORKSPACE/认证链注入）")]
        # T-014 归属留痕：发起人从认证链 emp contextvar 注入（MCP 无登录态时留空）
        emp = get_context_emp_no() or ""

        sf_base = specflow_dir(emp=emp)
        result = open_interview(
            title=args["title"],
            initiator_emp=emp,
            initiator_role="",
            source=args.get("source", []),
            target_delta=args.get("target_delta", ""),
            session_id=args.get("session_id", ""),
            workspace=ws,
            specflow_base=sf_base,
        )
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"开标失败: {e}")]


async def _handle_iv_read_baseline(args: dict) -> list[TextContent]:
    """基线锚点摘录：specstd.anchors 扫描当前工作区 specs/，返回真实 FR 信息。

    不存在的 FR 返回 not_found + 可用锚点自愈提示（诚实结果，不编造）。
    """
    from specstd.anchors import scan_anchors
    from specstd.workspace import get_workspace_root

    fr_refs = args.get("fr_refs", [])
    ws_root = get_workspace_root()
    if not ws_root:
        return [TextContent(type="text", text="错误：无激活的工作区")]
    anchors = scan_anchors(ws_root)
    results = []
    for fr in fr_refs:
        info = anchors.get(str(fr))
        if not info:
            results.append({"fr": fr, "status": "not_found"})
            continue
        results.append({
            "fr": fr,
            "status": "found",
            "title": info.title,
            "module": info.module,
            "feature": info.feature,
            "ac_ids": list(info.ac_ids),
            "file": info.file_path,
        })
    # 附可引用锚点清单（自愈提示）
    available = sorted(anchors.keys())
    return [TextContent(type="text", text=str({
        "baseline_refs": results,
        "available_frs": available[:50],
        "total_frs": len(available),
    }))]


async def _handle_iv_ask_question(args: dict) -> list[TextContent]:
    """登记分级问题（面试官 Agent 生成 → 入库 → 产品可回答）。"""
    try:
        from specflow.interview.iv_lifecycle import validate_iv_id
        from workbench.backend.services.specflow.sf_store import create_question

        iv_id = args["iv_id"]
        err = validate_iv_id(iv_id)
        if err:
            return [TextContent(type="text", text=f"登记失败: {err}")]
        priority = args["priority"]
        if priority not in ("P0", "P1", "P2"):
            return [TextContent(type="text", text=f"登记失败: 非法优先级 {priority!r}")]
        question = args["question"]
        if not question.strip():
            return [TextContent(type="text", text="登记失败: question 不能为空")]

        ws, ws_err = _require_workspace()
        if ws_err:
            return [TextContent(type="text", text=f"登记失败: {ws_err}")]

        q = create_question(
            iv_id=iv_id,
            priority=priority,
            question=question,
            chapter=args.get("chapter", 0),
            spq_ref=args.get("spq_ref", ""),
            fr_refs=args.get("fr_refs", ""),
            workspace=ws,
        )
        return [TextContent(type="text", text=str({
            "status": "created",
            "q_id": q["q_id"],
            "priority": q["priority"],
            "question": q["question"],
        }))]
    except ValueError as e:
        return [TextContent(type="text", text=f"登记失败: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"登记失败: {e}")]


async def _handle_iv_next_question(args: dict) -> list[TextContent]:
    iv_id = args["iv_id"]
    from specflow.interview.topic import load_topic
    from specflow.interview.iv_lifecycle import validate_iv_id
    from specstd.workspace import specflow_dir, get_context_workspace
    from workbench.backend.services.specflow.sf_store import list_questions

    err = validate_iv_id(iv_id)
    if err:
        return [TextContent(type="text", text=f"错误: {err}")]
    sf_base = specflow_dir()
    topic = load_topic(iv_id, sf_base)
    ws = get_context_workspace() or ""
    questions = list_questions(iv_id, status="pending", workspace=ws)
    return [TextContent(type="text", text=str({
        "iv_id": iv_id,
        "status": topic.status if topic else "unknown",
        "pending_questions": len(questions),
        "questions": questions,
    }))]


async def _handle_iv_record_answer(args: dict) -> list[TextContent]:
    from workbench.backend.services.specflow.sf_store import (
        update_answer, get_question,
    )
    from specstd.workspace import get_context_workspace

    q_id = args["q_id"]
    answer = args["answer"]
    ws = get_context_workspace() or ""

    q = get_question(q_id)
    if not q or q.get("workspace", "") != ws:
        return [TextContent(type="text", text=f"记录失败: 问题 {q_id} 不存在")]
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
    from specflow.interview.iv_lifecycle import validate_iv_id
    from specstd.workspace import get_context_workspace

    iv_id = args["iv_id"]
    err = validate_iv_id(iv_id)
    if err:
        return [TextContent(type="text", text=f"错误: {err}")]
    ws = get_context_workspace() or ""
    gate = db_get_gate(iv_id, ws)
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
    from specflow.interview.iv_lifecycle import append_transcript, iv_transcript_path, validate_iv_id
    from specstd.workspace import specflow_dir

    iv_id = args["iv_id"]
    err = validate_iv_id(iv_id)
    if err:
        return [TextContent(type="text", text=f"错误: {err}")]

    sf_base = specflow_dir()
    tpath = iv_transcript_path(sf_base, iv_id)
    entry = {
        "role": args["role"],
        "text": args["text"],
        "q_ref": args.get("q_ref", ""),
    }
    append_transcript(tpath, entry)
    return [TextContent(type="text", text=str({"status": "appended"}))]


# ══════════════════════════════════════════════════════════
# T-982 工具收敛：7 碎片合并为单 interview 工具（action 参数化）
# ══════════════════════════════════════════════════════════
TOOLS, handle = consolidate(
    "interview",
    "需求面试会话状态机：open 开话题、read_baseline 读基线、ask 提问、next 下一问、"
    "record 记录回答（落台账）、p0_check P0 清零检查、append 追加 transcript。",
    actions={
        "open": ActionMeta(legacy="iv_open_topic", side_effect=SIDE_DRAFT),
        "read_baseline": ActionMeta(legacy="iv_read_baseline"),
        "ask": ActionMeta(legacy="iv_ask_question"),
        "next": ActionMeta(legacy="iv_next_question", side_effect=SIDE_DRAFT),
        "record": ActionMeta(legacy="iv_record_answer", side_effect=SIDE_DRAFT),
        "p0_check": ActionMeta(legacy="iv_p0_clear_check"),
        "append": ActionMeta(legacy="iv_append_transcript", side_effect=SIDE_DRAFT),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="specflow",
    rbac="product",
)
