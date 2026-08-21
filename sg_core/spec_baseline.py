"""spec 签名基线管理（K-007）。

核心：路由信号从「pulled_at 时间」改为「spec 文件签名相对基线是否有变更」。

复用 specstd.signature 的字段级签名能力：
- spec.md 主体签名（剔除 Changelog）
- api.yaml 每个 path 的入参/出参 schema 字段级签名

基线存 `{workspace}/.specguard/signature_baseline.json`（F-1-1 的 specguard_dir）。

工作流（闭环）：
  注册/激活 → init_baseline（建初始基线，不误触发）
  研发修正 spec → 文件变化
  发消息 → has_spec_changes 检测（当前签名 vs 基线）→ 有变更路由 audit
  审计完成 → update_baseline（默认手动标记；设置开启则自动）→ 等下次变更
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from specstd.signature import (
    compute_signatures,
    detect_changes,
    load_signature_baseline,
    save_signature_baseline,
)
from specstd.workspace import get_workspace_root, specguard_dir

_BASELINE_NAME = "signature_baseline.json"


def _baseline_path(workspace_root: Path) -> Path:
    return specguard_dir(workspace_root) / _BASELINE_NAME


def _resolve_root(workspace_root: Optional[Path]) -> Optional[Path]:
    if workspace_root:
        return Path(workspace_root)
    return get_workspace_root()


def init_baseline(workspace_root: Optional[Path] = None) -> bool:
    """建立/重建签名基线为当前状态（register/activate/审计完成后调用）。

    Returns:
        是否成功（无工作区或无可签名文件时也返回 True，基线为空 dict）。
    """
    ws = _resolve_root(workspace_root)
    if not ws:
        return False
    sigs = compute_signatures(ws)
    save_signature_baseline(sigs, _baseline_path(ws))
    return True


def detect_spec_changes(workspace_root: Optional[Path] = None) -> list[dict]:
    """检测 spec 文件相对基线的变更列表（spec.md/api.yaml 内容级）。

    无基线时自动建立初始基线并返回空（首次不视为变更，避免 register 误触发）。
    """
    ws = _resolve_root(workspace_root)
    if not ws:
        return []
    bp = _baseline_path(ws)
    if not bp.is_file():
        init_baseline(ws)
        return []
    baseline = load_signature_baseline(bp)
    current = compute_signatures(ws)
    return detect_changes(current, baseline)


def has_spec_changes(workspace_root: Optional[Path] = None) -> bool:
    """spec 文件相对基线是否有变更（路由信号主依据）。"""
    return len(detect_spec_changes(workspace_root)) > 0


def update_baseline(workspace_root: Optional[Path] = None) -> bool:
    """审计完成后更新基线为当前签名（默认手动标记已审计的动作）。"""
    return init_baseline(workspace_root)
