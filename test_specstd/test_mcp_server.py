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
from specstd.workspace import register_local, unregister, drafts_dir
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
    def test_11_tools_registered(self):
        assert len(ALL_TOOLS) == 25  # 新增 sync_workspace 后 24→25

    def test_tool_names(self):
        names = {t.name for t in ALL_TOOLS}
        expected = {"read_spec", "list_spec_files", "list_scenarios",
                     "read_scenario", "next_scenario_id",
                     "query_registry", "write_draft", "undo_draft", "validate",
                     "read_run_report", "db_evidence",
                     "write_audit_report", "report_vulnerability",
                     "todo_write", "switch_mode",
                     "promote_draft",  # H-3/H-4: meta 工具；K-015: promote_draft
                     "check_dag", "run_scenario",  # K-021: DAG 预演 + 试执行
                     "promote_drafts",  # K-021⑥: 批量入库
                     "edit_dependency",  # K-027: DAG 依赖边编排
                     "suggest_deps",  # K-046: 依赖建议（确定性引擎）
                     "list_failures", "read_run_log",  # K-052: 失败索引 + 按任务号读日志
                     "scan_compliance",  # T-313: 全库格式合规缺口扫描
                     "sync_workspace"}  # 远端更新同步 + 会话级 dismiss
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

    # ── K-021①：双根扩展（Agent 可达 SpecGuard 全部内容）──

    def test_read_spec_sg_prefix(self, workspace):
        """sg:// 前缀强制 SpecGuard 仓库根。"""
        result = _call(spec_reader, "read_spec", {"path": "sg://contracts_baseline.json"})
        assert "fingerprint" in result[0].text or "version" in result[0].text

    def test_read_spec_sg_fallback(self, workspace):
        """工作区未命中时回退 SpecGuard 仓库根（仓库侧内容可达）。"""
        result = _call(spec_reader, "read_spec", {"path": "contracts_baseline.json"})
        assert "不存在" not in result[0].text
        assert "fingerprint" in result[0].text or "version" in result[0].text

    def test_read_spec_workspace_priority(self, workspace):
        """双根同名时工作区优先（AGENTS.md 两边都有，原行为不变）。"""
        result = _call(spec_reader, "read_spec", {"path": "AGENTS.md"})
        assert "术语 Token" in result[0].text  # 工作区样例独有（SpecGuard 仓库根的 AGENTS.md 无此节）

    def test_read_spec_sg_blocked_sensitive(self, workspace):
        """敏感路径拒读：用户 DB / 会话记录 / .git / .env。"""
        for p in ("sg://workbench/backend/data/workbench.db",
                  "sg://agent/sessions/x/y.jsonl",
                  "sg://.git/config",
                  "sg://.env.devops"):
            result = _call(spec_reader, "read_spec", {"path": p})
            assert "OUT_OF_SCOPE" in result[0].text, f"{p} 应被拒读"

    def test_read_spec_sg_traversal(self, workspace):
        result = _call(spec_reader, "read_spec", {"path": "sg://../../etc/passwd"})
        assert "OUT_OF_SCOPE" in result[0].text

    def test_read_spec_binary_guard(self, workspace, tmp_path):
        """非办公二进制文件（zip 等）返回明确提示而非乱码/异常。

        K-030 起 xlsx/docx/pdf 转为文本预览（见 test_file_preview.py），
        其余二进制仍拒读。
        """
        z = tmp_path / "ws" / "specs" / "module1" / "feature1" / "data.zip"
        z.write_bytes(b"PK\x03\x04 fake zip")
        result = _call(spec_reader, "read_spec",
                       {"path": "specs/module1/feature1/data.zip"})
        assert "二进制" in result[0].text


# ══════════════════════════════════════════════════════════
# scenario_tools
# ══════════════════════════════════════════════════════════

