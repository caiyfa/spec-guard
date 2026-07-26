"""MCP 工具层测试。

验证：
1. 8 个工具正确注册
2. spec_reader 越界访问拒绝
3. scenario_tools 基本功能
4. registry_query 基本功能
5. draft_writer 路径守卫 + 禁覆盖
6. validator covers 校验
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from test_specstd.helpers import create_valid_workspace
from specstd.workspace import register_local, unregister
from mcp_server.tools import spec_reader, scenario_tools, registry_query, draft_writer, validator
from mcp_server.server import ALL_TOOLS


def _call(module, name, arguments):
    """同步调用异步 handle 函数。"""
    return asyncio.run(module.handle(name, arguments))


@pytest.fixture
def workspace(tmp_path):
    """创建并注册一个合规工作区。"""
    ws_path = create_valid_workspace(tmp_path / "ws")
    register_local("test-mcp", str(ws_path), "tdm", activate=True)
    yield "test-mcp"
    unregister("test-mcp")


# ══════════════════════════════════════════════════════════
# 工具注册
# ══════════════════════════════════════════════════════════

class TestToolRegistration:
    def test_10_tools_registered(self):
        assert len(ALL_TOOLS) == 10

    def test_tool_names(self):
        names = {t.name for t in ALL_TOOLS}
        expected = {"read_spec", "list_spec_files", "list_scenarios",
                     "read_scenario", "next_scenario_id",
                     "query_registry", "write_draft", "validate",
                     "read_run_report", "db_evidence"}
        assert names == expected


# ══════════════════════════════════════════════════════════
# spec_reader
# ══════════════════════════════════════════════════════════

class TestSpecReader:
    def test_read_spec(self, workspace):
        result = _call(spec_reader, "read_spec", {"path": "AGENTS.md"})
        assert "Project Overview" in result[0].text

    def test_read_spec_spec_md(self, workspace):
        result = _call(spec_reader, "read_spec", {"path": "specs/module1/feature1/spec.md"})
        assert "FR-001" in result[0].text

    def test_read_spec_out_of_scope(self, workspace):
        result = _call(spec_reader, "read_spec", {"path": "../../../etc/passwd"})
        assert "OUT_OF_SCOPE" in result[0].text

    def test_read_spec_nonexistent(self, workspace):
        result = _call(spec_reader, "read_spec", {"path": "nonexistent.md"})
        assert "不存在" in result[0].text

    def test_list_spec_files(self, workspace):
        result = _call(spec_reader, "list_spec_files", {})
        files = json.loads(result[0].text)
        paths = [f["path"] for f in files]
        assert any("AGENTS.md" in p for p in paths)
        assert any("spec.md" in p for p in paths)

    def test_list_spec_files_delta_marked(self, workspace):
        result = _call(spec_reader, "list_spec_files", {"subdir": "changes"})
        files = json.loads(result[0].text)
        delta_files = [f for f in files if f["is_delta"]]
        assert len(delta_files) > 0


# ══════════════════════════════════════════════════════════
# scenario_tools
# ══════════════════════════════════════════════════════════

class TestScenarioTools:
    def test_list_scenarios(self):
        result = _call(scenario_tools, "list_scenarios", {})
        scenarios = json.loads(result[0].text)
        assert len(scenarios) > 0
        ids = [s["id"] for s in scenarios]
        assert "PP-RC-001" in ids

    def test_read_scenario(self):
        result = _call(scenario_tools, "read_scenario", {"id": "PP-RC-001"})
        assert "PP-RC-001" in result[0].text

    def test_read_scenario_not_found(self):
        result = _call(scenario_tools, "read_scenario", {"id": "NONEXISTENT-999"})
        assert "不存在" in result[0].text

    def test_next_scenario_id(self):
        result = _call(scenario_tools, "next_scenario_id", {"prefix": "PP", "type_abbr": "RC"})
        data = json.loads(result[0].text)
        assert "next_id" in data
        assert data["next_id"].startswith("PP-RC-")


# ══════════════════════════════════════════════════════════
# registry_query
# ══════════════════════════════════════════════════════════

class TestRegistryQuery:
    def test_query_tool(self):
        result = _call(registry_query, "query_registry", {"type": "tool"})
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_query_oracle(self):
        result = _call(registry_query, "query_registry", {"type": "oracle"})
        data = json.loads(result[0].text)
        names = [o["name"] for o in data]
        assert "snapshot_frozen" in names

    def test_query_step(self):
        result = _call(registry_query, "query_registry", {"type": "step"})
        data = json.loads(result[0].text)
        types = [s["type"] for s in data]
        assert "call" in types
        assert "tool" in types


# ══════════════════════════════════════════════════════════
# draft_writer
# ══════════════════════════════════════════════════════════

class TestDraftWriter:
    def test_write_draft_create(self, tmp_path):
        result = _call(draft_writer, "write_draft", {
            "filename": "test-draft-create.yaml",
            "content": "id: TEST-DRAFT\ntitle: 测试\nflow: []\nverify: []\n",
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert data["action"] == "create"
        # 清理
        (SG_ROOT / "drafts" / "test-draft-create.yaml").unlink(missing_ok=True)

    def test_write_draft_overwrite_denied(self, tmp_path):
        # 先创建文件
        _call(draft_writer, "write_draft", {
            "filename": "test-overwrite.yaml",
            "content": "id: FIRST\n",
        })
        # 再尝试覆盖
        result = _call(draft_writer, "write_draft", {
            "filename": "test-overwrite.yaml",
            "content": "id: SECOND\n",
        })
        assert "OVERWRITE_DENIED" in result[0].text
        # 清理
        (SG_ROOT / "drafts" / "test-overwrite.yaml").unlink(missing_ok=True)

    def test_write_draft_out_of_scope(self):
        result = _call(draft_writer, "write_draft", {
            "filename": "../escape.yaml",
            "content": "id: EVIL\n",
        })
        assert "OUT_OF_SCOPE" in result[0].text

    def test_write_draft_patch(self, tmp_path):
        # 先创建
        _call(draft_writer, "write_draft", {
            "filename": "test-patch.yaml",
            "content": "id: FIRST\n",
        })
        # 再 patch
        result = _call(draft_writer, "write_draft", {
            "filename": "test-patch.yaml",
            "content": "# patch content\n",
            "mode": "patch",
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert data["action"] == "patch"
        # 清理
        (SG_ROOT / "drafts" / "test-patch.yaml").unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════
# validator
# ══════════════════════════════════════════════════════════

class TestValidator:
    def test_validate_valid_scenario(self, workspace):
        yaml_content = """id: TEST-VAL-001
