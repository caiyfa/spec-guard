"""通知配置 CRUD 测试（J-1 验收）。

覆盖验收标准：
1. 配置增删改查
2. 按事件订阅字段
3. webhook_url/secret 加密存储（DB 中 ENC: 前缀）
4. 列表脱敏、获取解密
5. 渠道/事件校验
6. get_configs_by_event 事件过滤

全部离线：固定测试密钥 + tmp_path 隔离 DB。
"""

import os
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

from services import crypto, notify_config, user_store  # noqa: E402


@pytest.fixture(autouse=True)
def fixed_key(monkeypatch):
    """固定测试密钥。"""
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
# 验收 1: 配置增删改查
# ══════════════════════════════════════════════════════════

class TestCRUD:
    """通知配置 CRUD 全流程。"""

    def test_create_config(self, db):
        """创建配置 → 返回完整配置（webhook_url 解密）。"""
        config = notify_config.create_config({
            "name": "TDM 研发群",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            "secret": "",
            "events": ["vulnerability"],
            "enabled": True,
        }, created_by="test_user")
        assert config["id"].startswith("notify-")
        assert config["name"] == "TDM 研发群"
        assert config["channel"] == "feishu"
        assert config["webhook_url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
        assert config["events"] == ["vulnerability"]
        assert config["enabled"] is True
        assert config["created_by"] == "test_user"

    def test_list_configs_masked(self, db):
        """列表 → webhook_url 脱敏。"""
        notify_config.create_config({
            "name": "测试群",
            "channel": "dingtalk",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=abcdef123456",
            "secret": "SEC123456",
            "events": ["plan_failure"],
        })
        configs = notify_config.list_configs()
        assert len(configs) == 1
        # webhook_url 应被 mask
        assert "abcdef123456" not in configs[0]["webhook_url"]
        assert "***" in configs[0]["webhook_url"]
        # secret 应被 mask
        assert "SEC123456" not in configs[0]["secret"]
        assert "***" in configs[0]["secret"]

    def test_get_config_decrypted(self, db):
        """获取单个 → webhook_url/secret 解密。"""
        created = notify_config.create_config({
            "name": "获取测试",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/secret123",
            "secret": "my_secret",
            "events": ["vulnerability", "plan_failure"],
        })
        config = notify_config.get_config(created["id"])
        assert config is not None
        assert config["webhook_url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/secret123"
        assert config["secret"] == "my_secret"

    def test_get_nonexistent(self, db):
        """获取不存在的配置 → None。"""
        assert notify_config.get_config("notify-nope") is None

    def test_update_config(self, db):
        """更新配置 → 字段更新 + webhook_url 重新加密。"""
        created = notify_config.create_config({
            "name": "原名称",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/old",
            "events": ["vulnerability"],
        })
        updated = notify_config.update_config(created["id"], {
            "name": "新名称",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/new",
            "enabled": False,
        })
        assert updated is not None
        assert updated["name"] == "新名称"
        assert updated["webhook_url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/new"
        assert updated["enabled"] is False

    def test_update_nonexistent(self, db):
        """更新不存在的配置 → None。"""
        assert notify_config.update_config("notify-nope", {"name": "x"}) is None

    def test_delete_config(self, db):
        """删除配置。"""
        created = notify_config.create_config({
            "name": "待删除",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/x",
            "events": ["vulnerability"],
        })
        assert notify_config.delete_config(created["id"]) is True
        assert notify_config.get_config(created["id"]) is None

    def test_delete_nonexistent(self, db):
        """删除不存在的配置 → False。"""
        assert notify_config.delete_config("notify-nope") is False


# ══════════════════════════════════════════════════════════
# 验收 2: 按事件订阅
# ══════════════════════════════════════════════════════════

class TestEventSubscription:
    """按事件订阅字段。"""

    def test_get_configs_by_event(self, db):
        """get_configs_by_event 只返回订阅了该事件且已启用的配置。"""
        notify_config.create_config({
            "name": "漏洞群",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/a",
            "events": ["vulnerability"],
        })
        notify_config.create_config({
            "name": "失败群",
            "channel": "dingtalk",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=b",
            "events": ["plan_failure"],
        })
        notify_config.create_config({
            "name": "全能群",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/c",
            "events": ["vulnerability", "plan_failure", "plan_success"],
        })

        vuln_configs = notify_config.get_configs_by_event("vulnerability")
        assert len(vuln_configs) == 2  # 漏洞群 + 全能群
        names = [c["name"] for c in vuln_configs]
        assert "漏洞群" in names
        assert "全能群" in names

        failure_configs = notify_config.get_configs_by_event("plan_failure")
        assert len(failure_configs) == 2  # 失败群 + 全能群

        success_configs = notify_config.get_configs_by_event("plan_success")
        assert len(success_configs) == 1  # 只有全能群

    def test_disabled_not_returned(self, db):
        """已禁用的配置不被 get_configs_by_event 返回。"""
        notify_config.create_config({
            "name": "禁用群",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/d",
            "events": ["vulnerability"],
            "enabled": False,
        })
        configs = notify_config.get_configs_by_event("vulnerability")
        assert len(configs) == 0

    def test_configs_decrypted_in_event_query(self, db):
        """get_configs_by_event 返回的 webhook_url/secret 是解密的。"""
        notify_config.create_config({
            "name": "解密验证",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/decrypt_me",
            "secret": "secret_value",
            "events": ["vulnerability"],
        })
        configs = notify_config.get_configs_by_event("vulnerability")
        assert configs[0]["webhook_url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/decrypt_me"
        assert configs[0]["secret"] == "secret_value"


# ══════════════════════════════════════════════════════════
# 验收 3: 加密存储
# ══════════════════════════════════════════════════════════

class TestEncryption:
    """webhook_url/secret 加密存储。"""

    def test_webhook_url_encrypted_in_db(self, db):
        """DB 中 webhook_url 带 ENC: 前缀。"""
        notify_config.create_config({
            "name": "加密测试",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/plaintext_url",
            "events": ["vulnerability"],
        })
        # 直接查 DB 验证加密
        from services.user_store import _connect, _LOCK
        with _LOCK, _connect() as conn:
            row = conn.execute(
                "SELECT webhook_url FROM notify_configs LIMIT 1"
            ).fetchone()
        assert row["webhook_url"].startswith("ENC:")
        assert "plaintext_url" not in row["webhook_url"]

    def test_secret_encrypted_in_db(self, db):
        """DB 中 secret 带 ENC: 前缀。"""
        notify_config.create_config({
            "name": "密钥加密测试",
            "channel": "dingtalk",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=x",
            "secret": "my_dingtalk_secret",
            "events": ["vulnerability"],
        })
        from services.user_store import _connect, _LOCK
        with _LOCK, _connect() as conn:
            row = conn.execute(
                "SELECT secret FROM notify_configs LIMIT 1"
            ).fetchone()
        assert row["secret"].startswith("ENC:")
        assert "my_dingtalk_secret" not in row["secret"]

    def test_empty_secret_not_encrypted(self, db):
        """空 secret 不加密（存空字符串）。"""
        notify_config.create_config({
            "name": "空密钥",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/x",
            "secret": "",
            "events": ["vulnerability"],
        })
        from services.user_store import _connect, _LOCK
        with _LOCK, _connect() as conn:
            row = conn.execute(
                "SELECT secret FROM notify_configs LIMIT 1"
            ).fetchone()
        assert row["secret"] == ""


# ══════════════════════════════════════════════════════════
# 验收 4: 渠道/事件校验
# ══════════════════════════════════════════════════════════

class TestValidation:
    """渠道和事件校验。"""

    def test_invalid_channel(self, db):
        """不支持的渠道 → ValueError。"""
        with pytest.raises(ValueError, match="不支持的渠道"):
            notify_config.create_config({
                "name": "坏渠道",
                "channel": "slack",
                "webhook_url": "https://slack.com/x",
                "events": ["vulnerability"],
            })

    def test_invalid_event(self, db):
        """不支持的事件 → ValueError。"""
        with pytest.raises(ValueError, match="不支持的事件"):
            notify_config.create_config({
                "name": "坏事件",
                "channel": "feishu",
                "webhook_url": "https://open.feishu.cn/x",
                "events": ["unknown_event"],
            })

    def test_default_events(self, db):
        """不指定 events 时使用默认值。"""
        config = notify_config.create_config({
            "name": "默认事件",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/x",
        })
        assert "plan_failure" in config["events"]
        assert "vulnerability" in config["events"]

    def test_events_as_comma_string(self, db):
        """events 也可以传逗号分隔字符串。"""
        config = notify_config.create_config({
            "name": "字符串事件",
            "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/x",
            "events": "vulnerability, plan_success",
        })
        assert config["events"] == ["vulnerability", "plan_success"]
