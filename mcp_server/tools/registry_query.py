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
        # 从 format_spec 的规范文档中提取 oracle 列表
        oracles = [
            {"name": "profile_matches_db", "desc": "basicInfo ↔ tdm_emp_employee"},
            {"name": "snapshot_frozen", "desc": "状态型字段 ↔ 快照 JSON 严格比对"},
            {"name": "result_time_filtered", "desc": "切片结果时点过滤校验"},
            {"name": "dhr_fallback_matches", "desc": "DHR 降级 basicInfo ↔ dhr_employee"},
            {"name": "permission_filtered", "desc": "corpCode 三维权限过滤"},
            {"name": "vm_filtered", "desc": "verticalManager 维度过滤"},
            {"name": "inv_context_injected", "desc": "inv* 上下文注入"},
            {"name": "trend_sorted_desc", "desc": "trend 接口按 inventoryDate 降序"},
        ]
        return [TextContent(type="text", text=json.dumps(oracles, ensure_ascii=False, indent=2))]

    elif qtype == "step":
        steps = [
            {"type": "call", "format": "{as?, method, path, params?, headers?, json?, save, timeout?}", "produces": "save.status, save.json, save.headers"},
            {"type": "db_query", "format": "{sql, save, note?}", "produces": "查询结果行数组"},
            {"type": "poll", "format": "{call, until, interval_ms?, timeout_ms?, on_timeout?, save}", "produces": "末轮响应"},
            {"type": "python", "format": "{script 或 file, save?}", "produces": "output 变量 / ns 直写"},
            {"type": "tool", "format": "{use, with?, save?}", "produces": "由工具声明决定"},
        ]
        return [TextContent(type="text", text=json.dumps(steps, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"错误：未知查询类型: {qtype}")]
