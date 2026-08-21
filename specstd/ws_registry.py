"""ws_registry — 工作区注册表（T-999d 自 specstd/workspace.py 抽出，行为零变化）。

WorkspaceInfo / 注册表读写 / CRUD / local·git 注册 / pull 更新。
打桩兼容：跨块引用一律经 `specstd.workspace` 模块属性解析（_ws.X）——
monkeypatch 单一事实面仍是 specstd.workspace。
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from specstd import workspace as _ws
from specstd.conformance import check_conformance

# 工作区名称黑名单（V1 修复）：拒绝路径分隔符/穿越与控制字符，放行中文等
# 任意 Unicode——工作区名本质是注册表 key，仅 git 克隆落点 _clones/{name} 拼目录
_WORKSPACE_NAME_BAD = re.compile(r'[\\/\x00-\x1f<>:"|?*]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                     *[f"COM{i}" for i in range(1, 10)],
                     *[f"LPT{i}" for i in range(1, 10)]}

# 注册表读写锁（V17 修复：并发请求防写坏）
_REGISTRY_LOCK = threading.RLock()


def _validate_name(name: str) -> str | None:
    """校验工作区名称合法性（黑名单式：防路径穿越，放行中文等任意字符）。

    拒绝：空串/前后空白、"."/".."、路径分隔符（/ \\）、控制字符、Windows 非法
    目录字符（<>:"|?*）与保留名（CON/PRN/AUX/NUL/COM1-9/LPT1-9）、结尾点、
    超长（>128）。返回错误消息，合法时返回 None。
    """
    if not name or name != name.strip():
        return f"工作区名称非法: {name!r}"
    if len(name) > 128:
        return f"工作区名称非法: {name!r}（长度超限）"
    if name in (".", "..") or _WORKSPACE_NAME_BAD.search(name):
        return f"工作区名称非法: {name!r}（含路径穿越或非法字符）"
    if name.endswith(".") or name.split(".")[0].upper() in _WINDOWS_RESERVED:
        return f"工作区名称非法: {name!r}"
    return None


def _clone_path_for(name: str) -> Path:
    """计算 git 工作区克隆落点，并断言解析结果在 _clones/ 之内（V1 修复）。"""
    base = _ws.CLONES_DIR.resolve()
    target = (base / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"克隆路径越界（工作区名称非法）: {name!r}")
    return target


def _rmtree_force(path: Path) -> None:
    """强制删除目录树（Windows 下 git 对象文件只读，普通 rmtree 静默失败）。

    onexc 回调先解除只读再重试（Python 3.12+ onexc，onerror 已移除）。
    注意：onexc 的 path 参数是 str（非 Path），须用 os.chmod。
    """
    import shutil
    import stat

    def _onexc(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, onexc=_onexc)


# ══════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════

@dataclass
class WorkspaceInfo:
    """工作区信息（对应注册表中一条记录）。"""
    name: str
    system: str                        # 关联 systems/{system} 适配包
    source_type: str = "local"         # local / git
    source_path: str = ""              # local 型：本地文件夹路径
    source_url: str = ""               # git 型：仓库 URL
    branch: str = "main"               # git 型：分支
    local_path: str = ""               # git 型：克隆落点（相对仓库根）
    last_commit: str = ""              # 最近一次 commit SHA
    owner_emp: str = ""                # T-1000：注册人工号（自管理归属；空=存量/系统登记）

    @property
    def root(self) -> Path:
        """工作区根路径。"""
        if self.source_type == "git":
            if self.local_path:
                p = Path(self.local_path)
                # 自定义克隆落点存绝对路径，默认 _clones/ 存相对路径（向后兼容）
                return p if p.is_absolute() else _ws.SG_ROOT / p
            return _ws.CLONES_DIR / self.name
        return Path(self.source_path)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "system": self.system,
            "source": {
                "type": self.source_type,
                **({"path": self.source_path} if self.source_type == "local" else {}),
                **({"url": self.source_url, "branch": self.branch,
                    "local_path": self.local_path} if self.source_type == "git" else {}),
            },
            "last_commit": self.last_commit,
            "owner_emp": self.owner_emp,
        }

    @classmethod
    def from_dict(cls, name: str, d: dict) -> WorkspaceInfo:
        source = d.get("source") or {}
        return cls(
            name=name,
            system=d.get("system", ""),
            source_type=source.get("type", "local"),
            source_path=source.get("path", ""),
            source_url=source.get("url", ""),
            branch=source.get("branch", "main"),
            local_path=source.get("local_path", ""),
            last_commit=d.get("last_commit", ""),
            owner_emp=d.get("owner_emp", ""),
        )


# ══════════════════════════════════════════════════════════
# 注册表读写
# ══════════════════════════════════════════════════════════

def _ensure_dirs():
    """确保 workspaces/ 和 _clones/ 目录存在。"""
    _ws.WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    _ws.CLONES_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> dict:
    """加载注册表。不存在时返回空结构。"""
    with _REGISTRY_LOCK:
        _ensure_dirs()
        if not _ws.REGISTRY_PATH.is_file():
            return {"active": "", "workspaces": {}}
        with open(_ws.REGISTRY_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {"active": "", "workspaces": {}}


def _save_registry(registry: dict):
    """保存注册表（写临时文件后原子替换，防并发写坏）。"""
    with _REGISTRY_LOCK:
        _ensure_dirs()
        tmp_path = _ws.REGISTRY_PATH.with_suffix(".yaml.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(registry, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            f.write("\n")
        os.replace(tmp_path, _ws.REGISTRY_PATH)


# ══════════════════════════════════════════════════════════
# 工作区管理
# ══════════════════════════════════════════════════════════

def list_workspaces() -> list[WorkspaceInfo]:
    """列出全部已注册工作区。"""
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    return [WorkspaceInfo.from_dict(name, info) for name, info in ws_dict.items()]


def get_workspace(name: str) -> WorkspaceInfo | None:
    """获取单个工作区信息。"""
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    if name not in ws_dict:
        return None
    return WorkspaceInfo.from_dict(name, ws_dict[name])


def get_active_workspace() -> WorkspaceInfo | None:
    """解析当前有效工作区（多用户改造，M7）。

    解析顺序：
    ① 请求上下文（X-SG-Workspace header 经中间件注入，多用户 Web 模式）
    ② SG_WORKSPACE 环境变量（MCP stdio POC 模式，Qoder 挂载无用户概念）
    ③ 注册表全局 active（遗留单机模式，仅 admin 可设）
    """
    name = _ws._CTX_WORKSPACE.get() or os.environ.get("SG_WORKSPACE", "").strip()
    if name:
        info = get_workspace(name)
        if info:
            return info
    registry = _load_registry()
    active = registry.get("active", "")
    if not active:
        return None
    return get_workspace(active)


def set_active(name: str) -> bool:
    """激活工作区。返回 False 表示工作区不存在。"""
    registry = _load_registry()
    if name not in (registry.get("workspaces") or {}):
        return False
    registry["active"] = name
    _save_registry(registry)
    return True


def unregister(name: str) -> bool:
    """注销工作区。

    git 型工作区会同时删除克隆目录。
    如果是当前激活的工作区，清除激活状态。
    """
    # V1 修复：名称非法直接拒绝（防注册表被篡改后路径穿越删除）
    if _validate_name(name):
        return False
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    if name not in ws_dict:
        return False

    info = WorkspaceInfo.from_dict(name, ws_dict[name])
    # git 型：删除克隆目录——仅限 SpecGuard 自管落点（_clones/ 内）；
    # 自定义落点只注销注册表、不删目录（防误删用户数据）
    if info.source_type == "git" and info.local_path:
        clone_path = Path(info.local_path)
        if not clone_path.is_absolute():
            clone_path = _ws.SG_ROOT / clone_path
        try:
            clone_path.resolve().relative_to(_ws.CLONES_DIR.resolve())
        except ValueError:
            clone_path = None  # 自定义落点：不删
        if clone_path and clone_path.exists():
            _rmtree_force(clone_path)

    del ws_dict[name]
    registry["workspaces"] = ws_dict
    if registry.get("active") == name:
        registry["active"] = ""
    _save_registry(registry)
    return True


# ══════════════════════════════════════════════════════════
# 本地接入
# ══════════════════════════════════════════════════════════

def register_local(name: str, path: str, system: str,
                   activate: bool = True, run_conformance: bool = True,
                   owner_emp: str = "") -> dict:
    """注册本地文件夹工作区。

    参数：
        name: 工作区名称（唯一标识）
        path: 本地 spec 仓库根路径
        system: 关联的被测系统（如 tdm）
        activate: 注册后是否自动激活
        run_conformance: 是否执行合规校验

    返回：
        {ok, workspace?, report?, error?}
    """
    name_err = _validate_name(name)
    if name_err:
        return {"ok": False, "error": name_err}
    ws_path = Path(path).resolve()
    if not ws_path.is_dir():
        return {"ok": False, "error": f"路径不存在或不是目录: {path}"}

    # 合规校验
    report = None
    if run_conformance:
        report = check_conformance(ws_path, name)
        if report.verdict == "REJECT":
            return {"ok": False, "error": "合规校验未通过（存在 ERROR）", "report": report.to_dict()}

    # 注册
    info = WorkspaceInfo(
        name=name, system=system, source_type="local",
        source_path=str(ws_path), owner_emp=owner_emp,
    )
    registry = _load_registry()
    ws_dict = registry.setdefault("workspaces", {})
    ws_dict[name] = info.to_dict()
    if activate:
        registry["active"] = name
    _save_registry(registry)

    result = {"ok": True, "workspace": info.to_dict()}
    if report:
        result["report"] = report.to_dict()
    return result


# ══════════════════════════════════════════════════════════
# Git 接入
# ══════════════════════════════════════════════════════════

def register_git(name: str, url: str, system: str, branch: str = "main",
                 activate: bool = True, run_conformance: bool = True,
                 clone_dir: str = "", owner_emp: str = "") -> dict:
    """注册 git 工作区（克隆仓库）。

    clone_dir 非空时克隆到自定义目录（必须绝对路径），留空克隆到
    _clones/{name}（SpecGuard 自管）。
    自定义落点安全边界：绝不清理已有目录（防误删用户数据）——目录已存在
    且非空时由 git clone 拒绝并原样报错。
    git 认证走系统 git 凭据管理器，SpecGuard 不存储任何凭据。
    """
    name_err = _validate_name(name)
    if name_err:
        return {"ok": False, "error": name_err}
    if clone_dir:
        if not Path(clone_dir).is_absolute():
            return {"ok": False, "error": f"克隆目录必须是绝对路径: {clone_dir}"}
        clone_path = Path(clone_dir).resolve()
    else:
        try:
            clone_path = _clone_path_for(name)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        # 默认落点（SpecGuard 自管）：残留目录先清理
        if clone_path.exists():
            _rmtree_force(clone_path)

    # 执行 git clone（`--` 终止选项解析，防 url 以 `-` 开头造成选项注入）
    try:
        result = subprocess.run(
            ["git", "clone", "--branch", branch, "--", url, str(clone_path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"git clone 失败: {result.stderr.strip()}"}
    except FileNotFoundError:
        return {"ok": False, "error": "git 命令不可用，请确认已安装 Git"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git clone 超时（120s）"}
    except Exception as e:
        return {"ok": False, "error": f"git clone 异常: {e}"}

    # 获取当前 commit
    last_commit = _git_rev_parse(clone_path)

    # 合规校验
    report = None
    if run_conformance:
        report = check_conformance(clone_path, name)
        if report.verdict == "REJECT":
            # 校验失败也保留克隆（用户可以查看报告），但不激活
            info = WorkspaceInfo(
                name=name, system=system, source_type="git",
                source_url=url, branch=branch,
                local_path=str(clone_path) if clone_dir else str(clone_path.relative_to(_ws.SG_ROOT)),
                last_commit=last_commit, owner_emp=owner_emp,
            )
            registry = _load_registry()
            ws_dict = registry.setdefault("workspaces", {})
            ws_dict[name] = info.to_dict()
            _save_registry(registry)
            return {"ok": False, "error": "合规校验未通过（存在 ERROR）",
                    "report": report.to_dict(), "workspace": info.to_dict()}

    # 注册：默认落点存相对路径，自定义落点存绝对路径
    local_rel = str(clone_path) if clone_dir else str(clone_path.relative_to(_ws.SG_ROOT))
    info = WorkspaceInfo(
        name=name, system=system, source_type="git",
        source_url=url, branch=branch,
        local_path=local_rel,
        last_commit=last_commit, owner_emp=owner_emp,
    )
    registry = _load_registry()
    ws_dict = registry.setdefault("workspaces", {})
    ws_dict[name] = info.to_dict()
    if activate:
        registry["active"] = name
    _save_registry(registry)

    result = {"ok": True, "workspace": info.to_dict()}
    if report:
        result["report"] = report.to_dict()
    return result


def pull(name: str) -> dict:
    """拉取 git 工作区的更新（fetch + checkout）。

    记录 commit 变化 → 触发 FR 变更检测。
    """
    name_err = _validate_name(name)
    if name_err:
        return {"ok": False, "error": name_err}
    info = get_workspace(name)
    if not info:
        return {"ok": False, "error": f"工作区 '{name}' 不存在"}
    if info.source_type != "git":
        return {"ok": False, "error": f"工作区 '{name}' 不是 git 型，不支持拉取"}

    clone_path = info.root
    if not clone_path.is_dir():
        return {"ok": False, "error": f"克隆目录不存在: {clone_path}"}

    old_commit = info.last_commit

    # git fetch + checkout + pull（逐步检查返回码，失败不静默——K-009 修复）
    steps = [
        ("fetch", ["git", "fetch", "origin"], 60),
        ("checkout", ["git", "checkout", info.branch], 30),
        ("pull", ["git", "pull", "origin", info.branch], 60),
    ]
    try:
        for step_name, cmd, timeout in steps:
            proc = subprocess.run(cmd, cwd=str(clone_path),
                                  capture_output=True, text=True, timeout=timeout)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()[:300]
                return {"ok": False, "error": f"git {step_name} 失败: {detail}"}
    except Exception as e:
        return {"ok": False, "error": f"git pull 异常: {e}"}

    new_commit = _git_rev_parse(clone_path)

    # 更新注册表
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    if name in ws_dict:
        ws_dict[name]["last_commit"] = new_commit
        _save_registry(registry)

    # 执行合规校验
    report = check_conformance(clone_path, name)

    return {
        "ok": True,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "changed": old_commit != new_commit,
        "report": report.to_dict(),
    }


def _git_rev_parse(path: Path) -> str:
    """获取 git 仓库的当前 commit SHA。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path), capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return ""