class TestScenarioTools:
    def test_list_scenarios(self):
        result = _call(scenario_tools, "list_scenarios", {})
        data = json.loads(result[0].text)
        # K-xxx：返回 {total, summary, scenarios}——summary 为确定性分类摘要
        assert data["total"] > 0
        ids = [s["id"] for s in data["scenarios"]]
        assert "PP-RC-001" in ids
        assert sum(data["summary"]["by_module"].values()) == data["total"]
        assert data["summary"]["by_tag"]

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

    # ── K-021③：check_dag DAG 预演 ──

    def test_check_dag_library(self):
        """场景库建图：无环、有拓扑序（离线，真实场景库）。"""
        result = _call(scenario_tools, "check_dag", {"include_drafts": False})
        data = json.loads(result[0].text)
        assert data["ok"], f"场景库不应有环/漂移: {data}"
        assert data["scenario_count"] > 0
        assert len(data["topo_order"]) == data["scenario_count"]

    def test_check_dag_cycle_detected(self, workspace):
        """并入草稿后检测到循环依赖 → ok=False + cycles。"""
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "CYC-A-001.yaml").write_text(
            "id: CYC-A-001\ntitle: 环A\ndepends_on: [CYC-B-001]\n"
            "flow:\n  - call: {method: GET, path: /api, save: r}\n"
            "verify:\n  - status: {eq: 200}\n", encoding="utf-8")
        (d / "CYC-B-001.yaml").write_text(
            "id: CYC-B-001\ntitle: 环B\ndepends_on: [CYC-A-001]\n"
            "flow:\n  - call: {method: GET, path: /api, save: r}\n"
            "verify:\n  - status: {eq: 200}\n", encoding="utf-8")
        result = _call(scenario_tools, "check_dag", {"include_drafts": True})
        data = json.loads(result[0].text)
        assert not data["ok"]
        assert data["cycles"], "应报告循环依赖"
        assert "CYC-A-001" in data["cycles"][0]

    def test_check_dag_focus(self, workspace):
        """focus：输出上游闭包与下游依赖者（草稿依赖真实场景）。"""
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "FOCUS-TEST-001.yaml").write_text(
            "id: FOCUS-TEST-001\ntitle: 焦点\ndepends_on: [IS-PREP-002]\n"
            "flow:\n  - call: {method: GET, path: /api, save: r}\n"
            "verify:\n  - status: {eq: 200}\n", encoding="utf-8")
        result = _call(scenario_tools, "check_dag",
                       {"include_drafts": True, "focus": "FOCUS-TEST-001"})
        data = json.loads(result[0].text)
        assert data["focus"]["upstream_chain"] == ["IS-PREP-002"]
        assert data["focus"]["dep_status"][0]["status"] in ("match", "minor_drift")

    def test_check_dag_dangling_dep(self, workspace):
        """草稿悬空依赖 → orphans 报告（ok=False）。"""
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "ORPH-001.yaml").write_text(
            "id: ORPH-001\ntitle: 孤儿\ndepends_on: [NOPE-999]\n"
            "flow:\n  - call: {method: GET, path: /api, save: r}\n"
            "verify:\n  - status: {eq: 200}\n", encoding="utf-8")
        result = _call(scenario_tools, "check_dag", {"include_drafts": True})
        data = json.loads(result[0].text)
        assert not data["ok"]
        assert "ORPH-001" in data["orphans"]
        assert data["orphans"]["ORPH-001"] == ["NOPE-999"]

    def test_run_scenario_param_guard(self):
        """run_scenario 参数守卫：scenario_id 与 draft 必须二选一（离线快速失败）。"""
        r1 = _call(scenario_tools, "run_scenario", {})
        assert "二选一" in r1[0].text
        r2 = _call(scenario_tools, "run_scenario",
                   {"scenario_id": "X-001", "draft": "Y.yaml"})
        assert "二选一" in r2[0].text

    # ── K-027：edit_dependency 依赖边编排 ──

    @pytest.fixture()
    def dag_lib(self, tmp_path, monkeypatch):
        """隔离场景库：A（无依赖）+ B（无依赖），指向 tmp 并清缓存。"""
        lib = tmp_path / "scenarios"
        lib.mkdir()
        (lib / "A-001.yaml").write_text(
            "id: A-001\ntitle: 上游\nversion: \"1.0\"\n"
            "flow:\n  - call: {method: GET, path: /a, save: r}\n"
            "verify:\n  - status: {eq: 200}\n", encoding="utf-8")
        (lib / "B-001.yaml").write_text(
            "id: B-001\ntitle: 下游\nversion: \"0.1\"\n"
            "flow:\n  - call: {method: GET, path: /b, save: r}\n"
            "verify:\n  - status: {eq: 200}\n", encoding="utf-8")
        from services import scenario_store
        monkeypatch.setattr(scenario_store, "SCENARIOS_ROOT", lib)
        monkeypatch.setattr(scenario_tools, "SCENARIOS_ROOT", lib)
        # K-xxx：场景库重定向时台账投影一并重定向，防污染真实 workbench.db
        monkeypatch.setattr(scenario_store, "_LEDGER_DB_PATH", tmp_path / "ledger.db")
        scenario_store._cache["fingerprint"] = None
        scenario_store._cache["scenarios"] = None
        scenario_store._cache["graph"] = None
        yield lib
        scenario_store._cache["fingerprint"] = None
        scenario_store._cache["scenarios"] = None
        scenario_store._cache["graph"] = None

    def test_edit_dependency_add(self, dag_lib):
        """add：B 依赖 A（版本期望自动推导 ^1），depends_on 写进 YAML。"""
        r = _call(scenario_tools, "edit_dependency",
                  {"scenario_id": "B-001", "action": "add", "dep_id": "A-001"})
        data = json.loads(r[0].text)
        assert data["ok"], data
        assert any(d["id"] == "A-001" and d["version"] == "^1" for d in data["depends_on"])
        content = (dag_lib / "B-001.yaml").read_text(encoding="utf-8")
        assert "A-001" in content

    def test_edit_dependency_remove(self, dag_lib):
        """add 后 remove：depends_on 清空（YAML 注释保留——文本外科手术）。"""
        _call(scenario_tools, "edit_dependency",
              {"scenario_id": "B-001", "action": "add", "dep_id": "A-001"})
        r = _call(scenario_tools, "edit_dependency",
                  {"scenario_id": "B-001", "action": "remove", "dep_id": "A-001"})
        data = json.loads(r[0].text)
        assert data["ok"], data
        assert not any(d["id"] == "A-001" for d in data["depends_on"])

    def test_edit_dependency_cycle_rejected(self, dag_lib):
        """环校验：B→A 后再加 A→B → cycle 拒绝。"""
        _call(scenario_tools, "edit_dependency",
              {"scenario_id": "B-001", "action": "add", "dep_id": "A-001"})
        r = _call(scenario_tools, "edit_dependency",
                  {"scenario_id": "A-001", "action": "add", "dep_id": "B-001"})
        data = json.loads(r[0].text)
        assert not data["ok"] and data["error_code"] == "cycle"

    def test_edit_dependency_guards(self, dag_lib):
        """守卫：自依赖 / 场景不存在 / 依赖目标不存在。"""
        r1 = _call(scenario_tools, "edit_dependency",
                   {"scenario_id": "B-001", "action": "add", "dep_id": "B-001"})
        assert "自依赖" in r1[0].text
        r2 = _call(scenario_tools, "edit_dependency",
                   {"scenario_id": "NOPE-001", "action": "add", "dep_id": "A-001"})
        assert "不存在" in r2[0].text
        r3 = _call(scenario_tools, "edit_dependency",
                   {"scenario_id": "B-001", "action": "add", "dep_id": "NOPE-999"})
        assert "不存在" in r3[0].text


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
    def test_write_draft_create(self, tmp_path, workspace):
        result = _call(draft_writer, "write_draft", {
            "filename": "test-draft-create.yaml",
            "content": "id: TEST-DRAFT\ntitle: 测试\nflow: []\nverify: []\n",
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert data["action"] == "create"
        # 清理（F-1-2: 路径在工作区 .specguard/drafts/ 下）
        (drafts_dir() / "test-draft-create.yaml").unlink(missing_ok=True)

    def test_write_draft_overwrite_denied(self, tmp_path, workspace):
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
        (drafts_dir() / "test-overwrite.yaml").unlink(missing_ok=True)

    def test_write_draft_out_of_scope(self):
        result = _call(draft_writer, "write_draft", {
            "filename": "../escape.yaml",
            "content": "id: EVIL\n",
        })
        assert "OUT_OF_SCOPE" in result[0].text

    def test_write_draft_patch(self, tmp_path, workspace):
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
        (drafts_dir() / "test-patch.yaml").unlink(missing_ok=True)


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

    def test_validate_missing_covers_warns(self, workspace):
        """K-020：doc.covers 缺失必须 WARN（此前零告警——Agent 在 ANCHOR 误报后
        学会「删 covers 就能过」，批量产生 30 份无锚点草稿，FR 溯源断裂）。"""
        yaml_content = """id: TEST-VAL-005
version: 0.1
title: 无covers场景
doc:
  given: g
  when: w
  then: t
flow:
  - call: {method: GET, path: /api/test, save: resp}
verify:
  - status: {eq: 200}
"""
        result = _call(validator, "validate", {"content": yaml_content})
        data = json.loads(result[0].text)
        cover_warns = [f for f in data["findings"] if f["rule"] == "COVERS" and f["level"] == "WARN"]
        assert len(cover_warns) > 0, "缺失 covers 应报 WARN"
        assert any("强制" in f["message"] or "锚点" in f["message"] for f in cover_warns)
        # WARN 不阻断（verdict 由 ERROR 决定）
        assert data["summary"]["error"] == 0

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

    # ── K-021②：T4/T5/T7 依赖连通性（此前 Agent 的 validate 不查 depends_on）──

    _DEP_YAML = """id: TEST-DEP-001
version: 0.1
title: 依赖测试
doc:
  covers: [FR-001]
depends_on: %s
flow:
  - call: {method: GET, path: /api/test, save: resp}
verify:
  - status: {eq: 200}
"""

    def test_validate_t4_dangling_dep(self, workspace, monkeypatch):
        """depends_on 悬空引用 → T4 ERROR（此前不查，到发布门禁才炸）。"""
        monkeypatch.setattr(validator, "_scenario_index", lambda: {})
        result = _call(validator, "validate",
                       {"content": self._DEP_YAML % "[NOPE-999]"})
        data = json.loads(result[0].text)
        t4 = [f for f in data["findings"] if f["rule"] == "T4" and f["level"] == "ERROR"]
        assert t4 and "NOPE-999" in t4[0]["message"]
        assert data["verdict"] == "REJECT"

    def test_validate_t4_draft_dep_ok(self, workspace, monkeypatch):
        """依赖 drafts/ 同批次草稿（生成期合法）→ 无 T4 ERROR。"""
        monkeypatch.setattr(validator, "_scenario_index", lambda: {
            "TL-PREP-001": {"version": "0.1", "source": "draft:TL-PREP-001.yaml"}})
        result = _call(validator, "validate",
                       {"content": self._DEP_YAML % "[{id: TL-PREP-001, version: ^0}]"})
        data = json.loads(result[0].text)
        t4_err = [f for f in data["findings"] if f["rule"] == "T4" and f["level"] == "ERROR"]
        assert not t4_err, f"草稿依赖不应误报: {t4_err}"

    def test_validate_t4_version_drift(self, workspace, monkeypatch):
        """版本期望不可满足（^1 vs 实际 0.1）→ T4 ERROR。"""
        monkeypatch.setattr(validator, "_scenario_index", lambda: {
            "TL-PREP-001": {"version": "0.1", "source": "scenarios"}})
        result = _call(validator, "validate",
                       {"content": self._DEP_YAML % "[{id: TL-PREP-001, version: ^1}]"})
        data = json.loads(result[0].text)
        t4 = [f for f in data["findings"] if f["rule"] == "T4" and f["level"] == "ERROR"]
        assert t4 and "不可满足" in t4[0]["message"]

    def test_validate_t7_string_dep_warns(self, workspace, monkeypatch):
        """字符串形式依赖（未声明版本期望）→ T7 WARN 建议 ^X。"""
        monkeypatch.setattr(validator, "_scenario_index", lambda: {
            "TL-PREP-001": {"version": "0.1", "source": "scenarios"}})
        result = _call(validator, "validate",
                       {"content": self._DEP_YAML % "[TL-PREP-001]"})
        data = json.loads(result[0].text)
        t7 = [f for f in data["findings"] if f["rule"] == "T7" and f["level"] == "WARN"]
        assert t7 and "^X" in t7[0]["message"]

    def test_validate_t5_orphan_warns(self, workspace, monkeypatch):
        """scenario 类型无依赖且非 prep → T5 WARN（孤例提示）。"""
        monkeypatch.setattr(validator, "_scenario_index", lambda: {})
        result = _call(validator, "validate",
                       {"content": self._DEP_YAML % "[]"})
        data = json.loads(result[0].text)
        t5 = [f for f in data["findings"] if f["rule"] == "T5" and f["level"] == "WARN"]
        assert t5, "无依赖 scenario 应报 T5 WARN"


# ══════════════════════════════════════════════════════════
# sync_workspace（远端更新同步 + 会话级 dismiss）
# ══════════════════════════════════════════════════════════

class TestSyncWorkspace:
    """远端更新提示 → sync_workspace 闭环（read_spec 注入决策提示 → 征询用户 → 同步/dismiss）。"""

    def test_sync_local_workspace_not_git(self, workspace):
        """local 工作区调 sync → ok=False（不是 git 型，不支持拉取）。"""
        from specstd.workspace import reset_sync_dismissed
        reset_sync_dismissed()
        r = _call(spec_reader, "sync_workspace", {"action": "sync"})
        data = json.loads(r[0].text)
        assert data["ok"] is False
        assert "不是 git 型" in data["error"]
        reset_sync_dismissed()

    def test_dismiss_then_read_spec_silent(self, workspace, monkeypatch):
        """dismiss 后 read_spec 不再注入远程提示（即便 remote_file_marks 报告有更新）。"""
        import specstd.workspace as ws_mod
        from specstd.workspace import reset_sync_dismissed
        reset_sync_dismissed()
        # 强制 remote_file_marks 报告远端有更新（模拟 git 工作区远端领先场景）
        monkeypatch.setattr(ws_mod, "remote_file_marks",
                            lambda paths, name=None: {paths[0]: "[远程已更新]"})
        # dismiss 前：read_spec 应含远程状态决策提示 + sync_workspace 引导
        r1 = _call(spec_reader, "read_spec", {"path": "AGENTS.md"})
        assert "[远程状态]" in r1[0].text
        assert "sync_workspace" in r1[0].text
        # 用户拒绝同步 → dismiss
        r_d = _call(spec_reader, "sync_workspace", {"action": "dismiss"})
        d = json.loads(r_d[0].text)
        assert d["ok"] is True and d["action"] == "dismiss"
        # dismiss 后：read_spec 不再含远程状态提示
        r2 = _call(spec_reader, "read_spec", {"path": "AGENTS.md"})
        assert "[远程状态]" not in r2[0].text
        reset_sync_dismissed()

    def test_sync_unknown_action_rejected(self, workspace):
        """未知 action → 明确报错并列出合法值。"""
        from specstd.workspace import reset_sync_dismissed
        reset_sync_dismissed()
        r = _call(spec_reader, "sync_workspace", {"action": "bogus"})
        assert "sync" in r[0].text and "dismiss" in r[0].text
        reset_sync_dismissed()
