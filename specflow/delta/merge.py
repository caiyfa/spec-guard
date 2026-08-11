"""delta/merge.py — delta 合并（ADDED 追加 / MODIFIED 整块替换 / REMOVED 删除）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from specflow.delta.manifest import DeltaManifest, load_manifest

# 锚点位置：## FR-xxx. 标题
FR_ANCHOR_RE = re.compile(
    r"^##\s+(FR-\d{3,})(?:[.．、]\s*.*)?$", re.MULTILINE)


def _find_anchor_block(text: str, anchor: str) -> Optional[tuple[int, int]]:
    """在 spec.md 中按锚点定位块，返回 (start, end) 行偏移。

    end = 下一个同级标题或文档结尾，包含锚点标题行本身。
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        m = FR_ANCHOR_RE.match(line)
        if m and m.group(1) == anchor:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if FR_ANCHOR_RE.match(lines[i]):
            end = i
            break
    return (start, end)


def merge_added(text: str, anchor: str, new_block: str) -> str:
    """ADDED: 在 spec.md 中新增 FR 锚点块（追加在最后已有锚点之后）。"""
    # 找到最后一个 FR 锚点位置
    lines = text.split("\n")
    last_fr_end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if FR_ANCHOR_RE.match(lines[i]):
            last_fr_end = i + 1
            break
    if last_fr_end >= len(lines):
        text = text.rstrip("\n") + "\n\n" + new_block
    else:
        before = "\n".join(lines[:last_fr_end])
        after = "\n".join(lines[last_fr_end:])
        text = before + "\n\n" + new_block + "\n\n" + after
    return text


def merge_modified(text: str, anchor: str, new_block: str) -> str:
    """MODIFIED: 替换指定锚点块为新区块。"""
    pos = _find_anchor_block(text, anchor)
    if pos is None:
        return text  # 锚点不存在，跳过
    lines = text.split("\n")
    # 保留锚点标题行，替换其下内容
    start = pos[0] + 1
    end = pos[1]
    before = "\n".join(lines[:start])
    after = "\n".join(lines[end:])
    return before + "\n" + new_block + "\n" + after


def merge_removed(text: str, anchor: str) -> str:
    """REMOVED: 删除指定锚点块。"""
    pos = _find_anchor_block(text, anchor)
    if pos is None:
        return text
    lines = text.split("\n")
    before = "\n".join(lines[:pos[0]])
    after = "\n".join(lines[pos[1]:])
    merged = before.rstrip("\n") + "\n" + after.lstrip("\n")
    return merged


def apply_operations(text: str, ops: list[dict]) -> str:
    """按 manifest operations 顺序执行合并操作。"""
    for op in ops:
        op_type = op.get("op", "")
        anchor = op.get("anchor", "")
        new_block = op.get("new_block", "")
        if op_type == "ADDED" and new_block:
            text = merge_added(text, anchor, new_block)
        elif op_type == "MODIFIED" and new_block:
            text = merge_modified(text, anchor, new_block)
        elif op_type == "REMOVED":
            text = merge_removed(text, anchor)
    return text


def prepare_operations_from_manifest(
    manifest: DeltaManifest,
    blocks: dict[str, str],  # {anchor: new_block_text}
) -> list[dict]:
    """从 manifest + 区块词典构建可执行操作列表。"""
    ops = []
    for op in manifest.operations or []:
        anchor = op.get("anchor", "")
        entry = {
            "op": op.get("op", ""),
            "anchor": anchor,
            "new_block": blocks.get(anchor, ""),
        }
        ops.append(entry)
    return ops


def merge_delta(
    spec_text: str,
    manifest: DeltaManifest,
    blocks: dict[str, str],
) -> str:
    """带 manifest 的完整 delta 合并。"""
    ops = prepare_operations_from_manifest(manifest, blocks)
    return apply_operations(spec_text, ops)