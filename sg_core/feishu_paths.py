"""feishu_paths — 飞书材料池路径函数（唯一事实源；T-976 下沉中立层解 graph_index↔specflow 环）。

共享材料区：{ws}/.specflow/feishu_pool/（T-949 起 chats/docs/minutes 快照与话题库
落此——工作区公共资产，pool_dirs 的 base 传共享区根即共享读写）；
私有区：.specflow/{emp}/feishu_pool/（watch 配置与话题草案；单用户兼容回退）。
共享区事实源：{workspace}/.specguard/feishu/（复核确认后提升）。
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
