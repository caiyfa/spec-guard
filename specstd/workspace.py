"""specstd.workspace — 工作区注册/接入/git 克隆/拉取/激活切换/AGENTS.md 读取。

工作区是 Spec 来源的抽象（§2.3 P1 决策）：
- local 型：用户选择本地文件夹 → 原地注册，只读使用
- git 型：输入仓库 URL → git clone 到 workspaces/_clones/ → 支持拉取更新

注册表 specstd/workspaces/registry.yaml（不入 git 凭据）。
运行时单活工作区：read_spec / covers 校验 / delta 导入全部作用于当前激活工作区。
"""

from __future__ import annotations

import contextvars
import os
import re
import subprocess
import threading
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

# 工作区名称白名单：字母开头，仅字母/数字/下划线/连字符（防路径穿越，V1 修复）
WORKSPACE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

# 注册表读写锁（V17 修复：并发请求防写坏）
_REGISTRY_LOCK = threading.RLock()

# ── 请求级工作区上下文（多用户改造，M7）──
# 服务端：X-SG-Workspace header 经中间件注入；asyncio.to_thread / threadpool 均复制 context，
# 因此 agent runtime、MCP 工具、covers 闸在任何下游线程都能读到请求工作区。
_CTX_WORKSPACE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sg_workspace_name", default=None)


def set_context_workspace(name: Optional[str]):
    """设置请求级工作区名（中间件/依赖注入调用）。返回 reset token。"""
    return _CTX_WORKSPACE.set(name or None)


def reset_context_workspace(token):
    """恢复上一上下文（中间件收尾调用）。"""
    _CTX_WORKSPACE.reset(token)


def get_context_workspace() -> Optional[str]:
    """当前请求上下文中的工作区名（未设置返回 None）。"""
    return _CTX_WORKSPACE.get()


def _validate_name(name: str) -> Optional[str]:
    """校验工作区名称合法性。返回错误消息，合法时返回 None。"""
    if not name or not WORKSPACE_NAME_RE.match(name):
        return (f"工作区名称非法: {name!r}（须字母开头，仅含字母/数字/下划线/连字符，"
                f"长度 1-64）")
    return None


def _clone_path_for(name: str) -> Path:
    """计算 git 工作区克隆落点，并断言解析结果在 _clones/ 之内（V1 修复）。"""
    base = CLONES_DIR.resolve()
    target = (base / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"克隆路径越界（工作区名称非法）: {name!r}")
    return target


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
    with _REGISTRY_LOCK:
        _ensure_dirs()
        if not REGISTRY_PATH.is_file():
            return {"active": "", "workspaces": {}}
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"active": "", "workspaces": {}}


def _save_registry(registry: dict):
    """保存注册表（写临时文件后原子替换，防并发写坏）。"""
    with _REGISTRY_LOCK:
        _ensure_dirs()
        tmp_path = REGISTRY_PATH.with_suffix(".yaml.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(registry, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            f.write("\n")
        os.replace(tmp_path, REGISTRY_PATH)


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
    """解析当前有效工作区（多用户改造，M7）。

    解析顺序：
    ① 请求上下文（X-SG-Workspace header 经中间件注入，多用户 Web 模式）
    ② SG_WORKSPACE 环境变量（MCP stdio POC 模式，Qoder 挂载无用户概念）
    ③ 注册表全局 active（遗留单机模式，仅 admin 可设）
    """
    name = _CTX_WORKSPACE.get() or os.environ.get("SG_WORKSPACE", "").strip()
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
    # git 型：删除克隆目录（删除前断言目标在 _clones/ 之内）
    if info.source_type == "git" and info.local_path:
        try:
            clone_path = _clone_path_for(name)
        except ValueError:
            clone_path = None
        if clone_path and clone_path.exists():
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
    name_err = _validate_name(name)
    if name_err:
        return {"ok": False, "error": name_err}
    try:
        clone_path = _clone_path_for(name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # 如果克隆目录已存在，先清理
    if clone_path.exists():
        import shutil
        shutil.rmtree(clone_path, ignore_errors=True)

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


# ══════════════════════════════════════════════════════════
# .specguard/ 路径解析（F-1-1）
# ══════════════════════════════════════════════════════════

def _is_safe_custom_path(custom_path: str) -> bool:
    """检查自定义路径安全性（防路径穿越）。

    安全规则：
    - 非空
    - 路径组件中不含 .. （防止 ../ 路径穿越）
    - resolve 后为绝对路径
    - 不等于文件系统根目录
    """
    if not custom_path or not custom_path.strip():
        return False
    p = Path(custom_path)
    if ".." in p.parts:
        return False
    resolved = p.resolve()
    if not resolved.is_absolute():
        return False
    if resolved == resolved.parent:  # 文件系统根目录
        return False
    return True


def _ensure_specguard_meta(sg_dir: Path):
    """首次创建时生成 README + .gitignore（幂等）。"""
    gitignore = sg_dir / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(
            "# SpecGuard 运行产物（不提交）\n"
            "reports/\n"
            "drafts/\n\n"
            "# 以下为版本化资产（提交）\n"
            "# plans/\n"
            "# info_packs/\n",
            encoding="utf-8",
        )
    readme = sg_dir / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# .specguard/\n\n"
            "本目录由 SpecGuard 自动管理。\n\n"
            "- `drafts/`：Agent 生成的场景草稿（评审后移入 `../scenarios/`，未评审不入 git）\n"
            "- `plans/`：delta 导入生成的测试计划（版本化）\n"
            "- `reports/`：运行报告（运行产物，不入 git）\n"
            "- `info_packs/`：场景的基础信息包关联（版本化）\n",
            encoding="utf-8",
        )


def specguard_dir(workspace_root: Path = None, custom_path: str = "") -> Path:
    """获取工作区的 .specguard 目录（可配置位置）。

    custom_path 非空时用自定义位置，否则默认 {workspace}/.specguard/。
    首次创建时自动生成 README + .gitignore。

    Args:
        workspace_root: 工作区根路径（None 时使用当前激活工作区）
        custom_path: 自定义 .specguard 目录位置（空字符串用默认）

    Returns:
        .specguard 目录路径

    Raises:
        RuntimeError: 无激活工作区
        ValueError: 非法自定义路径
    """
    ws = workspace_root or get_workspace_root()
    if not ws:
        raise RuntimeError("无激活工作区")

    if custom_path:
        if not _is_safe_custom_path(custom_path):
            raise ValueError(f"非法自定义路径: {custom_path}")
        sg_dir = Path(custom_path).resolve()
    else:
        sg_dir = ws / ".specguard"

    sg_dir.mkdir(parents=True, exist_ok=True)
    _ensure_specguard_meta(sg_dir)
    return sg_dir


def drafts_dir() -> Path:
    """Agent 草稿目录：{.specguard}/drafts/。"""
    return specguard_dir() / "drafts"


def plans_dir() -> Path:
    """测试计划目录：{.specguard}/plans/。"""
    return specguard_dir() / "plans"


def reports_dir() -> Path:
    """运行报告目录：{.specguard}/reports/。"""
    return specguard_dir() / "reports"


def info_packs_dir() -> Path:
    """基础信息包目录：{.specguard}/info_packs/。"""
    return specguard_dir() / "info_packs"
