"""T-507 量化脚本：实测 system prompt 各静态组成部分大小。"""
import re
from pathlib import Path


# format_spec
from sg_core.format_spec import generate_format_spec_md  # noqa: E402

fs = generate_format_spec_md()
print(f"format_spec: {len(fs)} chars")

# agents_md（tdm 工作区）
from specstd.workspace import read_agents_md  # noqa: E402

am = read_agents_md()
print(f"AGENTS.md(工作区): {len(am)} chars")

# skills
from agent.skill_loader import build_skills_xml, list_skills  # noqa: E402

sx = build_skills_xml()
skills = list_skills()
print(f"skills XML 全量: {len(sx)} chars ({len(skills)} 技能)")
total_content = sum(len(s.content) for s in skills)
print(f"  skills 正文合计: {total_content} chars; 目录(仅 name+description)估计: {len(sx) - total_content} chars")

# j2 模板固定文本
j2 = Path("agent/prompts/system.md.j2").read_text(encoding="utf-8")
fixed = re.sub(r"\{\{[^}]+\}\}", "[PH]", j2)
print(f"j2 模板总长: {len(j2)} chars; 固定文本(去占位符): {len(fixed.replace('[PH]',''))} chars")

total = len(fs) + len(am) + len(sx) + len(fixed.replace("[PH]", ""))
print(f"合计静态: {total} chars ({total/1024:.1f} KB)")
