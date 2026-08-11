"""S4 草案扫描仪/五维评分/冻结门禁测试（T-040/T-041/T-042）。

覆盖：
- spec_draft: TBD 标记扫描/落锤替换/11 章校验
- proposal_schema: 四段式解析/生成/校验
- delta/manifest: YAML 读写/FR 收集/校验
- delta/verify: V1-V6 逐条 + 全量
- delta/merge: ADDED/MODIFIED/REMOVED
- delta/archive: 归档/检查/列表
- scoring: 四维机打采集 + 加权合计
- freeze_gate: 三闸编排
- REST: 冻结端点（product 闸门/409）
全部离线。
"""

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
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════════════
# fixtures（REST 测试用）
# ══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cleanup_ctx():
    """防 contextvar 泄漏。"""
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
    """装配 TestClient。"""
    from test_specstd.helpers import create_valid_workspace
    import specstd.workspace as wsm

    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from main import app
    with TestClient(app) as c:
        yield c

    wsm.unregister("tdm")


SAMPLE_DRAFT = """\
## 一、概述
系统 SHALL 支持绩效域落位。
## 二、范围
本规范适用于九宫格绩效域规则。
## 三、功能需求
系统 SHALL 按新规则计算落位。
系统 SHALL 支持落位名单刷新。
系统 SHALL 记录落位变更历史。
## 四、非功能需求
## 五、数据需求
## 六、接口需求
## 七、安全需求
## 八、前置条件
## 九、验收标准
## 十、术语定义
## 十一、Changelog
"""

SAMPLE_SPEC = """\
## FR-001. 规则一
原内容

## FR-002. 规则二
原内容
"""


class TestSpecDraft:
    """T-040 spec_draft.py 单元测试。"""
    def test_find_tbd_marks(self):
        from specflow.anchor.spec_draft import find_tbd_marks
        marks = find_tbd_marks("「待确认处理方案」")
        assert len(marks) == 1
    def test_find_tbd_marks_none(self):
        from specflow.anchor.spec_draft import find_tbd_marks
        assert find_tbd_marks("全部已确认") == []
    def test_resolve_tbd(self):
        from specflow.anchor.spec_draft import resolve_tbd
        result = resolve_tbd("「待确认处理方案」", "冻结存量 ✅ D-032")
        assert "D-032" in result
    def test_count_unresolved_tbd(self):
        from specflow.anchor.spec_draft import count_unresolved_tbd
        assert count_unresolved_tbd("「待确认A」「待确认B」") == 2
    def test_find_delta_marks(self):
        from specflow.anchor.spec_draft import find_delta_marks
        marks = find_delta_marks("[delta:grid-rule-perf ADDED]")
        assert len(marks) == 1
    def test_validate_sections_all(self):
        from specflow.anchor.spec_draft import validate_spec_draft_sections
        assert len(validate_spec_draft_sections(SAMPLE_DRAFT)) == 0
    def test_validate_sections_missing(self):
        from specflow.anchor.spec_draft import validate_spec_draft_sections
        assert len(validate_spec_draft_sections("## 一、概述")) > 0


class TestProposalSchema:
    """T-040 proposal_schema.py 单元测试。"""
    def test_generate(self):
        from specflow.anchor.proposal_schema import generate_proposal
        text = generate_proposal("测试", background="背景", scope="范围",
                                 exclude="排除", acceptance="验收",
                                 decision_refs=[{"id":"D-031","question":"Q","resolution":"R"}],
                                 fr_refs=["FR-006"])
        assert "为什么做" in text
        assert "D-031" in text
    def test_validate_ok(self):
        from specflow.anchor.proposal_schema import generate_proposal, validate_proposal
        assert validate_proposal(generate_proposal("测试")) == []
    def test_validate_missing(self):
        from specflow.anchor.proposal_schema import validate_proposal
        assert len(validate_proposal("无段落")) == 4
    def test_extract_refs(self):
        from specflow.anchor.proposal_schema import extract_decision_refs, extract_fr_refs
        assert "D-031" in extract_decision_refs("D-031")
        assert "FR-006" in extract_fr_refs("FR-006")


