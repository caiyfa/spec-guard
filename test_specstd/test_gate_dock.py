"""对话操作台（GateDock）只读汇总 API 测试（一期）。

覆盖：
- 参数校验：无参 400 / 面试不存在 404 / 跨工作区 404
- session_id 反查面试（sf_interviews UNIQUE(workspace, session_id)）
- 五类卡片聚合：议题确认 / 材料入包 / 评分确认 / 冻结三闸 / 禅道建故事
- 已入包材料不再出卡；已建故事的冻结 delta 不再出卡
- 纯读：重复调用结果一致，不产生写副作用
全部离线。
"""

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

from fastapi.testclient import TestClient  # noqa: E402


# ══════════════════════════════════════════════════════════
# fixtures（隔离 DB + 隔离工作区注册表，模式同 test_specflow_rest）
# ══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cleanup_ctx():
    """防 contextvar 泄漏：REST 请求/测试内的 emp/workspace 注入影响后续测试。"""
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离 SQLite 数据文件（user_store + sf_store 共用；sf_refs_store 复用）。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")

    from services import user_store
    from workbench.backend.services.specflow import sf_store
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    monkeypatch.setattr(sf_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    from services.auth import _TOKEN_CACHE
    _TOKEN_CACHE.clear()
    return db_file


@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    """装配 TestClient（隔离 DB + 注册合规工作区）。"""
    from test_specstd.helpers import create_valid_workspace
    import specstd.workspace as wsm

    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from main import app
    with TestClient(app) as c:
        yield c

    wsm.unregister("tdm")


def _login(client, emp_no, name=""):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _as_tester(client, admin_emp="90000001", emp="90000002"):
    """登录 + 授权 tdm 工作区（gate-dock 为只读端点，tester 即可）。"""
    from services import user_store
    _login(client, admin_emp)
    h_user = _login(client, emp)
    user_store.set_roles(emp, ["tester"], actor=admin_emp)
    user_store.grant_workspace("tdm", emp, admin_emp)
    return {**h_user, "X-SG-Workspace": "tdm"}


# ══════════════════════════════════════════════════════════
# 数据构造 helper（直写服务层/store，与 REST 同库）
# ══════════════════════════════════════════════════════════

def _open_interview(title="九宫格规则调整", session_id="SESS-1",
                    target_delta="", workspace="tdm", emp_no="90000002"):
    """服务层开标（产物落私有区，与 REST 请求上下文一致）。"""
    from specstd.workspace import specflow_dir, set_context_emp_no
    from workbench.backend.services.specflow.interview_service import (
        open_interview)
    set_context_emp_no(emp_no)
    result = open_interview(
        title=title,
        initiator_emp=emp_no,
        initiator_role="product",
        source=[{"type": "prd_section", "ref": "PRD v3.2 §2.7"}],
        target_delta=target_delta,
        session_id=session_id,
        workspace=workspace,
        specflow_base=specflow_dir(),
    )
    return result["iv_id"]


def _mk_material(iv_id, ws="tdm", status="indexed", pack_included=0):
    """直接落库材料（indexed 默认），返回材料行。"""
    from specflow.materials import store as mat_store
    from workbench.backend.services.specflow.sf_store import _connect
    conn = _connect()
    mat_store.init_tables(conn)
    try:
        content = "# 会议纪要\n正文".encode("utf-8")
        m = mat_store.create_material(
            conn, iv_id, ws, "会议纪要.md", "md", len(content), content, "e1")
        mat_store.update_material_status(conn, m["material_id"], status)
        if pack_included:
            mat_store.set_pack_included(conn, m["material_id"], 1)
        conn.commit()
        return mat_store.get_material(conn, m["material_id"])
    finally:
        conn.close()


def _mk_topic(mid, iv_id, ws="tdm", title="绩效阈值调整"):
    from specflow.materials import store as mat_store
    from workbench.backend.services.specflow.sf_store import _connect
    conn = _connect()
    mat_store.init_tables(conn)
    try:
        t = mat_store.add_topic(conn, mid, iv_id, ws, title, "P0",
                                ["FR-001"], "§2.7")
        conn.commit()
        return t
    finally:
        conn.close()


def _mk_score(iv_id, ws="tdm", dimension="coverage"):
    from workbench.backend.services.specflow.decision_service import (
        db_add_score)
    return db_add_score(ws, iv_id, dimension, 80, "machine", "机打证据")


def _freeze_delta(delta_id="delta001", emp_no="90000002"):
    """落 FREEZE.yaml 冻结凭证（与 REST 请求同一 emp 私有区）。"""
    from specstd.workspace import specflow_dir, set_context_emp_no
    set_context_emp_no(emp_no)
    d = specflow_dir() / "changes" / delta_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "FREEZE.yaml").write_text(f"delta: {delta_id}\n", encoding="utf-8")


def _mk_story_job(delta_id="delta001", ws="tdm"):
    """登记一条 succeeded 建故事作业（幂等键含 delta_id）。"""
    from workbench.backend.services.specflow import sf_refs_store
    job = sf_refs_store.create_job(
        ws, "story_create", f"story:{ws}:{delta_id}", {"delta_id": delta_id},
        "e1")
    sf_refs_store.update_job(job["job_id"], status="succeeded",
                             zt_ref="ZT-4821")
    return job


def _kinds(resp):
    return [c["kind"] for c in resp["cards"]]


# ══════════════════════════════════════════════════════════
# 参数校验与上下文反查
# ══════════════════════════════════════════════════════════

