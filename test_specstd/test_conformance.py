"""specstd.conformance 合规校验器测试。

验证：
1. 合规仓库全 PASS
2. 7 类违规样本全部正确拦截
3. covers 校验（编造 FR 报错）
"""

from pathlib import Path

import pytest

# 确保仓库根在 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent

from specstd.conformance import check_conformance, check_covers
from specstd.anchors import scan_anchors, extract_covers_from_yaml
from specstd.schema import RuleName, RuleLevel

from test_specstd.helpers import (
    create_valid_workspace,
    create_struct_violation,
    create_agents_violation,
    create_anchor_violation,
    create_manifest_violation,
    create_modify_full_violation,
    create_trace_violation,
    create_api_lint_violation,
)


class TestConformance:
    """合规校验器测试。"""

    def test_valid_workspace_passes(self, tmp_path):
        """合规仓库应全 PASS，无 ERROR。"""
        ws = create_valid_workspace(tmp_path / "valid")
        report = check_conformance(ws, "test-valid")
        errors = [f for f in report.findings if f.level == RuleLevel.ERROR.value]
        assert len(errors) == 0, f"合规仓库不应有 ERROR: {[f.to_dict() for f in errors]}"
        assert report.verdict == "PASS"

    def test_struct_violation(self, tmp_path):
        """STRUCT 违规：缺少 archive 目录应报 ERROR。"""
        ws = create_struct_violation(tmp_path / "struct")
        report = check_conformance(ws, "test-struct")
        struct_errors = [
            f for f in report.findings
            if f.rule == RuleName.STRUCT.value and f.level == RuleLevel.ERROR.value
        ]
        assert len(struct_errors) > 0, "应检测到 STRUCT 违规"
        assert any("archive" in f.message for f in struct_errors), "错误消息应提及 archive"

    def test_agents_violation(self, tmp_path):
        """AGENTS 违规：缺少术语 token 清单节应报 ERROR。"""
        ws = create_agents_violation(tmp_path / "agents")
        report = check_conformance(ws, "test-agents")
        agents_errors = [
            f for f in report.findings
            if f.rule == RuleName.AGENTS.value and f.level == RuleLevel.ERROR.value
        ]
        assert len(agents_errors) > 0, "应检测到 AGENTS 违规"
        assert any("术语" in f.message for f in agents_errors), "错误消息应提及术语"

    def test_anchor_violation(self, tmp_path):
        """ANCHOR 违规：FR 锚点重复应报 ERROR。"""
        ws = create_anchor_violation(tmp_path / "anchor")
        report = check_conformance(ws, "test-anchor")
        anchor_errors = [
            f for f in report.findings
            if f.rule == RuleName.ANCHOR.value and f.level == RuleLevel.ERROR.value
        ]
        assert len(anchor_errors) > 0, "应检测到 ANCHOR 违规"
        assert any("FR-001" in f.message for f in anchor_errors), "错误消息应提及 FR-001"

    def test_manifest_violation(self, tmp_path):
        """MANIFEST 违规：manifest 与 delta-spec 不一致应报 ERROR。"""
        ws = create_manifest_violation(tmp_path / "manifest")
        report = check_conformance(ws, "test-manifest")
        manifest_errors = [
            f for f in report.findings
            if f.rule == RuleName.MANIFEST.value and f.level == RuleLevel.ERROR.value
        ]
        assert len(manifest_errors) > 0, "应检测到 MANIFEST 违规"
        assert any("FR-099" in f.message or "FR-099" in str(f.detail) for f in manifest_errors)

    def test_modify_full_violation(self, tmp_path):
        """MODIFY_FULL 违规：MODIFIED 缺少原因应报 ERROR。"""
        ws = create_modify_full_violation(tmp_path / "modify")
        report = check_conformance(ws, "test-modify")
        modify_errors = [
            f for f in report.findings
            if f.rule == RuleName.MODIFY_FULL.value and f.level == RuleLevel.ERROR.value
        ]
        assert len(modify_errors) > 0, "应检测到 MODIFY_FULL 违规"
        assert any("FR-002" in f.message or "原因" in f.message for f in modify_errors)

    def test_trace_violation(self, tmp_path):
        """TRACE 违规：task 引用不存在应报 WARN。"""
        ws = create_trace_violation(tmp_path / "trace")
        report = check_conformance(ws, "test-trace")
        trace_findings = [
            f for f in report.findings
            if f.rule == RuleName.TRACE.value
        ]
        assert len(trace_findings) > 0, "应检测到 TRACE 违规"
        assert any("TSK-099" in f.message or "TSK-099" in str(f.detail) for f in trace_findings)
        # TRACE 应为 WARN，不阻塞接入
        assert all(f.level == RuleLevel.WARN.value for f in trace_findings)

    def test_api_lint_violation(self, tmp_path):
        """API_LINT 违规：api.yaml 缺少 openapi 版本应报 ERROR。"""
        ws = create_api_lint_violation(tmp_path / "apilint")
        report = check_conformance(ws, "test-apilint")
        api_errors = [
            f for f in report.findings
            if f.rule == RuleName.API_LINT.value and f.level == RuleLevel.ERROR.value
        ]
        assert len(api_errors) > 0, "应检测到 API_LINT 违规"
        assert any("openapi" in f.message.lower() for f in api_errors)


