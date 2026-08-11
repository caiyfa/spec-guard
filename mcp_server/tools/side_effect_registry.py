"""side_effect_registry — MCP 工具副作用注册表（T-081）。

side_effect 枚举：
- none: 纯读无副作用（默认）。运行时强制：执行前后仓库指纹比对，变化即报错。
- draft: 产物一律草稿态。写 draft 目录、场景库、台账等内部存储。
- external-write: 触外部系统的写。默认为空集（「外部写不进 MCP」通则的代码形态）。

构建方式：全模块扫描，未显式声明的工具默认 none。
"""

from __future__ import annotations

import logging
from typing import Optional

from mcp_server import server

_log = logging.getLogger("side_effect_registry")

# ── 级别枚举 ──
SIDE_NONE = "none"
SIDE_DRAFT = "draft"
SIDE_EXTERNAL_WRITE = "external-write"

VALID_LEVELS = frozenset({SIDE_NONE, SIDE_DRAFT, SIDE_EXTERNAL_WRITE})


# ── 已知写工具的覆盖声明（未在此列的均默认 none）──
_KNOWN_WRITERS: dict[str, str] = {
    # draft_writer
    "write_draft": SIDE_DRAFT,
    # fabrication
    "fabricate_data": SIDE_DRAFT,
    # scenario_tools
    "promote_draft": SIDE_DRAFT,
    "edit_dependency": SIDE_DRAFT,
    # graph_index（写派生物索引库/快照）
    "graph_rebuild": SIDE_DRAFT,
    "graph_snapshot": SIDE_DRAFT,
    # audit
    "file_vulnerability": SIDE_DRAFT,
    # meta
    "todo_write": SIDE_DRAFT,
    # specflow_interview（写面试/问题/外部锚点表）
    "iv_open_topic": SIDE_DRAFT,
    "iv_record_answer": SIDE_DRAFT,
    "iv_append_transcript": SIDE_DRAFT,
    "iv_next_question": SIDE_DRAFT,
    "iv_p0_clear_check": SIDE_DRAFT,
    # specflow_ledger（写决策台账/评分）
    "sf_propose_decision": SIDE_DRAFT,
    "sf_check_p0_gate": SIDE_DRAFT,
    "sf_suggest_scores": SIDE_DRAFT,
    "sf_read_score_gate": SIDE_DRAFT,
    # specflow_refs（写外部锚点）
    "sf_register_external_ref": SIDE_DRAFT,
    # coverage（写草稿/计划）
    "query_coverage_gaps": SIDE_DRAFT,
    "query_coverage_backlink": SIDE_DRAFT,
    "query_next_batch": SIDE_DRAFT,
    "fabricate_data": SIDE_DRAFT,
    # specflow_pack（写信息包）
    "pack_assemble": SIDE_DRAFT,
    "add_to_info_pack": SIDE_DRAFT,
    # draft_gates（写评审/闸门状态）
    "draft_review": SIDE_DRAFT,
    "draft_promote": SIDE_DRAFT,
    # zentao 相关（写外部系统放行前暂标 draft，确认 external-write 安全后再升）
    "sf_suggest_story_draft": SIDE_DRAFT,
}

# ── 外部写集（初始化为空——「外部写不进 MCP」通则）──
_EXTERNAL_WRITERS: set[str] = set()


# ── 构建注册表 ──

def _build_registry() -> dict[str, str]:
    """扫描全部已注册工具，构造 tool_name → side_effect 映射。"""
    registry: dict[str, str] = {}
    all_tools = server.ALL_TOOLS  # 从 server 读已注册的工具清单
    for tool in all_tools:
        name = tool.name
        if name in _EXTERNAL_WRITERS:
            registry[name] = SIDE_EXTERNAL_WRITE
        elif name in _KNOWN_WRITERS:
            registry[name] = _KNOWN_WRITERS[name]
        else:
            registry[name] = SIDE_NONE
    return registry


# 单例注册表（首次构建后缓存）
_REGISTRY: Optional[dict[str, str]] = None


def get_side_effect(tool_name: str) -> str:
    """查询工具的副作用级别（默认 none）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY.get(tool_name, SIDE_NONE)


def is_pure_read(tool_name: str) -> bool:
    """是否为纯读工具（side_effect=none）。"""
    return get_side_effect(tool_name) == SIDE_NONE


def list_tools_by_side_effect(level: str) -> list[str]:
    """按副作用级别列出工具名。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return sorted(name for name, se in _REGISTRY.items() if se == level)


def invalidate_cache():
    """清空注册表缓存（工具模块热加载后调用）。"""
    global _REGISTRY
    _REGISTRY = None