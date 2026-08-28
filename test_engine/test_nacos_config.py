"""Nacos 配置中心客户端 + load_env 接线（T-1036）。

全部离线：httpx.get/post 打桩（FakeResponse），不触网。覆盖：
深合并语义 / disabled 直通 / 拉取+TTL 缓存+invalidate / 不可达 WARN 降级 /
404/非法 YAML 诚实报错 / 鉴权分支（accessToken 透传）/ load_env config_source
标注与 nacos 覆盖生效。
"""

import pytest
import yaml

from systems._shared import nacos
from systems._shared.nacos import NacosError, deep_merge, fetch_config, invalidate_cache

# ── deep_merge ──

def test_deep_merge_nested_and_scalar():
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "lst": [1, 2], "keep": "v"}
    override = {"nested": {"y": 3, "z": 4}, "lst": [9], "a": 2}
    out = deep_merge(base, override)
    assert out == {"a": 2, "nested": {"x": 1, "y": 3, "z": 4}, "lst": [9], "keep": "v"}
    assert base["nested"]["y"] == 2  # 纯函数不改入参


def test_deep_merge_empty_sides():
    assert deep_merge({}, {"a": 1}) == {"a": 1}
    assert deep_merge({"a": 1}, None) == {"a": 1}


# ── fetch_config ──

class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise NacosError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clean_cache():
    invalidate_cache()
    yield
    invalidate_cache()


def test_fetch_disabled_short_circuits(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("disabled 时不应发起 HTTP")
    monkeypatch.setattr(nacos.httpx, "get", _boom)
    monkeypatch.setattr(nacos.httpx, "post", _boom)
    assert fetch_config({"enabled": False}) is None
    assert fetch_config({}) is None


def test_fetch_success_and_ttl_cache(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return FakeResponse(text=yaml.safe_dump({"default_resource_code": "FROM_NACOS"}))

    monkeypatch.setattr(nacos.httpx, "get", fake_get)
    cfg = {"enabled": True, "server_addr": "http://nacos:8848", "data_id": "spec.yaml",
           "group": "DEFAULT_GROUP", "namespace": ""}
    assert fetch_config(cfg) == {"default_resource_code": "FROM_NACOS"}
    assert fetch_config(cfg) == {"default_resource_code": "FROM_NACOS"}
    assert len(calls) == 1  # TTL 缓存命中
    invalidate_cache()
    fetch_config(cfg)
    assert len(calls) == 2


def test_fetch_unreachable_warns_and_returns_none(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise nacos.httpx.ConnectError("connection refused")

    monkeypatch.setattr(nacos.httpx, "get", fake_get)
    with pytest.warns(UserWarning, match="Nacos 配置拉取降级本地文件"):
        assert fetch_config({"enabled": True, "server_addr": "http://nacos:8848",
                             "data_id": "spec.yaml"}) is None


def test_fetch_404_honest_error(monkeypatch):
    monkeypatch.setattr(nacos.httpx, "get",
                        lambda url, params=None, timeout=None: FakeResponse(status_code=404))
    # 底层：404 → NacosError（fetch_config 捕获后 WARN 降级返回 None）
    with pytest.raises(NacosError, match="配置不存在"):
        nacos._fetch_via_http({"server_addr": "http://nacos:8848", "data_id": "x.yaml"})
    with pytest.warns(UserWarning, match="降级"):
        assert fetch_config({"enabled": True, "server_addr": "http://n:1", "data_id": "x"}) is None


def test_fetch_non_dict_yaml_rejected(monkeypatch):
    monkeypatch.setattr(nacos.httpx, "get",
                        lambda url, params=None, timeout=None: FakeResponse(text="- just\n- list\n"))
    with pytest.warns(UserWarning, match="降级"):
        assert fetch_config({"enabled": True, "server_addr": "http://n:1", "data_id": "x"}) is None


def test_fetch_auth_branch_passes_access_token(monkeypatch):
    posts, gets = [], []

    def fake_post(url, data=None, timeout=None):
        posts.append((url, data))
        return FakeResponse(payload={"accessToken": "tok-1"})

    def fake_get(url, params=None, timeout=None):
        gets.append(params)
        return FakeResponse(text="{}")

    monkeypatch.setattr(nacos.httpx, "post", fake_post)
    monkeypatch.setattr(nacos.httpx, "get", fake_get)
    fetch_config({"enabled": True, "server_addr": "http://n:1", "data_id": "x",
                  "username": "nacos", "password": "pw"})
    assert posts[0][0] == "http://n:1/nacos/v1/auth/login"
    assert gets[0]["accessToken"] == "tok-1"
    assert gets[0]["dataId"] == "x"


# ── load_env 接线（temp env yaml + fetch_config 打桩）──

@pytest.fixture()
def tdm_cfg_dir(tmp_path, monkeypatch):
    """临时 tdm 配置目录（最小 env.test.yaml，含启用 nacos 块）。"""
    import systems.tdm.config as tdm_config
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "env.test.yaml").write_text(yaml.safe_dump({
        "system": "tdm", "env": "test",
        "default_resource_code": "FROM_FILE",
        "nacos": {"enabled": True, "server_addr": "http://n:1", "data_id": "spec-test.yaml"},
    }), encoding="utf-8")
    monkeypatch.setattr(tdm_config, "_CONFIG_DIR", str(cfg_dir))
    return tdm_config


def test_load_env_nacos_override_and_source(tdm_cfg_dir, monkeypatch):
    monkeypatch.setattr(nacos, "fetch_config",
                        lambda cfg: {"default_resource_code": "FROM_NACOS", "accounts": {"default": {"ad": "n1"}}})
    cfg = tdm_cfg_dir.load_env("test")
    assert cfg["config_source"] == "nacos:spec-test.yaml"
    assert cfg["default_resource_code"] == "FROM_NACOS"   # Nacos 逐键胜出
    assert cfg["accounts"]["default"]["ad"] == "n1"


def test_load_env_nacos_downgrade_to_file(tdm_cfg_dir, monkeypatch):
    monkeypatch.setattr(nacos, "fetch_config", lambda cfg: None)  # 不可达降级
    cfg = tdm_cfg_dir.load_env("test")
    assert cfg["config_source"].startswith("file (nacos 降级")
    assert cfg["default_resource_code"] == "FROM_FILE"    # 本地值兜底


def test_load_env_no_nacos_block_marks_file(monkeypatch, tmp_path):
    import systems.tdm.config as tdm_config
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "env.test.yaml").write_text(yaml.safe_dump({"system": "tdm", "env": "test"}),
                                           encoding="utf-8")
    monkeypatch.setattr(tdm_config, "_CONFIG_DIR", str(cfg_dir))
    cfg = tdm_config.load_env("test")
    assert cfg["config_source"] == "file"


def test_real_sit_yaml_nacos_disabled_by_default():
    """仓库内 env.sit.yaml 的 nacos 块保持注释（默认不接真）——防误启红线。"""
    import systems.tdm.config as tdm_config
    cfg = tdm_config.load_env("sit")
    assert not isinstance(cfg.get("nacos"), dict) or not cfg["nacos"].get("enabled")
    assert cfg["config_source"] == "file"
