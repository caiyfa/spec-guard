"""live_registry — 离线构建引擎注册表（供 MCP 工具查询真实注册快照）。

D3 决策：注册表是单一事实源——query_registry / validator 必须读活注册表，
新增 oracle/step 后工具自动可见，不允许硬编码清单漂移。

构建走 engine.bootstrap 组合根（T-970 装配归一；db=None，仅注册元数据，不触网/连库）。
"""

from __future__ import annotations

import os
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent

_CACHE: dict = {}


def _resolve_system(system: str = "") -> str:
    """system 解析（容错）：specstd.resolve_system 唯一口径，导入失败回退环境变量。"""
    try:
        from specstd.workspace import resolve_system
        return resolve_system(system)
    except Exception:
        return system or os.environ.get("SPEC_GUARD_SYSTEM", "tdm")


def get_live_registry(system: str = ""):
    """构建并缓存活注册表。失败时返回 None（调用方自行降级）。

    T-970 装配归一：统一走 engine.bootstrap 组合根（db=None，仅注册元数据，
    不触网/连库；环境配置缺失时降级空 dict，注册元数据通常不依赖配置值）。
    T-971：按 system 分键缓存——多系统部署下切换 system 各自持有注册快照，
    不再进程级单键锁死；invalidate(system) 供系统包热重建（T-973 接缝）。
    """
    system = _resolve_system(system)
    if system in _CACHE:
        return _CACHE[system]
    try:
        from engine.bootstrap import build_registry, load_system_env

        env_name = os.environ.get("SG_ENV", "sit")
        try:
            env_config = load_system_env(system, env_name)
        except Exception:
            env_config = {}

        reg = build_registry(system, env_config, None)
        _CACHE[system] = reg
        return reg
    except Exception:
        _CACHE[system] = None
        return None


def invalidate_live_registry(system: str = "") -> None:
    """失效某系统（空 = 全部）的活注册表缓存——系统包重建/热加载后调用。

    T-973：单系统失效连带清掉该系统的 tool 元数据（重装配时重新注册）；
    extensions 模块缓存按 sha256 自动失效（system_package._EXT_MODULE_CACHE）。
    空参全清只清注册表缓存——tool 元数据无法枚举系统归属，留待各自重建。
    """
    from engine.tool_registry import unregister_system_tools
    if system:
        _CACHE.pop(system, None)
        unregister_system_tools(system)
    else:
        _CACHE.clear()


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


# ══════════════════════════════════════════════════════════
# env 配置只读窗口（query_registry type=env 数据源）
# 背景：agent 工具被沙箱在工作区（spec 仓库），够不到引擎仓库的
# systems/{system}/config/env.{env}.yaml——曾致模型拿旧试跑报告当
# 现状、误断言「缺 hr_tdm_base」（20260827_094125_f955645e 会话）。
# ══════════════════════════════════════════════════════════

# 值打码的键名模式（大小写不敏感的子串匹配）——凭据不进会话日志
_SENSITIVE_KEY_PAT = ("password", "secret", "token", "credential")


def mask_env_config(cfg: dict) -> dict:
    """递归脱敏 env 配置：password/secret/token 类键与 accounts.*.ad 值打码。

    agent 只需要「键是否存在 + 非敏感值」（URL/开关/别名），凭据
    （DB 密码、SSO secret、AD 域账号名）不得经工具结果落进会话 JSONL。
    """
    def _mask(node):
        if isinstance(node, dict):
            masked = {}
            for key, val in node.items():
                if isinstance(val, (dict, list)):
                    masked[key] = _mask(val)
                elif key.lower() == "ad" or any(p in key.lower() for p in _SENSITIVE_KEY_PAT):
                    masked[key] = "***"
                else:
                    masked[key] = val
            return masked
        if isinstance(node, list):
            return [_mask(x) for x in node]
        return node

    return _mask(cfg)


def load_env_view(system: str = "", env_name: str = "") -> dict | None:
    """加载当前系统 env 配置并脱敏，返回 {system, env, source, config}。

    走 engine.bootstrap.load_system_env——与运行时同源，工具看到的即引擎用的。
    加载失败/配置为空返回 None（调用方诚实报错，不伪造空清单）。
    """
    system = _resolve_system(system)
    env_name = env_name or os.environ.get("SG_ENV", "sit")
    try:
        from engine.bootstrap import load_system_env
        cfg = load_system_env(system, env_name)
    except Exception:
        return None
    if not isinstance(cfg, dict) or not cfg:
        return None
    return {
        "system": system,
        "env": env_name,
        "source": f"systems/{system}/config/env.{env_name}.yaml",
        "config": mask_env_config(cfg),
    }
