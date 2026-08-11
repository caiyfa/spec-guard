"""graph_index.py — 图谱查询 MCP 工具（M11 §5.2，T-070）。

工具：
  graph_query      图谱查询（L0/L1/L2 三层语义缩放 + 节点详情）；纯读
  graph_backlink   计算型反向链接查询；纯读
  graph_rebuild    触发索引重建（写索引库，不动任何源数据）
  graph_snapshot   打里程碑快照（写 .specflow/graph_snapshots/，三自动触发点之外的手动补充）
  graph_diff       两档快照演化 diff（纯读）
  lineage_trace    血缘链追溯（Q1 向上/Q2 向下，审计动线）；纯读
  lineage_check    断链校验（BL 规则集 WARNING 清单）；纯读（rebuild 只重写缓存）

约束：graph_query / graph_backlink 校验类工具必须纯读，禁止副作用；
graph_rebuild 只写派生物（graph_index.db），红线：绝不回写 spec/场景/台账。
"""

from __future__ import annotations

from mcp.types import Tool, TextContent

# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

graph_query_tool = Tool(
    name="graph_query",
    description="图谱查询：L0 模块星座图 / L1 功能点视图（健康分+覆盖缺口）/ L2 FR 邻域"
                "（FR 圆+场景方块+covers 边），或按 node_id 查节点详情。"
                "查询前自动做指纹保鲜（源数据变更时重建索引，对调用方透明）。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["L0", "L1", "L2"],
                      "description": "查询层级（node_id 存在时忽略）"},
            "module": {"type": "string", "description": "L1 查询的模块名（如 system-settings）"},
            "feature": {"type": "string", "description": "L2 查询的功能点（如 inventory/grid-placement）"},
            "node_id": {"type": "string", "description": "节点 ID（FR-012 / PP-RC-005 / SPQ-xxx）"},
        },
    },
)

graph_backlink_tool = Tool(
    name="graph_backlink",
    description="计算型反向链接：点 FR 查「哪些场景覆盖我 / 哪些 delta 改过我 / 哪些决策引用我」。"
                "边一律从源数据确定性派生，无手工标注。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "节点 ID（FR-xxx 等）"},
        },
        "required": ["node_id"],
    },
)

graph_rebuild_tool = Tool(
    name="graph_rebuild",
    description="强制重建图谱索引（幂等）：重新解析 specs/场景/台账等源数据，"
                "重建 nodes/edges 并刷新源数据聚合指纹。只写派生物 graph_index.db，"
                "绝不触碰任何源文件（红线：图谱是派生物不是事实源）。",
    inputSchema={
        "type": "object",
        "properties": {},
    },
)

graph_snapshot_tool = Tool(
    name="graph_snapshot",
    description="打里程碑快照：从当前索引导出节点/边集 + 源数据指纹，落"
                ".specflow/graph_snapshots/（版本化保留，可凭指纹重建校验）。"
                "三自动触发点（delta 冻结/归档/计划完成）之外的手动补充。",
    inputSchema={
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "快照标签（如 es-acceleration 归档）"},
            "trigger": {"type": "string", "enum": ["delta_frozen", "delta_archived", "plan_completed", "manual"],
                        "description": "触发点（默认 manual）"},
        },
    },
)

graph_diff_tool = Tool(
    name="graph_diff",
    description="两档快照演化 diff：+新增/-移除/~修改 计数 + per_module 聚合 + 两侧指纹。"
                "确定性比对，纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "from": {"type": "string", "description": "起始快照 ID（snap_xxx）"},
            "to": {"type": "string", "description": "终止快照 ID 或 current（默认 current 当前索引）"},
        },
        "required": ["from"],
    },
)

lineage_trace_tool = Tool(
    name="lineage_trace",
    description="血缘链追溯（M10 审计 Q1/Q2）：Q1「这个场景为什么存在」向上追到面试/决策；"
                "Q2「这个需求被验证了吗」向下追到场景/计划/报告/SPQ。"
                "确定性图遍历（不走 LLM），外部锚点标记 external 供虚线渲染。纯读。",
    inputSchema={
        "type": "object",
        "properties": {
            "node": {"type": "string", "description": "起始节点 ID（如 PP-RC-005 / FR-012）"},
            "dir": {"type": "string", "enum": ["up", "down", "both"],
                    "description": "追溯方向：up=向上（场景为什么存在）/ down=向下（需求被验证了吗）"},
            "max_depth": {"type": "integer", "description": "最大深度（默认 8，上限 16）"},
        },
        "required": ["node"],
    },
)

