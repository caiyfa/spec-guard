"""open/ — SpecGuard 对外开放面命名空间（M13 §4.5/§5.1，T-083/T-085）。

分层纪律：
- L0（本命名空间全部工具）：只读开放面，side_effect 一律 none（纯读运行时强制）。
  任何写动作（promote/草稿晋升/禅道写/图谱索引构建/平台管理/面试过程）不得在本
  命名空间出现——L2 永不开放清单的能力在 open/ 物理不存在。
- 图谱读面纪律：只读存量索引（graph_index.db），不调 ensure_fresh/rebuild——
  索引构建是 L2 不开放能力；索引缺失或 stale 时返回 stale 标记（诚实降级）。
- 草稿物理不可达：open/ 工具只读 specs/（基线）+ changes/（冻结产物）+
  scenarios/（已入库）+ workbench.db 台账，不触碰 drafts/ 私有区。

本模块承载 open/ 各工具共享的只读辅助（工作区解析/changes 扫描/图谱只读打开）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# 工作区名称校验复用 specstd.workspace 黑名单口径（防路径穿越）


def resolve_workspace_root(name: str = "") -> tuple[Optional[Path], str]:
    """解析工作区根：显式 name 优先（白名单校验），否则上下文/激活工作区。

    Returns:
        (root, workspace_name)；不可用时 (None, "")。
    """
    from specstd.workspace import (_validate_name, get_active_workspace,
                                 get_context_workspace, get_workspace)

    ws_name = (name or "").strip()
    info = None
    if ws_name:
        if _validate_name(ws_name) is not None:
            return None, ""
        info = get_workspace(ws_name)
    else:
        ctx = get_context_workspace() or ""
        if ctx:
            info = get_workspace(ctx)
        if info is None:
            info = get_active_workspace()
    if info is None:
        return None, ""
    return info.root, info.name


def changes_root(root: Path) -> list[Path]:
    """delta 目录候选根：.specflow/changes（S5 冻结产物正式路径）优先，回退 changes/。"""
    bases = [Path(root) / ".specflow" / "changes", Path(root) / "changes"]
    return [b for b in bases if b.is_dir()]


def delta_dirs(root: Path) -> list[Path]:
    """扫描全部 delta 目录（两处候选根去重）。"""
    seen: set = set()
    result: list[Path] = []
    for base in changes_root(root):
        for d in sorted(base.iterdir()):
            if d.is_dir() and d.name not in seen:
                seen.add(d.name)
                result.append(d)
    return result


def delta_dir(root: Path, delta_id: str) -> Optional[Path]:
    """按代号定位 delta 目录（白名单校验防路径穿越）。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", delta_id or ""):
        return None
    for base in changes_root(root):
        d = base / delta_id
        if d.is_dir():
            return d
    return None


def is_frozen(delta_path: Path) -> bool:
    """冻结凭证存在性校验（FREEZE.yaml，铁律 3 同口径）。"""
    return (delta_path / "FREEZE.yaml").is_file()


def frozen_deltas(root: Path) -> list[dict]:
    """已冻结 delta 清单：{delta_id, frozen_at, spec_sha, interview_id, workspace}。"""
    out: list[dict] = []
    import yaml
    for d in delta_dirs(root):
        mark = d / "FREEZE.yaml"
        if not mark.is_file():
            continue
        try:
            data = yaml.safe_load(mark.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        out.append({
            "delta_id": d.name,
            "frozen_at": data.get("frozen_at", ""),
            "spec_sha": data.get("spec_sha", ""),
            "interview_id": data.get("interview_id", ""),
            "workspace": data.get("workspace", ""),
        })
    return sorted(out, key=lambda x: x["delta_id"])


def open_graph(root: Path) -> tuple[Optional[object], dict]:
    """只读打开图谱索引（不保鲜、不重建——索引构建是 L2 不开放能力）。

    Returns:
        (store 或 None, status)：status 含 stale 标记；索引缺失时 store=None。
    """
    try:
        from graph_index.service import index_path, status
        from graph_index.store import GraphStore
    except Exception:
        return None, {"available": False, "reason": "graph_index 不可用"}
    st = status(root)
    db = index_path(root)
    if not db.is_file():
        return None, {"available": False, "stale": True, "reason": "索引未构建"}
    try:
        store = GraphStore(db)
    except Exception as e:
        return None, {"available": False, "stale": True, "reason": f"索引打开失败: {e}"}
    return store, {"available": True, "stale": bool(st.get("stale")),
                   "built_at": st.get("built_at")}


def read_text(path: Path, limit: int = 200_000) -> str:
    """安全读文本（超限截断，防巨文件打爆工具结果）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) > limit:
        return text[:limit] + f"\n…[截断，全文 {len(text)} 字符]"
    return text
