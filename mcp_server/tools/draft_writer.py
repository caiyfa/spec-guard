"""draft_writer — 草稿生命周期工具（T-982 收敛：5 碎片合并为单 draft 工具）。

工具：
  draft（action 参数化）:
    write         写入草稿（drafts/ 限定 + 禁覆盖 + patch 模式）［原 write_draft］
    undo          从 .bak 备份恢复草稿［原 undo_draft］
    promote       单份草稿入库［原 promote_draft］
    promote_batch 批量草稿入库［原 promote_drafts］
    reset         重置草稿区状态（清空草稿/回收站/元数据/DB 记录）［原 reset_draft_area］
"""

import contextvars
import json
from datetime import datetime
from pathlib import Path

from mcp.types import Tool, TextContent

from mcp_server.tools.tool_meta import ActionMeta, SIDE_DRAFT, consolidate

SG_ROOT = Path(__file__).resolve().parent.parent.parent

from specstd.workspace import drafts_dir, get_workspace_root  # noqa: E402


# M6 修复：pending source files 改 contextvar——原模块级全局变量在多用户并发
# 会话下会串户（用户 A read_spec 设置的依赖记录被并发的用户 B 覆盖）。
# runtime 在 to_thread 线程内 set，asyncio.run 复制调用方 context 后 pop，同链透传。
_PENDING_SOURCE_FILES: contextvars.ContextVar[list] = contextvars.ContextVar(
    "sg_pending_source_files", default=[])


def set_pending_source_files(files: list[str]):
    """设置待写入的 source files（供 _handle_write_draft 消费）。"""
    _PENDING_SOURCE_FILES.set(list(files))


def pop_pending_source_files() -> list[str]:
    """消费并清空 pending source files。"""
    files = _PENDING_SOURCE_FILES.get()
    _PENDING_SOURCE_FILES.set([])
    return files


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


def _record_meta(filename: str, scenario_id: str = "", source_files: list[str] = None):
    """记录草稿元数据到 drafts/_meta.json（M7 作者归属 + K-013 场景关联/信息包基准 commit + K-xxx 文件依赖）。"""
    try:
        from sg_core.emp_context import current_emp_no  # 延迟导入（MCP stdio 无此上下文）
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
            from sg_core import scenario_meta as sm
            m = sm.get_meta(scenario_id)
            if m:
                commits = [e.get("commit") for e in (m.get("info_pack") or []) if e.get("commit")]
                if commits:
                    entry["pack_commit"] = commits[0]
        except Exception:
            pass
    if source_files:
        entry["source_files"] = source_files
    meta[filename] = entry
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")


def _record_author(filename: str):
    """记录草稿作者到 drafts/_meta.json（M7 多用户归属；无用户上下文时跳过）。"""
    _record_meta(filename)

# T-982：原 5 个碎片 Tool 声明逐字保留（schema/描述零漂移），模块末尾
# consolidate 合并为单 draft 工具（action 参数化）。
_TOOL_DECLS = [
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
                    "（失败自动回滚，不产生半截入库）。仅在用户明确确认入库后调用。"
                    "T-313：replace=true 覆盖同名场景（更新已有场景的写入路径，原文件备份+失败回滚）。",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "草稿文件名（如 PP-RC-008.yaml）"},
                "module": {"type": "string",
                            "description": "目标模块目录（相对 scenarios/，如 employee/person-profile）"},
                "skip_gate": {"type": "boolean",
                               "description": "跳过发布门禁（仅调试用途，默认 false）", "default": False},
                "replace": {"type": "boolean",
                             "description": "覆盖同名场景（更新已有场景用；缺省 false 时同名冲突）", "default": False}
            },
            "required": ["filename", "module"]
        }
    ),
    Tool(
        name="promote_drafts",
        description="批量草稿入库（多份一键入库，K-021⑥）：逐份格式校验（不合格单份跳过并给出原因）"
                    "→ 合格批次整批移入 scenarios/{module}/ → 一次契约基线更新 → 一次发布门禁"
                    "（失败整批回滚）。多份草稿入库必须用它（逐份 promote_draft 会重复跑全量门禁）；"
                    "仅在用户明确确认入库后调用。",
        inputSchema={
            "type": "object",
            "properties": {
                "filenames": {"type": "array", "items": {"type": "string"},
                               "description": "要入库的草稿文件名清单（省略 = drafts/ 全部 YAML 草稿）"},
                "module": {"type": "string",
                            "description": "目标模块目录（相对 scenarios/，如 system-settings/tag-library）"},
                "skip_gate": {"type": "boolean",
                               "description": "跳过发布门禁（仅调试用途，默认 false）", "default": False}
            },
            "required": ["module"]
        }
    ),
    Tool(
        name="reset_draft_area",
        description="重置草稿区状态：清空当前工作区所有草稿文件、回收站、元数据、三闸与台账记录。"
                    "操作不可逆（已入库场景不受影响），调用前请用户确认。",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
]


