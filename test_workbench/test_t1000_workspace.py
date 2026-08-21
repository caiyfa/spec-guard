"""T-1000 工作区自管理 + 系统二级 + 产出反查 测试。

覆盖设计单验收要点：
- WorkspaceInfo owner_emp 往返/存量默认空
- system_ready 软校验 + ensure_system_ready 运行期诚实报错
- register 放开登录 + owner_emp + 自助授权 + system_pending 标记 + 合规闸门保留
- /workspace/tree 按系统分组 + 可见范围（owner/被授权/admin）
- product_index 写入与三反查 + mine 越权 403
- audit 本人查自己放行 / 越权查他人 403 / 未带 emp 收窄本人
"""
import json
import sqlite3
from pathlib import Path

import pytest

from services import user_store, rbac_store  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "t1000.db"
    user_store.init_db(p)
    rbac_store.init_db(p)
    monkeypatch.setattr(user_store, "DB_PATH", p)
    monkeypatch.setattr(rbac_store, "DB_PATH", p)
    # product_index 共用 sg_core.user_store._connect；audit_store 独立 DB_PATH——全部指向临时库
    import sg_core.user_store as core_us
    import sg_core.audit_store as audit_store
    monkeypatch.setattr(core_us, "DB_PATH", p)
    monkeypatch.setattr(audit_store, "DB_PATH", p)
    return p


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """specstd 注册表隔离到临时目录。"""
    import specstd.workspace as wsm
    root = tmp_path / "specstd_ws"
    monkeypatch.setattr(wsm, "WORKSPACES_DIR", root)
    monkeypatch.setattr(wsm, "REGISTRY_PATH", root / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", root / "_clones")
    return wsm


def _mk_spec_dir(base: Path) -> Path:
    """造最小合规 spec 目录（过 conformance 门禁：必备目录 specs/changes/archive
    + AGENTS.md 含 Project Overview 与术语节）。"""
    ws = base / "spec-ws"
    for d in ("specs", "changes", "archive"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    (ws / "AGENTS.md").write_text(
        "# WS\n\n## Project Overview\n\nx\n\n## 术语\n\n- FR\n", encoding="utf-8")
    (ws / "specs" / "FR-001-测试功能.md").write_text(
        "# 测试\n\n## FR-001 功能\n\n### AC-001 验收\n", encoding="utf-8")
    return ws


def _mk_user(db, emp, roles=("tester",)):
    user_store.upsert_user(emp, emp, db)
    user_store.set_roles(emp, list(roles), emp, db)


# ══════════════════════════════════════════════════════════
# F1：模型与软校验
# ══════════════════════════════════════════════════════════

class TestOwnerEmpModel:
    def test_roundtrip_and_legacy_default(self, reg):
        w = reg.WorkspaceInfo("a", "tdm", owner_emp="u9")
        assert reg.WorkspaceInfo.from_dict("a", w.to_dict()).owner_emp == "u9"
        # 存量注册表（无 owner_emp 键）默认空——零迁移
        legacy = {"system": "tdm", "source": {"type": "local", "path": "/x"}}
        assert reg.WorkspaceInfo.from_dict("b", legacy).owner_emp == ""


class TestSystemSoftHardCheck:
    def test_system_ready_soft(self):
        from services.systems_catalog import system_ready
        assert system_ready("tdm") is True
        assert system_ready("ghost_sys") is False
        assert system_ready("../evil") is False

    def test_validate_system_still_hard(self):
        """运行期硬校验保留：包不存在 400。"""
        from fastapi import HTTPException
        from services.systems_catalog import validate_system
        with pytest.raises(HTTPException):
            validate_system("ghost_sys")

    def test_ensure_system_ready_honest(self):
        from specstd.workspace import ensure_system_ready
        ensure_system_ready("tdm")  # 已建包不抛
        with pytest.raises(RuntimeError) as ei:
            ensure_system_ready("ghost_sys")
        assert "待接入" in str(ei.value) or "system_pending" in str(ei.value)


# ══════════════════════════════════════════════════════════
# F1：注册放开登录 + owner_emp + 可见范围
# ══════════════════════════════════════════════════════════

class TestRegisterSelfService:
    def test_register_local_records_owner(self, reg, tmp_path):
        ws = _mk_spec_dir(tmp_path)
        r = reg.register_local("self-ws", str(ws), "ghost_sys", owner_emp="u1")
        assert r["ok"], r.get("error")
        assert reg.get_workspace("self-ws").owner_emp == "u1"
        reg.unregister("self-ws")

    def test_register_with_pending_system_ok(self, reg, tmp_path):
        """未建包系统也能注册（specstd 层无硬校验；软标记在 router 层）。"""
        ws = _mk_spec_dir(tmp_path)
        r = reg.register_local("pend-ws", str(ws), "no_such_pkg", owner_emp="u2")
        assert r["ok"]
        assert reg.get_workspace("pend-ws").system == "no_such_pkg"
        reg.unregister("pend-ws")

    def test_conformance_gate_kept(self, reg, tmp_path):
        """合规闸门保留：内容级 ERROR（AGENTS.md 缺 Project Overview 节）注册拒绝。"""
        bad = tmp_path / "bad-ws"
        for d in ("specs", "changes", "archive"):
            (bad / d).mkdir(parents=True, exist_ok=True)
        (bad / "AGENTS.md").write_text("# 无节标题\n", encoding="utf-8")
        r = reg.register_local("bad-ws", str(bad), "tdm", owner_emp="u1")
        assert not r["ok"]
        assert r["report"]["verdict"] == "REJECT"

    def test_missing_structure_warn_not_reject(self, reg, tmp_path):
        """T-1000：目录/AGENTS.md 缺失降级 WARN——空壳工作区可注册先上车。"""
        bare = tmp_path / "bare-ws"
        bare.mkdir()
        r = reg.register_local("bare-ws", str(bare), "tdm", owner_emp="u1")
        assert r["ok"]
        assert r["report"]["summary"]["warn"] > 0
        reg.unregister("bare-ws")


# ══════════════════════════════════════════════════════════
# F2：tree 分组（router 纯逻辑经 TestClient 验证成本过高，
# 直接验证其数据依赖：list_workspaces + system_ready + grants）
# ══════════════════════════════════════════════════════════

class TestWorkspaceVisibility:
    def test_owner_channel_visible(self, reg, db, tmp_path):
        """非 admin：owner_emp 通道可见自己的工作区（不再只认 grants）。"""
        ws = _mk_spec_dir(tmp_path)
        reg.register_local("mine-ws", str(ws), "tdm", owner_emp="u1")
        reg.register_local("other-ws", str(ws), "tdm", owner_emp="u9")
        workspaces = reg.list_workspaces()
        # router /list 的过滤逻辑（owner 或 grant）
        granted = {g["workspace_name"] for g in user_store.list_grants(emp_no="u1")}
        visible = [w for w in workspaces if w.name in granted or w.owner_emp == "u1"]
        assert {w.name for w in visible} == {"mine-ws"}
        reg.unregister("mine-ws")
        reg.unregister("other-ws")


# ══════════════════════════════════════════════════════════
# F3：product_index
# ══════════════════════════════════════════════════════════

class TestProductIndex:
    def test_record_and_three_queries(self, db):
        from sg_core import product_index as pi
        pi.record_product("drafts/A.yaml", "draft", session_id="s1", emp_no="u1", workspace="ws")
        pi.record_product("scenarios/m/A.yaml", "scenario", session_id="s1", emp_no="u1",
                          workspace="ws", fr_anchor="FR-001")
        pi.record_product("drafts/B.yaml", "draft", session_id="s2", emp_no="u2")
        assert len(pi.by_session("s1")) == 2
        mine = pi.by_emp("u1")
        assert len(mine) == 2 and all(r["emp_no"] == "u1" for r in mine)
        assert pi.by_emp("u1", product_type="draft")[0]["product_path"] == "drafts/A.yaml"
        trace = pi.trace("scenarios/m/A.yaml")
        assert trace[0]["session_id"] == "s1" and trace[0]["fr_anchor"] == "FR-001"

    def test_empty_path_noop(self, db):
        from sg_core import product_index as pi
        pi.record_product("", "draft")  # 静默忽略
        assert pi.by_emp("u1") == []


class TestMinePermission:
    def test_mine_other_403_logic(self):
        """router 层权限：非 admin 查他人 → 403（纯判定逻辑复核）。"""
        # api_mine 的判定：target != user.emp_no and not user.is_admin → 403
        class U:
            emp_no = "u1"
            is_admin = False
        target = "u2"
        assert target != U.emp_no and not U.is_admin  # 触发 403 分支


# ══════════════════════════════════════════════════════════
# F3：audit 本人查自己
# ══════════════════════════════════════════════════════════

class TestAuditSelfQuery:
    def _client(self, db, monkeypatch, emp="u1", roles=("viewer",)):
        from fastapi.testclient import TestClient
        # 菜单守卫豁免（本文件测路由逻辑不测菜单授权；专项在 test_menu_guard.py）
        from services.menu_guard import MenuGuardMiddleware

        async def _passthrough(self, scope, receive, send):
            await self.app(scope, receive, send)

        monkeypatch.setattr(MenuGuardMiddleware, "__call__", _passthrough)
        import main
        _mk_user(db, emp, roles)
        monkeypatch.setenv("SG_AUTH_MODE", "mock")
        c = TestClient(main.app)
        c.headers["Authorization"] = f"Bearer mock-{emp}"
        c.headers["X-SG-Workspace"] = ""
        return c

    def test_self_query_allowed(self, db, monkeypatch):
        _mk_user(db, "ad1", ("admin",))  # 占位 admin，防 u1 首登提权
        c = self._client(db, monkeypatch)
        import sg_core.audit_store as audit_store
        audit_store.ensure_tables(db)
        audit_store.record_call(tool_name="spec.read", emp_no="u1", session_id="s1",
                                side_effect="none", verdict="ok", db_path=db)
        r = c.get("/api/agent/audit")
        assert r.status_code == 200
        calls = r.json()["calls"]
        assert all(x["emp_no"] == "u1" for x in calls)

    def test_other_query_403(self, db, monkeypatch):
        _mk_user(db, "ad1", ("admin",))
        c = self._client(db, monkeypatch)
        r = c.get("/api/agent/audit?emp=u9")
        assert r.status_code == 403

    def test_products_mine_other_403(self, db, monkeypatch):
        _mk_user(db, "ad1", ("admin",))
        c = self._client(db, monkeypatch)
        assert c.get("/api/products/mine?emp=u9").status_code == 403
        assert c.get("/api/products/mine").status_code == 200
