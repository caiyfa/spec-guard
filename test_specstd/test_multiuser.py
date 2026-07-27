"""多用户与 RBAC 测试（M6-M8）。

覆盖：user_store 基座 / mock 认证 / RBAC 矩阵 / 工作区授权解析 / 执行队列。
全部离线：SG_AUTH_MODE=mock，SQLite 落 tmp_path。
"""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402
importlib.reload(auth_mod)  # 确保以 mock 模式加载

from services import user_store  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离的 SQLite 数据文件。"""
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    auth_mod._TOKEN_CACHE.clear()
    return db_file


# ══════════════════════════════════════════════════════════
# user_store 基座
# ══════════════════════════════════════════════════════════

class TestUserStore:
    def test_first_user_becomes_admin(self, db):
        u = user_store.upsert_user("90000001", "张三")
        assert u["role"] == "admin"  # 防锁死 bootstrap
        # 第二个用户默认 viewer
        u2 = user_store.upsert_user("90000002", "李四")
        assert u2["role"] == "viewer"

    def test_env_admin_accounts(self, db, monkeypatch):
        monkeypatch.setenv("SG_ADMIN_ACCOUNTS", "90000003, 90000004")
        u = user_store.upsert_user("90000003", "王五")
        assert u["role"] == "admin"

    def test_set_role_and_audit(self, db):
        user_store.upsert_user("90000001", "A")
        user_store.upsert_user("90000002", "B")
        assert user_store.set_role("90000002", "tester", "90000001") is True
        assert user_store.get_user("90000002")["role"] == "tester"
        with pytest.raises(ValueError):
            user_store.set_role("90000002", "superroot", "90000001")
        entries = user_store.list_audit()
        assert any(e["action"] == "set_role" for e in entries)

    def test_grants(self, db):
        assert user_store.grant_workspace("tdm", "90000002", "90000001") is True
        assert user_store.grant_workspace("tdm", "90000002", "90000001") is False  # 幂等
        assert user_store.has_grant("90000002", "tdm") is True
        assert user_store.has_grant("90000002", "pbs") is False
        assert user_store.revoke_workspace("tdm", "90000002", "90000001") is True
        assert user_store.has_grant("90000002", "tdm") is False

    def test_default_workspace(self, db):
        user_store.upsert_user("90000001", "A")
        assert user_store.set_default_workspace("90000001", "tdm") is True
        assert user_store.get_user("90000001")["default_workspace"] == "tdm"


# ══════════════════════════════════════════════════════════
# mock 认证
# ══════════════════════════════════════════════════════════

class TestMockAuth:
    def test_mock_token_issue_and_validate(self, db):
        token = auth_mod.issue_mock_token("90000001", "张三")
        assert token == "mock-90000001"
        emp_no, name = auth_mod._validate_token(token)
        assert emp_no == "90000001"
        assert name == "张三"

    def test_mock_token_invalid(self, db):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            auth_mod._validate_token("bad-token")

    def test_token_cache(self, db):
        token = auth_mod.issue_mock_token("90000001")
        auth_mod._validate_token(token)
        assert token in auth_mod._TOKEN_CACHE


# ══════════════════════════════════════════════════════════
# RBAC 矩阵（TestClient 端到端）
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    """装配 TestClient（隔离 DB + 隔离工作区注册表 + 隔离 sessions）。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    # 注册一个合规工作区供授权测试
    from test_specstd.helpers import create_valid_workspace
    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def _login(client, emp_no, name=""):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestRBACMatrix:
    def test_health_public(self, client):
        assert client.get("/api/health").status_code == 200

    def test_auth_config_public(self, client):
        r = client.get("/api/auth/config")
        assert r.status_code == 200
        assert r.json()["auth_mode"] == "mock"

    def test_unauthenticated_401(self, client):
        assert client.get("/api/scenarios").status_code == 401
        assert client.get("/api/runs/status").status_code == 401
        assert client.get("/api/workspace/list").status_code == 401

    def test_me(self, client):
        h = _login(client, "90000001", "张三")
        r = client.get("/api/auth/me", headers=h)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"  # 首用户 bootstrap

    def test_viewer_blocked_from_write_endpoints(self, client):
        _login(client, "90000001")          # admin（首用户）
        h_viewer = _login(client, "90000002")  # 默认 viewer
        # viewer：读可以，写全拒
        assert client.get("/api/scenarios", headers=h_viewer).status_code == 200
        assert client.post("/api/runs/trigger", json={"scope": "engine_modes"},
                           headers=h_viewer).status_code == 403
        assert client.post("/api/drafts/x.yaml/validate", headers=h_viewer).status_code == 403
        assert client.get("/api/feedback/ledger", headers=h_viewer).status_code == 403
        assert client.get("/api/users", headers=h_viewer).status_code == 403
        assert client.post("/api/workspace/register-local",
                           json={"name": "x", "path": "/tmp", "system": "tdm"},
                           headers=h_viewer).status_code == 403
        assert client.post("/api/agent/chat", json={"message": "hi"},
                           headers=h_viewer).status_code == 403

    def test_tester_allowed_but_not_admin_ops(self, client):
        h_admin = _login(client, "90000001")
        h_tester = _login(client, "90000002")
        # admin 提权 tester
        r = client.put("/api/users/90000002/role", json={"role": "tester"}, headers=h_admin)
        assert r.status_code == 200
        # tester：不能管用户/工作区注册/环境配置
        assert client.get("/api/users", headers=h_tester).status_code == 403
        assert client.post("/api/workspace/register-local",
                           json={"name": "x", "path": "/tmp", "system": "tdm"},
                           headers=h_tester).status_code == 403
        assert client.put("/api/reference/env-config", json={"raw": "a: 1"},
                          headers=h_tester).status_code == 403

    def test_audit_log_admin_only(self, client):
        _login(client, "90000001")
        h_tester = _login(client, "90000002")
        assert client.get("/api/users/audit-log", headers=h_tester).status_code == 403


