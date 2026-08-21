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
from pathlib import Path

# ══════════════════════════════════════════════════════════
# 路径常量
# ══════════════════════════════════════════════════════════

SPECSTD_DIR = Path(__file__).resolve().parent          # specstd/
SG_ROOT = SPECSTD_DIR.parent                            # 仓库根
WORKSPACES_DIR = SPECSTD_DIR / "workspaces"             # specstd/workspaces/
REGISTRY_PATH = WORKSPACES_DIR / "registry.yaml"        # 注册表
CLONES_DIR = WORKSPACES_DIR / "_clones"                # git 型克隆落点


# ── 请求级工作区上下文（多用户改造，M7）──
# 服务端：X-SG-Workspace header 经中间件注入；asyncio.to_thread / threadpool 均复制 context，
# 因此 agent runtime、MCP 工具、covers 闸在任何下游线程都能读到请求工作区。
_CTX_WORKSPACE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sg_workspace_name", default=None)

# ── 请求级用户上下文（T-014 多会话产物地基）──
# 服务端：get_current_user 认证后注入；产物写读点据此定位私有区（.specguard/{emp}/）。
# 与 workspace 同模式：MCP stdio POC（无用户概念）为空 → 产物落共享区（向后兼容）。
_CTX_EMP_NO: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sg_emp_no", default=None)


def set_context_emp_no(emp_no: str | None):
    """设置请求级用户工号（认证依赖注入）。返回 reset token。"""
    return _CTX_EMP_NO.set(emp_no or None)


def reset_context_emp_no(token):
    """恢复上一用户上下文（请求收尾调用）。"""
    _CTX_EMP_NO.reset(token)


def get_context_emp_no() -> str | None:
    """当前请求上下文中的用户工号（未设置返回 None）。"""
    return _CTX_EMP_NO.get()


def set_context_workspace(name: str | None):
    """设置请求级工作区名（中间件/依赖注入调用）。返回 reset token。"""
    return _CTX_WORKSPACE.set(name or None)


def reset_context_workspace(token):
    """恢复上一上下文（中间件收尾调用）。"""
    _CTX_WORKSPACE.reset(token)


def get_context_workspace() -> str | None:
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




# ══════════════════════════════════════════════════════════
# T-999d 四分块再导出（ws_registry / ws_dirs / ws_git）——
# `from specstd.workspace import X` 与 monkeypatch(specstd.workspace.X) 存量零改动
# ══════════════════════════════════════════════════════════

from specstd.ws_dirs import (  # noqa: F401,E402
    can_read_private,
    drafts_dir,
    get_workspace_root,
    info_packs_dir,
    plans_dir,
    read_agents_md,
    reports_dir,
    run_conformance,
    safe_resolve,
    specflow_dir,
    specguard_dir,
    uploads_dir,
)
from specstd.ws_git import (  # noqa: F401,E402
    _ls_remote_head,
    _remote_cache,
    check_remote_sync,
    get_cached_remote_sync,
    git_log,
    is_sync_dismissed,
    mark_sync_dismissed,
    refresh_remote_sync_async,
    remote_file_marks,
    remote_head_status,
    reset_sync_dismissed,
)
from specstd.ws_registry import (  # noqa: F401,E402
    WorkspaceInfo,
    # 私有名兼容再导出（存量 from specstd.workspace import _X / wsm._X 零改动）
    _clone_path_for,
    _ensure_dirs,
    _git_rev_parse,
    _load_registry,
    _rmtree_force,
    _save_registry,
    _validate_name,
    get_active_workspace,
    get_workspace,
    list_workspaces,
    pull,
    register_git,
    register_local,
    set_active,
    unregister,
)
