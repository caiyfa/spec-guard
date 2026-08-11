"""delta/archive.py — delta 归档冻结管理。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import copytree


def archive_delta(changes_dir: Path, archive_root: Path) -> str:
    """冻结后把 delta 从 changes/ 转入 archive/ 只读。

    Args:
        changes_dir: {workspace}/.specflow/changes/{delta_id}
        archive_root: {workspace}/.specflow/archive/

    Returns:
        archive 目标路径字符串
    """
    delta_id = changes_dir.name
    archive_dir = archive_root / delta_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    copytree(str(changes_dir), str(archive_dir), dirs_exist_ok=True)
    # 写入冻结时间戳
    freeze_mark = archive_dir / "FROZEN_AT.txt"
    freeze_mark.write_text(
        datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    return str(archive_dir)


def is_archived(archive_root: Path, delta_id: str) -> bool:
    """检查 delta 是否已归档。"""
    return (archive_root / delta_id).is_dir()


def list_archived(archive_root: Path) -> list[str]:
    """列出已归档 delta 列表。"""
    if not archive_root.is_dir():
        return []
    return sorted(
        d.name for d in archive_root.iterdir()
        if d.is_dir() and d.name.startswith(("grid-", "delta-", "iv-"))
    )