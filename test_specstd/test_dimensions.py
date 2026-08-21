"""T-981 测试类型学：dimensions 受控词表 + 维度↔断言模式映射 + 覆盖聚合。

验收锚点（《架构反馈升级/2026-08-21-模块化任务拆分.md》M-C T-981）：
- doc.dimensions 受控词表（八维）+ format_spec 规范漂移守护（词表与文档同源）
- 断言证据提取（http_ok/http_error/body_error_code/error_message/absent/db_proof…）
- check_dimensions：缺失 WARN / 词表外 ERROR / 映射自检 WARN / regression 不检查
- 存量 24 场景补标注后全库零 DIM 告警（映射设计对存量的适配性回归）
- compute_coverage 输出 dimensions 聚合（含 0 计数维度 + 未标注清单）
"""

from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

from sg_core.test_dimensions import (  # noqa: E402
    DIMENSION_EVIDENCE,
    DIMENSIONS,
    check_dimensions,
    extract_evidence,
)


def _raw(sid="XX-T-001", dims=None, flow=None, verify=None):
    doc = {}
    if dims is not None:
        doc["dimensions"] = dims
    return {
        "id": sid,
        "doc": doc,
        "flow": flow if flow is not None else [{"call": {"method": "GET", "path": "/x", "save": "resp"}}],
        "verify": verify if verify is not None else [{"status": {"eq": 200}}],
    }


# ══════════════════════════════════════════════════════════
# 词表与规范同源（漂移守护）
# ══════════════════════════════════════════════════════════

class TestVocabulary:
    def test_vocabulary_is_eight_dimensions(self):
        assert list(DIMENSIONS) == [
            "happy-path", "negative", "boundary", "permission",
            "security", "state", "isolation", "regression",
        ]

    def test_format_spec_body_mentions_every_dimension(self):
        """受控词表与 format_spec §1.2 文档同源——改词表必须同步规范（三同步守护）。"""
        from sg_core.format_spec import _BODY, SPEC_VERSION
        for d in DIMENSIONS:
            assert f"`{d}`" in _BODY, f"format_spec §1.2 缺维度 {d}（改词表需走三同步）"
        assert "T10" in _BODY
        assert SPEC_VERSION >= "2.14.0"

    def test_mapping_covers_all_but_regression(self):
        """除 regression（标注语义）外每维都有映射；映射证据集非空且有中文提示。"""
        assert set(DIMENSION_EVIDENCE) == set(DIMENSIONS) - {"regression"}
        for d, (evidence, hint) in DIMENSION_EVIDENCE.items():
            assert evidence, d
            assert hint, d


# ══════════════════════════════════════════════════════════
# 断言证据提取
# ══════════════════════════════════════════════════════════

class TestExtractEvidence:
    def test_http_ok_and_error_by_status_code(self):
        ev = extract_evidence(_raw(verify=[{"status": {"eq": 200}}]))
        assert "http_ok" in ev and "http_error" not in ev
        ev = extract_evidence(_raw(verify=[{"status": {"eq": 400, "of": "resp"}}]))
        assert "http_error" in ev and "http_ok" not in ev

    def test_body_error_code_via_wrapped_protocol(self):
        """统一包装协议：HTTP 200 + $.status≠200 是负向证据（PP-RC-004 形态）。"""
        ev = extract_evidence(_raw(verify=[
            {"status": {"eq": 200}},
            {"json": {"path": "$.status", "eq": "500000"}},
            {"json": {"path": "$.message", "contains": "不存在"}},
        ]))
        assert {"body_error_code", "error_message", "http_ok"} <= ev

    def test_body_error_code_excludes_success_code(self):
        """$.status eq 200/0 是成功断言，不算错误码证据。"""
        ev = extract_evidence(_raw(verify=[{"json": {"path": "$.status", "eq": "200"}}]))
        assert "body_error_code" not in ev

    def test_absent_and_oracle_and_python(self):
        ev = extract_evidence(_raw(verify=[
            {"json": {"path": "$.data.basicInfo", "absent": True}},
            {"oracle": "permission_filtered"},
            {"python": "assert True"},
        ]))
        assert {"absent", "oracle", "db_proof", "python"} <= ev

    def test_db_proof_via_db_query_save_reference(self):
        """json 断言 of 指向 db_query 的 save = 持久层证据（EV-IMP-002 行级隔离形态）。"""
        ev = extract_evidence(_raw(
            flow=[
                {"call": {"method": "POST", "path": "/x", "save": "resp"}},
                {"db_query": {"sql": "SELECT 1", "save": "rows"}},
            ],
            verify=[{"json": {"of": "rows", "path": "$", "len_eq": 1}}],
        ))
        assert "db_proof" in ev and "oracle" not in ev

    def test_json_of_call_save_is_not_db_proof(self):
        ev = extract_evidence(_raw(verify=[{"json": {"of": "resp", "path": "$.x", "eq": 1}}]))
        assert "db_proof" not in ev and "json_field" in ev


