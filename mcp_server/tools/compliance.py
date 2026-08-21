"""compliance — 全库格式合规缺口扫描（T-313：Agent 更新已有场景的依据）。

工具：scan_compliance
  对场景库每个场景比对「requires 声明」与「flow/verify 静态提取的依赖」，
  输出 2.3.0 格式迁移缺口（账号/env 键/跨场景引用未声明、冗余声明、T8 违规）——
  Agent 对话中据此逐个更新存量场景（read_scenario → 改写补 requires → write_draft
  → validate → promote_draft(replace=true)）。
"""

import json
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

TOOLS = [
    Tool(
        name="scan_compliance",
        description="全库格式合规缺口扫描（T-313）：比对每个场景 requires 声明与 flow/verify "
                    "静态提取的依赖（账号别名 / {{env.*}} 键 / {{上游ID.*}} 引用），输出 2.3.0 "
                    "格式迁移缺口清单（missing_accounts/missing_env/missing_upstream 未声明项、"
                    "extra_requires 冗余声明、t8_violations 上游引用不在 depends_on）。"
                    "格式要求升级后用它查哪些存量场景需要更新。纯读，无副作用。",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多返回的缺口条数（0 = 全部）", "default": 0}
            },
            "required": []
        }
    ),
]


def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "scan_compliance":
        return _handle_scan_compliance(arguments)
    return []


def _handle_scan_compliance(arguments: dict) -> list[TextContent]:
    try:
        from workbench.backend.services import preflight
        r = preflight.scan_compliance()
        limit = int(arguments.get("limit") or 0)
        if limit > 0:
            r["gaps"] = r["gaps"][:limit]
        return [TextContent(type="text", text=json.dumps(r, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error": f"{type(e).__name__}: {e}",
        }, ensure_ascii=False, indent=2))]
