"""migrate_drafts_emp — T-014 存量 drafts 按会话 emp_no 归位。

背景：v1.7 前草稿落 {ws}/.specguard/drafts/（工作区级共享）；T-014 后
未确认草稿应落私有区 {ws}/.specguard/{emp}/drafts/。

归位逻辑：扫描全部会话 JSONL（agent/sessions/{emp}/.../*.jsonl），
从 tool 消息内容中提取被引用/生成的草稿文件名（draft 文件名形如
ST-XXX-001.yaml / PP-XXX-001.yaml 等），按会话归属 emp 迁入其私有区。
无法归属的文件保留共享区（兼容存量读取）。

用法：python scripts/migrate_drafts_emp.py [--ws-root <工作区根>] [--sessions-root <会话根>]
默认 ws-root = 当前激活工作区根；sessions-root = {SG_ROOT}/agent/sessions。
"""

import argparse
import json
import re
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

from specstd.workspace import get_workspace_root

# 草稿文件名形态（与 draft_writer 命名一致：模块前缀 + 序号 + .yaml）
_DRAFT_NAME_RE = re.compile(r"\b([A-Z]{2,4}-[A-Z0-9]+-\d{3}\.yaml)\b")


def _iter_session_files(sessions_root: Path):
    """遍历全部会话 JSONL：{sessions_root}/{emp}/{ws}/{sid}.jsonl。"""
    if not sessions_root.is_dir():
        return
    for emp_dir in sorted(sessions_root.iterdir()):
        if not emp_dir.is_dir() or emp_dir.name.startswith("_"):
            continue
        emp = emp_dir.name
        for f in sorted(emp_dir.rglob("*.jsonl")):
            yield emp, f


def _collect_emp_refs(sessions_root: Path) -> dict[str, set[str]]:
    """扫描会话消息中的草稿文件名引用 → {emp: {draft_name}}。"""
    refs: dict[str, set[str]] = {}
    for emp, f in _iter_session_files(sessions_root):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        names = set(_DRAFT_NAME_RE.findall(text))
        if names:
            refs.setdefault(emp, set()).update(names)
    return refs


def migrate(ws_root: Path = None, sessions_root: Path = None) -> tuple[list, list]:
    """执行迁移：共享 drafts 按会话归属迁入 {emp}/drafts/。

    Returns:
        (moved, kept)：moved = 已迁入私有区的文件名；kept = 保留共享区的文件名。
    """
    ws = ws_root or get_workspace_root()
    if ws is None:
        raise RuntimeError("无激活工作区（可用 --ws-root 显式指定）")
    sroot = sessions_root or (SG_ROOT / "agent" / "sessions")
    shared_drafts = ws / ".specguard" / "drafts"
    if not shared_drafts.is_dir():
        return [], []

    refs = _collect_emp_refs(sroot)
    moved: list[str] = []
    kept: list[str] = []
    for f in sorted(shared_drafts.glob("*.yaml")):
        owner = next((emp for emp, names in refs.items() if f.name in names), None)
        if not owner:
            kept.append(f.name)  # 无归属保留共享区
            continue
        target = ws / ".specguard" / owner / "drafts"
        target.mkdir(parents=True, exist_ok=True)
        dest = target / f.name
        if not dest.exists():
            f.rename(dest)
        else:
            # 目标已存在：保留新文件（私有区优先），共享区旧文件删除
            f.unlink(missing_ok=True)
        moved.append(f.name)
    return moved, kept


def main():
    parser = argparse.ArgumentParser(description="存量 drafts 按会话 emp_no 归位（T-014）")
    parser.add_argument("--ws-root", default="", help="工作区根路径（默认当前激活工作区）")
    parser.add_argument("--sessions-root", default="", help="会话根（默认 SG_ROOT/agent/sessions）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不移动")
    args = parser.parse_args()

    ws = Path(args.ws_root) if args.ws_root else get_workspace_root()
    if ws is None:
        print("错误：无激活工作区，请用 --ws-root 指定", file=sys.stderr)
        sys.exit(1)
    sroot = Path(args.sessions_root) if args.sessions_root else SG_ROOT / "agent" / "sessions"

    if args.dry_run:
        refs = _collect_emp_refs(sroot)
        shared = ws / ".specguard" / "drafts"
        total = len(list(shared.glob("*.yaml"))) if shared.is_dir() else 0
        owned = sum(1 for f in shared.glob("*.yaml") if any(f.name in n for n in refs.values())) if shared.is_dir() else 0
        print(f"共享草稿 {total} 份，可归位 {owned} 份，无归属保留 {total - owned} 份")
        return

    moved, kept = migrate(ws_root=ws, sessions_root=sroot)
    print(f"迁移完成：归位 {len(moved)} 份（{', '.join(moved[:10]) or '无'}），"
          f"保留共享区 {len(kept)} 份（{', '.join(kept[:10]) or '无'}）")


if __name__ == "__main__":
    main()
