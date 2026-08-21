"""audit_store — MCP 调用审计日志表（T-082）。

与 user_store.audit_log（业务审计）分离，sf_mcp_call_audit 专用于 MCP 工具调用审计。
字段：
  id / emp_no / session_id / purpose / workspace / tool_name / side_effect /
  args_digest / result_digest / verdict / created_at

verdict ∈ {ok, denied-whitelist, denied-side-effect, warn}
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

# SQLite 路径：workbench backend 的 data 目录
DB_DIR = Path(__file__).resolve().parent.parent / "workbench" / "backend" / "data"
DB_PATH = DB_DIR / "workbench.db"

_LOCK = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS sf_mcp_call_audit (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  emp_no          TEXT NOT NULL DEFAULT '',
  session_id      TEXT NOT NULL DEFAULT '',
  purpose         TEXT NOT NULL DEFAULT '',
  workspace       TEXT NOT NULL DEFAULT '',
  tool_name       TEXT NOT NULL,
  side_effect     TEXT NOT NULL DEFAULT 'none',
  args_digest     TEXT NOT NULL DEFAULT '',
  result_digest   TEXT NOT NULL DEFAULT '',
  verdict         TEXT NOT NULL DEFAULT 'ok',
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sf_mcp_call_audit_emp
  ON sf_mcp_call_audit(emp_no);
CREATE INDEX IF NOT EXISTS idx_sf_mcp_call_audit_session
  ON sf_mcp_call_audit(session_id);
CREATE INDEX IF NOT EXISTS idx_sf_mcp_call_audit_tool
  ON sf_mcp_call_audit(tool_name);
CREATE INDEX IF NOT EXISTS idx_sf_mcp_call_audit_created
  ON sf_mcp_call_audit(created_at);
"""

# 敏感字段正则（args/result 脱敏用）——兼容三种形态：
#   JSON 键值   "token": "abc" / "token":abc
#   明文键值   token=abc / token: abc
#   query 内嵌  ?token=abc
_SENSITIVE_RE = re.compile(
    r'("?\s*(?:token|password|secret|authorization|api_key|apikey|credential)\s*"?\s*[:=]\s*)'
    r'("[^"]*"|[^\s"\'&,;}]+)',
    re.IGNORECASE,
)


def _db_path(db_path: Optional[Path] = None) -> Path:
    return Path(db_path) if db_path else DB_PATH


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _mask_sensitive(text: str) -> str:
    """脱敏敏感字段：token/password/secret 等（保留键名，值替换为 ***）。"""
    return _SENSITIVE_RE.sub(r"\1***", text)


def _truncate_digest(text: str, max_len: int = 200) -> str:
    """截断 + 脱敏。"""
    sanitized = _mask_sensitive(text)
    if len(sanitized) <= max_len:
        return sanitized
    return sanitized[:max_len] + "..."


def ensure_tables(db_path: Optional[Path] = None):
    """确保审计表存在（幂等，挂 main.py startup）。"""
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, sqlite3.connect(str(path)) as conn:
        conn.executescript(_DDL)


def record_call(
    tool_name: str,
    verdict: str = "ok",
    emp_no: str = "",
    session_id: str = "",
    purpose: str = "",
    workspace: str = "",
    side_effect: str = "none",
    args_raw: str = "",
    result_raw: str = "",
    db_path: Optional[Path] = None,
):
    """记录一次 MCP 调用。

    Args:
        tool_name: 工具名
        verdict: ok / denied-whitelist / denied-side-effect / warn
        emp_no: 工号
        session_id: 会话 ID
        purpose: 用途 ID
        workspace: 工作区名
        side_effect: 副作用级别
        args_raw: 原始参数 JSON（将自动截断脱敏）
        result_raw: 原始结果（将自动截断脱敏）
    """
    ensure_tables(db_path)
    path = _db_path(db_path)
    with _LOCK, sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO sf_mcp_call_audit"
            " (emp_no, session_id, purpose, workspace, tool_name, side_effect,"
            "  args_digest, result_digest, verdict, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                emp_no,
                session_id,
                purpose,
                workspace,
                tool_name,
                side_effect,
                _truncate_digest(args_raw),
                _truncate_digest(result_raw),
                verdict,
                _now(),
            ),
        )


def query_calls(
    emp_no: str = "",
    session_id: str = "",
    tool_name: str = "",
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """查询审计记录（可按工号/会话/工具过滤，倒序）。"""
    ensure_tables(db_path)
    path = _db_path(db_path)
    sql = "SELECT * FROM sf_mcp_call_audit WHERE 1=1"
    args: list = []
    if emp_no:
        sql += " AND emp_no=?"
        args.append(emp_no)
    if session_id:
        sql += " AND session_id=?"
        args.append(session_id)
    if tool_name:
        sql += " AND tool_name=?"
        args.append(tool_name)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    with _LOCK, sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def get_call(call_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    """按 ID 查询单条审计记录。"""
    ensure_tables(db_path)
    path = _db_path(db_path)
    with _LOCK, sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM sf_mcp_call_audit WHERE id=?", (call_id,)
        ).fetchone()
    return dict(row) if row else None