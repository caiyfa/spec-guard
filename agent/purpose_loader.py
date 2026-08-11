"""agent.purpose_loader — 用途定义加载器（T-012）。

解析 agent/purposes/{purpose_id}.md 文件，提取 YAML frontmatter + Markdown 正文。
30 秒内存缓存，支持热加载（新增用途文件无需重启、不改 runtime）。
用途定义驱动：提示词装配（正文注入）、工具白名单（tools）、RBAC 可见性（roles）、
面板集（panels）——创建会话时快照，后续热更新不回流已建会话。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from agent.skill_loader import load_skill

_log = __import__("logging").getLogger("agent.purpose_loader")

PURPOSES_DIR = Path(__file__).resolve().parent / "purposes"

# 内存缓存（L6：并发首载加锁，防多用户同时冷加载重复解析/写覆盖）
_CACHE: dict[str, tuple[float, PurposeDef]] = {}
_CACHE_TTL: float = 30  # 30 秒
_LOCK = threading.Lock()


@dataclass
class PurposeDef:
    """用途定义（创建期快照源）。"""
    id: str                            # 用途 ID（文件名去掉 .md）
    title: str = ""                    # 卡片标题
    icon: str = ""                     # 卡片图标
    color: str = ""                    # 身份色 token
    chips: list[str] = field(default_factory=list)   # 卡片能力 chips
    roles: list[str] = field(default_factory=list)   # RBAC 可见性（v1.8 并集语义）
    tools: list[str] = field(default_factory=list)   # 工具白名单（MCP 工具名）
    panels: list[str] = field(default_factory=list)  # 右侧面板集
    description: str = ""              # 用途简述
    content: str = ""                  # Markdown 正文（system prompt 注入）


def load_purpose(purpose_id: str) -> Optional[PurposeDef]:
    """加载单个用途定义。"""
    if not purpose_id:
        return None

    # 缓存检查（无锁读，GIL 安全）
    now = time.time()
    cached = _CACHE.get(purpose_id)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    # 并发首载：双重检查 + 锁内解析（只解析一次）
    with _LOCK:
        cached = _CACHE.get(purpose_id)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]
        purpose_file = PURPOSES_DIR / f"{purpose_id}.md"
        if not purpose_file.is_file():
            return None
        text = purpose_file.read_text(encoding="utf-8")
        purpose_def = _parse_purpose_file(purpose_id, text)
        _CACHE[purpose_id] = (time.time(), purpose_def)
        return purpose_def


def list_purposes() -> list[PurposeDef]:
    """列出全部用途定义（扫描 agent/purposes/ 目录）。"""
    if not PURPOSES_DIR.is_dir():
        return []
    purposes = []
    for f in sorted(PURPOSES_DIR.glob("*.md")):
        purpose_id = f.stem
        purpose = load_purpose(purpose_id)
        if purpose:
            purposes.append(purpose)
    return purposes


def visible_purposes(roles: list) -> list[PurposeDef]:
    """按角色集合并集过滤（v1.8）：用户角色 ∩ 用途 roles 非空即可见。"""
    user_roles = set(r for r in (roles or []) if r)
    return [p for p in list_purposes() if user_roles & set(p.roles)]


def clear_cache():
    """清空缓存（调试用）。"""
    with _LOCK:
        _CACHE.clear()


def _parse_purpose_file(purpose_id: str, text: str) -> PurposeDef:
    """解析用途文件：YAML frontmatter + Markdown 正文。T-080 悬空引用校验。"""
    frontmatter = {}
    body = text

    # 提取 YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                frontmatter = {}
            body = parts[2].strip()

    # T-080：悬空引用校验——skills 声明在 skill_loader 中不存在则 Warning
    raw_skills = frontmatter.get("skills", []) or []
    if isinstance(raw_skills, list):
        for skill_name in raw_skills:
            sn = str(skill_name).strip() if skill_name else ""
            if sn and not load_skill(sn):
                _log.warning(
                    "purpose %r 引用了不存在的 skill %r（悬空引用）",
                    purpose_id, sn)
    elif isinstance(raw_skills, str):
        for sn in raw_skills.split(","):
            sn = sn.strip()
            if sn and not load_skill(sn):
                _log.warning(
                    "purpose %r 引用了不存在的 skill %r（悬空引用）",
                    purpose_id, sn)

    def _str_list(key: str) -> list[str]:
        raw = frontmatter.get(key, []) or []
        if isinstance(raw, list):
            return [str(k).strip() for k in raw if str(k).strip()]
        if isinstance(raw, str):
            return [k.strip() for k in raw.split(",") if k.strip()]
        return []

    return PurposeDef(
        id=str(frontmatter.get("id", purpose_id)),
        title=str(frontmatter.get("title", "")),
        icon=str(frontmatter.get("icon", "")),
        color=str(frontmatter.get("color", "")),
        chips=_str_list("chips"),
        roles=_str_list("roles"),
        tools=_str_list("tools"),
        panels=_str_list("panels"),
        description=str(frontmatter.get("description", "")),
        content=body,
    )
