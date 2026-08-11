"""store.py — 材料包数据层（M03 §4.2，T-030/T-031）。

sf_materials / sf_material_topics 表：材料登记、解析状态机、议题候选与确认闸门。

- MAT-xxx 编号全局唯一（sf_materials.material_id 是全局主键——参照 D-xxx 教训，
  编号全局递增，不按工作区各自递增，防跨工作区撞主键）。
- workspace 隔离：所有查询带 workspace 过滤（fail-closed：空 workspace 匹配空串）。
- 人拍板闸门：材料 pack_included=0 不入信息包；议题候选 confirmed=0 不进面试上下文。
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 材料状态机（M03 §4.2）
MATERIAL_STATUSES = frozenset({
    "uploaded", "parsing", "parsed", "indexed", "packed", "failed"})

# 材料格式（人工上传 + 飞书/禅道类型 v1.1 预留）
MATERIAL_FMTS = frozenset({
    "md", "txt", "docx", "pdf", "yaml",
    "feishu_doc", "feishu_base", "feishu_minutes", "feishu_im",
    "zentao_story",
})

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _next_material_id(conn) -> str:
    """生成下一个 MAT-xxx 编号（全局唯一，跨工作区不撞号）。"""
    cursor = conn.execute("SELECT material_id FROM sf_materials ORDER BY material_id DESC LIMIT 1")
    row = cursor.fetchone()
    num = 0
    if row:
        try:
            num = int(row[0].split("-")[1])
        except (ValueError, IndexError):
            num = 0
    return f"MAT-{num + 1:03d}"


def init_tables(conn):
    """建表（幂等）。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sf_materials (
      material_id   TEXT PRIMARY KEY,
      iv_id         TEXT NOT NULL,
      workspace     TEXT NOT NULL,
      filename      TEXT NOT NULL,
      fmt           TEXT NOT NULL,
      source_url    TEXT,
      fetched_by    TEXT,
      size_bytes    INTEGER NOT NULL,
      sha256_12     TEXT NOT NULL,
      status        TEXT NOT NULL DEFAULT 'uploaded'
                    CHECK(status IN ('uploaded','parsing','parsed','indexed','packed','failed')),
      parse_error   TEXT,
      parsed_at     TEXT,
      pack_included INTEGER NOT NULL DEFAULT 0,
      uploaded_by   TEXT NOT NULL,
      uploaded_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_mat_iv ON sf_materials(iv_id, status);

    CREATE TABLE IF NOT EXISTS sf_material_topics (
      topic_id      TEXT PRIMARY KEY,
      material_id   TEXT NOT NULL REFERENCES sf_materials(material_id),
      iv_id         TEXT NOT NULL,
      workspace     TEXT NOT NULL,
      title         TEXT NOT NULL,
      priority_hint TEXT,
      fr_hints      TEXT,
      prd_section   TEXT,
      confirmed     INTEGER NOT NULL DEFAULT 0,
      created_at    TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_topic_iv ON sf_material_topics(iv_id, confirmed);
    """)


# ══════════════════════════════════════════════════════════
# sf_materials CRUD
# ══════════════════════════════════════════════════════════

def create_material(conn, iv_id: str, workspace: str, filename: str,
                    fmt: str, size_bytes: int, content: bytes,
                    uploaded_by: str, source_url: str = "",
                    fetched_by: str = "") -> dict:
    """登记材料（status=uploaded 出生）。

    Raises:
        ValueError: 格式非法 / 文件为空
    """
    if fmt not in MATERIAL_FMTS:
        raise ValueError(f"非法材料格式: {fmt!r}（允许: {sorted(MATERIAL_FMTS)}）")
    if size_bytes <= 0:
        raise ValueError("材料文件不能为空")
    now = _now()
    mid = _next_material_id(conn)
    sha = _sha12(content)
    conn.execute(
        "INSERT INTO sf_materials (material_id, iv_id, workspace, filename, "
        "fmt, source_url, fetched_by, size_bytes, sha256_12, status, "
        "uploaded_by, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "'uploaded', ?, ?)",
        (mid, iv_id, workspace, filename, fmt, source_url or None,
         fetched_by or None, size_bytes, sha, uploaded_by, now),
    )
    return get_material(conn, mid)


def get_material(conn, material_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM sf_materials WHERE material_id = ?", (material_id,)).fetchone()
    return dict(row) if row else None


def list_materials(conn, iv_id: str = "", workspace: str = "",
                   status: str = "") -> list[dict]:
    """材料列表（按工作区隔离；iv_id 为空列出工作区全部）。"""
    clauses, params = ["workspace = ?"], [workspace]
    if iv_id:
        clauses.append("iv_id = ?")
        params.append(iv_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    rows = conn.execute(
        f"SELECT * FROM sf_materials WHERE {' AND '.join(clauses)} "
        f"ORDER BY uploaded_at DESC", params).fetchall()
    return [dict(r) for r in rows]


def update_material_status(conn, material_id: str, status: str,
                           parse_error: str = "") -> bool:
    """推进解析状态机（uploaded→parsing→parsed→indexed→packed|failed）。"""
    if status not in MATERIAL_STATUSES:
        raise ValueError(f"非法材料状态: {status!r}")
    now = _now()
    cur = conn.execute(
        "UPDATE sf_materials SET status=?, parse_error=?, parsed_at=? "
        "WHERE material_id=?",
        (status, parse_error or None, now if status in ("parsed", "indexed", "failed") else None,
         material_id))
    return cur.rowcount > 0


def set_pack_included(conn, material_id: str, included: int) -> bool:
    """人拍板：材料入信息包闸门（pack_included=1 才被装配器纳入）。"""
    cur = conn.execute(
        "UPDATE sf_materials SET pack_included=? WHERE material_id=?",
        (1 if included else 0, material_id))
    return cur.rowcount > 0


# ══════════════════════════════════════════════════════════
# sf_material_topics CRUD（T-031 议题候选 + 确认闸门）
# ══════════════════════════════════════════════════════════

def _next_topic_id(conn, material_id: str) -> str:
    """生成 MAT-xxx-Tnn 议题候选编号。"""
    cursor = conn.execute(
        "SELECT topic_id FROM sf_material_topics WHERE material_id = ? "
        "ORDER BY topic_id DESC LIMIT 1", (material_id,))
    row = cursor.fetchone()
    seq = 1
    if row:
        parts = row[0].rsplit("-T", 1)
        if len(parts) == 2:
            try:
                seq = int(parts[1]) + 1
            except ValueError:
                pass
    return f"{material_id}-T{seq:02d}"


def add_topic(conn, material_id: str, iv_id: str, workspace: str,
              title: str, priority_hint: str = "",
              fr_hints: list[str] = None, prd_section: str = "") -> dict:
    """登记议题候选（confirmed=0 出生——人拍板前不进面试上下文）。"""
    mat = get_material(conn, material_id)
    if not mat:
        raise KeyError(f"材料不存在: {material_id}")
    now = _now()
    tid = _next_topic_id(conn, material_id)
    import json
    conn.execute(
        "INSERT INTO sf_material_topics (topic_id, material_id, iv_id, "
        "workspace, title, priority_hint, fr_hints, prd_section, confirmed, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (tid, material_id, iv_id, workspace, title, priority_hint or None,
         json.dumps(fr_hints or [], ensure_ascii=False), prd_section or None, now),
    )
    return get_topic(conn, tid)


def get_topic(conn, topic_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM sf_material_topics WHERE topic_id = ?", (topic_id,)).fetchone()
    return dict(row) if row else None


def list_topics(conn, iv_id: str = "", workspace: str = "",
                confirmed_only: bool = False,
                material_id: str = "") -> list[dict]:
    """议题候选列表（人拍板闸门：confirmed_only 只取已确认）。"""
    clauses, params = ["workspace = ?"], [workspace]
    if iv_id:
        clauses.append("iv_id = ?")
        params.append(iv_id)
    if material_id:
        clauses.append("material_id = ?")
        params.append(material_id)
    if confirmed_only:
        clauses.append("confirmed = 1")
    rows = conn.execute(
        f"SELECT * FROM sf_material_topics WHERE {' AND '.join(clauses)} "
        f"ORDER BY created_at", params).fetchall()
    return [dict(r) for r in rows]


def confirm_topic(conn, topic_id: str, confirmed: int = 1) -> bool:
    """人拍板：议题候选生效（confirmed=1 供面试官提问管线消费）。"""
    cur = conn.execute(
        "UPDATE sf_material_topics SET confirmed=? WHERE topic_id=?",
        (1 if confirmed else 0, topic_id))
    return cur.rowcount > 0
