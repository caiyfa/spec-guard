"""SpecGuard MCP Server — stdio 模式入口。

启动方式：
    python -m mcp_server.server          # stdio 模式
    python mcp_server/server.py           # 直接运行

Qoder 挂载后 list_tools 可见全部 10 个工具。
"""

import asyncio
import sys
from pathlib import Path

# 确保仓库根在 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import Tool, TextContent  # noqa: E402

# 导入所有工具模块
from mcp_server.tools import (  # noqa: E402
    spec_reader,
    scenario_tools,
    registry_query,
    draft_writer,
    validator,
    attribution,
    audit,
    meta,
)

# ══════════════════════════════════════════════════════════
# 工具注册
# ══════════════════════════════════════════════════════════

TOOL_MODULES = [
    spec_reader,
    scenario_tools,
    registry_query,
    draft_writer,
    validator,
    attribution,
    audit,
    meta,
]

ALL_TOOLS: list[Tool] = []
for mod in TOOL_MODULES:
    ALL_TOOLS.extend(mod.TOOLS)

# 工具名 → 模块映射（用于快速查找）
TOOL_NAME_TO_MODULE = {}
for mod in TOOL_MODULES:
    for tool in mod.TOOLS:
        TOOL_NAME_TO_MODULE[tool.name] = mod


# ══════════════════════════════════════════════════════════
# MCP Server
# ══════════════════════════════════════════════════════════

server = Server("specguard")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """返回全部可用工具。"""
    return ALL_TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """分发工具调用到对应模块。"""
    mod = TOOL_NAME_TO_MODULE.get(name)
    if mod:
        return await mod.handle(name, arguments)
    return [TextContent(type="text", text=f"未知工具: {name}")]


# ══════════════════════════════════════════════════════════
# 启动入口
# ══════════════════════════════════════════════════════════

async def main():
    """stdio 模式启动。"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