async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_draft":
        return _handle_write_draft(arguments)
    elif name == "undo_draft":
        return _handle_undo_draft(arguments)
    elif name == "promote_draft":
        return _handle_promote_draft(arguments)
    elif name == "promote_drafts":
        return _handle_promote_drafts(arguments)
    elif name == "reset_draft_area":
        return _handle_reset_draft_area(arguments)
    return []


def _handle_promote_drafts(arguments: dict) -> list[TextContent]:
    """K-021⑥：批量入库（与 promote_draft 同一服务层）。"""
    filenames = arguments.get("filenames") or None
    module = arguments.get("module", "")
    skip_gate = bool(arguments.get("skip_gate", False))
    if not module:
        return [TextContent(type="text", text="错误：缺少 module 参数")]
    if filenames is not None and not isinstance(filenames, list):
        return [TextContent(type="text", text="错误：filenames 必须是数组")]

    try:
        from sg_core import draft_promote
        try:
            from sg_core.emp_context import current_emp_no
            emp_no = current_emp_no()
        except Exception:
            emp_no = ""
        result = draft_promote.promote_batch(filenames, module,
                                             skip_gate=skip_gate, emp_no=emp_no)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        code = getattr(e, "code", "error")
        detail = getattr(e, "detail", None)
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error_code": code, "error": str(e), **(detail or {}),
        }, ensure_ascii=False, indent=2))]


