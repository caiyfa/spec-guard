"""rbac API 校验逻辑经 store 层测试覆盖；本文件验证路由挂载与 /api/menus/me 形状。"""
from pathlib import Path

import pytest


from routers import rbac  # noqa: E402
from services import rbac_store  # noqa: E402


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "rbac.db"
    rbac_store.init_db(p)
    return p


def test_router_prefix():
    assert rbac.router.prefix == "/api"


def test_menus_me_shape(db):
    rbac_store.set_role_menus("tester", ["menu-plans", "menu-run"], db)
    groups = rbac_store.menus_for_user(["tester"], db)
    assert isinstance(groups, list)
    for g in groups:
        assert {"label", "icon", "items"} <= set(g)
        for i in g["items"]:
            assert {"to", "label"} <= set(i)
            assert "end" in i
