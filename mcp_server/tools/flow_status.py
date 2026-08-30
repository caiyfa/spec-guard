"""flow_status — golden flow 路径自检工具（T-1042 三期阶段 2，meta 域常驻纯读）。

agent 在对话内自查进度：当前会话实际走径 vs golden flow 基线（阶段四态 +
跑偏点 + 计划外旁支）——「图在看、提示不打断」的 agent 侧自助入口
（用户侧是 🧭 路径面板，agent 侧是本工具；判定同源 evals.flowpath）。

数据源：当前会话 JSONL（runtime 每轮增量落盘；本工具读到的路径截至上一轮，
进行中轮次的调用在其结果落盘后可见）。
无会话上下文（MCP stdio 直连）/会话未落盘/evals 依赖缺失 → 诚实降级提示，
不猜不炸。设计：docs/superpowers/specs/2026-08-30-Agent路径自检与纠正提示-design.md。

domain=meta：resolve_tools 对 meta 域无条件入白名单（与 topic/gate_dock_status
同槽），全 purpose 会话常驻可见，不挤 ≤15 名额；纯读 side_effect 自动 product 可见。
"""

from __future__ import annotations

from mcp.types import TextContent, Tool

_TOOL_DECLS = [
    Tool(
        name="flow_status",
        description=(
            "路径自检（纯读）：golden flow 基线（generate-scenario 技能流程）与"
            "当前会话实际走径的逐节点比对——各阶段 顺序正确/乱序/缺失/跳过、"
            "跑偏点（带步号证据）、计划外旁支。生成场景任务中可随时调用自查"
            "是否跑偏；反映到上一轮落盘为止。"
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]


async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    if name != "flow_status":
        raise ValueError(f"未知工具: {name}")
    return [TextContent(type="text", text=_flow_status_text())]


def _flow_status_text() -> str:
    from sg_core.session_context import current_session_id, get_runtime_scope

    sid = current_session_id()
    if not sid:
        return ("当前不在会话上下文（MCP stdio 直连/无会话），无路径可重放——"
                "flow 自检仅在工作台/CLI 会话内可用。")
    scope = get_runtime_scope() or {}
    sessions_dir = scope.get("sessions_dir", "")
    if not sessions_dir:
        return "会话运行时作用域缺失（sessions_dir 未知），无法定位会话文件。"
    from pathlib import Path

    path = Path(sessions_dir) / f"{sid}.jsonl"
    if not path.exists():
        return (f"会话 {sid} 尚未落盘（首轮进行中），暂无路径可重放——"
                "下轮再调即可看到已保存轮次的路径比对。")
    try:
        import json as _json

        rows = [_json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError):
        return f"会话文件解析失败: {sid}——跳过自检，不阻塞任务。"
    try:
        from evals.baseline import scan_rows
        from evals.flowpath import trace_scan
    except Exception as e:  # 评测依赖缺失 → 诚实降级（懒加载，零模块级回边）
        return f"路径重放组件不可用（{e}），跳过自检——不影响当前任务。"

    scan = scan_rows(rows, session_id=sid)
    trace = trace_scan(scan)
    _GLYPH = {"in_order": "✓顺序正确", "out_of_order": "⇄乱序", "missing": "✗缺失",
              "skipped": "－跳过(可选)"}
    lines = [
        f"[flow 自检] golden flow「{trace.flow_title}」vs 当前会话实际走径"
        f"（截至上一轮落盘，共 {trace.n_tool_calls} 步工具调用）：",
        "",
    ]
    for i, s in enumerate(trace.stages, start=1):
        ev = f"第{s.first_step}步×{s.times}" if s.first_step else ("未调用" if s.required else "—")
        lines.append(f"  {i}. {s.label}：{_GLYPH[s.status]}（{ev}）")
    if trace.deviations:
        lines += ["", "跑偏点："] + [f"  ⚠ {d}" for d in trace.deviations]
    else:
        lines += ["", "无跑偏：全部必需阶段按基线顺序走完。"]
    if trace.extras:
        lines += ["", f"计划外旁支：{'、'.join(trace.extras)}（旁支不等于违规，benign 元工具已剔除）"]
    lines += ["", "（本自检仅供参考；如属用户明确要求的路径，向用户说明即可，无需强行对齐基线。）"]
    return "\n".join(lines)


# T-982：action 参数化合并（元数据单一事实源；domain=meta 全用途常驻）
from mcp_server.tools.tool_meta import ActionMeta, consolidate  # noqa: E402

TOOLS, handle = consolidate(
    "flow",
    "路径自检（纯读）：golden flow 基线（generate-scenario 技能流程）与当前会话"
    "实际走径的逐节点比对——各阶段四态、跑偏点带步号证据、计划外旁支。生成场景"
    "任务中可随时调用自查是否跑偏；无会话上下文时诚实提示。",
    actions={
        "status": ActionMeta(legacy="flow_status"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="meta",
)
