"""specstd.glossary — 语义词典（glossary.md）轻解析（L1 语义词典）。

词条格式约定（T-505，七维适配版）：
- 标题行：`### 词条标题 [token: 词条token]`（[token:] 锚点复用 specstd/anchors 风格）
- 字段行（Markdown 列表，维度名固定）：
  - **语义**：精确语义（一句话）
  - **规则**：SHALL 规则（背后挂的业务规则）
  - **数据**：数据维度（表/字段/码值）
  - **关联**：FR 锚点 / 场景 ID / 资源码 / env 键（空格或分号分隔）
  - **歧义史**：历史上的歧义点（可选）
  - **出处**：关联文档/代码位置

词条↔FR 关联完整性校验进 conformance 留 T-508 后评（本模块只提供解析与提取能力）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 工作区根下的词典文件名（随 spec 同库同评审）
GLOSSARY_FILE = "glossary.md"

# [token:] 锚点标题：### 词条标题 [token: 词条token]
GLOSSARY_HEADING_RE = re.compile(
    r"^###\s+(.+?)\s*\[token:\s*([A-Za-z0-9_.-]+)\s*\]\s*$", re.MULTILINE)

# 七维字段行：- **语义**：xxx（MULTILINE：^ 匹配每行行首）
GLOSSARY_FIELD_RE = re.compile(r"^-\s*\*\*([^*]+)\*\*\s*[:：]\s*(.*)$", re.MULTILINE)

# 词条「关联」字段中的裸 FR ID（与 covers: [FR-xxx] 风格一致，无需加粗）
GLOSSARY_FR_RE = re.compile(r"\bFR-[\w-]+\b")

# 字段名 → GlossaryEntry 属性映射
_FIELD_MAP = {
    "语义": "semantic",
    "规则": "rules",
    "数据": "data",
    "关联": "refs",
    "歧义史": "history",
    "出处": "source",
}


@dataclass
class GlossaryEntry:
    """单条词条（七维适配版）。"""
    token: str                       # [token:] 锚点（机器寻址用）
    title: str                       # 词条标题（人类可读）
    semantic: str = ""               # 精确语义
    rules: str = ""                  # SHALL 规则
    data: str = ""                   # 数据维度（表/字段/码值）
    refs: str = ""                   # 关联（FR/场景/资源码/env 键）
    history: str = ""                # 歧义史（可选）
    source: str = ""                 # 出处
    line: int = 0                    # 词条标题所在行号（1-based）

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "title": self.title,
            "semantic": self.semantic,
            "rules": self.rules,
            "data": self.data,
            "refs": self.refs,
            "history": self.history,
            "source": self.source,
            "line": self.line,
        }


def parse_glossary(path: Path) -> list[GlossaryEntry]:
    """解析单个 glossary.md，返回词条列表（按出现顺序）。

    无 [token:] 锚点的标题不算词条（与 anchors 同款纪律）；重复 token 后者覆盖
    （唯一性冲突由 T-508 后的 conformance 规则检测）。
    """
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 收集标题行（位置 + token + title）
    matches = []
    for i, line in enumerate(lines, start=1):
        m = GLOSSARY_HEADING_RE.match(line)
        if m:
            matches.append((i, m.group(1).strip(), m.group(2)))
    if not matches:
        return []

    entries: list[GlossaryEntry] = []
    for idx, (line_no, title, token) in enumerate(matches):
        # 截取到下一个词条标题之前的文本
        end_line = matches[idx + 1][0] if idx + 1 < len(matches) else len(lines) + 1
        chunk = "\n".join(lines[line_no:end_line])

        entry = GlossaryEntry(token=token, title=title, line=line_no)
        for m in GLOSSARY_FIELD_RE.finditer(chunk):
            attr = _FIELD_MAP.get(m.group(1).strip())
            if attr:
                setattr(entry, attr, m.group(2).strip())
        entries.append(entry)

    # 重复 token 后者覆盖（保持首次出现位置）
    by_token: dict[str, GlossaryEntry] = {}
    for e in entries:
        by_token[e.token] = e
    return list(by_token.values())


def scan_glossary(workspace_root: Path) -> dict[str, GlossaryEntry]:
    """扫描工作区根 glossary.md，返回 token → 词条映射（无词典返回空 dict）。"""
    path = workspace_root / GLOSSARY_FILE
    if not path.is_file():
        return {}
    return {e.token: e for e in parse_glossary(path)}


def extract_fr_refs(entries: list[GlossaryEntry]) -> dict[str, list[str]]:
    """从词条「关联」字段提取 FR 引用，返回 {token: [FR-xxx, ...]}。

    供 T-508 后的词条↔FR 关联完整性校验使用（本模块不执行校验）。
    """
    result: dict[str, list[str]] = {}
    for e in entries:
        frs = sorted(set(GLOSSARY_FR_RE.findall(e.refs)))
        result[e.token] = frs
    return result
