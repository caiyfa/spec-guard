"""菜单守卫中间件单测：直接构造 ASGI scope 调用（不依赖 FastAPI TestClient）。"""
import asyncio
from pathlib import Path

import pytest


from services import menu_guard, rbac_store, user_store  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "rbac.db"
    rbac_store.init_db(p)
    user_store.init_db(p)
    # 三个模块的默认库全部指向临时库（隔离，不碰 workbench.db）
    monkeypatch.setattr(rbac_store, "DB_PATH", p)
    monkeypatch.setattr(user_store, "DB_PATH", p)
    return p


class DummyApp:
    """透传 ASGI app：记录是否被调用。"""

    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})


def _scope(path: str, token: str = ""):
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return {"type": "http", "path": path, "headers": headers, "query_string": b""}


def _run(mw, scope):
    """执行中间件并收集响应。"""
    status = []
    body = []

    async def receive():
        return {}

    async def send(msg):
        if msg["type"] == "http.response.start":
            status.append(msg["status"])
        elif msg["type"] == "http.response.body":
            body.append(msg["body"])

    asyncio.run(mw(scope, receive, send))
    return status[0] if status else None, b"".join(body).decode()


def test_match_rules(db):
    assert menu_guard.menu_keys_for_path("/api/plans") == ("menu-plans",)
    assert menu_guard.menu_keys_for_path("/api/plans/PP-001") == ("menu-plans",)
    assert menu_guard.menu_keys_for_path("/api/agent/audit") == ("menu-audit",)  # 前两段精确优先
    assert menu_guard.menu_keys_for_path("/api/agent/chat") == ("menu-agent",)
    # spec 前缀细分：push 归 agent（仅 AgentChat 页调用）；T-996 合规校验整体收编 agent
    assert menu_guard.menu_keys_for_path("/api/spec/push") == ("menu-agent",)
    assert menu_guard.menu_keys_for_path("/api/spec/validate") == ("menu-agent",)
    assert menu_guard.menu_keys_for_path("/api/spec/deltas") == ("menu-agent",)
    # T-996 共享前缀并集：/api/runs 同时服务测试执行与执行中心
    assert menu_guard.menu_keys_for_path("/api/runs/history") == ("menu-run", "menu-history")
    # T-996 补绑漏洞与新增页
    assert menu_guard.menu_keys_for_path("/api/feishu-pool/x") == ("menu-feishu-pool",)
    assert menu_guard.menu_keys_for_path("/api/systems") == ("menu-system-config",)  # T-1010 收编
    assert menu_guard.menu_keys_for_path("/api/users/audit-log") == ("menu-audit",)
    assert menu_guard.menu_keys_for_path("/api/health") == ()
    assert menu_guard.menu_keys_for_path("/api/data-fab/x") == ()  # 未绑定放行


def test_guard_allow_with_grant(db, monkeypatch):
    rbac_store.set_role_menus("tester", ["menu-plans"], db)
    user_store.upsert_user("u1", "u1", db)  # set_roles 仅 UPDATE，用户需先建档
    user_store.set_roles("u1", ["tester"], "u1", db)
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    status, _ = _run(mw, _scope("/api/plans", "mock-u1"))
    assert status == 200


def test_guard_deny_without_grant(db, monkeypatch):
    user_store.upsert_user("u1", "u1", db)
    user_store.set_roles("u1", ["tester"], "u1", db)
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    status, body = _run(mw, _scope("/api/plans", "mock-u1"))
    assert status == 403
    assert "无权限" in body
    # 403 必须明确缺失的菜单（label + key + 开通路径），拒绝空泛提示
    assert "场景管理" in body and "menu-plans" in body
    assert "菜单管理 → 角色授权" in body


