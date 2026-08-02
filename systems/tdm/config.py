"""TDM 系统环境配置加载。

配置优先级（T-309 分层）：
1. 共享通用配置 systems/_shared/config/env.{env}.yaml（跨系统复用，不存在则跳过）
2. 本系统配置 systems/tdm/config/env.{env}.yaml —— 系统键覆盖共享同键（顶层合并）
3. ${VAR:default} 占位符 → 环境变量替换（无环境变量时用 default）
4. DB 密码为空时回退读取 devops 技能凭据 ~/.qoder/skills/devops/scripts/.env.devops
"""

import os
import re

import yaml

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
_DEVOPS_ENV = os.path.expanduser(r"~\.qoder\skills\devops\scripts\.env.devops")

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


class ConfigError(Exception):
    pass


def _substitute(value):
    """递归替换 ${VAR:default} 占位符"""
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


def _read_devops_env():
    """读取 devops 技能凭据文件（key=value 行），不存在返回空 dict"""
    result = {}
    if not os.path.isfile(_DEVOPS_ENV):
        return result
    with open(_DEVOPS_ENV, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def load_env(env_name="sit"):
    """加载环境配置（共享通用层 + 本系统层合并，系统覆盖共享），完成占位符替换与凭据回退"""
    from systems._shared import load_shared_env, merge_env

    path = os.path.join(_CONFIG_DIR, f"env.{env_name}.yaml")
    if not os.path.isfile(path):
        raise ConfigError(f"环境配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        system_cfg = _substitute(yaml.safe_load(f) or {})
    # T-309：共享通用配置打底（不存在返回 {}），系统键覆盖共享同键
    cfg = merge_env(load_shared_env(env_name), system_cfg)

    # DB 密码回退（K-055 多 schema 感知）：逐连接回退——
    # env yaml 为空 → SG_DB_PASSWORD_{SCHEMA} → SG_DB_PASSWORD → devops .env.devops
    from engine.db_oracle import normalize_db_config
    db_cfg = cfg.setdefault("db", {})
    conns, _ = normalize_db_config(db_cfg)
    devops = None
    suffix = "_UAT" if env_name.lower() == "uat" else ""
    for name, conn in conns.items():
        if conn.get("password"):
            continue
        conn["password"] = (
            os.environ.get(f"SG_DB_PASSWORD_{name.upper()}", "")
            or os.environ.get("SG_DB_PASSWORD", "")
        )
        if not conn["password"]:
            if devops is None:
                devops = _read_devops_env()
            conn["password"] = devops.get(f"DB_PASSWORD{suffix}", "")
            # host/user/port 也允许从 devops 凭据补全
            if not conn.get("host"):
                conn["host"] = devops.get(f"DB_HOST{suffix}", "")
            if not conn.get("user"):
                conn["user"] = devops.get(f"DB_USER{suffix}", "")
            if not conn.get("port"):
                conn["port"] = int(devops.get(f"DB_PORT{suffix}", "3306") or "3306")
    cfg["env_name"] = env_name
    return cfg