class TestCoversResolution:
    """covers 校验测试。"""

    def test_valid_covers(self, tmp_path):
        """covers 引用存在的 FR 应无报错。"""
        ws = create_valid_workspace(tmp_path / "covers-ok")
        anchors = scan_anchors(ws)
        assert "FR-001" in anchors
        assert "FR-002" in anchors

        # 创建场景 YAML
        scenario_dir = tmp_path / "scenarios"
        scenario_dir.mkdir()
        scenario_file = scenario_dir / "TEST-001.yaml"
        scenario_file.write_text(
            "id: TEST-001\ntitle: 测试\ndoc:\n  covers: [FR-001, FR-002]\n"
            "flow:\n  - call: {method: GET, path: /api, save: r}\n"
            "verify:\n  - status: {eq: 200}\n",
            encoding="utf-8",
        )

        findings = check_covers(anchors, scenario_dir)
        errors = [f for f in findings if f.level == RuleLevel.ERROR.value]
        assert len(errors) == 0, f"有效的 covers 不应报错: {[f.to_dict() for f in errors]}"

    def test_fabricated_covers(self, tmp_path):
        """编造的 FR（不存在于 spec.md）应报 ERROR。"""
        ws = create_valid_workspace(tmp_path / "covers-bad")
        anchors = scan_anchors(ws)

        scenario_dir = tmp_path / "scenarios"
        scenario_dir.mkdir()
        scenario_file = scenario_dir / "TEST-002.yaml"
        scenario_file.write_text(
            "id: TEST-002\ntitle: 测试\ndoc:\n  covers: [FR-001, FR-099]\n"
            "flow:\n  - call: {method: GET, path: /api, save: r}\n"
            "verify:\n  - status: {eq: 200}\n",
            encoding="utf-8",
        )

        findings = check_covers(anchors, scenario_dir)
        errors = [f for f in findings if f.level == RuleLevel.ERROR.value]
        assert len(errors) > 0, "编造的 FR 应报 ERROR"
        assert any("FR-099" in f.message or "FR-099" in str(f.detail) for f in errors)


class TestAnchors:
    """锚点解析测试。"""

    def test_scan_anchors(self, tmp_path):
        """扫描应提取 FR-001 和 FR-002。"""
        ws = create_valid_workspace(tmp_path / "anchors")
        anchors = scan_anchors(ws)
        assert "FR-001" in anchors
        assert "FR-002" in anchors
        assert anchors["FR-001"].module == "module1"
        assert anchors["FR-001"].feature == "feature1"
        assert "AC-001" in anchors["FR-001"].ac_ids
        assert "AC-002" in anchors["FR-001"].ac_ids

    def test_extract_covers(self, tmp_path):
        """从场景 YAML 提取 covers。"""
        scenario_file = tmp_path / "test.yaml"
        scenario_file.write_text(
            "id: TEST-003\ntitle: 测试\ndoc:\n  covers: [FR-001, FR-002, FR-003]\n"
            "flow: []\nverify: []\n",
            encoding="utf-8",
        )
        covers = extract_covers_from_yaml(scenario_file)
        assert covers == ["FR-001", "FR-002", "FR-003"]

    def test_parse_list_format_anchors(self, tmp_path):
        """K-020：列表定义格式（- **FR-004**：）必须被识别为锚点。

        生产事故：tdm tag-library/spec.md 用列表加粗格式写 FR → validate 误报
        「FR-004 不存在」→ Agent 删 covers 绕过，30 份草稿 FR 溯源断裂。
        """
        from specstd.anchors import parse_spec_md
        spec_dir = tmp_path / "specs" / "system-settings" / "tag-library"
        spec_dir.mkdir(parents=True)
        spec_md = spec_dir / "spec.md"
        spec_md.write_text(
            "# Feature Spec: 标签库管理\n\n"
            "## 4. Functional Requirements\n\n"
            "- **FR-001**：标签 CRUD——创建、读取、更新、删除操作\n"
            "- **FR-004**：标签库列表查询——支持组合筛选，验收标准 AC-101\n"
            "\n正文内联引用 **FR-001** 不算锚点定义。\n",
            encoding="utf-8",
        )
        anchors = parse_spec_md(spec_md)
        fr_ids = [a.fr_id for a in anchors]
        assert fr_ids.count("FR-001") == 1, "行首列表定义计入一次，正文内联引用不计入"
        assert "FR-004" in fr_ids
        fr004 = next(a for a in anchors if a.fr_id == "FR-004")
        assert "AC-101" in fr004.ac_ids, "列表格式下 AC 提取同样生效"
        assert fr004.module == "system-settings"
        assert fr004.feature == "tag-library"

    def test_mixed_heading_and_list_anchors(self, tmp_path):
        """K-020：标题格式与列表格式混排时按位置合并识别，AC 分块正确。"""
        from specstd.anchors import parse_spec_md
        spec_dir = tmp_path / "specs" / "module1" / "feature1"
        spec_dir.mkdir(parents=True)
        spec_md = spec_dir / "spec.md"
        spec_md.write_text(
            "## 4. Functional Requirements\n\n"
            "### FR-001: 标题格式的锚点\n描述，验收 AC-201\n\n"
            "- **FR-002**：列表格式的锚点，验收 AC-202\n",
            encoding="utf-8",
        )
        anchors = parse_spec_md(spec_md)
        assert [a.fr_id for a in anchors] == ["FR-001", "FR-002"]
        assert anchors[0].ac_ids == ["AC-201"]
        assert anchors[1].ac_ids == ["AC-202"]


