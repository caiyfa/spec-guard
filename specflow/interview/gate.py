"""gate.py — P0 清零确定性纯函数 + 门禁聚合（M02 §7 + M04 §7，T-024）。

P0 清零门禁：台账无 pending P0 → 放行，零 LLM 参与。
门禁聚合：P0 清零 + 影响面确认 + 评分及格 → freeze_allowed。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GateResult:
    """门禁聚合结果。"""
    pending_p0: int              # 待定 P0 数量
    impact_confirmed: bool       # 影响面已确认
    score_pass: bool             # 评分≥70 及格
    total_score: float = 0.0     # 加权总分
    freeze_allowed: bool = False # 允许冻结（三项全满足）
    gaps: list[str] = None       # 缺口清单

    def __post_init__(self):
        if self.gaps is None:
            self.gaps = []
        self.freeze_allowed = (
            self.pending_p0 == 0
            and self.impact_confirmed
            and self.score_pass
        )

    def to_dict(self) -> dict:
        return {
            "pending_p0": self.pending_p0,
            "impact_confirmed": self.impact_confirmed,
            "score_pass": self.score_pass,
            "total_score": self.total_score,
            "freeze_allowed": self.freeze_allowed,
            "gaps": self.gaps,
        }


def check_p0_clear(p0_pending_count: int) -> bool:
    """P0 清零确定性检查：台账中无 pending P0。

    这是纯确定性函数，零 LLM 参与。
    由调用方提供 pending P0 计数（gate 不直接查 DB）。

    Args:
        p0_pending_count: 当前 pending P0 数量

    Returns:
        True = 无 pending P0，可放行
    """
    return p0_pending_count == 0


def gate_aggregate(
    p0_pending_count: int,
    impact_confirmed: bool,
    total_score: float,
    score_threshold: float = 70.0,
) -> GateResult:
    """门禁聚合：P0 清零 + 影响面确认 + 评分及格。

    Args:
        p0_pending_count: 待定 P0 数量
        impact_confirmed: 影响面已确认
        total_score: 加权总分（仅 status=confirmed 的维度）
        score_threshold: 及格线（默认 70）

    Returns:
        GateResult（含 freeze_allowed 判定与缺口清单）
    """
    score_pass = total_score >= score_threshold
    gaps: list[str] = []

    if p0_pending_count > 0:
        gaps.append(f"P0 待定 {p0_pending_count} 项未清零")
    if not impact_confirmed:
        gaps.append("影响面未人工确认")
    if not score_pass:
        gaps.append(f"五维评分 {total_score}/{score_threshold} 未及格")

    return GateResult(
        pending_p0=p0_pending_count,
        impact_confirmed=impact_confirmed,
        score_pass=score_pass,
        total_score=total_score,
        gaps=gaps,
    )


def validate_freeze_request(result: GateResult) -> Optional[str]:
    """校验冻结请求是否可通过，返回错误消息或 None（通过）。

    供 POST freeze API 调用。
    """
    if result.freeze_allowed:
        return None
    gap_text = "；".join(result.gaps) if result.gaps else "未知原因"
    return f"冻结条件未满足: {gap_text}"