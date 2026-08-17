"""被测系统适配包目录（systems/{system}/）枚举与校验——工作区注册与环境配置共用。

一个「系统标识」= systems/ 下一个适配包子目录（如 tdm），内含 config/env.{env}.yaml
（网关/账号池/DB）、steps.py（tool）、oracles.py（断言器）。它同时是 Python 模块名——
引擎按 importlib.import_module(f"systems.{system}") 装配运行时，故注册/读写前必须校验。
"""
import re
from pathlib import Path

import yaml
from fastapi import HTTPException

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SYSTEMS_ROOT = SG_ROOT / "systems"

SYSTEM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def list_systems(systems_root: Path | None = None) -> list[dict]:
    """枚举可用被测系统适配包：name + envs（config/env.*.yaml）+ 默认环境账号别名。

    过滤 _shared 共享层与 __pycache__ 等非适配包目录。
    """
    root = systems_root or SYSTEMS_ROOT
    systems = []
    if not root.is_dir():
        return systems
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name == "__pycache__":
            continue
        cfg_dir = d / "config"
        envs = sorted(f.name[len("env."):-len(".yaml")]
                      for f in cfg_dir.glob("env.*.yaml")) if cfg_dir.is_dir() else []
        accounts = []
        if envs:
            try:
                raw = yaml.safe_load((cfg_dir / f"env.{envs[0]}.yaml").read_text(encoding="utf-8")) or {}
                accounts = sorted((raw.get("accounts") or {}).keys())
            except Exception:
                pass
        systems.append({"name": d.name, "envs": envs,
                        "default_env": envs[0] if envs else "", "accounts": accounts})
    return systems


def validate_system(system: str) -> None:
    """系统标识硬校验：合法 Python 模块名 + 适配包存在（注册期防线，防运行期 ModuleNotFoundError）。"""
    if not SYSTEM_NAME_RE.match(system):
        raise HTTPException(status_code=400,
                            detail=f"系统标识非法: {system}（须为字母/数字/下划线组成的 Python 模块名）")
    if not (SYSTEMS_ROOT / system).is_dir():
        raise HTTPException(status_code=400,
                            detail=f"系统适配包不存在: systems/{system}/（可用 GET /api/workspace/systems 查看可选值）")
