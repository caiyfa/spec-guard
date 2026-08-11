"""specflow.lineage.lineage_check — 断链确定性校验器（M10 §4.3/§6.3，T-074）。

从 graph_index 读节点/边，逐条执行 broken_link_rules.yaml：
- 某类节点缺少必填边 → WARNING（含规则 ID + 节点 ID）
- 结果落 {ws}/.specguard/lineage_check.json（带 graph_fingerprint，可删可重建）

纪律：校验是纯图遍历 + 规则集匹配，不靠 LLM；断链只报 WARNING，
补链动作（登记 external_ref、补 source_delta）永远由人回源执行（铁律 1）。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

import yaml

from graph_index.store import GraphStore

RULES_FILE = Path(__file__).resolve().parent / "broken_link_rules.yaml"
CHECK_OUTPUT = ".specguard/lineage_check.json"


def load_rules(path: Optional[Path] = None) -> list[dict]:
    """加载断链规则集（broken_link_rules.yaml）。"""
    p = Path(path) if path else RULES_FILE
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("rules") or []


def _node_missing_required(store: GraphStore, node: dict, rule: dict) -> bool:
    """单节点 × 单规则：必填边是否缺失（确定性）。"""
    node_type = rule.get("node", "")
    require = rule.get("require", "")
    if node.get("node_type") != node_type:
        return False
    edges = store.list_edges_by_node(node["id"])
    if require == "covers":
        return not any(e["edge_type"] == "covers" for e in edges)
    if require == "derives":
        # source_delta 缺失 = 落笔未挂链（索引 attrs 快照）
        return not str((node.get("attrs") or {}).get("source_delta") or "").strip()
    if require == "produces":
        return not any(e["edge_type"] == "produces" and e["dst"] == node["id"]
                       for e in edges)
    if require == "feedback":
        return not any(e["edge_type"] == "feedback" for e in edges)
    if require == "references":
        return not any(e["edge_type"] == "references" for e in edges)
    if require.startswith("any_of["):
        candidates = require[len("any_of["):-1].split(",")
        for cand in candidates:
            if cand.strip() == "covers" and any(e["edge_type"] == "covers" for e in edges):
                return False
            if cand.strip() == "references" and any(e["edge_type"] == "references" for e in edges):
                return False
        return True
    return False


def run_checks(workspace_root: Path, index_path: Optional[Path] = None,
               write_output: bool = True) -> dict:
    """执行断链校验（确定性，幂等）。

    Args:
        workspace_root: 工作区根
        index_path: 图谱索引路径（默认 {ws}/.specguard/graph_index.db）
        write_output: 是否落盘 lineage_check.json（派生物缓存）

    Returns:
        {workspace, graph_fingerprint, checked_at, warnings, rules} 
    """
    workspace_root = Path(workspace_root)
    db = Path(index_path) if index_path else workspace_root / ".specguard" / "graph_index.db"
    if not db.is_file():
        raise FileNotFoundError("图谱索引未构建：请先重建索引（graph_rebuild）")

    rules = load_rules()
    warnings: list[dict] = []
    with GraphStore(db) as store:
        graph_fingerprint = store.get_meta("source_fingerprint") or ""
        nodes = store.list_nodes()
        for rule in rules:
            for node in nodes:
                if _node_missing_required(store, node, rule):
                    warnings.append({
                        "rule": rule.get("id", ""),
                        "node": node["id"],
                        "node_type": node.get("node_type", ""),
                        "message": rule.get("message", ""),
                    })
    warnings.sort(key=lambda w: (w["rule"], w["node"]))

    result = {
        "workspace": workspace_root.name,
        "graph_fingerprint": graph_fingerprint,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "warnings": warnings,
        "rules": [r.get("id", "") for r in rules],
    }
    if write_output:
        target = workspace_root / CHECK_OUTPUT
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    return result


def load_check_output(workspace_root: Path) -> Optional[dict]:
    """读断链校验缓存（删除后重跑即重建，派生物非事实源）。"""
    target = Path(workspace_root) / CHECK_OUTPUT
    if not target.is_file():
        return None
    try:
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
