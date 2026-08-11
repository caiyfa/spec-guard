"""graph_index.service — 图谱查询服务（M11 §5）。

- status / rebuild / ensure_fresh：指纹失效即重建
- panorama L0/L1/L2：三层语义缩放视图数据（对齐原型 PANODATA）
- backlink：计算型反向链接（只读不落盘）
- health_score：健康分确定性公式（M11 §4.4）

全部为确定性计算，零 LLM；查询不写任何源数据（rebuild 只写索引库本身）。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from graph_index.store import GraphStore, STAGE_BY_TYPE
from graph_index.builder import (
    build_index, compute_source_fingerprint, SCENARIOS_DIR,
)

INDEX_FILE = "graph_index.db"
_STALE_DAYS = 30          # 健康分：近 N 天无执行 → stale_factor 线性升到 1
_HEALTH_CLAMP = (0, 100)


# ══════════════════════════════════════════════════════════
# 路径与状态
# ══════════════════════════════════════════════════════════

def index_path(workspace_root: Path) -> Path:
    """索引库落点：{workspace}/.specguard/graph_index.db（工作区共享）。"""
    return Path(workspace_root) / ".specguard" / INDEX_FILE


def status(workspace_root: Path, scenarios_root: Optional[Path] = None,
           sg_root: Optional[Path] = None) -> dict:
    """索引状态：指纹比对，失配 stale=true。"""
    workspace_root = Path(workspace_root)
    sg_root = Path(sg_root) if sg_root else Path(__file__).resolve().parent.parent
    scenarios_root = Path(scenarios_root) if scenarios_root else sg_root / SCENARIOS_DIR
    current = compute_source_fingerprint(workspace_root, scenarios_root, sg_root)
    db = index_path(workspace_root)
    if not db.is_file():
        return {"fingerprint": "", "source_fingerprint": current,
                "stale": True, "built_at": None}
    with GraphStore(db) as store:
        saved = store.get_meta("source_fingerprint") or ""
        built_at = store.get_meta("built_at")
    return {"fingerprint": saved, "source_fingerprint": current,
            "stale": saved != current, "built_at": built_at}


def rebuild(workspace_root: Path, scenarios_root: Optional[Path] = None,
            sg_root: Optional[Path] = None) -> dict:
    """强制重建索引（幂等；只写索引库，不触碰任何源文件）。"""
    sg_root = Path(sg_root) if sg_root else Path(__file__).resolve().parent.parent
    return build_index(workspace_root, index_path(workspace_root),
                       scenarios_root=scenarios_root, sg_root=sg_root)


def ensure_fresh(workspace_root: Path, scenarios_root: Optional[Path] = None,
                 sg_root: Optional[Path] = None) -> dict:
    """查询前保鲜：指纹失配自动重建，返回最终状态。"""
    st = status(workspace_root, scenarios_root, sg_root)
    if st["stale"]:
        rebuild(workspace_root, scenarios_root, sg_root)
        return status(workspace_root, scenarios_root, sg_root)
    return st


def _open(workspace_root: Path) -> GraphStore:
    return GraphStore(index_path(workspace_root))


# ══════════════════════════════════════════════════════════
# 健康分（M11 §4.4，确定性）
# ══════════════════════════════════════════════════════════

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def health_score(store: GraphStore, module: str, feature: str,
                 stale_days: int = _STALE_DAYS) -> Optional[float]:
    """功能点健康分：覆盖率 30% + 近期执行 40% + 未闭环 SPQ 10%。

    新功能点（无 FR 无场景）返回 None（前端渲染为虚线新节点）。
    索引库位于 {ws}/.specguard/graph_index.db → store.path.parent.parent = 工作区根。
    """
    workspace_root = store.path.parent.parent
    frs = store.list_nodes(node_type="fr", module=module, feature=feature)
    # scenario 节点未挂 module/feature——经 covers 边归属到 FR 所在功能点
    covers_edges = store.list_edges(edge_type="covers")
    covered_frs = {e["dst"] for e in covers_edges}
    fr_ids = {n["id"] for n in frs}
    if not fr_ids:
        return None
    covered_ratio = len(fr_ids & covered_frs) / len(fr_ids)

    # stale_factor：feature 下场景近 stale_days 天无执行 → 1（有任一近期 run 即 0）
    feature_frs = {n["id"] for n in frs}
    feature_scenarios = {e["src"] for e in covers_edges if e["dst"] in feature_frs}
    recent_cutoff = datetime.datetime.now().timestamp() - stale_days * 86400
    runs = store.list_nodes(node_type="run")
    recent_run = False
    for r in runs:
        ref = r.get("source_ref") or {}
        file = ref.get("file", "")
        if "reports" not in file:
            continue
        try:
            if (workspace_root / file).stat().st_mtime >= recent_cutoff:
                recent_run = True
                break
        except Exception:
            continue
    stale_factor = 0.0 if recent_run else (1.0 if feature_scenarios else 0.0)

    # open_spq：未闭环 SPQ（pending/in_progress）且关联场景属于本功能点
    open_spq = 0
    for n in store.list_nodes(node_type="spq"):
        attrs = n.get("attrs") or {}
        if attrs.get("status") in ("pending", "in_progress"):
            if attrs.get("scenario_id") in feature_scenarios:
                open_spq += 1

    health = 100.0 - 30.0 * (1 - covered_ratio) - 40.0 * stale_factor - 10.0 * open_spq
    return round(_clamp(health, *_HEALTH_CLAMP), 1)


# ══════════════════════════════════════════════════════════
# 三层视图（M11 §4.3 PANODATA 口径）
# ══════════════════════════════════════════════════════════

def _l0_edges(store: GraphStore) -> list[dict]:
    """模块间耦合边：跨模块 covers 共享 FR 数 + 场景 DAG 跨模块依赖数（确定性公式）。"""
    fr_module: dict = {n["id"]: n.get("module", "") for n in store.list_nodes(node_type="fr")}
    shared: dict = {}
    for e in store.list_edges(edge_type="covers"):
        m = fr_module.get(e["dst"], "")
        src = store.get_node(e["src"])
        src_mod = (src or {}).get("module", "")
        if src_mod and m and src_mod != m:
            key = tuple(sorted((src_mod, m)))
            shared[key] = shared.get(key, 0) + 1
    # 跨模块场景依赖（depends_on 边，经 scenario→fr→module 归属）
    for e in store.list_edges(edge_type="depends_on"):
        a, b = store.get_node(e["src"]), store.get_node(e["dst"])
        ma = (a or {}).get("module", "") or ""
        mb = (b or {}).get("module", "") or ""
        if ma and mb and ma != mb:
            key = tuple(sorted((ma, mb)))
            shared[key] = shared.get(key, 0) + 0.5
    edges = []
    for (a, b), w in sorted(shared.items()):
        strength = round(min(3.0, 1.2 + 0.6 * w), 1)
        edges.append({"a": a, "b": b, "w": strength})
    return edges


def panorama_l0(store: GraphStore) -> dict:
    """L0 系统星座图：模块节点 + 耦合边 + FR 计数。"""
    modules = store.distinct_modules()
    l0mods = {}
    for m in modules:
        fr_count = len(store.list_nodes(node_type="fr", module=m))
        l0mods[m] = {"name": m, "fr_count": fr_count, "counts": [fr_count]}
    return {"l0mods": l0mods, "l0edges": _l0_edges(store)}


def panorama_l1(store: GraphStore, module: str) -> dict:
    """L1 功能点视图：health + 覆盖/缺口计数。"""
    features = store.distinct_features(module)
    result = {}
    for feature in features:
        frs = store.list_nodes(node_type="fr", module=module, feature=feature)
        covers_edges = store.list_edges(edge_type="covers")
        fr_ids = {n["id"] for n in frs}
        covered = {e["dst"] for e in covers_edges if e["dst"] in fr_ids}
        result[feature] = {
            "health": health_score(store, module, feature),
            "counts": [len(fr_ids)],
            "era": 0,
            "nCov": len(covered),
            "nGap": len(fr_ids) - len(covered),
        }
    return result


def panorama_l2(store: GraphStore, module: str, feature: str) -> dict:
    """L2 FR 邻域：FR 圆 + 场景方块 + covers 边 + FR 互提边。"""
    frs = store.list_nodes(node_type="fr", module=module, feature=feature)
    covers_edges = store.list_edges(edge_type="covers")
    scenario_by_id = {n["id"]: n for n in store.list_nodes(node_type="scenario")}
    fr_ids = {n["id"] for n in frs}

    fr_nodes = []
    for n in sorted(frs, key=lambda x: x["id"]):
        attrs = n.get("attrs") or {}
        fr_nodes.append({
            "id": n["id"],
            "t": n.get("title", ""),
            "era": 0,
            "modAt": None,
            "goneAt": None,
            "cov": "ok" if attrs.get("cov") == "ok" else "gap",
            "source_ref": n.get("source_ref"),
        })

    scenarios = []
    seen_scenarios: set = set()
    for e in covers_edges:
        if e["dst"] in fr_ids and e["src"] not in seen_scenarios:
            seen_scenarios.add(e["src"])
            node = scenario_by_id.get(e["src"])
            scenarios.append({
                "id": e["src"],
                "title": (node or {}).get("title", ""),
                "covers": sorted((node or {}).get("attrs", {}).get("covers") or []),
                "source_ref": (node or {}).get("source_ref"),
            })
    scenarios.sort(key=lambda x: x["id"])

    return {"frs": fr_nodes, "frEdges": [], "scenarios": scenarios}


def backlink(store: GraphStore, node_id: str) -> dict:
    """计算型反向链接：covered_by / modified_by / decided_by / referenced_by（只读）。"""
    result = {"covered_by": [], "modified_by": [], "decided_by": [], "referenced_by": []}
    edges = store.list_edges_by_node(node_id)
    for e in edges:
        if e["edge_type"] == "covers" and e["dst"] == node_id:
            result["covered_by"].append(e["src"])
        elif e["edge_type"] == "contains" and e["dst"] == node_id:
            src_node = store.get_node(e["src"])
            src_type = (src_node or {}).get("node_type", "")
            if src_type == "delta":
                result["modified_by"].append(e["src"])
            else:
                result["covered_by"].append(e["src"])
        elif e["edge_type"] == "decides" and e["dst"] == node_id:
            result["decided_by"].append(e["src"])
        elif e["edge_type"] == "references" and e["dst"] == node_id:
            result["referenced_by"].append(e["src"])
    for key in result:
        result[key] = sorted(set(result[key]))
    return result


def query(workspace_root: Path, level: str = "L0", module: str = "",
          feature: str = "", node_id: str = "",
          scenarios_root: Optional[Path] = None,
          sg_root: Optional[Path] = None) -> dict:
    """图谱查询入口（REST/MCP 共用）：查询前保鲜（指纹失配自动重建）。"""
    ensure_fresh(workspace_root, scenarios_root, sg_root)
    with _open(workspace_root) as store:
        level = (level or "L0").upper()
        if node_id:
            return {"node": store.get_node(node_id), "backlink": backlink(store, node_id)}
        if level == "L0":
            return panorama_l0(store)
        if level == "L1":
            return panorama_l1(store, module)
        if level == "L2":
            return panorama_l2(store, module, feature)
        raise ValueError(f"非法图谱层级: {level!r}（允许 L0/L1/L2）")


# ══════════════════════════════════════════════════════════
# 谱系口径（M10 §4.1，供血缘链 T-073 消费）
# ══════════════════════════════════════════════════════════

def node_stage(node_type: str) -> str:
    """节点 → 谱系阶段映射（纯函数）。"""
    return STAGE_BY_TYPE.get(node_type, "")


# ══════════════════════════════════════════════════════════
# 血缘链投影（T-073，M10 §6.1/§6.2）
# ══════════════════════════════════════════════════════════

# 谱系主链（M10 §4.2 生命周期流）：interview → decision → delta → fr → scenario → plan → run → spq
# 边方向与流方向对照：
#   produces/decides/contains/references：边方向 = 流方向（上游在 src）
#   covers/schedules/executes/feedback：边方向 = 流反向（上游在 dst）
#   depends_on（场景同层依赖）：上游在 src
_TRACE_UP_SIDE = {
    "covers": "dst", "contains": "src", "produces": "src", "decides": "src",
    "references": "src", "schedules": "dst", "executes": "dst",
    "feedback": "dst", "depends_on": "src",
}


def trace(store: GraphStore, node_id: str, direction: str = "up",
          max_depth: int = 8) -> dict:
    """谱系投影：单节点沿生命周期流向上/向下可达集的有序线性链（确定性图遍历）。

    Q1（up）：这个场景为什么存在 → 面试/决策；Q2（down）：这个需求被验证了吗
    → 场景/计划/报告/SPQ。返回 {path, edges, truncated}，对齐原型 auditTrace。
    """
    direction = (direction or "up").lower()
    if direction not in ("up", "down", "both"):
        raise ValueError(f"非法追溯方向: {direction!r}（允许 up/down/both）")
    max_depth = max(1, min(int(max_depth or 8), 16))

    start = store.get_node(node_id)
    if start is None:
        raise KeyError(f"节点不存在: {node_id}")

    path: list[dict] = []
    edges_out: list[dict] = []
    seen: set = set()
    truncated = False

    def _node_view(nid: str) -> dict:
        n = store.get_node(nid)
        attrs = (n or {}).get("attrs") or {}
        return {
            "id": nid,
            "type": (n or {}).get("node_type", ""),
            "stage": (n or {}).get("stage", ""),
            "title": (n or {}).get("title", ""),
            "status": attrs.get("status") or attrs.get("cov") or "",
            "external": (n or {}).get("node_type") == "external_ref",
            "url": attrs.get("url", ""),
        }

    # BFS 分层遍历：同层按边类型 + 邻居 ID 排序（确定性）
    frontier = [(node_id, 0)]
    seen.add(node_id)
    while frontier:
        next_frontier = []
        for current, depth in frontier:
            path.append(_node_view(current))
            if depth >= max_depth:
                truncated = True
                continue
            edges = store.list_edges_by_node(current)
            neighbors = []
            for e in edges:
                etype = e["edge_type"]
                up_side = _TRACE_UP_SIDE.get(etype)
                if up_side is None:
                    continue
                down_side = "src" if up_side == "dst" else "dst"
                if direction in ("up", "both"):
                    other = "src" if up_side == "dst" else "dst"
                    if e[other] == current:
                        neighbors.append((e[up_side], etype))
                if direction in ("down", "both"):
                    other = "src" if down_side == "dst" else "dst"
                    if e[other] == current:
                        neighbors.append((e[down_side], etype))
            neighbors.sort()
            for nid, etype in neighbors:
                if nid not in seen:
                    seen.add(nid)
                    next_frontier.append((nid, depth + 1))
                    edges_out.append({"from": current, "to": nid, "type": etype})
        frontier = next_frontier

    return {"path": path, "edges": edges_out, "truncated": truncated,
            "root": node_id, "direction": direction}
