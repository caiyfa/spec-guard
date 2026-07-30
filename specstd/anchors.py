"""specstd.anchors — FR/AC 锚点解析 → 清单快照。

解析 spec.md 中的 FR 锚点（### FR-<id>:）和关联 AC，
生成 FR ID → AnchorInfo 的清单快照，供 covers 校验与签名检测共用。
同时提供 delta-spec.md 三段式解析（conformance.py 消费）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import yaml

from specstd.schema import (
    FR_HEADING_RE, FR_LIST_RE, FR_INLINE_RE, AC_RE,
    DELTA_MARKER_RE, TASK_REF_RE,
    DELTA_SECTION_RE, DELTA_SECTIONS,
    SECTION_ADDED, SECTION_MODIFIED, SECTION_REMOVED,
    FILE_SPEC_MD, FILE_DELTA_SPEC_MD,
    DIR_SPECS, DIR_CHANGES,
    AnchorInfo, Finding, ParsedDeltaSpec, DeltaOperation,
    RuleName, RuleLevel,
)


# ══════════════════════════════════════════════════════════
# spec.md 解析
# ══════════════════════════════════════════════════════════

def parse_spec_md(path: Path) -> list[AnchorInfo]:
    """解析单个 spec.md，提取 FR 锚点和关联 AC。

    FR 锚点格式（两种都识别，K-020）：
    - 标题格式：### FR-<id>: 标题
    - 列表定义格式：- **FR-<id>**：描述（真实工作区 spec 的合法写法，
      如 tdm specs/system-settings/tag-library/spec.md——仅匹配行首列表项+
      加粗+冒号的定义格式，正文内联引用 **FR-001** 不算锚点；
      此前只认标题格式 → FR-004 误报「不存在」→ Agent 删 covers 绕过，溯源断裂）
    AC 锚点：AC-<number>（在 FR 锚点下方文本中）
    """
    text = path.read_text(encoding="utf-8")
    results: list[AnchorInfo] = []

    # 合并两种格式的匹配，按出现位置排序；重复 FR 保留全部出现
    # （唯一性冲突由 conformance.py 的 ANCHOR 规则检测，不在此判重）
    raw = [(m.start(), m.end(), m.group(1), m.group(2))
           for m in FR_HEADING_RE.finditer(text)]
    raw += [(m.start(), m.end(), m.group(1), m.group(2))
            for m in FR_LIST_RE.finditer(text)]
    raw.sort(key=lambda x: x[0])
    fr_matches = raw

    for i, (start, end, fr_id, title_raw) in enumerate(fr_matches):
        title = title_raw.strip().rstrip("：：")

        # 截取到下一个 FR 锚点之前的文本，提取 AC
        # （列表格式的定义行本身常含 AC，需并入扫描——该行已被正则整体消费）
        chunk_start = end
        chunk_end = fr_matches[i + 1][0] if i + 1 < len(fr_matches) else len(text)
        chunk = title_raw + "\n" + text[chunk_start:chunk_end]
        ac_ids = sorted(set(AC_RE.findall(chunk)))

        # 从路径推断 module/feature
        rel = path.relative_to(path.parents[2]) if len(path.parents) >= 3 else path
        parts = rel.parts
        module = parts[0] if len(parts) > 0 else ""
        feature = parts[1] if len(parts) > 1 else ""

        results.append(AnchorInfo(
            fr_id=fr_id,
            file_path=str(path),
            module=module,
            feature=feature,
            title=title,
            ac_ids=ac_ids,
        ))

    return results


def scan_anchors(workspace_root: Path) -> dict[str, AnchorInfo]:
    """扫描工作区 specs/ 下所有 spec.md，返回 FR ID → AnchorInfo 映射。

    如果 specs/ 目录不存在，返回空 dict。
    """
    specs_dir = workspace_root / DIR_SPECS
    if not specs_dir.is_dir():
        return {}

    anchors: dict[str, AnchorInfo] = {}
    for spec_md in sorted(specs_dir.rglob(FILE_SPEC_MD)):
        for info in parse_spec_md(spec_md):
            # 重复 FR ID 被后者覆盖；唯一性冲突由 conformance.py 的 ANCHOR 规则检测
            anchors[info.fr_id] = info

    return anchors


# ══════════════════════════════════════════════════════════
# covers 校验
# ══════════════════════════════════════════════════════════

def extract_covers_from_yaml(path: Path) -> list[str]:
    """从场景 YAML 中提取 doc.covers 列表。

    场景 YAML 格式：
        doc:
          covers: [FR-001, FR-002]
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    doc = raw.get("doc") or {}
    covers = doc.get("covers") or []
    return [str(c) for c in covers]


def resolve_covers(covers: list[str], anchors: dict[str, AnchorInfo]) -> list[Finding]:
    """检查 covers 中的 FR ID 是否全部在锚点清单中可解析。

    编造的 FR（不在任何 spec.md 中）→ ERROR + hint。
    """
    findings: list[Finding] = []
    for fr_id in covers:
        if fr_id not in anchors:
            # 尝试提供 hint：找最接近的 FR ID
            hint = _suggest_similar(fr_id, list(anchors.keys()))
            # K-020：附行为指引——Agent 曾在此误报后删除 covers 绕过校验（溯源断裂）。
            # 真实工作区存在列表定义格式（- **FR-xxx**：），已兼容；仍误报时必须上报而非绕过
            findings.append(Finding(
                rule=RuleName.ANCHOR.value,
                level=RuleLevel.ERROR.value,
                message=(f"covers 引用的 FR '{fr_id}' 在当前工作区的 spec.md 中不存在。"
                         f"请先用 read_spec 核实该 FR 是否真实存在（支持的锚点格式："
                         f"### FR-xxx: 标题 或 - **FR-xxx**： 列表定义）；"
                         f"若确认存在却仍报此错，属于校验器误报——禁止删除 covers 绕过，"
                         f"必须向用户报告并等待指示"),
                detail={"hint": hint} if hint else {},
            ))
    return findings


