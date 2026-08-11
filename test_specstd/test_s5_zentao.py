"""S5 禅道集成测试（T-053/T-054/T-055/T-056 + 铁律 6）。

覆盖：
- sf_refs_store: 三表 CRUD / 幂等 UNIQUE / workspace 隔离 / 评估状态机
- estimator: FR 拆解 / 恒 suggested 出生 / 确认 / 驳回
- client: 凭据 fail-closed / 未冻结拒绝 / 幂等防重 / 锚点登记 /
          诚实结果拒提单（SKIP/BLOCKED）/ 对账补登记
- REST: 角色闸门 / SPQ zentao_filed / 铁律 6（手动新建计划 404）
全部离线（禅道 API 以 fake 替换）。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402


# ══════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cleanup_ctx():
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离 SQLite 数据文件。"""
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


@pytest.fixture()
def frozen_delta(tmp_path, monkeypatch):
    """构造冻结 delta 目录（FREEZE.yaml + manifest + proposal）+ 注入环境。"""
    import specstd.workspace as wsm
    sf = tmp_path / ".specflow"
    d = sf / "changes" / "delta-test"
    d.mkdir(parents=True)
    (d / "FREEZE.yaml").write_text("frozen: true", encoding="utf-8")
    (d / "delta.manifest.yaml").write_text(
        "delta: delta-test\nsource_interview: IV-001\nbase_spec: s.md\n"
        "operations:\n"
        "  - op: ADDED\n    anchor: FR-002\n"
        "  - op: MODIFIED\n    anchor: FR-001\n    reason: x\n"
        "    decisions: [D-001]\n",
        encoding="utf-8")
    (d / "proposal.md").write_text("# Proposal: 测试\n## 一、为什么做\n背景",
                                   encoding="utf-8")
    monkeypatch.setattr(wsm, "specflow_dir", lambda *a, **k: sf)
    monkeypatch.setenv("SG_ZENTAO_TOKEN", "tok-test")
    return sf


@pytest.fixture()
def fake_zt(monkeypatch):
    """替换 client 命名空间中的禅道客户端（离线）。"""
    calls = {"story_create": 0, "story_update": 0, "bug_create": 0}

    class _Fake:
        def __init__(self, base_url="", token=""):
            pass

        def story_create(self, data):
            calls["story_create"] += 1
            return {"story": {"id": "4821", "title": data.get("title", "")}}

        def story_update(self, story_id, data):
            calls["story_update"] += 1
            return {"story": {"id": story_id}}

        def bug_create(self, data):
            calls["bug_create"] += 1
            return {"bug": {"id": "9917"}}

        def bug_get(self, bug_id):
            return {"bug": {"id": bug_id, "status": "resolved",
                            "title": "t"}}

    monkeypatch.setattr(
        "workbench.backend.services.zentao.client.ZenTaoClient", _Fake)
    return calls


@pytest.fixture()
def run_report(tmp_path, monkeypatch):
    """构造 FAIL 运行报告 + 工作区上下文。"""
    import specstd.workspace as wsm
    ws = type("WS", (), {"root": str(tmp_path)})()
    monkeypatch.setattr(wsm, "get_active_workspace", lambda: ws)
    run_dir = tmp_path / ".specguard" / "reports" / "EX-test001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "cases": [{"id": "IS-RVT-002", "verdict": "FAIL",
                   "message": "断言失败: 列表未刷新",
                   "diffs": ["expected != actual"]}],
    }, ensure_ascii=False), encoding="utf-8")
    return run_dir


def _login(client, emp_no, name=""):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _as_role(client, emp="90000002", roles=("tester",)):
    """登录 admin 设置目标用户角色 + 授权 tdm，返回目标用户 headers。"""
    from services import user_store
    h_admin = _login(client, "90000001")
    h_user = _login(client, emp)
    user_store.set_roles(emp, list(roles), actor="90000001")
    user_store.grant_workspace("tdm", emp, "90000001")
    return {**h_user, "X-SG-Workspace": "tdm"}


