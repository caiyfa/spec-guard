"""引擎离线单测：SpecGuard 自有凭据解析（T-960b 凭据自有化）——不依赖网络/真实凭据。

锁定契约：
- 解析顺序：环境变量 → 自有凭据文件（SG_SECRETS_FILE 重定向，缺省 ~/.specguard/secrets.env）
            → （过渡期兼容）devops .env.devops
- devops 命中时发一次 DeprecationWarning 提示迁移（同键进程级只提示一次）
- 三层全空返回空串（缺凭据诚实为空，由上层报错）
- systems.tdm.config.load_env 的 internal_token 回退接入 resolve_secret
"""

import os
import sys
import warnings

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

import pytest  # noqa: E402

from systems._shared import secrets as local_secrets  # noqa: E402
from systems._shared.secrets import resolve_secret, secrets_path  # noqa: E402

PRIVATE_KEY = "SG_UNITTEST_ONLY_KEY"
SENTINEL_FILE = "from-own-file"
SENTINEL_DEVOPS = "sg-unittest-devops-marker-0716"


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """三层隔离：同名环境变量清空、自有文件指到临时路径、告警去重表复位。"""
    monkeypatch.delenv(PRIVATE_KEY, raising=False)
    own_file = tmp_path / "secrets.env"
    monkeypatch.setenv("SG_SECRETS_FILE", str(own_file))
    monkeypatch.setattr(local_secrets, "_WARNED_KEYS", set())
    return own_file


def _write_devops_stub(tmp_path, monkeypatch, content=SENTINEL_DEVOPS):
    """把 devops 路径指向临时文件，防止读开发机真实凭据。"""
    stub = tmp_path / "fake-env.devops"
    if content is not None:
        stub.write_text(f"{PRIVATE_KEY}={content}\n", encoding="utf-8")
    monkeypatch.setattr(local_secrets, "_DEVOPS_ENV", str(stub))
    return stub


def test_secrets_path_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("SG_SECRETS_FILE", raising=False)
    expected_default = os.path.join(os.path.expanduser("~"), ".specguard", "secrets.env")
    assert secrets_path() == expected_default
    override = str(tmp_path / "custom.env")
    monkeypatch.setenv("SG_SECRETS_FILE", override)
    assert secrets_path() == override


def test_own_file_hit(isolated):
    isolated.parent.mkdir(parents=True, exist_ok=True)
    isolated.write_text(f"# 注释行\n{PRIVATE_KEY}={SENTINEL_FILE}\n", encoding="utf-8")
    assert resolve_secret(PRIVATE_KEY) == SENTINEL_FILE


def test_env_var_wins_over_own_file(isolated, monkeypatch):
    isolated.parent.mkdir(parents=True, exist_ok=True)
    isolated.write_text(f"{PRIVATE_KEY}={SENTINEL_FILE}\n", encoding="utf-8")
    monkeypatch.setenv(PRIVATE_KEY, "from-env")
    assert resolve_secret(PRIVATE_KEY) == "from-env"


def test_devops_fallback_warns_once(isolated, tmp_path, monkeypatch):
    _write_devops_stub(tmp_path, monkeypatch)   # 有值
    with pytest.warns(DeprecationWarning, match="旧位置"):
        assert resolve_secret(PRIVATE_KEY) == SENTINEL_DEVOPS
    # 同键第二次命中不再提示
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert resolve_secret(PRIVATE_KEY) == SENTINEL_DEVOPS
        assert not [w for w in caught if w.category is DeprecationWarning], \
            "同键重复提示：去重失效"


def test_all_layers_missing_returns_empty(isolated, tmp_path, monkeypatch):
    _write_devops_stub(tmp_path, monkeypatch, content=None)   # devops 存根不存在
    assert not isolated.exists()
    assert resolve_secret(PRIVATE_KEY) == ""


def test_config_load_env_uses_resolve_secret(isolated, monkeypatch, tmp_path):
    """集成：tdm load_env 的 internal_token.client_secret 经 resolve_secret 取自有文件。"""
    _write_devops_stub(tmp_path, monkeypatch, content=None)
    sentinel = "unittest-own-file-secret-marker"
    isolated.parent.mkdir(parents=True, exist_ok=True)
    isolated.write_text(f"SG_TDM_CLIENT_SECRET={sentinel}\n", encoding="utf-8")
    monkeypatch.delenv("SG_TDM_CLIENT_SECRET", raising=False)

    from systems.tdm.config import load_env
    cfg = load_env("sit")
    assert cfg["internal_token"]["client_secret"] == sentinel


def test_config_load_env_sso_password_uses_resolve_secret(isolated, monkeypatch, tmp_path):
    """T-1034 集成：sso.password 同款回退——env yaml 默认位清空后经 resolve_secret 取链。

    曾经的缺陷形态：真实口令写在 env.sit.yaml 的 ${SG_SSO_PASSWORD:默认值} 位，
    入库推远端 + 环境变量/secrets 链永不生效（yaml 默认值恒胜）。
    """
    _write_devops_stub(tmp_path, monkeypatch, content=None)
    sentinel = "unittest-sso-file-marker"
    isolated.parent.mkdir(parents=True, exist_ok=True)
    isolated.write_text(f"SG_SSO_PASSWORD={sentinel}\n", encoding="utf-8")
    monkeypatch.delenv("SG_SSO_PASSWORD", raising=False)

    from systems.tdm.config import load_env
    cfg = load_env("sit")
    assert cfg["sso"]["password"] == sentinel


def test_config_load_env_sso_password_missing_is_empty(isolated, monkeypatch, tmp_path):
    """T-1034：三层全空 → sso.password 诚实为空（TokenProvider 登录时自然失败，
    不回退任何硬编码值——与「缺凭据诚实为空，由上层报错」契约一致）。"""
    _write_devops_stub(tmp_path, monkeypatch, content=None)
    monkeypatch.delenv("SG_SSO_PASSWORD", raising=False)

    from systems.tdm.config import load_env
    cfg = load_env("sit")
    assert cfg["sso"]["password"] == ""


def test_shared_env_yaml_no_plaintext_sso_password():
    """T-1034 凭据红线源码钉：共享 env yaml 不得再出现明文口令默认值
    （回归形态：真实密码写进 ${VAR:默认值} 的 default 位随仓库入库）。"""
    import io
    import os
    yaml_path = os.path.join(SG_ROOT, "systems", "_shared", "config", "env.sit.yaml")
    text = io.open(yaml_path, encoding="utf-8").read()
    assert "Fehorizon" not in text, "共享 env yaml 出现明文口令默认值（凭据红线）"
    assert "${SG_SSO_PASSWORD:}" in text, "sso.password 应保留空默认位的链路引用"
