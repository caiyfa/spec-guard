"""test_audit — audit-spec 技能 + 审计工具 + ledger 扩展测试。

覆盖验收标准：
1. audit-spec 技能存在且内容完整（T-601：modes 退役后技能为单一事实源）
2. report_vulnerability 登记的漏洞进入 feedback ledger（pending 状态）
3. write_audit_report 落盘到 {workspace}/.specguard/audit/
4. 漏洞条目含完整字段（vtype/severity/location/evidence/suggestion）
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.skill_loader import load_skill, list_skills, clear_cache
from feedback.ledger import FeedbackLedger
from mcp_server.tools import audit
from specstd.workspace import register_local, unregister
from test_specstd.helpers import create_valid_workspace


def _call_sync(module, name, arguments):
    """同步调用异步 handle 函数。"""
    return asyncio.run(module.handle(name, arguments))


@pytest.fixture
def workspace(tmp_path):
    """创建并注册一个合规工作区。"""
    ws_path = create_valid_workspace(tmp_path / "ws")
    register_local("test-audit-ws", str(ws_path), "tdm", activate=True)
    yield "test-audit-ws"
    unregister("test-audit-ws")


# ══════════════════════════════════════════════════════════
# 验收 1: audit-spec 技能存在，内容覆盖审计流程（T-601 迁移后断言技能）
# ══════════════════════════════════════════════════════════

class TestAuditSkill:
    def test_audit_skill_exists(self):
        clear_cache()
        skill = load_skill("audit-spec")
        assert skill is not None
        assert skill.name == "audit-spec"

    def test_audit_skill_content(self):
        clear_cache()
        skill = load_skill("audit-spec")
        assert skill is not None
        # 审计流程与工具指引
        assert "write_audit_report" in skill.content
        assert "report_vulnerability" in skill.content
        assert "read_spec" in skill.content
        assert "list_spec_files" in skill.content

    def test_audit_skill_in_list(self):
        clear_cache()
        skills = list_skills()
        names = [s.name for s in skills]
        assert "audit-spec" in names

    def test_audit_skill_no_write_draft_guidance(self):
        """audit-spec 技能不指引写草稿（审计只读 spec，不写草稿）。"""
        clear_cache()
        skill = load_skill("audit-spec")
        assert skill is not None
        assert "write_draft" not in skill.content

    def test_audit_skill_prompt_fragment(self):
        clear_cache()
        skill = load_skill("audit-spec")
        assert skill is not None
        assert "审计" in skill.content
        assert "漏洞" in skill.content


# ══════════════════════════════════════════════════════════
# 验收 4+5: ledger 漏洞条目扩展
# ══════════════════════════════════════════════════════════

class TestLedgerVulnerability:
    def test_create_vulnerability_full_fields(self, tmp_path):
        """漏洞条目含完整字段。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="logic_defect",
            severity="major",
            location="FR-001",
            summary="FR-001 描述模糊",
            evidence="spec 中使用'合理'一词",
            suggestion="改为明确的数值范围",
        )
        assert entry["spq_id"].startswith("SPQ-")
        assert entry["status"] == "pending"
        assert entry["source"] == "loop_b"
        assert entry["vtype"] == "logic_defect"
        assert entry["severity"] == "major"
        assert entry["location"] == "FR-001"
        assert entry["summary"] == "FR-001 描述模糊"
        assert entry["evidence"] == "spec 中使用'合理'一词"
        assert entry["suggestion"] == "改为明确的数值范围"

    def test_create_vulnerability_optional_fields(self, tmp_path):
        """evidence 和 suggestion 可选。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="missing_info",
            severity="blocker",
            location="FR-002",
            summary="缺少字段定义",
        )
        assert entry["evidence"] == ""
        assert entry["suggestion"] == ""

    def test_invalid_vtype(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        with pytest.raises(ValueError, match="vtype"):
            ledger.create_vulnerability(
                vtype="invalid", severity="major",
                location="FR-001", summary="test",
            )

    def test_invalid_severity(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        with pytest.raises(ValueError, match="severity"):
            ledger.create_vulnerability(
                vtype="logic_defect", severity="critical",
                location="FR-001", summary="test",
            )

    def test_list_vulnerabilities_filters(self, tmp_path):
        """list_vulnerabilities 只返回漏洞条目（含 vtype）。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create("普通条目", source="loop_b")
        ledger.create_vulnerability(
            vtype="missing_info", severity="blocker",
            location="FR-002", summary="缺少字段定义",
        )
        vulns = ledger.list_vulnerabilities()
        assert len(vulns) == 1
        assert vulns[0]["vtype"] == "missing_info"

    def test_list_vulnerabilities_by_status(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        e1 = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test1",
        )
        ledger.create_vulnerability(
            vtype="missing_info", severity="minor",
            location="FR-002", summary="test2",
        )
        # close one
        ledger.transition(e1["spq_id"], "closed")
        pending = ledger.list_vulnerabilities(status="pending")
        assert len(pending) == 1
        closed = ledger.list_vulnerabilities(status="closed")
        assert len(closed) == 1

    def test_count_vulnerabilities(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test1",
        )
        ledger.create_vulnerability(
            vtype="missing_info", severity="minor",
            location="FR-002", summary="test2",
        )
        assert ledger.count_vulnerabilities("pending") == 2
        spq_id = ledger.list_vulnerabilities()[0]["spq_id"]
        ledger.transition(spq_id, "closed")
        assert ledger.count_vulnerabilities("pending") == 1
        assert ledger.count_vulnerabilities("closed") == 1

    def test_vulnerability_transition(self, tmp_path):
        """漏洞条目支持完整状态机。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create_vulnerability(
            vtype="logic_defect", severity="major",
            location="FR-001", summary="test",
        )
        # pending -> in_progress
        updated = ledger.transition(entry["spq_id"], "in_progress")
        assert updated["status"] == "in_progress"
        # in_progress -> closed
        updated = ledger.transition(entry["spq_id"], "closed")
        assert updated["status"] == "closed"

    def test_all_vtypes(self, tmp_path):
        """4 种漏洞类型都能创建。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        for vtype in ["logic_defect", "spec_impl_mismatch", "missing_info", "behavior_deviation"]:
            entry = ledger.create_vulnerability(
                vtype=vtype, severity="minor",
                location="FR-001", summary=f"test-{vtype}",
            )
            assert entry["vtype"] == vtype

    def test_all_severities(self, tmp_path):
        """3 种严重度都能创建。"""
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        for sev in ["blocker", "major", "minor"]:
            entry = ledger.create_vulnerability(
                vtype="logic_defect", severity=sev,
                location="FR-001", summary=f"test-{sev}",
            )
            assert entry["severity"] == sev