def _handle_promote_draft(arguments: dict) -> list[TextContent]:
    """K-015：草稿入库（与 API /drafts/{filename}/promote 同一实现）。

    T-313：replace=true 覆盖同名场景（更新已有场景）；缺省 false 时同名冲突。
    """
    filename = arguments.get("filename", "")
    module = arguments.get("module", "")
    skip_gate = bool(arguments.get("skip_gate", False))
    replace = bool(arguments.get("replace", False))
    if not filename or not module:
        return [TextContent(type="text", text="错误：缺少 filename 或 module 参数")]

    try:
        from sg_core import draft_promote
        try:
            from sg_core.emp_context import current_emp_no
            emp_no = current_emp_no()
        except Exception:
            emp_no = ""
        result = draft_promote.promote(filename, module, skip_gate=skip_gate,
                                       emp_no=emp_no, replace=replace)
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
        # 获取并消费 pending source files（A+B：注入头部注释 + 记录到 _meta.json）
        source_files = pop_pending_source_files()
        if source_files:
            header = "# 生成依据：\n" + "".join(f"#   - {f}\n" for f in source_files) + "\n"
            content = header + content
        draft_path.write_text(content, encoding="utf-8")
        _record_meta(filename, scenario_id, source_files=source_files)
        _register_gates(filename, content)
        _record_product_index(draft_path)
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
        _register_gates(filename, merged)
        _record_product_index(draft_path)
        return [TextContent(type="text", text=json.dumps({
            "ok": True, "action": "patch",
            "path": _rel_path(draft_path), "size": len(merged),
            "backup": f"{filename}.bak",
        }, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"错误：未知模式: {mode}")]


def _record_product_index(draft_path):
    """T-1000 F3：草稿产出登记 product_index（产物 → 会话/工号 反查）。

    会话来自 session_context（agent runtime 注入），stdio/纯 API 路径为空串；
    失败静默——索引是派生层，绝不阻断草稿写入主路径。
    """
    try:
        from sg_core.product_index import record_product
        from sg_core.emp_context import current_emp_no
        from sg_core.session_context import current_session_id
        from specstd.workspace import get_context_workspace
        record_product(_rel_path(draft_path), "draft",
                       session_id=current_session_id(),
                       emp_no=current_emp_no(),
                       workspace=get_context_workspace() or "")
    except Exception:
        pass


def _register_gates(filename: str, content: str):
    """T-061：write 落盘后自动登记草稿三闸并跑第②闸（格式校验自动先跑）。

    从 YAML 提取 scenario_id/covers/source_delta 登记 sg_draft_gates；
    失败静默（三闸登记失败不阻断草稿写入主流程，promote 时 fail-closed 拦截）。
    """
    try:
        import yaml as _yaml
        from specstd.workspace import get_context_emp_no
        from sg_core import draft_gates

        draft_gates.ensure_tables()
        raw = _yaml.safe_load(content) or {}
        covers = (raw.get("doc") or {}).get("covers") or raw.get("covers") or []
        emp = get_context_emp_no() or ""
        draft_gates.register_draft(
            filename,
            scenario_id=str(raw.get("id", "") or ""),
            covers=[str(c) for c in covers],
            source_delta=str(raw.get("source_delta", "") or ""),
            created_by=emp,
        )
    except Exception:
        pass


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


def _handle_reset_draft_area(arguments: dict) -> list[TextContent]:
    """重置草稿区状态：清空当前工作区所有草稿文件、回收站、元数据、三闸与台账。"""
    try:
        drafts_root = _drafts_root()
    except RuntimeError as e:
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error": str(e),
        }, ensure_ascii=False, indent=2))]

    try:
        from specstd.workspace import get_active_workspace
    except Exception:
        get_active_workspace = None

    # get_active_workspace() 返回 WorkspaceInfo 对象（dataclass，.name 属性），非 dict
    ws = ""
    if get_active_workspace:
        try:
            info = get_active_workspace()
            ws = info.name if info else ""
        except Exception:
            ws = ""
    stats = {"yaml_deleted": 0, "bak_deleted": 0, "trash_deleted": 0}

    # 1. 删除 .yaml / .yml / .bak
    if drafts_root.is_dir():
        for f in list(drafts_root.glob("*.yaml")) + list(drafts_root.glob("*.yml")):
            f.unlink(missing_ok=True)
            stats["yaml_deleted"] += 1
        for f in list(drafts_root.glob("*.bak")):
            f.unlink(missing_ok=True)
            stats["bak_deleted"] += 1

        # 2. 重置 _meta.json
        meta_path = drafts_root / "_meta.json"
        if meta_path.is_file():
            meta_path.write_text("{}\n", encoding="utf-8")

        # 3. 清空 _trash/
        trash = drafts_root / "_trash"
        if trash.is_dir():
            for f in list(trash.glob("*")):
                if f.is_file():
                    f.unlink(missing_ok=True)
                    stats["trash_deleted"] += 1

    # 4. 删除 DB 三闸记录
    try:
        from sg_core import draft_gates
        if ws:
            draft_gates.delete_workspace_gates(ws)
    except Exception:
        pass

    # 5. 删除 DB 草稿台账
    try:
        from sg_core import ledger_store
        if ws:
            ledger_store.clear_drafts(ws)
    except Exception:
        pass

    return [TextContent(type="text", text=json.dumps({
        "ok": True, "workspace": ws, **stats,
    }, ensure_ascii=False, indent=2))]


# ══════════════════════════════════════════════════════════
# T-982 工具收敛：5 碎片合并为单 draft 工具（action 参数化）
# ══════════════════════════════════════════════════════════
TOOLS, handle = consolidate(
    "draft",
    "草稿生命周期管理：写入/撤销/入库（单份/批量）/重置草稿区。"
    "写草稿用 write；入库（移入场景库+发布门禁）用 promote/promote_batch"
    "（仅用户明确确认后）；reset 不可逆，调用前请用户确认。",
    actions={
        "write": ActionMeta(legacy="write_draft", rbac="product", doc_track="write"),
        "undo": ActionMeta(legacy="undo_draft", doc_track="write"),
        "promote": ActionMeta(legacy="promote_draft", doc_track="write"),
        "promote_batch": ActionMeta(legacy="promote_drafts", doc_track="write"),
        "reset": ActionMeta(legacy="reset_draft_area"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="draft",
    side_effect=SIDE_DRAFT,
)
