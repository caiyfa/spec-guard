"""gate_dock — 对话操作台状态查询工具（GateDock 二期，T-901）。

工具：
  gate_dock_status: 当前会话上下文的待办闸门卡片汇总（纯读；side_effect 默认 none）。

Agent 推卡动线：状态迁移节点（材料解析/评分产出/三闸推进/冻结/建故事）后
调本工具 → 存在待办卡片时，用 ```gate-card 围栏把卡片 JSON 原样嵌入回复
推送给用户（前端渲染为可操作卡片），并附 L1 引导话术。
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT / "workbench" / "backend") not in sys.path:
    sys.path.insert(0, str(SG_ROOT / "workbench" / "backend"))

TOOLS = [
    Tool(
        name="gate_dock_status",
        description=(
            "查询当前会话上下文的待办闸门卡片（对话操作台，纯读零写副作用）。"
            "按会话绑定的需求面试聚合五类待办：议题确认/材料入包/评分确认/"
            "冻结三闸/禅道建故事。存在待办卡片时，用 ```gate-card 围栏把该卡片"
            " JSON 原样嵌入回复推送给用户，并附一句引导（解释闸门意义与下一步）。"
            "卡片 level=L2 的操作（评分/冻结/禅道写）只引导不代办。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "interview_id": {
                    "type": "string",
                    "description": "可选：显式指定面试 ID（缺省按当前会话反查绑定面试）",
                },
            },
            "required": [],
        },
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name != "gate_dock_status":
        raise ValueError(f"未知工具: {name}")

    def _emit(payload: dict) -> list[TextContent]:
        return [TextContent(
            type="text", text=json.dumps(payload, ensure_ascii=False))]

    from specstd.workspace import get_context_workspace
    ws = get_context_workspace() or ""
    if not ws:
        return _emit({"ok": False, "error": "工作区上下文缺失"})

    # _session_id 由 runtime 注入（特权参数，LLM 入参同名键会被覆盖）
    session_id = arguments.get("_session_id") or arguments.get("session_id") or ""
    interview_id = arguments.get("interview_id") or ""

    from workbench.backend.services.specflow import sf_store
    from workbench.backend.services.specflow.gate_dock_service import (
        build_gate_dock)

    iv = None
    if interview_id:
        iv = sf_store.get_interview(interview_id)
        if not iv or iv.get("workspace") != ws:
            return _emit({"ok": False, "error": f"面试不存在: {interview_id}"})
    elif session_id:
        rows = sf_store.list_interviews_db(workspace=ws, session_id=session_id)
        iv = rows[0] if rows else None

    if not iv:
        return _emit({"ok": True, "interview": None, "cards": [],
                      "hint": "当前会话未绑定需求面试，无待办闸门"})

    result = build_gate_dock(ws, iv)
    result["ok"] = True
    return _emit(result)
