"""Nacos 配置中心客户端（T-1036）——执行环境配置的统一管理源。

定位：本地 env.{env}.yaml 退为 bootstrap（连接信息）+ 兜底；启用 Nacos 后，
配置值从 Nacos 拉取深合并覆盖本地（Nacos 逐键胜出，支持全量接管与增量覆盖）。
消费方零感知——全部收敛到 systems/{system}.load_env 单点（T-309 分层语义之上）。

对接 Nacos OpenAPI v1（httpx，零新增依赖，同 integrations/zentao 先例）：
  拉取  GET {server}/nacos/v1/cs/configs?dataId=&group=&tenant=
  鉴权  POST {server}/nacos/v1/auth/login（仅配置了 username 时；password 走
        ${NACOS_PASSWORD:} 占位符 → resolve_secret 自有链，不硬编码）

纪律（secrets.py 同款）：纯函数 + 模块级常量；缺失/不可达诚实降级不抛——
可用性优先（配置中心抖动不应阻断测试执行），降级时 warnings WARN + 由
load_env 在 config_source 标注真实来源。缓存 TTL 300s（参照 sg_core/db_access.py：
模块级 dict + threading.Lock + invalidate_cache），配置中心变更最迟 5 分钟生效。
"""

from __future__ import annotations

import threading
import time
import warnings

import httpx
import yaml

_CACHE_TTL = 300.0
_TIMEOUT = 5.0
_cache: dict = {"key": None, "ts": 0.0, "data": None}
_LOCK = threading.Lock()


class NacosError(Exception):
    """Nacos 拉取失败（连接/超时/非 200/内容非合法 YAML）。message 面向排障。"""


def invalidate_cache():
    """清空拉取缓存（配置中心侧变更后想立即生效时用；测试隔离用）。"""
    with _LOCK:
        _cache.update(key=None, ts=0.0, data=None)


def deep_merge(base: dict, override: dict) -> dict:
    """递归深合并：override 逐键胜出，dict 递归、其余类型整体替换。纯函数不改入参。"""
    out = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _fetch_via_http(nacos_cfg: dict) -> dict:
    """单次拉取（无缓存）。连接/超时/非 200/内容非法 → NacosError。"""
    server = str(nacos_cfg.get("server_addr") or "").rstrip("/")
    data_id = str(nacos_cfg.get("data_id") or "")
    group = str(nacos_cfg.get("group") or "DEFAULT_GROUP")
    namespace = str(nacos_cfg.get("namespace") or "")
    if not server or not data_id:
        raise NacosError("nacos 配置块缺少 server_addr 或 data_id")

    params = {"dataId": data_id, "group": group}
    if namespace:
        params["tenant"] = namespace

    # 可选鉴权：配置了 username 才走登录换 accessToken（password 经 resolve_secret 链）
    username = str(nacos_cfg.get("username") or "")
    if username:
        password = str(nacos_cfg.get("password") or "")
        if not password:
            from systems._shared.secrets import resolve_secret
            password = resolve_secret("NACOS_PASSWORD")
        try:
            r = httpx.post(f"{server}/nacos/v1/auth/login",
                           data={"username": username, "password": password},
                           timeout=_TIMEOUT)
            r.raise_for_status()
            params["accessToken"] = r.json().get("accessToken", "")
        except (httpx.HTTPError, ValueError) as e:
            raise NacosError(f"nacos 鉴权失败: {e}") from e

    try:
        r = httpx.get(f"{server}/nacos/v1/cs/configs", params=params, timeout=_TIMEOUT)
        if r.status_code == 404:
            raise NacosError(f"nacos 配置不存在: dataId={data_id} group={group}")
        r.raise_for_status()
        content = r.text
    except httpx.HTTPError as e:
        raise NacosError(f"nacos 拉取失败: {e}") from e

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise NacosError(f"nacos 配置内容不是合法 YAML: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise NacosError(f"nacos 配置内容应为 YAML 映射，实为 {type(data).__name__}")
    return data


def fetch_config(nacos_cfg: dict) -> dict | None:
    """拉取 Nacos 配置（TTL 缓存）。

    返回 dict（命中/缓存）；返回 None 表示未启用或不可达（调用方诚实降级本地
    文件，降级原因已 warnings WARN）。nacos_cfg 为 env yaml 的 nacos 块。
    """
    if not (nacos_cfg or {}).get("enabled"):
        return None
    key = "\x1f".join(str(nacos_cfg.get(k) or "") for k in
                      ("server_addr", "namespace", "group", "data_id", "username"))
    now = time.time()
    with _LOCK:
        if _cache["data"] is not None and _cache["key"] == key and now - _cache["ts"] < _CACHE_TTL:
            return _cache["data"]
    try:
        data = _fetch_via_http(nacos_cfg)
    except NacosError as e:
        warnings.warn(f"[SpecGuard] Nacos 配置拉取降级本地文件：{e}", stacklevel=2)
        return None
    with _LOCK:
        _cache.update(key=key, ts=now, data=data)
    return data