class TestDeltaManifest:
    """T-040 delta/manifest.py 单元测试。"""
    def test_roundtrip(self, tmp_path):
        from specflow.delta.manifest import DeltaManifest, write_manifest, load_manifest
        m = DeltaManifest(delta="test", source_interview="IV-001", base_spec="spec.md",
                          operations=[{"op":"MODIFIED","anchor":"FR-001","reason":"x"}])
        path = tmp_path / "manifest.yaml"
        write_manifest(path, m)
        assert load_manifest(str(path)).delta == "test"
    def test_validate_ok(self):
        from specflow.delta.manifest import DeltaManifest, validate_manifest
        m = DeltaManifest(delta="x", source_interview="IV-001", base_spec="spec.md",
                          operations=[{"op":"MODIFIED","anchor":"FR-001","reason":"x"}])
        assert validate_manifest(m) == []
    def test_validate_missing(self):
        from specflow.delta.manifest import DeltaManifest, validate_manifest
        assert len(validate_manifest(DeltaManifest(delta=""))) >= 2
    def test_collect_frs(self):
        from specflow.delta.manifest import collect_operation_frs
        assert collect_operation_frs([{"anchor":"FR-001"},{"anchor":"FR-002"}]) == {"FR-001","FR-002"}


class TestDeltaVerify:
    """T-040 delta/verify.py 单元测试。"""
    def _m(self, **kw):
        from specflow.delta.manifest import DeltaManifest
        base = {"delta":"t","source_interview":"IV-001","base_spec":"s.md",
                "operations":[{"op":"MODIFIED","anchor":"FR-001","reason":"x"}]}
        base.update(kw)
        return DeltaManifest(**base)
    def test_v1_valid(self):
        from specflow.delta.verify import verify_v1_anchor_valid
        assert verify_v1_anchor_valid(self._m()) == []
    def test_v1_invalid(self):
        from specflow.delta.verify import verify_v1_anchor_valid
        assert len(verify_v1_anchor_valid(self._m(operations=[{"anchor":"INVALID"}]))) > 0
    def test_v2_has_reason(self):
        from specflow.delta.verify import verify_v2_full_replace
        assert verify_v2_full_replace(self._m()) == []
    def test_v2_missing(self):
        from specflow.delta.verify import verify_v2_full_replace
        assert len(verify_v2_full_replace(self._m(operations=[{"op":"MODIFIED","anchor":"FR-001","reason":""}]))) > 0
    def test_v4_has(self):
        from specflow.delta.verify import verify_v4_traceable
        assert verify_v4_traceable(self._m()) == []
    def test_v4_missing(self):
        from specflow.delta.verify import verify_v4_traceable
        assert len(verify_v4_traceable(self._m(source_interview=""))) > 0
    def test_verify_all_pass(self):
        from specflow.delta.verify import verify_all
        assert verify_all(self._m()).to_dict()["verdict"] == "PASS"
    def test_verify_all_fail(self):
        from specflow.delta.verify import verify_all
        assert verify_all(self._m(delta="", source_interview="")).to_dict()["verdict"] == "FAIL"


class TestDeltaMerge:
    """T-040 delta/merge.py 单元测试。"""
    def test_added(self):
        from specflow.delta.merge import merge_added
        result = merge_added(SAMPLE_SPEC, "FR-003", "## FR-003. 新规则\n新内容")
        assert "FR-003" in result
    def test_modified(self):
        from specflow.delta.merge import merge_modified
        result = merge_modified(SAMPLE_SPEC, "FR-001", "替换内容\n")
        assert "替换内容" in result
    def test_removed(self):
        from specflow.delta.merge import merge_removed
        assert "FR-002" in merge_removed(SAMPLE_SPEC, "FR-001")


class TestDeltaArchive:
    """T-040 delta/archive.py 单元测试。"""
    def test_archive_roundtrip(self, tmp_path):
        from specflow.delta.archive import archive_delta, is_archived, list_archived
        cd = tmp_path / "changes" / "delta-test"
        cd.mkdir(parents=True); (cd / "f.yaml").write_text("", encoding="utf-8")
        ar = tmp_path / "archive"
        archive_delta(cd, ar)
        assert is_archived(ar, "delta-test")
        assert "delta-test" in list_archived(ar)


