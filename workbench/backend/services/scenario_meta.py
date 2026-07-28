"""场景元数据 CRUD（G2-1）。

存储场景创建向导的元数据：名称、模块、基础信息包（文件列表）。
持久化到 SQLite（workbench.db），与 LLM 配置共用同一数据库。
"""

from __future__ import annotations

import json
from datetime import datetime

from services.user_store import _connect, _LOCK, init_db


def _ensure_table():
    """建表（幂等）。"""
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scenario_meta (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                module TEXT NOT NULL DEFAULT '',
                workspace TEXT NOT NULL DEFAULT '',
                info_pack TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'creating',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)


def _next_id() -> str:
    """生成下一个场景元数据 ID（SG-META-序号）。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM scenario_meta WHERE id LIKE 'SG-META-%' ORDER BY id"
        ).fetchall()
    max_num = 0
    for r in rows:
        try:
            num = int(r["id"].replace("SG-META-", ""))
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            pass
    return f"SG-META-{max_num + 1:04d}"


def create_meta(name: str, module: str, workspace: str = "") -> dict:
    """创建场景元数据记录，返回完整记录。"""
    _ensure_table()
    sid = _next_id()
    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "id": sid,
        "name": name,
        "module": module,
        "workspace": workspace,
        "info_pack": "[]",
        "status": "creating",
        "created_at": now,
        "updated_at": now,
    }
    with _LOCK, _connect() as conn:
        conn.execute("""
            INSERT INTO scenario_meta (id, name, module, workspace, info_pack, status, created_at, updated_at)
            VALUES (:id, :name, :module, :workspace, :info_pack, :status, :created_at, :updated_at)
        """, record)
    record["info_pack"] = []
    return record


def get_meta(sid: str) -> dict | None:
    """获取单个场景元数据。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scenario_meta WHERE id = ?", (sid,)
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def update_info_pack(sid: str, files: list[str]) -> dict | None:
    """更新基础信息包文件列表。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    info_pack_json = json.dumps(files, ensure_ascii=False)
    with _LOCK, _connect() as conn:
        result = conn.execute(
            "UPDATE scenario_meta SET info_pack = ?, updated_at = ? WHERE id = ?",
            (info_pack_json, now, sid),
        )
        if result.rowcount == 0:
            return None
    return get_meta(sid)


def add_to_info_pack(sid: str, file_path: str) -> dict | None:
    """向基础信息包追加单个文件（Agent 调用）。"""
    meta = get_meta(sid)
    if not meta:
        return None
    files = meta.get("info_pack", [])
    if file_path not in files:
        files.append(file_path)
    return update_info_pack(sid, files)


def list_meta(workspace: str = "") -> list[dict]:
    """列出场景元数据（按工作区筛选）。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        if workspace:
            rows = conn.execute(
                "SELECT * FROM scenario_meta WHERE workspace = ? ORDER BY updated_at DESC",
                (workspace,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scenario_meta ORDER BY updated_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_status(sid: str, status: str) -> dict | None:
    """更新场景状态。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
        result = conn.execute(
            "UPDATE scenario_meta SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, sid),
        )
        if result.rowcount == 0:
            return None
    return get_meta(sid)


def _row_to_dict(row) -> dict:
    """将数据库行转为字典（info_pack 反序列化）。"""
    d = dict(row)
    try:
        d["info_pack"] = json.loads(d.get("info_pack", "[]"))
    except (json.JSONDecodeError, TypeError):
        d["info_pack"] = []
    return d
