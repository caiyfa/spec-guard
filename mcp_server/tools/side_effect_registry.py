"""side_effect_registry — MCP 工具副作用注册表（T-081；T-982 起从 tool_meta 派生）。

side_effect 枚举：
- none: 纯读无副作用（默认）。运行时强制：执行前后仓库指纹比对，变化即报错。
- draft: 产物一律草稿态。写 draft 目录、场景库、台账等内部存储。
- external-write: 触外部系统的写。_EXTERNAL_WRITERS 为空集（「外部写不进 MCP」红线）。

T-982：_KNOWN_WRITERS 手工登记废除，分级改从 tool_meta 声明派生（合并工具按
action 粒度判定）——新增写工具漏登记不再可能：未声明 side_effect 的工具默认
none（纯读 + 指纹闸），写工具必须在声明处标 SIDE_DRAFT 否则会被指纹闸拦下。
查询兼容 legacy 工具名（自动映射到所属 (tool, action)，测试/脚本零改动）。
"""

from __future__ import annotations

import logging

from mcp_server.tools.tool_meta import (
    SIDE_NONE, SIDE_DRAFT, SIDE_EXTERNAL_WRITE, VALID_SIDES,  # noqa: F401 再导出
    legacy_owner, resolve_side_effect,
)

_log = logging.getLogger("side_effect_registry")

# ── 外部写集（红线：初始化为空——「外部写不进 MCP」通则）──
_EXTERNAL_WRITERS: set[str] = set()


def get_side_effect(tool_name: str, action: str = "") -> str:
    """查询工具（或 legacy 工具名）的副作用级别（默认 none）。

    合并工具按 action 粒度：get_side_effect("draft", "write") 或兼容形态
    get_side_effect("write_draft") 均可。
    """
    if tool_name in _EXTERNAL_WRITERS:
        return SIDE_EXTERNAL_WRITE
    owner = legacy_owner(tool_name)
    if owner is None:
        return SIDE_NONE
    name, owned_action = owner
    return resolve_side_effect(name, action or owned_action)


def is_pure_read(tool_name: str, action: str = "") -> bool:
    """是否为纯读工具/action（side_effect=none）。"""
    return get_side_effect(tool_name, action) == SIDE_NONE


def list_tools_by_side_effect(level: str) -> list[str]:
    """按副作用级别列出逻辑工具 id（合并工具展开为 legacy action 名）。

    返回逻辑 id 而非合并工具名：消费方（测试/审计报表）以收敛前词汇读取，
    收敛前后口径一致。
    """
    from mcp_server import server  # 延迟导入（避环：server 聚合工具模块）
    out: list[str] = []
    for tool in server.ALL_TOOLS:
        if tool.name in _EXTERNAL_WRITERS:
            if level == SIDE_EXTERNAL_WRITE:
                out.append(tool.name)
            continue
        from mcp_server.tools.tool_meta import get_meta
        meta = get_meta(tool.name)
        if not meta.actions:
            if resolve_side_effect(tool.name) == level:
                out.append(tool.name)
            continue
        for a in meta.actions:
            if resolve_side_effect(tool.name, a) == level:
                from mcp_server.tools.tool_meta import logical_id
                out.append(logical_id(tool.name, a))
    return sorted(out)


def invalidate_cache():
    """兼容桩：派生自 tool_meta 声明（import 时登记），无缓存可清。

    保留仅为旧调用点零改动（工具模块热加载场景已由 import 机制覆盖）。
    """
