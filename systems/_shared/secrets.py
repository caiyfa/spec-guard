"""SpecGuard 自有凭据解析（T-960b 凭据自有化：移除对第三方 devops 技能目录的耦合）。

凭据键解析顺序（前一级取到非空即返回）：
1. 环境变量
2. 自有凭据文件：``SG_SECRETS_FILE`` 显式指定路径，缺省 ``~/.specguard/secrets.env``
3. （过渡期兼容，计划下线）Qoder devops 技能 ``~/.qoder/skills/devops/scripts/.env.devops``
   —— 命中即发一次 DeprecationWarning，提示迁入自有文件

两类文件均为行式 ``KEY=VALUE`` 格式，``#`` 注释行跳过；值不做引号剥离
（与 env yaml 占位符替换同口径，凭据按字面量使用）。每次调用实时读取，
改动即时生效、无需重启任何进程。
"""

import os
import warnings

_DEVOPS_ENV = os.path.join(
    os.path.expanduser("~"), ".qoder", "skills", "devops", "scripts", ".env.devops")

# 同键 devops 兜底提示只发一次的进程级去重表
_WARNED_KEYS = set()


def secrets_path():
    """自有凭据文件路径：环境变量 SG_SECRETS_FILE 覆盖，缺省 ~/.specguard/secrets.env"""
    override = os.environ.get("SG_SECRETS_FILE")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".specguard", "secrets.env")


def _read_kv(path):
    """行式 KEY=VALUE 文件解析；文件不存在返回 {}（某层缺文件是兜底链路的正常形态）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return {}
    result = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def resolve_secret(key):
    """统一凭据解析入口：环境变量 → 自有 secrets 文件 →（过渡期）devops 兜底。

    缺省返回空串——缺失是否报错由调用方语义决定（如 token_provider 的诚实 TokenError）。
    """
    val = os.environ.get(key, "")
    if val:
        return val
    val = _read_kv(secrets_path()).get(key, "")
    if val:
        return val
    val = _read_kv(_DEVOPS_ENV).get(key, "")
    if val and key not in _WARNED_KEYS:
        _WARNED_KEYS.add(key)
        warnings.warn(
            f"凭据 {key} 仍从旧位置 {os.path.basename(_DEVOPS_ENV)} 读取"
            f"（T-960b 过渡期兜底）。请把该键迁入 SpecGuard 自有凭据文件 "
            f"{secrets_path()}，devops 通道将在后续版本下线",
            DeprecationWarning,
            stacklevel=2)
    return val
