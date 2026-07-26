"""registry_query — 查询引擎注册表（tool/oracle/step）。

工具：
  query_registry: 查询 tool 目录 / oracle 列表 / step 类型
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.format_spec import get_tool_catalog  # noqa: E402
from mcp_server.tools.live_registry import list_oracles, list_step_types  # noqa: E402

TOOLS = [
    Tool(
        name="query_registry",
        description="查询 SpecGuard 引擎注册表：tool 目录（可用工具及其参数）、oracle 列表（DB 校对断言器）、step 类型",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["tool", "oracle", "step"],
                    "description": "查询类型：tool（工具目录）/ oracle（断言器列表）/ step（步骤类型）"
                }
            },
            "required": ["type"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_registry":
        return _handle_query_registry(arguments)
    return []


def _handle_query_registry(arguments: dict) -> list[TextContent]:
    qtype = arguments.get("type", "tool")

    if qtype == "tool":
        catalog = get_tool_catalog()
        return [TextContent(type="text", text=json.dumps(catalog, ensure_ascii=False, indent=2))]

    elif qtype == "oracle":
        # V8 修复：从活注册表动态读取（D3 单一事实源），不再硬编码
        oracles = list_oracles()
        if not oracles:
            return [TextContent(type="text", text="错误：活注册表构建失败，无法查询 oracle 清单")]
        return [TextContent(type="text", text=json.dumps(oracles, ensure_ascii=False, indent=2))]

    elif qtype == "step":
        # V8 修复：步骤类型同样从活注册表读取（内置原语 + 系统适配包步骤）
        steps = list_step_types()
        if not steps:
            return [TextContent(type="text", text="错误：活注册表构建失败，无法查询 step 清单")]
        return [TextContent(type="text", text=json.dumps(steps, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"错误：未知查询类型: {qtype}")]
