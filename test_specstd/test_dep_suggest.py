"""dep_suggest 依赖建议引擎测试（K-046）。

验证：
1. needs 提取：跨场景引用（{{SC-ID.save.path}}）→ 高置信建议
2. needs 提取：save 变量匹配（{{emp.no}}，他场景 save: emp）→ 中置信建议
3. 剔除规则：已声明/传递依赖、自依赖、会成环、env.*、本场景自产 save
4. 多生产者同名 save → 全部列出；引用不存在的场景 → unresolved
5. drafts_only / target_id 过滤
"""

from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from services import dep_suggest


def _scenario(sid, saves=(), deps=(), body_refs=(), title=""):
    """构造最小合法场景 YAML 文本（格式 2.0 双层）。"""
    lines = [
        f"id: {sid}",
        f"title: {title or sid + ' 标题'}",
        "version: '0.1'",
        "doc:",
        "  given: [g]",
        "  when: [w]",
        "  then: [t]",
        "  covers: [FR-X]",
    ]
    if deps:
        lines.append("depends_on:")
        for d in deps:
            lines.append(f"  - {{id: {d}, version: ^0}}")
    else:
        lines.append("depends_on: []")
    lines.append("flow:")
    for i, sv in enumerate(saves):
        lines.append(f"  - python: {{code: 'x = {i}', save: {sv}}}")
    if body_refs:
        ref_str = ", ".join(f"k{i}: '{r}'" for i, r in enumerate(body_refs))
        lines.append(f"  - python: {{code: 'y = 1', save: out_{sid.replace('-', '_')}}}")
        lines.append(f"# refs: {ref_str}")
        # 插值必须出现在 YAML 文本中（needs 从全文扫描）
        for r in body_refs:
            lines.append(f"  - call: {{method: GET, path: '/api/{r}', save: c_{len(r)}}}")
    else:
        lines.append("  - python: {code: 'y = 1', save: out}")
    lines.append("verify: []")
    return "\n".join(lines) + "\n"


def _mk_library(tmp_path, files):
    root = tmp_path / "scenarios"
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


