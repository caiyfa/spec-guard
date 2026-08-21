"""ws_dirs — 工作区路径访问与产物目录（T-999d 自 specstd/workspace.py 抽出，行为零变化）。

safe_resolve 防穿越 / AGENTS.md 读取 / 合规校验 / .specguard·.specflow 目录区
（共享区 vs emp 私有区）。
打桩兼容：跨块引用与 get_workspace_root 一律经 _ws 模块属性解析。
"""

from __future__ import annotations

import re
from pathlib import Path

from specstd import workspace as _ws
from specstd.conformance import ConformanceReport, check_conformance
from specstd.schema import FILE_AGENTS_MD

# ══════════════════════════════════════════════════════════
# 路径访问与安全
# ══════════════════════════════════════════════════════════

def get_workspace_root(name: str | None = None) -> Path | None:
    """获取工作区根路径。

    name 为空时使用当前激活的工作区。
    """
    if name:
        info = _ws.get_workspace(name)
    else:
        info = _ws.get_active_workspace()
    if not info:
        return None
    return info.root


def safe_resolve(relative_path: str, name: str | None = None) -> Path | None:
    """安全解析工作区内文件路径（越界访问拒绝）。

    确保解析后的绝对路径在工作区根目录之内。
    返回 None 表示路径越界或工作区不存在。
    """
    root = _ws.get_workspace_root(name)
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

def read_agents_md(name: str | None = None) -> str:
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

def run_conformance(name: str | None = None) -> ConformanceReport:
    """对工作区执行合规校验。

    name 为空时使用当前激活的工作区。
    """
    if name:
        info = _ws.get_workspace(name)
    else:
        info = _ws.get_active_workspace()
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
    return emp or (_ws.get_context_emp_no() or "")


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
    ws = workspace_root or _ws.get_workspace_root()
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
    ws = _ws.get_workspace_root()
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


