"""数据库敏感字段加密（AES-128-CBC + HMAC，Fernet 对称加密）。

用途：
    加密 DB 中的敏感字段（api_key、webhook_url、secret 等），避免明文落库。

主密钥来源（优先级）：
    1. 环境变量 SG_DB_ENCRYPTION_KEY（Fernet 兼容的 base64 key，生产推荐）
    2. 本地文件 workbench/backend/data/.encryption_key（首次启动自动生成，权限 600）

识别约定：
    密文以 "ENC:" 前缀存储，便于识别已加密数据 + 兼容存量明文（decrypt 原样返回）。

安全注意：
    - 密钥丢失 = 数据不可恢复，务必备份 SG_DB_ENCRYPTION_KEY 或 .encryption_key
    - .encryption_key 已在 .gitignore 排除，不得提交
    - Windows 无 chmod，生产部署建议改用环境变量注入密钥
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("specguard.crypto")

# 密钥文件位置（与 user_store.DATA_DIR 一致，但独立定义避免循环依赖）
BACKEND_DIR = Path(__file__).resolve().parent.parent / "workbench" / "backend"
_KEY_FILE = BACKEND_DIR / "data" / ".encryption_key"

# 密文前缀（识别已加密数据，兼容存量明文）
_PREFIX = "ENC:"

# 进程内密钥缓存（避免每次读文件）
_KEY_CACHE: bytes | None = None


def _load_key() -> bytes:
    """加载主密钥（环境变量优先，回退本地文件，首次自动生成）。"""
    global _KEY_CACHE
    if _KEY_CACHE:
        return _KEY_CACHE

    # 1. 环境变量（生产推荐，可对接 KMS/密钥管理服务）
    env_key = os.environ.get("SG_DB_ENCRYPTION_KEY", "").strip()
    if env_key:
        _KEY_CACHE = env_key.encode("ascii")
        return _KEY_CACHE

    # 2. 本地文件
    if _KEY_FILE.is_file():
        _KEY_CACHE = _KEY_FILE.read_bytes().strip()
        return _KEY_CACHE

    # 3. 首次启动：生成并写入
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_CACHE = Fernet.generate_key()
    _KEY_FILE.write_bytes(_KEY_CACHE)
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:
        pass  # Windows 无 chmod 语义，依赖文件系统 ACL
    logger.warning("已生成数据库加密密钥到 %s，建议配置 SG_DB_ENCRYPTION_KEY "
                   "环境变量以固定密钥（密钥丢失=数据不可恢复）", _KEY_FILE)
    return _KEY_CACHE


def encrypt(plaintext: str) -> str:
    """加密字符串，返回 'ENC:<base64>' 密文。幂等（已加密不二次加密）。"""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_PREFIX):
        return plaintext  # 已加密，幂等
    f = Fernet(_load_key())
    token = f.encrypt(plaintext.encode("utf-8"))
    return _PREFIX + token.decode("ascii")


def decrypt(ciphertext: str) -> str:
    """解密。无 ENC: 前缀的旧明文原样返回（向后兼容存量数据）。"""
    if not ciphertext or not ciphertext.startswith(_PREFIX):
        return ciphertext  # 明文旧数据，原样返回
    f = Fernet(_load_key())
    try:
        return f.decrypt(ciphertext[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "解密失败：密钥不匹配或密文损坏。"
            "若更换过 SG_DB_ENCRYPTION_KEY / .encryption_key，旧数据将无法解密。"
        ) from e


def mask(key: str) -> str:
    """脱敏显示（如 sk-ab***wxyz）。用于前端列表，避免完整密钥回显。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return key[:4] + "***" + key[-4:]


def is_encrypted(value: str) -> bool:
    """判断是否已加密（带 ENC: 前缀）。"""
    return bool(value) and value.startswith(_PREFIX)


def _reset_cache_for_test():
    """清空密钥缓存（仅测试用）。"""
    global _KEY_CACHE
    _KEY_CACHE = None
