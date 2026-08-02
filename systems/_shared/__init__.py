"""systems/_shared — 跨被测系统共享配置层（T-309）。

通用配置（跨系统复用）放 `systems/_shared/config/env.{env}.yaml`，
系统专属配置仍放 `systems/{system}/config/env.{env}.yaml`。
引擎加载时「共享打底 + 系统覆盖」（顶层键合并，段级覆盖）。
"""

import os
import re

import yaml

_SHARED_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


class SharedConfigError(Exception):
    pass


def _substitute(value):
    """递归替换 ${VAR:default} 占位符（与系统 config.py 同口径）。"""
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    if isinstance(value, str):
        def _rep(m):
            var, default = m.group(1), m.group(2)
            env_val = os.environ.get(var)
            if env_val is not None and env_val != "":
                return env_val
            return default if default is not None else ""
        return _PLACEHOLDER.sub(_rep, value)
    return value


def load_shared_env(env_name: str = "sit") -> dict:
    """加载共享通用配置（systems/_shared/config/env.{env}.yaml）。

    文件不存在返回空 dict（纯系统配置的部署不受影响）；占位符替换与系统层同口径。
    """
    path = os.path.join(_SHARED_CONFIG_DIR, f"env.{env_name}.yaml")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return _substitute(yaml.safe_load(f) or {})


def merge_env(shared: dict, system: dict) -> dict:
    """合并共享 + 系统配置：系统覆盖共享（顶层键合并，段级整体覆盖）。"""
    merged = dict(shared or {})
    merged.update(system or {})
    return merged
