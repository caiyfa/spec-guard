"""fabrication — 测试数据制造工具（M08 §5.2，T-062）。

工具：
  fabrication.fabricate_data: 数据制造编排（复用优先 + data_contract 骨架 + 数据校验器）
"""

import json
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

TOOLS = [
    Tool(
        name="fabricate_data",
        description="测试数据制造编排：按缺口 FR 生成 IS-PREP 数据准备草稿。"
                    "复用优先（既有 IS-PREP 场景 covers 命中时建议复用不新造）；"
                    "产物含 data_contract 声明块并过数据校验器（实例完整性/工号池/"
                    "隔离级别/版本仲裁），一律草稿态走三闸，promote 必须三闸全过。"
                    "只消费 systems/{system}/ 适配包资产，引擎零改动。",
        inputSchema={
            "type": "object",
            "properties": {
                "frs": {"type": "array", "items": {"type": "string"},
                        "description": "目标 FR 锚点清单（如 [FR-012]）"},
                "source_delta": {"type": "string",
                                 "description": "来源 delta 代号（挂链，如 extend-void-scope）"},
            },
            "required": ["frs"],
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "fabricate_data":
        return _handle_fabricate(arguments)
    return []


def _handle_fabricate(arguments: dict) -> list[TextContent]:
    frs = arguments.get("frs") or []
    source_delta = str(arguments.get("source_delta", "") or "")
    if not isinstance(frs, list) or not frs:
        return [TextContent(type="text", text="错误：frs 必须为非空数组")]
    try:
        from sg_core import data_fabrication
        result = data_fabrication.fabricate(frs=frs, source_delta=source_delta)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error": f"数据制造失败: {e}"}, ensure_ascii=False, indent=2))]
