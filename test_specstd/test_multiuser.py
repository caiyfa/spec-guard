"""多用户与 RBAC 测试（M6-M8）。

覆盖：user_store 基座 / mock 认证 / RBAC 矩阵 / 工作区授权解析 / 执行队列。
全部离线：SG_AUTH_MODE=mock，SQLite 落 tmp_path。
"""

import importlib
import json
import os
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

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
    # 会话目录隔离（否则 TestClient 端到端测试写真实 agent/sessions）
    from routers import agent as agent_router
    monkeypatch.setattr(agent_router, "SESSIONS_ROOT", tmp_path / "sessions")
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


class TestSessionConcurrencyGuard:
    """K-015：同会话并发写防护（_ACTIVE_RUNS 互斥）。

    生产佐证：同 session_id 两个并发 run 的 save 全量覆盖写互相冲掉内容。
    """

    def test_chat_409_when_session_active(self, client):
        """K-015：_ACTIVE_RUNS 并发防护语义（POST /chat 端点已随 T-601 删除，
        防护逻辑在 WS 端点仍生效，此处直接验证互斥判定）。"""
        import asyncio
        from routers.agent import _ACTIVE_RUNS, _run_in_progress
        sid = "testsession001"

        async def scenario():
            # 预置一个未完成的活跃 run（dummy task，.done() 为 False）
            async def _dummy():
                await asyncio.sleep(60)

            task = asyncio.create_task(_dummy())
            _ACTIVE_RUNS[sid] = task
            try:
                assert _run_in_progress(sid) is True
                assert _run_in_progress("other-sid") is False
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                _ACTIVE_RUNS.clear()

        asyncio.run(scenario())

    def test_chat_no_conflict_when_done(self, client):
        import asyncio
        from routers.agent import _ACTIVE_RUNS, _run_in_progress
        sid = "testsession002"

        async def scenario():
            async def _done():
                return 1

            task = asyncio.create_task(_done())
            await asyncio.sleep(0)  # 让 task 完成
            _ACTIVE_RUNS[sid] = task
            try:
                assert _run_in_progress(sid) is False  # 已完成 → 不拦截
            finally:
                _ACTIVE_RUNS.clear()

        asyncio.run(scenario())

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
        # T-1000：工作区注册放开登录即可（自管理，注册人记 owner_emp）——viewer 不再 403

    def test_tester_allowed_but_not_admin_ops(self, client):
        h_admin = _login(client, "90000001")
        h_tester = _login(client, "90000002")
        # admin 提权 tester
        r = client.put("/api/users/90000002/role", json={"role": "tester"}, headers=h_admin)
        assert r.status_code == 200
        # tester：不能管用户/工作区注销/环境配置（T-1000：注册已放开登录即可）
        assert client.get("/api/users", headers=h_tester).status_code == 403
        assert client.delete("/api/workspace/some-ws", headers=h_tester).status_code == 403
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
        """T-123：首帧非 auth → 服务端关闭连接（token 不再经 query 明文）。"""
        with client.websocket_connect("/api/runs/stream") as ws:
            ws.send_json({"type": "ping"})  # 非认证首帧
            with pytest.raises(Exception):
                ws.receive_json()

    def test_runs_stream_connects_with_token(self, client):
        """T-123：首帧 auth 认证通过后正常订阅（status 消息）。"""
        h = _login(client, "90000001")
        token = h["Authorization"].split(" ", 1)[1]
        with client.websocket_connect("/api/runs/stream") as ws:
            ws.send_json({"type": "auth", "token": token})
            msg = ws.receive_json()
            assert msg["type"] == "status"

    def test_agent_ws_open_to_all_logged_in(self, client):
        h_admin = _login(client, "90000001")
        h_viewer = _login(client, "90000002")  # 非首用户 → viewer
        admin_token = h_admin["Authorization"].split(" ", 1)[1]
        viewer_token = h_viewer["Authorization"].split(" ", 1)[1]
        # 2026-08-14 首页免权：viewer 也可连接（不再 tester+ 门禁）
        with client.websocket_connect(f"/api/agent/ws?token={viewer_token}") as ws:
            ws.send_json({"message": "ping", "purpose": "test_workbench"})
            msg = ws.receive_json()
            assert msg["type"] == "state" and msg.get("status") == "started"
        # admin 可连接并收到 started 事件（T-010：新建会话必须带用途，未选使命被拒）
        with client.websocket_connect(f"/api/agent/ws?token={admin_token}") as ws:
            ws.send_json({"message": "ping", "purpose": "test_workbench"})
            msg = ws.receive_json()
            assert msg["type"] == "state" and msg.get("status") == "started"


