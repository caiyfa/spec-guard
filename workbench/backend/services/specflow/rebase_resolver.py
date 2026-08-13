"""rebase_resolver — rebase 中断的界面化恢复服务。

pull --rebase 冲突中断后，用户无需下终端：检测状态 → 展示冲突 →
三选解决（取本地/取远端/智能合并）→ 完成或放弃 rebase。

语义约定（rebase 冲突标记，与 merge 相反）：
- ours   = rebase 目标（onto，即远端/上游版本，<<<<<<< HEAD 侧）
- theirs = 被应用的本地提交（>>>>>>> commit 侧）

智能合并（smart_merge）：以 theirs 为基础版本，保留 ours 独有的新增行；
ours 独有的、与 theirs 某行「去等价模式后相同」的行判定为内容变体丢弃。
等价模式当前覆盖 FR 编号（FR-009 ↔ FR-feat-0817-001 视为同一内容行）。
校验失败（ours 含编号行在 theirs 中无等价对应）→ 拒绝自动合并，返回
needs_manual=True 由用户手动选择。

全部写操作（resolve/abort/continue）经 _audit 留痕。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import get_context_emp_no, get_workspace_root  # noqa: E402

from workbench.backend.services.specflow.delta_committer import _git_run  # noqa: E402

# 冲突段标记（git 标准三向标记）
_CONFLICT_RE = re.compile(
    r"<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>>[^\n]*\n?", re.DOTALL)

# FR 编号等价模式：新编号 FR-{功能}-{迭代}-{流水} 与旧编号 FR-{流水} 视为同一内容行
_FR_NEW_RE = re.compile(r"FR-[A-Za-z0-9-]+-\d{4}-\d+")
_FR_OLD_RE = re.compile(r"FR-\d+")


def _audit(emp: str, action: str, target: str, detail: str = ""):
    if not emp:
        return
    try:
        from services import user_store
        user_store.audit(emp, action, target, detail)
    except Exception:
        pass


def _rebase_state(root: Path) -> str:
    """rebase 状态：none / merge（rebase-merge）/ apply（rebase-apply）。"""
    if (root / ".git" / "rebase-merge").exists():
        return "merge"
    if (root / ".git" / "rebase-apply").exists():
        return "apply"
    return "none"


def _conflict_files(root: Path) -> list[str]:
    """未解决冲突文件列表（git diff --diff-filter=U）。"""
    code, out = _git_run(["git", "diff", "--name-only", "--diff-filter=U"], root)
    if code != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def get_rebase_status(workspace: str = "") -> dict:
    """rebase 中断状态 + 冲突文件列表（含每文件冲突段数）。

    Returns:
        {"ok": bool, "in_progress": bool, "state": str, "onto": str,
         "conflicts": [{"path": str, "segments": int}], "error"?: str}
    """
    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用（未激活或不存在）"}
    state = _rebase_state(root)
    if state == "none":
        return {"ok": True, "in_progress": False, "state": "none",
                "onto": "", "conflicts": []}

    # rebase 目标（onto）：rebase-merge 目录下的 onto 文件
    onto = ""
    onto_file = root / ".git" / "rebase-merge" / "onto"
    if onto_file.is_file():
        onto = onto_file.read_text(encoding="utf-8", errors="replace").strip()[:12]

    conflicts = []
    for f in _conflict_files(root):
        p = root / f
        segments = 0
        if p.is_file():
            try:
                segments = len(_CONFLICT_RE.findall(
                    p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
        conflicts.append({"path": f, "segments": segments})

    return {"ok": True, "in_progress": True, "state": state,
            "onto": onto, "conflicts": conflicts}


def get_conflict_detail(workspace: str = "", path: str = "") -> dict:
    """读取冲突文件的冲突段（ours/theirs 分段，供界面展示与选择）。

    Returns:
        {"ok": bool, "path": str, "segments": [{"ours": str, "theirs": str}],
         "error"?: str}
    """
    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用"}
    if not path or ".." in path or Path(path).is_absolute():
        return {"ok": False, "error": f"非法路径: {path!r}"}
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "error": f"路径越界: {path!r}"}
    if not target.is_file():
        return {"ok": False, "error": f"文件不存在: {path}"}

    content = target.read_text(encoding="utf-8", errors="replace")
    segments = [
        {"ours": m.group(1), "theirs": m.group(2)}
        for m in _CONFLICT_RE.finditer(content)
    ]
    if not segments:
        return {"ok": False, "error": f"文件无冲突标记（可能已解决）: {path}"}
    return {"ok": True, "path": path, "segments": segments}


def _strip_equiv(line: str) -> str:
    """去掉等价模式后的内容指纹（FR 新旧编号 → 同一占位符）。"""
    s = _FR_NEW_RE.sub("FR#", line)
    s = _FR_OLD_RE.sub("FR#", s)
    return s.strip()


def smart_merge(ours: str, theirs: str) -> tuple[str | None, str]:
    """智能合并单个冲突段：theirs 为基础 + ours 独有的新增行。

    ours 独有的含 FR 编号行必须与 theirs 某行内容等价（去编号后相同），
    否则判定为「双方真实改动同一区域」，拒绝自动合并。

    Returns:
        (merged, "") 成功合并；或 (None, reason) 需人工处理。
    """
    ours_lines = [l for l in ours.splitlines() if l.strip()]
    theirs_stripped = theirs.rstrip("\n")
    theirs_keys = {_strip_equiv(l) for l in theirs_stripped.splitlines() if l.strip()}

    for l in ours_lines:
        if (_FR_OLD_RE.search(l) or _FR_NEW_RE.search(l)) and \
                _strip_equiv(l) not in theirs_keys:
            return None, f"ours 独有编号行在 theirs 中无等价对应，需人工判断: {l[:80]}"

    extra = [l for l in ours_lines
             if not _FR_OLD_RE.search(l) and not _FR_NEW_RE.search(l)
             and _strip_equiv(l) not in theirs_keys]
    merged = theirs_stripped + ("\n" + "\n".join(extra) if extra else "") + "\n"
    return merged, ""


def resolve_conflict(workspace: str = "", path: str = "", resolution: str = "",
                     merged_content: str = "", emp_no: str = "") -> dict:
    """解决单个文件冲突并 git add。

    resolution: ours（取远端/目标版本）| theirs（取本地提交版本）|
                smart（智能合并）| custom（merged_content 自定义内容）
    """
    emp = emp_no or get_context_emp_no() or ""
    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用"}
    if _rebase_state(root) == "none":
        return {"ok": False, "error": "当前无 rebase 中断"}
    if not path or ".." in path or Path(path).is_absolute():
        return {"ok": False, "error": f"非法路径: {path!r}"}
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "error": f"路径越界: {path!r}"}

    if resolution in ("ours", "theirs"):
        # git checkout --ours/--theirs 直接取一侧版本
        code, out = _git_run(["git", "checkout", f"--{resolution}", "--", path], root)
        if code != 0:
            return {"ok": False, "error": f"git checkout --{resolution} 失败: {out[:200]}"}
    elif resolution == "smart":
        if not target.is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}
        content = target.read_text(encoding="utf-8", errors="replace")

        def _repl(m: re.Match) -> str:
            merged, reason = smart_merge(m.group(1), m.group(2))
            if merged is None:
                raise ValueError(reason)
            return merged

        try:
            new_content = _CONFLICT_RE.sub(_repl, content)
        except ValueError as e:
            return {"ok": False, "error": f"智能合并失败: {e}", "needs_manual": True}
        if any(mark in new_content for mark in ("<<<<<<<", ">>>>>>>")):
            return {"ok": False, "error": "智能合并后仍有冲突标记残留", "needs_manual": True}
        target.write_text(new_content, encoding="utf-8")
    elif resolution == "custom":
        if not merged_content:
            return {"ok": False, "error": "custom 模式需提供 merged_content"}
        if any(mark in merged_content for mark in ("<<<<<<<", ">>>>>>>")):
            return {"ok": False, "error": "合并内容仍含冲突标记"}
        target.write_text(merged_content, encoding="utf-8")
    else:
        return {"ok": False, "error": f"未知 resolution: {resolution!r}（ours/theirs/smart/custom）"}

    code, out = _git_run(["git", "add", "--", path], root)
    if code != 0:
        return {"ok": False, "error": f"git add 失败: {out[:200]}"}

    _audit(emp, "rebase_resolve", path, detail=f"resolution={resolution}")
    remaining = _conflict_files(root)
    return {"ok": True, "path": path, "resolution": resolution,
            "remaining": remaining}


def abort_rebase(workspace: str = "", emp_no: str = "") -> dict:
    """放弃 rebase（git rebase --abort）：回到 rebase 前状态，本地提交原样保留。"""
    emp = emp_no or get_context_emp_no() or ""
    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用"}
    if _rebase_state(root) == "none":
        return {"ok": False, "error": "当前无 rebase 中断"}
    code, out = _git_run(["git", "rebase", "--abort"], root)
    if code != 0:
        return {"ok": False, "error": f"git rebase --abort 失败: {out[:300]}"}
    _audit(emp, "rebase_abort", "", detail=out[:200])
    return {"ok": True, "note": "已放弃 rebase，回到原始状态（autostash 已自动还原）"}


def continue_rebase(workspace: str = "", emp_no: str = "") -> dict:
    """完成 rebase（git rebase --continue）：前置校验无未解决冲突。"""
    emp = emp_no or get_context_emp_no() or ""
    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用"}
    if _rebase_state(root) == "none":
        return {"ok": False, "error": "当前无 rebase 中断"}
    remaining = _conflict_files(root)
    if remaining:
        return {"ok": False, "error": f"仍有 {len(remaining)} 个文件冲突未解决: {', '.join(remaining[:5])}",
                "remaining": remaining}
    # core.editor=true 跳过编辑器（保留原 commit message）
    code, out = _git_run(["git", "-c", "core.editor=true", "rebase", "--continue"],
                         root, timeout=60)
    if code != 0:
        return {"ok": False, "error": f"git rebase --continue 失败: {out[:400]}"}
    _audit(emp, "rebase_continue", "", detail=out[:200])
    return {"ok": True, "note": "rebase 完成", "output": out[:500]}
