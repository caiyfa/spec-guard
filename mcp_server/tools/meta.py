"""meta — Agent 元控制工具（H-4）。

工具：
  todo_write: 更新任务待办列表（H-4）
  switch_mode: （K-023 已废弃）模式机制移除，保留壳平滑过渡

注意：这两个工具在 AgentRuntime._execute_tool 中被特殊拦截，
不通过常规 mod.handle 执行。MCP server 独立模式下返回提示信息。
"""

import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))


# Meta 工具名称集合（常驻，不写入 modes/*.md 的 tools 白名单）
META_TOOL_NAMES = frozenset({"switch_mode", "todo_write"})

TOOLS = [
    Tool(
        name="todo_write",
        description="更新任务待办列表。开始新任务、完成任务、阶段转换时调用。"
                    "待办会实时展示给用户，帮助用户了解当前进度。",
        inputSchema={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "完整的待办列表（全量替换，非增量）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "待办唯一标识",
                            },
                            "title": {
                                "type": "string",
                                "description": "待办标题",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done", "blocked"],
                                "description": "待办状态",
                            },
                            "mode": {
                                "type": "string",
                                "description": "（遗留字段，可省略）该待办所属阶段标签",
                            },
                        },
                        "required": ["id", "title", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
    ),
    Tool(
        name="switch_mode",
        description="（已废弃，无任何效果）模式机制已移除，所有工具全程可用。"
                    "请勿调用——直接按任务需要调用对应工具即可。",
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "（忽略）",
                },
                "reason": {
                    "type": "string",
                    "description": "（忽略）",
                },
            },
        },
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    """MCP server 独立模式处理（无 runtime 上下文）。

    Agent 运行时中这些工具被 _execute_tool 拦截，不会走到这里。
    """
    return [TextContent(
        type="text",
        text=f"工具 {name} 仅在 Agent 运行时中可用，MCP server 独立模式不支持。",
    )]
