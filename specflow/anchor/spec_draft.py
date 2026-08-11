"""anchor/spec_draft.py — spec 草案管理（TBD 标记 + 落锤替换）。"""

from __future__ import annotations

import re
from typing import Optional

# 待确认标记正则
TBD_RE = re.compile(r"「待确认[^」]*」")

# 决策落锤标记正则
RESOLVED_RE = re.compile(r"✅\s*D-\d{3,}")

# [delta:xxx] 标记正则
DELTA_MARK_RE = re.compile(r"\[delta:([a-z0-9_-]+)(?:\s+\w+)?\]")


def find_tbd_marks(text: str) -> list[dict]:
    """扫描文本中的 TBD 待确认标记，返回 [{position, text}]。"""
    marks = []
    for m in TBD_RE.finditer(text):
        marks.append({"position": m.start(), "text": m.group()})
    return marks


def find_delta_marks(text: str) -> list[dict]:
    """扫描文本中的 [delta:xxx] 标记。"""
    marks = []
    for m in DELTA_MARK_RE.finditer(text):
        marks.append({"position": m.start(), "delta": m.group(1), "full": m.group()})
    return marks


def resolve_tbd(text: str, replacement: str) -> str:
    """替换第一个 TBD 标记为确定文本（用于决策落锤联动）。"""
    return TBD_RE.sub(replacement, text, count=1)


def resolve_all_tbd(text: str, replacements: dict[str, str]) -> str:
    """按 mapping 替换全部 TBD 标记。"""
    def _replacer(m: re.Match) -> str:
        key = m.group()
        return replacements.get(key, key)
    return TBD_RE.sub(_replacer, text)


def count_unresolved_tbd(text: str) -> int:
    """统计未落锤 TBD 标记数量。"""
    return len(TBD_RE.findall(text))


def needs_decision_sync(text: str) -> bool:
    """草案是否需要决策同步（有 TBD 标记）。"""
    return count_unresolved_tbd(text) > 0


def validate_spec_draft_sections(text: str) -> list[str]:
    """校验 spec draft 的 11 章完整性（段落级）。"""
    chapter_patterns = [
        r"^##\s+一[、.．]\s*概述",
        r"^##\s+二[、.．]\s*范围",
        r"^##\s+三[、.．]\s*功能需求",
        r"^##\s+四[、.．]\s*非功能需求",
        r"^##\s+五[、.．]\s*数据需求",
        r"^##\s+六[、.．]\s*接口需求",
        r"^##\s+七[、.．]\s*安全需求",
        r"^##\s+八[、.．]\s*前置条件",
        r"^##\s+九[、.．]\s*验收标准",
        r"^##\s+十[、.．]\s*术语定义",
        r"^##\s+(?:十一|11)[、.．]\s*[Cc]hangelog",
    ]
    missing = []
    for i, pat in enumerate(chapter_patterns):
        if not re.search(pat, text, re.MULTILINE):
            chapter_num = i + 1
            chapter_names = [
                "概述", "范围", "功能需求", "非功能需求", "数据需求",
                "接口需求", "安全需求", "前置条件", "验收标准", "术语定义", "Changelog",
            ]
            missing.append(f"第{chapter_num}章«{chapter_names[i]}»缺失")
    return missing