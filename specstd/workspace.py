"""specstd.workspace — 工作区注册/接入/git 克隆/拉取/激活切换/AGENTS.md 读取。

工作区是 Spec 来源的抽象（§2.3 P1 决策）：
- local 型：用户选择本地文件夹 → 原地注册，只读使用
- git 型：输入仓库 URL → git clone 到 workspaces/_clones/ → 支持拉取更新

注册表 specstd/workspaces/registry.yaml（不入 git 凭据）。
运行时单活工作区：read_spec / covers 校验 / delta 导入全部作用于当前激活工作区。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from specstd.schema import FILE_AGENTS_MD
from specstd.conformance import check_conformance, ConformanceReport


# ══════════════════════════════════════════════════════════
# 路径常量
# ══════════════════════════════════════════════════════════

SPECSTD_DIR = Path(__file__).resolve().parent          # specstd/
SG_ROOT = SPECSTD_DIR.parent                            # 仓库根
WORKSPACES_DIR = SPECSTD_DIR / "workspaces"             # specstd/workspaces/
REGISTRY_PATH = WORKSPACES_DIR / "registry.yaml"        # 注册表
CLONES_DIR = WORKSPACES_DIR / "_clones"                # git 型克隆落点


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
    pulled_at: str = ""                # 最近一次拉取时间

    @property
    def root(self) -> Path:
        """工作区根路径。"""
        if self.source_type == "git":
            return SG_ROOT / self.local_path if self.local_path else CLONES_DIR / self.name
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
            "pulled_at": self.pulled_at,
        }

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "WorkspaceInfo":
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
            pulled_at=d.get("pulled_at", ""),
        )


# ══════════════════════════════════════════════════════════
# 注册表读写
# ══════════════════════════════════════════════════════════

def _ensure_dirs():
    """确保 workspaces/ 和 _clones/ 目录存在。"""
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    CLONES_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> dict:
    """加载注册表。不存在时返回空结构。"""
    _ensure_dirs()
    if not REGISTRY_PATH.is_file():
        return {"active": "", "workspaces": {}}
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"active": "", "workspaces": {}}


def _save_registry(registry: dict):
    """保存注册表。"""
    _ensure_dirs()
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        yaml.dump(registry, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        f.write("\n")


# ══════════════════════════════════════════════════════════
# 工作区管理
# ══════════════════════════════════════════════════════════

def list_workspaces() -> list[WorkspaceInfo]:
    """列出全部已注册工作区。"""
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    return [WorkspaceInfo.from_dict(name, info) for name, info in ws_dict.items()]


def get_workspace(name: str) -> Optional[WorkspaceInfo]:
    """获取单个工作区信息。"""
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    if name not in ws_dict:
        return None
    return WorkspaceInfo.from_dict(name, ws_dict[name])


def get_active_workspace() -> Optional[WorkspaceInfo]:
    """获取当前激活的工作区。"""
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
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    if name not in ws_dict:
        return False

    info = WorkspaceInfo.from_dict(name, ws_dict[name])
    # git 型：删除克隆目录
    if info.source_type == "git" and info.local_path:
        clone_path = SG_ROOT / info.local_path
        if clone_path.exists():
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)

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
                   activate: bool = True, run_conformance: bool = True) -> dict:
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
        source_path=str(ws_path),
        pulled_at=datetime.now().isoformat(timespec="minutes"),
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
                 activate: bool = True, run_conformance: bool = True) -> dict:
    """注册 git 工作区（克隆仓库到 _clones/）。

    git 认证走系统 git 凭据管理器，SpecGuard 不存储任何凭据。
    """
    clone_path = CLONES_DIR / name

    # 如果克隆目录已存在，先清理
    if clone_path.exists():
        import shutil
        shutil.rmtree(clone_path, ignore_errors=True)

    # 执行 git clone
    try:
        result = subprocess.run(
            ["git", "clone", "--branch", branch, url, str(clone_path)],
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
                local_path=str(clone_path.relative_to(SG_ROOT)),
                last_commit=last_commit,
                pulled_at=datetime.now().isoformat(timespec="minutes"),
            )
            registry = _load_registry()
            ws_dict = registry.setdefault("workspaces", {})
            ws_dict[name] = info.to_dict()
            _save_registry(registry)
            return {"ok": False, "error": "合规校验未通过（存在 ERROR）",
                    "report": report.to_dict(), "workspace": info.to_dict()}

    # 注册
    local_rel = str(clone_path.relative_to(SG_ROOT))
    info = WorkspaceInfo(
        name=name, system=system, source_type="git",
        source_url=url, branch=branch,
        local_path=local_rel,
        last_commit=last_commit,
        pulled_at=datetime.now().isoformat(timespec="minutes"),
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
    info = get_workspace(name)
    if not info:
        return {"ok": False, "error": f"工作区 '{name}' 不存在"}
    if info.source_type != "git":
        return {"ok": False, "error": f"工作区 '{name}' 不是 git 型，不支持拉取"}

    clone_path = info.root
    if not clone_path.is_dir():
        return {"ok": False, "error": f"克隆目录不存在: {clone_path}"}

    old_commit = info.last_commit

    # git fetch + checkout
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=str(clone_path),
                        capture_output=True, text=True, timeout=60)
        subprocess.run(["git", "checkout", info.branch], cwd=str(clone_path),
                        capture_output=True, text=True, timeout=30)
        subprocess.run(["git", "pull", "origin", info.branch], cwd=str(clone_path),
                        capture_output=True, text=True, timeout=60)
    except Exception as e:
        return {"ok": False, "error": f"git pull 异常: {e}"}

    new_commit = _git_rev_parse(clone_path)

    # 更新注册表
    registry = _load_registry()
    ws_dict = registry.get("workspaces") or {}
    if name in ws_dict:
        ws_dict[name]["last_commit"] = new_commit
        ws_dict[name]["pulled_at"] = datetime.now().isoformat(timespec="minutes")
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


# ══════════════════════════════════════════════════════════
# 路径访问与安全
# ══════════════════════════════════════════════════════════

def get_workspace_root(name: Optional[str] = None) -> Optional[Path]:
    """获取工作区根路径。

    name 为空时使用当前激活的工作区。
    """
    if name:
        info = get_workspace(name)
    else:
        info = get_active_workspace()
    if not info:
        return None
    return info.root


def safe_resolve(relative_path: str, name: Optional[str] = None) -> Optional[Path]:
    """安全解析工作区内文件路径（越界访问拒绝）。

    确保解析后的绝对路径在工作区根目录之内。
    返回 None 表示路径越界或工作区不存在。
    """
    root = get_workspace_root(name)
    if root is None:
        return None
    # 规范化路径，防止 ../ 越界
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None  # 越界
    return target


# ══════════════════════════════════════════════════════════
# AGENTS.md 读取
# ══════════════════════════════════════════════════════════

def read_agents_md(name: Optional[str] = None) -> str:
    """读取工作区的 AGENTS.md 全量原文。

    P1 决策：工作区 AGENTS.md 全量原文注入 agent system prompt。
    规则层知识不允许有损压缩。

    name 为空时使用当前激活的工作区。
    """
    agents_path = safe_resolve(FILE_AGENTS_MD, name)
    if agents_path is None or not agents_path.is_file():
        return ""
    return agents_path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════
# 合规校验
# ══════════════════════════════════════════════════════════

def run_conformance(name: Optional[str] = None) -> ConformanceReport:
    """对工作区执行合规校验。

    name 为空时使用当前激活的工作区。
    """
    if name:
        info = get_workspace(name)
    else:
        info = get_active_workspace()
    if not info:
        report = ConformanceReport(verdict="REJECT", workspace=name or "(none)")
        report.add("STRUCT", "ERROR", "工作区不存在或未激活")
        return report

    return check_conformance(info.root, info.name)