class TestWorkspace:
    """工作区管理测试。"""

    def test_register_local(self, tmp_path):
        """本地文件夹注册应成功。"""
        from specstd.workspace import register_local, get_workspace, unregister

        ws_path = create_valid_workspace(tmp_path / "ws-register")
        result = register_local("test-ws", str(ws_path), "tdm", activate=True)
        assert result["ok"], f"注册失败: {result.get('error')}"
        assert result["workspace"]["name"] == "test-ws"

        info = get_workspace("test-ws")
        assert info is not None
        assert info.source_type == "local"
        assert info.system == "tdm"

        # 清理
        unregister("test-ws")

    def test_set_active(self, tmp_path):
        """激活切换应正确。"""
        from specstd.workspace import register_local, get_active_workspace, set_active, unregister

        ws_path = create_valid_workspace(tmp_path / "ws-active")
        register_local("test-active", str(ws_path), "tdm", activate=True)
        active = get_active_workspace()
        assert active is not None
        assert active.name == "test-active"

        # 切换激活（注册第二个工作区但不激活，再切换）
        ws_path2 = create_valid_workspace(tmp_path / "ws-active2")
        register_local("test-active2", str(ws_path2), "tdm", activate=False)
        assert set_active("test-active2") is True
        active = get_active_workspace()
        assert active.name == "test-active2"

        # 清理
        unregister("test-active")
        unregister("test-active2")

    def test_safe_resolve_in_bounds(self, tmp_path):
        """工作区内文件路径应可正常解析。"""
        from specstd.workspace import register_local, safe_resolve, unregister

        ws_path = create_valid_workspace(tmp_path / "ws-safe")
        register_local("test-safe", str(ws_path), "tdm", activate=True)

        path = safe_resolve("AGENTS.md")
        assert path is not None
        assert path.is_file()

        path = safe_resolve("specs/module1/feature1/spec.md")
        assert path is not None
        assert path.is_file()

        unregister("test-safe")

    def test_safe_resolve_out_of_bounds(self, tmp_path):
        """越界路径应返回 None。"""
        from specstd.workspace import register_local, safe_resolve, unregister

        ws_path = create_valid_workspace(tmp_path / "ws-oob")
        register_local("test-oob", str(ws_path), "tdm", activate=True)

        # 尝试用 ../ 越界
        path = safe_resolve("../../../../etc/passwd")
        assert path is None, "越界路径应返回 None"

        path = safe_resolve("../../../some-secret.txt")
        assert path is None

        unregister("test-oob")

    def test_read_agents_md(self, tmp_path):
        """AGENTS.md 读取应返回全量原文。"""
        from specstd.workspace import register_local, read_agents_md, unregister

        ws_path = create_valid_workspace(tmp_path / "ws-agents")
        register_local("test-agents", str(ws_path), "tdm", activate=True)

        content = read_agents_md()
        assert "Project Overview" in content
        assert "术语 Token" in content

        unregister("test-agents")

    def test_unregistered_workspace(self):
        """未注册的工作区应返回 None。"""
        from specstd.workspace import get_workspace
        info = get_workspace("nonexistent-workspace-12345")
        assert info is None
