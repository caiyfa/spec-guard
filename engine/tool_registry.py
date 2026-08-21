"""工具注册表：领域步骤（tool）的元数据中心。

格式 2.0 核心：YAML 步骤语法冻结为 3 原语（call / db_query / poll）+ tool 信封。
新增领域能力 = 在对应模块声明 tool 元数据 + 注册 handler，YAML 语法层零变更，
format_spec 的 tool 目录由本注册表动态生成（单一真相源）。

元数据在模块导入时注册（无需运行时上下文），handler 绑定在 engine.registry.Registry
（运行时）。step_tool 分发器以 name 关联两者。

T-973 命名空间：TOOLS 键改为 `{system}:{name}`（core 内置除外）——多系统动态注册
共存时防撞名；同键重复注册 = 热重建覆盖（不再视为冲突），跨系统同名各自独立。
YAML `use:` 支持裸名（唯一命中即用）与限定名（`tdm:select_emp`）两种写法。
"""

import contextvars
from dataclasses import dataclass, field

# 当前注册中的系统（loader 装配系统包时设置；extensions.py 里 register_tool 免写 system 参数）
_CTX_REGISTERING_SYSTEM: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sg_registering_system", default="")


@dataclass
class ToolSpec:
    name: str                                   # 裸名（YAML use: 写法）
    desc: str
    args: dict = field(default_factory=dict)      # {参数名: 说明}
    outputs: list = field(default_factory=list)   # 产出变量名（save 对象的字段）
    system: str = "core"                          # 归属系统（core=引擎内置）


TOOLS = {}


def tool_key(system: str, name: str) -> str:
    """TOOLS 字典键：core 内置用裸名，系统工具用 system:name 限定名。"""
    return name if system in ("", "core") else f"{system}:{name}"


def set_registering_system(system: str):
    """loader 装配系统包期间设置当前系统（返回 reset token）。"""
    return _CTX_REGISTERING_SYSTEM.set(system or "")


def register_tool(name, desc, args=None, outputs=None, system=""):
    """注册 tool 元数据。

    system 缺省取「当前注册中的系统」（loader 上下文），无上下文 = core 内置。
    同键重复注册 = 热重建覆盖（T-973：系统包重载不再撞名崩溃）。
    """
    sys_name = system or _CTX_REGISTERING_SYSTEM.get() or "core"
    key = tool_key(sys_name, name)
    TOOLS[key] = ToolSpec(name=name, desc=desc, args=args or {},
                          outputs=outputs or [], system=sys_name)
    return key


def unregister_system_tools(system: str) -> int:
    """移除某系统注册的全部 tool 元数据（系统包停用/重建前调用）。返回移除数。"""
    keys = [k for k, t in TOOLS.items() if t.system == system and system != "core"]
    for k in keys:
        TOOLS.pop(k, None)
    return len(keys)


def resolve_tool(use: str):
    """use 名 → (ToolSpec, handler 名)。裸名唯一命中 / 限定名精确命中。

    裸名多系统同名 → None（调用方报错并提示用限定名）。
    """
    if use in TOOLS:
        return TOOLS[use], TOOLS[use].name
    matches = [t for t in TOOLS.values() if t.name == use]
    if len(matches) == 1:
        return matches[0], matches[0].name
    return None, use


def get_tool(name):
    return TOOLS.get(name)


def list_tools():
    return [TOOLS[k] for k in sorted(TOOLS)]


def catalog_dict():
    """tool 目录（结构化，供 /api/reference/tools 与 format_spec 使用）"""
    return [
        {"name": t.name, "system": t.system, "desc": t.desc,
         "args": t.args, "outputs": t.outputs}
        for t in list_tools()
    ]


def catalog_markdown():
    """tool 目录 Markdown 表格（format_spec 动态段；非 core 工具标注归属系统）"""
    lines = [
        "| tool | 归属系统 | 说明 | 参数（with 段） | 产出变量 |",
        "|------|----------|------|----------------|----------|",
    ]
    for t in list_tools():
        args_md = "<br>".join(f"`{k}`：{v}" for k, v in t.args.items()) or "—"
        outs_md = "、".join(f"`{o}`" for o in t.outputs) or "—"
        lines.append(f"| `{t.name}` | {t.system} | {t.desc} | {args_md} | {outs_md} |")
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
        "pool": "词库名（text 用：由系统适配包注入，如 activity_name/department/person_name）",
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
