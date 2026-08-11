"""sf_refs_store.py — 外部锚点/禅道作业/故事点评估三表管理（M06，T-056）。

sf_external_refs   外部锚点统一登记口（M10 血缘链唯一数据源，同表同源）
sf_zentao_jobs     禅道写作业幂等表（防重复建故事/提单，崩溃可续）
sf_storypoint_estimates 故事点评估留痕（建议恒 suggested，产品确认才回写）

设计红线：
- 链可跨界、资产不跨界：SpecGuard 只登记引用，不管理禅道资产
- 幂等键 UNIQUE 防重：重复点击/重试命中约束直接返回原作业
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from workbench.backend.services.specflow.sf_store import _connect, _LOCK, DB_PATH

# 外部锚点类型与链接类型枚举（M06 §4.1）
VALID_REF_TYPES = ("zt_story", "zt_bug", "zt_task", "pr", "unit_test_report")
VALID_LINKED_TYPES = ("delta", "fr_anchor", "spq", "scenario", "run", "interview")

VALID_JOB_KINDS = ("story_create", "bug_create", "story_point_writeback", "status_poll")
VALID_JOB_STATUSES = ("pending", "running", "succeeded", "failed", "rolled_back")

VALID_ESTIMATE_STATUSES = ("suggested", "confirmed", "written_back", "rejected")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_tables(db_path: Path | None = None):
    """建表（幂等）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sf_external_refs (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          workspace     TEXT NOT NULL,
          type          TEXT NOT NULL,
          ref           TEXT NOT NULL,
          ref_url       TEXT,
          linked_type   TEXT NOT NULL,
          linked        TEXT NOT NULL,
          note          TEXT,
          registered_by TEXT NOT NULL,
          created_at    TEXT NOT NULL,
          UNIQUE (workspace, type, ref, linked_type, linked)
        );
        CREATE INDEX IF NOT EXISTS idx_refs_linked
          ON sf_external_refs(workspace, linked_type, linked);

        CREATE TABLE IF NOT EXISTS sf_zentao_jobs (
          job_id      TEXT PRIMARY KEY,
          workspace   TEXT NOT NULL DEFAULT '',
          kind        TEXT NOT NULL,
          idem_key    TEXT NOT NULL UNIQUE,
          payload     TEXT NOT NULL,
          status      TEXT NOT NULL DEFAULT 'pending',
          cli_stdout  TEXT,
          cli_stderr  TEXT,
          zt_ref      TEXT,
          attempt     INTEGER NOT NULL DEFAULT 0,
          created_by  TEXT NOT NULL,
          created_at  TEXT NOT NULL,
          finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_idem ON sf_zentao_jobs(kind, idem_key);

        CREATE TABLE IF NOT EXISTS sf_storypoint_estimates (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          workspace    TEXT NOT NULL,
          delta_id     TEXT NOT NULL,
          zt_story     TEXT,
          breakdown    TEXT NOT NULL,
          points       INTEGER NOT NULL,
          confidence   REAL NOT NULL,
          ref_list     TEXT,
          status       TEXT NOT NULL DEFAULT 'suggested',
          confirmed_by TEXT,
          confirmed_at TEXT,
          created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_est_delta
          ON sf_storypoint_estimates(workspace, delta_id, status);

        CREATE TABLE IF NOT EXISTS sf_story_drafts (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          workspace   TEXT NOT NULL,
          session_id  TEXT NOT NULL DEFAULT '',
          title       TEXT NOT NULL,
          spec        TEXT NOT NULL,
          source_refs TEXT NOT NULL DEFAULT '[]',
          status      TEXT NOT NULL DEFAULT 'draft',
          created_by  TEXT NOT NULL,
          created_at  TEXT NOT NULL,
          zt_story    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_drafts_status
          ON sf_story_drafts(workspace, status);
        """)


# ══════════════════════════════════════════════════════════
# sf_external_refs CRUD（T-056 外部锚点登记）
# ══════════════════════════════════════════════════════════

def register_ref(workspace: str, ref_type: str, ref: str,
                 linked_type: str, linked: str,
                 ref_url: str = "", note: str = "",
                 registered_by: str = "system:zentao-cli",
                 db_path: Path | None = None) -> dict:
    """登记外部锚点（幂等：同四元组已存在返回既有行）。"""
    if ref_type not in VALID_REF_TYPES:
        raise ValueError(f"type 必须为 {VALID_REF_TYPES}")
    if linked_type not in VALID_LINKED_TYPES:
        raise ValueError(f"linked_type 必须为 {VALID_LINKED_TYPES}")
    if not ref or not linked:
        raise ValueError("ref 与 linked 不能为空")
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_external_refs WHERE workspace=? AND type=? "
            "AND ref=? AND linked_type=? AND linked=?",
            (workspace, ref_type, ref, linked_type, linked)).fetchone()
        if row:
            return {**dict(row), "duplicate": True}
        conn.execute(
            "INSERT INTO sf_external_refs (workspace, type, ref, ref_url, "
            "linked_type, linked, note, registered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (workspace, ref_type, ref, ref_url or None, linked_type, linked,
             note or None, registered_by, _now()))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM sf_external_refs WHERE workspace=? AND type=? "
            "AND ref=? AND linked_type=? AND linked=?",
            (workspace, ref_type, ref, linked_type, linked)).fetchone()
        return {**dict(row), "duplicate": False}


def list_refs(workspace: str = "", ref_type: str = "", ref: str = "",
              linked_type: str = "", linked: str = "",
              db_path: Path | None = None) -> list[dict]:
    """按条件列出外部锚点（工作区隔离）。"""
    init_tables(db_path)
    clauses, params = [], []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if ref_type:
        clauses.append("type = ?")
        params.append(ref_type)
    if ref:
        clauses.append("ref = ?")
        params.append(ref)
    if linked_type:
        clauses.append("linked_type = ?")
        params.append(linked_type)
    if linked:
        clauses.append("linked = ?")
        params.append(linked)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sf_external_refs {where} ORDER BY id DESC",
            params).fetchall()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
# sf_zentao_jobs CRUD（T-053 幂等作业）
# ══════════════════════════════════════════════════════════

def create_job(workspace: str, kind: str, idem_key: str, payload: dict,
               created_by: str, job_id: str = "",
               db_path: Path | None = None) -> dict:
    """创建作业（幂等键 UNIQUE；已存在返回原作业 + duplicate=True）。

    Raises:
        ValueError: kind 非法
    """
    if kind not in VALID_JOB_KINDS:
        raise ValueError(f"kind 必须为 {VALID_JOB_KINDS}")
    init_tables(db_path)
    jid = job_id or f"ZTJ-{uuid.uuid4().hex[:12]}"
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_zentao_jobs WHERE kind=? AND idem_key=?",
            (kind, idem_key)).fetchone()
        if row:
            return {**dict(row), "duplicate": True}
        conn.execute(
            "INSERT INTO sf_zentao_jobs (job_id, workspace, kind, idem_key, "
            "payload, status, created_by, created_at) VALUES (?, ?, ?, ?, ?, "
            "'pending', ?, ?)",
            (jid, workspace, kind, idem_key,
             json.dumps(payload, ensure_ascii=False), created_by, _now()))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM sf_zentao_jobs WHERE job_id=?", (jid,)).fetchone()
        return {**dict(row), "duplicate": False}


def get_job(job_id: str, db_path: Path | None = None) -> Optional[dict]:
    """查询作业。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_zentao_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.get("payload") or "{}")
        return d


def find_job_by_idem(kind: str, idem_key: str,
                     db_path: Path | None = None) -> Optional[dict]:
    """按幂等键反查作业（重试/重复点击命中）。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_zentao_jobs WHERE kind=? AND idem_key=?",
            (kind, idem_key)).fetchone()
        return dict(row) if row else None


def update_job(job_id: str, status: str = "", zt_ref: str = "",
               stdout: str = "", stderr: str = "", attempt: int = None,
               db_path: Path | None = None) -> bool:
    """更新作业状态/回显/引用（成功或终态时写 finished_at）。"""
    if status and status not in VALID_JOB_STATUSES:
        raise ValueError(f"status 必须为 {VALID_JOB_STATUSES}")
    sets, params = [], []
    if status:
        sets.append("status = ?")
        params.append(status)
    if zt_ref:
        sets.append("zt_ref = ?")
        params.append(zt_ref)
    if stdout:
        sets.append("cli_stdout = ?")
        params.append(stdout)
    if stderr:
        sets.append("cli_stderr = ?")
        params.append(stderr)
    if attempt is not None:
        sets.append("attempt = ?")
        params.append(attempt)
    if status in ("succeeded", "failed", "rolled_back"):
        sets.append("finished_at = ?")
        params.append(_now())
    if not sets:
        return False
    params.append(job_id)
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE sf_zentao_jobs SET {', '.join(sets)} WHERE job_id=?",
            params)
        return cur.rowcount > 0


def list_jobs(workspace: str = "", kind: str = "", status: str = "",
              db_path: Path | None = None) -> list[dict]:
    """列出作业。"""
    init_tables(db_path)
    clauses, params = [], []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sf_zentao_jobs {where} ORDER BY created_at DESC",
            params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.get("payload") or "{}")
            out.append(d)
        return out


# ══════════════════════════════════════════════════════════
# sf_story_drafts CRUD（S5 增补：对话分析产出的禅道故事草案）
# ══════════════════════════════════════════════════════════

VALID_DRAFT_STATUSES = ("draft", "created", "cancelled")


def create_story_draft(workspace: str, title: str, spec: str,
                       source_refs: list = None, created_by: str = "agent:mcp",
                       session_id: str = "",
                       db_path: Path | None = None) -> dict:
    """创建故事草案（恒 draft 态出生，人拍板后才创建禅道故事）。"""
    if not title or not spec:
        raise ValueError("title 与 spec 不能为空")
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sf_story_drafts (workspace, session_id, title, spec, "
            "source_refs, status, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
            (workspace, session_id, title, spec,
             json.dumps(source_refs or [], ensure_ascii=False),
             created_by, _now()))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM sf_story_drafts WHERE id = last_insert_rowid()"
        ).fetchone()
        return _draft_dict(row)


def get_story_draft(draft_id: int,
                    db_path: Path | None = None) -> Optional[dict]:
    """查询故事草案。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_story_drafts WHERE id=?", (draft_id,)).fetchone()
        return _draft_dict(row) if row else None


def list_story_drafts(workspace: str = "", status: str = "",
                      session_id: str = "",
                      db_path: Path | None = None) -> list[dict]:
    """列出故事草案（工作区隔离）。"""
    init_tables(db_path)
    clauses, params = [], []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sf_story_drafts {where} ORDER BY id DESC",
            params).fetchall()
        return [_draft_dict(r) for r in rows]


def mark_draft_created(draft_id: int, zt_story: str,
                       db_path: Path | None = None) -> bool:
    """草案 → created（禅道故事创建成功后回填编号）。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE sf_story_drafts SET status='created', zt_story=? "
            "WHERE id=? AND status='draft'",
            (zt_story, draft_id))
        return cur.rowcount > 0


def cancel_story_draft(draft_id: int,
                       db_path: Path | None = None) -> bool:
    """取消草案（draft → cancelled）。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE sf_story_drafts SET status='cancelled' "
            "WHERE id=? AND status='draft'",
            (draft_id,))
        return cur.rowcount > 0


