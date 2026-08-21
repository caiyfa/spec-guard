"""feishu_fetch.py — 飞书日程/纪要素材拉取 MCP 工具（T-025/T-026，S2.5）。

链路（全部实测验证，read-only）：
  feishu_calendar_agenda: lark-cli calendar +agenda --as user [--start --end]
  feishu_meeting_notes:   event_id → calendar +meeting → vc +detail
                          → note +detail → docs +fetch（纪要正文主链路）
                          └→ minutes +detail（vc 仅给 minute_token 时兜底）

约束：
- 全部 read 命令（+agenda/+meeting/vc +detail/note +detail/docs +fetch/minutes +detail 均 Risk: read），
  无任何飞书侧写操作（不加评论/不建文档/不改表格）。
- 权限不足不静默降级、不报内部错误：返回结构化信息块（T-026），
  apply_command 仅在存在对应命令时给出（当前仅 minutes +apply-permission）。
- 认证/网络错误返回确定性提示，绝不伪造数据。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mcp.types import Tool, TextContent

# 飞书知识图谱一期 T-914：lark-cli 子进程封装统一为 specflow.feishu_pool.lark_cli
#（原内联实现迁移，行为不变；_PERMISSION_HINTS 为本模块特有保留）
from specflow.feishu_pool.lark_cli import _LARK_TIMEOUT, _lark_command, _run_lark  # noqa: F401

# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

feishu_calendar_agenda_tool = Tool(
    name="feishu_calendar_agenda",
    description="飞书日程列表（T-025）：按时间范围拉取当前用户日程（含 event_id/时间/参会链接），"
                "面试官据此发现会议上下文/纪要素材入口。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "start": {"type": "string",
                      "description": "起始时间 ISO8601（如 2026-08-11T00:00:00+08:00），默认今天零点"},
            "end": {"type": "string",
                    "description": "结束时间 ISO8601，默认 start 次日零点"},
            "max_results": {"type": "integer",
                            "description": "返回条数上限（默认 20）"},
        },
    },
)

feishu_meeting_notes_tool = Tool(
    name="feishu_meeting_notes",
    description="飞书会议纪要正文拉取（T-025）：从日程 event_id 经 +meeting→vc +detail→note +detail→docs +fetch "
                "全链路取纪要正文（vc 仅给 minute_token 时走 minutes +detail 兜底）。"
                "无产物/权限不足返回结构化提示（T-026），不伪造数据。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "日程事件 ID（feishu_calendar_agenda 返回）"},
            "with_keywords": {"type": "boolean",
                              "description": "minutes 兜底时是否附关键词（默认 true）"},
        },
        "required": ["event_id"],
    },
)

feishu_doc_read_tool = Tool(
    name="feishu_doc_read",
    description="飞书云文档正文拉取（S5 增补）：docs +fetch 纯读，支持 /docx/ /wiki/ URL 或 token。"
                "对话中分析飞书文档内容（需求说明/PRD 片段）作为禅道故事草案素材。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "doc": {"type": "string",
                    "description": "飞书文档 URL 或 token（/docx/ 或 /wiki/）"},
            "max_chars": {"type": "integer",
                           "description": "正文截断上限（默认 8000），防撑爆上下文"},
        },
        "required": ["doc"],
    },
)

feishu_base_query_tool = Tool(
    name="feishu_base_query",
    description="飞书多维表格记录查询（S5 增补）：+url-resolve 解析 token 后 +record-list 纯读。"
                "对话中分析表格内容（需求清单/优先级矩阵）作为禅道故事草案素材。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "多维表格分享 URL（/base/）"},
            "table_id": {"type": "string",
                          "description": "可选：指定数据表 ID（缺省取 url-resolve 返回的第一个表）"},
            "limit": {"type": "integer", "description": "记录条数上限（默认 50）"},
        },
        "required": ["url"],
    },
)

feishu_link_read_tool = Tool(
    name="feishu_link_read",
    description="飞书链接统一解析入口：用户直接把 /docx/ /wiki/ /minutes/ /base/ 链接贴在会话中，"
                "自动识别类型并拉取正文/摘要/记录（docs +fetch / minutes +detail / url-resolve + record-list）。"
                "贴链接即可读，无需先取 token。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string",
                      "description": "飞书链接（/docx/ /wiki/ 云文档、/minutes/ 妙记、/base/ 多维表格）"},
            "max_chars": {"type": "integer",
                           "description": "docs 正文截断上限（默认 8000），防撑爆上下文"},
            "limit": {"type": "integer", "description": "base 记录条数上限（默认 50）"},
        },
        "required": ["url"],
    },
)

TOOLS = [
    feishu_calendar_agenda_tool,
    feishu_meeting_notes_tool,
    feishu_doc_read_tool,
    feishu_base_query_tool,
    feishu_link_read_tool,
]


# ══════════════════════════════════════════════════════════
# lark-cli 子进程封装：已统一迁移至 specflow.feishu_pool.lark_cli（T-914）
# ══════════════════════════════════════════════════════════

# 无权限错误关键词（T-026 结构化引导；lark-cli 无权限返回友好错误而非静默降级）
_PERMISSION_HINTS = (
    "无权限", "权限不足", "没有权限", "no permission", "forbidden",
    "permission denied", "denied", "无权", "申请权限",
)


def _permission_block(resource_type: str, title: str = "",
                      url: str = "", minute_token: str = "") -> dict:
    """T-026 无权限结构化信息块（不静默降级，apply_command 仅在有命令时给出）。"""
    block = {
        "status": "permission_denied",
        "resource_type": resource_type,
        "title": title,
        "hint": "无权限，请点击链接申请权限",
    }
    if url:
        block["url"] = url
    if minute_token:
        block["apply_command"] = f"minutes +apply-permission --minute-token {minute_token}"
    else:
        block["apply_command"] = ""  # docs/note 域暂无 apply-permission 命令，走链接申请
    return block


def _looks_like_permission_denied(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _PERMISSION_HINTS)


# ══════════════════════════════════════════════════════════
# 工具处理函数
# ══════════════════════════════════════════════════════════

async def handle(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "feishu_calendar_agenda": _handle_agenda,
        "feishu_meeting_notes": _handle_meeting_notes,
        "feishu_doc_read": _handle_doc_read,
        "feishu_base_query": _handle_base_query,
        "feishu_link_read": _handle_link_read,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return await handler(arguments)


async def _handle_agenda(args: dict) -> list[TextContent]:
    """日程列表：默认今天，支持 ISO8601 时间范围。"""
    try:
        now = datetime.now().astimezone()
        start = args.get("start") or now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = args.get("end") or (
            (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat())
        max_results_arg = args.get("max_results")
        max_results = int(max_results_arg) if max_results_arg is not None else 20
        if max_results < 1 or max_results > 100:
            return [TextContent(type="text", text="错误: max_results 须在 1-100 之间")]

        payload = _run_lark(["calendar", "+agenda", "--as", "user",
                             "--start", start, "--end", end])
        events = payload.get("data") or []
        items = []
        for ev in events[:max_results]:
            items.append({
                "event_id": ev.get("event_id", ""),
                "summary": ev.get("summary", ""),
                "start": (ev.get("start_time") or {}).get("datetime", ""),
                "end": (ev.get("end_time") or {}).get("datetime", ""),
                "organizer": (ev.get("event_organizer") or {}).get("display_name", ""),
                "app_link": ev.get("app_link", ""),
                "meeting_url": (ev.get("vchat") or {}).get("meeting_url", ""),
            })
        return [TextContent(type="text", text=str({
            "status": "ok",
            "range": {"start": start, "end": end},
            "total": len(events),
            "events": items,
            "hint": "取纪要请用 feishu_meeting_notes（入参 event_id）",
        }))]
    except ValueError as e:
        return [TextContent(type="text", text=f"日程拉取失败: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"日程拉取失败: {e}")]


async def _handle_meeting_notes(args: dict) -> list[TextContent]:
    """会议纪要全链路：event_id → +meeting → vc +detail → note/minutes 分支。"""
    try:
        event_id = args["event_id"].strip()
        if not event_id:
            return [TextContent(type="text", text="错误: event_id 不能为空")]
        with_keywords = bool(args.get("with_keywords", True))

        # ① 日程事件 → meeting_id
        m = _run_lark(["calendar", "+meeting", "--as", "user", "--event-ids", event_id])
        meetings = ((m.get("data") or {}).get("meetings")) or []
        if not meetings:
            return [TextContent(type="text", text=str({
                "status": "not_available",
                "event_id": event_id,
                "hint": "该日程无关联会议（非视频会议或无 meeting 记录）",
            }))]
        meeting = meetings[0]
        meeting_id = meeting.get("meeting_id", "")
        if not meeting_id:
            return [TextContent(type="text", text=str({
                "status": "not_available",
                "event_id": event_id,
                "hint": meeting.get("hint", "该日程无 meeting_id"),
            }))]

        # ② meeting_id → note_id / minute_token
        v = _run_lark(["vc", "+detail", "--as", "user", "--meeting-ids", meeting_id])
        vmeetings = ((v.get("data") or {}).get("meetings")) or []
        vmeta = vmeetings[0] if vmeetings else {}
        hint = vmeta.get("hint", "")
        note_id = vmeta.get("note_id", "")
        minute_token = vmeta.get("minute_token", "")
        if not note_id and not minute_token:
            # 会议进行中/无纪要产物：原样友好提示（诚实结果，不报错）
            return [TextContent(type="text", text=str({
                "status": "not_available",
                "event_id": event_id,
                "meeting_id": meeting_id,
                "topic": vmeta.get("topic", ""),
                "hint": hint or "该会议暂无纪要/妙记产物（可能进行中或未开启纪要）",
            }))]

        # ③ 分支 A：note 纪要正文（主链路）
        if note_id:
            n = _run_lark(["note", "+detail", "--as", "user", "--note-id", note_id])
            note = (n.get("data") or {})
            # lark-cli note +detail 实测：token 在 data.note 内层（兼容扁平形态）
            note_inner = note.get("note") or note
            doc_token = note_inner.get("note_doc_token", "")
            if doc_token:
                d = _run_lark(["docs", "+fetch", "--as", "user", "--doc", doc_token])
                return [TextContent(type="text", text=str({
                    "status": "ok",
                    "source": "note",
                    "event_id": event_id,
                    "meeting_id": meeting_id,
                    "topic": vmeta.get("topic", ""),
                    "content": d.get("data") or d,
                    "note_id": note_id,
                }))]
            # note 存在但无正文 token（如逐字稿形态）
            return [TextContent(type="text", text=str({
                "status": "ok",
                "source": "note_meta",
                "event_id": event_id,
                "meeting_id": meeting_id,
                "note": note,
                "hint": "纪要无 note_doc_token，如需逐字稿请用 lark-cli note +transcript 路由",
            }))]

        # ④ 分支 B：仅 minute_token（妙记兜底）
        m_args = ["minutes", "+detail", "--as", "user",
                  "--minute-tokens", minute_token, "--summary"]
        if with_keywords:
            m_args.append("--keyword")
        try:
            mm = _run_lark(m_args)
        except ValueError as e:
            if _looks_like_permission_denied(str(e)):
                return [TextContent(type="text", text=str(_permission_block(
                    resource_type="minutes", title=vmeta.get("topic", ""),
                    url=(vmeta.get("app_link") or ""),
                    minute_token=minute_token)))]
            raise
        return [TextContent(type="text", text=str({
            "status": "ok",
            "source": "minutes",
            "event_id": event_id,
            "meeting_id": meeting_id,
            "topic": vmeta.get("topic", ""),
            "content": mm.get("data") or mm,
        }))]
    except ValueError as e:
        return [TextContent(type="text", text=f"纪要拉取失败: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"纪要拉取失败: {e}")]


# ══════════════════════════════════════════════════════════
# S5 增补：文档/多维表格拉取（禅道故事草案素材）
# ══════════════════════════════════════════════════════════

_DOC_FETCH_TIMEOUT = 90  # docs +fetch 大文档放宽


def _extract_content(payload: dict, fallback_keys=("content", "markdown", "data")) -> str:
    """从 lark-cli 响应中提取正文（兼容多种返回形态）。"""
    for key in fallback_keys:
        val = payload.get(key)
        if val is not None:
            # docs +fetch 的 data.document.content 是真正正文，去掉包裹层
            if isinstance(val, dict):
                inner = val.get("document") or {}
                if isinstance(inner, dict) and inner.get("content") is not None:
                    return str(inner["content"])
            return str(val)
    return str(payload)


async def _handle_doc_read(arguments: dict) -> list[TextContent]:
    """飞书云文档正文拉取（docs +fetch 纯读）。"""
    doc = str(arguments.get("doc", "")).strip()
    if not doc:
        return [TextContent(type="text",
                            text=str({"ok": False, "error": "doc 必填（URL 或 token）"}))]
    try:
        payload = _run_lark(["docs", "+fetch", "--as", "user", "--doc", doc,
                             "--doc-format", "markdown"],
                            timeout=_DOC_FETCH_TIMEOUT)
    except ValueError as e:
        if _looks_like_permission_denied(str(e)):
            return [TextContent(type="text", text=str(_permission_block(
                resource_type="docx", url=doc)))]
        return [TextContent(type="text",
                            text=str({"ok": False, "error": str(e)}))]
    content = _extract_content(payload)
    max_chars = int(arguments.get("max_chars") or 8000)
    truncated = len(content) > max_chars
    return [TextContent(type="text", text=str({
        "ok": True,
        "doc": doc,
        "truncated": truncated,
        "content": content[:max_chars],
    }))]


async def _handle_link_read(arguments: dict) -> list[TextContent]:
    """飞书链接统一解析入口：按 URL 路径自动路由到对应 lark-cli 命令（纯读）。

    支持：
    - /docx/ /wiki/  → docs +fetch（云文档正文）
    - /minutes/      → minutes +detail（妙记摘要+关键词）
    - /base/         → base +url-resolve → +record-list（多维表格记录）
    """
    url = str(arguments.get("url", "")).strip()
    if not url:
        return [TextContent(type="text", text=str({
            "ok": False, "error": "url 必填（/docx/ /wiki/ /minutes/ /base/ 链接）"}))]
    path = url.split("?")[0].split("#")[0].rstrip("/")
    try:
        # ① 妙记链接：路径末段即 minute_token
        if "/minutes/" in path:
            token = path.rsplit("/", 1)[-1]
            if not token:
                raise ValueError("无法从链接提取 minute_token")
            try:
                mm = _run_lark(["minutes", "+detail", "--as", "user",
                                "--minute-tokens", token, "--summary", "--keyword"])
            except ValueError as e:
                if _looks_like_permission_denied(str(e)):
                    return [TextContent(type="text", text=str(_permission_block(
                        resource_type="minutes", url=url, minute_token=token)))]
                raise
            return [TextContent(type="text", text=str({
                "ok": True, "type": "minutes", "url": url,
                "minute_token": token, "content": _extract_content(mm),
            }))]
        # ② 云文档链接：URL 原样传给 docs +fetch（lark-cli 接受 URL 或 token）
        if "/docx/" in path or "/wiki/" in path:
            try:
                payload = _run_lark(["docs", "+fetch", "--as", "user",
                                     "--doc", url, "--doc-format", "markdown"],
                                    timeout=_DOC_FETCH_TIMEOUT)
            except ValueError as e:
                if _looks_like_permission_denied(str(e)):
                    return [TextContent(type="text", text=str(_permission_block(
                        resource_type="docx", url=url)))]
                raise
            content = _extract_content(payload)
            max_chars = int(arguments.get("max_chars") or 8000)
            return [TextContent(type="text", text=str({
                "ok": True, "type": "docx" if "/docx/" in path else "wiki",
                "url": url, "truncated": len(content) > max_chars,
                "content": content[:max_chars],
            }))]
        # ③ 多维表格链接：url-resolve 取坐标后 record-list
        if "/base/" in path:
            try:
                resolved = _run_lark(["base", "+url-resolve", "--url", url,
                                      "--as", "user"])
            except ValueError as e:
                if _looks_like_permission_denied(str(e)):
                    return [TextContent(type="text", text=str(_permission_block(
                        resource_type="base", url=url)))]
                raise
            data = resolved.get("data") or resolved
            base_token = (data.get("base_token") or "").strip()
            if not base_token:
                return [TextContent(type="text", text=str({
                    "ok": False, "type": "base", "url": url,
                    "error": "url-resolve 未返回 base_token（请确认是 /base/ 链接）",
                    "resolved": data,
                }))]
            rec_args = ["base", "+record-list", "--base-token", base_token,
                        "--limit", str(int(arguments.get("limit") or 50))]
            table_id = (data.get("table_id") or "").strip()
            if table_id:
                rec_args += ["--table-id", table_id]
            payload = _run_lark(rec_args, timeout=_DOC_FETCH_TIMEOUT)
            records = payload.get("records") or ((payload.get("data") or {})
                                                  .get("records") or [])
            return [TextContent(type="text", text=str({
                "ok": True, "type": "base", "url": url,
                "base_token": base_token, "table_id": table_id,
                "record_count": len(records) if isinstance(records, list) else -1,
                "records": records,
            }))]
        return [TextContent(type="text", text=str({
            "ok": False,
            "error": "无法识别链接类型，仅支持 /docx/ /wiki/ /minutes/ /base/ 链接",
            "url": url,
        }))]
    except ValueError as e:
        return [TextContent(type="text", text=str({"ok": False, "error": str(e)}))]


async def _handle_base_query(arguments: dict) -> list[TextContent]:
    """飞书多维表格记录查询（+url-resolve → +record-list 纯读）。"""
    url = str(arguments.get("url", "")).strip()
    if not url:
        return [TextContent(type="text",
                            text=str({"ok": False, "error": "url 必填（/base/ 分享链接）"}))]
    try:
        # ① URL → base_token/table_id
        resolved = _run_lark(["base", "+url-resolve", "--url", url,
                              "--as", "user"])
        data = resolved.get("data") or resolved
        base_token = (data.get("base_token") or "").strip()
        table_id = str(arguments.get("table_id", "")).strip() or \
            str((data.get("table_id") or "")).strip()
        if not base_token:
            return [TextContent(type="text", text=str({
                "ok": False,
                "error": "url-resolve 未返回 base_token（请确认是 /base/ 链接）",
                "resolved": data,
            }))]
        # ② 记录查询
        rec_args = ["base", "+record-list", "--base-token", base_token,
                    "--limit", str(int(arguments.get("limit") or 50))]
        if table_id:
            rec_args += ["--table-id", table_id]
        payload = _run_lark(rec_args, timeout=_DOC_FETCH_TIMEOUT)
        records = payload.get("records") or ((payload.get("data") or {})
                                              .get("records") or [])
        return [TextContent(type="text", text=str({
            "ok": True,
            "base_token": base_token,
            "table_id": table_id,
            "record_count": len(records) if isinstance(records, list) else -1,
            "records": records,
        }))]
    except ValueError as e:
        if _looks_like_permission_denied(str(e)):
            return [TextContent(type="text", text=str(_permission_block(
                resource_type="base", url=url)))]
        return [TextContent(type="text",
                            text=str({"ok": False, "error": str(e)}))]
