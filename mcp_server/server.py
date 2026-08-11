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
    compliance,
    specflow_interview,
    specflow_ledger,
    feishu_fetch,
    specflow_pack,
    specflow_refs,
)

# ══════════════════════════════════════════════════════════
# 工具注册（T-602：单一注册函数，runtime import 复用防双写漂移）
# ══════════════════════════════════════════════════════════

def build_tool_modules(include_info_pack: bool = False) -> list:
    """工具模块单一注册函数（B1 修复）。

    Args:
        include_info_pack: runtime（workbench Agent）需要 info_pack（延迟导入避免
            循环依赖）；stdio server 刻意排除——收窄对外工具面（刻意设计，非漂移，
            见总控 §2.4 刻意保留清单）。
    """
    mods = [
        spec_reader,
        scenario_tools,
        registry_query,
        draft_writer,
        validator,
        attribution,
        audit,
        meta,
        compliance,
        specflow_interview,
        specflow_ledger,
        feishu_fetch,
        specflow_pack,
        specflow_refs,
    ]
    if include_info_pack:
        try:
            from mcp_server.tools import info_pack as _info_pack_mod
            mods.append(_info_pack_mod)
        except ImportError:
            pass
    return mods


TOOL_MODULES = build_tool_modules()

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
