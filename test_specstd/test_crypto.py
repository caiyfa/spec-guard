"""数据库敏感字段加密测试（A-3）。

覆盖：crypto 加解密往返 / 幂等 / 旧明文兼容 / 脱敏 / 密钥错误 / model_config 集成。
全部离线：固定测试密钥（SG_DB_ENCRYPTION_KEY）+ tmp_path 隔离 DB，不触真实 data 目录。
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import crypto  # noqa: E402
from services import model_config, user_store  # noqa: E402


@pytest.fixture(autouse=True)
def fixed_key(monkeypatch):
    """固定测试密钥，避免触碰真实 data/.encryption_key。"""
    monkeypatch.setenv("SG_DB_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    crypto._reset_cache_for_test()
    yield
    crypto._reset_cache_for_test()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离的 SQLite 数据文件。"""
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    return db_file


# ══════════════════════════════════════════════════════════
# crypto 单元测试
# ══════════════════════════════════════════════════════════

def test_encrypt_decrypt_roundtrip():
    assert crypto.decrypt(crypto.encrypt("sk-test123")) == "sk-test123"
    assert crypto.decrypt(crypto.encrypt("中文密钥")) == "中文密钥"


def test_encrypt_has_prefix():
    assert crypto.encrypt("sk-x").startswith("ENC:")


def test_encrypt_idempotent():
    enc = crypto.encrypt("sk-test")
    assert crypto.encrypt(enc) == enc  # 已加密不二次加密


def test_decrypt_legacy_plaintext():
    """存量明文（无 ENC: 前缀）原样返回，向后兼容。"""
    assert crypto.decrypt("sk-legacy") == "sk-legacy"


def test_empty_safe():
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""
    assert crypto.mask("") == ""


def test_mask():
    assert crypto.mask("sk-abcdefghij") == "sk-a***ghij"
    assert crypto.mask("short") == "***"


def test_is_encrypted():
    assert crypto.is_encrypted(crypto.encrypt("x")) is True
    assert crypto.is_encrypted("plain") is False
    assert crypto.is_encrypted("") is False


def test_decrypt_wrong_key_raises(monkeypatch):
    """换密钥后解密失败，报明确错误（不静默返回乱码）。"""
    enc = crypto.encrypt("secret")
    monkeypatch.setenv("SG_DB_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    crypto._reset_cache_for_test()
    with pytest.raises(ValueError, match="解密失败"):
        crypto.decrypt(enc)


# ══════════════════════════════════════════════════════════
# model_config 集成测试
# ══════════════════════════════════════════════════════════

def test_model_config_encrypts_on_create(db):
    """create_model 后 DB 中 api_key 为密文。"""
    model_config.create_model({"name": "t", "api_key": "sk-secret-123", "model": "gpt-4o"})
    conn = sqlite3.connect(str(db))
    raw = conn.execute("SELECT api_key FROM model_configs LIMIT 1").fetchone()[0]
    conn.close()
    assert raw.startswith("ENC:")
    assert "sk-secret-123" not in raw  # 明文不出现


def test_model_config_get_decrypts(db):
    """get_model / get_default_model 返回解密后的完整 key（LLMClient 用）。"""
    created = model_config.create_model(
        {"name": "t", "api_key": "sk-real-key-999", "model": "gpt-4o"})
    m = model_config.get_model(created["id"])
    assert m["api_key"] == "sk-real-key-999"
    d = model_config.get_default_model()
    assert d["api_key"] == "sk-real-key-999"


def test_model_config_list_masks(db):
    """list_models 返回脱敏 key（前端列表用）。"""
    model_config.create_model({"name": "t", "api_key": "sk-secret-123", "model": "gpt-4o"})
    listed = model_config.list_models()
    assert listed[0]["api_key"] == "sk-s***-123"


def test_model_config_update_encrypts(db):
    """update_model 改 api_key 时也加密。"""
    created = model_config.create_model({"name": "t", "api_key": "sk-old", "model": "gpt-4o"})
    model_config.update_model(created["id"], {"api_key": "sk-new-456"})
    conn = sqlite3.connect(str(db))
    raw = conn.execute("SELECT api_key FROM model_configs WHERE id = ?",
                       (created["id"],)).fetchone()[0]
    conn.close()
    assert raw.startswith("ENC:")
    assert model_config.get_model(created["id"])["api_key"] == "sk-new-456"


def test_migrate_plaintext_keys(db, monkeypatch):
    """迁移脚本把存量明文 key 加密，且幂等。"""
    # 手动插入明文 key（模拟存量数据）
    from services.user_store import _connect, _LOCK
    model_config._ensure_table()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO model_configs (id, name, base_url, api_key, model, timeout,"
            " temperature, max_context_tokens, max_output_tokens, thinking_enabled,"
            " reasoning_effort, is_default, created_at, updated_at)"
            " VALUES ('model-legacy', 'legacy', '', 'sk-plain-legacy', 'gpt-4o',"
            " '120', '0.7', '', '', 'false', '', 1, '2026-01-01', '2026-01-01')")

    # 执行迁移
    scripts_dir = BACKEND_DIR / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import migrate_encrypt_apikeys as mig
    m1, s1 = mig.migrate()
    assert m1 == 1  # 1 条明文被加密
    # 幂等：再跑一次不再迁移
    m2, s2 = mig.migrate()
    assert m2 == 0
    # 迁移后可正常解密
    assert model_config.get_model("model-legacy")["api_key"] == "sk-plain-legacy"
