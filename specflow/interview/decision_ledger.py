"""decision_ledger.py — 决策台账服务（M04，T-023）。

参照 feedback/ledger.py 模式独立实现（不共用表，保需求侧/测试侧分离）。
D-xxx 状态机：pending（待确认）→ resolved（已决）→ superseded（被增补只读）。
落锤不可推翻：resolved 条目禁止 UPDATE/DELETE；content_sha 指纹审计。
写操作（resolve/amend/confirm）不暴露 MCP，仅 UI/REST 通道。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# D-xxx 状态常量
STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_SUPERSEDED = "superseded"
VALID_STATUSES = frozenset({STATUS_PENDING, STATUS_RESOLVED, STATUS_SUPERSEDED})

# 合法状态流转（superseded 为终态，不可重开）
ALLOWED_TRANSITIONS = {
    STATUS_PENDING: {STATUS_RESOLVED},       # pending → resolved（人拍板）
    STATUS_RESOLVED: {STATUS_SUPERSEDED},    # resolved → superseded（增补只读）
    STATUS_SUPERSEDED: set(),               # 终态
}

# 链接类型
LINK_TYPES = frozenset({"fr_anchor", "delta", "spq", "question", "decision"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _next_d_id(conn, workspace: str) -> str:
    """生成下一个 D-xxx 编号（全局唯一，跨工作区不撞号）。

    sf_decisions.id 是全局主键，编号必须全局递增——
    若按 workspace 各自递增，两工作区会生成相同 D-xxx 触发主键冲突。
    """
    cursor = conn.execute(
        "SELECT id FROM sf_decisions ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        try:
            num = int(row[0].split("-")[1])
        except (ValueError, IndexError):
            num = 0
    else:
        num = 0
    return f"D-{num + 1:03d}"


def init_tables(conn):
    """建幂等建表（sf_decisions / sf_decision_links / sf_decision_amendments /
    sf_decision_draft_marks / sf_gate_evidence / sf_scores）。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sf_decisions (
      id            TEXT PRIMARY KEY,
      workspace     TEXT NOT NULL,
      interview_id  TEXT NOT NULL,
      question_ref  TEXT,
      priority      TEXT NOT NULL CHECK(priority IN ('P0','P1','P2')),
      question      TEXT NOT NULL,
      status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','resolved','superseded')),
      resolution    TEXT,
      resolved_by   TEXT,
      resolved_at   TEXT,
      superseded_by TEXT,
      created_by    TEXT NOT NULL DEFAULT 'agent',
      created_at    TEXT NOT NULL DEFAULT (datetime('now')),
      content_sha   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sf_decisions_ws_iv ON sf_decisions(workspace, interview_id);
    CREATE INDEX IF NOT EXISTS idx_sf_decisions_pending_p0 ON sf_decisions(workspace, priority, status);

    CREATE TABLE IF NOT EXISTS sf_decision_links (
      decision_id TEXT NOT NULL REFERENCES sf_decisions(id),
      link_type   TEXT NOT NULL CHECK(link_type IN ('fr_anchor','delta','spq','question','decision')),
      link_ref    TEXT NOT NULL,
      direction   TEXT NOT NULL DEFAULT 'out' CHECK(direction IN ('out','in')),
      PRIMARY KEY (decision_id, link_type, link_ref)
    );

    CREATE TABLE IF NOT EXISTS sf_decision_amendments (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      base_decision TEXT NOT NULL REFERENCES sf_decisions(id),
      new_decision  TEXT NOT NULL REFERENCES sf_decisions(id),
      reason        TEXT NOT NULL,
      created_by    TEXT NOT NULL,
      created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sf_decision_draft_marks (
      mark_id      TEXT PRIMARY KEY,
      decision_id  TEXT NOT NULL REFERENCES sf_decisions(id),
      draft_path   TEXT NOT NULL,
      anchor_ref   TEXT NOT NULL,
      mark_text    TEXT NOT NULL,
      resolved     INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sf_gate_evidence (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      workspace    TEXT NOT NULL,
      interview_id TEXT NOT NULL,
      gate_item    TEXT NOT NULL,
      verdict      TEXT NOT NULL,
      evidence     TEXT,
      actor        TEXT,
      acted_at     TEXT
    );

    CREATE TABLE IF NOT EXISTS sf_scores (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      workspace    TEXT NOT NULL,
      interview_id TEXT NOT NULL,
      dimension    TEXT NOT NULL CHECK(dimension IN ('logic','clarity','coverage','boundary','precondition')),
      score        INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
      source       TEXT NOT NULL CHECK(source IN ('machine','llm_suggested')),
      evidence     TEXT,
      status       TEXT NOT NULL DEFAULT 'suggested' CHECK(status IN ('suggested','confirmed','rejected')),
      confirmed_by TEXT,
      confirmed_at TEXT,
      spec_sha     TEXT NOT NULL,
      created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)


# ══════════════════════════════════════════════════════════
# 决策操作
# ══════════════════════════════════════════════════════════

def create_decision(conn, workspace: str, interview_id: str,
                    priority: str, question: str,
                    question_ref: str = "",
                    links: list[dict] = None,
                    created_by: str = "agent") -> dict:
    """创建决策条目（永远 pending 出生）。

    Args:
        conn: DB 连接
        workspace: 工作区
        interview_id: 面试 IV-xxx
        priority: P0/P1/P2
        question: 问题原文
        question_ref: 议题编号 Q1/Q2
        links: 挂链 [{type, ref}]
        created_by: agent/human

    Returns:
        新创建的决策行 dict

    Raises:
        ValueError: 参数非法
    """
    if priority not in ("P0", "P1", "P2"):
        raise ValueError(f"非法优先级: {priority!r}")
    links = links or []
    now = _now()
    d_id = _next_d_id(conn, workspace)
    # 计算指纹
    content = f"{d_id}|{workspace}|{interview_id}|{priority}|{question}"
    sha = _compute_sha(content)

    conn.execute(
        "INSERT INTO sf_decisions (id, workspace, interview_id, question_ref, "
        "priority, question, status, created_by, created_at, content_sha) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
        (d_id, workspace, interview_id, question_ref or None,
         priority, question, created_by, now, sha),
    )
    for link in links:
        lt = link.get("type", "")
        lr = link.get("ref", "")
        if lt in LINK_TYPES and lr:
            conn.execute(
                "INSERT OR IGNORE INTO sf_decision_links (decision_id, link_type, link_ref) "
                "VALUES (?, ?, ?)",
                (d_id, lt, lr),
            )
    return get_decision(conn, d_id)


def resolve_decision(conn, d_id: str, resolution: str,
                     resolved_by: str) -> dict:
    """人拍板确认决策（仅 product 角色可调）。

    resolved 条目禁止再次 UPDATE/DELETE。
    content_sha 在落锤时重算（含 resolution，指纹审计覆盖落锤内容）。

    Args:
        conn: DB 连接
        d_id: D-xxx
        resolution: 决策内容
        resolved_by: 拍板人工号

    Returns:
        更新后的决策行 dict

    Raises:
        ValueError: 非法状态流转
        KeyError: 决策不存在
        PermissionError: 非 pending 状态不可 resolve
    """
    decision = get_decision(conn, d_id)
    if not decision:
        raise KeyError(f"决策不存在: {d_id}")
    old_status = decision["status"]
    if old_status != STATUS_PENDING:
        raise PermissionError(
            f"决策 {d_id} 状态={old_status}，只有 pending 状态可 resolve")
    now = _now()
    # 重算指纹：含 resolution（审计覆盖落锤内容）
    content = (f"{d_id}|{decision['workspace']}|{decision['interview_id']}|"
               f"{decision['priority']}|{decision['question']}|{resolution}")
    sha = _compute_sha(content)
    conn.execute(
        "UPDATE sf_decisions SET status='resolved', resolution=?, "
        "resolved_by=?, resolved_at=?, content_sha=? WHERE id=?",
        (resolution, resolved_by, now, sha, d_id),
    )
    return get_decision(conn, d_id)


def amend_decision(conn, d_id: str, new_priority: str,
                   new_question: str, new_resolution: str,
                   reason: str, created_by: str,
                   workspace: str, interview_id: str) -> tuple[dict, dict]:
    """增补决策（生成新 D-xxx，原条目标 superseded 只读）。

    仅 resolved 条目可被增补。

    Args:
        conn: DB 连接
        d_id: 被增补的已决决策 D-xxx
        new_priority: 新决策优先级
        new_question: 新问题
        new_resolution: 新决策内容
        reason: 增补原因
        created_by: 操作人工号
        workspace: 工作区
        interview_id: 面试 IV-xxx

    Returns:
        (原决策, 新决策) 元组

    Raises:
        ValueError: 非法状态流转
        KeyError: 决策不存在
    """
    old = get_decision(conn, d_id)
    if not old:
        raise KeyError(f"决策不存在: {d_id}")
    if old["status"] != STATUS_RESOLVED:
        raise ValueError(
            f"决策 {d_id} 状态={old['status']}，仅 resolved 条目可被增补")
    # 增补链不跨面试：新决策必须挂原决策所在面试（防跨面试挂链）
    if interview_id and interview_id != old["interview_id"]:
        raise ValueError(
            f"增补不能跨面试: 原决策属于 {old['interview_id']}，"
            f"入参为 {interview_id}")
    interview_id = interview_id or old["interview_id"]

    now = _now()
    # 创建新决策
    new_d_id = _next_d_id(conn, workspace)
    content = (f"{new_d_id}|{workspace}|{interview_id}|{new_priority}|"
               f"{new_question}|{new_resolution}")
    sha = _compute_sha(content)
    conn.execute(
        "INSERT INTO sf_decisions (id, workspace, interview_id, priority, question, "
        "resolution, status, created_by, created_at, content_sha) "
        "VALUES (?, ?, ?, ?, ?, ?, 'resolved', ?, ?, ?)",
        (new_d_id, workspace, interview_id, new_priority, new_question,
         new_resolution, created_by, now, sha),
    )
    # 旧条目标 superseded
    conn.execute(
        "UPDATE sf_decisions SET status='superseded', superseded_by=? WHERE id=?",
        (new_d_id, d_id),
    )
    # 登记增补记录
    conn.execute(
        "INSERT INTO sf_decision_amendments (base_decision, new_decision, "
        "reason, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
        (d_id, new_d_id, reason, created_by, now),
    )
    return get_decision(conn, d_id), get_decision(conn, new_d_id)


def get_decision(conn, d_id: str) -> Optional[dict]:
    """按 D-xxx 查询决策。"""
    cursor = conn.execute("SELECT * FROM sf_decisions WHERE id = ?", (d_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return dict(row)


def list_decisions(conn, interview_id: str = "",
                   status: str = "", priority: str = "",
                   workspace: str = "") -> list[dict]:
    """按条件查询决策列表。"""
    clauses, params = [], []
    if interview_id:
        clauses.append("interview_id = ?")
        params.append(interview_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor = conn.execute(
        f"SELECT * FROM sf_decisions {where} ORDER BY created_at DESC", params)
    return [dict(r) for r in cursor.fetchall()]


def count_pending_p0(conn, interview_id: str, workspace: str = "") -> int:
    """统计指定面试的 pending P0 数量（gate.py 使用）。

    workspace 非空时按工作区过滤（跨工作区 IV-xxx 重号隔离）；
    空串按空串匹配（fail-closed：无工作区上下文时查不到数据，而非全量）。
    """
    cursor = conn.execute(
        "SELECT COUNT(*) FROM sf_decisions "
        "WHERE interview_id = ? AND priority = 'P0' AND status = 'pending' "
        "AND workspace = ?",
        (interview_id, workspace))
    row = cursor.fetchone()
    return row[0] if row else 0


def add_gate_evidence(conn, workspace: str, interview_id: str,
                      gate_item: str, verdict: str,
                      evidence: str = "", actor: str = "") -> dict:
    """登记门禁证据（影响面确认等人工动作）。"""
    now = _now()
    conn.execute(
        "INSERT INTO sf_gate_evidence (workspace, interview_id, gate_item, "
        "verdict, evidence, actor, acted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (workspace, interview_id, gate_item, verdict, evidence, actor, now),
    )
    cursor = conn.execute("SELECT last_insert_rowid()")
    row = cursor.fetchone()
    return {"id": row[0], "gate_item": gate_item, "verdict": verdict,
            "actor": actor, "acted_at": now}


def get_impact_confirmed(conn, interview_id: str, workspace: str = "") -> bool:
    """查询影响面是否已确认（按工作区隔离）。"""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM sf_gate_evidence "
        "WHERE interview_id = ? AND gate_item = 'impact_confirm' "
        "AND verdict = 'pass' AND workspace = ?",
        (interview_id, workspace))
    row = cursor.fetchone()
    return (row and row[0] > 0) or False


# ══════════════════════════════════════════════════════════
# 评分操作
# ══════════════════════════════════════════════════════════

def add_score(conn, workspace: str, interview_id: str,
              dimension: str, score: int, source: str,
              evidence: str = "", spec_sha: str = "") -> dict:
    """添加评分条目（status=suggested 出生）。"""
    now = _now()
    conn.execute(
        "INSERT INTO sf_scores (workspace, interview_id, dimension, score, "
        "source, evidence, status, spec_sha, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'suggested', ?, ?)",
        (workspace, interview_id, dimension, score, source, evidence, spec_sha, now),
    )
    cursor = conn.execute("SELECT last_insert_rowid()")
    row = cursor.fetchone()
    return {"id": row[0], "dimension": dimension, "score": score,
            "source": source, "status": "suggested"}


def confirm_score(conn, score_id: int, verdict: str,
                  confirmed_by: str, comment: str = "") -> dict:
    """QA 确认/驳回评分条目。

    Args:
        conn: DB 连接
        score_id: 评分条目 ID
        verdict: confirm / reject
        confirmed_by: QA 工号
        comment: 备注

    Returns:
        更新后的评分行 dict

    Raises:
        KeyError: 评分条目不存在
        ValueError: 非法 verdict
    """
    if verdict not in ("confirm", "reject"):
        raise ValueError(f"非法 verdict: {verdict!r}（允许 confirm/reject）")
    new_status = "confirmed" if verdict == "confirm" else "rejected"
    now = _now()
    conn.execute(
        "UPDATE sf_scores SET status=?, confirmed_by=?, confirmed_at=? WHERE id=?",
        (new_status, confirmed_by, now, score_id),
    )
    cursor = conn.execute("SELECT * FROM sf_scores WHERE id = ?", (score_id,))
    row = cursor.fetchone()
    if not row:
        raise KeyError(f"评分条目不存在: {score_id}")
    return dict(row)


def list_scores(conn, interview_id: str, workspace: str = "") -> list[dict]:
    """列出指定面试的全部评分记录（按工作区隔离）。"""
    cursor = conn.execute(
        "SELECT * FROM sf_scores WHERE interview_id = ? AND workspace = ? "
        "ORDER BY id", (interview_id, workspace))
    return [dict(r) for r in cursor.fetchall()]


def calculate_total_score(conn, interview_id: str, workspace: str = "") -> float:
    """计算加权总分（仅 status=confirmed 的维度，weight 均分 100/5=20）。

    未确认维度不计入总分（suggested/rejected 不计）；按工作区隔离。
    """
    cursor = conn.execute(
        "SELECT score FROM sf_scores "
        "WHERE interview_id = ? AND status = 'confirmed' AND workspace = ?",
        (interview_id, workspace))
    rows = cursor.fetchall()
    if not rows:
        return 0.0
    # 五维等权均分
    return sum(r[0] for r in rows) / 5.0


def has_suggested_score(conn, interview_id: str, dimension: str,
                        workspace: str = "") -> bool:
    """检查指定面试/维度是否已有 suggested 评分（evaluate 幂等去重）。"""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM sf_scores "
        "WHERE interview_id = ? AND dimension = ? AND status = 'suggested' "
        "AND workspace = ?",
        (interview_id, dimension, workspace))
    row = cursor.fetchone()
    return (row and row[0] > 0) or False


def export_ledger(conn, interview_id: str, workspace: str = "") -> dict:
    """导出面试台账快照（供 .specflow/decisions/IV-xxx.ledger.yaml 写入）。"""
    decisions = list_decisions(conn, interview_id=interview_id, workspace=workspace)
    p0_pending = count_pending_p0(conn, interview_id, workspace)
    scores = list_scores(conn, interview_id, workspace)
    confirmed_scores = [s for s in scores if s["status"] == "confirmed"]
    total = sum(s["score"] for s in confirmed_scores) / 5.0 if confirmed_scores else 0.0
    impact_confirmed = get_impact_confirmed(conn, interview_id, workspace)
    return {
        "decisions": decisions,
        "p0_gate": {
            "pending_p0": p0_pending,
            "impact_confirmed": impact_confirmed,
            "score": {"total": round(total, 1), "pass": total >= 70.0},
        },
    }