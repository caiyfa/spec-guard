"""辅助会话 session 模型（设计 2026-08-25 §B2）：extra_meta 透传 / save 继承 / list 返回 / set_meta_fields。"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def sm(tmp_path):
    from agent.session import SessionManager
    return SessionManager(tmp_path, workspace="w1")


def test_create_with_extra_meta(sm):
    sid = sm.create(emp_no="90024166", workspace="w1", purpose="sql_assistant",
                    extra_meta={"kind": "aux", "parent_session_id": "PARENT1"})
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["kind"] == "aux"
    assert meta["parent_session_id"] == "PARENT1"
    mfile = sm.sessions_dir / f"{sid}_meta.json"
    assert json.loads(mfile.read_text(encoding="utf-8"))["kind"] == "aux"


def test_create_without_extra_meta_unchanged(sm):
    sid = sm.create(emp_no="e", workspace="w1")
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert "kind" not in meta  # 非辅助会话不写 kind（存量语义不变）


def test_save_inherits_aux_fields(sm):
    sid = sm.create(emp_no="e", workspace="w1", purpose="sql_assistant",
                    extra_meta={"kind": "aux", "parent_session_id": "P1", "last_parent_fp": "abc"})
    sm.save(sid, [{"role": "user", "content": "hi"}], emp_no="e", workspace="w1")
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["kind"] == "aux"
    assert meta["parent_session_id"] == "P1"
    assert meta["last_parent_fp"] == "abc"


def test_list_sessions_returns_aux_fields(sm):
    p = sm.create(emp_no="e", workspace="w1")
    a = sm.create(emp_no="e", workspace="w1", purpose="sql_assistant",
                  extra_meta={"kind": "aux", "parent_session_id": p})
    sessions = sm.list_sessions()
    aux = next(s for s in sessions if s["id"] == a)
    parent = next(s for s in sessions if s["id"] == p)
    assert aux["kind"] == "aux"
    assert aux["parent_session_id"] == p
    assert parent.get("kind", "") == ""


def test_set_meta_fields_roundtrip(sm):
    sid = sm.create(emp_no="e", workspace="w1")
    ok = sm.set_meta_fields(sid, last_parent_fp="fp123")
    assert ok is True
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["last_parent_fp"] == "fp123"
    sm.set_meta_fields(sid, kind="aux")
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["last_parent_fp"] == "fp123" and meta["kind"] == "aux"


def test_set_meta_fields_missing_session(sm):
    assert sm.set_meta_fields("nonexistent_sid", kind="aux") is False


def test_sql_assistant_purpose_has_draft_domain():
    """验收缺陷修复（2026-08-25 主库验收发现）：sql_assistant 白名单必须含 draft 域，
    否则 write_draft 落盘不可用（产出物区/引用回流链路断裂）。"""
    from agent.purpose_loader import load_purpose
    p = load_purpose("sql_assistant")
    assert p is not None
    assert "draft" in p.domains

# ══════════════════════════════════════════════════════════
# spawn 派生 API（设计 2026-08-25 §B3）——TestClient 端到端，SG_AUX_TEST_TMP 隔离。
# 适配说明：DB_PATH/SESSIONS_ROOT 均为模块常量（不读环境变量），隔离经
# monkeypatch 落到 SG_AUX_TEST_TMP 目录；mock 登录走 /api/auth/mock-login。
# ══════════════════════════════════════════════════════════
import os

_SPY_TMP = os.environ.get("SG_AUX_TEST_TMP")  # 隔离目录由运行命令注入

if _SPY_TMP:
    os.environ["SG_AUTH_MODE"] = "mock"


@pytest.fixture()
def aux_client(monkeypatch):
    """装配 TestClient（隔离 DB + 隔离 sessions，全部落 SG_AUX_TEST_TMP）。"""
    if not _SPY_TMP:
        pytest.skip("需隔离环境（SG_AUX_TEST_TMP）")
    base = Path(_SPY_TMP)
    base.mkdir(parents=True, exist_ok=True)
    from sg_core import user_store as us
    monkeypatch.setattr(us, "DB_PATH", base / "wb.db")
    us.init_db(base / "wb.db")
    import services.auth as auth_mod
    auth_mod._TOKEN_CACHE.clear()
    from services import agent_session_store as ass
    monkeypatch.setattr(ass, "DB_PATH", base / "wb.db")
    from routers import agent as agent_router
    monkeypatch.setattr(agent_router, "SESSIONS_ROOT", base / "sessions")
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", base / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", base / "_clones")
    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        r = c.post("/api/auth/mock-login", json={"emp_no": "90000001", "name": "测试"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.mark.skipif(not _SPY_TMP, reason="需隔离环境（SG_AUX_TEST_TMP）")
class TestSpawnApi:
    def test_spawn_creates_aux_session(self, aux_client):
        c = aux_client
        parent = c.post("/api/agent/sessions",
                        json={"purpose": "test_workbench"}).json()["session_id"]
        r = c.post("/api/agent/sessions/spawn",
                   json={"parent_session_id": parent, "purpose": "sql_assistant"})
        assert r.status_code == 200
        body = r.json()
        assert body["created"] is True and body["session_id"] != parent

    def test_spawn_idempotent_same_parent_purpose(self, aux_client):
        c = aux_client
        parent = c.post("/api/agent/sessions",
                        json={"purpose": "test_workbench"}).json()["session_id"]
        s1 = c.post("/api/agent/sessions/spawn",
                    json={"parent_session_id": parent, "purpose": "sql_assistant"}).json()
        s2 = c.post("/api/agent/sessions/spawn",
                    json={"parent_session_id": parent, "purpose": "sql_assistant"}).json()
        assert s1["session_id"] == s2["session_id"]
        assert s2["created"] is False

    def test_spawn_parent_not_found_404(self, aux_client):
        c = aux_client
        r = c.post("/api/agent/sessions/spawn",
                   json={"parent_session_id": "NOT_EXIST_1", "purpose": "sql_assistant"})
        assert r.status_code == 404

    def test_spawn_bad_purpose_403(self, aux_client):
        c = aux_client
        parent = c.post("/api/agent/sessions",
                        json={"purpose": "test_workbench"}).json()["session_id"]
        r = c.post("/api/agent/sessions/spawn",
                   json={"parent_session_id": parent, "purpose": "no_such_purpose"})
        assert r.status_code == 403


class TestParentSnapshot:
    def test_snapshot_changed_content(self, sm):
        from test_specstd.routers_shim import _parent_snapshot
        p = sm.create(emp_no="e", workspace="w1")
        sm.save(p, [
            {"role": "user", "content": "生成 HI-PERM-001"},
            {"role": "assistant", "content": "场景清单已列出，等待拍板" + "x" * 600},
        ], emp_no="e", workspace="w1")
        block, fp = _parent_snapshot(sm, p, last_fp="")
        assert block.startswith("<parent_context>")
        assert "等待拍板" in block  # assistant 摘要可见
        assert fp  # 新指纹非空

    def test_snapshot_unchanged_returns_short_line(self, sm):
        from test_specstd.routers_shim import _parent_snapshot
        p = sm.create(emp_no="e", workspace="w1")
        sm.save(p, [{"role": "assistant", "content": "hello"}], emp_no="e", workspace="w1")
        _, fp = _parent_snapshot(sm, p, last_fp="")
        block2, _ = _parent_snapshot(sm, p, last_fp=fp)
        assert "无变更" in block2 and not block2.startswith("<parent_context>")

    def test_snapshot_parent_missing_degrades(self, sm):
        from test_specstd.routers_shim import _parent_snapshot
        block, _ = _parent_snapshot(sm, "NOT_EXIST_1", last_fp="")
        assert "父会话不可读" in block

    def test_snapshot_truncated_to_8kb(self, sm):
        from test_specstd.routers_shim import _parent_snapshot
        p = sm.create(emp_no="e", workspace="w1")
        sm.save(p, [{"role": "assistant", "content": "y" * 20000}], emp_no="e", workspace="w1")
        block, _ = _parent_snapshot(sm, p, last_fp="")
        assert len(block) <= 8 * 1024 + 200  # 8KB 上限 + 包裹标签余量
