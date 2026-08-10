"""用户 / 工作区授权 / 审计 / 执行队列 持久化（SQLite，WAL 模式）。

多用户基座（M6）：
- users: 用户与角色（admin/tester/viewer）+ 个人默认工作区
- workspace_grants: 工作区授权（admin 开通给用户）
- audit_log: 敏感操作审计（登录/授权/注册/入库/触发）
- run_queue: 执行队列持久化（进程重启不丢排队）

约束：单 worker 部署（RunManager 全局单例），WAL + 短事务，几十用户量级无压力。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "workbench.db"

VALID_ROLES = ("admin", "tester", "viewer", "product")

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
        CREATE TABLE IF NOT EXISTS users (
            emp_no TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'viewer',
            roles TEXT NOT NULL DEFAULT '',
            default_workspace TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_login_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workspace_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_name TEXT NOT NULL,
            emp_no TEXT NOT NULL,
            granted_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(workspace_name, emp_no)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_no TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS run_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_no TEXT NOT NULL,
            scope TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            env TEXT NOT NULL DEFAULT 'sit',
            plan_id TEXT NOT NULL DEFAULT '',
            breakpoints TEXT NOT NULL DEFAULT '[]',
            strict_deps INTEGER NOT NULL DEFAULT 0,
            workspace TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT ''
        );
        """)
        # 迁移：老库补列（幂等）
        for col, ddl in (
            ("workspace", "ALTER TABLE run_queue ADD COLUMN workspace TEXT NOT NULL DEFAULT ''"),
            ("prep_only", "ALTER TABLE run_queue ADD COLUMN prep_only INTEGER NOT NULL DEFAULT 0"),
            ("skip_upstream_verify", "ALTER TABLE run_queue ADD COLUMN skip_upstream_verify INTEGER NOT NULL DEFAULT 0"),
            ("account_override", "ALTER TABLE run_queue ADD COLUMN account_override TEXT NOT NULL DEFAULT ''"),
            ("overrides", "ALTER TABLE run_queue ADD COLUMN overrides TEXT NOT NULL DEFAULT ''"),
            ("roles", "ALTER TABLE users ADD COLUMN roles TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # 列已存在


# ══════════════════════════════════════════════════════════
# 用户
# ══════════════════════════════════════════════════════════

def _parse_roles(raw_role: str, raw_roles: str = "") -> list[str]:
    """解析角色集：roles 列（逗号分隔多值）优先，回退 role 列（单值存量）。"""
    if raw_roles and raw_roles.strip():
        return [r.strip() for r in raw_roles.split(",") if r.strip()]
    if raw_role and raw_role.strip():
        return [raw_role.strip()]
    return ["viewer"]


def _row_to_user(row: sqlite3.Row) -> dict:
    roles = _parse_roles(row["role"], row["roles"] if "roles" in row.keys() else "")
    return {
        "emp_no": row["emp_no"],
        "name": row["name"],
        "role": roles[0],          # 主角色（兼容存量单值语义）
        "roles": roles,            # 全量角色集（v1.8 多角色）
        "default_workspace": row["default_workspace"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def get_user(emp_no: str, db_path: Path | None = None) -> Optional[dict]:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE emp_no = ?", (emp_no,)).fetchone()
        return _row_to_user(row) if row else None


def _admin_accounts() -> set[str]:
    raw = os.environ.get("SG_ADMIN_ACCOUNTS", "")
    return {a.strip() for a in raw.split(",") if a.strip()}


def _has_admin(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    return row is not None


def upsert_user(emp_no: str, name: str = "", db_path: Path | None = None) -> dict:
    """登录时落用户：新建（默认 viewer）或刷新姓名与登录时间。

    bootstrap 规则（防锁死）：
    - SG_ADMIN_ACCOUNTS 环境变量（逗号分隔 AD 账号）预置 admin
    - 库中无任何 admin 时，首个登录用户自动成为 admin（记审计）
    """
    init_db(db_path)
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE emp_no = ?", (emp_no,)).fetchone()
        if row is None:
            role = "viewer"
            if emp_no in _admin_accounts():
                role = "admin"
            elif not _has_admin(conn):
                role = "admin"  # 首个登录用户兜底成为 admin
            conn.execute(
                "INSERT INTO users (emp_no, name, role, default_workspace, created_at, last_login_at)"
                " VALUES (?, ?, ?, '', ?, ?)",
                (emp_no, name, role, now, now),
            )
            if role == "admin":
                conn.execute(
                    "INSERT INTO audit_log (emp_no, action, target, detail, created_at)"
                    " VALUES (?, 'bootstrap_admin', ?, '', ?)",
                    (emp_no, emp_no, now),
                )
        else:
            role = row["role"]
            # 环境变量提升：已存在用户被加入 SG_ADMIN_ACCOUNTS 时同步提权
            if role != "admin" and emp_no in _admin_accounts():
                role = "admin"
                conn.execute(
                    "INSERT INTO audit_log (emp_no, action, target, detail, created_at)"
                    " VALUES (?, 'bootstrap_admin', ?, 'env_promote', ?)",
                    (emp_no, emp_no, now),
                )
            conn.execute(
                "UPDATE users SET name = ?, role = ?, last_login_at = ? WHERE emp_no = ?",
                (name or row["name"], role, now, emp_no),
            )
    return get_user(emp_no, db_path)


def list_users(db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return [_row_to_user(r) for r in rows]


def set_role(emp_no: str, role: str, actor: str, db_path: Path | None = None) -> bool:
    """设置单角色（兼容存量接口）：等价于 set_roles([role])。"""
    return set_roles(emp_no, [role], actor, db_path)


def set_roles(emp_no: str, roles: list[str], actor: str, db_path: Path | None = None) -> bool:
    """设置角色集（v1.8 多角色）：逗号分隔写入 roles 列，主角色同步 role 列。"""
    roles = [r.strip() for r in roles if r.strip()]
    if not roles:
        raise ValueError("角色集不能为空")
    for r in roles:
        if r not in VALID_ROLES:
            raise ValueError(f"非法角色: {r}（应为 {VALID_ROLES}）")
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE users SET roles = ?, role = ? WHERE emp_no = ?",
            (",".join(roles), roles[0], emp_no))
        if cur.rowcount == 0:
            return False
        conn.execute(
            "INSERT INTO audit_log (emp_no, action, target, detail, created_at)"
            " VALUES (?, 'set_role', ?, ?, ?)",
            (actor, emp_no, ",".join(roles), _now()),
        )
        return True


def set_default_workspace(emp_no: str, workspace: str, db_path: Path | None = None) -> bool:
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE users SET default_workspace = ? WHERE emp_no = ?", (workspace, emp_no))
        return cur.rowcount > 0


# ══════════════════════════════════════════════════════════
# 工作区授权
# ══════════════════════════════════════════════════════════

def grant_workspace(workspace_name: str, emp_no: str, granted_by: str,
                    db_path: Path | None = None) -> bool:
    """授权（幂等：已授权返回 False）。"""
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO workspace_grants (workspace_name, emp_no, granted_by, created_at)"
                " VALUES (?, ?, ?, ?)",
                (workspace_name, emp_no, granted_by, _now()),
            )
        except sqlite3.IntegrityError:
            return False
        conn.execute(
            "INSERT INTO audit_log (emp_no, action, target, detail, created_at)"
            " VALUES (?, 'grant_workspace', ?, ?, ?)",
            (granted_by, workspace_name, emp_no, _now()),
        )
        return True


def revoke_workspace(workspace_name: str, emp_no: str, actor: str,
                     db_path: Path | None = None) -> bool:
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM workspace_grants WHERE workspace_name = ? AND emp_no = ?",
            (workspace_name, emp_no),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "INSERT INTO audit_log (emp_no, action, target, detail, created_at)"
            " VALUES (?, 'revoke_workspace', ?, ?, ?)",
            (actor, workspace_name, emp_no, _now()),
        )
        return True


def list_grants(emp_no: str = "", workspace_name: str = "",
                db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    sql = "SELECT * FROM workspace_grants"
    conds, params = [], []
    if emp_no:
        conds.append("emp_no = ?")
        params.append(emp_no)
    if workspace_name:
        conds.append("workspace_name = ?")
        params.append(workspace_name)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at"
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def has_grant(emp_no: str, workspace_name: str, db_path: Path | None = None) -> bool:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM workspace_grants WHERE emp_no = ? AND workspace_name = ?",
            (emp_no, workspace_name),
        ).fetchone()
        return row is not None


# ══════════════════════════════════════════════════════════
# 审计
# ══════════════════════════════════════════════════════════

def audit(emp_no: str, action: str, target: str = "", detail: str = "",
          db_path: Path | None = None):
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_log (emp_no, action, target, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (emp_no, action, target, detail, _now()),
        )


def list_audit(limit: int = 100, db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
# 执行队列
# ══════════════════════════════════════════════════════════

def enqueue_run(emp_no: str, scope: str, target: str, env: str, plan_id: str,
                breakpoints: list[str], strict_deps: bool, workspace: str = "",
                status: str = "queued", db_path: Path | None = None,
                prep_only: bool = False, skip_upstream_verify: bool = False,
                account_override: str = "", overrides=None) -> int:
    """入队，返回队列项 id（status 可为 queued/running）。

    T-114：轻量选项持久化——此前只存 strict_deps/breakpoints，排队后重放
    静默丢失 prep_only/skip_upstream_verify/account_override（用户选择）。
    T-312：overrides（确认弹窗变量覆盖输入值）同样持久化，排队重放不丢。
    """
    import json as _json
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO run_queue (emp_no, scope, target, env, plan_id, breakpoints,"
            " strict_deps, workspace, status, created_at,"
            " prep_only, skip_upstream_verify, account_override, overrides)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (emp_no, scope, target, env, plan_id, _json.dumps(breakpoints),
             1 if strict_deps else 0, workspace, status, _now(),
             1 if prep_only else 0, 1 if skip_upstream_verify else 0, account_override,
             _json.dumps(overrides or [], ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def list_run_queue(db_path: Path | None = None) -> list[dict]:
    """全部排队/运行中条目（FIFO 序）。"""
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM run_queue WHERE status IN ('queued', 'running') ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_run_queue_item(item_id: int, db_path: Path | None = None) -> Optional[dict]:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM run_queue WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def update_run_queue(item_id: int, status: str, db_path: Path | None = None,
                     started: bool = False, finished: bool = False) -> bool:
    init_db(db_path)
    sets, params = ["status = ?"], [status]
    if started:
        sets.append("started_at = ?")
        params.append(_now())
    if finished:
        sets.append("finished_at = ?")
        params.append(_now())
    params.append(item_id)
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(f"UPDATE run_queue SET {', '.join(sets)} WHERE id = ?", params)
        return cur.rowcount > 0


def fail_stale_running(db_path: Path | None = None) -> int:
    """进程启动时调用：上一生命周期遗留的 running 目标记 failed（进程已死）。"""
    init_db(db_path)
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE run_queue SET status = 'failed', finished_at = ?"
            " WHERE status = 'running'", (_now(),))
        return cur.rowcount