def _draft_dict(row) -> dict:
    d = dict(row)
    d["source_refs"] = json.loads(d.get("source_refs") or "[]")
    return d


# ══════════════════════════════════════════════════════════
# sf_storypoint_estimates CRUD（T-054 故事点评估）
# ══════════════════════════════════════════════════════════

def create_estimate(workspace: str, delta_id: str, breakdown: list,
                    points: int, confidence: float, references: list = None,
                    zt_story: str = "",
                    db_path: Path | None = None) -> dict:
    """创建故事点评估（恒 suggested 出生）。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sf_storypoint_estimates (workspace, delta_id, "
            "zt_story, breakdown, points, confidence, ref_list, status, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'suggested', ?)",
            (workspace, delta_id, zt_story or None,
             json.dumps(breakdown, ensure_ascii=False), points, confidence,
             json.dumps(references or [], ensure_ascii=False), _now()))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM sf_storypoint_estimates "
            "WHERE id = last_insert_rowid()").fetchone()
        d = dict(row)
        d["breakdown"] = json.loads(d.get("breakdown") or "[]")
        d["ref_list"] = json.loads(d.get("ref_list") or "[]")
        return d


def get_estimate(estimate_id: int,
                 db_path: Path | None = None) -> Optional[dict]:
    """查询评估记录。"""
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sf_storypoint_estimates WHERE id=?",
            (estimate_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["breakdown"] = json.loads(d.get("breakdown") or "[]")
        d["ref_list"] = json.loads(d.get("ref_list") or "[]")
        return d


def update_estimate_status(estimate_id: int, status: str, actor: str = "",
                           zt_story: str = "",
                           db_path: Path | None = None) -> Optional[dict]:
    """更新评估状态（suggested → confirmed / rejected / written_back）。"""
    if status not in VALID_ESTIMATE_STATUSES:
        raise ValueError(f"status 必须为 {VALID_ESTIMATE_STATUSES}")
    init_tables(db_path)
    with _LOCK, _connect(db_path) as conn:
        if status == "confirmed":
            if not actor:
                raise ValueError("确认必须带操作人")
            cur = conn.execute(
                "UPDATE sf_storypoint_estimates SET status=?, confirmed_by=?, "
                "confirmed_at=? WHERE id=? AND status='suggested'",
                (status, actor, _now(), estimate_id))
        elif status == "written_back":
            cur = conn.execute(
                "UPDATE sf_storypoint_estimates SET status=?, zt_story=COALESCE(?, zt_story) "
                "WHERE id=? AND status='confirmed'",
                (status, zt_story or None, estimate_id))
        else:  # rejected
            cur = conn.execute(
                "UPDATE sf_storypoint_estimates SET status=? WHERE id=? "
                "AND status='suggested'",
                (status, estimate_id))
        if cur.rowcount == 0:
            return None
        conn.commit()
        return get_estimate(estimate_id, db_path)


def list_estimates(workspace: str = "", delta_id: str = "",
                   status: str = "",
                   db_path: Path | None = None) -> list[dict]:
    """列出评估记录。"""
    init_tables(db_path)
    clauses, params = [], []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if delta_id:
        clauses.append("delta_id = ?")
        params.append(delta_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sf_storypoint_estimates {where} "
            "ORDER BY id DESC", params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["breakdown"] = json.loads(d.get("breakdown") or "[]")
            d["ref_list"] = json.loads(d.get("ref_list") or "[]")
            out.append(d)
        return out
