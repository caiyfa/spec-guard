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
    Tool(
        name="list_info_pack_artifacts",
        description="查询信息包的全部关联产物（串联视图）：信息包文件清单（含新鲜度）、"
                    "由该信息包生成的草稿（含场景 ID/标题/是否已过时）。"
                    "用于回答「信息包对应的草稿有哪些」「这个场景生成了什么」等问题——"
                    "不要通过翻阅 spec 文件猜测，直接用本工具查询。",
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
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "read_info_pack":
        return _handle_read_info_pack(arguments)
    elif name == "add_to_info_pack":
        return _handle_add_to_info_pack(arguments)
    elif name == "list_info_pack_artifacts":
        return _handle_list_artifacts(arguments)
    return []


def _handle_list_artifacts(arguments: dict) -> list[TextContent]:
    """K-015：查询信息包关联产物（文件新鲜度 + 派生草稿）。"""
    scenario_id = arguments.get("scenario_id", "")
    if not scenario_id:
        return [TextContent(type="text", text="错误：缺少 scenario_id 参数")]

    try:
        from services import scenario_meta, info_pack_freshness
        meta = scenario_meta.get_meta(scenario_id)
    except Exception as e:
        return [TextContent(type="text", text=f"错误：无法访问场景元数据: {e}")]
    if not meta:
        return [TextContent(type="text", text=f"错误：场景不存在: {scenario_id}")]

    # 信息包文件 + 新鲜度
    freshness = info_pack_freshness.check_freshness(scenario_id)
    files = freshness.get("files", [])

    # 关联草稿（_meta.json 按 scenario_id 匹配）+ 解析 YAML 取场景 id/title
    drafts = []
    try:
        import yaml as _yaml
        from specstd.workspace import drafts_dir
        root = drafts_dir()
        meta_path = root / "_meta.json"
        meta_map = {}
        if meta_path.is_file():
            try:
                meta_map = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta_map = {}
        for fname, entry in meta_map.items():
            if entry.get("scenario_id") != scenario_id:
                continue
            f = root / fname
            yaml_id, title = "", ""
            if f.is_file():
                try:
                    raw = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    yaml_id, title = str(raw.get("id", "")), str(raw.get("title", ""))
                except Exception:
                    pass
            drafts.append({
                "filename": fname,
                "scenario_yaml_id": yaml_id,
                "title": title,
                "promoted_or_missing": not f.is_file(),
                "modified": entry.get("updated_at", ""),
                "author": entry.get("author", ""),
            })
        drafts.sort(key=lambda d: d["modified"], reverse=True)
    except Exception:
        pass  # 无工作区/drafts 目录时草稿清单为空

    result = {
        "scenario_id": scenario_id,
        "name": meta.get("name", ""),
        "workspace": meta.get("workspace", ""),
        "files": files,
        "drafts": drafts,
        "summary": {
            "file_count": len(files),
            "stale_count": freshness.get("stale_count", 0),
            "draft_count": len(drafts),
        },
        "note": "草稿关联自 K-013 起由 write_draft 的 scenario_id 参数记录；更早的草稿无关联记录。"
                "promoted_or_missing=true 表示草稿已入库或已删除。",
    }

    # K-026：入库血缘（信息包 → 已入库场景）——串联 DAG 编排与执行
    try:
        promoted = scenario_meta.get_promotions(scenario_id)
        if promoted:
            result["promoted_scenarios"] = promoted
            result["summary"]["promoted_count"] = len(promoted)
    except Exception:
        pass

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


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

    # 逐个读取文件（K-013：附新鲜度标记，Agent 可感知文件是否在引用后被修改/删除）
    from specstd.workspace import safe_resolve
    parts = []
    for entry in files:
        file_path = entry.get("path", "") if isinstance(entry, dict) else str(entry)
        stored_sha = entry.get("sha", "") if isinstance(entry, dict) else ""
        resolved = safe_resolve(file_path)
        if resolved is None:
            parts.append(f"--- {file_path} ---\n[OUT_OF_SCOPE: 路径越界或工作区未激活]\n")
            continue
        if not resolved.is_file():
            parts.append(f"--- {file_path} [已删除] ---\n[文件不存在：引用后已被删除或移动]\n")
            continue
        try:
            # K-030：办公文档（xlsx/docx/pdf）经 file_preview 转文本——
            # 信息包关键文件常是 xlsx（read_text 直接 UnicodeDecodeError）
            from services import file_preview
            if file_preview.is_office_doc(resolved):
                _fmt, content = file_preview.preview_text(resolved)
                content = f"[办公文档已转换为文本预览]\n{content}"
            else:
                content = resolved.read_text(encoding="utf-8", errors="replace")
            mark = ""
            if stored_sha:
                try:
                    if scenario_meta.file_sha(resolved) != stored_sha:
                        mark = " [已变更]"
                except Exception:
                    pass
            parts.append(f"--- {file_path}{mark} ---\n{content}\n")
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
