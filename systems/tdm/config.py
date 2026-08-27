"""TDM 系统环境配置加载。

配置优先级（T-309 分层）：
1. 共享通用配置 systems/_shared/config/env.{env}.yaml（跨系统复用，不存在则跳过）
2. 本系统配置 systems/tdm/config/env.{env}.yaml —— 系统键覆盖共享同键（顶层合并）
3. ${VAR:default} 占位符 → 环境变量替换（无环境变量时用 default）
4. 凭据回退走 SpecGuard 自有链（T-960b）：resolve_secret 统一解析——
   环境变量 → 自有文件 ~/.specguard/secrets.env（SG_SECRETS_FILE 可重定向）
   → 旧 devops .env.devops 过渡兜底（命中发 DeprecationWarning，计划下线）
"""

import os
import re

import yaml

from systems._shared.secrets import resolve_secret

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")

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

    # T-960/T-960b 凭据出库：internal_token.client_secret 回退——
    # env yaml ${SG_TDM_CLIENT_SECRET:} 为空 → resolve_secret 自有链
    it_cfg = cfg.get("internal_token")
    if isinstance(it_cfg, dict) and not it_cfg.get("client_secret"):
        it_cfg["client_secret"] = resolve_secret("SG_TDM_CLIENT_SECRET")

    # DB 密码回退（K-055 多 schema 感知）：逐连接回退——
    # env yaml 为空 → SG_DB_PASSWORD_{SCHEMA} → SG_DB_PASSWORD → resolve_secret 自有链
    from engine.db_oracle import normalize_db_config
    db_cfg = cfg.setdefault("db", {})
    conns, _ = normalize_db_config(db_cfg)
    suffix = "_UAT" if env_name.lower() == "uat" else ""
    for name, conn in conns.items():
        if conn.get("password"):
            continue
        conn["password"] = (
            os.environ.get(f"SG_DB_PASSWORD_{name.upper()}", "")
            or os.environ.get("SG_DB_PASSWORD", "")
        )
        if not conn["password"]:
            conn["password"] = resolve_secret(f"DB_PASSWORD{suffix}")
            # host/user/port 也允许从凭据链补全（resolve_secret 内部环境变量优先）
            if not conn.get("host"):
                conn["host"] = resolve_secret(f"DB_HOST{suffix}")
            if not conn.get("user"):
                conn["user"] = resolve_secret(f"DB_USER{suffix}")
            if not conn.get("port"):
                conn["port"] = int(resolve_secret(f"DB_PORT{suffix}") or "3306")
    cfg["env_name"] = env_name
    return cfg