# ══════════════════════════════════════════════════════════
# 工作区授权解析
# ══════════════════════════════════════════════════════════

class TestWorkspaceGrants:
    def test_list_filtered_by_grants(self, client):
        h_admin = _login(client, "90000001")
        h_user = _login(client, "90000002")
        # admin 见全部（含 tdm）
        assert len(client.get("/api/workspace/list", headers=h_admin).json()["workspaces"]) == 1
        # 未授权用户看不到
        assert len(client.get("/api/workspace/list", headers=h_user).json()["workspaces"]) == 0
        # admin 授权后可见
        client.post("/api/users/90000002/grants", json={"workspace_name": "tdm"}, headers=h_admin)
        lst = client.get("/api/workspace/list", headers=h_user).json()["workspaces"]
        assert len(lst) == 1 and lst[0]["name"] == "tdm"

    def test_spec_files_requires_grant(self, client):
        h_admin = _login(client, "90000001")
        h_user = _login(client, "90000002")
        # 未授权 → 403
        r = client.get("/api/workspace/spec-files",
                       headers={**h_user, "X-SG-Workspace": "tdm"})
        assert r.status_code == 403
        # 授权 → 200
        client.post("/api/users/90000002/grants", json={"workspace_name": "tdm"}, headers=h_admin)
        r = client.get("/api/workspace/spec-files",
                       headers={**h_user, "X-SG-Workspace": "tdm"})
        assert r.status_code == 200
        assert any(f["path"].endswith("spec.md") for f in r.json()["files"])

    def test_no_workspace_selected_403(self, client):
        h_user = _login(client, "90000002")
        r = client.get("/api/workspace/spec-files", headers=h_user)
        assert r.status_code == 403
        assert "选择工作区" in r.json()["detail"]

    def test_default_workspace_resolution(self, client):
        h_admin = _login(client, "90000001")
        h_user = _login(client, "90000002")
        client.post("/api/users/90000002/grants", json={"workspace_name": "tdm"}, headers=h_admin)
        # 设个人默认后，无需 header 也能访问
        r = client.put("/api/users/me/default-workspace",
                       json={"workspace_name": "tdm"}, headers=h_user)
        assert r.status_code == 200
        r = client.get("/api/workspace/spec-files", headers=h_user)
        assert r.status_code == 200

    def test_set_default_requires_grant(self, client):
        _login(client, "90000001")  # 先登录 admin，确保 90000002 是 viewer
        h_user = _login(client, "90000002")
        r = client.put("/api/users/me/default-workspace",
                       json={"workspace_name": "tdm"}, headers=h_user)
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════
# WebSocket 认证与角色门禁（M6：Request 型依赖在 WS 上不可注入，需 WS 专用依赖）
# ══════════════════════════════════════════════════════════