class TestScoring:
    """T-041 specflow.anchor.scoring 单元测试。"""
    def test_logic_full(self):
        from specflow.anchor.scoring import collect_logic_dimension
        r = collect_logic_dimension(SAMPLE_DRAFT)
        assert r["chapters_found"] == 11 and r["score"] >= 80
    def test_logic_poor(self):
        from specflow.anchor.scoring import collect_logic_dimension
        assert collect_logic_dimension("仅一段")["score"] < 70
    def test_coverage_full(self):
        from specflow.anchor.scoring import collect_coverage_dimension
        assert collect_coverage_dimension(coverage_total=10, coverage_mapped=9)["score"] >= 80
    def test_coverage_poor(self):
        from specflow.anchor.scoring import collect_coverage_dimension
        assert collect_coverage_dimension(coverage_total=10, coverage_mapped=2)["score"] <= 50
    def test_boundary_good(self):
        from specflow.anchor.scoring import collect_boundary_dimension
        assert collect_boundary_dimension("异常处理 边界条件 超时 重试 错误回滚 异常场景")["score"] >= 80
    def test_boundary_poor(self):
        from specflow.anchor.scoring import collect_boundary_dimension
        assert collect_boundary_dimension("简单描述")["score"] <= 50
    def test_precondition_good(self):
        from specflow.anchor.scoring import collect_precondition_dimension
        assert collect_precondition_dimension("前置条件 前提 依赖 假设 环境要求")["score"] >= 70
    def test_all_machine(self):
        from specflow.anchor.scoring import collect_all_machine_dimensions
        assert len(collect_all_machine_dimensions(SAMPLE_DRAFT)) == 4
    def test_weighted_total(self):
        from specflow.anchor.scoring import calculate_weighted_total
        s = {"l":{"score":80,"status":"confirmed"},"c":{"score":70,"status":"confirmed"}}
        assert calculate_weighted_total(s)["total"] == 75.0


class TestFreezeGate:
    """T-042 freeze_gate.py 单元测试。"""
    def test_check_all_gates(self):
        from workbench.backend.services.specflow.freeze_gate import check_all_gates
        r = check_all_gates("ws", "IV-001", "d", "t")
        assert "freeze_allowed" in r and "gates" in r
    def test_gate_structure(self):
        from workbench.backend.services.specflow.freeze_gate import check_all_gates
        r = check_all_gates("ws", "IV-001", "d", "t")
        assert "product_confirm" in r["gates"]


class TestFreezeRest:
    """T-042 REST 端点。"""
    def test_export_404(self, client):
        r = client.post("/api/specflow/freeze/changes/nonexistent/export",
                        headers={"Authorization": "Bearer mock-admin",
                                 "X-SG-Workspace": "tdm"})
        assert r.status_code in (403, 404)
    def test_gates_endpoint(self, client):
        r = client.get("/api/specflow/freeze/changes/test-d/gates",
                       params={"interview_id":"IV-001"},
                       headers={"Authorization": "Bearer mock-admin"})
        assert r.status_code in (200, 403)


class TestVerifyV6:
    """I2 修复：V6 一致性校验（正文 [delta:代号 OP] 集 == manifest operations 集）。"""
    def _m(self, delta="grid-rule-perf", ops=None):
        from specflow.delta.manifest import DeltaManifest
        return DeltaManifest(
            delta=delta, source_interview="IV-001", base_spec="s.md",
            operations=ops or [{"op": "MODIFIED", "anchor": "FR-001",
                                "reason": "x"}])

    def test_v6_consistent(self):
        from specflow.delta.verify import verify_v6_manifest_consistency
        text = "## FR-001. 规则\n[delta:grid-rule-perf MODIFIED]\n新内容"
        assert verify_v6_manifest_consistency(self._m(), text) == []

    def test_v6_consistent_multi_ops(self):
        from specflow.delta.verify import verify_v6_manifest_consistency
        ops = [{"op": "ADDED", "anchor": "FR-002"},
               {"op": "MODIFIED", "anchor": "FR-001", "reason": "x"}]
        text = "[delta:grid-rule-perf ADDED]\n[delta:grid-rule-perf MODIFIED]"
        assert verify_v6_manifest_consistency(self._m(ops=ops), text) == []

    def test_v6_inconsistent_op(self):
        """正文操作类型与 manifest 不一致 → 报错。"""
        from specflow.delta.verify import verify_v6_manifest_consistency
        text = "[delta:grid-rule-perf ADDED]"
        assert len(verify_v6_manifest_consistency(self._m(), text)) > 0

    def test_v6_inconsistent_delta(self):
        """正文 delta 代号与 manifest.delta 不一致 → 报错。"""
        from specflow.delta.verify import verify_v6_manifest_consistency
        text = "[delta:other-name MODIFIED]"
        assert len(verify_v6_manifest_consistency(self._m(), text)) > 0

    def test_v6_missing_op_suffix(self):
        """正文标记缺操作类型 → 视为不一致（fail-closed）。"""
        from specflow.delta.verify import verify_v6_manifest_consistency
        text = "[delta:grid-rule-perf]"
        assert len(verify_v6_manifest_consistency(self._m(), text)) > 0

    def test_v6_empty_text_skip(self):
        from specflow.delta.verify import verify_v6_manifest_consistency
        assert verify_v6_manifest_consistency(self._m(), "") == []


