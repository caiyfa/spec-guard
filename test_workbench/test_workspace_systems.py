"""工作区注册「系统标识」防线测试：枚举接口逻辑 + 注册期硬校验。

覆盖：
- _list_systems：适配包枚举（过滤 _shared/__pycache__，含 envs/accounts 摘要）
- _validate_system：非法模块名 / 适配包不存在 → HTTPException(400)；合法 → 通过
- 路由挂载：GET /api/workspace/systems
"""
from pathlib import Path

import pytest


from fastapi import HTTPException  # noqa: E402

from routers import workspace  # noqa: E402
from services import systems_catalog  # noqa: E402


LIST_SYSTEMS = systems_catalog.list_systems
VALIDATE_SYSTEM = systems_catalog.validate_system


def test_router_prefix():
    assert workspace.router.prefix == "/api/workspace"


def test_router_reuses_catalog():
    # workspace 的注册校验与枚举应复用 services.systems_catalog（单一事实源）
    assert workspace.list_systems is systems_catalog.list_systems
    assert workspace.validate_system is systems_catalog.validate_system


def test_systems_route_registered():
    paths = [r.path for r in workspace.router.routes]
    assert "/api/workspace/systems" in paths


def test_list_systems_shape(tmp_path):
    """枚举返回 tdm 形状：envs + default_env + accounts（过滤 _shared 与 __pycache__）。"""
    (tmp_path / "_shared").mkdir()
    (tmp_path / "__pycache__").mkdir()
    tdm = tmp_path / "tdm"
    (tdm / "config").mkdir(parents=True)
    (tdm / "config" / "env.sit.yaml").write_text(
        "accounts:\n  default: {ad: a, emp_no: '1'}\n  internal: {type: internal}\n",
        encoding="utf-8")
    (tdm / "config" / "env.uat.yaml").write_text("system: tdm\n", encoding="utf-8")

    systems = LIST_SYSTEMS(tmp_path)
    assert [s["name"] for s in systems] == ["tdm"]
    s = systems[0]
    assert s["envs"] == ["sit", "uat"]
    assert s["default_env"] == "sit"
    assert s["accounts"] == ["default", "internal"]


def test_list_systems_no_config_dir(tmp_path):
    (tmp_path / "bare").mkdir()
    systems = LIST_SYSTEMS(tmp_path)
    assert systems == [{"name": "bare", "envs": [], "default_env": "", "accounts": []}]


@pytest.mark.parametrize("bad", ["人才发展", "a b", "1abc", "tdm/../x", ""])
def test_validate_system_rejects_invalid_name(bad):
    with pytest.raises(HTTPException) as ei:
        VALIDATE_SYSTEM(bad)
    assert ei.value.status_code == 400


def test_validate_system_rejects_missing_package(tmp_path, monkeypatch):
    monkeypatch.setattr(systems_catalog, "SYSTEMS_ROOT", tmp_path)
    with pytest.raises(HTTPException) as ei:
        VALIDATE_SYSTEM("not_exist")
    assert ei.value.status_code == 400


def test_validate_system_accepts_tdm(tmp_path, monkeypatch):
    (tmp_path / "tdm").mkdir()
    monkeypatch.setattr(systems_catalog, "SYSTEMS_ROOT", tmp_path)
    VALIDATE_SYSTEM("tdm")  # 不抛异常即通过
