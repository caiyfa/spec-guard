"""信息包新鲜度检测（K-013，仿 spec_baseline 的「记录 → 后比对」模式）。

- check_freshness：逐条目重算内容指纹，比对记录值 → fresh / stale / missing
- discover_related_changes：git 型工作区用记录的 commitId 做 git diff，
  拆「信息包内已变更」+「信息包外相关变更/新增」（local 型无 commit 概念，返回空）
"""

import subprocess
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from services import scenario_meta  # noqa: E402

# 变更发现时忽略的目录/文件（产物与缓存不参与"相关内容"判定）
_IGNORED_PREFIXES = (".specguard/", "__pycache__/", ".git/")
_IGNORED_SUFFIXES = (".pyc",)


def check_freshness(sid: str) -> dict:
    """检查信息包各条目新鲜度。

    返回 {files: [{path, status, stored_sha, current_sha}], base_commit, head_commit}。
    status: fresh（一致）/ stale（内容已变更）/ missing（文件已删除）。
    旧条目 sha 为空（迁移前文件就不存在）→ missing。
    """
    from specstd.workspace import safe_resolve

    meta = scenario_meta.get_meta(sid)
    if not meta:
        return {"files": [], "base_commit": "", "head_commit": "", "error": f"场景不存在: {sid}"}

    files = []
    for entry in meta.get("info_pack") or []:
        path = entry.get("path", "")
        stored = entry.get("sha", "")
        current = ""
        status = "missing"
        resolved = safe_resolve(path) if path else None
        if resolved and resolved.is_file():
            try:
                current = scenario_meta.file_sha(resolved)
                status = "fresh" if current == stored else "stale"
            except Exception:
                status = "missing"
        files.append({
            "path": path,
            "status": status,
            "stored_sha": stored,
            "current_sha": current,
        })

    commits = [e.get("commit") for e in (meta.get("info_pack") or []) if e.get("commit")]
    return {
        "files": files,
        "base_commit": _base_commit(meta),
        "head_commit": scenario_meta.workspace_head_commit(),
        "stale_count": sum(1 for f in files if f["status"] != "fresh"),
        "has_commit": bool(commits),
    }


def _base_commit(meta: dict) -> str:
    """信息包基准 commit：取最早添加条目的 commit（信息包建立时点）。"""
    entries = [e for e in (meta.get("info_pack") or []) if e.get("commit")]
    if not entries:
        return ""
    entries.sort(key=lambda e: e.get("added_at") or "")
    return entries[0].get("commit", "")


def discover_related_changes(sid: str) -> dict:
    """git 型工作区：git diff base_commit HEAD 发现变更，拆信息包内/外。

    返回 {inside_stale: [...], outside_changes: [...], base_commit, head_commit}。
    local 型 / 无 commit 记录 → 两个清单均为空。
    """
    from specstd.workspace import get_active_workspace

    meta = scenario_meta.get_meta(sid)
    if not meta:
        return {"inside_stale": [], "outside_changes": [], "base_commit": "", "head_commit": ""}

    ws = get_active_workspace()
    base = _base_commit(meta)
    if not ws or ws.source_type != "git" or not base:
        return {"inside_stale": [], "outside_changes": [], "base_commit": base,
                "head_commit": scenario_meta.workspace_head_commit()}

    head = scenario_meta.workspace_head_commit()
    if head == base:
        return {"inside_stale": [], "outside_changes": [], "base_commit": base, "head_commit": head}

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base, "HEAD"],
            cwd=str(ws.root), capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return {"inside_stale": [], "outside_changes": [], "base_commit": base,
                    "head_commit": head, "error": proc.stderr.strip()[:200]}
        changed = [ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()]
    except Exception as e:
        return {"inside_stale": [], "outside_changes": [], "base_commit": base,
                "head_commit": head, "error": str(e)}

    pack_set = set(scenario_meta.pack_paths(meta))
    inside, outside = [], []
    for rel in changed:
        if rel.startswith(_IGNORED_PREFIXES) or rel.endswith(_IGNORED_SUFFIXES):
            continue
        if rel in pack_set:
            inside.append(rel)
        else:
            outside.append(rel)

    return {
        "inside_stale": inside,
        "outside_changes": outside,
        "base_commit": base,
        "head_commit": head,
    }
