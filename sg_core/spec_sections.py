"""章节提取纯函数（T-1023 自 mcp_server/tools/sections.py 下沉 sg_core）
——read_spec/read_scenario 定位参数 + 工作台 anchor-refs 接口共同消费。

纯函数零 I/O：输入文本，输出 {title, start, end, chunk}（行号 1-based 闭区间）。
锚点正则复用 specstd.schema 单一事实源（只 import 不修改）：
- FR 标题式  ### FR-001: 描述      → 到下一同级或更高级标题
- FR 列表式  - **FR-001**：描述     → 到下一同缩进列表项/标题（tdm 生产 spec 主形态）
- AC 锚点    - [ ] **AC-001**：…    → 所在连续列表块
- md 标题树  section 查询（编号「4」或标题文字子串）→ 到下一同级或更高级标题
- yaml part  doc/flow/verify/covers → 顶层键文本边界（不走 round-trip，保注释）
"""

from __future__ import annotations

import re

from specstd.schema import FR_HEADING_RE, FR_LIST_RE

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s*)[-*]\s")
_TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w]*):")


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _hit(title: str, start: int, end: int, lines: list[str]) -> dict:
    """start/end 为 1-based 闭区间。"""
    start = max(1, start)
    end = min(len(lines), max(start, end))
    return {"title": title, "start": start, "end": end,
            "chunk": "\n".join(lines[start - 1:end])}


# ══════════════════════════════════════════════════════════
# FR / AC 锚点
# ══════════════════════════════════════════════════════════

def list_fr_anchors(text: str) -> list[str]:
    """文中全部 FR 锚点（标题式 + 列表式，按出现顺序去重）——未命中自愈提示用。"""
    hits: dict[str, int] = {}
    for rex in (FR_HEADING_RE, FR_LIST_RE):
        for m in rex.finditer(text):
            fr = m.group(1)
            if fr not in hits or m.start() < hits[fr]:
                hits[fr] = m.start()
    return sorted(hits, key=lambda fr: hits[fr])


def _extract_fr_heading(lines: list[str], anchor: str) -> dict | None:
    """标题式：### FR-xxx: → 到下一同级（≤3 级）标题。"""
    start_idx = None
    for i, line in enumerate(lines):
        m = re.match(r"^###\s+(FR-[\w-]+)\s*[:：]\s*(.*)$", line)
        if m and m.group(1) == anchor:
            start_idx = i
            title = f"{m.group(1)}: {m.group(2).strip()}".rstrip(": ").strip()
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^#{1,3}\s", lines[j]):
            end_idx = j
            break
    return _hit(title, start_idx + 1, end_idx, lines)


def _extract_fr_list(lines: list[str], anchor: str) -> dict | None:
    """列表式：- **FR-xxx**：… → 到下一同/浅缩进列表项或标题。"""
    start_idx = None
    start_indent = 0
    title = ""
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)[-*]\s+\*\*(FR-[\w-]+)\*\*\s*[:：]\s*(.*)$", line)
        if m and m.group(2) == anchor:
            start_idx = i
            start_indent = len(m.group(1))
            title = f"{m.group(2)}：{m.group(3).strip()}".strip()
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        line = lines[j]
        if re.match(r"^#{1,6}\s", line):
            end_idx = j
            break
        li = _LIST_ITEM_RE.match(line)
        if li and len(li.group(1)) <= start_indent:
            end_idx = j  # 同/浅缩进列表项 = 下一条目
            break
        if line.strip() and not line.startswith((" ", "\t")) and not line.startswith("-"):
            end_idx = j  # 非空非缩进非列表行（新段落）
            break
    # 尾部空行不纳入 chunk
    while end_idx - 1 > start_idx and not lines[end_idx - 1].strip():
        end_idx -= 1
    return _hit(title, start_idx + 1, end_idx, lines)


