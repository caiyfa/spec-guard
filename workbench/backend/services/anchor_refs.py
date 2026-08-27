"""FR/AC 锚点 → spec 原文解析（T-1023 结构化阅读视图数据源）。

链路：扫描工作区 specs/ 全部 spec.md 定位锚点 → `sg_core.spec_sections`
按锚点切原文片段。AC 通过 AnchorInfo.ac_ids 反查所属 FR 的文件。

**同号歧义**：FR/AC 编号只在单个 spec 文件内唯一，跨模块天然重号（如 FR-005
在 data-export / history-inventory / person-profile 各有定义）——与
`scan_anchors` 后者覆盖的取舍不同，这里返回**全部候选** matches，并按 hint
（通常是场景文件路径）与候选文件路径的分词交集降序，前端默认取 [0]、
同号可切换；未命中诚实 `found=False`，不做全文搜索兜底（不猜）。
"""

from __future__ import annotations

import re
from pathlib import Path

from sg_core.spec_sections import extract_fr_section
from specstd.anchors import parse_spec_md
from specstd.schema import DIR_SPECS, FILE_SPEC_MD, AnchorInfo

MAX_IDS = 50

_TOKEN_RE = re.compile(r"[\w一-龥]+")


def _scan_all(ws_root: Path) -> tuple[dict[str, list[AnchorInfo]], dict[str, list[AnchorInfo]]]:
    """扫描 specs/ 全部 spec.md：FR ID → [AnchorInfo]（保留同号），AC ID → [所属 FR AnchorInfo]。"""
    fr_map: dict[str, list[AnchorInfo]] = {}
    ac_map: dict[str, list[AnchorInfo]] = {}
    specs_dir = ws_root / DIR_SPECS
    if not specs_dir.is_dir():
        return fr_map, ac_map
    for spec_md in sorted(specs_dir.rglob(FILE_SPEC_MD)):
        for info in parse_spec_md(spec_md):
            fr_map.setdefault(info.fr_id, []).append(info)
            for ac in info.ac_ids:
                ac_map.setdefault(ac, []).append(info)
    return fr_map, ac_map


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 3}


def resolve_anchor_refs(ws_root: Path, ids: list[str], hint: str = "") -> list[dict]:
    """批量解析锚点原文。

    返回 [{id, found, matches: [{title, file, module, feature, start, end, chunk}]}]，
    matches 按 hint 路径词相关性降序（同分按文件路径序）。
    """
    fr_map, ac_map = _scan_all(ws_root)
    hint_tokens = _tokens(hint)
    text_cache: dict[str, str] = {}

    def _read(info: AnchorInfo) -> str:
        if info.file_path not in text_cache:
            text_cache[info.file_path] = Path(info.file_path).read_text(
                encoding="utf-8", errors="replace")
        return text_cache[info.file_path]

    refs: list[dict] = []
    for raw in ids[:MAX_IDS]:
        aid = (raw or "").strip()
        if not aid:
            continue
        candidates = fr_map.get(aid)
        if candidates is None and aid.upper().startswith("AC-"):
            candidates = ac_map.get(aid)
        matches: list[dict] = []
        for info in candidates or []:
            sec = extract_fr_section(_read(info), aid)
            if sec is None:
                # 锚点在清单中但切片未命中（如同名定义歧义块）——跳过该候选
                continue
            try:
                rel = str(Path(info.file_path).relative_to(ws_root)).replace("\\", "/")
            except ValueError:
                rel = info.file_path  # 不在工作区根内（理论不至）——原样给绝对路径
            # T-1025：相关性分数（hint 与候选路径的分词交集数）——前端据此把
            # 零相关候选折叠，测试用例视角默认只看对应模块的 spec
            score = len(hint_tokens & _tokens(info.file_path))
            matches.append({
                "title": sec["title"],
                "file": info.file_path,
                "rel": rel,
                "module": info.module,
                "feature": info.feature,
                "start": sec["start"],
                "end": sec["end"],
                "chunk": sec["chunk"],
                "score": score,
            })
        matches.sort(key=lambda m: (-m["score"], m["file"]))
        refs.append({"id": aid, "found": bool(matches), "matches": matches})
    return refs