class TestNeedsExtraction:
    def test_cross_scenario_ref_high_confidence(self, tmp_path):
        """消费 {{PP-PREP-001.session.id}} → 建议依赖 PP-PREP-001（高置信）。"""
        root = _mk_library(tmp_path, {
            "PP-PREP-001.yaml": _scenario("PP-PREP-001", saves=["session"]),
            "PP-RC-001.yaml": _scenario("PP-RC-001", body_refs=["{{PP-PREP-001.session.id}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        sug = [s for s in out["suggestions"] if s["consumer"] == "PP-RC-001"]
        assert len(sug) == 1
        assert sug[0]["dep_id"] == "PP-PREP-001"
        assert sug[0]["confidence"] == "high"
        assert sug[0]["kind"] == "cross_ref"
        assert "PP-PREP-001" in sug[0]["reason"]

    def test_var_match_medium_confidence(self, tmp_path):
        """消费 {{emp.no}}，他场景 save: emp → 中置信建议，理由含变量名。"""
        root = _mk_library(tmp_path, {
            "PP-RC-005.yaml": _scenario("PP-RC-005", saves=["emp"]),
            "PP-RC-006.yaml": _scenario("PP-RC-006", body_refs=["{{emp.no}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        sug = [s for s in out["suggestions"] if s["consumer"] == "PP-RC-006"]
        assert len(sug) == 1
        assert sug[0]["dep_id"] == "PP-RC-005"
        assert sug[0]["confidence"] == "medium"
        assert "emp" in sug[0]["reason"]

    def test_env_and_own_saves_excluded(self, tmp_path):
        """env.* 与本场景自产 save 不产生建议。"""
        root = _mk_library(tmp_path, {
            "PP-RC-001.yaml": _scenario("PP-RC-001", saves=["emp"],
                                        body_refs=["{{emp.no}}", "{{env.gateway}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        assert out["suggestions"] == []
        assert "PP-RC-001" not in out["unresolved"]


class TestExclusions:
    def test_existing_dep_not_suggested(self, tmp_path):
        root = _mk_library(tmp_path, {
            "PP-PREP-001.yaml": _scenario("PP-PREP-001", saves=["session"]),
            "PP-RC-001.yaml": _scenario("PP-RC-001", deps=["PP-PREP-001"],
                                        body_refs=["{{PP-PREP-001.session.id}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        assert out["suggestions"] == []

    def test_transitive_dep_not_suggested(self, tmp_path):
        """A→B→C 时 C 引用 A 的变量，不再建议 C 直接依赖 A（已传递覆盖）。"""
        root = _mk_library(tmp_path, {
            "A-A-001.yaml": _scenario("A-A-001", saves=["session"]),
            "B-B-001.yaml": _scenario("B-B-001", deps=["A-A-001"]),
            "C-C-001.yaml": _scenario("C-C-001", deps=["B-B-001"],
                                      body_refs=["{{A-A-001.session.id}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        assert [s for s in out["suggestions"] if s["consumer"] == "C-C-001"] == []

    def test_cycle_not_suggested(self, tmp_path):
        """B 依赖 A，A 引用 B 的变量 → 不建议 A 依赖 B（会成环）。"""
        root = _mk_library(tmp_path, {
            "A-A-001.yaml": _scenario("A-A-001", body_refs=["{{B-B-001.resp}}"]),
            "B-B-001.yaml": _scenario("B-B-001", saves=["resp"], deps=["A-A-001"]),
        })
        out = dep_suggest.suggest_deps(root)
        assert [s for s in out["suggestions"] if s["consumer"] == "A-A-001"] == []

    def test_self_dependency_not_suggested(self, tmp_path):
        """跨场景引用形态指向自己 → 不建议。"""
        root = _mk_library(tmp_path, {
            "A-A-001.yaml": _scenario("A-A-001", body_refs=["{{A-A-001.session.id}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        assert out["suggestions"] == []


class TestMultiProducerAndUnresolved:
    def test_multiple_producers_all_listed(self, tmp_path):
        root = _mk_library(tmp_path, {
            "A-A-001.yaml": _scenario("A-A-001", saves=["emp"]),
            "B-B-001.yaml": _scenario("B-B-001", saves=["emp"]),
            "C-C-001.yaml": _scenario("C-C-001", body_refs=["{{emp.no}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        deps = sorted(s["dep_id"] for s in out["suggestions"] if s["consumer"] == "C-C-001")
        assert deps == ["A-A-001", "B-B-001"]

    def test_unknown_scenario_ref_unresolved(self, tmp_path):
        root = _mk_library(tmp_path, {
            "A-A-001.yaml": _scenario("A-A-001", body_refs=["{{ZZ-RC-999.session.id}}"]),
        })
        out = dep_suggest.suggest_deps(root)
        assert out["suggestions"] == []
        assert "A-A-001" in out["unresolved"]
        assert any("ZZ-RC-999" in r for r in out["unresolved"]["A-A-001"])


class TestDrafts:
    def test_draft_to_draft_and_draft_to_lib(self, tmp_path):
        """草稿引用库内场景 + 草稿引用另一草稿，均出建议。"""
        root = _mk_library(tmp_path, {
            "PP-PREP-001.yaml": _scenario("PP-PREP-001", saves=["session"]),
        })
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "TL-PREP-001.yaml").write_text(
            _scenario("TL-PREP-001", saves=["tag"]), encoding="utf-8")
        (drafts / "TL-RC-001.yaml").write_text(
            _scenario("TL-RC-001", body_refs=["{{PP-PREP-001.session.id}}", "{{tag.id}}"]),
            encoding="utf-8")
        out = dep_suggest.suggest_deps(root, drafts)
        deps = sorted(s["dep_id"] for s in out["suggestions"] if s["consumer"] == "TL-RC-001")
        assert deps == ["PP-PREP-001", "TL-PREP-001"]

    def test_drafts_only_filter(self, tmp_path):
        root = _mk_library(tmp_path, {
            "PP-PREP-001.yaml": _scenario("PP-PREP-001", saves=["session"]),
            "PP-RC-001.yaml": _scenario("PP-RC-001", body_refs=["{{PP-PREP-001.session.id}}"]),
        })
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "TL-RC-001.yaml").write_text(
            _scenario("TL-RC-001", body_refs=["{{PP-PREP-001.session.id}}"]), encoding="utf-8")
        out = dep_suggest.suggest_deps(root, drafts, drafts_only=True)
        consumers = {s["consumer"] for s in out["suggestions"]}
        assert consumers == {"TL-RC-001"}

    def test_target_id_filter(self, tmp_path):
        root = _mk_library(tmp_path, {
            "PP-PREP-001.yaml": _scenario("PP-PREP-001", saves=["session"]),
            "PP-RC-001.yaml": _scenario("PP-RC-001", body_refs=["{{PP-PREP-001.session.id}}"]),
            "PP-RC-002.yaml": _scenario("PP-RC-002", body_refs=["{{PP-PREP-001.session.id}}"]),
        })
        out = dep_suggest.suggest_deps(root, target_id="PP-RC-002")
        consumers = {s["consumer"] for s in out["suggestions"]}
        assert consumers == {"PP-RC-002"}

    def test_draft_with_same_id_as_library_skipped(self, tmp_path):
        """与库内同 id 的草稿视为已入库副本，不作为生产者重复参与。"""
        root = _mk_library(tmp_path, {
            "PP-PREP-001.yaml": _scenario("PP-PREP-001", saves=["session"]),
        })
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "PP-PREP-001.yaml").write_text(
            _scenario("PP-PREP-001", saves=["session"]), encoding="utf-8")
        out = dep_suggest.suggest_deps(root, drafts)
        # 不出现任何异常，且无自引用建议
        assert all(s["consumer"] != s["dep_id"] for s in out["suggestions"])


class TestGraphErrorExplicit:
    """T-104：建图失败（依赖环）必须显式返回 graph_error，不再静默跳过环预检。"""

    def test_cycle_library_reports_graph_error(self, tmp_path):
        root = _mk_library(tmp_path, {
            "A.yaml": _scenario("A", deps=["B"]),
            "B.yaml": _scenario("B", deps=["A"]),
        })
        out = dep_suggest.suggest_deps(root, target_id="A")
        assert out["graph_error"], "依赖环场景库必须显式返回建图失败原因"
        assert "循环" in out["graph_error"] or "CycleError" in out["graph_error"]

    def test_healthy_library_no_graph_error(self, tmp_path):
        root = _mk_library(tmp_path, {
            "A.yaml": _scenario("A", deps=[]),
            "B.yaml": _scenario("B", deps=["A"]),
        })
        out = dep_suggest.suggest_deps(root, target_id="B")
        assert out["graph_error"] == ""
