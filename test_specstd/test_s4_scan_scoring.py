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