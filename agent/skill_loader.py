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
    keywords: list[str] = field(default_factory=list)  # K-xxx：确定性触发关键词
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

    K-023 去模式化：全量注入（技能共 3 个 ~2.5k 字符，全量成本可忽略；
    mode 参数保留仅为向后兼容，已无效）。

    格式：
        <skills>
          <skill name="generate-scenario" description="...">
            ...技能内容...
          </skill>
          ...
        </skills>
    """
    skills = list_skills()
    if not skills:
        return ""

    parts = ["<skills>"]
    for s in skills:
        parts.append(f'  <skill name="{s.name}" description="{s.description}">')
        parts.append(s.content)
        parts.append("  </skill>")
    parts.append("</skills>")
    return "\n".join(parts)


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

    raw_kw = frontmatter.get("keywords", []) or []
    keywords = []
    if isinstance(raw_kw, list):
        keywords = [str(k).strip() for k in raw_kw if str(k).strip()]
    elif isinstance(raw_kw, str):
        # 兼容逗号分隔字符串形式
        keywords = [k.strip() for k in raw_kw.split(",") if k.strip()]

    return SkillDef(
        name=frontmatter.get("name", name),
        description=str(frontmatter.get("description", "")),
        trigger=str(frontmatter.get("trigger", "")),
        keywords=keywords,
        content=body,
    )


def match_skills_hint(text: str) -> str:
    """K-xxx：确定性技能触发——关键词子串匹配（大小写不敏感）。

    用户消息命中技能 frontmatter 的 keywords 时，返回注入提示（可多技能命中，
    全部列出，由模型结合上下文最终采用）；未命中返回空串。
    与 <skills> XML 全量注入互补：XML 是「技能存在性」，这里是「本任务优先用哪个」。
    """
    if not text:
        return ""
    low = text.lower()
    hits = []
    for s in list_skills():
        if any(kw and kw.lower() in low for kw in s.keywords):
            hits.append(s)
    if not hits:
        return ""
    lines = ["[技能提示] 用户请求关键词匹配到以下技能，请优先遵循其流程："]
    for s in hits:
        lines.append(f"- {s.name}：{s.description}")
    return "\n".join(lines)
