"""question_bank.py — 提问维度库（M02，T-020）。

按 spec 11 章组织扫描清单，生成 P0/P1/P2 分级候选问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# spec 11 章扫描维度
CHAPTER_NAMES = {
    1: "功能范围与边界",
    2: "输入输出与格式",
    3: "业务规则与约束",
    4: "异常与错误处理",
    5: "权限与安全",
    6: "性能与容量",
    7: "兼容性与迁移",
    8: "配置与可观测性",
    9: "依赖与外部集成",
    10: "测试策略与验收",
    11: "非功能需求",
}


@dataclass
class ScanItem:
    """一项扫描维度条目。"""
    chapter: int           # 1-11
    priority: str          # P0/P1/P2（模板建议，人可改）
    question: str          # 问题模板
    hint: str = ""         # 提示（素材来源建议）
    fr_ref_pattern: str = ""  # 锚点匹配模式


# 11 章扫描清单模板
SCAN_TEMPLATES: list[ScanItem] = [
    # 第 1 章：功能范围与边界
    ScanItem(1, "P0", "调整范围：只改{target_area}，还是{scope_list}同改？",
             hint="从议题卡 source 提取，比对 baseline_refs"),
    ScanItem(1, "P0", "存量已落位{entity}怎么处理？冻结存量、重算覆盖、还是分批迁移？",
             hint="影响现有数据语义，属于 P0 范围界定"),
    ScanItem(1, "P1", "本次改动涉及哪些功能模块？新增/修改/废弃各多少？",
             hint="对 baseline_refs 做 diff 分析"),

    # 第 2 章：输入输出与格式
    ScanItem(2, "P1", "输入数据来源与格式是什么？是否有新字段或字段变更？"),
    ScanItem(2, "P2", "输出结果的数据结构是否有变化？是否需要兼容旧格式？"),

    # 第 3 章：业务规则与约束
    ScanItem(3, "P0", "现有业务规则是修改还是新增？存量规则冻结还是同步更新？",
             hint="M04 历史决策 D-012 级联约束检查"),
    ScanItem(3, "P1", "规则执行顺序是否影响结果？是否存在规则覆盖冲突？"),

    # 第 4 章：异常与错误处理
    ScanItem(4, "P1", "操作过程中可能出现哪些异常？各异常的处置策略是什么？",
             hint="五维边界异常维度评估参考"),
    ScanItem(4, "P1", "规则切换/数据迁移过程中出现的中间态如何处理？",
             hint="边界异常 55 分缺口反哺"),

    # 第 5 章：权限与安全
    ScanItem(5, "P1", "新功能/修改对现有权限模型的影响？是否需要新增权限点？"),
    ScanItem(5, "P2", "数据访问范围是否需要收窄？是否有敏感字段暴露风险？"),

    # 第 6 章：性能与容量
    ScanItem(6, "P2", "数据量级估计？预期吞吐量？是否有性能退化风险？"),
    ScanItem(6, "P2", "是否存在批量操作场景？超时/限流阈值如何设定？"),

    # 第 7 章：兼容性与迁移
    ScanItem(7, "P1", "存量数据是否需要迁移？迁移方案？回滚预案？",
             hint="影响存量数据语义"),
    ScanItem(7, "P1", "对外接口是否有兼容性要求？版本兼容策略？"),

    # 第 8 章：配置与可观测性
    ScanItem(8, "P2", "是否有新增配置项？默认值？配置变更后的生效方式？"),
    ScanItem(8, "P2", "关键路径日志是否完备？是否需要新增监控指标？"),

    # 第 9 章：依赖与外部集成
    ScanItem(9, "P1", "功能依赖哪些外部系统/接口？接口变更是否兼容？",
             hint="从 baseline_refs 分析外部依赖"),
    ScanItem(9, "P1", "是否存在时序依赖？多系统间一致性如何保证？"),

    # 第 10 章：测试策略与验收
    ScanItem(10, "P1", "测试覆盖范围？需要新增哪些场景类型？",
             hint="M07 覆盖缺口聚合参考"),
    ScanItem(10, "P2", "验收标准如何定义？P0/P1 的测试准入条件？"),

    # 第 11 章：非功能需求
    ScanItem(11, "P2", "是否有可用性/SLA 要求？维护窗口期需求？"),
    ScanItem(11, "P2", "是否有合规/审计要求？数据留存策略？"),
]


# ── SPQ 反哺提问模板 ──

SPQ_FEEDBACK_TEMPLATES = [
    "未闭环 SPQ-{spq_id}（{title}）——是否纳入本期处置？",
    "上轮 SPQ-{spq_id} 的处置方案需要在本期确认？",
]


# ── 评分缺口反哺提问模板 ──

SCORE_GAP_TEMPLATES = [
    "边界异常维度 {score}/100，缺「{gap_desc}」场景——请确认是否补充？",
    "需求覆盖率维度 {score}/100，{gap_desc}——本期是否覆盖？",
]


def generate_scan_questions(topic_title: str, target_area: str = "",
                            scope_list: str = "") -> list[dict]:
    """从 11 章扫描清单生成候选问题列表。

    Returns:
        [{chapter, priority, question, hint}, ...]
    """
    questions = []
    for item in SCAN_TEMPLATES:
        q = item.question.format(
            target_area=target_area or "对应功能",
            scope_list=scope_list or "关联域",
            entity="数据",
        )
        questions.append({
            "chapter": item.chapter,
            "priority": item.priority,
            "question": q,
            "hint": item.hint,
        })
    return questions


def generate_spq_questions(spq_entries: list[dict]) -> list[dict]:
    """从未闭环 SPQ 条目生成反哺提问。

    Args:
        spq_entries: SPQ 条目列表，每项含 spq_id, title

    Returns:
        [{chapter: 0, priority: 'P1', question, spq_ref}, ...]
    """
    questions = []
    for entry in spq_entries:
        spq_id = entry.get("spq_id", "")
        title = entry.get("title", "")
        for tpl in SPQ_FEEDBACK_TEMPLATES:
            q = tpl.format(spq_id=spq_id, title=title)
            questions.append({
                "chapter": 0,
                "priority": "P1",
                "question": q,
                "spq_ref": spq_id,
            })
    return questions


def generate_score_gap_questions(score_gaps: list[dict]) -> list[dict]:
    """从评分缺口生成反哺提问。

    Args:
        score_gaps: 评分缺口列表，每项含 dimension, score, gap_desc

    Returns:
        [{chapter: 0, priority: 'P1', question}, ...]
    """
    questions = []
    for gap in score_gaps:
        for tpl in SCORE_GAP_TEMPLATES:
            q = tpl.format(
                score=gap.get("score", 0),
                gap_desc=gap.get("gap_desc", "未覆盖场景"),
            )
            questions.append({
                "chapter": 0,
                "priority": "P1",
                "question": q,
            })
    return questions