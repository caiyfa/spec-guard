"""feishu_paths — 飞书材料池路径函数（唯一事实源；T-976 下沉中立层解 graph_index↔specflow 环）。

私有区：.specflow/{emp}/feishu_pool/（随用户，原始快照永不出私有区）
共享区：{workspace}/.specguard/feishu/（随工作区，复核确认后提升）
"""

from __future__ import annotations

from pathlib import Path


def pool_dirs(specflow_emp_base: Path) -> dict:
    """私有区材料池目录（docs/minutes/chats；imgmap 与原文同目录）。"""
    base = Path(specflow_emp_base)
    return {
        "root": base / "feishu_pool",
        "docs": base / "feishu_pool" / "docs",
        "minutes": base / "feishu_pool" / "minutes",
        "chats": base / "feishu_pool" / "chats",
    }


def shared_dirs(workspace_root: Path) -> dict:
    """共享区事实源目录（topics.yaml / material_links.yaml / materials/）。"""
    base = Path(workspace_root) / ".specguard" / "feishu"
    return {
        "root": base,
        "materials": base / "materials",
        "topics_yaml": base / "topics.yaml",
        "links_yaml": base / "material_links.yaml",
    }
