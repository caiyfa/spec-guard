"""anchor/scoring.py — 五维评分服务：机打维度采集 + LLM 预打分 + QA 确认。

五维维度：
- logic: 逻辑完整性（11 章齐全 / SHALL 语句）
- clarity: 预期清晰度（LLM 建议，QA 确认）
- coverage: 需求覆盖率（coverage_map 贡献）
- boundary: 边界异常（边界场景比对）
- precondition: 前置条件

机打维度是确定性采集，LLM 建议维度永远 status=suggested 出生。
"""

from __future__ import annotations

import re
from typing import Optional


# 五维维度常量
DIMENSION_LOGIC = "logic"
DIMENSION_CLARITY = "clarity"
DIMENSION_COVERAGE = "coverage"
DIMENSION_BOUNDARY = "boundary"
DIMENSION_PRECONDITION = "precondition"

ALL_DIMENSIONS = [
    DIMENSION_LOGIC,
    DIMENSION_CLARITY,
    DIMENSION_COVERAGE,
    DIMENSION_BOUNDARY,
    DIMENSION_PRECONDITION,
]

MACHINE_DIMENSIONS = [
    DIMENSION_LOGIC,
    DIMENSION_COVERAGE,
    DIMENSION_BOUNDARY,
    DIMENSION_PRECONDITION,
]

# 权重（等权 20）
DIMENSION_WEIGHT = 20

# 机打采集最小文本长度：低于此值视为无有效内容，拒绝采集（空文本评分无意义）
MIN_SPEC_TEXT_LEN = 50


