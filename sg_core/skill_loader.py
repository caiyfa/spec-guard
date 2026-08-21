"""skill_loader — 技能文件加载器（G3-2；T-976 下沉 sg_core）。

解析 agent/skills/{name}.md 文件，提取 YAML frontmatter + Markdown 正文。
30 秒内存缓存，支持热加载（新增 SKILL.md 无需重启）。
技能内容注入 system prompt 的 XML 块，模型可见。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# 技能资产目录留在 agent/skills/（AGENTS.md 约定路径 + 总控 §6 基准行引用）；
# T-976 loader 下沉 sg_core 解 agent↔mcp_server 环，此处仅为数据路径约定（非 import 依赖）
SKILLS_DIR = Path(__file__).resolve().parent.parent / "agent" / "skills"

# 内存缓存
_CACHE: dict[str, tuple[float, SkillDef]] = {}
_CACHE_TTL: float = 30  # 30 秒


@dataclass
class SkillDef:
    """技能定义（T-080：新增 version/author/depends_tools 字段）。"""
    name: str                         # 技能名称（文件名去掉 .md）
    description: str = ""             # 技能简述
    version: str = ""                 # 自建 SemVer（T-080 新增）
    author: str = ""                  # 维护方（T-080 新增）
    depends_tools: list[str] = field(default_factory=list)  # 依赖 MCP 工具清单（T-080 新增）
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
    """构建技能目录 XML 块，注入 system prompt（T-507 目录化）。

    T-507 瘦身：目录常驻（name+description+trigger），正文由 load_skill
    工具按需取（skill 正文 10 个约 15KB，全量注入是 prompt 静态部分主重之一）。
    mode 参数保留仅为向后兼容，已无效。

    格式：
        <skills>
          <skill name="generate-scenario" description="..." trigger="..." />
          ...
        </skills>
    """
    skills = list_skills()
    if not skills:
        return ""

    import html as _html
    parts = ["<skills>"]
    for s in skills:
        name_esc = _html.escape(s.name, quote=True)
        desc_esc = _html.escape(s.description, quote=True)
        trig_esc = _html.escape(s.trigger, quote=True)
        parts.append(f'  <skill name="{name_esc}" description="{desc_esc}" trigger="{trig_esc}" />')
    parts.append("</skills>")
    return "\n".join(parts)


def _parse_skill_file(name: str, text: str) -> SkillDef:
    """解析技能文件：YAML frontmatter + Markdown 正文。T-080 新增格式校验。"""
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

    # T-080：格式校验（拒载）
    _validate_frontmatter(frontmatter, name)

    raw_kw = frontmatter.get("keywords", []) or []
    keywords = []
    if isinstance(raw_kw, list):
        keywords = [str(k).strip() for k in raw_kw if str(k).strip()]
    elif isinstance(raw_kw, str):
        # 兼容逗号分隔字符串形式
        keywords = [k.strip() for k in raw_kw.split(",") if k.strip()]

    # T-080：depends_tools 解析
    raw_deps = frontmatter.get("depends_tools", []) or []
    if isinstance(raw_deps, list):
        depends_tools = [str(d).strip() for d in raw_deps if str(d).strip()]
    elif isinstance(raw_deps, str):
        depends_tools = [d.strip() for d in raw_deps.split(",") if d.strip()]
    else:
        depends_tools = []

    return SkillDef(
        name=frontmatter.get("name", name),
        description=str(frontmatter.get("description", "")),
        version=str(frontmatter.get("version", "")),
        author=str(frontmatter.get("author", "")),
        depends_tools=depends_tools,
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


# ══════════════════════════════════════════════════════════
# T-080: 格式校验与元数据查询
# ══════════════════════════════════════════════════════════


def _validate_frontmatter(frontmatter: dict, expected_name: str) -> None:
    """T-080：格式校验——不符合项直接抛 ValueError（拒载）。

    检验项：
    - name 缺失/空/超 64 字符/与文件名不匹配
    - description 缺失/空/超 1024 字符
    - frontmatter 字符串字段含 `<...>` 注入
    - 未知字段静默忽略（宽容解析，不抛）
    """
    name = frontmatter.get("name", "")
    name_str = str(name).strip() if name else ""
    if not name_str:
        raise ValueError("skill frontmatter 'name' 缺失或为空")
    if len(name_str) > 64:
        raise ValueError(f"skill name 超长（{len(name_str)} 字符，上限 64）")
    # 目录名=name 强校验（M13 §4.1：与文件名精确一致，不做 -/_ 等价）
    if name_str != expected_name:
        raise ValueError(f"skill name {name_str!r} 与文件名 {expected_name!r} 不匹配")

    desc = frontmatter.get("description", "")
    desc_str = str(desc).strip() if desc else ""
    if not desc_str:
        raise ValueError("skill frontmatter 'description' 缺失或为空")
    if len(desc_str) > 1024:
        raise ValueError(f"skill description 超长（{len(desc_str)} 字符，上限 1024）")

    # 所有字符串字段的 <> 注入检测
    _INJECTION_RE = re.compile(r"<[^>]+>")
    for key, val in frontmatter.items():
        if isinstance(val, str) and _INJECTION_RE.search(val):
            raise ValueError(
                f"skill frontmatter '{key}' 包含 '<>' 注入标记: {val!r}")
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and _INJECTION_RE.search(item):
                    raise ValueError(
                        f"skill frontmatter '{key}' 包含 '<>' 注入标记: {item!r}")


def get_skill_metadata(name: str) -> Optional[dict]:
    """T-080：返回技能元数据（不含 content 正文，节省序列化成本）。"""
    skill = load_skill(name)
    if not skill:
        return None
    return {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "author": skill.author,
        "depends_tools": skill.depends_tools,
        "trigger": skill.trigger,
        "keywords": skill.keywords,
        "source": "internal",
    }


def list_skills_metadata() -> list[dict]:
    """T-080：全部技能元数据列表。"""
    return [
        get_skill_metadata(s.name)
        for s in list_skills()
        if get_skill_metadata(s.name)
    ]
