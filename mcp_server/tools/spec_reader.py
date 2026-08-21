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

from specstd.workspace import (
    safe_resolve, get_active_workspace,
    is_sync_dismissed, mark_sync_dismissed, pull,
)

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
                    "sg:// 前缀强制 SpecGuard 仓库根（消除双根同名歧义）。"
                    "可选 anchor/section 参数只取关键章节（T-512，省 token）："
                    "anchor=FR-xxx/AC-xxx 按锚点提取（支持 ### FR-xxx: 标题式与 - **FR-xxx**： 列表式），"
                    "section=章节编号或标题文字按 md 标题树提取；两者互斥，缺省读全文。",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对工作区根的路径（如 specs/module1/feature1/spec.md），"
                                   "或 sg:// 前缀的 SpecGuard 仓库路径（如 sg://scenarios/employee/person-profile/PP-RC-001.yaml）"
                },
                "anchor": {
                    "type": "string",
                    "description": "可选：FR/AC 锚点（如 FR-009、AC-003）——只返回该锚点章节（带行区间标头），"
                                   "与 section 互斥"
                },
                "section": {
                    "type": "string",
                    "description": "可选：md 章节编号（如 4）或标题文字子串（如 Functional Requirements）——"
                                   "只返回该章节（带行区间标头），与 anchor 互斥"
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
    Tool(
        name="sync_workspace",
        description="同步当前工作区（git pull）或本次会话不再提醒远端更新。"
                    "当 read_spec 返回「[远程状态] 远端有更新」决策提示时，征询用户后调用："
                    "用户同意同步→action=sync（拉取远端更新，同步成功后重新 read_spec 获取最新内容）；"
                    "用户拒绝同步→action=dismiss（本次会话不再提醒该工作区远端更新）。",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["sync", "dismiss"],
                    "description": "sync=拉取远端更新（git pull）；dismiss=本次会话不再提醒远端更新",
                }
            },
            "required": ["action"],
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "read_spec":
        return _handle_read_spec(arguments)
    elif name == "list_spec_files":
        return _handle_list_spec_files(arguments)
    elif name == "sync_workspace":
        return _handle_sync_workspace(arguments)
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
            BACKEND_DIR = SG_ROOT / "workbench" / "backend"
            from sg_core import file_preview
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


def _migration_hint(path: str) -> str:
    """K-xxx：文件路径迁移指引——路径指向 drafts/ 但文件不存在时，查台账定位去向。

    草稿入库后文件从 drafts/ 移到 scenarios/{module}/（ID 不变、路径迁移），
    Agent 用旧路径读取会「文件不存在」——台账（drafts/scenarios 表）维护
    ID → 当前路径映射，这里给出可执行指引而非裸报错。
    """
    if not path or "drafts/" not in path.replace("\\", "/"):
        return ""
    name = path.replace("\\", "/").split("/")[-1]
    if not name.endswith((".yaml", ".yml")):
        return ""
    sid = name.rsplit(".", 1)[0]
    try:
        BACKEND_DIR = SG_ROOT / "workbench" / "backend"
        from sg_core import ledger_store
        # 1) 场景台账：同 ID 已入库 → 指向库内当前路径（file_path 为相对仓库根路径）
        for r in ledger_store.query_scenarios():
            if r.get("id") == sid:
                rel = str(r.get("file_path", "")).replace("\\", "/")
                if rel:
                    return (f"；该场景已入库于 {rel}（文件随入库从 drafts/ 迁移到场景库，"
                            f"请用 read_scenario 按 ID {sid} 读取，或直接读该路径）")
        # 2) 草稿台账：status=promoted/discarded → 说明去向
        for d in ledger_store.query_drafts():
            if d.get("filename") == name:
                st = d.get("status", "")
                if st == "promoted":
                    mod = d.get("module", "")
                    return (f"；草稿 {name} 已入库（module={mod or '未知'}），"
                            f"请用 read_scenario 按 ID {sid} 读取库内场景")
                if st == "discarded":
                    return f"；草稿 {name} 已废弃（移入 drafts/_trash/）"
    except Exception:
        pass
    return ""


def _read_with_remote_status(resolved: Path, display_path: str) -> list[TextContent]:
    """读工作区文件，并在输出前注入远程仓库新鲜度提示。

    Agent 使用工作区文档前先判断远程仓库中该文件是否存在/是否有更新——
    非 git 工作区 / 远程不可达时静默无标记，不阻塞读取。
    用户已拒绝同步（sync_workspace action=dismiss）时，本次会话不再注入提示。
    """
    # 用户已拒绝同步 → 本次会话静默，不再提醒（避免反复打断）
    if is_sync_dismissed():
        return _read_text_guarded(resolved, display_path)
    from specstd.workspace import remote_file_marks
    try:
        mark = remote_file_marks([display_path]).get(display_path, "")
    except Exception:
        mark = ""
    note = ""
    if mark == "[远程已更新]":
        note = (
            "[远程状态] 远程仓库中该文件有更新版本，本地内容可能过时。\n"
            "请征询用户是否同步工作区：\n"
            '- 用户同意 → 调用 sync_workspace(action="sync")，'
            "同步成功后重新 read_spec 获取最新内容；\n"
            '- 用户拒绝 → 调用 sync_workspace(action="dismiss")，'
            "本次会话不再提醒。\n\n"
            "（下方为本地当前内容，供用户拒绝同步时直接使用。）\n\n"
        )
    elif mark == "[远程不存在]":
        note = "[远程状态] 远程仓库中不存在该文件（本地新增未推送，或远程已删除该文件）。\n\n"
    result = _read_text_guarded(resolved, display_path)
    if note and result:
        result = [TextContent(type="text", text=note + result[0].text)]
    return result