def collect_logic_dimension(spec_text: str) -> dict:
    """机打维度：逻辑完整性——11 章齐全性 + SHALL 语句密度。

    Returns:
        {"score": int, "evidence": str, "chapters": list[str], "shalls": int}
    """
    from specflow.anchor.spec_draft import validate_spec_draft_sections
    missing = validate_spec_draft_sections(spec_text)
    shall_count = len(re.findall(r"\bSHALL\b", spec_text))
    chapters_found = 11 - len(missing)

    score = 0
    if chapters_found >= 10:
        score = 90
    elif chapters_found >= 8:
        score = 70
    elif chapters_found >= 5:
        score = 50
    else:
        score = 30

    # SHALL 语句加分（每 5 条 +2 分，上限 +10）
    shall_bonus = min(shall_count // 5 * 2, 10)
    score = min(score + shall_bonus, 100)

    evidence_parts = [f"11 章 {chapters_found}/11 齐全"]
    if missing:
        evidence_parts.append(f"缺失: {'; '.join(missing[:3])}")
    evidence_parts.append(f"SHALL 语句 {shall_count} 条")
    if shall_count < 3:
        evidence_parts.append("SHALL 语句不足（建议 ≥3 条/功能点）")

    return {
        "score": score,
        "evidence": "；".join(evidence_parts),
        "chapters_found": chapters_found,
        "chapters_total": 11,
        "shall_count": shall_count,
    }


def collect_coverage_dimension(
    coverage_gap_summary: Optional[str] = None,
    coverage_total: int = 0,
    coverage_mapped: int = 0,
) -> dict:
    """机打维度：需求覆盖率——基于 coverage_map 的 FR 映射情况。

    Args:
        coverage_gap_summary: coverage.py gap_summary 文本
        coverage_total: 总 FR 数
        coverage_mapped: 已映射 FR 数

    Returns:
        {"score": int, "evidence": str}
    """
    if coverage_total == 0:
        score = 0
        evidence = "无覆盖率数据（coverage_map 未生成）"
    else:
        ratio = coverage_mapped / coverage_total
        if ratio >= 0.9:
            score = 90
        elif ratio >= 0.7:
            score = 70
        elif ratio >= 0.5:
            score = 50
        else:
            score = 30
        evidence = (
            f"FR 覆盖率 {coverage_mapped}/{coverage_total} ({ratio * 100:.0f}%)"
        )
        if coverage_gap_summary:
            evidence += f"；缺口: {str(coverage_gap_summary)[:200]}"
    return {"score": score, "evidence": evidence}


def collect_boundary_dimension(text: str) -> dict:
    """机打维度：边界异常——扫描异常场景/边界条件提及。

    通过关键词扫描估算边界异常场景的覆盖情况。
    """
    boundary_keywords = [
        "异常", "边界", "极限", "超时", "重试", "异常处理",
        "失败", "错误", "回滚", "异常场景", "边界条件",
    ]
    found = [kw for kw in boundary_keywords if kw in text]
    count = len(found)
    if count >= 6:
        score = 85
        evidence = f"边界异常场景覆盖较完整（命中 {count} 个关键词）"
    elif count >= 3:
        score = 60
        evidence = f"边界异常场景部分覆盖（命中 {count} 个关键词）"
    else:
        score = 40
        evidence = f"边界异常场景覆盖不足（仅命中 {count} 个关键词）"
    if found:
        evidence += f": {', '.join(found[:6])}"
    else:
        evidence = "未发现异常场景相关描述"
    return {"score": score, "evidence": evidence}


def collect_precondition_dimension(text: str) -> dict:
    """机打维度：前置条件——扫描前置条件/前提声明的完整性。"""
    pre_keywords = [
        "前置条件", "前提", "假设", "依赖", "先决条件",
        "预置", "初始化", "准备工作", "环境要求", "准入条件",
    ]
    found = [kw for kw in pre_keywords if kw in text]
    count = len(found)
    if count >= 4:
        score = 80
        evidence = f"前置条件较完整（命中 {count} 个关键词）"
    elif count >= 2:
        score = 60
        evidence = f"前置条件部分覆盖（命中 {count} 个关键词）"
    else:
        score = 40
        evidence = f"前置条件严重不足（仅命中 {count} 个关键词）"
    if found:
        evidence += f": {', '.join(found[:5])}"
    return {"score": score, "evidence": evidence}


def collect_all_machine_dimensions(
    spec_text: str,
    coverage_gap_summary: Optional[str] = None,
    coverage_total: int = 0,
    coverage_mapped: int = 0,
) -> list[dict]:
    """采集全部机打维度的评分数据。

    spec_text 过短（< MIN_SPEC_TEXT_LEN）时返回空列表——
    基于空文本的评分无意义，调用方应跳过写库。

    Returns:
        [(dimension, score, evidence), ...]
    """
    if len((spec_text or "").strip()) < MIN_SPEC_TEXT_LEN:
        return []
    logic = collect_logic_dimension(spec_text)
    coverage_result = collect_coverage_dimension(
        coverage_gap_summary, coverage_total, coverage_mapped)
    boundary = collect_boundary_dimension(spec_text)
    precondition = collect_precondition_dimension(spec_text)

    return [
        (DIMENSION_LOGIC, logic["score"], logic["evidence"]),
        (DIMENSION_COVERAGE, coverage_result["score"], coverage_result["evidence"]),
        (DIMENSION_BOUNDARY, boundary["score"], boundary["evidence"]),
        (DIMENSION_PRECONDITION, precondition["score"], precondition["evidence"]),
    ]


def calculate_weighted_total(
    scores: dict[str, dict],
    threshold: float = 70.0,
) -> dict:
    """计算五维加权总分（仅 status=confirmed 的维度计入合计）。

    Args:
        scores: {dimension: {"score": int, "status": str, ...}}
        threshold: 及格线（默认 70）

    Returns:
        {"total": float, "pass": bool, "confirmed_count": int}
    """
    confirmed_scores = [
        v["score"]
        for v in scores.values()
        if v.get("status") == "confirmed" and isinstance(v.get("score"), (int, float))
    ]
    if not confirmed_scores:
        total = 0.0
    else:
        total = sum(confirmed_scores) / len(confirmed_scores)

    return {
        "total": round(total, 1),
        "pass": total >= threshold,
        "confirmed_count": len(confirmed_scores),
    }