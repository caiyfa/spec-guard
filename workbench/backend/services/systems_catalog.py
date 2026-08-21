"""被测系统适配包目录（systems/{system}/）枚举与校验——工作区注册与环境配置共用。

一个「系统标识」= 系统包目录（如 tdm）。T-973 起系统包带 manifest.yaml
（tier/layout/enabled），支持 SG_SYSTEMS_ROOT 动态根（仓库外）：

  {SG_SYSTEMS_ROOT}/{system}/ = manifest.yaml + config/env.{env}.yaml
                              + assertions.yaml（模板断言，可选）
                              + extensions.py（代码型，评审闸后加载，可选）

仓内 legacy 包（无 manifest）按 code/package 呈现（现状不变）。
"""
import re
from pathlib import Path

import yaml
from fastapi import HTTPException

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SYSTEMS_ROOT = SG_ROOT / "systems"

SYSTEM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# manifest.tier → 展示语义（分级接入，08-21 用户拍板）
TIER_LABELS = {
    "config": "配置型（纯配置，注册/编辑即时生效）",
    "template": "模板断言型（+声明式断言，SELECT-only 守卫）",
    "code": "代码型（+extensions.py，admin 评审后热加载）",
}


def _systems_roots() -> list[Path]:
    """系统包查找根序列：动态根（SG_SYSTEMS_ROOT）优先，仓内 systems/ 兜底。"""
    import os
    roots = []
    dyn = os.environ.get("SG_SYSTEMS_ROOT", "").strip()
    if dyn:
        p = Path(dyn)
        if p.is_dir() and p not in roots:
            roots.append(p)
    if SYSTEMS_ROOT.is_dir():
        roots.append(SYSTEMS_ROOT)
    return roots


def _read_manifest(pkg_dir: Path) -> dict:
    """读包内 manifest.yaml（无/坏文件按 legacy 呈现，不炸目录枚举）。"""
    from engine import system_package
    try:
        m = system_package.load_manifest(pkg_dir.name)
        if not m:
            return {}
        return m
    except Exception:
        return {}


def list_systems() -> list[dict]:
    """枚举可用被测系统包：name/envs/tier/enabled/review 状态 + 默认环境账号别名。

    过滤 _shared 共享层与 __pycache__ 等非包目录；动态根与仓内根同名时
    动态根优先（同名只呈现一次）。
    """
    from engine.system_package import extension_gate_status
    seen: dict = {}
    for root in _systems_roots():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("_") or d.name == "__pycache__":
                continue
            if d.name in seen:
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
            manifest = _read_manifest(d)
            gate = extension_gate_status(d.name)
            seen[d.name] = {
                "name": d.name,
                "display_name": manifest.get("display_name", d.name),
                "tier": manifest.get("tier", "code"),
                "tier_label": TIER_LABELS.get(manifest.get("tier", "code"), ""),
                "enabled": bool(manifest.get("enabled", True)),
                "description": manifest.get("description", ""),
                "dynamic": manifest.get("layout") == "extensions",
                "envs": envs,
                "default_env": envs[0] if envs else "",
                "accounts": accounts,
                "extensions_review": gate,
            }
    return list(seen.values())


def get_system_detail(system: str) -> dict | None:
    """单系统详情（manifest + envs + 评审闸状态 + 目录位置）。"""
    if not SYSTEM_NAME_RE.match(system or ""):
        return None
    for entry in list_systems():
        if entry["name"] == system:
            from engine.system_package import package_dir
            entry = dict(entry)
            entry["package_dir"] = str(package_dir(system))
            return entry
    return None


def validate_system(system: str) -> None:
    """系统标识硬校验：合法 Python 模块名 + 系统包存在（注册期防线，防运行期 ModuleNotFoundError）。"""
    if not SYSTEM_NAME_RE.match(system):
        raise HTTPException(status_code=400,
                            detail=f"系统标识非法: {system}（须为字母/数字/下划线组成的 Python 模块名）")
    from engine.system_package import package_dir
    if not package_dir(system).is_dir():
        raise HTTPException(status_code=400,
                            detail=f"系统适配包不存在: systems/{system}/（可用 GET /api/systems 查看可选值）")
