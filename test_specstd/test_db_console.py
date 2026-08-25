"""db_console router 端到端：schemas 清单 / query 审计 / 守卫 400 / 无 RBAC（登录即可）。

TestClient 隔离装配（sg_core.user_store.DB_PATH 打桩 tmp_path + mock 鉴权），
参照 test_multiuser.py 的 client fixture 模式——DB_PATH/SESSIONS_ROOT 均为模块
级常量（不读环境变量），隔离只能走 monkeypatch 打桩；mock 登录端点是
/api/auth/mock-login。全程不触真实 workbench.db 与 agent/sessions/。
"""
import importlib
import os
from pathlib import Path

import pytest

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402
importlib.reload(auth_mod)  # 确保以 mock 模式加载

from sg_core import user_store  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离的 SQLite 数据文件（审计落库断言读它）。"""
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    auth_mod._TOKEN_CACHE.clear()
    return db_file


@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    """装配 TestClient（隔离 DB + 隔离工作区注册表 + 隔离 sessions）。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    # 会话目录隔离（否则 TestClient 端到端测试写真实 agent/sessions）
    from routers import agent as agent_router
    monkeypatch.setattr(agent_router, "SESSIONS_ROOT", tmp_path / "sessions")
    # 注册一个合规工作区
    from test_specstd.helpers import create_valid_workspace
    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def _login(client, emp_no="90000001", name="测试"):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_query_guard_reject_returns_400(client):
    h = _login(client)
    r = client.post("/api/db/query", json={"sql": "DELETE FROM t"}, headers=h)
    assert r.status_code == 400
    assert "非查询语句" in r.json()["detail"]


def test_query_missing_db_config_reports_error(client, monkeypatch):
    from sg_core import db_access
    monkeypatch.setattr(db_access, "_load_env_cfg", lambda env: {})
    monkeypatch.setattr(db_access, "invalidate_cache", lambda: None)
    h = _login(client)
    r = client.post("/api/db/query", json={"sql": "SELECT 1"}, headers=h)
    # 未配置 db 段：400 + hint（诚实报错不炸 500）
    assert r.status_code == 400
    assert "db 段" in r.json()["detail"]


def test_query_success_writes_audit(client, db, monkeypatch):
    # 假连接：execute_readonly 返回固定结果（审计链路验证不依赖真实 DB）
    from sg_core import db_access
    monkeypatch.setattr(
        db_access, "execute_readonly",
        lambda sql, **kw: {"rows": [{"x": 1}], "row_count": 1,
                           "truncated": False, "elapsed_ms": 3,
                           "sql_rendered": sql})
    h = _login(client)
    r = client.post("/api/db/query", json={"sql": "SELECT 1"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == 1 and body["rows"] == [{"x": 1}]
    # 审计已落库（action=db_query）
    conn = user_store.db_connect(db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action='db_query'").fetchone()
        assert row["n"] >= 1
    finally:
        conn.close()


def test_schemas_empty_when_no_db(client, monkeypatch):
    from sg_core import db_access
    monkeypatch.setattr(db_access, "_load_env_cfg", lambda env: {})
    monkeypatch.setattr(db_access, "invalidate_cache", lambda: None)
    h = _login(client)
    r = client.get("/api/db/schemas", headers=h)
    assert r.status_code == 200
    assert r.json()["schemas"] == []
