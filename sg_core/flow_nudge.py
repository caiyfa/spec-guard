"""flow_nudge — 路径纠正提示的纯函数核（T-1042 三期，「图在看、提示不打断」）。

设计：docs/superpowers/specs/2026-08-30-Agent路径自检与纠正提示-design.md。
agent runtime（工具结果出口）与 evals（EDD 指标识别）共同消费本模块——
放 sg_core 使两侧依赖方向都合法（agent→sg_core ✓ / evals→sg_core ✓）。

三条铁律（与设计文档 §二 对应）：
  1. 只提示不打断——本模块永不抛错、永不改判定，产物质量仍由三闸把守
  2. 整会话一次——去重由调用方扫历史 NUDGE_MARKER 实现（防唠叨/防 Goodhart）
  3. 诚实裁量——文案明示「用户明确要求的跳过，向用户说明即可，无需补做」

与 evals/flows/generate-scenario.flow.json hard_order 的镜像关系由测试钉死
（test_flow_nudge.py::test_prereq_families_cover_flow_hard_order）——flow 定义
变更而本模块未同步即红。
"""

from __future__ import annotations

# 落盘标记：runtime 追加到工具结果尾部；评测层据此识别触发点算 EDD 指标
NUDGE_MARKER = "[flow-nudge]"

# 硬前置工具族（（基名, action）；action="" 表示该基名任意 action）——
# 对应 flow JSON hard_order 的两条：读需求<写草稿、validate<写草稿。
# 家族刻意取「超集」口径（含 legacy 旧会话候选）：旧会话在先也算满足前置。
_PREREQ_FAMILIES: dict[str, set[tuple[str, str]]] = {
    "validate": {
        ("validate", ""),
    },
    "read_requirement": {
        ("info_pack", ""), ("read_info_pack", ""),
        ("spec", "read"), ("spec", "list"), ("spec", "search"),
        ("read_spec", ""), ("list_spec_files", ""),
    },
}

# 缺失项的人话文案（nudge 一句话里逐个点名）
_GAP_LABELS = {
    "validate": "validate 校验（validate 工具）",
    "read_requirement": "读需求（info_pack(action=read) 或 spec(action=read)）",
}


def family_hit(family: set[tuple[str, str]], unit: tuple[str, str]) -> bool:
    """工具单元是否命中工具族（基名相等且族 action 为空=任意，或 action 精确相等）。

    公开给一致性钉测试用：sg_core 预置族必须覆盖 evals/flows JSON hard_order
    earlier 阶段的全部工具候选，flow 定义变更未同步本模块即红。
    """
    b, a = unit
    return any(b == fb and (fa == "" or a == fa) for fb, fa in family)


def draft_write_prereq_gaps(units: list[tuple[str, str]]) -> list[str]:
    """写草稿之前会话内工具单元序列 → 缺失的硬前置阶段 key 列表。

    units 必须不含当前这次 draft write 自身（调用方裁剪）。顺序即返回顺序
    （读需求在前、validate 在后，与 flow JSON hard_order 对应）。
    """
    gaps = []
    for key, family in _PREREQ_FAMILIES.items():
        if not any(family_hit(family, u) for u in units):
            gaps.append(key)
    # 稳定输出：读需求在前
    return sorted(gaps, key=lambda k: 0 if k == "read_requirement" else 1)


def build_flow_nudge(missing: list[str]) -> str:
    """构造一句话纠正提示（非打断；追加到 draft write 工具结果尾部）。"""
    if not missing:
        return ""
    parts = "、".join(_GAP_LABELS.get(k, k) for k in missing)
    return (
        f"{NUDGE_MARKER} 路径提示：按 generate-scenario 技能流程，写场景草稿前应先完成 {parts}，"
        f"当前会话尚未发生。如属用户明确要求的跳过，向用户说明即可，无需补做；"
        f"否则建议先补齐再写草稿（进度可用 flow 工具自查）。"
    )


def has_nudge_in_history(messages: list) -> bool:
    """会话消息里是否已出现过 nudge（整会话一次去重的判定核）。"""
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str) and NUDGE_MARKER in content:
            return True
    return False
