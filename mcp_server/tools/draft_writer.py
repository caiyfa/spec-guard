"""draft_writer — 写入草稿到 .specguard/drafts/ 目录。

工具：
  write_draft: 写入草稿（drafts/ 限定 + 禁覆盖 + patch 模式）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import drafts_dir, get_workspace_root  # noqa: E402


def _drafts_root() -> Path:
    """获取草稿目录（动态解析当前工作区 .specguard/drafts/）。"""
    d = drafts_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rel_path(path: Path) -> str:
    """返回相对工作区根的路径（用于展示）。"""
    ws = get_workspace_root()
    if ws:
        try:
            return str(path.relative_to(ws))
        except ValueError:
            pass
    return str(path)


def _record_meta(filename: str, scenario_id: str = ""):
    """记录草稿元数据到 drafts/_meta.json（M7 作者归属 + K-013 场景关联/信息包基准 commit）。"""
    try:
        from services.auth import current_emp_no  # 延迟导入（MCP stdio 无此上下文）
        emp_no = current_emp_no()
    except Exception:
        emp_no = ""
    if not emp_no and not scenario_id:
        return
    meta_path = _drafts_root() / "_meta.json"
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    entry = meta.get(filename, {})
    if emp_no:
        entry["author"] = emp_no
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if scenario_id:
        entry["scenario_id"] = scenario_id
        # K-013：记录信息包基准 commit（git 型），供后续核对信息包是否已演进
        try:
            from services import scenario_meta as sm
            m = sm.get_meta(scenario_id)
            if m:
                commits = [e.get("commit") for e in (m.get("info_pack") or []) if e.get("commit")]
                if commits:
                    entry["pack_commit"] = commits[0]
        except Exception:
            pass
    meta[filename] = entry
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")


def _record_author(filename: str):
    """记录草稿作者到 drafts/_meta.json（M7 多用户归属；无用户上下文时跳过）。"""
    _record_meta(filename)

TOOLS = [
    Tool(
        name="write_draft",
        description="写入草稿到 drafts/ 目录。路径限定（仅 drafts/ 可写），禁止覆盖已有文件"
                    "（mode=create 时已存在返回 OVERWRITE_DENIED），支持 patch 模式（追加到已有文件）。"
                    "写入前自动备份到 .bak 文件（支持 undo_draft 回滚）。",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "草稿文件名（如 PP-RC-008.yaml），不允许包含路径分隔符"},
                "content": {"type": "string", "description": "草稿内容（YAML 文本）"},
                "mode": {"type": "string", "enum": ["create", "patch"],
                          "description": "模式：create（新建，禁止覆盖）/ patch（追加到已有文件）",
                          "default": "create"},
                "scenario_id": {"type": "string",
                                 "description": "可选：来源场景元数据 ID（如 SG-META-0001）。"
                                 "记录后草稿与其信息包关联，信息包内容变更时可被核对标记"}
            },
            "required": ["filename", "content"]
        }
    ),
    Tool(
        name="undo_draft",
        description="撤销最后一次 write_draft 操作：从 .bak 备份恢复文件内容。"
                    "如果没有 .bak 文件则返回错误。",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "要撤销的草稿文件名"}
            },
            "required": ["filename"]
        }
    ),
    Tool(
        name="promote_draft",
        description="草稿入库：格式校验 PASS → 移入 scenarios/{module}/ → 契约基线更新 → 发布门禁"
                    "（失败自动回滚，不产生半截入库）。仅在用户明确确认入库后调用。",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "草稿文件名（如 PP-RC-008.yaml）"},
                "module": {"type": "string",
                            "description": "目标模块目录（相对 scenarios/，如 employee/person-profile）"},
                "skip_gate": {"type": "boolean",
                               "description": "跳过发布门禁（仅调试用途，默认 false）", "default": False}
            },
            "required": ["filename", "module"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_draft":
        return _handle_write_draft(arguments)
    elif name == "undo_draft":
        return _handle_undo_draft(arguments)
    elif name == "promote_draft":
        return _handle_promote_draft(arguments)
    return []


def _handle_promote_draft(arguments: dict) -> list[TextContent]:
    """K-015：草稿入库（与 API /drafts/{filename}/promote 同一实现）。"""
    filename = arguments.get("filename", "")
    module = arguments.get("module", "")
    skip_gate = bool(arguments.get("skip_gate", False))
    if not filename or not module:
        return [TextContent(type="text", text="错误：缺少 filename 或 module 参数")]

    try:
        from services import draft_promote
        try:
            from services.auth import current_emp_no
            emp_no = current_emp_no()
        except Exception:
            emp_no = ""
        result = draft_promote.promote(filename, module, skip_gate=skip_gate, emp_no=emp_no)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        code = getattr(e, "code", "error")
        detail = getattr(e, "detail", None)
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error_code": code, "error": str(e), **(detail or {}),
        }, ensure_ascii=False, indent=2))]


def _backup_draft(filename: str):
    """写入前备份已有文件到 .bak（G4-A 操作撤销）。"""
    drafts_root = _drafts_root()
    draft_path = drafts_root / filename
    bak_path = drafts_root / f"{filename}.bak"
    if draft_path.exists():
        bak_path.write_text(draft_path.read_text(encoding="utf-8"), encoding="utf-8")


def _handle_write_draft(arguments: dict) -> list[TextContent]:
    filename = arguments.get("filename", "")
    content = arguments.get("content", "")
    mode = arguments.get("mode", "create")
    scenario_id = arguments.get("scenario_id", "")  # K-013: 来源场景关联

    if not filename or not content:
        return [TextContent(type="text", text="错误：缺少 filename 或 content 参数")]

    # 路径守卫：只允许 drafts/ 目录，禁止路径分隔符和 ..
    if "/" in filename or "\\" in filename or ".." in filename:
        return [TextContent(type="text", text="OUT_OF_SCOPE: filename 不允许包含路径分隔符或 ..")]

    try:
        drafts_root = _drafts_root()
    except RuntimeError as e:
        return [TextContent(type="text", text=f"错误：{e}")]
    draft_path = drafts_root / filename

    if mode == "create":
        if draft_path.exists():
            return [TextContent(type="text", text=f"OVERWRITE_DENIED: 文件已存在: {filename}（使用 mode=patch 追加）")]
        draft_path.write_text(content, encoding="utf-8")
        _record_meta(filename, scenario_id)
        return [TextContent(type="text", text=json.dumps({
            "ok": True, "action": "create",
            "path": _rel_path(draft_path), "size": len(content),
        }, ensure_ascii=False, indent=2))]

    elif mode == "patch":
        # G4-A: patch 前备份
        _backup_draft(filename)
        existing = ""
        if draft_path.exists():
            existing = draft_path.read_text(encoding="utf-8")
        merged = existing + "\n" + content if existing else content
        draft_path.write_text(merged, encoding="utf-8")
        _record_meta(filename, scenario_id)
        return [TextContent(type="text", text=json.dumps({
            "ok": True, "action": "patch",
            "path": _rel_path(draft_path), "size": len(merged),
            "backup": f"{filename}.bak",
        }, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"错误：未知模式: {mode}")]


def _handle_undo_draft(arguments: dict) -> list[TextContent]:
    """G4-A: 从 .bak 备份恢复草稿文件。"""
    filename = arguments.get("filename", "")
    if not filename:
        return [TextContent(type="text", text="错误：缺少 filename 参数")]
    if "/" in filename or "\\" in filename or ".." in filename:
        return [TextContent(type="text", text="OUT_OF_SCOPE: filename 不允许包含路径分隔符或 ..")]

    try:
        drafts_root = _drafts_root()
    except RuntimeError as e:
        return [TextContent(type="text", text=f"错误：{e}")]
    bak_path = drafts_root / f"{filename}.bak"
    draft_path = drafts_root / filename

    if not bak_path.exists():
        return [TextContent(type="text", text=f"错误：无 .bak 备份文件: {filename}.bak")]

    # 恢复
    draft_path.write_text(bak_path.read_text(encoding="utf-8"), encoding="utf-8")
    return [TextContent(type="text", text=json.dumps({
        "ok": True, "action": "undo",
        "path": _rel_path(draft_path),
        "restored_from": f"{filename}.bak",
    }, ensure_ascii=False, indent=2))]
