"""draft_writer — 写入草稿到 drafts/ 目录。

工具：
  write_draft: 写入草稿（drafts/ 限定 + 禁覆盖 + patch 模式）
"""

import json
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
DRAFTS_ROOT = SG_ROOT / "drafts"

TOOLS = [
    Tool(
        name="write_draft",
        description="写入草稿到 drafts/ 目录。路径限定（仅 drafts/ 可写），禁止覆盖已有文件"
                    "（mode=create 时已存在返回 OVERWRITE_DENIED），支持 patch 模式（追加到已有文件）。",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "草稿文件名（如 PP-RC-008.yaml），不允许包含路径分隔符"},
                "content": {"type": "string", "description": "草稿内容（YAML 文本）"},
                "mode": {"type": "string", "enum": ["create", "patch"],
                          "description": "模式：create（新建，禁止覆盖）/ patch（追加到已有文件）",
                          "default": "create"}
            },
            "required": ["filename", "content"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_draft":
        return _handle_write_draft(arguments)
    return []


def _handle_write_draft(arguments: dict) -> list[TextContent]:
    filename = arguments.get("filename", "")
    content = arguments.get("content", "")
    mode = arguments.get("mode", "create")

    if not filename or not content:
        return [TextContent(type="text", text="错误：缺少 filename 或 content 参数")]

    # 路径守卫：只允许 drafts/ 目录，禁止路径分隔符和 ..
    if "/" in filename or "\\" in filename or ".." in filename:
        return [TextContent(type="text", text="OUT_OF_SCOPE: filename 不允许包含路径分隔符或 ..")]

    DRAFTS_ROOT.mkdir(parents=True, exist_ok=True)
    draft_path = DRAFTS_ROOT / filename

    if mode == "create":
        if draft_path.exists():
            return [TextContent(type="text", text=f"OVERWRITE_DENIED: 文件已存在: {filename}（使用 mode=patch 追加）")]
        draft_path.write_text(content, encoding="utf-8")
        return [TextContent(type="text", text=json.dumps({
            "ok": True, "action": "create",
            "path": str(draft_path.relative_to(SG_ROOT)), "size": len(content),
        }, ensure_ascii=False, indent=2))]

    elif mode == "patch":
        existing = ""
        if draft_path.exists():
            existing = draft_path.read_text(encoding="utf-8")
        merged = existing + "\n" + content if existing else content
        draft_path.write_text(merged, encoding="utf-8")
        return [TextContent(type="text", text=json.dumps({
            "ok": True, "action": "patch",
            "path": str(draft_path.relative_to(SG_ROOT)), "size": len(merged),
        }, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"错误：未知模式: {mode}")]
