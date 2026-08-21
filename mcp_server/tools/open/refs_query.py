"""open/refs_query.py — 外部锚点反查只读面（M13 §4.5，T-083）。

L0 工具（side_effect 全部 none）：
  lookup_external_ref   ZT-STORY / ZT-BUG 反查：spec 锚点 / 验证状态 / 血缘提示

数据源 owner：M06 sf_external_refs（同表同源，不另建副本）；谱系提示读 graph_index 存量索引。
红线：禅道写不开放（「外部写不进 MCP」通则）——本模块只读登记，不触外部系统。
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

lookup_external_ref_tool = Tool(
    name="lookup_external_ref",
    description="外部锚点反查（M06）：ZT-STORY-xxx / ZT-BUG-xxx 在 SpecGuard 的登记行——"
                "关联的 spec 锚点（FR/delta）、验证状态（关联场景执行）、血缘提示。",
    inputSchema={
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "外部编号（如 ZT-STORY-4821 / ZT-BUG-9917）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["ref"],
    },
)

TOOLS = [lookup_external_ref_tool]


# ══════════════════════════════════════════════════════════
# 工具处理
# ══════════════════════════════════════════════════════════

def _handle_lookup_external_ref(args: dict) -> list[TextContent]:
    ref = str(args.get("ref") or "").strip()
    if not ref:
        return _render({"ok": False, "error": "ref 必填（如 ZT-STORY-4821）"})
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})

    from workbench.backend.services.specflow import sf_refs_store

    # 前缀补全尝试：ZT-STORY-4821 与 4821 两种形态
    candidates = [ref]
    upper = ref.upper()
    for prefix, typ in (("ZT-STORY-", "zt_story"), ("ZT-BUG-", "zt_bug"),
                        ("ZT-TASK-", "zt_task")):
        if upper.startswith(prefix):
            candidates.append(ref[len(prefix):])
        else:
            candidates.append(f"{prefix}{ref}")
    rows = []
    seen: set = set()
    for cand in candidates:
        for r in sf_refs_store.list_refs(workspace=ws_name, ref=cand):
            key = (r.get("type"), r.get("ref"), r.get("linked_type"), r.get("linked"))
            if key not in seen:
                seen.add(key)
                rows.append(r)

    if not rows:
        return _render({"ok": False, "error": f"外部锚点 {ref!r} 未登记（sf_external_refs 无记录）",
                        "hint": "锚点由禅道建故事/提 BUG 作业自动登记；未登记 = SpecGuard 尚未挂链"})

    # 血缘提示（只读存量索引；stale 时诚实标记）
    lineage_hint = {"available": False, "reason": ""}
    store = None
    try:
        store, st = open_graph(root)
        if store is not None:
            node_id = f"{(rows[0].get('type') or '')}:{rows[0].get('ref')}"
            node = store.get_node(node_id)
            lineage_hint = {
                "available": True,
                "node_id": node_id,
                "in_graph": node is not None,
                "index_stale": st.get("stale", False),
            }
            if node is not None:
                from graph_index.service import trace
                try:
                    t = trace(store, node_id, direction="both", max_depth=6)
                    lineage_hint["path"] = [{"id": p["id"], "type": p["type"],
                                             "title": p["title"]} for p in t["path"]]
                except KeyError:
                    lineage_hint["path"] = []
    except Exception as e:
        lineage_hint = {"available": False, "reason": f"图谱提示不可用: {e}"}
    finally:
        if store is not None:
            store.close()

    # 验证状态：linked 场景的最近执行（只读台账）
    verify_status = {"linked": [], "latest_runs": []}
    for r in rows:
        item = {"linked_type": r.get("linked_type"), "linked": r.get("linked")}
        if r.get("linked_type") == "fr_anchor":
            item["spec_anchor"] = r.get("linked")
        elif r.get("linked_type") == "delta":
            item["spec_anchor"] = f"delta:{r.get('linked')}"
        elif r.get("linked_type") == "scenario":
            item["spec_anchor"] = ""
        verify_status["linked"].append(item)
    # 关联场景的最近执行（failures/executions 台账，读不到静默）
    try:
        from mcp_server.tools.attribution import _get_reports_root
        from sg_core import execution_index
        for r in rows:
            if r.get("linked_type") != "scenario":
                continue
            runs = execution_index.query_executions(
                _get_reports_root(), r.get("linked"), "", "", 3)
            verify_status["latest_runs"].extend(
                {"scenario_id": r.get("linked"),
                 "run_id": x.get("run_id"), "verdict": x.get("verdict"),
                 "finished_at": x.get("finished_at")} for x in runs)
    except Exception:
        pass

    return _render({
        "ok": True,
        "workspace": ws_name,
        "ref": ref,
        "count": len(rows),
        "refs": [{k: r.get(k) for k in ("type", "ref", "ref_url", "linked_type",
                                        "linked", "note", "registered_by", "created_at")}
                 for r in rows],
        "spec_anchor": verify_status["linked"],
        "verify_status": verify_status,
        "lineage_hint": lineage_hint,
        "note": "本模块只读登记；禅道写（建故事/提 BUG）不经 MCP 暴露（外部写不进 MCP 通则）",
    })


HANDLERS = {
    "lookup_external_ref": _handle_lookup_external_ref,
}


async def handle(name: str, arguments: dict) -> list[TextContent]:
    fn = HANDLERS.get(name)
    if fn is None:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return fn(arguments)


# T-982：工具元数据声明（side_effect/domain/rbac 派生源，见 tool_meta）
from mcp_server.tools.tool_meta import declare, SIDE_DRAFT  # noqa: E402

declare("lookup_external_ref", domain="open")