class TestGateDockParams:
    def test_require_param(self, client):
        """session_id 与 interview_id 皆空 → 400。"""
        headers = _as_tester(client)
        r = client.get("/api/specflow/gate-dock", headers=headers)
        assert r.status_code == 400

    def test_interview_not_found(self, client):
        headers = _as_tester(client)
        r = client.get("/api/specflow/gate-dock?interview_id=IV-999",
                       headers=headers)
        assert r.status_code == 404

    def test_session_unbound_empty(self, client):
        """会话未绑定面试 → 200 空卡片（前端空态引导，不算错误）。"""
        headers = _as_tester(client)
        r = client.get("/api/specflow/gate-dock?session_id=SESS-X",
                       headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"interview": None, "cards": []}

    def test_session_reverse_lookup(self, client):
        """session_id 反查到面试，返回 interview 摘要。"""
        headers = _as_tester(client)
        iv_id = _open_interview(session_id="SESS-1")
        r = client.get("/api/specflow/gate-dock?session_id=SESS-1",
                       headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["interview"]["iv_id"] == iv_id
        assert body["interview"]["title"] == "九宫格规则调整"
        assert body["cards"] == []

    def test_cross_workspace_404(self, client):
        """interview 属 tdm，other 工作区视角 → 404（隔离，fail-closed）。"""
        headers = _as_tester(client)
        # 同时授予 other 工作区（排除未授权 403 干扰，专验归属隔离 404）
        from services import user_store
        user_store.grant_workspace("other", "90000002", "90000001")
        iv_id = _open_interview()
        r = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                       headers={**headers, "X-SG-Workspace": "other"})
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════
# 五类卡片聚合
# ══════════════════════════════════════════════════════════

class TestGateDockCards:
    def test_topic_confirm_card(self, client):
        """indexed 材料 + 未确认议题 → topic_confirm 卡（L3）。"""
        headers = _as_tester(client)
        iv_id = _open_interview()
        m = _mk_material(iv_id)
        _mk_topic(m["material_id"], iv_id)
        r = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                       headers=headers)
        assert r.status_code == 200, r.text
        kinds = _kinds(r.json())
        assert "topic_confirm" in kinds
        card = next(c for c in r.json()["cards"]
                    if c["kind"] == "topic_confirm")
        assert card["level"] == "L3"
        assert card["payload"]["mid"] == m["material_id"]
        assert len(card["payload"]["topics"]) == 1
        assert card["payload"]["topics"][0]["title"] == "绩效阈值调整"

    def test_material_include_card(self, client):
        """已解析未入包 → material_include 卡；入包后消失。"""
        headers = _as_tester(client)
        iv_id = _open_interview()
        _mk_material(iv_id, status="parsed", pack_included=0)
        r = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                       headers=headers)
        assert "material_include" in _kinds(r.json())

        # 已入包材料不再出卡
        iv_id2 = _open_interview(session_id="SESS-2")
        _mk_material(iv_id2, status="indexed", pack_included=1)
        r2 = client.get(f"/api/specflow/gate-dock?interview_id={iv_id2}",
                        headers=headers)
        assert "material_include" not in _kinds(r2.json())

    def test_score_confirm_card(self, client):
        """suggested 评分 → score_confirm 卡（L2，永远人拍板）。"""
        headers = _as_tester(client)
        iv_id = _open_interview()
        _mk_score(iv_id)
        r = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                       headers=headers)
        kinds = _kinds(r.json())
        assert "score_confirm" in kinds
        card = next(c for c in r.json()["cards"]
                    if c["kind"] == "score_confirm")
        assert card["level"] == "L2"
        assert card["payload"]["scores"][0]["dimension"] == "coverage"

    def test_freeze_gates_card(self, client):
        """target_delta 未冻结 → freeze_gates 卡（三闸状态 + freeze_allowed）。"""
        headers = _as_tester(client)
        iv_id = _open_interview(target_delta="delta001")
        r = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                       headers=headers)
        assert r.status_code == 200, r.text
        card = next(c for c in r.json()["cards"]
                    if c["kind"] == "freeze_gates")
        assert card["level"] == "L2"
        assert card["payload"]["delta_id"] == "delta001"
        assert set(card["payload"]["gates"].keys()) == {
            "product_confirm", "conformance", "p0_zero"}
        assert card["payload"]["freeze_allowed"] is False

    def test_zentao_story_card_after_freeze(self, client):
        """delta 已冻结且未建故事 → zentao_story 卡；建故事后消失。"""
        headers = _as_tester(client)
        iv_id = _open_interview(target_delta="delta001")
        _freeze_delta("delta001")
        r = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                       headers=headers)
        kinds = _kinds(r.json())
        assert "zentao_story" in kinds
        assert "freeze_gates" not in kinds
        card = next(c for c in r.json()["cards"]
                    if c["kind"] == "zentao_story")
        assert card["payload"]["suggested_title"] == "九宫格规则调整"

        # 已有 succeeded 建故事作业 → 不再出卡
        _mk_story_job("delta001")
        r2 = client.get(f"/api/specflow/gate-dock?interview_id={iv_id}",
                        headers=headers)
        assert "zentao_story" not in _kinds(r2.json())

    def test_pure_read_idempotent(self, client):
        """纯读：连续两次调用结果一致（无写副作用）。"""
        headers = _as_tester(client)
        iv_id = _open_interview()
        m = _mk_material(iv_id)
        _mk_topic(m["material_id"], iv_id)
        url = f"/api/specflow/gate-dock?interview_id={iv_id}"
        r1 = client.get(url, headers=headers)
        r2 = client.get(url, headers=headers)
        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json()
