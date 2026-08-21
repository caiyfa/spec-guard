"""open/quality_query.py — 测试侧质量读面（M13 §4.5，T-083）。

L0 工具（side_effect 全部 none）：
  get_coverage_gaps  覆盖缺口三态聚合（gap/draft/covered + 优先级排序 + 指纹）
  get_test_debt      测试债清单（缺口 + 未审草稿 + 未闭环 SPQ，确定性派生）
  get_plan_status    计划/批次/DAG 校验状态（读 plans/ YAML + 引擎环检测）
  read_run_report    执行报告查询（映射内部 attribution.read_run_report）

数据源 owner：M07（覆盖缺口）/ M08（计划）/ M09（报告）；本模块只做查询面。
红线：全部纯读；DAG 校验只读引擎环检测（不落盘）；报告读取路径净化。
"""

from __future__ import annotations

import json

from mcp.types import Tool, TextContent

from mcp_server.tools.open import resolve_workspace_root


def _render(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False,
                                                     indent=2, default=str))]


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

get_coverage_gaps_tool = Tool(
    name="get_coverage_gaps",
    description="覆盖缺口三态聚合（M07）：FR 锚点 × 场景 covers × 草稿派生——"
                "gap 无覆盖 / draft 草稿待审 / covered 已覆盖，附优先级排序与指纹。",
    inputSchema={
        "type": "object",
        "properties": {
            "module": {"type": "string", "description": "可选：模块名过滤（如 inventory-session）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
    },
)

get_test_debt_tool = Tool(
    name="get_test_debt",
    description="测试债清单：覆盖缺口（delta 新增 P0 优先）+ 未审草稿 + 未闭环 SPQ，"
                "确定性派生（草稿不计覆盖）。",
    inputSchema={
        "type": "object",
        "properties": {
            "module": {"type": "string", "description": "可选：模块名过滤"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
    },
)

get_plan_status_tool = Tool(
    name="get_plan_status",
    description="计划状态查询（M08 读面）：批次/断点/DAG 环检测/来源 delta。"
                "plan_id 形如 plan#7（或 plan-7）。",
    inputSchema={
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "计划 ID（如 plan#7）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["plan_id"],
    },
)

# read_run_report：映射内部 attribution.read_run_report（M13 §4.5「旧工具直接映射」）——
# 不重复注册 Tool 对象（工具名全局唯一，重复注册会触发 LLM API 400），
# handle 层转发 attribution 实现；open 面语义上可见、注册面上与内部工具同名同源。

TOOLS = [
    get_coverage_gaps_tool,
    get_test_debt_tool,
    get_plan_status_tool,
]


# ══════════════════════════════════════════════════════════
# 工具处理
# ══════════════════════════════════════════════════════════

def _handle_get_coverage_gaps(args: dict) -> list[TextContent]:
    module = str(args.get("module") or "").strip()
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    try:
        from workbench.backend.services import coverage_gaps
        data = coverage_gaps.compute_coverage(module)
    except Exception as e:
        return _render({"ok": False, "error": f"覆盖缺口计算失败: {e}"})
    data["workspace"] = ws_name
    return _render({"ok": True, **data})


def _handle_get_test_debt(args: dict) -> list[TextContent]:
    module = str(args.get("module") or "").strip()
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    try:
        from workbench.backend.services import coverage_gaps
        data = coverage_gaps.compute_coverage(module)
    except Exception as e:
        return _render({"ok": False, "error": f"测试债计算失败: {e}"})

    lanes = data.get("lanes") or {}
    gaps = lanes.get("gap") or []
    drafts = lanes.get("draft") or []

    # 未闭环 SPQ（feedback/ledger.json，纯读）
    open_spq: list[dict] = []
    try:
        import json as _json
        from pathlib import Path as _Path
        from specstd.workspace import SG_ROOT as _sg
        ledger = _Path(_sg) / "feedback" / "ledger.json"
        if ledger.is_file():
            entries = _json.loads(ledger.read_text(encoding="utf-8"))
            for e in entries if isinstance(entries, list) else []:
                if e.get("status") in ("pending", "in_progress"):
                    open_spq.append({
                        "spq_id": e.get("spq_id", ""),
                        "title": (e.get("title") or "")[:120],
                        "scenario_id": e.get("scenario_id", ""),
                    })
    except Exception:
        pass

    items = []
    for g in gaps:
        items.append({"item": g["fr"], "state": "gap",
                      "since": g.get("reason", "history"),
                      "owner_hint": g.get("module", ""),
                      "detail": g.get("name", "")})
    for d in drafts:
        items.append({"item": d["scenario_id"], "state": "draft_unreviewed",
                      "since": d.get("source_delta") or "draft",
                      "owner_hint": d.get("module", ""),
                      "detail": d.get("draft_id", "")})
    for s in open_spq:
        items.append({"item": s["spq_id"], "state": "open_spq",
                      "since": "feedback", "owner_hint": s["scenario_id"],
                      "detail": s["title"]})

    return _render({
        "ok": True,
        "workspace": ws_name,
        "module": module or "all",
        "count": len(items),
        "items": items,
        "coverage_fingerprint": data.get("fingerprint", ""),
    })


def _handle_get_plan_status(args: dict) -> list[TextContent]:
    plan_id = str(args.get("plan_id", "") or "").strip()
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    if not plan_id:
        return _render({"ok": False, "error": "plan_id 必填（如 plan#7）"})

    # plan#7 / plan-7 → plan-7（plan_store 文件名形态）
    norm = plan_id.replace("#", "-")
    try:
        from workbench.backend.services import plan_store
        plan = plan_store.get_plan(norm)
    except Exception as e:
        return _render({"ok": False, "error": f"计划读取失败: {e}"})
    if plan is None:
        return _render({"ok": False, "error": f"计划 {plan_id!r} 不存在",
                        "hint": "计划只能由 delta 导入生成（铁律 6），手工无创建通道"})

    resolved = plan.get("resolved_scenarios") or plan.get("scenarios") or []
    scenario_ids = sorted({s.get("id") if isinstance(s, dict) else str(s)
                           for s in resolved})

    # DAG 环检测：依赖边 {id: 上游集}（引擎单一事实源，纯读）
    # 依赖信息优先读存量图谱节点 attrs（不重建）；图谱不可用时按计划自身字段推断
    dag = {"ok": "no_deps", "cycles": []}
    edges: dict = {}
    try:
        from mcp_server.tools.open import open_graph
        store, _ = open_graph(root)
        if store is not None:
            try:
                for sid in scenario_ids:
                    node = store.get_node(sid)
                    if node is None:
                        continue
                    deps = [d for d in ((node.get("attrs") or {}).get("depends_on") or [])
                            if d in scenario_ids]
                    if deps:
                        edges[sid] = deps
            finally:
                store.close()
    except Exception:
        edges = {}
    if not edges:
        for s in resolved:
            if not isinstance(s, dict):
                continue
            deps = [d.get("id") for d in (s.get("depends_on") or [])
                    if isinstance(d, dict)]
            deps = [d for d in deps if d in scenario_ids]
            if deps:
                edges[s.get("id", "")] = deps
    try:
        if edges:
            from engine.dependency_graph import detect_cycles
            cycles = detect_cycles(edges)
            dag = {"ok": "ok" if not cycles else "cycle",
                   "cycles": [[c] if isinstance(c, str) else c for c in cycles]}
    except Exception as e:
        dag = {"ok": "check_error", "error": str(e)}

    return _render({
        "ok": True,
        "workspace": ws_name,
        "plan_id": plan.get("id", norm),
        "name": plan.get("name", ""),
        "env": plan.get("env", ""),
        "scenario_count": len(scenario_ids),
        "scenarios": scenario_ids,
        "breakpoints": plan.get("breakpoints") or [],
        "batch_layers": plan.get("batches") or [],
        "dag_check": dag,
        "delta_ref": plan.get("source_delta") or plan.get("delta_ref") or "",
    })


def _handle_read_run_report(args: dict) -> list[TextContent]:
    """映射内部 attribution.read_run_report（语义等价，纯读）。"""
    from mcp_server.tools import attribution
    return attribution._handle_read_report(args)


HANDLERS = {
    "get_coverage_gaps": _handle_get_coverage_gaps,
    "get_test_debt": _handle_get_test_debt,
    "get_plan_status": _handle_get_plan_status,
    "read_run_report": _handle_read_run_report,
}


async def handle(name: str, arguments: dict) -> list[TextContent]:
    fn = HANDLERS.get(name)
    if fn is None:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return fn(arguments)


# T-982：工具元数据声明（side_effect/domain/rbac 派生源，见 tool_meta）
from mcp_server.tools.tool_meta import declare, SIDE_DRAFT  # noqa: E402

declare(["get_coverage_gaps", "get_test_debt", "get_plan_status"], domain="open")
