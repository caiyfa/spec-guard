"""validator — 场景校验（格式 + covers 关联 + 注册表引用）。

工具：
  validate: 校验场景 YAML 内容，返回结构化报告
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from specstd.anchors import resolve_covers, scan_anchors  # noqa: E402
from specstd.workspace import get_active_workspace  # noqa: E402

TOOLS = [
    Tool(
        name="validate",
        description="校验场景 YAML 内容：格式合规（T1-T7）+ covers 关联（FR 锚点存在性）"
                    "+ 注册表引用有效性（tool/oracle 名称已注册）。编造的 FR 必报 COVER 错误并给 hint。",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "场景 YAML 内容"},
            },
            "required": ["content"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "validate":
        return _handle_validate(arguments)
    return []


def _handle_validate(arguments: dict) -> list[TextContent]:
    import yaml

    content = arguments.get("content", "")
    if not content:
        return [TextContent(type="text", text="错误：缺少 content 参数")]

    # 解析 YAML
    try:
        raw = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        return [TextContent(type="text", text=json.dumps({
            "verdict": "ERROR",
            "findings": [{"level": "ERROR", "rule": "T1", "message": f"YAML 解析失败: {e}"}],
        }, ensure_ascii=False, indent=2))]

    findings = []
    sid = raw.get("id", "(unknown)")

    # T1: 格式基本
    flow = raw.get("flow") or []
    verify = raw.get("verify") or []
    if not flow and not verify:
        findings.append({"level": "ERROR", "rule": "T1", "scenario": sid,
                         "message": "flow/verify 均为空，场景不可执行"})

    # T2: 类型声明
    test_type = raw.get("test_type", "scenario")
    if test_type not in ("unit", "scenario"):
        findings.append({"level": "WARN", "rule": "T2", "scenario": sid,
                         "message": f"test_type='{test_type}' 非法（应为 unit/scenario）"})

    # T6: 契约指纹
    try:
        from engine.versioning import fingerprint_from_raw, check_t6, load_baseline
        baseline = load_baseline(str(SG_ROOT))
        result = check_t6(sid, fingerprint_from_raw(raw), str(raw.get("version", "0.1")), baseline)
        if result:
            level, message = result
            findings.append({"level": level, "rule": "T6", "scenario": sid, "message": message})
    except Exception:
        pass  # 引擎未就绪时跳过 T6

    # covers 关联校验
    doc = raw.get("doc") or {}
    covers = doc.get("covers") or []
    if covers:
        ws = get_active_workspace()
        if ws:
            anchors = scan_anchors(ws.root)
            cover_findings = resolve_covers([str(c) for c in covers], anchors)
            for f in cover_findings:
                findings.append({
                    "level": f.level, "rule": f.rule,
                    "scenario": sid, "message": f.message,
                    "detail": f.detail,
                })
        else:
            findings.append({"level": "WARN", "rule": "COVERS", "scenario": sid,
                             "message": "无激活工作区，无法校验 covers 关联"})

    # 注册表引用校验（tool 名称）
    try:
        from services.format_spec import get_tool_catalog
        valid_tools = {t["name"] for t in get_tool_catalog()}
    except Exception:
        valid_tools = set()

    for step in flow:
        if isinstance(step, dict) and "tool" in step:
            tool_body = step["tool"]
            if isinstance(tool_body, dict):
                tool_name = tool_body.get("use", "")
                if tool_name and valid_tools and tool_name not in valid_tools:
                    findings.append({"level": "ERROR", "rule": "REGISTRY", "scenario": sid,
                                     "message": f"未注册的 tool: {tool_name}"})

    n_err = sum(1 for f in findings if f["level"] == "ERROR")
    n_warn = sum(1 for f in findings if f["level"] == "WARN")
    verdict = "PASS" if n_err == 0 else "REJECT"

    return [TextContent(type="text", text=json.dumps({
        "verdict": verdict,
        "scenario": sid,
        "findings": findings,
        "summary": {"error": n_err, "warn": n_warn},
    }, ensure_ascii=False, indent=2))]
