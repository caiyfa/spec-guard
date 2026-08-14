"""rbac_store 单测：种子/CRUD/授权查询/保底约束（临时 SQLite 库，不碰 workbench.db）。"""
import pytest
from services import rbac_store


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "rbac.db"
    rbac_store.init_db(p)
    return p


def test_seed_idempotent(db):
    rbac_store.init_db(db)  # 重复 init 不重复写
    menus = rbac_store.list_menus(db)
    roles = rbac_store.list_roles(db)
    assert len(menus) >= 33  # 7 分组 + 26 菜单项（含新增 menu-menu-manage）
    assert {r["role_key"] for r in roles} == {"admin", "tester", "viewer", "product"}
    assert all(r["is_builtin"] for r in roles)
    # admin 保底两条授权
    assert set(rbac_store.list_role_menus("admin", db)) == {"menu-menu-manage", "menu-users"}


def test_menu_crud_validation(db):
    with pytest.raises(ValueError):  # key 重复
        rbac_store.create_menu({"menu_key": "menu-dashboard", "label": "x", "parent_key": ""}, db)
    with pytest.raises(ValueError):  # 父节点不存在
        rbac_store.create_menu({"menu_key": "menu-xyz", "label": "x", "parent_key": "group-nope"}, db)
    rbac_store.create_menu({"menu_key": "menu-xyz", "label": "新页", "path": "/xyz",
                            "parent_key": "group-scenario", "sort": 9, "visible": True}, db)
    m = rbac_store.get_menu("menu-xyz", db)
    assert m["label"] == "新页" and m["visible"] == 1
    with pytest.raises(ValueError):  # 有子项禁删
        rbac_store.delete_menu("group-scenario", db)
    with pytest.raises(ValueError):  # 系统菜单禁删
        rbac_store.delete_menu("menu-menu-manage", db)
    rbac_store.update_menu("menu-xyz", {"label": "改名", "visible": False}, db)
    assert rbac_store.get_menu("menu-xyz", db)["visible"] == 0


def test_role_crud_and_delete_guard(db):
    rbac_store.create_role("dept-lead", "部门主管", 9, db)
    assert rbac_store.role_exists("dept-lead", db)
    with pytest.raises(ValueError):  # 内置角色禁删
        rbac_store.delete_role("admin", db)
    with pytest.raises(ValueError):  # key 格式非法
        rbac_store.create_role("BAD KEY", "坏", 0, db)
    with pytest.raises(ValueError):  # 与内置冲突
        rbac_store.create_role("tester", "冲突", 0, db)


def test_role_menus_override_and_admin_guard(db):
    rbac_store.set_role_menus("tester", ["menu-plans", "menu-run"], db)
    assert set(rbac_store.list_role_menus("tester", db)) == {"menu-plans", "menu-run"}
    # 覆盖式写入
    rbac_store.set_role_menus("tester", ["menu-dag"], db)
    assert set(rbac_store.list_role_menus("tester", db)) == {"menu-dag"}
    # admin 保底：移除系统菜单被强制保留
    rbac_store.set_role_menus("admin", ["menu-graph"], db)
    assert {"menu-menu-manage", "menu-users"} <= set(rbac_store.list_role_menus("admin", db))
    # 不存在的角色/菜单
    with pytest.raises(ValueError):
        rbac_store.set_role_menus("ghost", ["menu-dag"], db)
    with pytest.raises(ValueError):
        rbac_store.set_role_menus("tester", ["menu-ghost"], db)


def test_user_has_menu_and_menus_for_user(db):
    rbac_store.set_role_menus("tester", ["menu-plans", "menu-run"], db)
    assert rbac_store.user_has_menu(["tester"], "menu-plans", db)
    assert not rbac_store.user_has_menu(["tester"], "menu-dag", db)
    assert not rbac_store.user_has_menu([], "menu-plans", db)
    # admin + is_system 恒通过（即使授权被手改删掉）
    import sqlite3
    with sqlite3.connect(str(db)) as c:
        c.execute("DELETE FROM role_menus WHERE role_key='admin'")
    assert rbac_store.user_has_menu(["admin"], "menu-users", db)
    assert not rbac_store.user_has_menu(["admin"], "menu-graph", db)
    # 可见树：visible=0 与无授权不返回；公开菜单恒含；分组无可见子项不返回
    rbac_store.set_role_menus("tester", ["menu-plans", "menu-run", "menu-schedules"], db)
    groups = rbac_store.menus_for_user(["tester"], db)
    labels = [g["label"] for g in groups]
    assert "场景" in labels and "执行" in labels      # 授权分组
    assert "Agent" in labels                           # 公开菜单分组恒含（首页对话）
    plan_item = next(i for g in groups if g["label"] == "场景" for i in g["items"] if i["to"] == "/plans")
    assert plan_item["label"] == "场景管理"


def test_set_roles_accepts_custom_role(db):
    """存量适配：set_roles 动态校验——自定义角色可赋给用户（Task 4 实现后通过）。"""
    from services import user_store
    rbac_store.create_role("dept-lead", "部门主管", 9, db)
    user_store.init_db(db)
    user_store.upsert_user("u9", "测试员", db)
    assert user_store.set_roles("u9", ["dept-lead"], "u9", db) is True
    u = user_store.get_user("u9", db)
    assert u["roles"] == ["dept-lead"]
    # 非法角色仍拒绝
    with pytest.raises(ValueError):
        user_store.set_roles("u9", ["ghost-role"], "u9", db)


def test_public_menu_always_accessible(db):
    """公开菜单（menu-agent）：无需任何角色/授权，登录即可访问（首页免权）。"""
    assert rbac_store.user_has_menu([], "menu-agent", db)          # 无角色也放行
    assert rbac_store.user_has_menu(["viewer"], "menu-agent", db)
    assert not rbac_store.user_has_menu([], "menu-plans", db)      # 非公开菜单仍拦截
    # 可见树：无授权用户也恒含对话菜单
    groups = rbac_store.menus_for_user([], db)
    agent = next(g for g in groups if g["label"] == "Agent")
    assert any(i["to"] == "/agent" for i in agent["items"])


def test_seed_dashboard_path_migrated(db):
    """存量库迁移：menu-dashboard path 由 / 改为 /dashboard（首页让位给对话页）。"""
    m = rbac_store.get_menu("menu-dashboard", db)
    assert m["path"] == "/dashboard"
    # 幂等：重复 init 不破坏
    rbac_store.init_db(db)
    assert rbac_store.get_menu("menu-dashboard", db)["path"] == "/dashboard"