version: 0.1
title: 测试校验
doc:
  covers: [FR-001]
flow:
  - call: {method: GET, path: /api/test, save: resp}
verify:
  - status: {eq: 200}
"""
        result = _call(validator, "validate", {"content": yaml_content})
        data = json.loads(result[0].text)
        # FR-001 在合规工作区中存在，不应有 covers ERROR
        cover_errors = [f for f in data["findings"] if f["rule"] == "ANCHOR" and f["level"] == "ERROR"]
        assert len(cover_errors) == 0, f"有效的 covers 不应报错: {cover_errors}"

    def test_validate_fabricated_covers(self, workspace):
        yaml_content = """id: TEST-VAL-002
version: 0.1
title: 测试编造FR
doc:
  covers: [FR-099]
flow:
  - call: {method: GET, path: /api/test, save: resp}
verify:
  - status: {eq: 200}
"""
        result = _call(validator, "validate", {"content": yaml_content})
        data = json.loads(result[0].text)
        cover_errors = [f for f in data["findings"] if f["rule"] == "ANCHOR" and f["level"] == "ERROR"]
        assert len(cover_errors) > 0, "编造的 FR 应报 COVER 错误"
        assert any("FR-099" in f["message"] for f in cover_errors)

    def test_validate_empty_flow_verify(self, workspace):
        yaml_content = """id: TEST-VAL-003
version: 0.1
title: 空场景
flow: []
verify: []
"""
        result = _call(validator, "validate", {"content": yaml_content})
        data = json.loads(result[0].text)
        t1_errors = [f for f in data["findings"] if f["rule"] == "T1" and f["level"] == "ERROR"]
        assert len(t1_errors) > 0, "空 flow/verify 应报 T1 错误"

    def test_validate_unregistered_tool(self, workspace):
        yaml_content = """id: TEST-VAL-004
version: 0.1
title: 未注册tool
flow:
  - tool: {use: nonexistent_tool, with: {}}
verify: []
"""
        result = _call(validator, "validate", {"content": yaml_content})
        data = json.loads(result[0].text)
        registry_errors = [f for f in data["findings"] if f["rule"] == "REGISTRY"]
        assert len(registry_errors) > 0, "未注册的 tool 应报 REGISTRY 错误"

    def test_validate_yaml_error(self, workspace):
        result = _call(validator, "validate", {"content": "id: BAD\n  bad: [unclosed"})
        data = json.loads(result[0].text)
        assert data["verdict"] == "ERROR"
