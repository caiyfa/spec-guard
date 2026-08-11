"""anchor/proposal_schema.py — proposal.md 四段式结构定义与校验。

四段式：
1. 为什么做      ← 背景/痛点/来源
2. 做什么        ← FR 操作集摘要，引用 D-xxx
3. 不做什么      ← 显式排除项
4. 验收口径      ← FR 对应 AC + 验证方式
"""

from __future__ import annotations

from typing import Optional

# 固定四段标题（缺段 → 合规 FAIL）
PROPOSAL_SECTIONS = [
    "为什么做",
    "做什么",
    "不做什么",
    "验收口径",
]
SECTION_HEADERS = [f"## {i+1}. {t}" for i, t in enumerate(PROPOSAL_SECTIONS)]
SECTION_HEADER_SET = set(SECTION_HEADERS)


def parse_proposal_sections(text: str) -> dict[str, str]:
    """解析 proposal.md 四段式，返回 {标题: 正文}。"""
    import re
    pattern = r"(## \d+\.\s*(.*?))\n(.*?)(?=\n## \d+\.|\Z)"
    matches = re.findall(pattern, text, re.DOTALL)
    sections: dict[str, str] = {}
    for header, title, body in matches:
        sections[title.strip()] = body.strip()
    return sections


def validate_proposal(text: str) -> list[str]:
    """校验 proposal.md 结构完整性。"""
    errors: list[str] = []
    sections = parse_proposal_sections(text)
    for title in PROPOSAL_SECTIONS:
        if title not in sections:
            errors.append(f"缺少段落: {title}")
    return errors


def extract_decision_refs(text: str) -> list[str]:
    """从 proposal 正文提取 D-xxx 决策引用。"""
    import re
    return re.findall(r"D-\d{3,}", text)


def extract_fr_refs(text: str) -> list[str]:
    """从 proposal 正文提取 FR-xxx 锚点引用。"""
    import re
    return re.findall(r"FR-\d{3,}", text)


def generate_proposal(
    title: str,
    background: str = "",
    scope: str = "",
    exclude: str = "",
    acceptance: str = "",
    decision_refs: list[dict] = None,
    fr_refs: list[str] = None,
) -> str:
    """生成 proposal.md 模板文本。"""
    dec_lines = []
    if decision_refs:
        for d in decision_refs:
            dec_lines.append(f"- {d.get('id', '')}: {d.get('question', '')} → {d.get('resolution', '')}")
    fr_lines = []
    if fr_refs:
        for f in fr_refs:
            fr_lines.append(f"- {f}")

    parts = [
        f"# Proposal: {title}",
        "",
        SECTION_HEADERS[0],
        "",
        background or "（待补充）",
    ]
    if dec_lines:
        parts += ["", "**相关决策：**", ""] + dec_lines
    parts += ["", SECTION_HEADERS[1], "", scope or "（待补充）"]
    if fr_lines:
        parts += ["", "**涉及 FR：**", ""] + fr_lines
    parts += [
        "", SECTION_HEADERS[2], "", exclude or "（无）",
        "", SECTION_HEADERS[3], "", acceptance or "（待补充）",
        "",
    ]
    return "\n".join(parts)