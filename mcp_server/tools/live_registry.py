"""live_registry — 离线构建引擎注册表（供 MCP 工具查询真实注册快照）。

D3 决策：注册表是单一事实源——query_registry / validator 必须读活注册表，
新增 oracle/step 后工具自动可见，不允许硬编码清单漂移。

构建方式与 conftest.py 一致（db=None，仅注册元数据，不触网/连库）。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

_CACHE = {}


def get_live_registry():
    """构建并缓存活注册表。失败时返回 None（调用方自行降级）。"""
    if "registry" in _CACHE:
        return _CACHE["registry"]
    try:
        from engine.registry import Registry
        from engine.scenario_runner import register_builtin_steps
        from engine.schema_match import register_builtin_oracles

        system = os.environ.get("SPEC_GUARD_SYSTEM", "tdm")
        mod = importlib.import_module(f"systems.{system}")

        env_config = {}
        try:
            env_name = os.environ.get("SG_ENV", "sit")
            if hasattr(mod, "load_env"):
                env_config = mod.load_env(env_name)
            else:
                cfg_mod = importlib.import_module(f"systems.{system}.config")
                env_config = cfg_mod.load_env(env_name)
        except Exception:
            env_config = {}  # 环境配置缺失时降级（注册元数据通常不依赖配置值）

        reg = Registry()
        register_builtin_steps(reg)
        register_builtin_oracles(reg)
        if hasattr(mod, "register"):
            mod.register(reg, env_config, None)  # db=None：只注册元数据
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