def _extract_ac_block(lines: list[str], anchor: str) -> dict | None:
    """AC 锚点：定位含 AC-xxx 的连续列表块（checkbox 项前后连续行）。"""
    target = None
    for i, line in enumerate(lines):
        if re.search(rf"\b{re.escape(anchor)}\b", line):
            target = i
            break
    if target is None:
        return None
    start = target
    while start > 0 and _LIST_ITEM_RE.match(lines[start - 1]):
        start -= 1
    end = target
    while end + 1 < len(lines) and _LIST_ITEM_RE.match(lines[end + 1]):
        end += 1
    # 标题取目标行文本（去 checkbox 与加粗标记）
    text = re.sub(r"^\s*[-*]\s+(\[[ xX]\]\s+)?", "", lines[target]).replace("**", "").strip()
    return _hit(text[:60], start + 1, end + 1, lines)


def extract_fr_section(text: str, anchor: str) -> dict | None:
    """按 FR/AC 锚点提取章节；未命中返回 None。"""
    anchor = (anchor or "").strip()
    if not anchor:
        return None
    lines = _lines(text)
    if anchor.upper().startswith("AC-"):
        return _extract_ac_block(lines, anchor)
    return _extract_fr_heading(lines, anchor) or _extract_fr_list(lines, anchor)


# ══════════════════════════════════════════════════════════
# md 标题树
# ══════════════════════════════════════════════════════════

def extract_heading_section(text: str, query: str) -> dict | None:
    """按标题树提取章节：query 支持编号（「4」/「4.1」）或标题文字子串（大小写不敏感）。"""
    query = (query or "").strip()
    if not query:
        return None
    lines = _lines(text)
    numeric = re.match(r"^\d+(\.\d+)*\.?$", query)
    q = query.lower().rstrip(".")
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level, heading = len(m.group(1)), m.group(2)
        if numeric:
            num = heading.split(None, 1)[0].rstrip(".") if heading else ""
            if num != q:
                continue
        elif q not in heading.lower():
            continue
        end_idx = len(lines)
        for j in range(i + 1, len(lines)):
            m2 = _HEADING_RE.match(lines[j])
            if m2 and len(m2.group(1)) <= level:
                end_idx = j
                break
        return _hit(heading, i + 1, end_idx, lines)
    return None


# ══════════════════════════════════════════════════════════
# 场景 YAML part（文本边界，保注释，不走 round-trip）
# ══════════════════════════════════════════════════════════

def extract_yaml_part(text: str, part: str) -> dict | None:
    """提取场景 YAML 的 doc/flow/verify/covers 段。

    doc/flow/verify：顶层键行 → 下一顶层键；covers：doc 段内 covers: 行 + 其列表项。
    """
    part = (part or "").strip().lower()
    if part not in ("doc", "flow", "verify", "covers"):
        return None
    lines = _lines(text)
    # 顶层键边界（列 0 的 key: 行）
    top_keys = [(i, m.group(1)) for i, line in enumerate(lines)
                if (m := _TOP_KEY_RE.match(line))]
    if part == "covers":
        for i, line in enumerate(lines):
            if re.match(r"^\s+covers\s*:", line):
                indent = len(line) - len(line.lstrip())
                end_idx = len(lines)
                for j in range(i + 1, len(lines)):
                    l2 = lines[j]
                    if l2.strip() and (len(l2) - len(l2.lstrip())) <= indent \
                            and not l2.lstrip().startswith("-"):
                        end_idx = j
                        break
                while end_idx - 1 > i and not lines[end_idx - 1].strip():
                    end_idx -= 1
                return _hit("covers 锚点清单", i + 1, end_idx, lines)
        return None
    for idx, (i, key) in enumerate(top_keys):
        if key == part:
            end_idx = top_keys[idx + 1][0] if idx + 1 < len(top_keys) else len(lines)
            while end_idx - 1 > i and not lines[end_idx - 1].strip():
                end_idx -= 1
            return _hit(f"{part} 段", i + 1, end_idx, lines)
    return None