class TestResolveTbdEdge:
    """I5 修复：resolve_tbd 替换文本含反斜杠/组引用不崩溃。"""
    def test_resolve_tbd_backslash(self):
        from specflow.anchor.spec_draft import resolve_tbd
        replacement = r"C:\temp\1\g<x>"
        result = resolve_tbd("「待确认处理方案」", replacement)
        assert replacement in result
        assert "待确认" not in result


class TestScoringGuard:
    """I4 修复：空/过短文本拒绝机打采集。"""
    def test_all_machine_empty(self):
        from specflow.anchor.scoring import collect_all_machine_dimensions
        assert collect_all_machine_dimensions("") == []

    def test_all_machine_short(self):
        from specflow.anchor.scoring import collect_all_machine_dimensions
        assert collect_all_machine_dimensions("仅一句短文本") == []

    def test_all_machine_long_ok(self):
        from specflow.anchor.scoring import collect_all_machine_dimensions
        assert len(collect_all_machine_dimensions(SAMPLE_DRAFT)) == 4


class TestFreezeGatePureRead:
    """C1/C2 修复：check_all_gates 纯读；确认必须带操作人。"""
    def test_check_all_gates_no_side_effect(self, db):
        """三闸聚合不写任何 product_confirm 证据（修复前每次检查插入一条）。"""
        from workbench.backend.services.specflow.freeze_gate import check_all_gates
        from workbench.backend.services.specflow.sf_store import _connect
        check_all_gates("tdm", "IV-001", "delta-a", "spec_text")
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sf_gate_evidence "
                "WHERE gate_item = 'product_confirm'").fetchone()
            assert row[0] == 0
        finally:
            conn.close()

    def test_unconfirmed_gate_blocks_freeze(self, db):
        """未确认时闸① fail → freeze_allowed=False（不再自动通过）。"""
        from workbench.backend.services.specflow.freeze_gate import check_all_gates
        r = check_all_gates("tdm", "IV-001", "delta-a", "spec_text")
        assert r["gates"]["product_confirm"]["status"] == "fail"
        assert r["freeze_allowed"] is False

    def test_confirm_then_gate_pass(self, db):
        """确认后 check_all_gates 闸① pass（纯读查询到已有证据）。"""
        from workbench.backend.services.specflow.freeze_gate import (
            product_confirm, check_all_gates)
        r = product_confirm("delta-a", "tdm", "emp-001", interview_id="IV-001")
        assert r["status"] == "pass"
        r2 = check_all_gates("tdm", "IV-001", "delta-a", "spec_text")
        assert r2["gates"]["product_confirm"]["status"] == "pass"

    def test_product_confirm_empty_actor_rejected(self, db):
        """空操作人确认被拒绝，且不写库。"""
        from workbench.backend.services.specflow.freeze_gate import product_confirm
        from workbench.backend.services.specflow.sf_store import _connect
        r = product_confirm("delta-a", "tdm", "", interview_id="IV-001")
        assert r["status"] == "fail"
        conn = _connect()
        try:
            # 空操作人路径不会建表，先初始化（真实环境表必然存在）
            from specflow.interview.decision_ledger import init_tables
            init_tables(conn)
            row = conn.execute(
                "SELECT COUNT(*) FROM sf_gate_evidence "
                "WHERE gate_item = 'product_confirm'").fetchone()
            assert row[0] == 0
        finally:
            conn.close()

    def test_freeze_requires_actor(self, db):
        """freeze_delta 无操作人 → 拒绝且不落凭证。"""
        from workbench.backend.services.specflow.freeze_gate import freeze_delta
        r = freeze_delta("tdm", "IV-001", "delta-a")
        assert r["ok"] is False
        assert "frozen_by" in r["error"]


