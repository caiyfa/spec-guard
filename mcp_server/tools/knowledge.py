"""knowledge — 知识层工具（T-507 skills 目录化配套 + T-508 触景分发配套）。
>
> T-982 收敛：3 工具合并为单 knowledge 工具（action=skill/read/format_spec）。

工具：
  load_skill: 按需取技能正文（T-507——skills 目录常驻 system prompt，
              正文由本工具按需取，避免 15KB 技能正文全量注入）
  read_format_spec: 按章节取格式规范细节（T-508——format_spec 骨架化后按需取）
  read_knowledge: 按 kg:// 引用读取知识正文（T-508 触景分发指针配套）

全部为纯读（side_effect: none）。
"""

from pathlib import Path

from mcp.types import Tool, TextContent
from mcp_server.tools.tool_meta import ActionMeta, SIDE_DRAFT, consolidate  # T-982

SG_ROOT = Path(__file__).resolve().parent.parent.parent

from sg_core.skill_loader import load_skill as _load_skill  # noqa: E402


def _skill_text(skill) -> str:
    """技能正文（frontmatter 元数据 + 正文）。"""
    header = (f"技能: {skill.name}\n"
              f"描述: {skill.description}\n"
              f"版本: {skill.version or '（未声明）'} | 作者: {skill.author or '（未声明）'}\n"
              f"触发: {skill.trigger or '（未声明）'}\n"
              f"依赖工具: {', '.join(skill.depends_tools) or '（无）'}\n"
              f"关键词: {', '.join(skill.keywords) or '（无）'}\n"
              f"{'-' * 40}\n")
    return header + skill.content


def _read_knowledge(ref: str) -> str:
    """按 kg://{workspace}/{layer}/{token} 读取知识正文（T-508）。

    物理隔离：term/experience 从工作区根解析；env 从系统适配包 config 解析。
    ref 非法（越界/格式错）返回错误消息，不抛异常。
    """
    import re as _re
    m = _re.fullmatch(r"kg://([A-Za-z0-9_-]+)/([a-z]+)/([A-Za-z0-9_.-]+)", ref or "")
    if not m:
        return f"知识引用格式非法: {ref!r}（应为 kg://{{workspace}}/{{layer}}/{{token}}）"
    ws_name, layer, token = m.group(1), m.group(2), m.group(3)

    try:
        from specstd.workspace import get_workspace
        info = get_workspace(ws_name)
        if not info:
            return f"工作区不存在: {ws_name}"
        ws_root = info.root

        if layer in ("term", "experience"):
            if layer == "term":
                from specstd.glossary import parse_glossary, GLOSSARY_FILE
                entries = parse_glossary(ws_root / GLOSSARY_FILE)
                for e in entries:
                    if e.token == token:
                        return (f"[知识] {e.title}（{e.token}）\n\n"
                                f"语义：{e.semantic}\n规则：{e.rules}\n数据：{e.data}\n"
                                f"关联：{e.refs}\n歧义史：{e.history}\n出处：{e.source}")
                return f"词条不存在: {token}"
            # experience：经验库目录
            exp_dir = ws_root / ".specguard" / "experience"
            import glob
            for f in glob.glob(str(exp_dir / "*.md")):
                if token in Path(f).stem:
                    return f"[经验] {Path(f).name}\n\n" + Path(f).read_text(encoding="utf-8")
            return f"经验条目不存在: {token}"

        if layer == "env":
            # env-{env} → systems/{system}/config/env.{env}.md
            env = token.removeprefix("env-")
            env_md = Path(SG_ROOT) / "systems" / info.system / "config" / f"env.{env}.md"
            if env_md.is_file():
                return f"[环境叙事] {env_md.name}\n\n" + env_md.read_text(encoding="utf-8")
            return f"环境叙事不存在: {token}"
    except Exception as e:
        return f"知识读取失败: {e}"
    return f"未知知识层: {layer}"


