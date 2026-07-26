"""工具注册表：领域步骤（tool）的元数据中心。

格式 2.0 核心：YAML 步骤语法冻结为 3 原语（call / db_query / poll）+ tool 信封。
新增领域能力 = 在对应模块声明 tool 元数据 + 注册 handler，YAML 语法层零变更，
format_spec 的 tool 目录由本注册表动态生成（单一真相源）。

元数据在模块导入时注册（无需运行时上下文），handler 绑定在 engine.registry.Registry
（运行时）。step_tool 分发器以 name 关联两者。
"""

from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    name: str
    desc: str
    args: dict = field(default_factory=dict)      # {参数名: 说明}
    outputs: list = field(default_factory=list)   # 产出变量名（save 对象的字段）


TOOLS = {}


def register_tool(name, desc, args=None, outputs=None):
    """注册 tool 元数据（模块导入时调用，幂等防护：重复注册视为定义冲突）"""
    if name in TOOLS:
        raise ValueError(f"tool 重复注册: {name}（已存在: {TOOLS[name].desc}）")
    TOOLS[name] = ToolSpec(name=name, desc=desc, args=args or {}, outputs=outputs or [])


def get_tool(name):
    return TOOLS.get(name)


def list_tools():
    return [TOOLS[k] for k in sorted(TOOLS)]


def catalog_dict():
    """tool 目录（结构化，供 /api/reference/tools 与 format_spec 使用）"""
    return [
        {"name": t.name, "desc": t.desc, "args": t.args, "outputs": t.outputs}
        for t in list_tools()
    ]


def catalog_markdown():
    """tool 目录 Markdown 表格（format_spec 动态段）"""
    lines = [
        "| tool | 说明 | 参数（with 段） | 产出变量 |",
        "|------|------|----------------|----------|",
    ]
    for t in list_tools():
        args_md = "<br>".join(f"`{k}`：{v}" for k, v in t.args.items()) or "—"
        outs_md = "、".join(f"`{o}`" for o in t.outputs) or "—"
        lines.append(f"| `{t.name}` | {t.desc} | {args_md} | {outs_md} |")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 引擎内置 tool（handler 在 scenario_runner.register_builtin_steps 注册）
# ══════════════════════════════════════════════════════════

register_tool(
    "random",
    desc="随机数据生成（随机数/浮点/文本/词库抓取/UUID/列表抓取）",
    args={
        "type": "number|float|text|uuid|pick（默认 number）",
        "min/max": "数值范围（number/float，默认 1~100 / 0~100）",
        "precision": "浮点精度（默认 1）",
        "pool": "词库名（text 用：activity_name/department/person_name/eval_text/session_desc/tag）",
        "length": "随机字符串长度（text 无 pool 时，默认 8）",
        "suffix": "文本追加随机数字后缀（bool，保证唯一性）",
        "items": "自定义列表（type=pick 必填）",
    },
    outputs=["（随机值本身，标量）"],
)

register_tool(
    "set_var",
    desc="直接设置变量（常量或 {{var}} 插值表达式）",
    args={"vars": "{k: v} 映射，v 支持插值"},
    outputs=["vars 中每个 key 都是变量"],
)