class TestConformanceFailClosed:
    """I1 修复：conformance 异常/上下文缺失 → fail（不再静默降级 pass）。"""
    def test_ws_missing_fails(self, monkeypatch):
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "get_active_workspace", lambda: None)
        from workbench.backend.services.specflow.freeze_gate import conformance_check
        r = conformance_check("tdm", "delta-a", "spec_text")
        assert r["status"] == "fail"
        assert r.get("degraded") is True

    def test_exception_fails(self, monkeypatch):
        import specstd.conformance as conf
        import specstd.workspace as wsm
        monkeypatch.setattr(
            conf, "check_conformance",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(
            wsm, "get_active_workspace",
            lambda: type("WS", (), {"root": "x"})())
        from workbench.backend.services.specflow.freeze_gate import conformance_check
        r = conformance_check("tdm", "delta-a", "spec_text")
        assert r["status"] == "fail"
        assert r.get("degraded") is True
        assert "异常" in r["errors"][0]


class TestArchiveFreezeGate:
    """I3 修复：未冻结 delta 禁止归档。"""
    def test_archive_unfrozen_rejected(self, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        sf = tmp_path / ".specflow"
        (sf / "changes" / "delta-test").mkdir(parents=True)
        monkeypatch.setattr(wsm, "specflow_dir", lambda *a, **k: sf)
        from workbench.backend.services.specflow.freeze_gate import archive_delta
        r = archive_delta("tdm", "delta-test")
        assert r["ok"] is False
        assert "未冻结" in r["error"]

    def test_archive_frozen_ok(self, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        sf = tmp_path / ".specflow"
        d = sf / "changes" / "delta-test"
        d.mkdir(parents=True)
        (d / "FREEZE.yaml").write_text("frozen: true", encoding="utf-8")
        (d / "delta.manifest.yaml").write_text(
            "delta: delta-test\nsource_interview: IV-001\nbase_spec: s.md\n"
            "operations:\n  - op: MODIFIED\n    anchor: FR-001\n    reason: x\n",
            encoding="utf-8")
        (d / "delta-spec.md").write_text(
            "## FR-001\n[delta:delta-test MODIFIED]\n新内容", encoding="utf-8")
        monkeypatch.setattr(wsm, "specflow_dir", lambda *a, **k: sf)
        from workbench.backend.services.specflow.freeze_gate import archive_delta
        r = archive_delta("tdm", "delta-test")
        assert r["ok"] is True, r
        assert "delta-test" in r["archive_path"]


class TestDeltaIdSanitize:
    """C3 修复：delta_id 白名单（REST 层 + 单元级）。"""
    def test_check_delta_id_valid(self):
        from routers.specflow_freeze import _check_delta_id
        _check_delta_id("delta-a")
        _check_delta_id("grid_rule_perf")
        _check_delta_id("iv-001")

    def test_check_delta_id_invalid(self):
        import pytest
        from fastapi import HTTPException
        from routers.specflow_freeze import _check_delta_id
        for bad in ("..", "a/b", "a\\b", "a b", "", "../x", "a.b"):
            with pytest.raises(HTTPException):
                _check_delta_id(bad)

    def test_gates_400_on_path_traversal(self, client):
        """GET 聚合端点拒绝路径穿越 delta_id（%2E%2E = 编码的 ..）。"""
        r = client.get("/api/specflow/freeze/changes/%2E%2E/gates",
                       params={"interview_id": "IV-001"},
                       headers={"Authorization": "Bearer mock-admin",
                                "X-SG-Workspace": "tdm"})
        assert r.status_code == 400

    def test_export_400_on_invalid_delta_id(self, client):
        """export 端点拒绝非法 delta_id。"""
        r = client.post("/api/specflow/freeze/changes/a.b/export",
                        headers={"Authorization": "Bearer mock-admin",
                                 "X-SG-Workspace": "tdm"})
        assert r.status_code == 400

    def test_get_gates_no_side_effect(self, client, db):
        """C1 端到端：GET 聚合后 sf_gate_evidence 无 product_confirm 证据。"""
        from workbench.backend.services.specflow.sf_store import _connect
        r = client.get("/api/specflow/freeze/changes/delta-a/gates",
                       params={"interview_id": "IV-001"},
                       headers={"Authorization": "Bearer mock-admin",
                                "X-SG-Workspace": "tdm"})
        assert r.status_code == 200
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sf_gate_evidence "
                "WHERE gate_item = 'product_confirm'").fetchone()
            assert row[0] == 0
        finally:
            conn.close()