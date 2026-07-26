"""scenario_tools — 场景列表 / 读取 / ID 分配。

工具：
  list_scenarios: 列出全部场景
  read_scenario: 读取单个场景 YAML
  next_scenario_id: 获取下一可用场景 ID
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

from services.format_spec import get_next_scenario_id  # noqa: E402

SCENARIOS_ROOT = SG_ROOT / "scenarios"

TOOLS = [
    Tool(
        name="list_scenarios",
        description="列出 SpecGuard 仓库的全部场景（扫描 scenarios/ 目录，返回 ID/标题/标签/模块）",
        inputSchema={"type": "object", "properties": {}}
    ),
    Tool(
        name="read_scenario",
        description="读取单个场景的 YAML 内容（根据场景 ID 查找文件）",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "场景 ID（如 PP-RC-001）"}
            },
            "required": ["id"]
        }
    ),
    Tool(
        name="next_scenario_id",
        description="获取下一可用的场景 ID（扫描已有 ID，返回下一序号）",
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "模块前缀（如 PP, IS, EV）"},
                "type_abbr": {"type": "string", "description": "类型缩写（如 RC, SNAP, PERM）"}
            },
            "required": ["prefix", "type_abbr"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "list_scenarios":
        return _handle_list_scenarios(arguments)
    elif name == "read_scenario":
        return _handle_read_scenario(arguments)
    elif name == "next_scenario_id":
        return _handle_next_scenario_id(arguments)
    return []


def _handle_list_scenarios(arguments: dict) -> list[TextContent]:
    import yaml

    scenarios = []
    for yaml_file in sorted(SCENARIOS_ROOT.rglob("*.yaml")) + sorted(SCENARIOS_ROOT.rglob("*.yml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            continue
        sid = raw.get("id", "")
        if not sid:
            continue
        rel = str(yaml_file.relative_to(SCENARIOS_ROOT)).replace("\\", "/")
        scenarios.append({
            "id": sid,
            "title": raw.get("title", ""),
            "tags": raw.get("tags", []),
            "module": rel.split("/")[0] if "/" in rel else "",
            "path": rel,
        })

    return [TextContent(type="text", text=json.dumps(scenarios, ensure_ascii=False, indent=2))]


def _handle_read_scenario(arguments: dict) -> list[TextContent]:
    import yaml

    sid = arguments.get("id", "")
    if not sid:
        return [TextContent(type="text", text="错误：缺少 id 参数")]

    for yaml_file in SCENARIOS_ROOT.rglob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if raw.get("id") == sid:
                content = yaml_file.read_text(encoding="utf-8")
                return [TextContent(type="text", text=content)]
        except Exception:
            continue

    return [TextContent(type="text", text=f"错误：场景不存在: {sid}")]


def _handle_next_scenario_id(arguments: dict) -> list[TextContent]:
    prefix = arguments.get("prefix", "")
    type_abbr = arguments.get("type_abbr", "")
    if not prefix or not type_abbr:
        return [TextContent(type="text", text="错误：缺少 prefix 或 type_abbr 参数")]

    result = get_next_scenario_id(prefix, type_abbr)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
