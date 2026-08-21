"""spec_search — 工作区 spec 文本搜索 + FR 编号解析校验（编号重排能力）。
>
> T-982 收敛：2 工具合并为单 spec_search 工具（action=search/parse_fr）。

工具：
  search_spec_files: 工作区内文本搜索（只读）——编号重排的替换点定位与残留自检；
      字面模式自动加标识符边界（搜 FR-001 不误中 FR-0010），regex=true 原样使用
  parse_fr_id: FR-{功能}-{迭代}-{流水} 注册表锚定解析（specstd.schema.parse_fr_delta_id）
      + 迭代代号文件系统安全底线校验（含 '-' 合法）+ 工作区功能注册表校验（specs/{module}/{feature}/ 二级目录名）；
      编号重排后验证新编号结构合法、功能名已注册、迭代代号安全

只读红线：两工具均无写副作用。
"""

import json
import re
from pathlib import Path

from mcp.types import Tool, TextContent
from mcp_server.tools.tool_meta import ActionMeta, SIDE_DRAFT, consolidate  # T-982

SG_ROOT = Path(__file__).resolve().parent.parent.parent

from specstd.schema import ITER_CODE_RE, FR_DELTA_ID_RE, parse_fr_delta_id  # noqa: E402
from specstd.workspace import get_active_workspace, safe_resolve  # noqa: E402

# 只搜索文本型 spec 文件
_TEXT_EXTS = {".md", ".yaml", ".yml"}
# 命中行返回上限（防大批量结果刷屏；total 仍报告真实总数）
_MAX_HITS = 200

_TOOL_DECLS = [
    Tool(
        name="search_spec_files",
        description="在当前工作区内搜索文本内容（只读），返回命中文件+行号+行文本。"
                    "编号重排动线核心工具：替换前定位全部引用点、替换后自检旧编号残留。"
                    "字面模式自动按标识符边界匹配（搜 FR-001 不会误中 FR-0010）；"
                    "regex=true 时 pattern 按正则原样使用。"
                    "可用 subdir 收窄范围（如 changes/0817、specs）。",
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索内容（字面字符串或正则）"},
                "subdir": {"type": "string",
                           "description": "可选：相对工作区根的子目录（如 changes/0817），缺省搜整个工作区"},
                "regex": {"type": "boolean",
                          "description": "可选：true 时 pattern 按正则使用（不加边界），缺省 false 字面匹配"},
            },
            "required": ["pattern"],
        },
    ),
    Tool(
        name="parse_fr_id",
        description="解析并校验 delta FR 编号（FR-{功能}-{迭代}-{流水}，如 FR-person-profile-0817-001）。"
                    "注册表锚定解析：流水=最右 3 位数字段（右锚）、功能=功能注册表最长匹配"
                    "（specs/{模块}/{功能}/ 目录，左锚）、迭代=中段剩余完全自由（可含 '-' 如"
                    "2026-08-17/sprint-23，仅禁路径字符/空白）；校验功能名已注册、迭代代号安全。"
                    "编号重排后验证新编号结构合法必用；check_iter 参数可单独校验一个迭代代号。",
        inputSchema={
            "type": "object",
            "properties": {
                "fr_id": {"type": "string", "description": "待解析的 FR 编号"},
                "check_iter": {"type": "string",
                               "description": "可选：单独校验一个迭代代号（起草新 delta 前用；可含 '-'）"},
            },
            "required": ["fr_id"],
        },
    ),
]


async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_spec_files":
        return _handle_search(arguments)
    elif name == "parse_fr_id":
        return _handle_parse_fr_id(arguments)
    return []


# ══════════════════════════════════════════════════════════
# search_spec_files
# ══════════════════════════════════════════════════════════

def _build_pattern(pattern: str, use_regex: bool) -> re.Pattern:
    """构造搜索正则。字面模式对首/尾单词字符加标识符边界（`-` 视为标识符字符）。"""
    if use_regex:
        return re.compile(pattern)
    esc = re.escape(pattern)
    if pattern and pattern[0].isalnum():
        esc = r"(?<![\w-])" + esc
    if pattern and (pattern[-1].isalnum()):
        esc = esc + r"(?![\w-])"
    return re.compile(esc)


def _handle_search(arguments: dict) -> list[TextContent]:
    pattern = str(arguments.get("pattern", "") or "")
    subdir = str(arguments.get("subdir", "") or "").strip()
    use_regex = bool(arguments.get("regex", False))

    if not pattern:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": "缺少 pattern 参数"}, ensure_ascii=False))]

    ws = get_active_workspace()
    if not ws:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": "无激活的工作区"}, ensure_ascii=False))]

    if subdir:
        root = safe_resolve(subdir)
        if root is None:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error": f"OUT_OF_SCOPE: 路径越界: {subdir}"}, ensure_ascii=False))]
    else:
        root = ws.root
    if not root.is_dir():
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": f"目录不存在: {subdir or '/'}"}, ensure_ascii=False))]

    try:
        rx = _build_pattern(pattern, use_regex)
    except re.error as e:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": f"正则非法: {e}"}, ensure_ascii=False))]

    hits: list[dict] = []
    total = 0
    truncated = False
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in _TEXT_EXTS:
            continue
        rel = str(f.relative_to(ws.root)).replace("\\", "/")
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for no, line in enumerate(lines, 1):
            matches = rx.findall(line)
            if not matches:
                continue
            total += 1
            if len(hits) < _MAX_HITS:
                hits.append({
                    "path": rel, "line": no,
                    "text": line.strip()[:300],
                    "matches": len(matches),
                })
            else:
                truncated = True

    return [TextContent(type="text", text=json.dumps({
        "ok": True, "pattern": pattern, "subdir": subdir or ".",
        "total": total, "hits": hits,
        **({"truncated": True, "note": f"仅返回前 {_MAX_HITS} 行命中"} if truncated else {}),
    }, ensure_ascii=False, indent=2))]


