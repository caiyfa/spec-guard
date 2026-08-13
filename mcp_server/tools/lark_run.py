"""lark_run.py — T-702：飞书 CLI 通用执行器。

MCP 工具：
  lark_execute: 透传 lark-cli 命令（白名单校验 + 写操作保护 + 审计）

安全设计：
- 命令白名单：仅允许预定义子命令域
- 禁止 shell 拼接：参数以 list 传 subprocess.run，无 shell=True
- 写操作自动追加 --yes 且需 confirm_write=true
- 审计落库：通过 audit_store.record_call

与 feishu_fetch 的关系：
  feishu_fetch 是高阶语义化封装（已知返回格式 + 面试场景语义），
  lark_execute 是低阶通用通道（能力探索 + feishu_fetch 未封装的命令）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from mcp_server.tools.lark_auth import _run_lark  # noqa: E402

# ══════════════════════════════════════════════════════════
# 安全层
# ══════════════════════════════════════════════════════════

# 允许的子命令域白名单
_ALLOWED_COMMANDS = frozenset({
    "calendar", "docs", "base", "minutes", "im", "vc",
    "task", "approval", "drive", "wiki", "sheets", "auth", "note",
})

# 写操作子命令关键词（需 --yes + confirm_write=true）
_HIGH_RISK_WRITE = frozenset({
    "+create", "+update", "+delete", "logout",
    "+add", "+remove", "+set",
})

_LARK_TIMEOUT = 60  # 通用执行器默认 60s
_TOOL_RESULT_MAX_CHARS = 50000  # 与 T-403 统一截断


# ══════════════════════════════════════════════════════════
# MCP 工具定义
# ══════════════════════════════════════════════════════════

lark_execute_tool = Tool(
    name="lark_execute",
    description="飞书 CLI 通用命令执行器。透传 lark-cli 子命令到指定域（calendar/docs/base/"
                "minutes/im/vc/task/approval/drive/wiki/sheets/auth/note）。"
                "写操作（+create/+update/+delete/logout 等）需设置 confirm_write=true"
                "确认后执行。结果自动 JSON 解析，失败返回原始 stdout。",
    inputSchema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "lark-cli 子命令（如 'calendar +agenda', 'docs +fetch'）",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "命令参数列表（每个参数独立元素，禁止 shell 拼接）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 60，可选 10-300）",
            },
            "confirm_write": {
                "type": "boolean",
                "description": "写操作确认（命令含 high-risk-write 子命令时必须为 true）",
            },
        },
        "required": ["command"],
    },
)

TOOLS = [lark_execute_tool]


def _check_write_permission(command: str, confirm_write: bool) -> None:
    """检查写操作权限。"""
    for keyword in _HIGH_RISK_WRITE:
        if keyword in command.split():
            if not confirm_write:
                raise ValueError(
                    f"命令 '{command}' 包含写操作关键词 '{keyword}'，"
                    f"请设置 confirm_write=true 确认后执行")
            return  # 找到匹配即停止
    # 无写操作关键词，不需要确认


async def handle(name: str, arguments: dict) -> list[TextContent]:
    """MCP 工具分发入口。"""
    if name != "lark_execute":
        return [TextContent(type="text", text=json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False))]

    # 获取当前用户 emp_no
    try:
        from services.auth import current_emp_no as _get_emp_no
        emp_no = _get_emp_no()
    except Exception:
        emp_no = os.environ.get("SG_LARK_EMP_NO", "")
    if not emp_no:
        return [TextContent(type="text", text=json.dumps({
            "error": "未获取到当前用户身份",
        }, ensure_ascii=False))]

    command = str(arguments.get("command", "")).strip()
    if not command:
        return [TextContent(type="text", text=json.dumps({"error": "command 必填"}, ensure_ascii=False))]

    # 白名单校验
    cmd_parts = command.split()
    if not cmd_parts or cmd_parts[0] not in _ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(_ALLOWED_COMMANDS))
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "error": f"命令域 '{cmd_parts[0] if cmd_parts else ''}' 不在白名单中",
            "allowed_commands": allowed,
        }, ensure_ascii=False))]

    # 写操作确认
    confirm_write = bool(arguments.get("confirm_write", False))
    try:
        _check_write_permission(command, confirm_write)
    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))]

    # 构造完整 args
    raw_args = arguments.get("args", [])
    if not isinstance(raw_args, list):
        return [TextContent(type="text", text=json.dumps({"error": "args 必须是字符串数组"}, ensure_ascii=False))]
    full_args = command.split() + [str(a) for a in raw_args]

    # auth 域子命令仅支持 --json（不支持 --format json），特判处理
    is_auth_domain = cmd_parts[0] == "auth"
    if is_auth_domain:
        full_args.append("--json")

    # 写操作自动追加 --yes
    has_write_op = any(kw in full_args for kw in _HIGH_RISK_WRITE)
    if has_write_op and "--yes" not in full_args:
        full_args.append("--yes")

    timeout = int(arguments.get("timeout", _LARK_TIMEOUT))
    timeout = max(10, min(timeout, 300))

    try:
        payload = _run_lark(emp_no, full_args, timeout=timeout, json_output=not is_auth_domain)
    except ValueError as e:
        text = str(e)
        if any(h in text.lower() for h in ("无权限", "权限不足", "forbidden", "denied", "无权")):
            return [TextContent(type="text", text=json.dumps({
                "ok": False,
                "status": "permission_denied",
                "hint": "无权限操作此资源，请检查飞书 scope 授权或重新授权",
                "error": text[:500],
            }, ensure_ascii=False))]
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": text[:500]}, ensure_ascii=False))]

    # 结果截断
    result_str = json.dumps(payload, ensure_ascii=False, default=str)
    truncated = len(result_str) > _TOOL_RESULT_MAX_CHARS
    if truncated:
        result_str = result_str[:_TOOL_RESULT_MAX_CHARS]

    result = {
        "ok": True,
        "data": payload.get("data") or payload,
        "truncated": truncated,
    }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]