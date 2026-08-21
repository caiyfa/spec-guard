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
import time
from dataclasses import dataclass, field
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

# 工作区名称黑名单（V1 修复）：拒绝路径分隔符/穿越与控制字符，放行中文等
# 任意 Unicode——工作区名本质是注册表 key，仅 git 克隆落点 _clones/{name} 拼目录
_WORKSPACE_NAME_BAD = re.compile(r'[\\/\x00-\x1f<>:"|?*]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                     *[f"COM{i}" for i in range(1, 10)],
                     *[f"LPT{i}" for i in range(1, 10)]}

# 注册表读写锁（V17 修复：并发请求防写坏）
_REGISTRY_LOCK = threading.RLock()

# ── 请求级工作区上下文（多用户改造，M7）──
# 服务端：X-SG-Workspace header 经中间件注入；asyncio.to_thread / threadpool 均复制 context，
# 因此 agent runtime、MCP 工具、covers 闸在任何下游线程都能读到请求工作区。
_CTX_WORKSPACE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sg_workspace_name", default=None)

# ── 请求级用户上下文（T-014 多会话产物地基）──
# 服务端：get_current_user 认证后注入；产物写读点据此定位私有区（.specguard/{emp}/）。
# 与 workspace 同模式：MCP stdio POC（无用户概念）为空 → 产物落共享区（向后兼容）。
_CTX_EMP_NO: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sg_emp_no", default=None)


def set_context_emp_no(emp_no: Optional[str]):
    """设置请求级用户工号（认证依赖注入）。返回 reset token。"""
    return _CTX_EMP_NO.set(emp_no or None)


def reset_context_emp_no(token):
    """恢复上一用户上下文（请求收尾调用）。"""
    _CTX_EMP_NO.reset(token)


def get_context_emp_no() -> Optional[str]:
    """当前请求上下文中的用户工号（未设置返回 None）。"""
    return _CTX_EMP_NO.get()


def set_context_workspace(name: Optional[str]):
    """设置请求级工作区名（中间件/依赖注入调用）。返回 reset token。"""
    return _CTX_WORKSPACE.set(name or None)


def reset_context_workspace(token):
    """恢复上一上下文（中间件收尾调用）。"""
    _CTX_WORKSPACE.reset(token)


def get_context_workspace() -> Optional[str]:
    """当前请求上下文中的工作区名（未设置返回 None）。"""
    return _CTX_WORKSPACE.get()


def resolve_system(system: str = "") -> str:
    """被测系统唯一解析口径（T-971 system 一等公民化）。

    优先级：显式参数 > 当前工作区 system（contextvar / SG_WORKSPACE / 注册表
    active，即 get_active_workspace 的解析链）> SPEC_GUARD_SYSTEM 环境变量 >
    "tdm"。此前该口径散落 workbench/MCP 九处各自解析、顺序不一，多系统部署
    下锁死单系统；全仓调用点一律经此收口。

    例外：conftest（pytest 子进程）保持读 SPEC_GUARD_SYSTEM 环境变量——
    runner 按触发工作区注入该变量（子进程契约，见 services.runner._spawn_pytest）。
    """
    if system:
        return system
    try:
        ws = get_active_workspace()
        if ws and ws.system:
            return ws.system
    except Exception:
        pass  # 注册表不可读时降级环境变量口径，不让 system 解析阻断调用方
    return os.environ.get("SPEC_GUARD_SYSTEM", "tdm")


