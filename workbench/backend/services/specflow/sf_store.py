"""sf_store.py — sf_* 表管理（建表/CRUD/查询，T-022）。

参照 agent_session_store.py 模式复用（同一 workbench.db）。
sf_interviews / sf_questions 表存储面试会话状态与问题。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "workbench.db"

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_tables(db_path: Path | None = None):
    """建表（幂等，含旧表 workspace 列迁移）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sf_interviews (
          iv_id        TEXT PRIMARY KEY,
          workspace    TEXT NOT NULL,
          session_id   TEXT NOT NULL,
          title        TEXT NOT NULL,
          initiator    TEXT NOT NULL,
          target_delta TEXT,
          status       TEXT NOT NULL DEFAULT 'opened',
          opened_at    TEXT NOT NULL,
          frozen_at    TEXT,
          UNIQUE(workspace, session_id)
        );

        CREATE TABLE IF NOT EXISTS sf_questions (
          q_id         TEXT PRIMARY KEY,
          iv_id        TEXT NOT NULL,
          workspace    TEXT NOT NULL DEFAULT '',
          priority     TEXT NOT NULL,
          chapter      INTEGER,
          question     TEXT NOT NULL,
          answer       TEXT,
          decision_ref TEXT,
          spq_ref      TEXT,
          fr_refs      TEXT,
          status       TEXT NOT NULL DEFAULT 'pending',
          asked_at     TEXT NOT NULL,
          decided_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_q_iv ON sf_questions(iv_id, priority, status);
        """)
        # 旧表迁移：sf_questions 补 workspace 列（幂等）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sf_questions)")]
        if "workspace" not in cols:
            conn.execute(
                "ALTER TABLE sf_questions "
                "ADD COLUMN workspace TEXT NOT NULL DEFAULT ''")
            conn.commit()


# ══════════════════════════════════════════════════════════
# sf_interviews CRUD
# ══════════════════════════════════════════════════════════

def create_interview(iv_id: str, workspace: str, session_id: str,
                     title: str, initiator: str,
                     target_delta: str = "",
                     db_path: Path | None = None) -> dict:
    """创建面试记录。

    Raises:
        ValueError: 会话已在该工作区开标过（UNIQUE(workspace, session_id)）
    """
    now = _now()
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sf_interviews (iv_id, workspace, session_id, title, "
            "initiator, target_delta, status, opened_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'opened', ?)",
            (iv_id, workspace, session_id, title, initiator,
             target_delta or None, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM sf_interviews WHERE iv_id = ?", (iv_id,)).fetchone()
        return dict(row)


def get_interview(iv_id: str, db_path: Path | None = None) -> Optional[dict]:
    """查询面试记录。"""
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_interviews WHERE iv_id = ?", (iv_id,)).fetchone()
        return dict(row) if row else None


def update_interview_status(iv_id: str, status: str,
                            db_path: Path | None = None) -> bool:
    """更新面试状态。"""
    with _LOCK, _connect(db_path) as conn:
        extra = ""
        if status == "frozen":
            extra = ", frozen_at = datetime('now')"
        cur = conn.execute(
            f"UPDATE sf_interviews SET status = ?{extra} WHERE iv_id = ?",
            (status, iv_id))
        return cur.rowcount > 0


def list_interviews_db(workspace: str = "", session_id: str = "",
                       status: str = "", db_path: Path | None = None) -> list[dict]:
    """按条件列出面试记录。"""
    init_tables(db_path)
    clauses, params = [], []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sf_interviews {where} ORDER BY opened_at DESC",
            params).fetchall()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
# sf_questions CRUD
# ══════════════════════════════════════════════════════════

def create_question(iv_id: str, priority: str, question: str,
                    chapter: int = 0, spq_ref: str = "",
                    fr_refs: str = "", workspace: str = "",
                    db_path: Path | None = None) -> dict:
    """创建问题记录。

    自动生成 q_id 格式: IV-xxx-Q<seq>。

    Raises:
        ValueError: 面试不存在 / 优先级非法 / 同 q_id 已存在（跨工作区撞号）
    """
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        # 归属校验：面试必须已存在（SQLite 默认 FK 关闭，手动保证引用完整性）
        row = conn.execute(
            "SELECT 1 FROM sf_interviews WHERE iv_id = ?", (iv_id,)).fetchone()
        if not row:
            raise ValueError(f"面试不存在: {iv_id}")
        # 计算下一个问题序号
        cursor = conn.execute(
            "SELECT q_id FROM sf_questions WHERE iv_id = ? AND workspace = ? "
            "ORDER BY q_id DESC LIMIT 1",
            (iv_id, workspace))
        row = cursor.fetchone()
        seq = 1
        if row:
            parts = row[0].rsplit("-Q", 1)
            if len(parts) == 2:
                try:
                    seq = int(parts[1]) + 1
                except ValueError:
                    pass
        q_id = f"{iv_id}-Q{seq}"
        now = _now()
        try:
            conn.execute(
                "INSERT INTO sf_questions (q_id, iv_id, workspace, priority, "
                "chapter, question, spq_ref, fr_refs, status, asked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (q_id, iv_id, workspace, priority, chapter or None, question,
                 spq_ref or None, fr_refs or None, now),
            )
        except Exception as e:
            raise ValueError(f"问题登记失败: {e}")
        conn.commit()
        row = conn.execute(
            "SELECT * FROM sf_questions WHERE q_id = ?", (q_id,)).fetchone()
        return dict(row)


def get_question(q_id: str, db_path: Path | None = None) -> Optional[dict]:
    """查询问题记录。"""
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_questions WHERE q_id = ?", (q_id,)).fetchone()
        return dict(row) if row else None


def update_answer(q_id: str, answer: str, decision_ref: str = "",
                  db_path: Path | None = None) -> bool:
    """记录回答（pending → answered）。"""
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE sf_questions SET answer=?, status='answered', "
            "decision_ref=?, decided_at=? WHERE q_id=?",
            (answer, decision_ref or None, now, q_id))
        return cur.rowcount > 0


def list_questions(iv_id: str, status: str = "", priority: str = "",
                   workspace: str = "",
                   db_path: Path | None = None) -> list[dict]:
    """列出指定面试的问题（按工作区隔离，空 workspace 匹配空串 fail-closed）。"""
    init_tables(db_path)
    clauses, params = ["iv_id = ?", "workspace = ?"], [iv_id, workspace]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    where = " AND ".join(clauses)
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sf_questions WHERE {where} ORDER BY q_id",
            params).fetchall()
        return [dict(r) for r in rows]