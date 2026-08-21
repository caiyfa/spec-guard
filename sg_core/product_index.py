"""产出物索引（T-1000 F3）：产物 → 会话/工号/时间/FR 的反查索引。

落 workbench.db（与 notify_configs 同库，复用 sg_core.user_store 连接）：
写路径钩子（agent 写草稿/promote 入库/计划生成/场景保存）各插一条，不改引擎语义。
反查：by-session / mine（本人查本人）/ trace（按产物路径溯源）。
"""

from __future__ import annotations

from datetime import datetime

from sg_core.user_store import _connect, _LOCK, init_db

# 产物类型白注册（不写死枚举——写路径诚实上报，查询侧任意过滤）
PRODUCT_TYPES = ("draft", "scenario", "plan", "doc")


def _ensure_table():
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_path TEXT NOT NULL,
                product_type TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                emp_no TEXT NOT NULL DEFAULT '',
                workspace TEXT NOT NULL DEFAULT '',
                fr_anchor TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_product_path ON product_index(product_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_product_emp ON product_index(emp_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_product_session ON product_index(session_id)")


def record_product(product_path: str, product_type: str, session_id: str = "",
                   emp_no: str = "", workspace: str = "", fr_anchor: str = ""):
    """写入一条产出记录（幂等不强制——同一路径多次产出保留时间线）。"""
    if not product_path:
        return
    _ensure_table()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO product_index (product_path,product_type,session_id,emp_no,workspace,fr_anchor,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (product_path, product_type, session_id, emp_no, workspace, fr_anchor,
             datetime.now().isoformat(timespec="seconds")))


def by_session(session_id: str) -> list[dict]:
    """某会话产出了什么。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM product_index WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    return [dict(r) for r in rows]


def by_emp(emp_no: str, product_type: str = "", date_from: str = "",
           limit: int = 100) -> list[dict]:
    """我的产出（调用方负责「本人查本人/ admin」权限判定）。"""
    _ensure_table()
    sql = "SELECT * FROM product_index WHERE emp_no=?"
    args: list = [emp_no]
    if product_type:
        sql += " AND product_type=?"
        args.append(product_type)
    if date_from:
        sql += " AND created_at>=?"
        args.append(date_from)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 100), 500)))
    with _LOCK, _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def trace(product_path: str) -> list[dict]:
    """产物溯源：这草稿/场景是哪次会话产的（同一路径全部记录，时间正序）。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM product_index WHERE product_path=? ORDER BY id", (product_path,)).fetchall()
    return [dict(r) for r in rows]