def test_guard_push_belongs_to_agent_menu(db, monkeypatch):
    """AgentChat 页的 push 操作只要求 agent 菜单授权，不依赖合规校验菜单。"""
    user_store.upsert_user("u1", "u1", db)
    user_store.set_roles("u1", ["tester"], "u1", db)
    rbac_store.set_role_menus("tester", ["menu-agent"], db)  # 仅有 agent 授权
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    status, _ = _run(mw, _scope("/api/spec/push", "mock-u1"))
    assert status == 200  # 有 agent 权限即可 push


def test_guard_agent_public_without_any_grant(db, monkeypatch):
    """首页免权：登录用户无任何菜单授权，agent 对话 API 与 push 也放行；审计仍拦。"""
    user_store.upsert_user("ad1", "ad1", db)  # 先占位 admin（否则 u1 首登自动提权）
    user_store.upsert_user("u1", "u1", db)    # u1 默认 viewer，无任何菜单授权
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    assert _run(mw, _scope("/api/agent/chat", "mock-u1"))[0] == 200   # 公开菜单放行
    assert _run(mw, _scope("/api/spec/push", "mock-u1"))[0] == 200    # agent 页操作放行
    assert _run(mw, _scope("/api/agent/audit", "mock-u1"))[0] == 403  # 审计非公开仍拦
    assert _run(mw, _scope("/api/plans", "mock-u1"))[0] == 403        # 非公开仍拦


def test_guard_spec_push_is_public_since_agent_public(db, monkeypatch):
    """push 归属 agent 菜单，agent 为公开菜单后 push 对登录用户免权（原 403 语义作废）。"""
    user_store.upsert_user("ad1", "ad1", db)
    user_store.upsert_user("u1", "u1", db)
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    assert _run(mw, _scope("/api/spec/push", "mock-u1"))[0] == 200


def test_guard_whitelist_and_unbound(db, monkeypatch):
    user_store.upsert_user("u1", "u1", db)
    user_store.set_roles("u1", ["tester"], "u1", db)
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    assert _run(mw, _scope("/api/health"))[0] == 200
    assert _run(mw, _scope("/api/auth/config"))[0] == 200
    assert _run(mw, _scope("/api/menus/me", "mock-u1"))[0] == 200
    assert _run(mw, _scope("/api/data-fab/x", "mock-u1"))[0] == 200  # 未绑定放行
    assert _run(mw, _scope("/api/feishu-pool/x", "mock-u1"))[0] == 403  # T-996 补绑后无授权拦截


def test_guard_shared_prefix_any_grant(db, monkeypatch):
    """共享前缀并集：/api/runs 归属 menu-run ∪ menu-history，任一授权即放行。"""
    user_store.upsert_user("u1", "u1", db)
    user_store.set_roles("u1", ["tester"], "u1", db)
    rbac_store.set_role_menus("tester", ["menu-history"], db)  # 仅执行中心授权
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    assert _run(mw, _scope("/api/runs/history", "mock-u1"))[0] == 200


def test_guard_admin_system_menu_bootstrap(db, monkeypatch):
    # 手删 admin 全部授权后，admin 访问系统菜单仍通过
    import sqlite3
    with sqlite3.connect(str(db)) as c:
        c.execute("DELETE FROM role_menus WHERE role_key='admin'")
    user_store.upsert_user("ad1", "ad1", db)
    user_store.set_roles("ad1", ["admin"], "ad1", db)
    monkeypatch.setenv("SG_AUTH_MODE", "mock")
    mw = menu_guard.MenuGuardMiddleware(DummyApp())
    assert _run(mw, _scope("/api/users", "mock-ad1"))[0] == 200   # menu-users is_system
    assert _run(mw, _scope("/api/graph", "mock-ad1"))[0] == 403   # 非系统菜单仍拦


def test_guard_ws_not_blocked(db):
    mw = menu_guard.MenuGuardMiddleware(DummyApp())

    async def fake_receive():
        return {}

    async def fake_send(msg):
        pass

    async def run():
        await mw({"type": "websocket", "path": "/api/agent/ws"},
                 fake_receive, fake_send)
        return mw.app.called

    assert asyncio.run(run()) is True
