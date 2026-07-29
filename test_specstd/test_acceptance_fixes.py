"""验收漏洞修复测试（V1-V17 / D1-D2 / V4 / V8-V10）。

每类修复至少一个确定性断言，全部离线可跑。
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from test_specstd.helpers import create_valid_workspace  # noqa: E402


# ══════════════════════════════════════════════════════════
# V1 工作区 name 路径穿越
# ══════════════════════════════════════════════════════════

class TestV1WorkspaceNameTraversal:
    def test_clone_path_traversal_rejected(self):
        from specstd.workspace import _clone_path_for
        with pytest.raises(ValueError):
            _clone_path_for("../../engine")

    def test_validate_name_rules(self):
        from specstd.workspace import _validate_name
        assert _validate_name("../../engine") is not None
        assert _validate_name("a/b") is not None
        assert _validate_name("a\\b") is not None
        assert _validate_name("..") is not None
        assert _validate_name("") is not None
        assert _validate_name("tdm") is None
        assert _validate_name("spec-pbs_2") is None

    def test_register_local_evil_name(self, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        ws = create_valid_workspace(tmp_path / "repo")
        result = wsm.register_local("../../engine", str(ws), "tdm")
        assert result["ok"] is False
        assert "非法" in result["error"]

    def test_register_git_evil_name_no_clone(self, tmp_path, monkeypatch):
        """恶意 name 应在 clone 之前被拒（不触发任何 rmtree/网络）。"""
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
        result = wsm.register_git("../../victim", "http://example.com/x.git", "tdm")
        assert result["ok"] is False
        assert "非法" in result["error"]
        assert not (tmp_path / "victim").exists()

    def test_unregister_evil_name(self, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        assert wsm.unregister("../../engine") is False


# ══════════════════════════════════════════════════════════
# V2 合规门禁不可被客户端跳过 / V10 covers 闸客户端不可跳过
# ══════════════════════════════════════════════════════════

class TestV2V10GateNotBypassable:
    def test_register_models_have_no_conformance_flag(self):
        backend = SG_ROOT / "workbench" / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from routers.workspace import RegisterLocalBody, RegisterGitBody
        assert "run_conformance" not in RegisterLocalBody.model_fields
        assert "run_conformance" not in RegisterGitBody.model_fields

    def test_trigger_model_has_no_skip_flag(self):
        backend = SG_ROOT / "workbench" / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from routers.runs import TriggerBody
        assert "skip_covers_check" not in TriggerBody.model_fields


# ══════════════════════════════════════════════════════════
# V3 subdir 路径穿越（MCP list_spec_files）
# ══════════════════════════════════════════════════════════

class TestV3SubdirTraversal:
    def _setup_active_workspace(self, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        ws = create_valid_workspace(tmp_path / "repo")
        result = wsm.register_local("tdm", str(ws), "tdm", activate=True)
        assert result["ok"] is True
        return ws

    def test_list_spec_files_out_of_scope(self, tmp_path, monkeypatch):
        self._setup_active_workspace(tmp_path, monkeypatch)
        from mcp_server.tools import spec_reader
        import asyncio
        out = asyncio.run(spec_reader.handle("list_spec_files", {"subdir": "../../"}))
        assert "OUT_OF_SCOPE" in out[0].text

    def test_list_spec_files_legal_subdir(self, tmp_path, monkeypatch):
        self._setup_active_workspace(tmp_path, monkeypatch)
        from mcp_server.tools import spec_reader
        import asyncio
        out = asyncio.run(spec_reader.handle("list_spec_files", {"subdir": "specs"}))
        files = json.loads(out[0].text)
        assert any(f["path"].endswith("spec.md") for f in files)


# ══════════════════════════════════════════════════════════
# V4 schema 结构级签名
# ══════════════════════════════════════════════════════════

class TestV4SchemaSignature:
    def _api(self, props):
        return {
            "paths": {
                "/profile": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "properties": props}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    def test_response_field_change_detected(self):
        from specstd.signature import sign_api_yaml
        sig_a = sign_api_yaml(self._api({"name": {"type": "string"}}))
        sig_b = sign_api_yaml(self._api({"name": {"type": "string"},
                                         "politicalStatusName": {"type": "string"}}))
        assert sig_a["/profile"]["get"] != sig_b["/profile"]["get"]

    def test_description_change_ignored(self):
        from specstd.signature import sign_api_yaml
        sig_a = sign_api_yaml(self._api({"name": {"type": "string", "description": "姓名"}}))
        sig_b = sign_api_yaml(self._api({"name": {"type": "string", "description": "改名后的描述"}}))
        assert sig_a["/profile"]["get"] == sig_b["/profile"]["get"]

    def test_field_type_change_detected(self):
        from specstd.signature import sign_api_yaml
        sig_a = sign_api_yaml(self._api({"score": {"type": "string"}}))
        sig_b = sign_api_yaml(self._api({"score": {"type": "integer"}}))
        assert sig_a["/profile"]["get"] != sig_b["/profile"]["get"]


# ══════════════════════════════════════════════════════════
# V8 注册表动态化 / V9 validator oracle 校验
# ══════════════════════════════════════════════════════════

class TestV8V9LiveRegistry:
    def test_oracle_list_from_live_registry(self):
        from mcp_server.tools.live_registry import list_oracles
        names = {o["name"] for o in list_oracles()}
        assert "snapshot_frozen" in names
        assert "profile_matches_db" in names

    def test_query_registry_oracle_dynamic(self):
        import asyncio
        from mcp_server.tools import registry_query
        out = asyncio.run(registry_query.handle("query_registry", {"type": "oracle"}))
        names = {o["name"] for o in json.loads(out[0].text)}
        assert "snapshot_frozen" in names

    def test_validator_rejects_fabricated_oracle(self):
        from mcp_server.tools.validator import validate_scenario_content
        content = """
