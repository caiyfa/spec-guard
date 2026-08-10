"""agent_session_store — 会话索引表持久化（T-010，M01 §4.3）。

agent_sessions：会话实例索引（session_id/emp/workspace/purpose/title/status/
created_at/last_active_at），与 agent/sessions/{emp}/ 文件系统双写：
- 文件系统：会话内容（.jsonl）+ 元数据（_meta.json）——单一事实源
- 本表：索引投影（列表/过滤/审计快速查询），失败静默不阻断主链路
用途定义不建表（agent/purposes/*.md 热加载），DB 只存会话实例。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "workbench.db"

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path | None = None):
    """建表（幂等）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id    TEXT PRIMARY KEY,
            emp_no        TEXT NOT NULL,
            workspace     TEXT NOT NULL,
            purpose       TEXT NOT NULL DEFAULT '',
            title         TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'active',
            created_at    TEXT NOT NULL,
            last_active_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_emp_ws ON agent_sessions(emp_no, workspace, purpose);
        """)


def upsert_session(session_id: str, emp_no: str, workspace: str, purpose: str = "",
                   title: str = "", db_path: Path | None = None):
    """写入/刷新会话索引行（幂等；失败静默——索引是投影非事实源）。"""
    try:
        init_db(db_path)
        now = _now()
        with _LOCK, _connect(db_path) as conn:
            conn.execute(
                "INSERT INTO agent_sessions (session_id, emp_no, workspace, purpose, title, status, created_at, last_active_at)"
                " VALUES (?, ?, ?, ?, ?, 'active', ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET"
                " emp_no=excluded.emp_no, workspace=excluded.workspace,"
                " purpose=excluded.purpose, title=excluded.title, last_active_at=excluded.last_active_at",
                (session_id, emp_no, workspace, purpose, title, now, now),
            )
    except Exception:
        pass  # 索引投影失败不影响会话主链路


def get_session(session_id: str, db_path: Path | None = None) -> Optional[dict]:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?",
                           (session_id,)).fetchone()
        return dict(row) if row else None


def list_sessions(emp_no: str = "", workspace: str = "", purpose: str = "",
                  db_path: Path | None = None) -> list[dict]:
    """按条件列出会话索引（emp/workspace/purpose 过滤）。"""
    init_db(db_path)
    clauses, params = [], []
    if emp_no:
        clauses.append("emp_no = ?")
        params.append(emp_no)
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if purpose:
        clauses.append("purpose = ?")
        params.append(purpose)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_sessions {where} ORDER BY last_active_at DESC",
            params).fetchall()
        return [dict(r) for r in rows]


def update_title(session_id: str, title: str, db_path: Path | None = None):
    """更新标题（与 SessionManager.update_title 双写）。"""
    try:
        init_db(db_path)
        with _LOCK, _connect(db_path) as conn:
            conn.execute("UPDATE agent_sessions SET title = ? WHERE session_id = ?",
                         (title[:50], session_id))
    except Exception:
        pass


def archive_session(session_id: str, db_path: Path | None = None) -> bool:
    """归档会话（status active → archived，purpose 仍不可变）。"""
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute("UPDATE agent_sessions SET status = 'archived' WHERE session_id = ?",
                           (session_id,))
        return cur.rowcount > 0
