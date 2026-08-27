"""registry_query — 查询引擎注册表（tool/oracle/step/env）。

工具：
  query_registry: 查询 tool 目录 / oracle 列表 / step 类型 / env 环境配置（脱敏）
"""

import json
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from sg_core.format_spec import get_tool_catalog  # noqa: E402
from mcp_server.tools.live_registry import (  # noqa: E402
    list_oracles,
    list_step_types,
    load_env_view,
)

TOOLS = [
    Tool(
        name="query_registry",
        description=(
            "查询 SpecGuard 引擎注册表：tool 目录（可用工具及其参数）、oracle 列表（DB 校对断言器）、"
            "step 类型、env 环境配置（当前生效的键与非敏感值，凭据已打码）。"
            "判断 service base / 资源码等 env 键是否已配置时必须用 type=env 实时查询——"
            "历史试跑报告只反映报告时刻的状态，不能作为当前配置缺失的证据"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["tool", "oracle", "step", "env"],
                    "description": "查询类型：tool（工具目录）/ oracle（断言器列表）/ step（步骤类型）/ env（环境配置键清单，密码与账号已打码）"
                },
                "system": {
                    "type": "string",
                    "description": "系统适配包名（可选，默认按当前工作区解析，通常无需传）"
                },
                "env": {
                    "type": "string",
                    "description": "环境名（可选，仅 type=env 生效，默认 sit）"
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

    elif qtype == "env":
        # env 配置对 agent 的脱敏只读窗口——与运行时同源（engine.bootstrap.load_system_env）
        view = load_env_view(
            str(arguments.get("system", "") or ""),
            str(arguments.get("env", "") or ""),
        )
        if view is None:
            return [TextContent(type="text", text=(
                "错误：环境配置加载失败或为空。"
                "请确认 systems/{system}/config/env.{env}.yaml 存在且非空"
                "（可尝试显式传 system/env 参数）"
            ))]
        return [TextContent(type="text", text=json.dumps(view, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"错误：未知查询类型: {qtype}")]


# T-982：工具元数据声明（side_effect/domain/rbac 派生源，见 tool_meta）
from mcp_server.tools.tool_meta import declare, SIDE_DRAFT  # noqa: E402

declare("query_registry", domain="spec")
