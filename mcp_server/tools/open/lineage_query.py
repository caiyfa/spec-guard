"""open/lineage_query.py — 血缘链与图谱只读面（M13 §4.5，T-083）。

L0 工具（side_effect 全部 none）：
  trace_forward    Q1 向下游追：从 FR/外部锚点 → 场景 → 计划 → 执行报告（验证了吗）
  trace_backward   Q2 向上游追：从场景/问题 → delta → 决策 → 面试（为什么存在）
  query_graph      图谱节点/边/backlink 查询（L0/L1/L2 缩放，edge_type 过滤）

数据源 owner：M10（谱系口径）/ M11（图谱索引）；本模块只读存量索引。
红线：不调 ensure_fresh/rebuild——索引构建是 L2 不开放能力；stale 时诚实标记。
"""

from __future__ import annotations

import json

from mcp.types import Tool, TextContent

from mcp_server.tools.open import resolve_workspace_root, open_graph


def _render(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False,
                                                     indent=2, default=str))]


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

trace_forward_tool = Tool(
    name="trace_forward",
    description="血缘链 Q1 向下游追：从 FR 锚点/外部锚点（ZT-STORY-xxx）/场景 ID 出发，"
                "沿谱系流找「这个需求被哪些场景、计划、执行报告验证过」。",
    inputSchema={
        "type": "object",
        "properties": {
            "ref": {"type": "string",
                    "description": "起点：FR-xxx / AC-xxx / 场景 ID / ZT-STORY-xxx / EX-xxx"},
            "max_depth": {"type": "integer", "description": "追溯深度（默认 8，最大 16）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["ref"],
    },
)

trace_backward_tool = Tool(
    name="trace_backward",
    description="血缘链 Q2 向上游追：从场景 ID / 问题（ZT-BUG-xxx）/ SPQ 出发，"
                "沿谱系流找「为什么存在」——上游决策链、来源 delta、面试。",
    inputSchema={
        "type": "object",
        "properties": {
            "ref": {"type": "string",
                    "description": "起点：场景 ID / ZT-BUG-xxx / SPQ-xxx / FR-xxx"},
            "max_depth": {"type": "integer", "description": "追溯深度（默认 8，最大 16）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["ref"],
    },
)

query_graph_tool = Tool(
    name="query_graph",
    description="图谱查询（M11 读面）：L0 模块星座 / L1 功能点健康 / L2 FR 邻域，"
                "或按 node_id 查单节点 + backlink；edge_type 过滤边。",
    inputSchema={
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "可选：单节点查询（FR-xxx/场景 ID/D-xxx）"},
            "edge_type": {"type": "string",
                          "description": "可选：边类型过滤（covers/depends_on/decides/references 等）"},
            "zoom": {"type": "string", "enum": ["L0", "L1", "L2"],
                     "description": "缩放层级（默认 L0；node_id 时忽略）"},
            "module": {"type": "string", "description": "L1/L2 所需模块名"},
            "feature": {"type": "string", "description": "L2 所需功能点"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
    },
)

TOOLS = [trace_forward_tool, trace_backward_tool, query_graph_tool]


# ══════════════════════════════════════════════════════════
# 只读辅助
# ══════════════════════════════════════════════════════════

def _normalize_node_id(ref: str) -> str:
    """ref 归一化为图谱节点 ID（宽容匹配外部锚点/run/plan 前缀形态）。"""
    r = (ref or "").strip()
    if not r:
        return r
    # 外部锚点：ZT-STORY-4821 → zt_story:ZT-STORY-4821
    upper = r.upper()
    for prefix, typ in (("ZT-STORY-", "zt_story"), ("ZT-BUG-", "zt_bug"),
                        ("ZT-TASK-", "zt_task")):
        if upper.startswith(prefix):
            return f"{typ}:{r}"
    # run/plan 前缀形态
    if upper.startswith("EX-") and not r.startswith("run:"):
        return f"run:{r}"
    return r


def _open_store(args: dict):
    """打开只读图谱，返回 (store, status, ws_name)；不可用返回 (None, status, "")。"""
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return None, {"ok": False, "error": "工作区不可用（未激活或不存在）"}, ""
    store, st = open_graph(root)
    if store is None:
        return None, {"ok": False, "error": st.get("reason", "图谱索引不可用"),
                      "stale": st.get("stale", False)}, ws_name
    return store, {"ok": True, "stale": st.get("stale", False),
                   "built_at": st.get("built_at")}, ws_name


def _do_trace(args: dict, direction: str) -> list[TextContent]:
    ref = str(args.get("ref") or "").strip()
    if not ref:
        return _render({"ok": False, "error": "ref 必填"})
    store, status, ws_name = _open_store(args)
    if store is None:
        return _render(status)
    node_id = _normalize_node_id(ref)
    try:
        from graph_index.service import trace
        data = trace(store, node_id, direction=direction,
                     max_depth=int(args.get("max_depth") or 8))
    except KeyError as e:
        return _render({"ok": False, "error": f"节点不存在: {e}",
                        "hint": f"可尝试 FR-xxx / ZT-STORY-xxx / 场景 ID / EX-xxx（ref={ref!r}）"})
    finally:
        store.close()
    return _render({"ok": True, "workspace": ws_name, "ref": ref,
                    "node_id": node_id, "direction": direction,
                    "index_stale": status.get("stale", False), **data})


def _handle_trace_forward(args: dict) -> list[TextContent]:
    return _do_trace(args, "down")


def _handle_trace_backward(args: dict) -> list[TextContent]:
    return _do_trace(args, "up")


def _handle_query_graph(args: dict) -> list[TextContent]:
    node_id = str(args.get("node_id") or "").strip()
    edge_type = str(args.get("edge_type") or "").strip()
    zoom = str(args.get("zoom") or "L0").upper()
    module = str(args.get("module") or "").strip()
    feature = str(args.get("feature") or "").strip()

    store, status, ws_name = _open_store(args)
    if store is None:
        return _render(status)
    try:
        # 只读视图函数（不调 service.query——其内部 ensure_fresh 会重建索引，
        # 索引构建是 L2 不开放能力，open/ 面禁止触发写）
        from graph_index.service import backlink, panorama_l0, panorama_l1, panorama_l2
        if node_id:
            nid = _normalize_node_id(node_id)
            node = store.get_node(nid)
            if node is None:
                return _render({"ok": False, "error": f"节点不存在: {nid}",
                                "hint": "可尝试 FR-xxx / 场景 ID / D-xxx / ZT-STORY-xxx"})
            bl = backlink(store, nid)
            if edge_type:
                bl = {k: v for k, v in bl.items()
                      if k == edge_type or edge_type in v}
            return _render({"ok": True, "workspace": ws_name,
                            "index_stale": status.get("stale", False),
                            "node": {k: node.get(k) for k in
                                     ("id", "node_type", "stage", "title",
                                      "module", "feature", "attrs", "source_ref")},
                            "backlink": bl})
        if zoom not in ("L0", "L1", "L2"):
            return _render({"ok": False, "error": f"非法 zoom: {zoom!r}（允许 L0/L1/L2）"})
        if zoom == "L0":
            data = panorama_l0(store)
        elif zoom == "L1":
            data = panorama_l1(store, module)
        else:
            data = panorama_l2(store, module, feature)
        # edge_type 过滤（L2 场景边 + L0 模块边）
        if edge_type and isinstance(data, dict):
            for key in ("l0edges", "frEdges", "edges"):
                if isinstance(data.get(key), list):
                    data[key] = [e for e in data[key]
                                 if e.get("type") == edge_type or e.get("edge_type") == edge_type]
        return _render({"ok": True, "workspace": ws_name,
                        "index_stale": status.get("stale", False),
                        "zoom": zoom, **data})
    finally:
        store.close()


HANDLERS = {
    "trace_forward": _handle_trace_forward,
    "trace_backward": _handle_trace_backward,
    "query_graph": _handle_query_graph,
}


async def handle(name: str, arguments: dict) -> list[TextContent]:
    fn = HANDLERS.get(name)
    if fn is None:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return fn(arguments)
