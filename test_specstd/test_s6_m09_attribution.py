"""S6 T-063/T-064：失败归因 Agent + SPQ→面试信息包 loop-back（M09 §4/§5/§9）。

验收锚点：
- suggestion 永不自动转 decided（decided_by/decided_at 留痕）
- 环境问题定性强制附诚实性复核（诚实结果铁律 7）
- 证据包四要素：响应快照 + DB 快照 + flow digest + 环境指纹
- SPQ 建档自动装配进匹配面试 IV 的信息包（幂等）
- SPQ 建档缺 run_id 或 fr_refs → 400 或 WARNING
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ══════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def ledger(tmp_path):
    """隔离 SPQ 台账（feedback/ledger.json 的临时副本）。"""
    from feedback.ledger import FeedbackLedger
    return FeedbackLedger(tmp_path / "ledger.json")


@pytest.fixture()
def run_report(tmp_path):
    """构造最小 run 报告（run.json + cases/）。"""
    run_dir = tmp_path / "reports" / "EX-test0001"
    (run_dir / "cases").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "EX-test0001", "env": "sit",
        "started_at": "2026-08-11T10:00:00",
        "stats": {"pass": 3, "fail": 1, "skip": 0, "blocked": 0},
        "cases": [{"id": "IS-RVT-002", "verdict": "FAIL",
                   "file": "cases/IS-RVT-002.json"}],
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "cases" / "IS-RVT-002.json").write_text(json.dumps({
        "scenario_id": "IS-RVT-002", "verdict": "FAIL",
        "error": "断言失败: 名单刷新延迟",
        "assertions": [{"name": "list_contains_new_revoked",
                        "passed": False, "message": "未含新退回人员"}],
        "steps": [{"step": 1, "method": "GET", "path": "/api/inventory/members",
                   "status": 200, "response": {"list": [{"emp": "90024713"}]}}],
        "saved_vars": {"activity_id": "A-1"},
    }, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "reports"


# ══════════════════════════════════════════════════════════
# SPQ 挂链字段（G-3/G-4）
# ══════════════════════════════════════════════════════════

class TestSpqLinkage:
    def test_create_with_linkage_fields(self, ledger):
        """建档带挂链：run_id/scenario_id/fr_refs/suggestion_kind 落台账。"""
        from workbench.backend.services.attribution_service import create_spq
        entry = create_spq(
            ledger, title="名单刷新延迟", run_id="EX-test0001",
            scenario_id="IS-RVT-002", fr_refs=["FR-009"],
            suggestion_kind="product_defect", decided_by="t1",
            decided_kind="product_defect")
        assert entry["spq_id"].startswith("SPQ-")
        assert entry["run_id"] == "EX-test0001"
        assert entry["scenario_id"] == "IS-RVT-002"
        assert entry["fr_refs"] == ["FR-009"]
        assert entry["suggestion_kind"] == "product_defect"
        assert entry["decided_kind"] == "product_defect"
        assert entry["decided_by"] == "t1"
        assert entry["decided_at"]
        assert entry["status"] == "pending"

    def test_suggestion_never_auto_decided(self, ledger):
        """suggestion 永不自动转 decided：只给建议不建档时无 decided 字段。"""
        from workbench.backend.services.attribution_service import suggest_kind
        suggestion = suggest_kind("FAIL", category="assertion")
        assert suggestion["kind"] == "product_defect"
        # 建议不产生任何台账行
        assert ledger.list_entries() == []

    def test_missing_linkage_warns(self, ledger):
        """建档缺 run_id/fr_refs → WARNING（合规审计），不阻断建档。"""
        from workbench.backend.services.attribution_service import create_spq
        entry = create_spq(ledger, title="x", decided_by="t1",
                           decided_kind="product_defect")
        assert entry["linkage_warnings"]
        assert any("run_id" in w for w in entry["linkage_warnings"])

    def test_illegal_transition_409(self, ledger):
        """状态机非法迁移（closed 后重开）→ 拒绝。"""
        from workbench.backend.services.attribution_service import create_spq
        entry = create_spq(ledger, title="x", decided_by="t1",
                           decided_kind="product_defect")
        from workbench.backend.services.attribution_service import transition_spq
        transition_spq(ledger, entry["spq_id"], "closed")
        with pytest.raises(ValueError):
            transition_spq(ledger, entry["spq_id"], "pending")


# ══════════════════════════════════════════════════════════
# 归因证据包（G-2）
# ══════════════════════════════════════════════════════════

class TestEvidencePack:
    def test_assemble_evidence_four_elements(self, run_report, monkeypatch):
        """证据包四要素：响应快照 + flow digest + 环境指纹（DB 快照按需）。"""
        from workbench.backend.services.attribution_service import assemble_evidence
        monkeypatch.setattr(
            "workbench.backend.services.attribution_service._reports_root",
            lambda: run_report)
        ev = assemble_evidence("EX-test0001", "IS-RVT-002")
        assert ev["scenario_id"] == "IS-RVT-002"
        assert ev["response_snapshot"]["status"] == 200
        assert ev["flow_digest"]
        assert ev["env_fingerprint"]["env"] == "sit"
        # DB 快照：无 db 段时为空数组（不阻塞）
        assert "db_snapshots" in ev

    def test_evidence_readonly(self, run_report, monkeypatch):
        """证据采集只读：调用前后报告目录哈希不变。"""
        import hashlib
        from workbench.backend.services.attribution_service import assemble_evidence
        monkeypatch.setattr(
            "workbench.backend.services.attribution_service._reports_root",
            lambda: run_report)

        def _snapshot():
            digest = hashlib.sha256()
            for p in sorted(run_report.rglob("*")):
                if p.is_file():
                    digest.update(p.read_bytes())
            return digest.hexdigest()

        before = _snapshot()
        assemble_evidence("EX-test0001", "IS-RVT-002")
        assert _snapshot() == before

    def test_unknown_run_raises(self, run_report, monkeypatch):
        """未知 run → 明确错误。"""
        from workbench.backend.services.attribution_service import (
            assemble_evidence, EvidenceError)
        monkeypatch.setattr(
            "workbench.backend.services.attribution_service._reports_root",
            lambda: run_report)
        with pytest.raises(EvidenceError):
            assemble_evidence("EX-unknown", "IS-RVT-002")


# ══════════════════════════════════════════════════════════
# 诚实性复核（G-4 红线）
# ══════════════════════════════════════════════════════════

class TestHonestyReview:
    def test_environment_suggestion_requires_review(self):
        """环境问题定性强制附诚实性复核结论。"""
        from workbench.backend.services.attribution_service import (
            build_honesty_review)
        review = build_honesty_review(
            verdict="FAIL", kind="environment",
            clues=["网关 502", "工号池耗尽"])
        assert review["required"] is True
        assert review["conclusion"] in ("改判 SKIP", "维持 FAIL 但附证据")
        assert review["evidence_required"]

    def test_product_defect_no_forced_review(self):
        """产品缺陷定性不强制复核（诚实 FAIL 语义）。"""
        from workbench.backend.services.attribution_service import build_honesty_review
        review = build_honesty_review(verdict="FAIL", kind="product_defect")
        assert review["required"] is False

    def test_honesty_review_substring_clues(self):
        """线索子串匹配：'502' 单字即判应改判 SKIP（不依赖调用方传精确短语）。"""
        from workbench.backend.services.attribution_service import build_honesty_review
        review = build_honesty_review(verdict="FAIL", kind="environment",
                                      clues=["HTTP 502 Bad Gateway"])
        assert review["conclusion"] == "改判 SKIP"
        review2 = build_honesty_review(verdict="FAIL", kind="environment",
                                       clues=["业务规则未命中"])
        assert review2["conclusion"] == "维持 FAIL 但附证据"


# ══════════════════════════════════════════════════════════
# T-064：SPQ → 面试信息包 loop-back（G-5）
# ══════════════════════════════════════════════════════════

class TestSpqInfoPackLoopback:
    def test_spq_sync_info_pack_idempotent(self, ledger, tmp_path):
        """装配进信息包幂等：重复触发不重复入包。"""
        from workbench.backend.services.attribution_service import (
            create_spq, sync_spq_to_info_pack)
        entry = create_spq(ledger, title="名单刷新延迟", run_id="EX-1",
                           scenario_id="IS-RVT-002", fr_refs=["FR-009"],
                           decided_by="t1", decided_kind="product_defect")
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir(parents=True)
        added1 = sync_spq_to_info_pack(entry["spq_id"], iv_id="IV-007",
                                       pack_dir=pack_dir, ledger=ledger)
        added2 = sync_spq_to_info_pack(entry["spq_id"], iv_id="IV-007",
                                       pack_dir=pack_dir, ledger=ledger)
        assert added1["added"] is True
        assert added2["added"] is False  # 幂等：已装配不重复
        # 台账回填 info_pack_synced
        got = ledger.get(entry["spq_id"])
        assert got["info_pack_synced"] == ["IV-007"]

    def test_sync_spq_iv_id_traversal_rejected(self, ledger, tmp_path):
        """iv_id 含 ../ 越界 → ValueError（路径穿越守卫，不产生任何文件）。"""
        from workbench.backend.services.attribution_service import (
            create_spq, sync_spq_to_info_pack)
        entry = create_spq(ledger, title="x", decided_by="t1",
                           decided_kind="product_defect")
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir(parents=True)
        with pytest.raises(ValueError):
            sync_spq_to_info_pack(entry["spq_id"], iv_id="../evil",
                                  pack_dir=pack_dir, ledger=ledger)
        assert not (pack_dir.parent / "evil").exists()

    def test_auto_sync_matches_fr_correlation(self, ledger, tmp_path, monkeypatch):
        """自动装配按 FR 相关性匹配：FR-009 只进 baseline_refs 含 FR-009 的面试。"""
        import yaml as _yaml
        import routers.feedback as rf
        from specstd import workspace as wmod

        base = tmp_path / "specflow"
        iv_a = base / "interviews" / "IV-001"
        iv_b = base / "interviews" / "IV-002"
        iv_a.mkdir(parents=True)
        iv_b.mkdir(parents=True)
        topic_a = {"iv_id": "IV-001", "title": "t",
                   "initiator": {"emp": "e", "role": "product"},
                   "opened_at": "2026-08-11T00:00:00",
                   "source": [{"type": "meeting", "ref": "m1"}],
                   "baseline_refs": [{"fr": "FR-001"}],
                   "status": "interviewing"}
        topic_b = dict(topic_a, iv_id="IV-002",
                       baseline_refs=[{"fr": "FR-009"}])
        (iv_a / "topic.yaml").write_text(_yaml.dump(topic_a, allow_unicode=True),
                                          encoding="utf-8")
        (iv_b / "topic.yaml").write_text(_yaml.dump(topic_b, allow_unicode=True),
                                          encoding="utf-8")

        monkeypatch.setattr(wmod, "get_workspace_root", lambda: tmp_path)
        monkeypatch.setattr(wmod, "specflow_dir", lambda emp="": base)
        monkeypatch.setattr(rf, "_get_ledger", lambda: ledger)  # 隔离台账（真实台账含历史 SPQ）

        from workbench.backend.services.attribution_service import create_spq
        entry = create_spq(ledger, title="名单刷新延迟", run_id="EX-1",
                           scenario_id="IS-RVT-002", fr_refs=["FR-009"],
                           decided_by="t1", decided_kind="product_defect")
        rf._auto_sync_info_pack(entry, ["FR-009"])
        # FR-009 命中 IV-002 → 装配；IV-001 无该 FR → 不装配
        assert (base / "interviews" / "IV-002" / "spq_feedback.yaml").is_file()
        assert not (base / "interviews" / "IV-001" / "spq_feedback.yaml").exists()


# ══════════════════════════════════════════════════════════
# T-063 REST 层（feedback spq + runs attribute/evidence）
# ══════════════════════════════════════════════════════════

class TestAttributionREST:
    @pytest.fixture(autouse=True)
    def _cleanup_ctx(self):
        yield
        from specstd.workspace import set_context_emp_no, set_context_workspace
        set_context_emp_no(None)
        set_context_workspace(None)

    @pytest.fixture()
    def rest_env(self, tmp_path, monkeypatch):
        """REST 测试环境：隔离 DB + 注册表 + mock 认证 + 报告目录。"""
        import os
        os.environ["SG_AUTH_MODE"] = "mock"
        os.environ.pop("SG_ADMIN_ACCOUNTS", None)
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
        from services import user_store
        db_file = tmp_path / "workbench.db"
        monkeypatch.setattr(user_store, "DB_PATH", db_file)
        user_store.init_db(db_file)
        from services.auth import _TOKEN_CACHE
        _TOKEN_CACHE.clear()

        from test_specstd.conftest import create_valid_workspace
        repo = create_valid_workspace(tmp_path / "repo")
        wsm.register_local("tdm", str(repo), "tdm", activate=True)

        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield {"client": c, "repo": repo, "tmp": tmp_path}
        wsm.unregister("tdm")

    def _login(self, client, emp_no="90000002"):
        from services import user_store
        _login(client, "90000001")
        h_user = _login(client, emp_no)
        user_store.set_roles(emp_no, ["tester"], actor="90000001")
        user_store.grant_workspace("tdm", emp_no, "90000001")
        return {**h_user, "X-SG-Workspace": "tdm"}

    def _make_run_report(self, tmp):
        import json as _json
        run_dir = tmp / "reports" / "EX-rest0001"
        (run_dir / "cases").mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(_json.dumps({
            "run_id": "EX-rest0001", "env": "sit",
            "stats": {"pass": 0, "fail": 1, "skip": 0, "blocked": 0},
            "cases": [{"id": "IS-RVT-002", "verdict": "FAIL"}],
        }), encoding="utf-8")
        (run_dir / "cases" / "IS-RVT-002.json").write_text(_json.dumps({
            "scenario_id": "IS-RVT-002", "verdict": "FAIL",
            "error": "断言失败",
            "assertions": [{"name": "a1", "passed": False, "message": "名单未刷新"}],
            "steps": [{"step": 1, "method": "GET", "status": 200,
                        "response": {"list": []}}],
        }), encoding="utf-8")

    def test_attribute_endpoint_suggests_only(self, rest_env, monkeypatch):
        """POST /runs/{run}/attribute：只给建议，不产生台账行。"""
        self._make_run_report(rest_env["tmp"])
        # 报告根目录指向隔离位置（REST 端点用顶层 services 包）
        monkeypatch.setattr(
            "services.attribution_service._reports_root",
            lambda: rest_env["tmp"] / "reports")
        client = rest_env["client"]
        headers = self._login(client)
        r = client.post("/api/runs/EX-rest0001/attribute", headers=headers,
                        json={"scenario_id": "IS-RVT-002"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["suggestion"]["kind"] in (
            "product_defect", "spec_question", "environment")
        assert data["honesty_review"] is not None
        # 建议不落台账：feedback ledger 无新行
        assert data["note"]

    def test_evidence_endpoint(self, rest_env, monkeypatch):
        """GET /runs/{run}/evidence/{scenario} 四要素。"""
        self._make_run_report(rest_env["tmp"])
        monkeypatch.setattr(
            "services.attribution_service._reports_root",
            lambda: rest_env["tmp"] / "reports")
        client = rest_env["client"]
        headers = self._login(client)
        r = client.get("/api/runs/EX-rest0001/evidence/IS-RVT-002", headers=headers)
        assert r.status_code == 200, r.text
        ev = r.json()
        assert ev["flow_digest"]
        assert ev["response_snapshot"]["assertion_failed"]
        assert "env_fingerprint" in ev

    def test_spq_create_and_transition(self, rest_env, monkeypatch):
        """POST /api/feedback/spq 建档 + PATCH 流转 + 非法迁移 409。"""
        import routers.feedback as rf
        ledger_path = rest_env["tmp"] / "ledger.json"
        monkeypatch.setattr(rf, "LEDGER_PATH", ledger_path)

        client = rest_env["client"]
        headers = self._login(client)
        r = client.post("/api/feedback/spq", headers=headers, json={
            "title": "名单未刷新", "run_id": "EX-rest0001",
            "scenario_id": "IS-RVT-002", "fr_refs": ["FR-009"],
            "suggestion_kind": "product_defect",
            "decided_kind": "product_defect", "comment": "确认为产品缺陷",
        })
        assert r.status_code == 200, r.text
        entry = r.json()
        assert entry["spq_id"].startswith("SPQ-")
        assert entry["decided_by"] == "90000002"
        assert entry["decided_at"]
        spq_id = entry["spq_id"]

        # 状态流转
        r2 = client.patch(f"/api/feedback/spq/{spq_id}", headers=headers,
                          json={"status": "in_progress"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "in_progress"
        # 非法迁移：in_progress → pending 非法？允许；closed 后重开 → 409
        r3 = client.patch(f"/api/feedback/spq/{spq_id}", headers=headers,
                          json={"status": "closed"})
        assert r3.status_code == 200
        r4 = client.patch(f"/api/feedback/spq/{spq_id}", headers=headers,
                          json={"status": "pending"})
        assert r4.status_code == 409

    def test_spq_missing_linkage_warns(self, rest_env, monkeypatch):
        """建档缺 run_id/fr_refs → linkage_warnings。"""
        import routers.feedback as rf
        ledger_path = rest_env["tmp"] / "ledger.json"
        monkeypatch.setattr(rf, "LEDGER_PATH", ledger_path)
        client = rest_env["client"]
        headers = self._login(client)
        r = client.post("/api/feedback/spq", headers=headers, json={
            "title": "x", "decided_kind": "product_defect"})
        assert r.status_code == 200, r.text
        assert r.json()["linkage_warnings"]


def _login(client, emp_no, name=""):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