class TestWebSocketAuth:
    def test_runs_stream_requires_token(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/api/runs/stream"):
                pass

    def test_runs_stream_connects_with_token(self, client):
        h = _login(client, "90000001")
        token = h["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"/api/runs/stream?token={token}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "status"

    def test_agent_ws_role_gate(self, client):
        h_admin = _login(client, "90000001")
        h_viewer = _login(client, "90000002")  # 非首用户 → viewer
        admin_token = h_admin["Authorization"].split(" ", 1)[1]
        viewer_token = h_viewer["Authorization"].split(" ", 1)[1]
        # viewer 被拒（tester+ 门禁）
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/agent/ws?token={viewer_token}"):
                pass
        # admin 可连接并收到 started 事件
        with client.websocket_connect(f"/api/agent/ws?token={admin_token}") as ws:
            ws.send_json({"message": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "state" and msg.get("status") == "started"


# ══════════════════════════════════════════════════════════
# 执行队列（M8）
# ══════════════════════════════════════════════════════════

class TestRunQueue:
    def test_enqueue_when_running(self, db, monkeypatch):
        import asyncio
        from services.runner import run_manager
        # 模拟占用中
        monkeypatch.setattr(run_manager, "status", "running")
        result = asyncio.run(run_manager.trigger(
            scope="engine_modes", emp_no="90000001", workspace="tdm"))
        assert result["ok"] is True
        assert result["queued"] is True
        assert result["position"] == 1
        # 第二个排队者 position=2
        result2 = asyncio.run(run_manager.trigger(
            scope="engine_modes", emp_no="90000002", workspace="tdm"))
        assert result2["position"] == 2
        # 队表持久化
        rows = [r for r in user_store.list_run_queue() if r["status"] == "queued"]
        assert len(rows) == 2
        assert rows[0]["emp_no"] == "90000001"

    def test_cancel_queued(self, db):
        qid = user_store.enqueue_run("90000001", "all", "", "sit", "", [], False, "tdm")
        assert user_store.update_run_queue(qid, "cancelled", finished=True) is True
        assert user_store.get_run_queue_item(qid)["status"] == "cancelled"

    def test_fail_stale_running(self, db):
        qid = user_store.enqueue_run("90000001", "all", "", "sit", "", [], False, "tdm",
                                     status="running")
        assert user_store.fail_stale_running() == 1
        assert user_store.get_run_queue_item(qid)["status"] == "failed"

    def test_queue_consumption_e2e(self, db, monkeypatch):
        """真实队列消费：占用释放后自动启动下一个（engine_modes 离线执行）。"""
        import asyncio
        import time
        from services.runner import run_manager

        async def scenario():
            # 第一个执行真实跑（engine_modes 离线秒级完成）
            r1 = await run_manager.trigger(scope="engine_modes", emp_no="90000001",
                                           workspace="")
            assert r1["ok"] is True and not r1.get("queued")
            # 第二个进入队列
            r2 = await run_manager.trigger(scope="engine_modes", emp_no="90000002",
                                           workspace="")
            assert r2.get("queued") is True
            # 等待两个执行全部完成
            deadline = time.time() + 60
            while time.time() < deadline:
                await asyncio.sleep(0.5)
                queued = [r for r in user_store.list_run_queue() if r["status"] == "queued"]
                if not run_manager.is_running and not queued:
                    break
            # 直接读库验证全部状态（list_run_queue 只返回 queued/running）
            import sqlite3
            with sqlite3.connect(str(db)) as conn:
                return conn.execute("SELECT emp_no, status FROM run_queue").fetchall()

        # 清理单例状态（防与其他用例串扰）
        run_manager.status = "idle"
        run_manager.process = None
        rows = asyncio.run(scenario())
        done = [r for r in rows if r[1] == "done"]
        assert len(done) >= 2, f"两个执行都应完成: {rows}"
        owners = {r[0] for r in done}
        assert owners == {"90000001", "90000002"}