lineage_check_tool = Tool(
    name="lineage_check",
    description="断链确定性校验（T-074，BL-01~BL-06）：产物落笔即挂链纪律的 WARNING 清单——"
                "场景缺 covers/source_delta、delta 缺决策来源、FR 双侧断链、SPQ 无回溯、"
                "外部锚点未挂链。纯图遍历 + 规则集匹配，不走 LLM。",
    inputSchema={
        "type": "object",
        "properties": {
            "rebuild": {"type": "boolean",
                         "description": "true=重跑校验并刷新缓存（只写 .specguard/lineage_check.json 派生物）"},
        },
    },
)

TOOLS = [graph_query_tool, graph_backlink_tool, graph_rebuild_tool,
         graph_snapshot_tool, graph_diff_tool, lineage_trace_tool,
         lineage_check_tool]


# ══════════════════════════════════════════════════════════
# 分发
# ══════════════════════════════════════════════════════════

def _workspace_root():
    """解析当前有效工作区根（SG_WORKSPACE 环境变量 / 注册表 active）。"""
    from specstd.workspace import get_active_workspace
    ws = get_active_workspace()
    if not ws:
        raise RuntimeError("无激活工作区：请先注册并激活工作区（或设置 SG_WORKSPACE）")
    return ws.root


async def handle(name: str, arguments: dict) -> list[TextContent]:
    arguments = arguments or {}
    try:
        if name == "graph_query":
            return _do_query(arguments)
        if name == "graph_backlink":
            return _do_backlink(arguments)
        if name == "graph_rebuild":
            return _do_rebuild()
        if name == "graph_snapshot":
            return _do_snapshot(arguments)
        if name == "graph_diff":
            return _do_diff(arguments)
        if name == "lineage_trace":
            return _do_lineage_trace(arguments)
        if name == "lineage_check":
            return _do_lineage_check(arguments)
        return [TextContent(type="text", text=f"未知工具: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"graph_index 工具错误: {type(e).__name__}: {e}")]


def _do_query(arguments: dict) -> list[TextContent]:
    from graph_index import service
    workspace_root = _workspace_root()
    data = service.query(
        workspace_root,
        level=str(arguments.get("level") or "L0"),
        module=str(arguments.get("module") or ""),
        feature=str(arguments.get("feature") or ""),
        node_id=str(arguments.get("node_id") or ""),
    )
    return [TextContent(type="text", text=_render(data))]


def _do_backlink(arguments: dict) -> list[TextContent]:
    from graph_index import service
    workspace_root = _workspace_root()
    service.ensure_fresh(workspace_root)
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    with GraphStore(index_path(workspace_root)) as store:
        data = service.backlink(store, str(arguments.get("node_id") or ""))
    return [TextContent(type="text", text=_render(data))]


def _do_rebuild() -> list[TextContent]:
    from graph_index import service
    workspace_root = _workspace_root()
    result = service.rebuild(workspace_root)
    return [TextContent(type="text", text=_render(result))]


def _do_snapshot(arguments: dict) -> list[TextContent]:
    from graph_index import snapshot
    workspace_root = _workspace_root()
    result = snapshot.create_snapshot(
        workspace_root,
        label=str(arguments.get("label") or ""),
        trigger=str(arguments.get("trigger") or "manual"),
    )
    return [TextContent(type="text", text=_render(result))]


def _do_diff(arguments: dict) -> list[TextContent]:
    from graph_index import snapshot
    workspace_root = _workspace_root()
    result = snapshot.diff_snapshots(
        workspace_root,
        from_snapshot=str(arguments.get("from") or ""),
        to_snapshot=str(arguments.get("to") or "current"),
    )
    return [TextContent(type="text", text=_render(result))]


def _do_lineage_trace(arguments: dict) -> list[TextContent]:
    from graph_index import service
    workspace_root = _workspace_root()
    service.ensure_fresh(workspace_root)
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    try:
        with GraphStore(index_path(workspace_root)) as store:
            data = service.trace(
                store,
                str(arguments.get("node") or ""),
                direction=str(arguments.get("dir") or "up"),
                max_depth=int(arguments.get("max_depth") or 8),
            )
    except KeyError as e:
        return [TextContent(type="text", text=f"节点不存在: {e}")]
    return [TextContent(type="text", text=_render(data))]


def _do_lineage_check(arguments: dict) -> list[TextContent]:
    from graph_index import service
    from specflow.lineage import lineage_check
    workspace_root = _workspace_root()
    service.ensure_fresh(workspace_root)
    rebuild = bool(arguments.get("rebuild"))
    try:
        if rebuild:
            data = lineage_check.run_checks(workspace_root)
        else:
            data = lineage_check.load_check_output(workspace_root)
            if data is None:
                data = lineage_check.run_checks(workspace_root, write_output=False)
    except FileNotFoundError as e:
        return [TextContent(type="text", text=f"索引未构建: {e}")]
    return [TextContent(type="text", text=_render(data))]


def _render(data) -> str:
    import json
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