# ══════════════════════════════════════════════════════════
# 执行队列（M8）
# ══════════════════════════════════════════════════════════

class TestSessionArchive:
    """T-010 扩展：会话批量归档/恢复（只处理本人会话；列表默认不含已归档）。"""

    def _create(self, client, headers, workspace=""):
        r = client.post("/api/agent/sessions",
                        headers=headers, json={"purpose": "test_workbench", "workspace": workspace})
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    def test_patch_archived_roundtrip(self, client):
        h = _login(client, "90000001")
        sid = self._create(client, h)
        # 默认未归档且列表可见
        r = client.get("/api/agent/sessions", headers=h)
        assert any(s["id"] == sid and not s.get("archived") for s in r.json()["sessions"])
        # 归档
        r = client.patch(f"/api/agent/sessions/{sid}", headers=h, json={"archived": True})
        assert r.status_code == 200
        # 默认列表不含已归档；include_archived=1 含且标记为 True
        r = client.get("/api/agent/sessions", headers=h)
        assert all(s["id"] != sid for s in r.json()["sessions"])
        r = client.get("/api/agent/sessions?include_archived=1", headers=h)
        found = [s for s in r.json()["sessions"] if s["id"] == sid]
        assert len(found) == 1 and found[0]["archived"] is True
        # 恢复
        r = client.patch(f"/api/agent/sessions/{sid}", headers=h, json={"archived": False})
        assert r.status_code == 200
        r = client.get("/api/agent/sessions", headers=h)
        assert any(s["id"] == sid and not s.get("archived") for s in r.json()["sessions"])

    def test_batch_archive_own_sessions(self, client):
        h = _login(client, "90000001")
        sid1 = self._create(client, h)
        sid2 = self._create(client, h)
        r = client.post("/api/agent/sessions/batch-archive", headers=h,
                        json={"session_ids": [sid1, sid2], "archived": True})
        assert r.status_code == 200
        body = r.json()
        assert body["processed"] == 2 and body["skipped"] == []
        # 默认列表两者都不可见
        r = client.get("/api/agent/sessions", headers=h)
        ids = {s["id"] for s in r.json()["sessions"]}
        assert sid1 not in ids and sid2 not in ids
        # 批量恢复
        r = client.post("/api/agent/sessions/batch-archive", headers=h,
                        json={"session_ids": [sid1, sid2], "archived": False})
        assert r.json()["processed"] == 2

    def test_batch_archive_skips_others(self, client):
        """owner 权限：每个用户只管理自己创建的会话，admin 也无越权——他人会话跳过。"""
        h1 = _login(client, "90000001")  # 首个登录 = admin
        h2 = _login(client, "90000002")
        # 90000002 提升为 tester（bootstrap 首个用户已占 admin，次用户默认 viewer）
        r = client.put("/api/users/90000002/role", json={"role": "tester"}, headers=h1)
        assert r.status_code == 200, r.text
        sid_a = self._create(client, h1)  # admin 的会话
        sid_b = self._create(client, h2)  # tester 的会话
        # 非 admin 尝试归档他人会话 → skipped
        r = client.post("/api/agent/sessions/batch-archive", headers=h2,
                        json={"session_ids": [sid_a], "archived": True})
        assert r.status_code == 200
        body = r.json()
        assert body["processed"] == 0 and body["skipped"] == [sid_a]
        # admin 同样无越权：归档他人会话 → skipped
        r = client.post("/api/agent/sessions/batch-archive", headers=h1,
                        json={"session_ids": [sid_b], "archived": True})
        assert r.status_code == 200
        body = r.json()
        assert body["processed"] == 0 and body["skipped"] == [sid_b]
        # 原会话均未被归档（各自列表仍可见）
        r = client.get("/api/agent/sessions", headers=h1)
        assert any(s["id"] == sid_a for s in r.json()["sessions"])
        r = client.get("/api/agent/sessions", headers=h2)
        assert any(s["id"] == sid_b for s in r.json()["sessions"])
        # 各自管理自己的会话正常生效
        r = client.post("/api/agent/sessions/batch-archive", headers=h2,
                        json={"session_ids": [sid_b], "archived": True})
        assert r.json()["processed"] == 1
        r = client.post("/api/agent/sessions/batch-archive", headers=h1,
                        json={"session_ids": [sid_a], "archived": True})
        assert r.json()["processed"] == 1

    def test_list_sessions_own_only(self, client):
        """会话列表只返回自己的会话：admin 也无聚合特权，他人会话不出现在查询结果中。"""
        h1 = _login(client, "90000001")  # 首个登录 = admin
        h2 = _login(client, "90000002")
        r = client.put("/api/users/90000002/role", json={"role": "tester"}, headers=h1)
        assert r.status_code == 200, r.text
        sid_a = self._create(client, h1)
        sid_b = self._create(client, h2)
        # admin 列表只有自己的会话，不含他人会话
        r = client.get("/api/agent/sessions?include_archived=1", headers=h1)
        ids = {s["id"] for s in r.json()["sessions"]}
        assert sid_a in ids and sid_b not in ids
        # 非 admin 同理
        r = client.get("/api/agent/sessions?include_archived=1", headers=h2)
        ids = {s["id"] for s in r.json()["sessions"]}
        assert sid_b in ids and sid_a not in ids

    def test_batch_archive_empty_rejected(self, client):
        h = _login(client, "90000001")
        r = client.post("/api/agent/sessions/batch-archive", headers=h,
                        json={"session_ids": [], "archived": True})
        assert r.status_code == 400


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


