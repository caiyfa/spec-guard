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

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

from mcp.types import Tool, TextContent

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

TOOLS = [
    feishu_calendar_agenda_tool,
    feishu_meeting_notes_tool,
]


# ══════════════════════════════════════════════════════════
# lark-cli 子进程封装
# ══════════════════════════════════════════════════════════

_LARK_TIMEOUT = 90  # 秒（会议链路多跳，放宽）

# 无权限错误关键词（T-026 结构化引导；lark-cli 无权限返回友好错误而非静默降级）
_PERMISSION_HINTS = (
    "无权限", "权限不足", "没有权限", "no permission", "forbidden",
    "permission denied", "denied", "无权", "申请权限",
)


def _lark_command() -> list[str]:
    """返回 lark-cli 可执行命令前缀（Windows 需经 cmd /c 执行 .cmd 包装）。"""
    if sys.platform == "win32":
        full = shutil.which("lark-cli") or "lark-cli"
        return ["cmd", "/c", full]
    return ["lark-cli"]


def _run_lark(args: list[str], timeout: int = _LARK_TIMEOUT) -> dict:
    """执行 lark-cli 并解析 JSON 输出。

    Returns:
        解析后的响应 dict

    Raises:
        ValueError: 认证未就绪/网络失败/输出非 JSON/命令超时（确定性错误）
    """
    cmd = _lark_command() + args + ["--format", "json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", check=False)
    except subprocess.TimeoutExpired:
        raise ValueError(f"lark-cli 调用超时（>{timeout}s）: {' '.join(args[:3])}")
    except OSError as e:
        raise ValueError(f"lark-cli 不可用: {e}（请确认已安装 npm 全局 lark-cli）")

    text = (proc.stdout or "") + (proc.stderr or "")
    # 认证未就绪（auth status ready 是调用前置）
    if "not logged in" in text or "登录" in text and "请先" in text:
        raise ValueError("飞书认证未就绪：请先执行 lark-cli auth login 完成 user 身份授权")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"lark-cli 输出非 JSON（rc={proc.returncode}）: {text[:300]}")
    if not payload.get("ok"):
        raise ValueError(f"lark-cli 调用失败: {text[:300]}")
    return payload


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
