"""info_pack — 基础信息包读取与追加工具（G2-1）。

工具：
  read_info_pack: 读取场景基础信息包的全部文件内容（拼接返回）
  add_to_info_pack: 向基础信息包追加文件
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT / "workbench" / "backend") not in sys.path:
    sys.path.insert(0, str(SG_ROOT / "workbench" / "backend"))

TOOLS = [
    Tool(
        name="read_info_pack",
        description="读取场景基础信息包的全部文件内容。"
                    "每文件带路径标头，内容拼接返回。"
                    "用于 Agent 分析需求文档、生成测试场景。",
        inputSchema={
            "type": "object",
            "properties": {
                "scenario_id": {
                    "type": "string",
                    "description": "场景元数据 ID（如 SG-META-0001）"
                }
            },
            "required": ["scenario_id"]
        }
    ),
    Tool(
        name="add_to_info_pack",
        description="向场景基础信息包追加一个文件。"
                    "Agent 发现信息不足时，用户确认后调用此工具补充文件。",
        inputSchema={
            "type": "object",
            "properties": {
                "scenario_id": {
                    "type": "string",
                    "description": "场景元数据 ID"
                },
                "path": {
                    "type": "string",
                    "description": "要追加的文件路径（相对工作区根）"
                }
            },
            "required": ["scenario_id", "path"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "read_info_pack":
        return _handle_read_info_pack(arguments)
    elif name == "add_to_info_pack":
        return _handle_add_to_info_pack(arguments)
    return []


def _handle_read_info_pack(arguments: dict) -> list[TextContent]:
    """读取基础信息包全部文件内容。"""
    scenario_id = arguments.get("scenario_id", "")
    if not scenario_id:
        return [TextContent(type="text", text="错误：缺少 scenario_id 参数")]

    # 从 DB 获取文件列表
    try:
        from services import scenario_meta
        meta = scenario_meta.get_meta(scenario_id)
    except Exception as e:
        return [TextContent(type="text", text=f"错误：无法访问场景元数据: {e}")]

    if not meta:
        return [TextContent(type="text", text=f"错误：场景不存在: {scenario_id}")]

    files = meta.get("info_pack", [])
    if not files:
        return [TextContent(type="text", text=f"基础信息包为空（场景 {scenario_id}）。请先在向导中添加文件。")]

    # 逐个读取文件
    from specstd.workspace import safe_resolve
    parts = []
    for file_path in files:
        resolved = safe_resolve(file_path)
        if resolved is None:
            parts.append(f"--- {file_path} ---\n[OUT_OF_SCOPE: 路径越界或工作区未激活]\n")
            continue
        if not resolved.is_file():
            parts.append(f"--- {file_path} ---\n[文件不存在]\n")
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
            parts.append(f"--- {file_path} ---\n{content}\n")
        except Exception as e:
            parts.append(f"--- {file_path} ---\n[读取失败: {e}]\n")

    return [TextContent(type="text", text="\n".join(parts))]


def _handle_add_to_info_pack(arguments: dict) -> list[TextContent]:
    """向基础信息包追加文件。"""
    scenario_id = arguments.get("scenario_id", "")
    file_path = arguments.get("path", "")
    if not scenario_id or not file_path:
        return [TextContent(type="text", text="错误：缺少 scenario_id 或 path 参数")]

    # 验证文件路径安全
    from specstd.workspace import safe_resolve
    resolved = safe_resolve(file_path)
    if resolved is None:
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界或工作区未激活: {file_path}")]
    if not resolved.is_file():
        return [TextContent(type="text", text=f"错误：文件不存在: {file_path}")]

    # 更新 DB
    try:
        from services import scenario_meta
        updated = scenario_meta.add_to_info_pack(scenario_id, file_path)
    except Exception as e:
        return [TextContent(type="text", text=f"错误：无法更新基础信息包: {e}")]

    if not updated:
        return [TextContent(type="text", text=f"错误：场景不存在: {scenario_id}")]

    return [TextContent(type="text", text=json.dumps({
        "ok": True,
        "scenario_id": scenario_id,
        "added_file": file_path,
        "info_pack": updated.get("info_pack", []),
    }, ensure_ascii=False, indent=2))]
