"""graph_index.store — 图谱索引 SQLite 存储（M11 §4.1）。

nodes：id + node_type + stage + title + module + feature + attrs（JSON 着色属性）
       + source_ref（JSON：file + line_range，T-070 v1.19 源头定位补强）
edges：src + dst + edge_type + attrs（类型化边）
index_meta：source_fingerprint / built_at / workspace / specstd_version

位置：{workspace}/.specguard/graph_index.db（工作区共享，天然共享产物不进私有区）。
派生物非事实源：删库重建必须得到同一张图（确定性）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

# 节点类型枚举（M11 §4.1，M10 §4.1 谱系口径；飞书知识图谱一期追加飞书三类）
NODE_TYPES = ("module", "feature", "fr", "ac", "scenario", "delta",
              "plan", "run", "spq", "decision", "external_ref", "interview",
              "feishu_doc", "feishu_minutes", "topic")

# 边类型枚举（M10 §4.2 谱系视角；飞书一期 mentions；三期 evolves）
EDGE_TYPES = ("covers", "depends_on", "contains", "produces", "decides",
              "references", "locks", "derives", "schedules", "executes",
              "verifies", "feedback", "archives", "relates", "mentions", "evolves")

# 节点 → 谱系阶段（M10 §4.1）
STAGE_BY_TYPE = {
    "interview": "req",
    "decision": "req",
    "delta": "req",
    "fr": "req",
    "ac": "req",
    "external_ref": "dev_ext",
    "scenario": "test",
    "plan": "test",
    "run": "test",
    "spq": "feedback",
    "feishu_doc": "req",
    "feishu_minutes": "req",
    "topic": "req",
}

_DDL = """
CREATE TABLE IF NOT EXISTS nodes (
  id          TEXT NOT NULL,
  node_type   TEXT NOT NULL,
  stage       TEXT,
  title       TEXT,
  module      TEXT,
  feature     TEXT,
  attrs       TEXT NOT NULL DEFAULT '{}',
  source_ref  TEXT,
  PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS edges (
  src       TEXT NOT NULL,
  dst       TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  attrs     TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (src, dst, edge_type)
);
CREATE TABLE IF NOT EXISTS index_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# 单进程内对同一索引库的写锁（防并发重建写坏）
_LOCK = threading.RLock()


def _json_default(obj) -> str:
    """attrs 序列化（确定性：ensure_ascii=False + sort_keys）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def open_index(path: Path) -> sqlite3.Connection:
    """打开索引库并确保表结构（幂等）。WAL 模式允许并发读。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class GraphStore:
    """图谱索引库读写封装（确定性写入：全部排序）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = open_index(self.path)

    # ── 写 ──────────────────────────────────────────────

    def clear_all(self, commit: bool = True):
        """清空全部节点/边（重建前调用）。

        Args:
            commit: 是否立即提交。False 时调用方负责事务生命周期。
        """
        with _LOCK:
            self.conn.execute("DELETE FROM nodes")
            self.conn.execute("DELETE FROM edges")
            self.conn.execute("DELETE FROM index_meta")
            if commit:
                self.conn.commit()

    def upsert_node(self, id: str, node_type: str, title: str = "",
                    module: str = "", feature: str = "",
                    attrs: Optional[dict] = None,
                    source_ref: Optional[dict] = None,
                    commit: bool = True):
        """写入节点（幂等，同 id 覆盖）。"""
        if node_type not in NODE_TYPES:
            raise ValueError(f"非法节点类型: {node_type!r}（允许: {NODE_TYPES}）")
        with _LOCK:
            self.conn.execute(
                "INSERT OR REPLACE INTO nodes"
                "(id, node_type, stage, title, module, feature, attrs, source_ref)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (id, node_type, STAGE_BY_TYPE.get(node_type, ""), title,
                 module, feature,
                 _json_default(attrs or {}),
                 _json_default(source_ref or {}) if source_ref else None),
            )
            if commit:
                self.conn.commit()

    def upsert_edge(self, src: str, dst: str, edge_type: str, attrs: Optional[dict] = None,
                    commit: bool = True):
        """写入边（幂等，同 (src, dst, edge_type) 覆盖）。"""
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"非法边类型: {edge_type!r}（允许: {EDGE_TYPES}）")
        with _LOCK:
            self.conn.execute(
                "INSERT OR REPLACE INTO edges (src, dst, edge_type, attrs)"
                " VALUES (?, ?, ?, ?)",
                (src, dst, edge_type, _json_default(attrs or {})),
            )
            if commit:
                self.conn.commit()

    def set_meta(self, key: str, value: str, commit: bool = True):
        with _LOCK:
            self.conn.execute(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
                (key, value))
            if commit:
                self.conn.commit()

    # ── 读 ──────────────────────────────────────────────

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM index_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def count_nodes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()["n"]

    def count_edges(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"]

    def get_node(self, id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (id,)).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def list_nodes(self, node_type: str = "", module: str = "", feature: str = "") -> list[dict]:
        """列出节点（可按类型/模块/功能点过滤）。"""
        sql = "SELECT * FROM nodes WHERE 1=1"
        args: list = []
        if node_type:
            sql += " AND node_type=?"
            args.append(node_type)
        if module:
            sql += " AND module=?"
            args.append(module)
        if feature:
            sql += " AND feature=?"
            args.append(feature)
        rows = self.conn.execute(sql + " ORDER BY id", args).fetchall()
        return [self._row_to_node(r) for r in rows]

    def list_nodes_by_type(self, node_type: str) -> list[dict]:
        return self.list_nodes(node_type=node_type)

    def list_edges_by_node(self, node_id: str) -> list[dict]:
        """节点全部出边与入边。"""
        rows = self.conn.execute(
            "SELECT * FROM edges WHERE src=? OR dst=? ORDER BY edge_type, src, dst",
            (node_id, node_id)).fetchall()
        return [{
            "src": r["src"], "dst": r["dst"], "edge_type": r["edge_type"],
            "attrs": _json_loads(r["attrs"]),
        } for r in rows]

    def list_edges(self, edge_type: str = "") -> list[dict]:
        sql = "SELECT * FROM edges WHERE 1=1"
        args: list = []
        if edge_type:
            sql += " AND edge_type=?"
            args.append(edge_type)
        rows = self.conn.execute(sql + " ORDER BY src, dst", args).fetchall()
        return [{
            "src": r["src"], "dst": r["dst"], "edge_type": r["edge_type"],
            "attrs": _json_loads(r["attrs"]),
        } for r in rows]

    def distinct_modules(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT module FROM nodes WHERE module<>'' ORDER BY module").fetchall()
        return [r["module"] for r in rows]

    def distinct_features(self, module: str = "") -> list[str]:
        sql = "SELECT DISTINCT feature FROM nodes WHERE feature<>''"
        args: list = []
        if module:
            sql += " AND module=?"
            args.append(module)
        rows = self.conn.execute(sql + " ORDER BY feature", args).fetchall()
        return [r["feature"] for r in rows]

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "node_type": row["node_type"],
            "stage": row["stage"],
            "title": row["title"],
            "module": row["module"],
            "feature": row["feature"],
            "attrs": _json_loads(row["attrs"]),
            "source_ref": _json_loads(row["source_ref"]) if row["source_ref"] else None,
        }
