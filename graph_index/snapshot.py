"""graph_index.snapshot — 里程碑快照 + 演化 diff（M11 §6.2/§6.3，T-072）。

快照：事件驱动（delta 冻结/归档/计划执行完成）+ 手动触发，
落 {workspace}/.specflow/graph_snapshots/snap_<date>_<label>.json
（版本化保留，随工作区 git 提交），带 source_fingerprint 可凭指纹重建校验。

diff：两快照节点/边集合比对 → ADDED/REMOVED/MODIFIED + per_module 聚合（确定性）。

不建图谱级版本库（红线）；快照是派生物，任何快照可删除重打。
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Optional

from graph_index.store import GraphStore
from graph_index.builder import compute_source_fingerprint, SCENARIOS_DIR

SNAPSHOTS_SUBDIR = ".specflow/graph_snapshots"
TRIGGERS = ("delta_frozen", "delta_archived", "plan_completed", "manual")


# ══════════════════════════════════════════════════════════
# 路径
# ══════════════════════════════════════════════════════════

def snapshots_dir(workspace_root: Path) -> Path:
    """快照目录：{ws}/.specflow/graph_snapshots/（版本化资产，共享不入私有区）。"""
    d = Path(workspace_root) / SNAPSHOTS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshot_id(label: str, created_at: str) -> str:
    """快照 ID：snap_<YYYY-MM-DD>_<label 净化>。"""
    date = created_at[:10]
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", (label or "snapshot").strip()).strip("-")[:40]
    return f"snap_{date}_{safe}" if safe else f"snap_{date}_snapshot"


# ══════════════════════════════════════════════════════════
# 快照生成
# ══════════════════════════════════════════════════════════

def create_snapshot(workspace_root: Path, label: str = "", trigger: str = "manual",
                    index_path: Optional[Path] = None,
                    scenarios_root: Optional[Path] = None,
                    sg_root: Optional[Path] = None) -> dict:
    """从当前图谱索引导出里程碑快照（幂等：同 label 同触发点覆盖）。"""
    if trigger not in TRIGGERS:
        raise ValueError(f"非法触发点: {trigger!r}（允许: {TRIGGERS}）")
    workspace_root = Path(workspace_root)
    sg_root = Path(sg_root) if sg_root else Path(__file__).resolve().parent.parent
    scenarios_root = Path(scenarios_root) if scenarios_root else sg_root / SCENARIOS_DIR

    db = Path(index_path) if index_path else workspace_root / ".specguard" / "graph_index.db"
    if not db.is_file():
        # 索引未建：先建（快照前保证有图可拍）
        from graph_index.service import rebuild
        rebuild(workspace_root, scenarios_root, sg_root)

    created_at = datetime.datetime.now().isoformat(timespec="seconds")
    snapshot_id = _snapshot_id(label, created_at)

    with GraphStore(db) as store:
        nodes = [{
            "id": n["id"], "node_type": n["node_type"], "stage": n["stage"],
            "title": n["title"], "module": n["module"], "feature": n["feature"],
            "attrs": n["attrs"], "source_ref": n["source_ref"],
        } for n in store.list_nodes()]
        edges = [{"src": e["src"], "dst": e["dst"], "edge_type": e["edge_type"],
                  "attrs": e["attrs"]} for e in store.list_edges()]
        source_fingerprint = store.get_meta("source_fingerprint") or ""

    data = {
        "snapshot_id": snapshot_id,
        "trigger": trigger,
        "label": label or snapshot_id,
        "created_at": created_at,
        "source_fingerprint": source_fingerprint,
        "nodes": nodes,
        "edges": edges,
    }
    target = snapshots_dir(workspace_root) / f"{snapshot_id}.json"
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return {"snapshot_id": snapshot_id, "path": str(target.relative_to(workspace_root))
            .replace("\\", "/"), "nodes": len(nodes), "edges": len(edges),
            "source_fingerprint": source_fingerprint}


def list_snapshots(workspace_root: Path) -> list[dict]:
    """快照列表（按时间倒序，含指纹）。"""
    d = snapshots_dir(workspace_root)
    snapshots = []
    for f in sorted(d.glob("snap_*.json"), reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            continue
        snapshots.append({
            "snapshot_id": raw.get("snapshot_id") or f.stem,
            "label": raw.get("label") or f.stem,
            "trigger": raw.get("trigger", ""),
            "created_at": raw.get("created_at", ""),
            "source_fingerprint": raw.get("source_fingerprint", ""),
            "nodes": len(raw.get("nodes") or []),
            "edges": len(raw.get("edges") or []),
        })
    return snapshots


def _load_snapshot(workspace_root: Path, snapshot_id: str) -> Optional[dict]:
    """按 ID 加载快照（current 返回 None 由调用方走当前索引）。"""
    if snapshot_id in ("", "current"):
        return None
    d = snapshots_dir(workspace_root)
    target = d / f"{snapshot_id}.json"
    if not target.is_file():
        # 兼容：snap_ 前缀缺失时补全重试
        target = d / f"snap_{snapshot_id}.json"
    if not target.is_file():
        raise FileNotFoundError(f"快照不存在: {snapshot_id}（可用 list_snapshots 查看）")
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════
# 演化 diff（M11 §6.3）
# ══════════════════════════════════════════════════════════

def _node_key(n: dict) -> tuple:
    return (n["id"], n["node_type"])


def _edge_key(e: dict) -> tuple:
    return (e["src"], e["dst"], e["edge_type"])


def diff_snapshots(workspace_root: Path, from_snapshot: str, to_snapshot: str = "current",
                   index_path: Optional[Path] = None) -> dict:
    """两档快照节点/边集合比对 → ADDED/REMOVED/MODIFIED + per_module 聚合。

    to=current 时与当前索引比对（原型主路径：历史档 → 当前）。
    """
    workspace_root = Path(workspace_root)
    from_data = _load_snapshot(workspace_root, from_snapshot)
    if from_data is None:
        raise FileNotFoundError(f"快照不存在: {from_snapshot}")
    to_data = _load_snapshot(workspace_root, to_snapshot)

    if to_data is None:
        db = Path(index_path) if index_path else workspace_root / ".specguard" / "graph_index.db"
        if not db.is_file():
            raise FileNotFoundError("当前索引未构建（先重建或打快照）")
        with GraphStore(db) as store:
            to_nodes = store.list_nodes()
            to_edges = store.list_edges()
            to_fingerprint = store.get_meta("source_fingerprint") or ""
    else:
        to_nodes = to_data.get("nodes") or []
        to_edges = to_data.get("edges") or []
        to_fingerprint = to_data.get("source_fingerprint", "")

    from_nodes = from_data.get("nodes") or []
    from_edges = from_data.get("edges") or []

    from_n = {_node_key(n): n for n in from_nodes}
    to_n = {_node_key(n): n for n in to_nodes}
    from_e = {_edge_key(e): e for e in from_edges}
    to_e = {_edge_key(e): e for e in to_edges}

    added = [n["id"] for k, n in sorted(to_n.items()) if k not in from_n]
    removed = [n["id"] for k, n in sorted(from_n.items()) if k not in to_n]
    modified = []
    for k, n in sorted(to_n.items()):
        if k in from_n and (from_n[k].get("attrs") or {}) != (n.get("attrs") or {}):
            modified.append(n["id"])
    # 边集合变化并入 modified 统计（节点 ID 视角）
    edge_added = sum(1 for k in to_e if k not in from_e)
    edge_removed = sum(1 for k in from_e if k not in to_e)

    # per_module 聚合（按节点 module 归属）
    to_by_id = {n["id"]: n for n in to_nodes}
    from_by_id = {n["id"]: n for n in from_nodes}
    per_module: dict = {}

    def _bump(nid: str, kind: str):
        m = (to_by_id.get(nid) or from_by_id.get(nid) or {})
        key = m.get("module") or "(无模块)"
        per_module.setdefault(key, {"added": 0, "removed": 0, "modified": 0})
        per_module[key][kind] += 1

    for nid in added:
        _bump(nid, "added")
    for nid in removed:
        _bump(nid, "removed")
    for nid in modified:
        _bump(nid, "modified")

    return {
        "from": from_snapshot,
        "to": to_snapshot,
        "added": len(added),
        "removed": len(removed),
        "modified": len(modified),
        "edge_added": edge_added,
        "edge_removed": edge_removed,
        "per_module": per_module,
        "fingerprint_from": from_data.get("source_fingerprint", ""),
        "fingerprint_to": to_fingerprint,
        "added_ids": added,
        "removed_ids": removed,
        "modified_ids": modified,
    }
