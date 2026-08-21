"""ws_git — 工作区 git 历史与远程同步状态（T-999d 自 specstd/workspace.py 抽出，行为零变化）。

git_log 展示 / 远程新鲜度检查（异步刷新+缓存）/ 文件变更标记 / 同步提示屏蔽。
打桩兼容：跨块引用一律经 _ws 模块属性解析。
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from specstd import workspace as _ws

# ══════════════════════════════════════════════════════════
# Git 历史与远程状态（git log 展示 / Agent 远程新鲜度检查）
# ══════════════════════════════════════════════════════════

# 远程检查 TTL 缓存：{name: {ts, remote_known, remote_head, local_head, synced, fetched}}
# TTL 内不重复 ls-remote/fetch——Agent 一轮对话多次读文件时只做一次网络探测。
_REMOTE_TTL = 60  # 秒
_remote_cache: dict = {}
_remote_lock = threading.Lock()


def _git_run(args: list, path: Path, timeout: int = 15) -> tuple[int, str]:
    """执行 git 命令（cwd=path）。返回 (returncode, stdout)；异常/超时返回 (None, "")。"""
    try:
        proc = subprocess.run(args, cwd=str(path),
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except Exception:
        return None, ""


def _resolve_git_workspace(name: str | None = None) -> tuple[_ws.WorkspaceInfo | None, Path | None]:
    """解析 git 型工作区及其克隆根。非 git / 不存在返回 (None, None)。"""
    if name:
        info = _ws.get_workspace(name)
    else:
        info = _ws.get_active_workspace()
    if not info or info.source_type != "git":
        return None, None
    path = info.root
    if not path.is_dir():
        return None, None
    return info, path


def _parse_git_log(out: str) -> list[dict]:
    """解析 git log --name-status 输出为 commits 列表（git_log 复用）。"""
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        lines = record.split("\n")
        head = lines[0].split("\x1f")
        if len(head) < 7:
            continue
        sha, short_sha, author, email, date = head[:5]
        parents = [p for p in head[5].split() if p]
        message = head[6].strip()
        files = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            status = parts[0][0] if parts else "?"
            # R 状态两段路径："R100\told\tnew" → 取新路径
            fpath = parts[2] if status == "R" and len(parts) >= 3 else (parts[-1] if len(parts) > 1 else "")
            if fpath:
                files.append({"status": status, "path": fpath})
        commits.append({
            "sha": sha, "short_sha": short_sha, "author": author, "email": email,
            "date": date, "parents": parents, "message": message, "files": files,
        })
    return commits


def git_log(name: str | None = None, limit: int = 50) -> dict:
    """获取 git 工作区的提交历史（含每个 commit 的变更文件）。

    返回 {ok, workspace, branch, url, commits, local_head, error?,
          ahead, behind, unpushed}
    commits: [{sha, short_sha, author, email, date, parents, message,
               files: [{status: A|M|D|R, path}]}]
    unpushed: 未推送提交列表（@{u}..HEAD，与 commits 同构）——分叉状态下
              remote_head 不在本地历史中，不能用 remote_head 比较判断未推送。
    ahead/behind: 相对上游分支的领先/落后提交数。
    """
    info, path = _resolve_git_workspace(name)
    if info is None:
        return {"ok": False, "error": "工作区不存在或不是 git 型"}
    limit = max(1, min(int(limit or 50), 200))
    fmt = "%x1e%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%P%x1f%s"
    rc, out = _git_run(["git", "log", "-n", str(limit), "--name-status",
                        f"--pretty=format:{fmt}"], path)
    if rc != 0:
        return {"ok": False, "error": f"git log 失败: {path}"}

    commits = _parse_git_log(out)

    # rebase 中断检测：HEAD detached 时 @{u} 引用解析失败，ahead/behind/unpushed 不可靠
    rebase_in_progress = (path / ".git" / "rebase-merge").exists() or \
                         (path / ".git" / "rebase-apply").exists()

    # ahead/behind 与未推送提交（相对上游分支 @{u}）
    ahead = behind = 0
    unpushed: list[dict] = []
    if not rebase_in_progress:
        rc, ab_out = _git_run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"], path)
        if rc == 0 and ab_out.strip():
            parts = ab_out.split()
            if len(parts) >= 2:
                ahead, behind = int(parts[0]), int(parts[1])
        if ahead > 0:
            rc, u_out = _git_run(
                ["git", "log", "-n", str(min(ahead, limit)), "--name-status",
                 f"--pretty=format:{fmt}", "@{u}..HEAD"], path)
            if rc == 0:
                unpushed = _parse_git_log(u_out)

    return {
        "ok": True,
        "workspace": info.name,
        "branch": info.branch,
        "url": info.source_url,
        "commits": commits,
        "local_head": _ws._git_rev_parse(path),
        "ahead": ahead,
        "behind": behind,
        "unpushed": unpushed,
        "rebase_in_progress": rebase_in_progress,
    }


def _ls_remote_head(info: _ws.WorkspaceInfo, path: Path) -> str:
    """ls-remote 获取远程分支 HEAD（12 位 SHA，失败返回空）。"""
    rc, out = _git_run(["git", "ls-remote", "origin", f"refs/heads/{info.branch}"],
                       path, timeout=10)
    if rc == 0 and out.split():
        return out.split()[0][:12]
    return ""


def remote_head_status(name: str | None = None) -> dict:
    """获取 git 工作区远程 HEAD 状态（ls-remote，实时无缓存——页面级调用）。

    返回 {remote_known, remote_head, local_head, synced}
    remote_known=False 表示无法访问远程（网络/认证失败）——调用方应静默降级。
    """
    info, path = _resolve_git_workspace(name)
    if info is None:
        return {"remote_known": False, "remote_head": "", "local_head": "", "synced": False}
    remote_head = _ws._ls_remote_head(info, path)
    local_head = _ws._git_rev_parse(path)
    return {
        "remote_known": bool(remote_head),
        "remote_head": remote_head,
        "local_head": local_head,
        "synced": bool(remote_head) and remote_head == local_head,
    }


def check_remote_sync(name: str | None = None, force: bool = False) -> dict:
    """Agent 链路用：带 TTL 缓存的远程同步状态检查。

    返回 {git, remote_known, remote_head, local_head, synced, fetched}
    - 远程领先且 fetch 成功时 fetched=True（此后可离线比较文件级差异）
    - fetch 只更新 .git 元数据（refs/remotes、FETCH_HEAD），不改工作区文件；
      失败静默降级（remote_known 仍来自 ls-remote 结果）
    """
    info, path = _resolve_git_workspace(name)
    if info is None:
        return {"git": False, "remote_known": False, "remote_head": "",
                "local_head": "", "synced": False, "fetched": False}
    now = time.time()
    with _remote_lock:
        cached = _remote_cache.get(info.name)
        if cached and not force and now - cached["ts"] < _REMOTE_TTL:
            return {k: cached[k] for k in ("git", "remote_known", "remote_head",
                                           "local_head", "synced", "fetched")}

        remote_head = _ws._ls_remote_head(info, path)
        local_head = _ws._git_rev_parse(path)
        fetched = False
        if remote_head and remote_head != local_head:
            # 远程有新提交 → fetch 一次（TTL 内），此后文件级比较全离线
            frc, _ = _git_run(["git", "fetch", "origin", info.branch], path, timeout=15)
            fetched = frc == 0
        _remote_cache[info.name] = {
            "ts": now, "git": True, "remote_known": bool(remote_head),
            "remote_head": remote_head, "local_head": local_head,
            "synced": bool(remote_head) and remote_head == local_head,
            "fetched": fetched,
        }
        return {k: _remote_cache[info.name][k] for k in ("git", "remote_known",
                "remote_head", "local_head", "synced", "fetched")}


def get_cached_remote_sync(name: str | None = None) -> dict | None:
    """非阻塞读取远程同步缓存——不执行 git，缓存未命中返回 None。

    用于 system prompt 构建等对延迟敏感的路径：首次或缓存过期时返回 None，
    调用方应使用默认提示并通过 refresh_remote_sync_async() 后台刷新。
    """
    info, _ = _resolve_git_workspace(name)
    if info is None:
        return None
    now = time.time()
    with _remote_lock:
        cached = _remote_cache.get(info.name)
        if cached and now - cached["ts"] < _REMOTE_TTL:
            return {k: cached[k] for k in ("git", "remote_known", "remote_head",
                                           "local_head", "synced", "fetched")}
    return None


def refresh_remote_sync_async(name: str | None = None):
    """后台异步刷新远程同步缓存（不阻塞调用方）。

    在 daemon 线程中执行 check_remote_sync(force=True)，结果写入 _remote_cache，
    下次 get_cached_remote_sync() 即可命中。
    """
    info, _ = _resolve_git_workspace(name)
    if info is None:
        return

    def _do_refresh():
        try:
            check_remote_sync(info.name, force=True)
        except Exception:
            pass

    threading.Thread(target=_do_refresh, daemon=True).start()


def remote_file_marks(paths: list, name: str | None = None) -> dict:
    """检查工作区文件相对远程仓库的状态，返回 {path: 标记}。

    标记：'' | '[远程已更新]' | '[远程不存在]'
    - [远程已更新]：远程分支中该文件存在且内容与本地当前内容不同（含未提交修改）
    - [远程不存在]：远程分支中不存在该文件（本地新增未推送 / 远程已删除）
    - 非 git / 远程不可达 / fetch 失败 / 远程与本地同步 → ''（静默降级，
      不阻塞工具、不向 Agent 注入错误信息）
    """
    marks = dict.fromkeys(paths, "")
    if not paths:
        return marks
    info, path = _resolve_git_workspace(name)
    if info is None:
        return marks
    sync = check_remote_sync(info.name)
    if not sync.get("remote_known"):
        return marks  # 远程不可达，静默降级

    if sync.get("synced"):
        # 远程与本地 HEAD 一致：远程存在性 == 本地 HEAD 存在性（无需 fetch）——
        # 文件不在本地 HEAD 即本地新增未推送，远程确实不存在
        for p in paths:
            rrc, _ = _git_run(["git", "rev-parse", f"HEAD:{p}"], path)
            if rrc != 0:
                marks[p] = "[远程不存在]"
        return marks

    if not sync.get("fetched"):
        return marks  # 远程领先但 fetch 失败，无法做文件级比较

    for p in paths:
        # 远程分支中该文件 blob SHA（不存在返回非零）
        rrc, rout = _git_run(["git", "rev-parse", f"origin/{info.branch}:{p}"], path)
        if rrc != 0 or not rout.strip():
            marks[p] = "[远程不存在]"
            continue
        # 本地当前内容 blob SHA（hash-object 不写对象库）
        lrc, lout = _git_run(["git", "hash-object", "--", p], path)
        if lrc != 0 or not lout.strip():
            continue  # 本地文件不存在（调用方已确认存在，防御性跳过）
        if lout.strip() != rout.strip():
            marks[p] = "[远程已更新]"
    return marks


# ══════════════════════════════════════════════════════════
# 会话级同步决策状态（Agent 工具链 sync_workspace 配套）
# ══════════════════════════════════════════════════════════

# 用户拒绝同步某工作区后，本次会话内 read_spec 不再注入远程更新提示。
# 进程级状态——MCP server / Agent runtime 常驻进程期间有效，会话结束即消亡。
_sync_dismissed: set = set()
_dismiss_lock = threading.Lock()


def mark_sync_dismissed(name: str | None = None) -> str:
    """标记某工作区为「用户已拒绝同步」，本次会话不再提醒远端更新。

    返回被标记的工作区名（无激活工作区时返回空串）。
    """
    if not name:
        info = _ws.get_active_workspace()
        if not info:
            return ""
        name = info.name
    with _dismiss_lock:
        _sync_dismissed.add(name)
    return name


def is_sync_dismissed(name: str | None = None) -> bool:
    """某工作区是否已被标记为拒绝同步（read_spec 据此静默远程提示）。"""
    if not name:
        info = _ws.get_active_workspace()
        if not info:
            return False
        name = info.name
    with _dismiss_lock:
        return name in _sync_dismissed


def reset_sync_dismissed() -> None:
    """清空会话级同步决策状态（测试用，生产不需调用）。"""
    with _dismiss_lock:
        _sync_dismissed.clear()
