"""agent.mode_loader — 模式文件加载器（G2-2）。

解析 agent/modes/{name}.md 文件，提取 YAML frontmatter + Markdown 正文。
30 秒内存缓存，支持热加载。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

MODES_DIR = Path(__file__).resolve().parent / "modes"

# 内存缓存
_CACHE: dict[str, tuple[float, ModeDef]] = {}
_CACHE_TTL: float = 30  # 30 秒


@dataclass
class ModeDef:
    """模式定义。"""
    name: str                         # 模式名称（文件名去掉 .md）
    tools: list[str] = field(default_factory=list)  # 工具白名单（空列表 = 无工具）
    prompt_fragment: str = ""         # Markdown 正文（system prompt 片段）
    description: str = ""             # 模式简述（frontmatter 可选）


def load_mode(name: str) -> Optional[ModeDef]:
    """加载单个模式定义。

    Args:
        name: 模式名称（如 "generate", "debug", "analyze", "chat"）

    Returns:
        ModeDef 或 None（文件不存在时）
    """
    if not name:
        return None

    # 缓存检查
    now = time.time()
    cached = _CACHE.get(name)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    mode_file = MODES_DIR / f"{name}.md"
    if not mode_file.is_file():
        return None

    text = mode_file.read_text(encoding="utf-8")
    mode_def = _parse_mode_file(name, text)

    _CACHE[name] = (now, mode_def)
    return mode_def


def list_modes() -> list[ModeDef]:
    """列出全部可用模式（扫描 agent/modes/ 目录）。"""
    if not MODES_DIR.is_dir():
        return []

    modes = []
    for f in sorted(MODES_DIR.glob("*.md")):
        name = f.stem
        mode = load_mode(name)
        if mode:
            modes.append(mode)
    return modes


def clear_cache():
    """清空缓存（调试用）。"""
    _CACHE.clear()


def _parse_mode_file(name: str, text: str) -> ModeDef:
    """解析模式文件：YAML frontmatter + Markdown 正文。

    格式：
        ---
        tools:
          - read_spec
          - validate
        ---
        Markdown 正文（system prompt 片段）

    向后兼容：旧文件的 temperature 字段会被安全忽略（不报错）。
    """
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

    return ModeDef(
        name=name,
        tools=list(frontmatter.get("tools", [])),
        prompt_fragment=body,
        description=str(frontmatter.get("description", "")),
    )
