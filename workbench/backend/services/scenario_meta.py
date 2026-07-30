"""场景元数据 CRUD（G2-1）。

存储场景创建向导的元数据：名称、模块、基础信息包（文件列表）。
持久化到 SQLite（workbench.db），与 LLM 配置共用同一数据库。

K-013：info_pack 条目化——每条 {path, sha, commit, added_at}，
sha=内容指纹（sha256[:12]，与 specstd.signature 约定一致），commit=git 型工作区 HEAD。
旧版纯路径列表读取时自动迁移（兼容 str/dict 混合）。
"""

from __future__ import annotations

import hashlib
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


def file_sha(resolved: Path) -> str:
    """单文件内容指纹（sha256[:12]）。"""
    return hashlib.sha256(resolved.read_bytes()).hexdigest()[:12]


def workspace_head_commit() -> str:
    """当前激活工作区 HEAD commit（git 型；local 型/异常返回 ""）。"""
    try:
        from specstd.workspace import get_active_workspace, _git_rev_parse
        ws = get_active_workspace()
        if ws and ws.source_type == "git":
            return _git_rev_parse(ws.root)
    except Exception:
        pass
    return ""


def make_entry(path_str: str) -> dict:
    """为路径构造信息包条目（计算 sha/commit/added_at；文件缺失时 sha=""）。"""
    sha = ""
    try:
        from specstd.workspace import safe_resolve
        resolved = safe_resolve(path_str)
        if resolved and resolved.is_file():
            sha = file_sha(resolved)
    except Exception:
        pass
    return {
        "path": path_str,
        "sha": sha,
        "commit": workspace_head_commit(),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }


def normalize_pack(raw: list) -> list[dict]:
    """兼容迁移：str 条目 → 对象条目（惰性算 sha）；对象条目补全缺失字段。"""
    entries = []
    for item in raw or []:
        if isinstance(item, str):
            entries.append(make_entry(item))
        elif isinstance(item, dict) and item.get("path"):
            entries.append({
                "path": item["path"],
                "sha": item.get("sha", ""),
                "commit": item.get("commit", ""),
                "added_at": item.get("added_at", ""),
            })
    return entries


def pack_paths(meta: dict) -> list[str]:
    """从 meta 提取纯路径列表（消费方便捷函数）。"""
    return [e["path"] for e in (meta.get("info_pack") or []) if isinstance(e, dict) and e.get("path")]


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


def _read_info_pack(sid: str) -> list[dict]:
    """从文件读取 info_pack 条目列表（K-013：str/dict 混合兼容，统一归一化为条目）。"""
    path = _info_pack_path(sid)
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return normalize_pack(data.get("files", []))
    except Exception:
        return []


def _write_info_pack(sid: str, files: list[dict]):
    """写入 info_pack 条目列表到 .specguard/info_packs/{sid}.yaml。"""
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


def update_info_pack(sid: str, files: list) -> dict | None:
    """更新基础信息包文件列表（K-013：接受 str/dict 混合入参，统一归一化为条目）。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    entries = normalize_pack(files)
    info_pack_json = json.dumps(entries, ensure_ascii=False)
    with _LOCK, _connect() as conn:
        result = conn.execute(
            "UPDATE scenario_meta SET info_pack = ?, updated_at = ? WHERE id = ?",
            (info_pack_json, now, sid),
        )
        if result.rowcount == 0:
            return None
    # F-1-2: 同步写入文件（.specguard/info_packs/），无工作区时仅写 DB
    try:
        _write_info_pack(sid, entries)
    except Exception:
        pass
    return get_meta(sid)


def add_to_info_pack(sid: str, file_path: str) -> dict | None:
    """向基础信息包追加单个文件（Agent 调用）。"""
    meta = get_meta(sid)
    if not meta:
        return None
    files = meta.get("info_pack", [])
    if file_path not in [e["path"] for e in files]:
        files.append(make_entry(file_path))
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
    """将数据库行转为字典（info_pack 反序列化 + K-013 条目归一化）。"""
    d = dict(row)
    try:
        d["info_pack"] = normalize_pack(json.loads(d.get("info_pack", "[]")))
    except (json.JSONDecodeError, TypeError):
        d["info_pack"] = []
    return d
