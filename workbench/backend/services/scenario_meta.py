"""场景元数据 CRUD（G2-1）。

存储场景创建向导的元数据：名称、模块、基础信息包（文件列表）。
持久化到 SQLite（workbench.db），与 LLM 配置共用同一数据库。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from services.user_store import _connect, _LOCK, init_db

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import info_packs_dir  # noqa: E402


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


def _info_pack_path(sid: str) -> Path:
    """获取场景 info_pack 文件路径：.specguard/info_packs/{sid}.yaml。"""
    return info_packs_dir() / f"{sid}.yaml"


def _read_info_pack(sid: str) -> list[str]:
    """从文件读取 info_pack 文件列表。"""
    path = _info_pack_path(sid)
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("files", [])
    except Exception:
        return []


def _write_info_pack(sid: str, files: list[str]):
    """写入 info_pack 文件列表到 .specguard/info_packs/{sid}.yaml。"""
    path = _info_pack_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump({"files": files}, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


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
    d = _row_to_dict(row)
    # F-1-2: info_pack 优先从文件读（.specguard/info_packs/），无工作区或文件不存在时回退 DB
    try:
        file_files = _read_info_pack(sid)
        if file_files:
            d["info_pack"] = file_files
    except Exception:
        pass  # 无激活工作区，用 DB 数据
    return d


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
    # F-1-2: 同步写入文件（.specguard/info_packs/），无工作区时仅写 DB
    try:
        _write_info_pack(sid, files)
    except Exception:
        pass
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