# ══════════════════════════════════════════════════════════
# 验收 3: write_audit_report 落盘到 .specguard/audit/
# ══════════════════════════════════════════════════════════

class TestWriteAuditReport:
    def test_write_report_success(self, workspace):
        """审计报告落盘到 .specguard/audit/。"""
        result = _call_sync(audit, "write_audit_report", {
            "title": "测试审计报告",
            "content": "# 审计内容\n\n发现 2 条漏洞。",
            "vulnerability_count": 2,
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert "audit" in data["path"]
        assert ".specguard" in data["path"]
        assert data["filename"].endswith(".md")
        assert data["vulnerability_count"] == 2
        # 验证文件实际存在且内容正确
        report_path = Path(data["path"])
        assert report_path.is_file()
        content = report_path.read_text(encoding="utf-8")
        assert "测试审计报告" in content
        assert "审计内容" in content

    def test_write_report_missing_title(self, workspace):
        result = _call_sync(audit, "write_audit_report", {
            "content": "test content",
        })
        assert "错误" in result[0].text

    def test_write_report_missing_content(self, workspace):
        result = _call_sync(audit, "write_audit_report", {
            "title": "test title",
        })
        assert "错误" in result[0].text

    def test_write_report_chinese_title(self, workspace):
        """中文标题生成安全文件名。"""
        result = _call_sync(audit, "write_audit_report", {
            "title": "干部盘点模块审计",
            "content": "内容",
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        # 文件名应包含中文（_sanitize_filename 保留 CJK 字符）
        assert "干部盘点模块审计" in data["filename"]


# ══════════════════════════════════════════════════════════
# 验收 2+3: report_vulnerability 登记漏洞到台账
# ══════════════════════════════════════════════════════════

class TestReportVulnerability:
    def test_report_vulnerability_success(self, monkeypatch, tmp_path):
        """漏洞登记到台账（pending 状态）。"""
        monkeypatch.setattr("mcp_server.tools.audit.LEDGER_PATH", tmp_path / "ledger.json")
        result = _call_sync(audit, "report_vulnerability", {
            "vtype": "logic_defect",
            "severity": "major",
            "location": "FR-001",
            "summary": "FR-001 描述模糊",
            "evidence": "spec 中使用'合理'一词",
            "suggestion": "改为明确的数值范围",
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert data["spq_id"].startswith("SPQ-")
        assert data["status"] == "pending"
        # notification 可能失败（无 DB/无配置），不影响台账
        assert "notification" in data

    def test_report_vulnerability_persists_to_ledger(self, monkeypatch, tmp_path):
        """漏洞确实写入台账文件。"""
        ledger_path = tmp_path / "ledger.json"
        monkeypatch.setattr("mcp_server.tools.audit.LEDGER_PATH", ledger_path)
        _call_sync(audit, "report_vulnerability", {
            "vtype": "missing_info",
            "severity": "blocker",
            "location": "FR-002",
            "summary": "缺少字段定义",
            "evidence": "无枚举值",
            "suggestion": "补充枚举",
        })
        # 从台账文件验证
        ledger = FeedbackLedger(ledger_path)
        vulns = ledger.list_vulnerabilities()
        assert len(vulns) == 1
        v = vulns[0]
        assert v["vtype"] == "missing_info"
        assert v["severity"] == "blocker"
        assert v["location"] == "FR-002"
        assert v["evidence"] == "无枚举值"
        assert v["suggestion"] == "补充枚举"
        assert v["status"] == "pending"

    def test_report_vulnerability_missing_vtype(self, monkeypatch, tmp_path):
        monkeypatch.setattr("mcp_server.tools.audit.LEDGER_PATH", tmp_path / "ledger.json")
        result = _call_sync(audit, "report_vulnerability", {
            "severity": "major",
            "location": "FR-001",
            "summary": "test",
        })
        assert "错误" in result[0].text

    def test_report_vulnerability_invalid_vtype(self, monkeypatch, tmp_path):
        monkeypatch.setattr("mcp_server.tools.audit.LEDGER_PATH", tmp_path / "ledger.json")
        result = _call_sync(audit, "report_vulnerability", {
            "vtype": "invalid_type",
            "severity": "major",
            "location": "FR-001",
            "summary": "test",
        })
        assert "错误" in result[0].text

    def test_report_vulnerability_missing_summary(self, monkeypatch, tmp_path):
        monkeypatch.setattr("mcp_server.tools.audit.LEDGER_PATH", tmp_path / "ledger.json")
        result = _call_sync(audit, "report_vulnerability", {
            "vtype": "logic_defect",
            "severity": "major",
            "location": "FR-001",
        })
        assert "错误" in result[0].text

    def test_report_vulnerability_notification_not_blocking(self, monkeypatch, tmp_path):
        """通知失败不阻塞台账记录。"""
        monkeypatch.setattr("mcp_server.tools.audit.LEDGER_PATH", tmp_path / "ledger.json")
        result = _call_sync(audit, "report_vulnerability", {
            "vtype": "behavior_deviation",
            "severity": "minor",
            "location": "FR-003",
            "summary": "接口返回与 spec 不符",
        })
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert data["spq_id"].startswith("SPQ-")
        # notification 字段存在（可能是 error/no_config/sent 等）
        assert "notification" in data