id: XX-TEST-001
version: "0.1"
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - oracle: fabricated_oracle_xyz
"""
        report = validate_scenario_content(content)
        reg_errors = [f for f in report["findings"]
                      if f["rule"] == "REGISTRY" and "fabricated_oracle_xyz" in f["message"]]
        assert reg_errors, f"编造 oracle 应被拦截: {report['findings']}"
        assert reg_errors[0]["level"] == "ERROR"

    def test_validator_accepts_registered_oracle(self):
        from mcp_server.tools.validator import validate_scenario_content
        content = """
id: XX-TEST-002
version: "0.1"
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - oracle: snapshot_frozen
"""
        report = validate_scenario_content(content)
        reg_errors = [f for f in report["findings"] if f["rule"] == "REGISTRY"]
        assert not reg_errors, f"已注册 oracle 不应报错: {reg_errors}"

    def test_validator_parametrized_oracle_form(self):
        """参数化形态 {name: xxx, params: {...}} 同样受校验。"""
        from mcp_server.tools.validator import validate_scenario_content
        content = """
id: XX-TEST-003
version: "0.1"
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - oracle: {name: fabricated_xyz, params: {k: v}}
"""
        report = validate_scenario_content(content)
        assert any("fabricated_xyz" in f["message"] for f in report["findings"]
                   if f["rule"] == "REGISTRY")


# ══════════════════════════════════════════════════════════
# V11 session_id 穿越 / V13 run_id 穿越
# ══════════════════════════════════════════════════════════

class TestV11V13IdGuards:
    def test_session_id_traversal_rejected(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(tmp_path)
        with pytest.raises(ValueError):
            sm.save("../../evil", [{"role": "user", "content": "x"}])
        with pytest.raises(ValueError):
            sm.load("../../evil")
        with pytest.raises(ValueError):
            sm.append("a/b", {})

    def test_session_roundtrip(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(tmp_path)
        sid = sm.create()
        sm.save(sid, [{"role": "user", "content": "你好"}])
        assert sm.load(sid)[0]["content"] == "你好"

    def test_run_id_traversal_rejected(self):
        import asyncio
        from mcp_server.tools import attribution
        out = asyncio.run(attribution.handle("read_run_report", {"run_id": "../../scenarios"}))
        assert "OUT_OF_SCOPE" in out[0].text

    def test_run_id_not_found(self):
        import asyncio
        from mcp_server.tools import attribution
        out = asyncio.run(attribution.handle("read_run_report", {"run_id": "1900-01-01_000000"}))
        assert "不存在" in out[0].text


# ══════════════════════════════════════════════════════════
# V12 SQL 只读守卫逃逸关键词
# ══════════════════════════════════════════════════════════

class TestV12SqlGuard:
    def _call(self, sql):
        import asyncio
        from mcp_server.tools import attribution
        return asyncio.run(attribution.handle("db_evidence", {"sql": sql}))[0].text

    def test_for_update_rejected(self):
        assert "危险子句" in self._call("SELECT * FROM tdm_emp_employee FOR UPDATE")

    def test_into_outfile_rejected(self):
        assert "危险子句" in self._call("SELECT * FROM t INTO OUTFILE '/tmp/x'")

    def test_lock_in_share_mode_rejected(self):
        assert "危险子句" in self._call("SELECT * FROM t LOCK IN SHARE MODE")

    def test_normal_select_passes_guard(self):
        # DB 未配置时会返回连接错误，但不应被只读守卫拦截
        out = self._call("SELECT 1")
        assert "危险子句" not in out
        assert "仅允许" not in out


# ══════════════════════════════════════════════════════════
# V14 webhook SSRF / V15 状态机 / D2 回执
# ══════════════════════════════════════════════════════════

class TestV14V15D2:
    def test_webhook_url_validation(self):
        from feedback.notify import validate_webhook_url
        assert validate_webhook_url("http://open.feishu.cn/x") is not None          # 仅 https
        assert validate_webhook_url("https://169.254.169.254/latest") is not None  # IP 字面量
        assert validate_webhook_url("https://127.0.0.1/x") is not None
        assert validate_webhook_url("https://evil.example.com/x") is not None      # 非白名单
        assert validate_webhook_url("https://open.feishu.cn/open-apis/bot/v2/hook/abc") is None
        assert validate_webhook_url("https://abc.feishu.cn/hook/abc") is None      # 泛域名命中

    def test_webhook_url_whitelist_env(self, monkeypatch):
        from feedback.notify import validate_webhook_url
        monkeypatch.setenv("SG_NOTIFY_ALLOWED_HOSTS", "hook.internal.corp")
        assert validate_webhook_url("https://hook.internal.corp/x") is None
        assert validate_webhook_url("https://open.feishu.cn/x") is not None

    def test_register_rejects_bad_url(self, tmp_path):
        from feedback.notify import NotifyRegistry
        reg = NotifyRegistry(tmp_path / "registry.json", tmp_path / "receipts.jsonl")
        with pytest.raises(ValueError):
            reg.register("tdm", "PP-*", "http://10.0.0.1/hook")

    def test_receipt_written_on_send(self, tmp_path, monkeypatch):
        from feedback import notify as notify_mod
        # 拦截出站请求，避免真实网络调用
        class FakeResp:
            status_code = 200
        monkeypatch.setattr(notify_mod.httpx, "post", lambda *a, **k: FakeResp())

        reg = notify_mod.NotifyRegistry(tmp_path / "registry.json", tmp_path / "receipts.jsonl")
        reg.register("tdm", "PP-*", "https://open.feishu.cn/hook/abc", events=["fail"])
        results = reg.send_notification("tdm", "PP-RC-005", "fail", "FAIL", "断言失败")
        assert results and results[0]["ok"] is True

        lines = (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        receipt = json.loads(lines[0])
        assert receipt["scenario_id"] == "PP-RC-005"
        assert receipt["matched"] == 1
        assert receipt["results"][0]["ok"] is True

    def test_ledger_illegal_transition(self, tmp_path):
        from feedback.ledger import FeedbackLedger
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create("测试条目", "loop_b")
        # pending → in_progress → closed 合法
        ledger.transition(entry["spq_id"], "in_progress")
        ledger.transition(entry["spq_id"], "closed")
        # closed 为终态
        with pytest.raises(ValueError):
            ledger.transition(entry["spq_id"], "pending")

    def test_ledger_full_url_not_in_list(self, tmp_path):
        from feedback.notify import NotifyRegistry
        reg = NotifyRegistry(tmp_path / "registry.json", tmp_path / "receipts.jsonl")
        reg.register("tdm", "*", "https://open.feishu.cn/hook/secret-token-12345")
        for wh in reg.list():
            assert "url" not in wh
            assert "secret-token-12345" not in json.dumps(wh)


# ══════════════════════════════════════════════════════════
# V16 anchors 死代码清除后扫描正常 / V17 注册表读写
# ══════════════════════════════════════════════════════════

class TestV16V17:
    def test_scan_anchors_sane(self, tmp_path):
        from specstd.anchors import scan_anchors
        ws = create_valid_workspace(tmp_path / "repo")
        anchors = scan_anchors(ws)
        assert "FR-001" in anchors
        assert anchors["FR-001"].ac_ids  # AC 提取正常

    def test_registry_roundtrip(self, tmp_path, monkeypatch):
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        ws = create_valid_workspace(tmp_path / "repo")
        wsm.register_local("tdm", str(ws), "tdm")
        # 重新加载验证持久化（原子写后内容完整）
        loaded = wsm._load_registry()
        assert "tdm" in loaded["workspaces"]
        assert loaded["active"] == "tdm"
        assert not (tmp_path / "registry.yaml.tmp").exists()


# ══════════════════════════════════════════════════════════
# D1 三道闸：drafts 路由守卫与入库流转
# ══════════════════════════════════════════════════════════

class TestD1DraftsGate:
    def _import_drafts_router(self):
        backend = SG_ROOT / "workbench" / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from routers import drafts as drafts_router
        return drafts_router

    def test_filename_guard(self):
        from fastapi import HTTPException
        dr = self._import_drafts_router()
        with pytest.raises(HTTPException):
            dr._guard_filename("../../evil.yaml")
        with pytest.raises(HTTPException):
            dr._guard_filename("a/b.yaml")
        with pytest.raises(HTTPException):
            dr._guard_filename("evil.py")  # 非 YAML
        assert dr._guard_filename("PP-X-001.yaml").name == "PP-X-001.yaml"

    def test_module_guard(self):
        from fastapi import HTTPException
        dr = self._import_drafts_router()
        with pytest.raises(HTTPException):
            dr._guard_module("../engine")
        with pytest.raises(HTTPException):
            dr._guard_module("nonexistent-module-xyz")
        assert dr._guard_module("employee/person-profile").is_dir()

    def test_promote_flow(self, tmp_path, monkeypatch):
        """入库流转：移动 + 基线重建（skip_gate 避免 release_check 子进程）。"""
        dr = self._import_drafts_router()
        drafts_dir = tmp_path / "drafts"
        scenarios_dir = tmp_path / "scenarios" / "mod" / "a"
        drafts_dir.mkdir(parents=True)
        scenarios_dir.mkdir(parents=True)
        (tmp_path / "scenarios" / "mod" / "a" / ".gitkeep").write_text("")

        monkeypatch.setattr(dr, "_drafts_root", lambda: drafts_dir)
        monkeypatch.setattr(dr, "_scenarios_root", lambda: tmp_path / "scenarios")
        monkeypatch.setattr(dr, "SG_ROOT", tmp_path)

        draft = drafts_dir / "XX-TEST-100.yaml"
        draft.write_text("""