# ══════════════════════════════════════════════════════════
# check_dimensions 规则
# ══════════════════════════════════════════════════════════

class TestCheckDimensions:
    def test_missing_dimensions_warns(self):
        findings = check_dimensions(_raw())
        assert [f["rule"] for f in findings] == ["DIM_MISSING"]
        assert findings[0]["level"] == "WARN"

    def test_unknown_dimension_is_error_with_hint(self):
        findings = check_dimensions(_raw(dims=["happy_path", "negtive"]))
        vocab = [f for f in findings if f["rule"] == "DIM_VOCAB"]
        assert vocab and vocab[0]["level"] == "ERROR"
        assert "happy-path" in vocab[0]["message"]  # 相近 hint
        assert "negative" in vocab[0]["message"]

    def test_non_list_dimensions_is_error(self):
        findings = check_dimensions(_raw(dims="happy-path"))
        assert findings[0]["rule"] == "DIM_VOCAB" and findings[0]["level"] == "ERROR"

    def test_empty_list_is_error(self):
        findings = check_dimensions(_raw(dims=[]))
        assert findings[0]["rule"] == "DIM_VOCAB"

    def test_mapping_warns_when_evidence_missing(self):
        """声明 state 但只有 HTTP 响应断言（无 oracle/db_query 派生）→ DIM_MAP WARN。"""
        findings = check_dimensions(_raw(
            dims=["state"],
            verify=[{"status": {"eq": 200}}, {"json": {"path": "$.data.x", "eq": 1}}],
        ))
        assert [f["rule"] for f in findings] == ["DIM_MAP"]
        assert findings[0]["level"] == "WARN"
        assert "state" in findings[0]["message"]

    def test_mapping_passes_with_oracle(self):
        findings = check_dimensions(_raw(dims=["state"], verify=[{"oracle": "snapshot_frozen"}]))
        assert findings == []

    def test_negative_passes_via_wrapped_protocol(self):
        findings = check_dimensions(_raw(
            dims=["negative"],
            verify=[{"status": {"eq": 200}}, {"json": {"path": "$.status", "eq": "401"}}],
        ))
        assert findings == []

    def test_regression_not_mapped(self):
        """regression 是标注语义——即使 verify 只有成功断言也不报 DIM_MAP。"""
        findings = check_dimensions(_raw(dims=["regression"], verify=[{"status": {"eq": 200}}]))
        assert findings == []

    def test_happy_path_passes_stock_shape(self):
        findings = check_dimensions(_raw(dims=["happy-path"]))
        assert findings == []


# ══════════════════════════════════════════════════════════
# 存量场景回归（标注适配性：全库零 DIM 告警）
# ══════════════════════════════════════════════════════════

class TestStockScenarios:
    def test_all_stock_scenarios_annotated_and_clean(self):
        """24 个存量场景全部补标注且通过维度检查（映射设计对存量零误报）。"""
        import yaml
        root = SG_ROOT / "scenarios"
        files = [f for f in sorted(root.rglob("*.yaml")) if not f.name.startswith("_")]
        assert len(files) == 24, "存量场景数（补标注任务基数）"
        problems = []
        for f in files:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            findings = check_dimensions(raw)
            for fd in findings:
                problems.append(f"{raw.get('id')}: {fd['rule']} {fd['message'][:80]}")
        assert not problems, "\n".join(problems)


# ══════════════════════════════════════════════════════════
# validator / spec_validator 集成
# ══════════════════════════════════════════════════════════