_TOOL_DECLS = [
    Tool(
        name="load_skill",
        description="按需读取技能正文（技能目录已在 system prompt 常驻，正文需要时用本工具取）。"
                    "参数 name 为技能名（目录中的 <skill name=...>）。返回技能元数据 + 完整正文。",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能名（如 generate-scenario）"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="read_knowledge",
        description="按 kg:// 引用读取知识正文（触景触发投递的 read_knowledge(ref) 指针配套，T-508）。"
                    "参数 ref 形如 kg://{workspace}/{layer}/{token}（layer ∈ term/env/experience）。"
                    "返回对应词条/环境叙事/经验条目的完整内容；引用不存在返回空。",
        inputSchema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "kg:// 知识引用"},
            },
            "required": ["ref"],
        },
    ),
    Tool(
        name="read_format_spec",
        description="按章节读取 YAML 格式规范细节（骨架已在 system prompt 常驻，"
                    "写场景前用本工具取所需章节全文）。参数 section 为章节号（如 1.6/3/8）"
                    "或章节标题子串（如 步骤语法/断言类型）。",
        inputSchema={
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "章节号或标题子串"},
            },
            "required": ["section"],
        },
    ),
]


async def _legacy_handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "load_skill":
        skill_name = arguments.get("name", "")
        skill = _load_skill(skill_name)
        if not skill:
            from sg_core.skill_loader import list_skills
            available = "、".join(s.name for s in list_skills())
            return [TextContent(type="text",
                                text=f"技能不存在: {skill_name}。可用技能: {available}")]
        return [TextContent(type="text", text=_skill_text(skill))]

    if name == "read_knowledge":
        ref = arguments.get("ref", "")
        return [TextContent(type="text", text=_read_knowledge(ref))]

    if name == "read_format_spec":
        section = arguments.get("section", "")
        try:
            from sg_core.format_spec import generate_format_spec_md
            md = generate_format_spec_md()
            chunk = _extract_section(md, section)
            if not chunk:
                return [TextContent(type="text",
                                    text=f"未找到章节: {section!r}（可用章节见 system prompt 骨架索引）")]
            return [TextContent(type="text", text=chunk)]
        except Exception as e:
            return [TextContent(type="text", text=f"格式规范加载失败: {e}")]

    return [TextContent(type="text", text=f"未知工具: {name}")]


def _extract_section(md: str, section: str) -> str:
    """按章节号/标题子串提取 format_spec 章节全文（T-508 read_format_spec）。

    章节边界：匹配到的标题行 → 下一个同级或更高级标题之前。
    """
    import re
    section = section.strip()
    lines = md.splitlines()
    # 定位目标标题行（标题号前缀匹配或子串匹配）
    start_idx = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not m:
            continue
        title = m.group(2)
        # 精确章节号匹配（如 "1.6" 匹配 "### 1.6 步骤语法"）
        if re.match(rf"^{re.escape(section)}\s", title):
            start_idx = i
            level = len(m.group(1))
            break
        # 标题子串匹配
        if section in title and (start_idx is None):
            start_idx = i
            level = len(m.group(1))
    if start_idx is None:
        return ""
    # 章节边界：下一个同级或更高级标题
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[j])
        if m and len(m.group(1)) <= level:
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


# ══════════════════════════════════════════════════════════
# T-982 工具收敛：3 碎片合并为单 knowledge 工具（action 参数化）
# ══════════════════════════════════════════════════════════
TOOLS, handle = consolidate(
    "knowledge",
    "知识层按需取用（纯读）：skill 取技能正文、read 读知识条目、format_spec 读格式规范章节。",
    actions={
        "skill": ActionMeta(legacy="load_skill"),
        "read": ActionMeta(legacy="read_knowledge"),
        "format_spec": ActionMeta(legacy="read_format_spec"),
    },
    decls=_TOOL_DECLS,
    legacy_handle=_legacy_handle,
    domain="knowledge",
    rbac="product",
)
