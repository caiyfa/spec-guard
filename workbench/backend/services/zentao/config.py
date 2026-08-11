"""workbench/services/zentao/config.py — 禅道凭据与实例配置（M06 §4.2，T-053）。

凭据优先级（M06：token 加密落盘，亦可用环境变量覆盖）：
    环境变量 SG_ZENTAO_TOKEN > settings_store zentao_token
    base_url: SG_ZENTAO_BASE_URL > settings_store zentao_base_url > 默认
    product:  settings_store zentao_product（别名/ID）> 默认 tdm

token 只在内存中传递（进程内调用 integrations.zentao.api），
永不落日志、不进 argv。
"""

from __future__ import annotations

import os

from integrations.zentao.api import ZenTaoClient, DEFAULT_BASE_URL

KEY_TOKEN = "zentao_token"
KEY_BASE_URL = "zentao_base_url"
KEY_PRODUCT = "zentao_product"


def get_zentao_config() -> dict:
    """解析禅道配置（不落日志）。"""
    from workbench.backend.services import settings_store
    token = (os.environ.get("SG_ZENTAO_TOKEN", "").strip()
             or settings_store.get_setting(KEY_TOKEN))
    base_url = (os.environ.get("SG_ZENTAO_BASE_URL", "").strip()
                or settings_store.get_setting(KEY_BASE_URL)
                or DEFAULT_BASE_URL)
    product = (settings_store.get_setting(KEY_PRODUCT) or "tdm").strip()
    return {
        "token": token,
        "base_url": base_url,
        "product": product,
    }


def zentao_client_from_config() -> ZenTaoClient:
    """按配置构造禅道客户端（token 仅存内存）。"""
    cfg = get_zentao_config()
    return ZenTaoClient(base_url=cfg["base_url"], token=cfg["token"])


def has_zentao_credentials() -> bool:
    """凭据是否已配置（无凭据时写通道应拒绝，不静默）。"""
    return bool(get_zentao_config()["token"])
