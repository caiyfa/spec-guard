"""大模型配置持久化 + 热加载（G1-1）。

配置存储到 SQLite（workbench.db），支持运行时热更新。
未配置 UI 配置时回退到环境变量（SG_LLM_BASE_URL / SG_LLM_API_KEY / SG_LLM_MODEL）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from sg_core.user_store import _connect, _LOCK, init_db

# 配置键常量（基础连接 + 模型能力）
LLM_CONFIG_KEYS = (
    # 连接参数
    "base_url", "api_key", "model", "timeout", "temperature",
    # 模型能力限制
    "max_context_tokens", "max_output_tokens",
    # 思考/推理选项
    "thinking_enabled", "reasoning_effort",
)

# 内存缓存：避免每次请求都查库
_CACHE: dict[str, str] = {}
_CACHE_TS: float = 0
_CACHE_TTL: float = 30  # 30 秒缓存


def _ensure_table():
    """建表（幂等）。"""
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)


def get_all() -> dict[str, str]:
    """获取全部 LLM 配置（优先缓存 → DB → 环境变量回退）。"""
    global _CACHE, _CACHE_TS
    now = time.time()
    if _CACHE and (now - _CACHE_TS) < _CACHE_TTL:
        return dict(_CACHE)

    _ensure_table()
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT key, value FROM llm_config").fetchall()
    result = {r["key"]: r["value"] for r in rows}
    _CACHE = result
    _CACHE_TS = now
    return result


def get(key: str, default: str = "") -> str:
    """获取单个配置值。"""
    configs = get_all()
    return configs.get(key, default)


def save(configs: dict[str, str]) -> dict[str, str]:
    """批量保存配置，返回保存后的完整配置。"""
    from datetime import datetime
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
        for key, value in configs.items():
            if key in LLM_CONFIG_KEYS:
                conn.execute(
                    "INSERT OR REPLACE INTO llm_config (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, str(value), now),
                )
    # 清缓存
    global _CACHE, _CACHE_TS
    _CACHE = {}
    _CACHE_TS = 0
    return get_all()


def clear():
    """清空 UI 配置（回退到环境变量）。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM llm_config")
    global _CACHE, _CACHE_TS
    _CACHE = {}
    _CACHE_TS = 0


def resolve_config() -> dict:
    """解析最终生效的配置（DB 优先 → 环境变量回退）。

    返回 dict 含连接参数 + 模型能力限制 + 思考选项。
    """
    db_configs = get_all()
    result = {}
    # 连接参数
    result["base_url"] = db_configs.get("base_url") or os.environ.get("SG_LLM_BASE_URL", "")
    result["api_key"] = db_configs.get("api_key") or os.environ.get("SG_LLM_API_KEY", "")
    result["model"] = db_configs.get("model") or os.environ.get("SG_LLM_MODEL", "gpt-4o")
    result["timeout"] = db_configs.get("timeout") or "120"
    result["temperature"] = db_configs.get("temperature") or "0.7"
    # 模型能力限制
    result["max_context_tokens"] = db_configs.get("max_context_tokens") or ""
    result["max_output_tokens"] = db_configs.get("max_output_tokens") or ""
    # 思考/推理选项
    result["thinking_enabled"] = db_configs.get("thinking_enabled") or "false"
    result["reasoning_effort"] = db_configs.get("reasoning_effort") or ""
    return result


def is_env_controlled() -> dict[str, bool]:
    """检测各字段是否由环境变量控制（UI 显示提示用）。"""
    db_configs = get_all()
    return {
        "base_url": bool(os.environ.get("SG_LLM_BASE_URL")) and not db_configs.get("base_url"),
        "api_key": bool(os.environ.get("SG_LLM_API_KEY")) and not db_configs.get("api_key"),
        "model": bool(os.environ.get("SG_LLM_MODEL")) and not db_configs.get("model"),
    }


def probe_connectivity(base_url: str, api_key: str, model: str,
                       timeout: int = 30) -> dict:
    """探测 LLM 连通性：发一条简短消息验证。

    返回 {"ok": bool, "message": str}。
    """
    import httpx

    if not base_url:
        return {"ok": False, "message": "base_url 不能为空"}
    if not api_key:
        return {"ok": False, "message": "api_key 不能为空"}

    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "model": model or "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            model_used = data.get("model", model)
            return {"ok": True, "message": f"连通成功，模型: {model_used}"}
        else:
            return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except httpx.ConnectError as e:
        return {"ok": False, "message": f"连接失败: {e}"}
    except httpx.ReadTimeout:
        return {"ok": False, "message": f"连接超时（{timeout}s）"}
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}