# ══════════════════════════════════════════════════════════
# T-056 sf_refs_store 单元测试
# ══════════════════════════════════════════════════════════

class TestRefsStore:
    def test_register_ref_idempotent(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        r1 = sf_refs_store.register_ref(
            "tdm", "zt_story", "4821", "delta", "grid-rule-perf",
            registered_by="tester-1")
        r2 = sf_refs_store.register_ref(
            "tdm", "zt_story", "4821", "delta", "grid-rule-perf",
            registered_by="tester-2")
        assert r1["duplicate"] is False
        assert r2["duplicate"] is True
        assert r2["registered_by"] == "tester-1"  # 返回原行

    def test_register_ref_invalid_type(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        with pytest.raises(ValueError):
            sf_refs_store.register_ref(
                "tdm", "evil", "x", "delta", "y")

    def test_refs_workspace_isolated(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        sf_refs_store.register_ref("tdm", "zt_story", "4821", "delta", "a")
        sf_refs_store.register_ref("other", "zt_story", "4821", "delta", "a")
        assert len(sf_refs_store.list_refs(workspace="tdm")) == 1
        assert len(sf_refs_store.list_refs(workspace="other")) == 1

    def test_job_idem_key_unique(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        j1 = sf_refs_store.create_job(
            "tdm", "story_create", "story:tdm:grid-rule-perf",
            {"delta_id": "grid-rule-perf"}, created_by="u1")
        j2 = sf_refs_store.create_job(
            "tdm", "story_create", "story:tdm:grid-rule-perf",
            {"delta_id": "grid-rule-perf"}, created_by="u2")
        assert j1["duplicate"] is False
        assert j2["duplicate"] is True
        assert j1["job_id"] == j2["job_id"]

    def test_estimate_status_machine(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        est = sf_refs_store.create_estimate(
            "tdm", "grid-rule-perf", [{"item": "x", "points": 2}],
            2, 0.8)
        assert est["status"] == "suggested"
        c = sf_refs_store.update_estimate_status(est["id"], "confirmed",
                                                 actor="pm-1")
        assert c["status"] == "confirmed"
        assert c["confirmed_by"] == "pm-1"
        w = sf_refs_store.update_estimate_status(
            est["id"], "written_back", zt_story="4821")
        assert w["status"] == "written_back"
        assert w["zt_story"] == "4821"
        # confirmed → written_back 后不可再确认
        assert sf_refs_store.update_estimate_status(
            est["id"], "confirmed", actor="pm-2") is None

    def test_estimate_reject(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        est = sf_refs_store.create_estimate("tdm", "d", [], 1, 0.5)
        r = sf_refs_store.update_estimate_status(est["id"], "rejected")
        assert r["status"] == "rejected"


# ══════════════════════════════════════════════════════════
# T-054 estimator 单元测试
# ══════════════════════════════════════════════════════════

class TestEstimator:
    def test_breakdown_and_points(self, db, frozen_delta):
        from workbench.backend.services.zentao import estimator
        est = estimator.estimate_points("tdm", "delta-test")
        # ADDED 2 + MODIFIED 2 + 级联 1 = 5
        assert est["points"] == 5
        assert len(est["breakdown"]) == 3
        assert est["status"] == "suggested"
        assert 0.5 <= est["confidence"] <= 0.95

    def test_estimate_requires_manifest(self, db, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        sf = tmp_path / ".specflow"
        (sf / "changes" / "d").mkdir(parents=True)
        monkeypatch.setattr(wsm, "specflow_dir", lambda *a, **k: sf)
        from workbench.backend.services.zentao import estimator
        with pytest.raises(ValueError):
            estimator.estimate_points("tdm", "d")

    def test_confirm_and_reject(self, db, frozen_delta):
        from workbench.backend.services.zentao import estimator
        est = estimator.estimate_points("tdm", "delta-test")
        c = estimator.confirm_estimate(est["id"], "pm-1")
        assert c["status"] == "confirmed"
        # 已确认不可重复确认
        with pytest.raises(ValueError):
            estimator.confirm_estimate(est["id"], "pm-2")
        est2 = estimator.estimate_points("tdm", "delta-test")
        r = estimator.reject_estimate(est2["id"])
        assert r["status"] == "rejected"


# ══════════════════════════════════════════════════════════
# T-053/T-055 client 单元测试（fake 禅道）
# ══════════════════════════════════════════════════════════

class TestZentaoClient:
    def test_no_credentials_rejected(self, db, frozen_delta, monkeypatch):
        monkeypatch.delenv("SG_ZENTAO_TOKEN", raising=False)
        from workbench.backend.services.zentao import client as zt_client
        with pytest.raises(ValueError, match="凭据"):
            zt_client.create_story_job("tdm", "delta-test", "t", "u1")

    def test_unfrozen_rejected(self, db, fake_zt, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        sf = tmp_path / ".specflow"
        (sf / "changes" / "d").mkdir(parents=True)
        monkeypatch.setattr(wsm, "specflow_dir", lambda *a, **k: sf)
        monkeypatch.setenv("SG_ZENTAO_TOKEN", "tok")
        from workbench.backend.services.zentao import client as zt_client
        with pytest.raises(ValueError, match="未冻结"):
            zt_client.create_story_job("tdm", "d", "t", "u1")

    def test_story_create_idempotent(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        j1 = zt_client.create_story_job("tdm", "delta-test", "故事", "u1")
        j2 = zt_client.create_story_job("tdm", "delta-test", "故事", "u1")
        assert j1["status"] == "succeeded"
        assert j2["duplicate"] is True
        assert j2["job_id"] == j1["job_id"]
        assert fake_zt["story_create"] == 1  # 只调了一次禅道

    def test_story_create_registers_refs(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        from workbench.backend.services.specflow import sf_refs_store
        zt_client.create_story_job("tdm", "delta-test", "故事", "u1")
        refs = sf_refs_store.list_refs(workspace="tdm", ref_type="zt_story")
        linked = {(r["linked_type"], r["linked"]) for r in refs}
        assert ("delta", "delta-test") in linked
        assert ("fr_anchor", "FR-001") in linked
        assert ("fr_anchor", "FR-002") in linked
        assert all(r["ref"] == "4821" for r in refs)

    def test_from_run_skip_rejected(self, db, frozen_delta, fake_zt,
                                    run_report, monkeypatch):
        # 改报告为 SKIP
        run_dir = run_report
        (run_dir / "run.json").write_text(json.dumps({
            "cases": [{"id": "IS-RVT-002", "verdict": "SKIP"}]}), encoding="utf-8")
        from workbench.backend.services.zentao import client as zt_client
        with pytest.raises(ValueError, match="禁止提单"):
            zt_client.create_bug_from_run_job(
                "tdm", "EX-test001", "IS-RVT-002", 2, "", "u1")

    def test_from_run_blocked_rejected(self, db, frozen_delta, fake_zt,
                                       run_report, monkeypatch):
        (run_report / "run.json").write_text(json.dumps({
            "cases": [{"id": "IS-RVT-002", "verdict": "BLOCKED"}]}),
            encoding="utf-8")
        from workbench.backend.services.zentao import client as zt_client
        with pytest.raises(ValueError, match="禁止提单"):
            zt_client.create_bug_from_run_job(
                "tdm", "EX-test001", "IS-RVT-002", 2, "", "u1")

    def test_from_run_fail_ok(self, db, frozen_delta, fake_zt, run_report):
        from workbench.backend.services.zentao import client as zt_client
        from workbench.backend.services.specflow import sf_refs_store
        job = zt_client.create_bug_from_run_job(
            "tdm", "EX-test001", "IS-RVT-002", 2, "落位后名单未刷新", "u1",
            spq_id="SPQ-005")
        assert job["status"] == "succeeded"
        assert job["zt_ref"] == "9917"
        refs = sf_refs_store.list_refs(workspace="tdm", ref_type="zt_bug")
        linked = {(r["linked_type"], r["linked"]) for r in refs}
        assert ("spq", "SPQ-005") in linked
        assert ("scenario", "IS-RVT-002") in linked
        assert ("run", "run#EX-test001") in linked

    def test_manual_bug_same_pipeline(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        job = zt_client.create_bug_manual_job(
            "tdm", "手工 BUG", "步骤 1\n步骤 2", 3, "u1", fr_ref="FR-009")
        assert job["status"] == "succeeded"
        assert job["zt_ref"] == "9917"
        # 重复调用（同 idem_key）幂等
        j2 = zt_client.create_bug_manual_job(
            "tdm", "手工 BUG", "步骤 1\n步骤 2", 3, "u1",
            fr_ref="FR-009", idem_key=job["idem_key"])
        assert j2["duplicate"] is True

    def test_writeback_requires_confirmed(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.specflow import sf_refs_store
        from workbench.backend.services.zentao import client as zt_client
        est = sf_refs_store.create_estimate(
            "tdm", "delta-test", [{"item": "x", "points": 5}], 5, 0.8,
            zt_story="4821")
        with pytest.raises(ValueError, match="产品确认"):
            zt_client.writeback_points_job("tdm", est["id"], "u1")

    def test_writeback_after_confirm(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.specflow import sf_refs_store
        from workbench.backend.services.zentao import client as zt_client
        est = sf_refs_store.create_estimate(
            "tdm", "delta-test", [{"item": "x", "points": 5}], 5, 0.8,
            zt_story="4821")
        sf_refs_store.update_estimate_status(est["id"], "confirmed",
                                             actor="pm-1")
        job = zt_client.writeback_points_job("tdm", est["id"], "pm-1")
        assert job["status"] == "succeeded"
        assert sf_refs_store.get_estimate(est["id"])["status"] == "written_back"
        assert fake_zt["story_update"] == 1

    def test_poll_bug_resolved(self, db, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        r = zt_client.poll_bug("tdm", "9917")
        assert r["status"] == "resolved"
        assert r["regression_suggested"] is True

    def test_reconcile_refs(self, db, frozen_delta, fake_zt):
        """对账：succeeded 缺登记的作业补登记。"""
        from workbench.backend.services.specflow import sf_refs_store
        from workbench.backend.services.zentao import client as zt_client
        # 直接造一个 succeeded 但无登记的作业
        job = sf_refs_store.create_job(
            "tdm", "story_create", "story:tdm:lost",
            {"delta_id": "lost"}, created_by="u1")
        sf_refs_store.update_job(job["job_id"], status="succeeded",
                                 zt_ref="9999")
        fixed = zt_client.reconcile_refs("tdm")
        assert job["job_id"] in fixed
        refs = sf_refs_store.list_refs(workspace="tdm", ref_type="zt_story",
                                       ref="9999")
        assert refs and refs[0]["linked"] == "lost"


# ══════════════════════════════════════════════════════════
# REST 层测试（角色闸门 + SPQ 状态 + 铁律 6）
# ══════════════════════════════════════════════════════════

class TestZentaoRest:
    def test_create_story_403_for_tester(self, client, frozen_delta):
        headers = _as_role(client)
        r = client.post("/api/zentao/stories", headers=headers,
                        json={"delta_id": "delta-test"})
        assert r.status_code == 403

    def test_create_story_unfrozen_403(self, client, fake_zt, tmp_path,
                                       monkeypatch):
        import specstd.workspace as wsm
        sf = tmp_path / ".specflow"
        (sf / "changes" / "d").mkdir(parents=True)
        monkeypatch.setattr(wsm, "specflow_dir", lambda *a, **k: sf)
        monkeypatch.setenv("SG_ZENTAO_TOKEN", "tok")
        headers = _as_role(client, roles=("product",))
        r = client.post("/api/zentao/stories", headers=headers,
                        json={"delta_id": "d"})
        assert r.status_code == 403

    def test_create_story_ok(self, client, frozen_delta, fake_zt):
        headers = _as_role(client, roles=("product",))
        r = client.post("/api/zentao/stories", headers=headers,
                        json={"delta_id": "delta-test", "title": "故事"})
        assert r.status_code == 200, r.text
        assert r.json()["job"]["status"] == "succeeded"
        assert r.json()["job"]["zt_ref"] == "4821"

    def test_estimate_confirm_403_for_tester(self, client, db, frozen_delta):
        from workbench.backend.services.zentao import estimator
        est = estimator.estimate_points("tdm", "delta-test")
        headers = _as_role(client)
        r = client.post(f"/api/zentao/estimates/{est['id']}/confirm",
                        headers=headers, json={"verdict": "confirm"})
        assert r.status_code == 403

    def test_estimate_reject_ok_for_product(self, client, db, frozen_delta):
        """驳回与确认同为拍板动作，仅 product（与 S4 评分 confirm 口径一致）。"""
        from workbench.backend.services.zentao import estimator
        est = estimator.estimate_points("tdm", "delta-test")
        headers = _as_role(client, roles=("product",))
        r = client.post(f"/api/zentao/estimates/{est['id']}/confirm",
                        headers=headers, json={"verdict": "reject"})
        assert r.status_code == 200, r.text
        assert r.json()["estimate"]["status"] == "rejected"

    def test_writeback_403_for_tester(self, client, db, frozen_delta):
        from workbench.backend.services.zentao import estimator
        est = estimator.estimate_points("tdm", "delta-test")
        headers = _as_role(client)
        r = client.post(
            f"/api/zentao/stories/4821/writeback-points",
            headers=headers, json={"estimate_id": est["id"]})
        assert r.status_code == 403

    def test_writeback_full_flow(self, client, frozen_delta, fake_zt):
        """评估 → 产品确认 → 回写（写后状态 written_back）。"""
        headers = _as_role(client, roles=("product",))
        # 评估
        r = client.post("/api/zentao/stories/4821/estimate-points",
                        headers=headers, json={"delta_id": "delta-test"})
        assert r.status_code == 200
        est_id = r.json()["estimate"]["id"]
        assert r.json()["estimate"]["status"] == "suggested"
        # 未确认回写 → 403
        r = client.post("/api/zentao/stories/4821/writeback-points",
                        headers=headers, json={"estimate_id": est_id})
        assert r.status_code == 403
        # 确认
        r = client.post(f"/api/zentao/estimates/{est_id}/confirm",
                        headers=headers, json={"verdict": "confirm"})
        assert r.status_code == 200
        # 回写
        r = client.post("/api/zentao/stories/4821/writeback-points",
                        headers=headers, json={"estimate_id": est_id})
        assert r.status_code == 200, r.text
        assert r.json()["job"]["status"] == "succeeded"

    def test_from_run_skip_403(self, client, frozen_delta, fake_zt,
                               run_report, monkeypatch):
        (run_report / "run.json").write_text(json.dumps({
            "cases": [{"id": "IS-RVT-002", "verdict": "SKIP"}]}),
            encoding="utf-8")
        headers = _as_role(client)
        r = client.post("/api/zentao/bugs/from-run", headers=headers,
                        json={"run_id": "EX-test001",
                              "scenario_id": "IS-RVT-002", "severity": 2})
        assert r.status_code == 403
        assert "禁止提单" in r.json()["detail"]

    def test_from_run_spq_filed(self, client, frozen_delta, fake_zt,
                                run_report, tmp_path, monkeypatch):
        """提单成功后 SPQ 状态推进 zentao_filed（M06 §4.3）。"""
        import routers.zentao as rz
        ledger_root = tmp_path / "sg"
        ledger_file = ledger_root / "feedback" / "ledger.json"
        ledger_file.parent.mkdir(parents=True)
        from feedback.ledger import FeedbackLedger
        ledger = FeedbackLedger(ledger_file)
        entry = ledger.create("SPQ 测试", source="loop_b",
                              scenario_id="IS-RVT-002")
        monkeypatch.setattr(rz, "SG_ROOT", ledger_root)
        headers = _as_role(client)
        r = client.post("/api/zentao/bugs/from-run", headers=headers,
                        json={"run_id": "EX-test001",
                              "scenario_id": "IS-RVT-002", "severity": 2,
                              "spq_id": entry["spq_id"]})
        assert r.status_code == 200, r.text
        assert FeedbackLedger(ledger_file).get(
            entry["spq_id"])["status"] == "zentao_filed"

    def test_refs_register_and_list(self, client):
        headers = _as_role(client, roles=("tester",))
        r = client.post("/api/zentao/refs", headers=headers,
                        json={"type": "pr", "ref": "PR#482",
                              "linked_type": "delta", "linked": "delta-test"})
        assert r.status_code == 200
        r2 = client.get("/api/zentao/refs?linked_type=delta", headers=headers)
        assert r2.status_code == 200
        assert len(r2.json()["refs"]) == 1

    def test_get_job_workspace_isolated(self, client, db):
        from workbench.backend.services.specflow import sf_refs_store
        job = sf_refs_store.create_job(
            "other", "story_create", "story:other:x", {}, created_by="u1")
        headers = _as_role(client)
        r = client.get(f"/api/zentao/jobs/{job['job_id']}", headers=headers)
        assert r.status_code == 404  # 跨工作区不可见


# ══════════════════════════════════════════════════════════
# 铁律 6：手动新建计划无 API
# ══════════════════════════════════════════════════════════

class TestIronRule6:
    def test_plan_manual_create_404(self, client):
        """PUT 不存在的 plan_id → 404（计划只能由 delta 导入生成）。"""
        headers = _as_role(client, roles=("tester",))
        r = client.put("/api/plans/manual-new-plan", headers=headers,
                       json={"name": "手动新建", "description": "",
                             "env": "sit"})
        assert r.status_code == 404
        assert "delta 导入" in r.json()["detail"]


# ══════════════════════════════════════════════════════════
# S5 增补：对话草案 → 禅道故事（飞书文档/多维表格分析链路）
# ══════════════════════════════════════════════════════════

class TestStoryDraftsStore:
    """sf_story_drafts 表 CRUD。"""
    def test_create_and_list(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        d = sf_refs_store.create_story_draft(
            "tdm", "绩效域落位", "系统 SHALL 支持新规则计算。",
            source_refs=[{"type": "feishu_doc", "ref": "Z1Fj",
                          "url": "https://xxx/docx/Z1Fj", "note": "PRD"}],
            created_by="agent:emp1")
        assert d["status"] == "draft"
        assert d["source_refs"][0]["type"] == "feishu_doc"
        rows = sf_refs_store.list_story_drafts(workspace="tdm", status="draft")
        assert len(rows) == 1
        # workspace 隔离
        assert sf_refs_store.list_story_drafts(workspace="other") == []

    def test_mark_created_and_cancel(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        d = sf_refs_store.create_story_draft("tdm", "t", "spec", created_by="u")
        assert sf_refs_store.mark_draft_created(d["id"], "4821")
        assert sf_refs_store.get_story_draft(d["id"])["status"] == "created"
        assert sf_refs_store.get_story_draft(d["id"])["zt_story"] == "4821"
        # created 后不可再 cancel
        assert not sf_refs_store.cancel_story_draft(d["id"])
        d2 = sf_refs_store.create_story_draft("tdm", "t2", "spec2", created_by="u")
        assert sf_refs_store.cancel_story_draft(d2["id"])
        assert sf_refs_store.get_story_draft(d2["id"])["status"] == "cancelled"

    def test_empty_title_rejected(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        with pytest.raises(ValueError):
            sf_refs_store.create_story_draft("tdm", "", "spec", created_by="u")


class TestDraftClient:
    """client.create_story_from_draft_job：幂等/状态机/登记。"""
    def _make_draft(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        return sf_refs_store.create_story_draft(
            "tdm", "绩效域落位", "系统 SHALL 支持新规则计算。\n验收：落位正确。",
            source_refs=[{"type": "feishu_doc", "ref": "Z1Fj", "url": "u"}],
            created_by="agent:emp1", session_id="sess-1")

    def test_from_draft_idempotent(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        draft = self._make_draft(db)
        j1 = zt_client.create_story_from_draft_job("tdm", draft["id"], "u1")
        j2 = zt_client.create_story_from_draft_job("tdm", draft["id"], "u1")
        assert j1["status"] == "succeeded"
        assert j2["duplicate"] is True
        assert fake_zt["story_create"] == 1  # 只建一单

    def test_from_draft_registers_and_marks(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        from workbench.backend.services.specflow import sf_refs_store
        draft = self._make_draft(db)
        zt_client.create_story_from_draft_job("tdm", draft["id"], "u1")
        # 草案状态推进 + 编号回填
        got = sf_refs_store.get_story_draft(draft["id"])
        assert got["status"] == "created"
        assert got["zt_story"] == "4821"
        # 锚点登记：zt_story → interview（来源会话）
        refs = sf_refs_store.list_refs(workspace="tdm", ref_type="zt_story",
                                       linked_type="interview")
        assert refs and refs[0]["linked"] == "sess-1"

    def test_from_draft_rejects_non_draft(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        from workbench.backend.services.specflow import sf_refs_store
        draft = self._make_draft(db)
        sf_refs_store.cancel_story_draft(draft["id"])
        with pytest.raises(ValueError, match="不可重复创建"):
            zt_client.create_story_from_draft_job("tdm", draft["id"], "u1")

    def test_from_draft_not_found(self, db, frozen_delta, fake_zt):
        from workbench.backend.services.zentao import client as zt_client
        with pytest.raises(KeyError):
            zt_client.create_story_from_draft_job("tdm", 99999, "u1")

    def test_from_draft_no_credentials(self, db, monkeypatch, frozen_delta):
        monkeypatch.delenv("SG_ZENTAO_TOKEN", raising=False)
        from workbench.backend.services.zentao import client as zt_client
        from workbench.backend.services.specflow import sf_refs_store
        draft = sf_refs_store.create_story_draft("tdm", "t", "s", created_by="u")
        with pytest.raises(ValueError, match="凭据"):
            zt_client.create_story_from_draft_job("tdm", draft["id"], "u1")


class TestDraftRest:
    """REST：from-draft 角色闸门/草案列表/取消。"""
    def test_from_draft_403_for_tester(self, client, db, frozen_delta):
        from workbench.backend.services.specflow import sf_refs_store
        draft = sf_refs_store.create_story_draft("tdm", "t", "s", created_by="u")
        headers = _as_role(client)
        r = client.post("/api/zentao/stories/from-draft", headers=headers,
                        json={"draft_id": draft["id"]})
        assert r.status_code == 403

    def test_from_draft_full_flow(self, client, db, frozen_delta, fake_zt):
        from workbench.backend.services.specflow import sf_refs_store
        draft = sf_refs_store.create_story_draft(
            "tdm", "绩效域落位", "系统 SHALL 支持新规则计算。",
            source_refs=[{"type": "feishu_base", "ref": "basetoken"}],
            created_by="agent:emp1")
        headers = _as_role(client, roles=("product",))
        r = client.post("/api/zentao/stories/from-draft", headers=headers,
                        json={"draft_id": draft["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["job"]["status"] == "succeeded"
        assert r.json()["job"]["zt_ref"] == "4821"

    def test_story_drafts_list_and_cancel(self, client, db):
        from workbench.backend.services.specflow import sf_refs_store
        draft = sf_refs_store.create_story_draft("tdm", "t", "s", created_by="u")
        headers = _as_role(client, roles=("product",))
        r = client.get("/api/zentao/story-drafts?status=draft", headers=headers)
        assert r.status_code == 200
        assert len(r.json()["drafts"]) == 1
        # 取消
        r2 = client.post(f"/api/zentao/story-drafts/{draft['id']}/cancel",
                         headers=headers)
        assert r2.status_code == 200
        # 已取消不可再取消
        r3 = client.post(f"/api/zentao/story-drafts/{draft['id']}/cancel",
                         headers=headers)
        assert r3.status_code == 403

    def test_frozen_deltas_list(self, client, frozen_delta):
        headers = _as_role(client, roles=("product",))
        r = client.get("/api/zentao/frozen-deltas", headers=headers)
        assert r.status_code == 200
        assert any(d["delta_id"] == "delta-test" for d in r.json()["deltas"])


class TestFeishuFetch:
    """S5 增补：飞书文档/多维表格拉取 handler（mock lark-cli）。"""
    def test_doc_read_ok(self, monkeypatch):
        import mcp_server.tools.feishu_fetch as ff
        monkeypatch.setattr(
            ff, "_run_lark",
            lambda args, timeout=90: {"ok": True, "content": "## 需求\n系统支持盘点"})
        result = asyncio.run(ff._handle_doc_read({"doc": "Z1Fj"}))
        assert "'ok': True" in result[0].text
        assert "盘点" in result[0].text

    def test_doc_read_missing_arg(self, monkeypatch):
        import mcp_server.tools.feishu_fetch as ff
        result = asyncio.run(ff._handle_doc_read({}))
        assert "doc 必填" in result[0].text

    def test_doc_read_permission_denied(self, monkeypatch):
        import mcp_server.tools.feishu_fetch as ff
        monkeypatch.setattr(
            ff, "_run_lark",
            lambda args, timeout=90: (_ for _ in ()).throw(
                ValueError("无权限访问该文档")))
        result = asyncio.run(ff._handle_doc_read({"doc": "Z1Fj"}))
        assert "permission_denied" in result[0].text

    def test_base_query_ok(self, monkeypatch):
        import mcp_server.tools.feishu_fetch as ff
        calls = []

        def fake_run_lark(args, timeout=90):
            calls.append(args)
            if args[1] == "+url-resolve":
                return {"ok": True, "data": {"base_token": "BT1",
                                               "table_id": "TB1"}}
            return {"ok": True, "records": [{"fields": {"标题": "需求A"}}]}

        monkeypatch.setattr(ff, "_run_lark", fake_run_lark)
        result = asyncio.run(ff._handle_base_query({"url": "https://x/base/BT1"}))
        assert "'ok': True" in result[0].text
        assert "'record_count': 1" in result[0].text
        assert "需求A" in result[0].text

    def test_base_query_missing_arg(self, monkeypatch):
        import mcp_server.tools.feishu_fetch as ff
        result = asyncio.run(ff._handle_base_query({}))
        assert "url 必填" in result[0].text

    def test_base_query_no_token(self, monkeypatch):
        import mcp_server.tools.feishu_fetch as ff
        monkeypatch.setattr(
            ff, "_run_lark",
            lambda args, timeout=90: {"ok": True, "data": {}})
        result = asyncio.run(ff._handle_base_query({"url": "https://x/base/xx"}))
        assert "base_token" in result[0].text



# ══════════════════════════════════════════════════════════
# MCP 工具行为（注册集合断言在 test_mcp_server，此处测 handler）
# ══════════════════════════════════════════════════════════

class TestRefsMcpHandlers:
    def test_list_refs_handler(self, db):
        from workbench.backend.services.specflow import sf_refs_store
        sf_refs_store.register_ref("tdm", "zt_story", "4821", "delta",
                                   "grid-rule-perf", registered_by="t")
        from specstd.workspace import set_context_workspace
        set_context_workspace("tdm")
        from mcp_server.tools.specflow_refs import _handle_sf_list_external_refs
        result = asyncio.run(_handle_sf_list_external_refs({}))
        assert "4821" in result[0].text

    def test_register_ref_handler(self, db):
        from specstd.workspace import set_context_workspace
        set_context_workspace("tdm")
        from mcp_server.tools.specflow_refs import _handle_sf_register_external_ref
        result = asyncio.run(_handle_sf_register_external_ref({
            "type": "zt_bug", "ref": "9917", "linked_type": "spq",
            "linked": "SPQ-005"}))
        assert "'registered': True" in result[0].text

    def test_get_job_handler_not_found(self, db):
        from mcp_server.tools.specflow_refs import _handle_sf_get_zentao_job
        result = asyncio.run(_handle_sf_get_zentao_job({"job_id": "ZTJ-none"}))
        assert "'found': False" in result[0].text
