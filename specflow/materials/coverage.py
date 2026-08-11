"""coverage.py — 覆盖率机打依据 coverage_map.yaml（M03 §4.4，T-034）。

PRD 类材料条目 ↔ FR/决策锚点映射，供 S4 五维评分「需求覆盖率」维度机打消费。

确定性优先（铁律 2）：
- high 置信 = 机打确定（FR 标题关键词与 PRD 章节文本子串命中，词表驱动）
- low 置信 = LLM 建议待确认（工具仅生成候选结构，由 Agent/QA 标注）
- 未映射条目 = 覆盖率缺口（反哺 M02 面试官提问）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

# 停用词（FR 标题关键词提取时剔除；命中用词表，不用分词器——零新依赖）
_STOPWORDS = frozenset({
    "的", "了", "与", "和", "及", "或", "在", "对", "为", "将", "应", "需",
    "要", "可", "以", "是", "有", "等", "功能", "要求", "规则", "系统", "支持",
    "the", "a", "an", "of", "for", "and", "with", "to",
})

_ITEM_SPLIT_RE = re.compile(r"[。；;\n]")

# 停用词切分正则（按长度降序，优先匹配长词）
_STOP_RE = re.compile("|".join(sorted(_STOPWORDS, key=len, reverse=True)))


# 中文无空格分词：标题按分隔符/停用词切片段，再补 2-gram（覆盖条目与标题字面
# 不同但词重叠的场景，如 PRD「绩效≥4.5」↔ FR 标题「绩效阈值」）
def _keywords(title: str) -> list[str]:
    """FR 标题关键词（片段 + 2-gram，≥2 字，去停用词）。"""
    segs = re.split(r"[，。、\s:：()（）/\\-]+", title or "")
    kws: set[str] = set()
    for seg in segs:
        for part in _STOP_RE.split(seg):
            p = part.strip()
            if len(p) >= 2:
                kws.add(p)
            for i in range(len(p) - 1):
                gram = p[i:i + 2]
                if len(gram) >= 2 and gram not in _STOPWORDS:
                    kws.add(gram)
    return sorted(kws, key=len, reverse=True)


def build_coverage_map(chunks: list[dict], anchors: dict) -> dict:
    """机打生成 coverage_map（确定性）。

    Args:
        chunks: pipeline.chunk 产出（PRD 按 § 锚点切分）
        anchors: specstd.anchors.scan_anchors 产出 {FR_ID: AnchorInfo}

    Returns:
        {source, entries: [{prd_item, section, mapped: {type, ref, title}, confidence}]}
    """
    # 词表：FR 标题关键词 → FR 引用（一个关键词命中多个 FR 时取标题最长者）
    fr_keywords: dict[str, str] = {}
    fr_by_id: dict[str, str] = {}
    for fr_id, info in anchors.items():
        fr_by_id[fr_id] = info.title or fr_id
        for kw in _keywords(info.title or ""):
            if len(kw) >= 2:
                existing = fr_keywords.get(kw)
                if not existing or len(fr_by_id.get(existing, "")) < len(info.title or ""):
                    fr_keywords[kw] = fr_id

    entries: list[dict] = []
    for chunk in chunks:
        section = chunk.get("section", "")
        text = chunk.get("content", "")
        # 按句子/分号切条目（PRD 条目粒度）
        items = [s.strip() for s in _ITEM_SPLIT_RE.split(text) if s.strip()]
        for item in items:
            if len(item) < 4:
                continue
            mapped, confidence = _match_item(item, fr_keywords, fr_by_id)
            if mapped:
                entries.append({
                    "prd_item": item[:120],
                    "section": section,
                    "mapped": {**mapped, "confidence": confidence},
                })

    return {"source": "coverage_map", "entries": entries}


def _match_item(item: str, fr_keywords: dict, fr_by_id: dict):
    """条目 ↔ FR 词表命中；命中返回 ({type: fr, ref, title}, high)，否则 (None, None)。"""
    hits: list[tuple[str, int]] = []
    for kw, fr_id in fr_keywords.items():
        if kw in item:
            hits.append((fr_id, len(kw)))
    if not hits:
        return None, None
    # 取最长关键词命中（最具体）
    best = max(hits, key=lambda h: h[1])[0]
    return {"type": "fr", "ref": best, "title": fr_by_id.get(best, "")}, "high"


def write_coverage_map(coverage: dict, parsed_dir: Path, stem: str) -> Path:
    """落盘 _parsed/{stem}.coverage_map.yaml。"""
    path = parsed_dir / f"{stem}.coverage_map.yaml"
    path.write_text(
        yaml.dump(coverage, allow_unicode=True, indent=2, sort_keys=False),
        encoding="utf-8")
    return path


def gap_summary(coverage: dict) -> list[str]:
    """未映射章节清单（覆盖率缺口，反哺 M02 提问；确定性计算）。"""
    mapped_sections = {e["section"] for e in coverage.get("entries", [])}
    return sorted(mapped_sections)