class TestValidatorIntegration:
    def test_mcp_validator_emits_dim_findings(self):
        from mcp_server.tools.validator import validate_scenario_content
        report = validate_scenario_content("""
id: XX-DIM-001
version: "0.1"
doc:
  given: x
  covers: []
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - status: {eq: 200}
""")
        dims = [f for f in report["findings"] if f["rule"] == "DIM_MISSING"]
        assert dims and dims[0]["level"] == "WARN"

    def test_mcp_validator_rejects_unknown_dimension(self):
        from mcp_server.tools.validator import validate_scenario_content
        report = validate_scenario_content("""
id: XX-DIM-002
version: "0.1"
doc:
  dimensions: [happy_path]
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - status: {eq: 200}
""")
        vocab = [f for f in report["findings"] if f["rule"] == "DIM_VOCAB"]
        assert vocab and vocab[0]["level"] == "ERROR"
        assert report["verdict"] == "REJECT"

    def test_spec_validator_full_library_has_no_dim_findings(self):
        """工作台全库校验口径：存量补标注后 T10 零命中。"""
        from workbench.backend.services.spec_validator import validate_test_cases
        report = validate_test_cases(str(SG_ROOT / "scenarios"))
        t10 = [f for f in report["findings"] if f.get("vid") == "T10"]
        assert not t10, t10


# ══════════════════════════════════════════════════════════
# 覆盖聚合（compute_coverage.dimensions）
# ══════════════════════════════════════════════════════════

class TestCoverageDimensionAggregation:
    def test_dimension_stats_shape_and_counts(self, monkeypatch):
        from workbench.backend.services import coverage_gaps as cg
        monkeypatch.setattr(cg, "_load_anchors", lambda: {})
        monkeypatch.setattr(cg, "_load_scenarios", lambda: [
            {"id": "A-001", "covers": ["FR-1"], "module": "m",
             "dimensions": ["happy-path", "state"], "path": ""},
            {"id": "A-002", "covers": ["FR-2"], "module": "m",
             "dimensions": ["negative"], "path": ""},
            {"id": "A-003", "covers": [], "module": "m", "dimensions": [], "path": ""},
            {"id": "A-004", "covers": ["FR-1"], "module": "m",
             "dimensions": ["happy-path"], "path": ""},
        ])
        monkeypatch.setattr(cg, "_load_drafts", lambda: [])
        r = cg.compute_coverage()
        lanes = r["dimensions"]["lanes"]
        assert len(lanes) == len(DIMENSIONS)  # 八维全出（含 0 计数=盲区可见）
        dims = {d["dimension"]: d for d in lanes}
        assert dims["happy-path"]["count"] == 2
        assert dims["happy-path"]["scenarios"] == ["A-001", "A-004"]
        assert dims["happy-path"]["frs"] == ["FR-1"]
        assert dims["negative"]["count"] == 1
        assert dims["boundary"]["count"] == 0
        assert r["dimensions"]["unassigned"] == ["A-003"]

    def test_dimension_stats_empty_library(self, monkeypatch):
        """空场景库：八维全 0、unassigned 空（三态分离——不是错误不是加载中）。"""
        from workbench.backend.services import coverage_gaps as cg
        monkeypatch.setattr(cg, "_load_anchors", lambda: {})
        monkeypatch.setattr(cg, "_load_scenarios", lambda: [])
        monkeypatch.setattr(cg, "_load_drafts", lambda: [])
        r = cg.compute_coverage()
        assert all(d["count"] == 0 for d in r["dimensions"]["lanes"])
        assert r["dimensions"]["unassigned"] == []

    def test_fingerprint_changes_with_annotation(self, monkeypatch):
        """标注变化（covers 不变）也会改变指纹——维度聚合是派生数据的一部分。"""
        from workbench.backend.services import coverage_gaps as cg
        monkeypatch.setattr(cg, "_load_anchors", lambda: {})
        monkeypatch.setattr(cg, "_load_drafts", lambda: [])
        base = [{"id": "A-001", "covers": ["FR-1"], "module": "m",
                 "dimensions": ["happy-path"], "path": ""}]
        monkeypatch.setattr(cg, "_load_scenarios", lambda: base)
        fp1 = cg.compute_coverage()["fingerprint"]
        monkeypatch.setattr(cg, "_load_scenarios", lambda: [
            {**base[0], "dimensions": ["negative"]}])
        fp2 = cg.compute_coverage()["fingerprint"]
        assert fp1 != fp2
