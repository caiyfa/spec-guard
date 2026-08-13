"""graph.py — 全景图谱 REST API（M11 §5.1，T-070）。

前缀 /api/graph，挂 RBAC。
- panorama / backlink / status：纯读，全角色可看
- rebuild：写索引库（派生物），限 admin/tester

红线：图谱视图只读，修改永远回源系统；本路由任何端点不触碰 specs/场景/台账。
"""

from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/graph", tags=["graph"],
                   dependencies=[Depends(get_current_user)])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# 源头文件受控前缀（v1.19）：工作区根内 specs|changes|.specguard|.specflow + 仓库根 scenarios|feedback


def _workspace_root(workspace: str):
    """按 X-SG-Workspace 解析工作区根（无激活工作区 → 404）。"""
    from specstd.workspace import get_workspace_root
    root = get_workspace_root(workspace)
    if root is None:
        raise HTTPException(status_code=404, detail=f"工作区不存在或未激活: {workspace!r}")
    return root


@router.get("/status")
def graph_status(
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """索引状态：{fingerprint, source_fingerprint, stale, built_at}。"""
    from graph_index import service
    root = _workspace_root(workspace)
    st = service.status(root)
    if st["stale"] and st["built_at"] is None:
        st["built_at"] = None
    return st


@router.get("/panorama")
def panorama_l0(
    level: str = "L0",
    lens: str = "map",
    era: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """L0 系统星座图（模块节点 + 耦合边 + 镜头着色属性）。

    lens=network（飞书知识图谱一期 T-915）：网状镜头全量节点+边投影
    （>500 节点护栏只回模块聚合）。纯读，全角色可看。
    """
    from graph_index import service
    root = _workspace_root(workspace)
    if level.upper() != "L0":
        raise HTTPException(status_code=400, detail="L0 端点仅支持 level=L0")
    if lens == "network":
        service.ensure_fresh(root)
        from graph_index.service import index_path
        from graph_index.store import GraphStore
        with GraphStore(index_path(root)) as store:
            return service.network_view(store)
    data = service.query(root, level="L0")
    data["lens"] = lens
    data["era"] = era or "current"
    return data


@router.get("/panorama/{module}")
def panorama_l1(
    module: str,
    lens: str = "map",
    era: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """L1 功能点视图（环形布局：health + nCov/nGap）。"""
    from graph_index import service
    root = _workspace_root(workspace)
    data = service.query(root, level="L1", module=module)
    data["lens"] = lens
    data["era"] = era or "current"
    return data


@router.get("/panorama/{module}/{feature}")
def panorama_l2(
    module: str,
    feature: str,
    era: str = "",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """L2 FR 邻域（FR 圆 + 场景方块 + covers 边 + backlink 数据）。"""
    from graph_index import service
    root = _workspace_root(workspace)
    data = service.query(root, level="L2", module=module, feature=feature)
    data["era"] = era or "current"
    return data


@router.get("/backlink/{node_id}")
def graph_backlink(
    node_id: str,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """计算型反向链接：{covered_by, modified_by, decided_by, referenced_by}。"""
    from graph_index import service
    root = _workspace_root(workspace)
    service.ensure_fresh(root)
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    with GraphStore(index_path(root)) as store:
        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")
        return {"node": node, "backlink": service.backlink(store, node_id)}


@router.get("/focus")
def graph_focus(
    node_id: str,
    depth: int = 2,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """焦点子图（飞书知识图谱一期 T-915）：以 node_id 为中心的 N 跳邻居
    （双向 BFS，depth ≤ 3 护栏）。纯读，全角色可看。"""
    from graph_index import service
    root = _workspace_root(workspace)
    service.ensure_fresh(root)
    from graph_index.service import index_path
    from graph_index.store import GraphStore
    with GraphStore(index_path(root)) as store:
        try:
            return service.focus_subgraph(store, node_id, depth=depth)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")


@router.get("/source")
def graph_source(
    file: str,
    line: int = 0,
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """源头文件只读定位（v1.19 source_ref 补强）：返回文件内容 + 定位行。

    安全：仅允许 specs/ / changes/ / .specguard/ / .specflow/（工作区根内）
    与 scenarios/ / feedback/（仓库根）前缀；resolve 后必须仍在受控目录内，
    越界 403。只读展示，修改永远回源系统。
    """
    from specstd.workspace import get_workspace_root

    root = get_workspace_root(workspace)
    if root is None:
        raise HTTPException(status_code=404, detail=f"工作区不存在或未激活: {workspace!r}")
    file = (file or "").replace("\\", "/").lstrip("/")
    if file.startswith(("specs/", "changes/", ".specguard/", ".specflow/")):
        base = root
    elif file.startswith(("scenarios/", "feedback/")):
        base = SG_ROOT
    else:
        raise HTTPException(status_code=403, detail=f"OUT_OF_SCOPE: 非受控源头前缀: {file}")
    target = (base / file).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail=f"OUT_OF_SCOPE: 路径越界: {file}")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"源头文件不存在: {file}")
    # M-02：仅允许文本文件扩展名，过滤二进制/索引/配置等非源头文件
    ALLOWED_EXTS = (".yaml", ".yml", ".json", ".md")
    if not target.suffix.lower() in ALLOWED_EXTS:
        raise HTTPException(
            status_code=403,
            detail=f"OUT_OF_SCOPE: 不允许读取 {target.suffix} 文件（仅允许 {', '.join(ALLOWED_EXTS)}）")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")
    return {"path": file, "content": content, "format": "raw",
            "line": max(0, int(line or 0)), "total_lines": len(content.splitlines())}


@router.get("/snapshots")
def graph_snapshots(
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """里程碑快照列表（时间倒序，含 source_fingerprint）。"""
    from graph_index import snapshot
    root = _workspace_root(workspace)
    return {"snapshots": snapshot.list_snapshots(root)}


@router.post("/snapshots")
def graph_snapshot_create(
    label: str = "",
    trigger: str = "manual",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """手动打里程碑快照（写 .specflow/graph_snapshots/，版本化保留）。"""
    require_role(user, "admin", "tester")
    # L-01：label 长度校验（30 字以内，与 snapshot._snapshot_id 净化后截断 40 一致）
    if len(label) > 60:
        raise HTTPException(status_code=400,
                            detail=f"label 过长（{len(label)} 字符，上限 60）")
    from graph_index import snapshot
    root = _workspace_root(workspace)
    try:
        return snapshot.create_snapshot(root, label=label, trigger=trigger)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/diff")
def graph_diff(
    from_snapshot: str,
    to_snapshot: str = "current",
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """演化 diff：两档快照比对（+新增/-移除/~修改 + per_module + 指纹）。"""
    from graph_index import snapshot
    root = _workspace_root(workspace)
    try:
        return snapshot.diff_snapshots(root, from_snapshot, to_snapshot)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/rebuild")
def graph_rebuild(
    user: CurrentUser = Depends(get_current_user),
    workspace: str = Depends(resolve_workspace),
):
    """强制重建索引（幂等；只写索引库，不触碰源数据）。"""
    require_role(user, "admin", "tester")
    from graph_index import service
    root = _workspace_root(workspace)
    return service.rebuild(root)
