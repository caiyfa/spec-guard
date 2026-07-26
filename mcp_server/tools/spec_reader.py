"""spec_reader — 读取当前工作区的 spec 文件。

工具：
  read_spec: 读取单个文件（只读，越界路径拒绝）
  list_spec_files: 列出文件树（含 delta 标记）
"""

import json

from mcp.types import Tool, TextContent

from specstd.workspace import safe_resolve, get_active_workspace

TOOLS = [
    Tool(
        name="read_spec",
        description="读取当前激活工作区的 spec 文件（只读，越界路径拒绝）。"
                    "可读 AGENTS.md、specs/**/*.md、specs/**/*.yaml、changes/**/* 等。",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对工作区根的文件路径（如 AGENTS.md, specs/module1/feature1/spec.md）"
                }
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="list_spec_files",
        description="列出当前激活工作区的 spec 文件树。"
                    "自动标注 changes/ 下的文件为 delta 文件。"
                    "可指定 subdir 过滤（如 specs, changes）。",
        inputSchema={
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": "可选的子目录路径（如 specs, changes）"
                }
            }
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "read_spec":
        return _handle_read_spec(arguments)
    elif name == "list_spec_files":
        return _handle_list_spec_files(arguments)
    return []


def _handle_read_spec(arguments: dict) -> list[TextContent]:
    path = arguments.get("path", "")
    if not path:
        return [TextContent(type="text", text="错误：缺少 path 参数")]

    resolved = safe_resolve(path)
    if resolved is None:
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界或工作区未激活: {path}")]

    if not resolved.is_file():
        return [TextContent(type="text", text=f"错误：文件不存在: {path}")]

    content = resolved.read_text(encoding="utf-8")
    return [TextContent(type="text", text=content)]


def _handle_list_spec_files(arguments: dict) -> list[TextContent]:
    ws = get_active_workspace()
    if not ws:
        return [TextContent(type="text", text="错误：无激活的工作区")]

    subdir = arguments.get("subdir", "")
    root = ws.root / subdir if subdir else ws.root

    if not root.is_dir():
        return [TextContent(type="text", text=f"错误：目录不存在: {subdir}")]

    files = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(ws.root)).replace("\\", "/")
            is_delta = "changes" in f.parts
            entry = {"path": rel, "is_delta": is_delta, "size": f.stat().st_size}
            files.append(entry)

    return [TextContent(type="text", text=json.dumps(files, ensure_ascii=False, indent=2))]