# ══════════════════════════════════════════════════════════
# parse_fr_id
# ══════════════════════════════════════════════════════════

def _feature_registry(ws_root: Path) -> set[str]:
    """收集工作区功能名注册表（specs/{module}/{feature}/ 的第二级目录名）。"""
    specs = ws_root / "specs"
    features: set[str] = set()
    if not specs.is_dir():
        return features
    for module_dir in sorted(specs.iterdir()):
        if not module_dir.is_dir():
            continue
        for feature_dir in sorted(module_dir.iterdir()):
            if feature_dir.is_dir():
                features.add(feature_dir.name)
    return features


def _handle_parse_fr_id(arguments: dict) -> list[TextContent]:
    fr_id = str(arguments.get("fr_id", "") or "").strip()
    check_iter = str(arguments.get("check_iter", "") or "").strip()
    if not fr_id:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": "缺少 fr_id 参数"}, ensure_ascii=False))]

    ws = get_active_workspace()
    if not ws:
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "error": "无激活的工作区——注册表锚定解析需要功能注册表（specs/{模块}/{功能}/ 目录）"
                     "确定功能边界，请先激活工作区",
        }, ensure_ascii=False, indent=2))]
    features = _feature_registry(ws.root)

    checks: dict = {}
    # 单独校验迭代代号（起草新 delta 前的代号合法性确认）
    if check_iter:
        checks["iter_code_legal"] = bool(ITER_CODE_RE.match(check_iter))
        if not checks["iter_code_legal"]:
            return [TextContent(type="text", text=json.dumps({
                "ok": False, "checks": checks,
                "error": f"迭代代号 '{check_iter}' 非法：禁路径分隔符/空白/Windows 保留字符"
                         "（: * ? \" < > |）且不能以 '.' 开头——迭代名可含 '-'（如 2026-08-17 合法）",
            }, ensure_ascii=False, indent=2))]

    # 基线编号快速识别（FR-001 形态不属于 delta 解析范围）
    if re.fullmatch(r"FR-\d+", fr_id):
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "error": f"'{fr_id}' 是基线编号（FR-{{序号}}），不是 delta 格式 "
                     "FR-{功能}-{迭代}-{流水}；基线编号永久保留、不参与重排",
        }, ensure_ascii=False, indent=2))]

    parsed = parse_fr_delta_id(fr_id, known_features=features)
    if parsed is None:
        # 区分失败原因：形态非法 vs 功能名未注册
        morph = FR_DELTA_ID_RE.match(fr_id)
        if morph is None:
            return [TextContent(type="text", text=json.dumps({
                "ok": False,
                "error": f"'{fr_id}' 不符合 delta 编号形态 FR-{{功能}}-{{迭代}}-{{流水}}"
                         "（流水恒为最右 3 位数字）",
            }, ensure_ascii=False, indent=2))]
        hint = f"当前工作区已注册功能: {', '.join(sorted(features)[:20])}" if features else ""
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "checks": {"format_delta": True, "func_registered": False},
            "error": f"功能名未在当前工作区注册（编号 '{fr_id}' 的功能段需命中 "
                     "specs/{模块}/{功能}/ 目录名，最长匹配）",
            **({"hint": hint} if hint else {}),
        }, ensure_ascii=False, indent=2))]

    checks = {
        "format_delta": True,
        "func_registered": True,
        "iter_code_legal": bool(ITER_CODE_RE.match(parsed["iter"])),
    }
    ok = checks["iter_code_legal"]
    result = {
        "ok": ok,
        "fr_id": fr_id,
        "func": parsed["func"], "iter": parsed["iter"], "seq": parsed["seq"],
        "checks": checks,
    }
    if not checks["iter_code_legal"]:
        result["error"] = (f"迭代代号 '{parsed['iter']}' 非法：禁路径分隔符/空白/Windows 保留字符"
                           "且不能以 '.' 开头——可含 '-'（如 2026-08-17 合法）")
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


# ══════════════════════════════════════════════════════════
# T-982 工具收敛：search/parse_fr 合并为单 spec_search 工具
# ══════════════════════════════════════════════════════════
TOOLS, handle = consolidate(
    "spec_search",
    "工作区 spec 文本搜索与 FR 编号解析校验（编号重排能力：替换点定位/残留自检/新编号合法性）。",
    actions={
        "search": ActionMeta(legacy="search_spec_files"),
        "parse_fr": ActionMeta(legacy="parse_fr_id"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="spec",
    rbac="staff",
)
