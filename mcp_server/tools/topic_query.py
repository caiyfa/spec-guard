"""topic_query — 飞书话题查询工具（T-1011，meta 域常驻合并工具）。

话题库与群聊快照均为工作区公共资产（T-949 共享材料区），本工具是纯读面：
  topic_list:     时效分级话题清单（近 3 天全量非闲聊 + 近 7 天 high）
  topic_search:   关键词搜索（标题/摘要/keywords，不限时效）
  topic_read:     单卡全文（含 source 原文定位与 messages 取原文指引）
  topic_messages: 原文口子——回放话题覆盖的群聊消息段（JSONL 事实源）

domain=meta：resolve_tools 对 meta 域无条件入白名单（与 todo_write/gate_dock_status
同槽），全 purpose 会话常驻可见，不挤 ≤15 名额；纯读 side_effect 自动 product 可见。
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.types import TextContent, Tool

_TOOL_DECLS = [
    Tool(
        name="topic_list",
        description=(
            "飞书话题清单（工作区群聊近期讨论摘要，纯读）。默认时效分级：近 3 天"
            "全部非闲聊话题 + 近 7 天 high 优先级；days>7 时放宽为全部天数内"
            "非闲聊话题。每行：id | 日期 | 优先级 | 状态 | 标题 | 结论摘要。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer",
                         "description": "回看天数（默认 7=分级口径；>7 查更旧）"},
                "status": {"type": "string",
                           "description": "可选：draft/confirmed/rejected 精确过滤"
                                          "（缺省隐藏 rejected）"},
                "category": {"type": "string",
                             "description": "可选：requirement/test/solution/routine/chat"
                                            "（缺省隐藏 chat 闲聊）"},
                "priority": {"type": "string",
                             "description": "可选：high/normal/low"},
                "keyword": {"type": "string",
                            "description": "可选：标题/摘要/keywords 子串过滤"},
            },
            "required": [],
        },
    ),
    Tool(
        name="topic_search",
        description=(
            "飞书话题关键词搜索（纯读，不限时效）：标题/摘要/keywords 子串命中，"
            "按相关度排序。找「群里以前有没有讨论过某事」用这个。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "cap": {"type": "integer", "description": "返回上限（默认 20）"},
            },
            "required": ["keyword"],
        },
    ),
    Tool(
        name="topic_read",
        description=(
            "读单个飞书话题卡全文（纯读）：标题/结论摘要/keywords/分类/优先级/"
            "时间窗/参与人数/状态，以及原文定位（source）。要回看群聊原文时，"
            "再用 topic(action=messages, id=同 id) 取消息段。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "话题 id（tp- 前缀）"},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="topic_messages",
        description=(
            "回放话题覆盖的群聊原文消息段（纯读；共享材料区 JSONL 事实源，"
            "按话题 message_ids 过滤；无 id 锚点的存量卡回退当日快照全文截取）。"
            "长段用 offset 分页。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "话题 id（tp- 前缀）"},
                "offset": {"type": "integer",
                           "description": "字符偏移（默认 0；超出截断时翻页用）"},
            },
            "required": ["id"],
        },
    ),
]

_MSG_CAP = 4000        # messages 单次返回字符上限
_LIST_CAP = 100        # list 行数上限
_SEARCH_CAP = 20


def _root() -> Path | None:
    # 必须 force_shared（T-1011 验收打回根因修复）：specflow_dir 空 emp 会回退
    # 请求上下文工号，Web 登录态下恒解析私有区，共享话题库永不可达
    from specstd.workspace import specflow_dir
    try:
        return specflow_dir("", force_shared=True)
    except Exception:
        return None


def _emit(payload) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _find_card(cards: list[dict], topic_id: str) -> dict | None:
    return next((c for c in cards if str(c.get("id")) == topic_id), None)


def _chat_name(root: Path, chat_sha8: str, day: str) -> str:
    """群名快照：chats md 首行标题（watch 配置在私有区，共享读面不碰）。"""
    md = root / "feishu_pool" / "chats" / chat_sha8 / f"{day}.md"
    if md.is_file():
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("# ").strip()
            if line:
                break
    return ""


def _action_list(root: Path, args: dict) -> list[TextContent]:
    from specflow.feishu_pool import topic_digest as td
    days = int(args.get("days") or 7)
    cards = td.load_topic_cards(root)
    if days <= td.HIGH_PRIORITY_DAYS:
        picked = td.select_digest_cards(cards)
    else:
        picked = [c for c in cards
                  if c.get("status") != "rejected" and c.get("category") != "chat"]
        picked = td.select_digest_cards(  # 同序：仅放宽时效门槛
            list(picked), recent_days=days, high_days=days)
    status = str(args.get("status") or "")
    category = str(args.get("category") or "")
    priority = str(args.get("priority") or "")
    keyword = str(args.get("keyword") or "").lower()
    out = []
    for c in picked:
        if status and c.get("status") != status:
            continue
        if category and c.get("category") != category:
            continue
        if priority and c.get("priority") != priority:
            continue
        if keyword:
            hay = " ".join([str(c.get("title") or ""), str(c.get("summary") or ""),
                            " ".join(str(k) for k in (c.get("keywords") or []))]).lower()
            if keyword not in hay:
                continue
        out.append(c)
    lines = [td.digest_line(c) for c in out[:_LIST_CAP]]
    return _emit({"ok": True, "count": len(out), "truncated": len(out) > _LIST_CAP,
                  "topics": lines})


def _action_search(root: Path, args: dict) -> list[TextContent]:
    from specflow.feishu_pool import topic_digest as td
    keyword = str(args.get("keyword") or "").strip().lower()
    if not keyword:
        return _emit({"ok": False, "error": "keyword 不能为空"})
    cap = int(args.get("cap") or _SEARCH_CAP)
    scored: list[tuple[int, dict]] = []
    for c in td.load_topic_cards(root):
        if c.get("status") == "rejected":
            continue
        score = sum(2 for kw in (c.get("keywords") or [])
                    if kw and keyword in str(kw).lower())
        if keyword in str(c.get("title") or "").lower():
            score += 2
        if keyword in str(c.get("summary") or "").lower():
            score += 1
        if score:
            scored.append((score, c))
    scored.sort(key=lambda t: -t[0])
    return _emit({"ok": True, "count": min(len(scored), cap),
                  "topics": [td.digest_line(c) for _, c in scored[:cap]]})


def _action_read(root: Path, args: dict) -> list[TextContent]:
    from specflow.feishu_pool import topic_digest as td
    topic_id = str(args.get("id") or "")
    card = _find_card(td.load_topic_cards(root), topic_id)
    if not card:
        return _emit({"ok": False,
                      "error": f"话题不存在: {topic_id}（用 topic(action=list) 看可用 id）"})
    day = str((card.get("source") or "").rsplit("/", 1)[-1]).replace(".md", "")
    return _emit({"ok": True, "topic": card,
                  "chat_name": _chat_name(root, str(card.get("chat_sha8") or ""), day),
                  "origin_hint": "用 topic(action=messages, id=同 id) 回放原文消息段"})


def _action_messages(root: Path, args: dict) -> list[TextContent]:
    from specflow.feishu_pool import chat_store
    from specflow.feishu_pool import topic_digest as td
    topic_id = str(args.get("id") or "")
    offset = max(0, int(args.get("offset") or 0))
    card = _find_card(td.load_topic_cards(root), topic_id)
    if not card:
        return _emit({"ok": False, "error": f"话题不存在: {topic_id}"})
    sha8 = str(card.get("chat_sha8") or "")
    day = str((card.get("source") or "").rsplit("/", 1)[-1]).replace(".md", "")
    chats_root = root / "feishu_pool" / "chats" / sha8
    ids = {str(m) for m in (card.get("message_ids") or [])}
    lines: list[str] = []
    source = ""
    jsonl = chats_root / f"{day}.jsonl"
    if jsonl.is_file():
        rows = chat_store.load_chat_jsonl(jsonl)
        if ids:
            rows = [r for r in rows if str(r.get("message_id")) in ids]
        for r in rows:
            hhmm = str(r.get("ts") or "")[11:16] or "??:??"
            sender = str(r.get("sender_name") or r.get("sender_id") or "?")
            body = str(r.get("content") or "")
            if str(r.get("msg_type") or "") == "image":
                body = body or "[图片]"
            lines.append(f"[{hhmm}] {sender}: {body}")
        source = f"chats/{sha8}/{day}.jsonl"
    else:
        md = chats_root / f"{day}.md"
        if md.is_file():
            lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
            source = f"chats/{sha8}/{day}.md"
    if not lines:
        return _emit({"ok": False,
                      "error": f"原文快照缺失: chats/{sha8}/{day}（可能尚未同步）"})
    text = "\n".join(lines)
    chunk = text[offset:offset + _MSG_CAP]
    return _emit({"ok": True, "source": source, "offset": offset,
                  "total_chars": len(text),
                  "has_more": offset + _MSG_CAP < len(text),
                  "chat_name": _chat_name(root, sha8, day),
                  "messages": chunk})


async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    root = _root()
    if root is None:
        return _emit({"ok": False, "error": "无激活工作区（话题库不可达）"})
    args = dict(arguments or {})
    if name == "topic_list":
        return _action_list(root, args)
    if name == "topic_search":
        return _action_search(root, args)
    if name == "topic_read":
        return _action_read(root, args)
    if name == "topic_messages":
        return _action_messages(root, args)
    raise ValueError(f"未知工具: {name}")


# T-982：action 参数化合并（元数据单一事实源；domain=meta 全用途常驻）
from mcp_server.tools.tool_meta import ActionMeta, consolidate  # noqa: E402

TOOLS, handle = consolidate(
    "topic",
    "飞书话题（工作区群聊讨论摘要，纯读）：list 时效分级清单、search 关键词搜索、"
    "read 单卡全文、messages 回放话题原文消息段。工作区群里聊过什么、结论是什么，"
    "先查这里，不要让用户重复。",
    actions={
        "list": ActionMeta(legacy="topic_list"),
        "search": ActionMeta(legacy="topic_search"),
        "read": ActionMeta(legacy="topic_read"),
        "messages": ActionMeta(legacy="topic_messages"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="meta",
)