def _handle_sync_workspace(arguments: dict) -> list[TextContent]:
    """同步工作区（git pull）或标记本次会话不再提醒远端更新。

    与 read_spec 的 [远程状态] 提示闭环：发现远端有更新时，Agent 征询用户，
    按用户选择调用本工具——sync 拉取远端更新，dismiss 静默后续提示。
    """
    action = arguments.get("action", "")
    if action == "dismiss":
        marked = mark_sync_dismissed()
        if not marked:
            return [TextContent(type="text", text="错误：无激活的工作区，无法标记")]
        return [TextContent(type="text", text=json.dumps({
            "ok": True, "action": "dismiss", "workspace": marked,
            "message": f"本次会话不再提醒 {marked} 工作区的远端更新提示",
        }, ensure_ascii=False))]
    if action == "sync":
        ws = get_active_workspace()
        if not ws:
            return [TextContent(type="text", text="错误：无激活的工作区")]
        result = pull(ws.name)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    return [TextContent(type="text",
        text=f"错误：未知 action: {action}（合法值: sync / dismiss）")]


def _read_section(resolved: Path, display_path: str, anchor: str, section: str) -> list[TextContent]:
    """T-512 章节提取分支：anchor/section 定位参数——只返回命中章节（带行区间标头）。

    读全文后确定性提取（不受 _MAX_READ 200KB 截断影响，提取结果天然小）；
    未命中返回含可用锚点清单的自愈提示。
    """
    from mcp_server.tools import sections as _sections
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [TextContent(type="text", text=f"错误：读取失败: {display_path}: {e}")]
    if anchor:
        hit = _sections.extract_fr_section(text, anchor)
        if hit is None:
            anchors = _sections.list_fr_anchors(text)
            hint = (f"可用锚点：{'、'.join(anchors[:20])}" if anchors
                    else "该文件无 FR/AC 锚点（支持 ### FR-xxx: 标题式与 - **FR-xxx**： 列表式）")
            return [TextContent(type="text", text=f"错误：锚点未命中: {anchor}（{hint}）")]
    else:
        hit = _sections.extract_heading_section(text, section)
        if hit is None:
            return [TextContent(type="text", text=(
                f"错误：章节未命中: {section}（按 md 标题树匹配，"
                "支持章节编号如「4」或标题文字子串）"))]
    header = f"--- {display_path} · {hit['title']} · 行{hit['start']}-{hit['end']} ---\n"
    return [TextContent(type="text", text=header + hit["chunk"])]


def _handle_read_spec(arguments: dict) -> list[TextContent]:
    path = arguments.get("path", "")
    if not path:
        return [TextContent(type="text", text="错误：缺少 path 参数")]
    # T-512：可选 anchor/section 定位参数（互斥），只取关键章节
    anchor = str(arguments.get("anchor", "") or "").strip()
    section = str(arguments.get("section", "") or "").strip()
    if anchor and section:
        return [TextContent(type="text", text="错误：anchor 与 section 参数互斥，请只传一个")]
    locate = bool(anchor or section)

    # K-021：sg:// 前缀强制 SpecGuard 仓库根
    if path.startswith("sg://"):
        sg_path = path[len("sg://"):]
        resolved = _resolve_sg_root(sg_path)
        if resolved is None:
            return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界或敏感目录: {path}")]
        if not resolved.is_file():
            hint = _migration_hint(sg_path)
            return [TextContent(type="text", text=f"错误：文件不存在: {path}{hint}")]
        if locate:
            return _read_section(resolved, path, anchor, section)
        return _read_text_guarded(resolved, path)

    # 第一根：工作区（原行为）
    resolved = safe_resolve(path)
    if resolved is not None and resolved.is_file():
        if locate:
            return _read_section(resolved, path, anchor, section)
        return _read_with_remote_status(resolved, path)

    # 第二根：SpecGuard 仓库（K-021 回退——scenarios/docs/contracts 等仓库侧内容）
    sg_resolved = _resolve_sg_root(path)
    if sg_resolved is not None and sg_resolved.is_file():
        if locate:
            return _read_section(sg_resolved, path, anchor, section)
        return _read_text_guarded(sg_resolved, path)

    hint = _migration_hint(path)
    if resolved is None and sg_resolved is None:
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界或工作区未激活: {path}")]
    return [TextContent(type="text", text=(
        f"错误：文件不存在: {path}（已查找工作区根与 SpecGuard 仓库根；"
        f"仓库侧路径可用 sg:// 前缀明确指定）{hint}"))]


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