id: XX-TEST-100
version: "0.1"
doc:
  given: 测试
  when: 测试
  then: 测试
  covers: []
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - status: {eq: 200}
""", encoding="utf-8")

        result = dr.promote_draft("XX-TEST-100.yaml", dr.PromoteBody(module="mod/a", skip_gate=True))
        assert result["ok"] is True
        assert (scenarios_dir / "XX-TEST-100.yaml").is_file()
        assert not draft.exists()
        # 契约基线已重建并包含新场景
        baseline = json.loads((tmp_path / "contracts_baseline.json").read_text(encoding="utf-8"))
        assert "XX-TEST-100" in baseline

    def test_discard_flow(self, tmp_path, monkeypatch):
        dr = self._import_drafts_router()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir(parents=True)
        monkeypatch.setattr(dr, "_drafts_root", lambda: drafts_dir)
        monkeypatch.setattr(dr, "_trash_dir", lambda: drafts_dir / "_trash")
        monkeypatch.setattr(dr, "SG_ROOT", tmp_path)

        draft = drafts_dir / "XX-TEST-101.yaml"
        draft.write_text("id: XX-TEST-101\n", encoding="utf-8")
        result = dr.discard_draft("XX-TEST-101.yaml")
        assert result["ok"] is True
        assert not draft.exists()
        assert len(list((drafts_dir / "_trash").glob("*XX-TEST-101.yaml"))) == 1
