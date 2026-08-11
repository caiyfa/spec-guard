"""coverage — 覆盖缺口查询工具（M07 §5.2，T-060）。

工具：
  coverage.query_gaps: Agent 侧查询覆盖缺口三态与建议顺序（与 REST 同一服务实现）
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

TOOLS = [
    Tool(
        name="query_coverage_gaps",
        description="查询覆盖缺口三态聚合（🔴 无覆盖 / 🟡 草稿待审 / 🟢 已覆盖）与建议补齐顺序。"
                    "用于生成场景前了解哪些 FR 还是缺口、哪些只有草稿（草稿不计覆盖）、"
                    "建议顺序按 delta 新增 P0 > 修改触及 > 历史缺口确定性排序。"
                    "生成草稿只建议给用户，用户确认后经 write_draft 走三闸。",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string",
                           "description": "可选：只看某模块（如 system-settings/inventory-activity）"},
            },
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_coverage_gaps":
        return _handle_query_gaps(arguments)
    return []


def _handle_query_gaps(arguments: dict) -> list[TextContent]:
    module = str(arguments.get("module", "") or "")
    try:
        from workbench.backend.services import coverage_gaps
        result = coverage_gaps.compute_coverage(module=module)
        result["note"] = ("草稿不计覆盖：🟡 与 🔴 同 FR 可并存；生成草稿请向用户确认后"
                          "经 write_draft 落盘（自动登记三闸），promote 必须三闸全过")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error": f"覆盖聚合失败: {e}"}, ensure_ascii=False, indent=2))]