# ══════════════════════════════════════════════════════════
# T-402: Agent cancel 端点
# ══════════════════════════════════════════════════════════

class TestAgentCancel:
    """T-402：Agent cancel 端点测试。"""

    def test_cancel_no_active_run(self, client):
        """无活跃运行返回 404。"""
        h = _login(client, "90000001")
        r = client.post("/api/agent/cancel/nonexistent_sid", headers=h)
        assert r.status_code == 404
        assert "没有活跃的运行" in r.json()["detail"]

    def test_cancel_invalid_session_id(self, client):
        """非法 session_id 返回 400。"""
        h = _login(client, "90000001")
        # @ 开头不符合 SESSION_ID_RE（^[A-Za-z0-9]...），是单一路径段
        r = client.post("/api/agent/cancel/%40invalid", headers=h)
        assert r.status_code == 400
        assert "非法 session_id" in r.json()["detail"]

    def test_cancel_requires_auth(self, client):
        """未经认证返回 401。"""
        r = client.post("/api/agent/cancel/test_sid")
        assert r.status_code == 401

    def test_cancel_open_to_all_logged_in(self, client):
        """2026-08-14 首页免权：viewer 不再被角色门禁拦，进入业务逻辑（无活跃运行 → 404）。"""
        _login(client, "90000001")  # admin（首用户）
        h_viewer = _login(client, "90000002")  # viewer
        r = client.post("/api/agent/cancel/test_sid", headers=h_viewer)
        assert r.status_code == 404  # 通过门禁后：该会话没有活跃的运行
        assert r.json()["detail"] == "该会话没有活跃的运行"

    def test_cancel_active_run(self, client):
        """有活跃运行时 cancel 返回 200。"""
        from routers.agent import _ACTIVE_RUNTIMES
        from agent.runtime import AgentRuntime
        from agent.llm_client import LLMClient
        h = _login(client, "90000001")
        sid = "test_active_sid"
        # 模拟活跃运行
        runtime = AgentRuntime(LLMClient(base_url=""), max_turns=3)
        _ACTIVE_RUNTIMES[sid] = runtime
        try:
            r = client.post(f"/api/agent/cancel/{sid}", headers=h)
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["session_id"] == sid
            assert "已请求取消" in data["message"]
        finally:
            _ACTIVE_RUNTIMES.pop(sid, None)
