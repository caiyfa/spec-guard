"""tool_units — 工具调用名归一（T-1042 三期自 evals.replay 下沉，T-975 模式）。

会话里同一能力有三种调用形态，统一归一到（基名, action）单元：
  ① 助记形态 spec(action=read)（文档/技能/旧 golden case 里的写法）
  ② legacy 逻辑 id read_spec（T-982 收敛前旧会话，经 tool_meta.legacy_owner）
  ③ 基名+参数 spec + arguments.action（T-982 后新会话 LLM 的真实发送形态）

消费方：evals（轨迹重放/路径重放）、agent runtime（flow nudge 前置判定）。
工具名形态是共享基础设施，故沉 sg_core（依赖方向：agent/evals → sg_core ✓；
对 mcp_server.tool_meta 的引用是函数级懒加载——sg_core⇄mcp_server 函数级回边
已在 release_check 白名单，模块级零新增边）。
"""

from __future__ import annotations

_TOOL_META_READY = False


def _ensure_tool_meta() -> None:
    """填充 tool_meta._TOOL_META（legacy_owner 依赖；幂等，失败静默降级）。"""
    global _TOOL_META_READY
    if _TOOL_META_READY:
        return
    try:
        from mcp_server import server as _srv
        _srv.build_tool_modules()
    except Exception:
        pass
    _TOOL_META_READY = True


def normalize_tool_unit(name: str, args: dict | None = None) -> tuple[str, str]:
    """任意形态工具名 →（基名, action）。

    runtime._tool_map 键是合并基名，action 经 arguments.action 派发——这是
    LLM 调用的真实形态；spec(action=read) 只是文档助记写法；read_spec 是
    T-982 前旧会话的 legacy 逻辑 id。未识别名原样返回（诚实暴露，不猜）。
    """
    args = args or {}
    name = str(name or "")
    # ① 助记形态 name(action=x[, ...])
    if "(" in name and name.endswith(")"):
        base = name.split("(", 1)[0].strip()
        inner = name[name.index("(") + 1:-1]
        act = ""
        for part in inner.split(","):
            part = part.strip()
            if part.startswith("action="):
                act = part.split("=", 1)[1].strip().strip('"').strip("'")
        return base, act
    _ensure_tool_meta()
    try:
        from mcp_server.tools import tool_meta as tm
        meta = tm._TOOL_META.get(name)
        if meta is not None:
            # 注册工具：合并工具取 arguments.action；单体工具无 action
            act = str(args.get("action") or "") if getattr(meta, "actions", None) else ""
            return name, act
        owner = tm.legacy_owner(name)  # ② legacy 逻辑 id →（基名, action）
        if owner:
            return owner
    except Exception:
        pass
    # ③ 未注册名：原样保留（action 取参数里的，可能为空）
    return name, str(args.get("action") or "")


def units_of(items) -> list[tuple[str, str]]:
    """名字列表/单元列表 → 归一单元列表（元组原样，字符串归一）。"""
    out: list[tuple[str, str]] = []
    for it in items:
        if isinstance(it, tuple):
            out.append(it)
        else:
            out.append(normalize_tool_unit(it))
    return out
