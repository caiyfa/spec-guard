"""spec_reader — 读取当前工作区的 spec 文件 + SpecGuard 仓库内容（K-021 双根）。

工具：
  read_spec: 读取单个文件（只读，越界/敏感路径拒绝）
  list_spec_files: 列出文件树（含 delta 标记）

K-021：Agent 能力设定为「能获取 SpecGuard 所有内容」——read_spec 双根解析：
  - 默认相对工作区根（原行为不变），未命中时回退 SpecGuard 仓库根
    （scenarios/ docs/ contracts_baseline.json release 报告等仅存在于仓库侧的内容）
  - sg:// 前缀强制 SpecGuard 仓库根（消除双根同名歧义，如 AGENTS.md）
  - 敏感路径拒读：.git / workbench/backend/data（用户 DB）/ agent/sessions（会话记录）/
    node_modules / __pycache__ / .env*；二进制文件（xlsx/pdf/png/db 等）返回不可读提示
"""

import json
from pathlib import Path

from mcp.types import Tool, TextContent

from specstd.workspace import safe_resolve, get_active_workspace

SG_ROOT = Path(__file__).resolve().parent.parent.parent

# K-021：SpecGuard 仓库侧的敏感/噪音目录（拒读）
_SG_BLOCKED_PARTS = {".git", "node_modules", "__pycache__", ".pytest_cache"}
_SG_BLOCKED_PREFIXES = (
    "workbench/backend/data",  # 用户/会话 SQLite DB
    "agent/sessions",          # 会话记录（含用户数据）
)
# 二进制扩展名（文本读取无意义，明确提示而非抛异常或输出乱码）
_BINARY_EXTS = {".xlsx", ".xls", ".pdf", ".png", ".jpg", ".jpeg", ".gif",
                ".db", ".sqlite", ".zip", ".jar", ".pyc"}
# 文本读取上限（防超大文件撑爆上下文）
_MAX_READ = 200 * 1024

TOOLS = [
    Tool(
        name="read_spec",
        description="读取文件内容（只读，越界/敏感路径拒绝）。"
                    "默认相对当前激活工作区根（AGENTS.md、specs/**、changes/**、.specguard/** 等）；"
                    "工作区未命中时自动回退 SpecGuard 仓库根（scenarios/**、docs/**、"
                    "contracts_baseline.json、release 报告等）；"
                    "sg:// 前缀强制 SpecGuard 仓库根（消除双根同名歧义）。",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对工作区根的路径（如 specs/module1/feature1/spec.md），"
                                   "或 sg:// 前缀的 SpecGuard 仓库路径（如 sg://scenarios/employee/person-profile/PP-RC-001.yaml）"
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


def _resolve_sg_root(path: str) -> Path | None:
    """K-021：相对 SpecGuard 仓库根解析（越界/敏感路径返回 None）。"""
    if not path or ".." in Path(path).parts:
        return None
    try:
        resolved = (SG_ROOT / path).resolve()
        resolved.relative_to(SG_ROOT)
    except (ValueError, OSError):
        return None
    rel = str(resolved.relative_to(SG_ROOT)).replace("\\", "/")
    parts = set(resolved.relative_to(SG_ROOT).parts)
    if parts & _SG_BLOCKED_PARTS:
        return None
    if any(rel == bp or rel.startswith(bp + "/") for bp in _SG_BLOCKED_PREFIXES):
        return None
    if resolved.name.startswith(".env"):
        return None
    return resolved


def _read_text_guarded(resolved: Path, display_path: str) -> list[TextContent]:
    """带二进制/大小守卫的文本读取。

    K-030：办公文档（xlsx/docx/pdf）经 file_preview 转换为 Markdown/文本——
    Agent 可直接读信息包里的 xlsx（标签库维护test-cases.xlsx 是关键信息源，
    此前只能拒读）；其他二进制仍拒读。
    """
    ext = resolved.suffix.lower()
    if ext in {".xlsx", ".docx", ".pdf"}:
        try:
            import sys as _sys
            BACKEND_DIR = SG_ROOT / "workbench" / "backend"
            if str(BACKEND_DIR) not in _sys.path:
                _sys.path.insert(0, str(BACKEND_DIR))
            from services import file_preview
            _fmt, text = file_preview.preview_text(resolved)
            note = f"[{ext} 已转换为文本预览，大文件可能截断]\n\n"
            return [TextContent(type="text", text=note + text)]
        except Exception as e:
            return [TextContent(type="text", text=f"办公文档转换失败: {display_path}: {e}")]
    if ext in _BINARY_EXTS:
        return [TextContent(type="text", text=(
            f"二进制文件不可文本读取: {display_path}（{ext}）。"
            f"如需其中信息，请让用户在对话中 @引用 或转换为文本格式"))]
    raw = resolved.read_bytes()
    truncated = len(raw) > _MAX_READ
    if truncated:
        raw = raw[:_MAX_READ]
    content = raw.decode("utf-8", errors="replace")
    if truncated:
        content += f"\n\n[截断] 文件超过 {_MAX_READ // 1024}KB，仅显示前段"
    return [TextContent(type="text", text=content)]


def _handle_read_spec(arguments: dict) -> list[TextContent]:
    path = arguments.get("path", "")
    if not path:
        return [TextContent(type="text", text="错误：缺少 path 参数")]

    # K-021：sg:// 前缀强制 SpecGuard 仓库根
    if path.startswith("sg://"):
        sg_path = path[len("sg://"):]
        resolved = _resolve_sg_root(sg_path)
        if resolved is None:
            return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界或敏感目录: {path}")]
        if not resolved.is_file():
            return [TextContent(type="text", text=f"错误：文件不存在: {path}")]
        return _read_text_guarded(resolved, path)

    # 第一根：工作区（原行为）
    resolved = safe_resolve(path)
    if resolved is not None and resolved.is_file():
        return _read_text_guarded(resolved, path)

    # 第二根：SpecGuard 仓库（K-021 回退——scenarios/docs/contracts 等仓库侧内容）
    sg_resolved = _resolve_sg_root(path)
    if sg_resolved is not None and sg_resolved.is_file():
        return _read_text_guarded(sg_resolved, path)

    if resolved is None and sg_resolved is None:
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界或工作区未激活: {path}")]
    return [TextContent(type="text", text=(
        f"错误：文件不存在: {path}（已查找工作区根与 SpecGuard 仓库根；"
        f"仓库侧路径可用 sg:// 前缀明确指定）"))]


def _handle_list_spec_files(arguments: dict) -> list[TextContent]:
    ws = get_active_workspace()
    if not ws:
        return [TextContent(type="text", text="错误：无激活的工作区")]

    subdir = arguments.get("subdir", "")
    # V3 修复：subdir 必须解析在工作区根之内（与 read_spec 同一守卫，防路径穿越）
    if subdir:
        root = safe_resolve(subdir)
        if root is None:
            return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界: {subdir}")]
    else:
        root = ws.root

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
