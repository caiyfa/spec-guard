"""agent.skill_loader — 技能文件加载器（G3-2）。

解析 agent/skills/{name}.md 文件，提取 YAML frontmatter + Markdown 正文。
30 秒内存缓存，支持热加载（新增 SKILL.md 无需重启）。
技能内容注入 system prompt 的 XML 块，模型可见。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# 内存缓存
_CACHE: dict[str, tuple[float, SkillDef]] = {}
_CACHE_TTL: float = 30  # 30 秒


@dataclass
class SkillDef:
    """技能定义。"""
    name: str                         # 技能名称（文件名去掉 .md）
    description: str = ""             # 技能简述
    trigger: str = ""                 # 触发条件描述
    content: str = ""                 # Markdown 正文（技能详细内容）


def load_skill(name: str) -> Optional[SkillDef]:
    """加载单个技能定义。"""
    if not name:
        return None

    # 缓存检查
    now = time.time()
    cached = _CACHE.get(name)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    skill_file = SKILLS_DIR / f"{name}.md"
    if not skill_file.is_file():
        return None

    text = skill_file.read_text(encoding="utf-8")
    skill_def = _parse_skill_file(name, text)

    _CACHE[name] = (now, skill_def)
    return skill_def


def list_skills() -> list[SkillDef]:
    """列出全部可用技能（扫描 agent/skills/ 目录）。"""
    if not SKILLS_DIR.is_dir():
        return []

    skills = []
    for f in sorted(SKILLS_DIR.glob("*.md")):
        name = f.stem
        skill = load_skill(name)
        if skill:
            skills.append(skill)
    return skills


def clear_cache():
    """清空缓存（调试用）。"""
    _CACHE.clear()


def build_skills_xml(mode: str = "") -> str:
    """构建技能 XML 块，注入 system prompt。

    K-014：按模式过滤（不分模式全量注入是 token 浪费——debug-failure 技能
    在 generate 模式毫无意义）。mode 为空时返回全部（向后兼容）。

    格式：
        <skills>
          <skill name="generate-scenario" description="...">
            ...技能内容...
          </skill>
          ...
        </skills>
    """
    skills = list_skills()
    if mode in _MODE_SKILLS:
        allowed = _MODE_SKILLS[mode]
        skills = [s for s in skills if s.name in allowed]
    if not skills:
        return ""

    parts = ["<skills>"]
    for s in skills:
        parts.append(f'  <skill name="{s.name}" description="{s.description}">')
        parts.append(s.content)
        parts.append("  </skill>")
    parts.append("</skills>")
    return "\n".join(parts)


# K-014: 技能 → 模式映射（未列出的模式不注入任何技能）
_MODE_SKILLS: dict[str, set[str]] = {
    "generate": {"generate-scenario", "validate-conformance"},
    "debug": {"debug-failure", "validate-conformance"},
    "analyze": {"validate-conformance"},
    "audit": set(),
    "chat": set(),
}


def _parse_skill_file(name: str, text: str) -> SkillDef:
    """解析技能文件：YAML frontmatter + Markdown 正文。"""
    frontmatter = {}
    body = text

    # 提取 YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                frontmatter = {}
            body = parts[2].strip()

    return SkillDef(
        name=frontmatter.get("name", name),
        description=str(frontmatter.get("description", "")),
        trigger=str(frontmatter.get("trigger", "")),
        content=body,
    )
