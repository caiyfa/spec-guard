"""环境配置多系统支持测试：envs 全系统枚举 + env-config/test-db 按系统读写。

覆盖：
- /api/reference/envs 返回 systems 字段（全系统列表）
- _env_file：scope=system 时按 system 定位；scope=shared 与 system 无关
- get_env_config / save_env_config：system 参数透传 + 非法 system 400
- 兼容性：缺省 system 参数回落 tdm
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / ".." / "workbench" / "backend"))

from fastapi import HTTPException  # noqa: E402

from routers import reference  # noqa: E402
from services import systems_catalog  # noqa: E402


@pytest.fixture
def fake_systems(tmp_path, monkeypatch):
    """构造多系统目录：tdm 与 alpha 各有 env.sit.yaml，共享层一份。"""
    for name in ("tdm", "alpha"):
        d = tmp_path / "systems" / name / "config"
        d.mkdir(parents=True)
        (d / "env.sit.yaml").write_text(f"system: {name}\n", encoding="utf-8")
    shared = tmp_path / "systems" / "_shared" / "config"
    shared.mkdir(parents=True)
    (shared / "env.sit.yaml").write_text("sso: {domain: x}\n", encoding="utf-8")
    monkeypatch.setattr(reference, "_SYSTEMS_ROOT", tmp_path / "systems")
    monkeypatch.setattr(reference, "_SHARED_CONFIG_DIR", shared)
    monkeypatch.setattr(systems_catalog, "SYSTEMS_ROOT", tmp_path / "systems")
    return tmp_path / "systems"


def test_env_file_system_scope_by_system(fake_systems):
    p = reference._env_file("sit", "system", "alpha")
    assert p == fake_systems / "alpha" / "config" / "env.sit.yaml"


def test_env_file_shared_scope_ignores_system(fake_systems):
    p = reference._env_file("sit", "shared", "alpha")
    assert p == fake_systems / "_shared" / "config" / "env.sit.yaml"


def test_env_file_default_system_is_tdm(fake_systems):
    p = reference._env_file("sit")
    assert p == fake_systems / "tdm" / "config" / "env.sit.yaml"


@pytest.mark.parametrize("bad_env", ["../x", "a/b"])
def test_env_file_rejects_bad_env(fake_systems, bad_env):
    with pytest.raises(HTTPException) as ei:
        reference._env_file(bad_env)
    assert ei.value.status_code == 400


def test_env_file_empty_env_falls_back_to_sit(fake_systems):
    p = reference._env_file("")
    assert p == fake_systems / "tdm" / "config" / "env.sit.yaml"


def test_get_env_config_system_param(fake_systems):
    r = reference.get_env_config("sit", "system", "alpha")
    assert r["exists"] and r["system"] == "alpha"
    assert r["parsed"]["system"] == "alpha"


def test_get_env_config_missing_file(fake_systems):
    r = reference.get_env_config("uat", "system", "tdm")
    assert r["exists"] is False and r["system"] == "tdm"


def test_get_env_config_rejects_unknown_system(fake_systems):
    with pytest.raises(HTTPException) as ei:
        reference.get_env_config("sit", "system", "人才发展")
    assert ei.value.status_code == 400


def test_save_env_config_writes_system_file(fake_systems):
    r = reference.save_env_config(reference.EnvConfigBody(raw="gateway: http://x\n"), "sit", "system", "alpha")
    assert r["ok"] and r["system"] == "alpha"
    written = (fake_systems / "alpha" / "config" / "env.sit.yaml").read_text(encoding="utf-8")
    assert written == "gateway: http://x\n"


def test_list_envs_returns_systems_field(fake_systems):
    r = reference.list_envs()
    assert r["system"] == "tdm"  # 兼容字段保留
    names = [s["name"] for s in r["systems"]]
    assert "tdm" in names and "alpha" in names
    assert "_shared" not in names  # 共享层不出现在适配包枚举
