"""live_registry — 离线构建引擎注册表（供 MCP 工具查询真实注册快照）。

D3 决策：注册表是单一事实源——query_registry / validator 必须读活注册表，
新增 oracle/step 后工具自动可见，不允许硬编码清单漂移。

构建走 engine.bootstrap 组合根（T-970 装配归一；db=None，仅注册元数据，不触网/连库）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

_CACHE = {}


def get_live_registry():
    """构建并缓存活注册表。失败时返回 None（调用方自行降级）。

    T-970 装配归一：统一走 engine.bootstrap 组合根（db=None，仅注册元数据，
    不触网/连库；环境配置缺失时降级空 dict，注册元数据通常不依赖配置值）。
    """
    if "registry" in _CACHE:
        return _CACHE["registry"]
    try:
        from engine.bootstrap import build_registry, load_system_env

        system = os.environ.get("SPEC_GUARD_SYSTEM", "tdm")
        env_name = os.environ.get("SG_ENV", "sit")
        try:
            env_config = load_system_env(system, env_name)
        except Exception:
            env_config = {}

        reg = build_registry(system, env_config, None)
        _CACHE["registry"] = reg
        return reg
    except Exception:
        _CACHE["registry"] = None
        return None


def list_oracles() -> list[dict]:
    """返回 [{name, desc}]——desc 取断言器函数 docstring 首行。"""
    reg = get_live_registry()
    if reg is None:
        return []
    result = []
    for name in sorted(reg.oracles):
        fn = reg.oracles[name]
        doc = (getattr(fn, "__doc__", "") or "").strip().splitlines()
        result.append({"name": name, "desc": doc[0].strip() if doc else ""})
    return result


def list_step_types() -> list[dict]:
    """返回 [{type, desc}]——引擎内置原语 + 系统适配包注册的步骤类型。"""
    reg = get_live_registry()
    if reg is None:
        return []
    result = []
    for name in sorted(reg.step_handlers):
        fn = reg.step_handlers[name]
        doc = (getattr(fn, "__doc__", "") or "").strip().splitlines()
        result.append({"type": name, "desc": doc[0].strip() if doc else ""})
    return result


def oracle_names() -> set[str]:
    """oracle 名称集合（validator 幻觉拦截用）。"""
    return {o["name"] for o in list_oracles()}
