"""lineage.py — 血缘链 REST API（M10 §5.1，T-073）。

前缀 /api/lineage，挂 RBAC，全角色可看（审计追溯为只读操作）。
- trace：Q1 向上 / Q2 向下谱系投影（确定性图遍历，不走 LLM）
- node：节点详情 + 一阶邻域

红线：血缘链全链路只读——本路由任何操作序列不改变 spec.md、场景 YAML、
台账、sf_external_refs 的任何字节。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, resolve_workspace

router = APIRouter(prefix="/api/lineage", tags=["lineage"],
                   dependencies=[Depends(get_current_user)])


def _workspace_root(workspace: str):
    from specstd.workspace import get_workspace_root
    root = get_workspace_root(workspace)
    if root is None:
        raise HTTPException(status_code=404, detail=f"工作区不存在或未激活: {workspace!r}")
    return root


@router.get("/trace")
def lineage_trace(
    node: str,
    dir: str = "up",
    max_depth: int = 8,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """谱系投影：Q1「场景为什么存在」（up）/ Q2「需求被验证了吗」（down）。"""
    from graph_index import service
    root = _workspace_root(workspace)
    service.ensure_fresh(root)
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    try:
        with GraphStore(index_path(root)) as store:
            return service.trace(store, node, direction=dir, max_depth=max_depth)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/check")
def lineage_check_get(
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """断链校验结果（读缓存 .specguard/lineage_check.json；无缓存 404）。"""
    from specflow.lineage import lineage_check
    root = _workspace_root(workspace)
    data = lineage_check.load_check_output(root)
    if data is None:
        raise HTTPException(status_code=404,
                            detail="断链校验未执行过：请先 POST /api/lineage/check 触发重跑")
    return data


@router.post("/check")
def lineage_check_run(
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """触发断链校验（确定性，幂等；结果落派生物缓存，不触碰任何源数据）。"""
    from graph_index import service
    from specflow.lineage import lineage_check
    root = _workspace_root(workspace)
    service.ensure_fresh(root)
    try:
        return lineage_check.run_checks(root)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/node/{node_id}")
def lineage_node(
    node_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """节点详情 + 一阶邻域（上游血缘列表）。"""
    from graph_index import service
    root = _workspace_root(workspace)
    service.ensure_fresh(root)
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    with GraphStore(index_path(root)) as store:
        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")
        edges = store.list_edges_by_node(node_id)
        return {
            "node": node,
            "upstream": sorted({e["src"] for e in edges
                                if e["edge_type"] in ("covers", "contains", "produces",
                                                      "decides", "references", "schedules",
                                                      "executes", "feedback")
                                and e["dst"] == node_id}),
            "edges": edges,
        }
