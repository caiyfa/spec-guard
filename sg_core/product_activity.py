"""product_activity — 产物活动流水（T-1020 F1）。

每次写动作一条流水：session_id/emp_no/workspace 自动取 contextvar（工具层
零传参——如同 Java ThreadLocal 上下文，工具无需显式接收会话/用户），
显式参数覆盖（测试/非 agent 路径用）。

与 product_index（T-1000 F3）的分工：
- product_index 只记「产出过」（path → session 反查），无版本无内容——并存
  过渡一个迭代后废弃（总控人 08-26 拍板）
- product_activity 是「活动流水」事实源：版本链（version_no 按 workspace+path
  递增）+ 全文快照（content 留档，reset 误删后可恢复——20260825_151821_3178914e
  会话 draft reset 事故根治）

动作词表（写路径诚实上报，不写死枚举约束）：
  create / patch / overwrite / undo / promote / promote_batch / discard / reset_delete

落 workbench.db（复用 sg_core.user_store 连接与 DB_PATH）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sg_core.user_store import DB_LOCK, db_connect, init_db


def _ensure_table():
    init_db()
    with DB_LOCK, db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_path TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                emp_no TEXT NOT NULL DEFAULT '',
                workspace TEXT NOT NULL DEFAULT '',
                version_no INTEGER NOT NULL DEFAULT 1,
                size INTEGER,
                sha TEXT NOT NULL DEFAULT '',
                content TEXT,
                created_at TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pa_session ON product_activity(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pa_path ON product_activity(workspace, product_path)")


def _ctx_defaults() -> tuple[str, str, str]:
    """contextvar 取值链：会话/工号/工作区（无上下文时诚实留空）。

    workspace 兼容两链路：请求 contextvar（workbench X-SG-Workspace 透传）
    优先；无 contextvar 时回退注册表激活工作区（MCP/CLI 路径——与
    drafts_dir() 落盘解析同源，保证写入与查询口径一致）。
    """
    session_id = emp_no = workspace = ""
    try:
        from sg_core.session_context import current_session_id
        session_id = current_session_id()
    except Exception:
        pass
    try:
        from sg_core.emp_context import current_emp_no
        emp_no = current_emp_no()
    except Exception:
        pass
    try:
        from specstd.workspace import get_context_workspace
        workspace = get_context_workspace() or ""
    except Exception:
        workspace = ""
    if not workspace:
        try:
            from specstd.workspace import get_active_workspace
            info = get_active_workspace()
            workspace = info.name if info else ""
        except Exception:
            workspace = ""
    return session_id, emp_no, workspace


def record_activity(product_path: str, action: str,
                    session_id: str = None, emp_no: str = None, workspace: str = None,
                    content: str = "") -> dict | None:
    """写入一条活动流水。

    session_id/emp_no/workspace 缺省（None）时自动取 contextvar；显式传值覆盖
    （含空串——纯 API 路径无会话时诚实留空）。

    version_no = 同 (workspace, product_path) 已有最大版本 +1。
    返回写入行（含 version_no）；product_path 为空时静默忽略返回 None。
    """
    if not product_path:
        return None
    if session_id is None or emp_no is None or workspace is None:
        sid, emp, ws = _ctx_defaults()
        session_id = session_id if session_id is not None else sid
        emp_no = emp_no if emp_no is not None else emp
        workspace = workspace if workspace is not None else ws

    size = len(content) if content else None
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12] if content else ""

    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) FROM product_activity"
            " WHERE workspace=? AND product_path=?",
            (workspace, product_path)).fetchone()
        version_no = (row[0] if row else 0) + 1
        created_at = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO product_activity"
            " (product_path,action,session_id,emp_no,workspace,version_no,size,sha,content,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (product_path, action, session_id, emp_no, workspace,
             version_no, size, sha, content or "", created_at))
    return {
        "product_path": product_path, "action": action, "session_id": session_id,
        "emp_no": emp_no, "workspace": workspace, "version_no": version_no,
        "size": size, "sha": sha, "created_at": created_at,
    }


def _row(r) -> dict:
    d = dict(r)
    if d.get("size") is None:
        d["size"] = 0
    return d


def by_session(session_id: str) -> list[dict]:
    """某会话的全部写活动（时间正序）。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM product_activity WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
    return [_row(r) for r in rows]


def version_chain(workspace: str, product_path: str) -> list[dict]:
    """某产物的版本链（正序：v1 → vN），content 供恢复。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM product_activity WHERE workspace=? AND product_path=?"
            " ORDER BY version_no", (workspace, product_path)).fetchall()
    return [_row(r) for r in rows]


def current_version(workspace: str, product_path: str) -> dict | None:
    """最新版本记录（含 content）；无记录返回 None。"""
    chain = version_chain(workspace, product_path)
    return chain[-1] if chain else None


def session_draft_files(session_id: str, workspace: str = "") -> set[str]:
    """某会话写过的草稿文件集（reset 会话收窄的数据依赖）。

    workspace 为空时不按工作区过滤（调用方单工作区场景）。
    """
    _ensure_table()
    sql = ("SELECT DISTINCT product_path FROM product_activity"
           " WHERE session_id=? AND product_path LIKE 'drafts/%'")
    args: list = [session_id]
    if workspace:
        sql += " AND workspace=?"
        args.append(workspace)
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {r[0] for r in rows}


def latest_by_workspace(workspace: str, product_type_path: str = "drafts/%") -> list[dict]:
    """工作区每份产物的最新状态（面板 DB 化数据源）。

    返回行：product_path / action / session_id / emp_no / version_no（最新版）
    / versions（累计版本数）/ size / created_at；按最新活动时间倒序。
    product_type_path 支持 LIKE 通配（drafts/% 默认；scenarios/% 等）。
    """
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            "SELECT t.* FROM product_activity t"
            " JOIN (SELECT product_path, MAX(id) AS max_id FROM product_activity"
            "       WHERE workspace=? AND product_path LIKE ?"
            "       GROUP BY product_path) m ON t.id = m.max_id"
            " ORDER BY t.id DESC", (workspace, product_type_path)).fetchall()
        counts = conn.execute(
            "SELECT product_path, COUNT(*) FROM product_activity"
            " WHERE workspace=? AND product_path LIKE ?"
            " GROUP BY product_path", (workspace, product_type_path)).fetchall()
    cnt = {r[0]: r[1] for r in counts}
    out = []
    for r in rows:
        d = _row(r)
        d["versions"] = cnt.get(d["product_path"], 1)
        out.append(d)
    return out