def _suggest_similar(target: str, candidates: list[str]) -> str:
    """为无法解析的 FR ID 提供最接近的候选建议。"""
    if not candidates:
        return ""
    # 简单编辑距离：找前缀匹配的
    target_prefix = target.rsplit("-", 1)[0] if "-" in target else target
    matches = [c for c in candidates if c.startswith(target_prefix)]
    if matches:
        return f"你是否想引用: {', '.join(matches[:3])}"
    return ""


# ══════════════════════════════════════════════════════════
# delta-spec.md 解析（三段式）
# ══════════════════════════════════════════════════════════

def parse_delta_spec(path: Path) -> ParsedDeltaSpec:
    """解析 delta-spec.md 的三段式结构。

    结构：
        ## ADDED Requirements
        ### FR-001: 新功能 [delta:代号]
        → task: TSK-001
        全量描述...

        ## MODIFIED Requirements
        ### FR-002: 修改功能 [delta:代号]
        **原**: ...
        **新**: ...
        → task: TSK-002
        **原因**: ...

        ## REMOVED Requirements
        ### FR-003: 删除功能 [delta:代号]
        **原**: ...
        → task: TSK-003
    """
    text = path.read_text(encoding="utf-8")
    delta_code = path.parent.name  # changes/<代号>/delta-spec.md

    result = ParsedDeltaSpec(delta_code=delta_code)

    # 找到三段的起止位置
    section_starts = []
    for m in DELTA_SECTION_RE.finditer(text):
        section_starts.append((m.group(1), m.start(), m.end()))

    # 为每段提取内容
    for i, (section_name, start, header_end) in enumerate(section_starts):
        content_end = section_starts[i + 1][1] if i + 1 < len(section_starts) else len(text)
        section_text = text[header_end:content_end]
        items = _parse_delta_section(section_text, section_name)
        result.sections[section_name] = items

    return result


def _parse_delta_section(section_text: str, section_name: str) -> list[dict]:
    """解析 delta-spec.md 的一个段落（ADDED/MODIFIED/REMOVED）。

    返回 dict 列表，每条含 fr / title / task / original / new / reason。
    """
    items: list[dict] = []

    # 找到段落中的所有 FR 锚点
    fr_matches = list(FR_HEADING_RE.finditer(section_text))
    for i, m in enumerate(fr_matches):
        fr_id = m.group(1)
        # 截取到下一个 FR 锚点之前的文本
        chunk_end = fr_matches[i + 1].start() if i + 1 < len(fr_matches) else len(section_text)
        chunk = section_text[m.end():chunk_end]

        # 提取标题（### FR-xxx: 标题 [delta:代号]）
        title_line = m.group(2).strip()
        # 去掉 delta 标记
        title = DELTA_MARKER_RE.sub("", title_line).strip().rstrip("：：")

        # 提取 delta 标记
        delta_marker = ""
        dm = DELTA_MARKER_RE.search(title_line)
        if dm:
            delta_marker = dm.group(1)

        # 提取 task 引用
        task = ""
        tm = TASK_REF_RE.search(chunk)
        if tm:
            task = tm.group(1)

        # 提取原/新/原因（MODIFIED 段落）
        original = _extract_field(chunk, ["**原描述**", "**原**", "**Original**"])
        new = _extract_field(chunk, ["**新描述**", "**新**", "**New**"])
        reason = _extract_field(chunk, ["**原因**", "**Reason**"])

        item: dict = {
            "fr": fr_id,
            "title": title,
            "section": section_name,
            "delta": delta_marker,
            "task": task,
        }
        if original:
            item["original"] = original
        if new:
            item["new"] = new
        if reason:
            item["reason"] = reason

        items.append(item)

    return items


def _extract_field(text: str, labels: list[str]) -> str:
    """从文本中提取 **标签**: 值 格式的字段。"""
    for label in labels:
        # 匹配 **原描述**: value 或 **原描述**：value
        pattern = re.escape(label) + r"\s*[:：]\s*(.+?)(?=\*\*|$|\n\s*\n)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return ""


# ══════════════════════════════════════════════════════════
# 清单快照（JSON 序列化/反序列化）
# ══════════════════════════════════════════════════════════

def save_anchor_snapshot(anchors: dict[str, AnchorInfo], path: Path) -> Path:
    """保存锚点清单快照到 JSON 文件。

    供后续 covers 校验与签名检测使用（避免每次都重新扫描）。
    """
    data = {}
    for fr_id, info in sorted(anchors.items()):
        data[fr_id] = {
            "fr_id": info.fr_id,
            "file_path": info.file_path,
            "module": info.module,
            "feature": info.feature,
            "title": info.title,
            "ac_ids": info.ac_ids,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return path


def load_anchor_snapshot(path: Path) -> dict[str, AnchorInfo]:
    """从 JSON 文件加载锚点清单快照。"""
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    anchors: dict[str, AnchorInfo] = {}
    for fr_id, item in data.items():
        anchors[fr_id] = AnchorInfo(
            fr_id=item["fr_id"],
            file_path=item["file_path"],
            module=item.get("module", ""),
            feature=item.get("feature", ""),
            title=item.get("title", ""),
            ac_ids=item.get("ac_ids", []),
        )
    return anchors