def _validate_name(name: str) -> Optional[str]:
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
    base = CLONES_DIR.resolve()
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

    @property
    def root(self) -> Path:
        """工作区根路径。"""
        if self.source_type == "git":
            if self.local_path:
                p = Path(self.local_path)
                # 自定义克隆落点存绝对路径，默认 _clones/ 存相对路径（向后兼容）
                return p if p.is_absolute() else SG_ROOT / p
            return CLONES_DIR / self.name
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
    # git 型：删除克隆目录——仅限 SpecGuard 自管落点（_clones/ 内）；
    # 自定义落点只注销注册表、不删目录（防误删用户数据）
    if info.source_type == "git" and info.local_path:
        clone_path = Path(info.local_path)
        if not clone_path.is_absolute():
            clone_path = SG_ROOT / clone_path
        try:
            clone_path.resolve().relative_to(CLONES_DIR.resolve())
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
                 clone_dir: str = "") -> dict:
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
                local_path=str(clone_path) if clone_dir else str(clone_path.relative_to(SG_ROOT)),
                last_commit=last_commit,
            )
            registry = _load_registry()
            ws_dict = registry.setdefault("workspaces", {})
            ws_dict[name] = info.to_dict()
            _save_registry(registry)
            return {"ok": False, "error": "合规校验未通过（存在 ERROR）",
                    "report": report.to_dict(), "workspace": info.to_dict()}

    # 注册：默认落点存相对路径，自定义落点存绝对路径
    local_rel = str(clone_path) if clone_dir else str(clone_path.relative_to(SG_ROOT))
    info = WorkspaceInfo(
        name=name, system=system, source_type="git",
        source_url=url, branch=branch,
        local_path=local_rel,
        last_commit=last_commit,
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


def _emp_subdir(sg_dir: Path, emp: str) -> Path:
    """计算用户私有区子目录（T-014）：{sg_dir}/{emp}/。

    emp 含非法字符时净化（防路径穿越，含 .. 拒绝）；空 emp 返回 sg_dir 本身（共享区）。
    """
    if not emp:
        return sg_dir
    # 防路径穿越：.. 直接拒绝（不净化，避免语义歧义）
    if ".." in emp or "/" in emp or "\\" in emp:
        return sg_dir
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", emp).strip(".")
    if not safe:
        return sg_dir
    private = sg_dir / safe
    private.mkdir(parents=True, exist_ok=True)
    _ensure_specguard_meta(private)
    return private


def _resolve_emp(emp: str = "") -> str:
    """解析当前有效 emp：显式参数 > 请求上下文（T-014）。"""
    return emp or (get_context_emp_no() or "")


def specguard_dir(workspace_root: Path = None, custom_path: str = "", emp: str = "",
                  force_shared: bool = False) -> Path:
    """获取工作区的 .specguard 目录（可配置位置 + T-014 emp 维度）。

    custom_path 非空时用自定义位置，否则默认 {workspace}/.specguard/。
    emp 非空（或请求上下文有 emp）时返回用户私有区 {sg}/{emp}/，
    否则返回工作区级共享区（向后兼容）。
    force_shared=True 时无视 emp/上下文强制共享区——天然共享产物
    （reports/ 执行台账、info_packs/ 版本化资产）专用，防 T-014 回归。
    首次创建时自动生成 README + .gitignore。

    Args:
        workspace_root: 工作区根路径（None 时使用当前激活工作区）
        custom_path: 自定义 .specguard 目录位置（空字符串用默认）
        emp: 用户工号（空串时尝试请求上下文；均空 = 共享区）
        force_shared: 强制共享区（忽略 emp 与请求上下文）

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
    if force_shared:
        return sg_dir
    return _emp_subdir(sg_dir, _resolve_emp(emp))


def drafts_dir(emp: str = "") -> Path:
    """Agent 草稿目录（T-014）：私有区 {.specguard}/{emp}/drafts/（未确认），
    无 emp 时回退共享区 {.specguard}/drafts/（兼容存量）。"""
    return specguard_dir(emp=emp) / "drafts"


def plans_dir(emp: str = "") -> Path:
    """测试计划目录（T-014）：未确认计划落私有区 {emp}/plans/，
    无 emp 时回退共享区（确认后共享）。"""
    return specguard_dir(emp=emp) / "plans"


def reports_dir() -> Path:
    """运行报告目录（天然共享产物，不进私有区）：{.specguard}/reports/。

    T-014 回归修复：必须强制共享区——此前 specguard_dir() 无 emp 参数时
    回退请求上下文 emp，Web 登录态下解析到私有区导致报告读取 404。
    """
    return specguard_dir(force_shared=True) / "reports"


def info_packs_dir() -> Path:
    """基础信息包目录（天然共享产物，不进私有区）：{.specguard}/info_packs/。

    T-014 回归修复：与 reports_dir 同因，强制共享区。
    """
    return specguard_dir(force_shared=True) / "info_packs"


def uploads_dir(emp: str = "") -> Path:
    """上传附件目录（T-014）：未确认上传落私有区 {emp}/uploads/。"""
    return specguard_dir(emp=emp) / "uploads"


def specflow_dir(emp: str = "") -> Path:
    """获取工作区的 .specflow 目录（S2，需求侧产物，双系统分离）。

    emp 非空（或请求上下文有 emp）时返回用户私有区 {ws}/.specflow/{emp}/，
    否则返回工作区级共享区 {ws}/.specflow/（向后兼容）。
    specflow_dir 不走 specguard_dir 路径——.specflow/ 是需求侧独立的目录树。
    首次创建时自动生成 README + .gitignore。

    Args:
        emp: 用户工号（空串时尝试请求上下文；均空 = 共享区）

    Returns:
        .specflow 目录路径
    """
    ws = get_workspace_root()
    if not ws:
        raise RuntimeError("无激活工作区")
    sf_dir = ws / ".specflow"
    sf_dir.mkdir(parents=True, exist_ok=True)
    _ensure_specguard_meta(sf_dir)
    return _emp_subdir(sf_dir, _resolve_emp(emp))


def can_read_private(owner_emp: str, current_emp: str, is_admin: bool = False) -> bool:
    """私有区越权读校验（T-014）：仅归属用户本人 + admin 可读，确定性拒绝。

    owner_emp 为空（共享区产物）不适用私有校验——返回 False 表示
    调用方不应走私有读取路径（应走共享区）。
    """
    if not owner_emp:
        return False
    if is_admin:
        return True
    return bool(current_emp) and owner_emp == current_emp


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


def _resolve_git_workspace(name: Optional[str] = None) -> tuple[Optional[WorkspaceInfo], Optional[Path]]:
    """解析 git 型工作区及其克隆根。非 git / 不存在返回 (None, None)。"""
    if name:
        info = get_workspace(name)
    else:
        info = get_active_workspace()
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


def git_log(name: Optional[str] = None, limit: int = 50) -> dict:
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
        "local_head": _git_rev_parse(path),
        "ahead": ahead,
        "behind": behind,
        "unpushed": unpushed,
        "rebase_in_progress": rebase_in_progress,
    }


def _ls_remote_head(info: WorkspaceInfo, path: Path) -> str:
    """ls-remote 获取远程分支 HEAD（12 位 SHA，失败返回空）。"""
    rc, out = _git_run(["git", "ls-remote", "origin", f"refs/heads/{info.branch}"],
                       path, timeout=10)
    if rc == 0 and out.split():
        return out.split()[0][:12]
    return ""


def remote_head_status(name: Optional[str] = None) -> dict:
    """获取 git 工作区远程 HEAD 状态（ls-remote，实时无缓存——页面级调用）。

    返回 {remote_known, remote_head, local_head, synced}
    remote_known=False 表示无法访问远程（网络/认证失败）——调用方应静默降级。
    """
    info, path = _resolve_git_workspace(name)
    if info is None:
        return {"remote_known": False, "remote_head": "", "local_head": "", "synced": False}
    remote_head = _ls_remote_head(info, path)
    local_head = _git_rev_parse(path)
    return {
        "remote_known": bool(remote_head),
        "remote_head": remote_head,
        "local_head": local_head,
        "synced": bool(remote_head) and remote_head == local_head,
    }


def check_remote_sync(name: Optional[str] = None, force: bool = False) -> dict:
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

        remote_head = _ls_remote_head(info, path)
        local_head = _git_rev_parse(path)
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


def get_cached_remote_sync(name: Optional[str] = None) -> Optional[dict]:
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


def refresh_remote_sync_async(name: Optional[str] = None):
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


def remote_file_marks(paths: list, name: Optional[str] = None) -> dict:
    """检查工作区文件相对远程仓库的状态，返回 {path: 标记}。

    标记：'' | '[远程已更新]' | '[远程不存在]'
    - [远程已更新]：远程分支中该文件存在且内容与本地当前内容不同（含未提交修改）
    - [远程不存在]：远程分支中不存在该文件（本地新增未推送 / 远程已删除）
    - 非 git / 远程不可达 / fetch 失败 / 远程与本地同步 → ''（静默降级，
      不阻塞工具、不向 Agent 注入错误信息）
    """
    marks = {p: "" for p in paths}
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


def mark_sync_dismissed(name: Optional[str] = None) -> str:
    """标记某工作区为「用户已拒绝同步」，本次会话不再提醒远端更新。

    返回被标记的工作区名（无激活工作区时返回空串）。
    """
    if not name:
        info = get_active_workspace()
        if not info:
            return ""
        name = info.name
    with _dismiss_lock:
        _sync_dismissed.add(name)
    return name


def is_sync_dismissed(name: Optional[str] = None) -> bool:
    """某工作区是否已被标记为拒绝同步（read_spec 据此静默远程提示）。"""
    if not name:
        info = get_active_workspace()
        if not info:
            return False
        name = info.name
    with _dismiss_lock:
        return name in _sync_dismissed


def reset_sync_dismissed() -> None:
    """清空会话级同步决策状态（测试用，生产不需调用）。"""
    with _dismiss_lock:
        _sync_dismissed.clear()
