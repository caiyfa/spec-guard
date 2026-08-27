"""parent — 辅助会话限界读取父会话脉络（T-1032 方案③）。

工具：
  parent: action=summary 读父会话现成脉络摘要 / action=recent 直读最近轮窗。

门卫铁律（与隔离保证矩阵对齐）：
- 仅 kind=aux 且有 parent_session_id 的会话可用；其余（主会话/stdio/无上下文）
  一律 ok:false 诚实拒绝——本工具不收任何会话 ID 参数，读取范围锁死为
  runtime 注入的本链接父会话，杜绝横向越权。
- 纯读零写副作用（side_effect=none；审计走 T-082 常规通道）。

摘要文件由方案②（routers/agent.py 每轮 run 完成后台 refresh_digest）维护；
本工具只读不生成——新鲜度以覆盖度 json 为准并在返回头明示。
"""

import json
from pathlib import Path

from mcp.types import TextContent, Tool

from mcp_server.tools.tool_meta import SIDE_NONE, declare

TOOLS = [
    Tool(
        name="parent",
        description=(
            "读取父会话（主会话）的工作脉络。仅辅助会话可用。\n"
            "action 明细：\n"
            "- summary: 返回主会话的脉络摘要文档（当前主题/关键里程碑/产物清单/"
            "进行中与下一步），附覆盖度说明\n"
            "- recent: 直读主会话最近若干轮对话窗口（最新进展优先，含工具调用要点）"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["summary", "recent"],
                    "description": "要执行的操作",
                },
            },
            "required": ["action"],
        },
    ),
]

declare("parent", domain="aux", side_effect=SIDE_NONE)


def _emit(payload: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _emit_text(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def _load_parent_msgs(scope: dict):
    from agent.session import SessionManager
    sm = SessionManager(Path(scope["sessions_dir"]))
    sid = scope["parent_sid"]
    msgs = sm.load(sid)
    if msgs is None:
        return None, sm, sid
    return msgs, sm, sid


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name != "parent":
        raise ValueError(f"未知工具: {name}")
    action = str((arguments or {}).get("action", "") or "")

    from sg_core import session_digest as sd
    from sg_core.session_context import get_runtime_scope

    scope = get_runtime_scope() or {}
    if not scope or not scope.get("sid"):
        return _emit({"ok": False,
                      "error": "当前无会话上下文（仅工作台辅助会话可用本工具）"})
    if scope.get("kind") != "aux" or not scope.get("parent_sid"):
        return _emit({"ok": False,
                      "error": f"会话 {scope['sid']} 不是辅助会话（kind=aux），无父会话可读"})
    if action not in ("summary", "recent"):
        return _emit({"ok": False, "error": f"未知 action: {action}，可用 summary/recent"})

    msgs, _sm, parent_sid = _load_parent_msgs(scope)
    if msgs is None:
        return _emit({"ok": False, "error": f"父会话 {parent_sid} 不存在或不可读"})

    header = f"[父会话 {parent_sid}] 共 {len(msgs)} 条消息。\n"

    if action == "recent":
        window = sd.render_recent_window(msgs)
        return _emit_text(f"{header}\n{window}")

    md_path, meta_path = sd.paths_for(scope["sessions_dir"], parent_sid)
    coverage = sd.parse_coverage(
        meta_path.read_text(encoding="utf-8") if meta_path.is_file() else None)
    if not md_path.is_file():
        return _emit({"ok": False,
                      "error": ("父会话脉络摘要尚未生成（会在其每轮运行完成后自动生成），"
                                "可先用 action=recent 查看最近轮窗")})
    freshness = sd.digest_staleness_note(coverage, len(msgs))
    body = md_path.read_text(encoding="utf-8")
    # 剥掉内部注释行再交给模型（mode/updatetime 已由 freshness 行表达）
    body_lines = [ln for ln in body.splitlines()
                  if not ln.startswith("<!--") and not ln.startswith("<!-- llm_error")]
    return _emit_text(header + freshness + "\n\n" + "\n".join(body_lines).strip())
