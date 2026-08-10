"""S1 purpose 地基测试：T-010 purpose 会话模型 / T-011 三层交集白名单 /
T-012 purposes 热加载注册表 / T-013 RBAC 多角色用途过滤。

覆盖：
1. SessionManager.create purpose 写入 + _meta.json + save 保留 purpose（不可变）
2. purpose_loader 解析 / 30s TTL 热加载 / visible_purposes 角色并集
3. resolve_tools 三层交集（purpose.tools ∩ rbac_visible_tools；越权拒绝）
4. RBAC 多角色：set_roles / require_role 交集语义
5. REST 端点：POST /sessions（purpose 锁定）、PATCH 含 purpose 409、GET /purposes 过滤
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))


# ══════════════════════════════════════════════════════════
# T-010: purpose 会话模型
# ══════════════════════════════════════════════════════════

class TestPurposeSessionModel:
    def test_create_with_purpose(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(tmp_path / "sessions", workspace="tdm")
        sid = sm.create(emp_no="90024166", workspace="tdm", purpose="test_workbench")
        meta = sm.list_sessions()[0]
        assert meta["purpose"] == "test_workbench"
        assert meta["purpose_locked"] is True
        # _meta.json 落盘
        assert (tmp_path / "sessions" / "tdm" / f"{sid}_meta.json").is_file()

    def test_create_without_purpose_backward_compat(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create(emp_no="90024166")
        meta = sm.list_sessions()[0]
        assert meta["purpose"] == ""
        assert meta["purpose_locked"] is False

    def test_save_preserves_purpose(self, tmp_path):
        """save 覆盖写后 purpose 不可丢失/改写。"""
        from agent.session import SessionManager
        sm = SessionManager(tmp_path / "sessions", workspace="tdm")
        sid = sm.create(emp_no="90024166", workspace="tdm", purpose="requirement_interview")
        sm.save(sid, [{"role": "user", "content": "hi"}], emp_no="90024166", workspace="tdm")
        meta = sm.list_sessions()[0]
        assert meta["purpose"] == "requirement_interview"
        assert meta["purpose_locked"] is True

    def test_purpose_snapshot_whitelist(self, tmp_path):
        """创建时 tool_whitelist/panels 从用途定义快照。"""
        from agent.session import SessionManager
        sm = SessionManager(tmp_path / "sessions", workspace="tdm")
        sid = sm.create(emp_no="90024166", workspace="tdm", purpose="requirement_interview")
        meta = sm.list_sessions()[0]
        assert "read_spec" in meta["tool_whitelist"]
        assert "panels" in meta and len(meta["panels"]) > 0


# ══════════════════════════════════════════════════════════
# T-012: purposes 热加载注册表
# ══════════════════════════════════════════════════════════

class TestPurposeLoader:
    def test_load_existing(self):
        from agent.purpose_loader import load_purpose, clear_cache
        clear_cache()
        p = load_purpose("test_workbench")
        assert p is not None
        assert p.id == "test_workbench"
        assert p.title == "测试工作台"
        assert "tester" in p.roles
        assert "admin" in p.roles

    def test_load_missing(self):
        from agent.purpose_loader import load_purpose
        assert load_purpose("no_such_purpose") is None

    def test_list_two_purposes(self):
        from agent.purpose_loader import list_purposes, clear_cache
        clear_cache()
        ids = {p.id for p in list_purposes()}
        assert ids == {"requirement_interview", "test_workbench"}

    def test_hot_reload_new_file(self, tmp_path, monkeypatch):
        """新增用途文件 30s 内可见（TTL 过期后重新扫描）。"""
        from agent import purpose_loader
        from agent.purpose_loader import list_purposes, clear_cache
        clear_cache()
        # 指向临时目录（隔离测试）
        tmp_purposes = tmp_path / "purposes"
        tmp_purposes.mkdir()
        monkeypatch.setattr(purpose_loader, "PURPOSES_DIR", tmp_purposes)
        clear_cache()
        assert list_purposes() == []
        # 新增文件（无需重启）
        (tmp_purposes / "temp_purpose.md").write_text(
            "---\nid: temp_purpose\ntitle: 临时用途\nroles: [admin]\n---\n正文",
            encoding="utf-8")
        import time
        purpose_loader._CACHE.clear()  # 模拟 TTL 过期
        assert {p.id for p in list_purposes()} == {"temp_purpose"}

    def test_visible_purposes_union(self):
        """角色集合并集：tester+product 双角色用户可见两卡。"""
        from agent.purpose_loader import visible_purposes, clear_cache
        clear_cache()
        # product 角色：仅需求面试
        p_product = {p.id for p in visible_purposes(["product"])}
        assert p_product == {"requirement_interview"}
        # tester+product（一人多用途）：两卡
        p_both = {p.id for p in visible_purposes(["tester", "product"])}
        assert p_both == {"requirement_interview", "test_workbench"}
        # viewer：无任何用途
        assert visible_purposes(["viewer"]) == []


# ══════════════════════════════════════════════════════════
# T-011: 三层交集白名单
# ══════════════════════════════════════════════════════════

class TestResolveTools:
    def test_tester_full_tools(self):
        """tester 角色（全量）∩ 空 purpose.tools（test_workbench）= 全量工具。"""
        from agent.runtime import resolve_tools, ALL_TOOLS
        tools = resolve_tools(purpose_tools=[], user_roles=["tester"])
        assert len(tools) == len(ALL_TOOLS)

    def test_product_intersection(self):
        """product 角色 ∩ requirement_interview.tools = 只读交集。"""
        from agent.runtime import resolve_tools
        from agent.purpose_loader import load_purpose
        pdef = load_purpose("requirement_interview")
        tools = resolve_tools(purpose_tools=list(pdef.tools), user_roles=["product"])
        names = {t.name for t in tools}
        assert "read_spec" in names
        assert "write_draft" not in names          # 写工具不可见
        assert "promote_draft" not in names
        assert "edit_dependency" not in names
        assert "todo_write" in names               # meta 常驻

    def test_viewer_empty(self):
        from agent.runtime import resolve_tools
        assert resolve_tools(purpose_tools=[], user_roles=["viewer"]) == []

    def test_runtime_rejects_whitelist_violation(self, tmp_path, monkeypatch):
        """越权调用确定性拒绝（不执行）+ WARNING 审计留痕。"""
        from agent.runtime import AgentRuntime, resolve_tools
        from agent.purpose_loader import load_purpose
        from agent.llm_client import LLMClient
        pdef = load_purpose("requirement_interview")
        tools = resolve_tools(purpose_tools=list(pdef.tools), user_roles=["product"])
        rt = AgentRuntime(LLMClient(), tools=tools)  # 无 base_url → mock
        # 审计落点：monkeypatch user_store.audit 捕获调用
        import services.user_store as us_mod
        captured = {}
        def fake_audit(emp_no, action, target="", detail="", db_path=None):
            captured.update(emp_no=emp_no, action=action, target=target, detail=detail)
        monkeypatch.setattr(us_mod, "audit", fake_audit)
        result = rt._execute_tool({"function": {"name": "write_draft",
                                                "arguments": "{}"}})
        assert "越权拒绝" in result
        assert "write_draft" not in rt._tool_whitelist
        # WARNING 审计：action=tool_denied，target=越权工具名
        assert captured.get("action") == "tool_denied"
        assert captured.get("target") == "write_draft"


# ══════════════════════════════════════════════════════════
# T-013: RBAC 多角色
# ══════════════════════════════════════════════════════════

class TestRbacMultiRole:
    def test_set_roles_and_parse(self, tmp_path, monkeypatch):
        from services import user_store
        db = tmp_path / "test.db"
        user_store.init_db(db)
        user_store.upsert_user("90024166", "张三", db)
        assert user_store.set_roles("90024166", ["tester", "product"], "90000001", db)
        user = user_store.get_user("90024166", db)
        assert user["roles"] == ["tester", "product"]
        assert user["role"] == "tester"  # 主角色兼容

    def test_set_role_single_compat(self, tmp_path):
        from services import user_store
        db = tmp_path / "test.db"
        user_store.init_db(db)
        user_store.upsert_user("90024167", "李四", db)
        assert user_store.set_role("90024167", "product", "90000001", db)
        user = user_store.get_user("90024167", db)
        assert user["roles"] == ["product"]

    def test_invalid_role_rejected(self, tmp_path):
        from services import user_store
        db = tmp_path / "test.db"
        user_store.init_db(db)
        user_store.upsert_user("90024168", "王五", db)
        with pytest.raises(ValueError):
            user_store.set_roles("90024168", ["superuser"], "90000001", db)

    def test_legacy_role_column_fallback(self, tmp_path):
        """存量单值 role 列（无 roles 列数据）→ 解析为单元素角色集。"""
        from services import user_store
        import sqlite3
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE users (emp_no TEXT PRIMARY KEY, name TEXT, role TEXT,"
                     " default_workspace TEXT, created_at TEXT, last_login_at TEXT)")
        conn.execute("INSERT INTO users VALUES ('90024169','赵六','tester','','','')")
        conn.commit()
        conn.close()
        user = user_store.get_user("90024169", db)
        assert user["roles"] == ["tester"]
        assert user["role"] == "tester"


# ══════════════════════════════════════════════════════════
# T-010/T-013: REST 端点（multiuser 风格）
# ══════════════════════════════════════════════════════════

class TestPurposeEndpoints:
    """POST /sessions purpose 锁定 + PATCH 409 + GET /purposes 过滤。"""

    @pytest.fixture()
    def client(self):
        sys.path.insert(0, str(SG_ROOT / "workbench" / "backend"))
        try:
            from main import app
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                yield c
        finally:
            sys.path.pop(0)

    def _login(self, client, emp_no: str, name: str = "") -> dict:
        r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name or emp_no})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_create_session_with_purpose(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        h = self._login(client, "90024166")
        r = client.post("/api/agent/sessions",
                        json={"purpose": "test_workbench", "workspace": "tdm"},
                        headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["session"]["purpose"] == "test_workbench"
        assert data["session"]["purpose_locked"] is True

    def test_create_session_invalid_purpose_403(self, client, monkeypatch):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        h = self._login(client, "90024166")
        r = client.post("/api/agent/sessions",
                        json={"purpose": "no_such", "workspace": "tdm"},
                        headers=h)
        assert r.status_code == 403

    def test_create_session_viewer_denied(self, client, monkeypatch):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        h = self._login(client, "90024170")  # viewer 角色
        r = client.post("/api/agent/sessions",
                        json={"purpose": "test_workbench", "workspace": "tdm"},
                        headers=h)
        assert r.status_code == 403  # require_role 拦截（viewer 不在 admin/tester/product）

    def test_patch_purpose_409(self, client, monkeypatch):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        h = self._login(client, "90024166")
        r = client.post("/api/agent/sessions",
                        json={"purpose": "test_workbench", "workspace": "tdm"},
                        headers=h)
        sid = r.json()["session_id"]
        r2 = client.patch(f"/api/agent/sessions/{sid}",
                          json={"purpose": "requirement_interview"},
                          headers=h)
        assert r2.status_code == 409

    def test_purposes_filtered_by_role(self, client, monkeypatch):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        # product 角色（用 set_roles 预置）
        from services import user_store
        user_store.upsert_user("90024171", "产品经理")
        user_store.set_roles("90024171", ["product"], "90000001")
        h = self._login(client, "90024171")
        r = client.get("/api/agent/purposes", headers=h)
        assert r.status_code == 200
        ids = {p["id"] for p in r.json()["purposes"]}
        assert ids == {"requirement_interview"}

    def test_purposes_multi_role_two_cards(self, client, monkeypatch):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        from services import user_store
        user_store.upsert_user("90024172", "双角色")
        user_store.set_roles("90024172", ["tester", "product"], "90000001")
        h = self._login(client, "90024172")
        r = client.get("/api/agent/purposes", headers=h)
        ids = {p["id"] for p in r.json()["purposes"]}
        assert ids == {"requirement_interview", "test_workbench"}

    def test_list_sessions_purpose_filter(self, client, monkeypatch):
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        h = self._login(client, "90024166")
        client.post("/api/agent/sessions",
                    json={"purpose": "test_workbench", "workspace": "tdm"}, headers=h)
        client.post("/api/agent/sessions",
                    json={"purpose": "requirement_interview", "workspace": "tdm"}, headers=h)
        r = client.get("/api/agent/sessions?purpose=requirement_interview", headers=h)
        sessions = r.json()["sessions"]
        assert len(sessions) >= 1
        assert all(s["purpose"] == "requirement_interview" for s in sessions)
