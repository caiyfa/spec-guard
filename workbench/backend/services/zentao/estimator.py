"""workbench/services/zentao/estimator.py — 故事点评估（M06 G7，T-054）。

评估永远是建议（铁律 1）：estimate 恒 suggested 出生，产品确认（confirmed）
后才允许回写禅道（writeback 走 client.writeback_points_job，REST 仅 product）。

经验基线（M06 §5.4，可调）：
    ADDED=2 点 / MODIFIED=2 点 / REMOVED=1 点；MODIFIED 带决策引用 → 级联 +1
置信度：0.5 基础 + 拆解条目校准 + 历史参照（已确认评估记录）加成，cap 0.95。
"""

from __future__ import annotations

from typing import Optional

from workbench.backend.services.specflow import sf_refs_store

# 经验基线（M06 §5.4 可调常量）
OP_BASE_POINTS = {"ADDED": 2, "MODIFIED": 2, "REMOVED": 1}
CASCADE_POINTS = 1


def _load_manifest(delta_id: str):
    """读取 delta manifest（拆解来源）。"""
    from specstd.workspace import specflow_dir
    from specflow.delta.manifest import load_manifest
    manifest_path = specflow_dir() / "changes" / delta_id / "delta.manifest.yaml"
    if not manifest_path.is_file():
        return None
    return load_manifest(str(manifest_path))


def estimate_points(workspace: str, delta_id: str,
                    actor: str = "system:estimator",
                    story_id: str = "") -> dict:
    """按冻结 delta 的 FR 操作集生成故事点建议（恒 suggested 出生）。

    Args:
        story_id: 已创建禅道故事编号（评估后回写关联用，可选）

    Raises:
        ValueError: delta 无 manifest / 无操作
    """
    manifest = _load_manifest(delta_id)
    if manifest is None:
        raise ValueError(f"delta {delta_id} 缺少 delta.manifest.yaml，无法拆解")
    ops = manifest.operations or []
    if not ops:
        raise ValueError(f"delta {delta_id} manifest 无操作，无法评估")

    breakdown = []
    total = 0
    for op in ops:
        anchor = op.get("anchor", "")
        op_type = op.get("op", "")
        pts = OP_BASE_POINTS.get(op_type, 1)
        breakdown.append({"item": f"{anchor}（{op_type}）", "points": pts})
        total += pts
        if op_type == "MODIFIED" and op.get("decisions"):
            breakdown.append({"item": f"{anchor} 级联影响面", "points": CASCADE_POINTS})
            total += CASCADE_POINTS

    # 历史参照：同工作区已确认的评估记录
    refs = []
    for est in sf_refs_store.list_estimates(workspace=workspace,
                                            status="confirmed"):
        refs.append({"estimate_id": est["id"], "delta_id": est["delta_id"],
                     "points": est["points"]})

    # 置信度：条目数校准 + 历史参照加成
    conf = 0.5
    if len(breakdown) >= 4:
        conf += 0.15
    elif len(breakdown) >= 2:
        conf += 0.10
    if refs:
        conf += 0.20
    conf = min(conf, 0.95)

    estimate = sf_refs_store.create_estimate(
        workspace, delta_id, breakdown, total, round(conf, 2), refs,
        zt_story=story_id)
    return estimate


def confirm_estimate(estimate_id: int, actor: str) -> dict:
    """产品确认（suggested → confirmed，产品闸门）。"""
    updated = sf_refs_store.update_estimate_status(estimate_id, "confirmed",
                                                   actor=actor)
    if updated is None:
        raise ValueError(
            f"评估记录 {estimate_id} 无法确认（不存在或已非 suggested）")
    return updated


def reject_estimate(estimate_id: int) -> dict:
    """驳回建议（suggested → rejected）。"""
    updated = sf_refs_store.update_estimate_status(estimate_id, "rejected")
    if updated is None:
        raise ValueError(f"评估记录 {estimate_id} 无法驳回（不存在或已非 suggested）")
    return updated
