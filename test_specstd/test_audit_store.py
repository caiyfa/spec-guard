"""test_audit_store — 审计表测试（T-082）。

覆盖：
- record_call 写入
- query_calls 过滤（工号/工具/会话）
- verdict 枚举
- get_call 单条查询
- 敏感字段脱敏（token/password 等）
- 截断逻辑（max 200 字符）
"""

import json
import tempfile
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from workbench.backend.services import audit_store  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    """临时数据库路径，每个测试隔离。"""
    return tmp_path / "test_audit.db"


class TestAuditStore:
    def test_record_and_query(self, db_path):
        """record_call 写入后 query_calls 能查到。"""
        audit_store.record_call(
            tool_name="test_tool",
            verdict="ok",
            emp_no="E001",
            session_id="sess-001",
            purpose="test-purpose",
            workspace="ws-test",
            side_effect="none",
            args_raw='{"key": "value"}',
            result_raw='{"result": "ok"}',
            db_path=db_path,
        )
        rows = audit_store.query_calls(db_path=db_path)
        assert len(rows) == 1
        r = rows[0]
        assert r["tool_name"] == "test_tool"
        assert r["verdict"] == "ok"
        assert r["emp_no"] == "E001"
        assert r["session_id"] == "sess-001"

    def test_query_filter_by_emp(self, db_path):
        """按工号过滤。"""
        audit_store.record_call(tool_name="t1", verdict="ok", emp_no="E001", db_path=db_path)
        audit_store.record_call(tool_name="t2", verdict="ok", emp_no="E002", db_path=db_path)
        rows = audit_store.query_calls(emp_no="E001", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["emp_no"] == "E001"

    def test_query_filter_by_tool(self, db_path):
        """按工具名过滤。"""
        audit_store.record_call(tool_name="tool_a", verdict="ok", emp_no="E001", db_path=db_path)
        audit_store.record_call(tool_name="tool_b", verdict="ok", emp_no="E001", db_path=db_path)
        rows = audit_store.query_calls(tool_name="tool_a", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "tool_a"

    def test_query_filter_by_session(self, db_path):
        """按会话 ID 过滤。"""
        audit_store.record_call(tool_name="t1", verdict="ok", emp_no="E001", session_id="s1", db_path=db_path)
        audit_store.record_call(tool_name="t2", verdict="ok", emp_no="E001", session_id="s2", db_path=db_path)
        rows = audit_store.query_calls(session_id="s1", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["session_id"] == "s1"

    def test_order_by_id_desc(self, db_path):
        """结果按 ID 倒序。"""
        audit_store.record_call(tool_name="t1", verdict="ok", emp_no="E001", db_path=db_path)
        audit_store.record_call(tool_name="t2", verdict="ok", emp_no="E001", db_path=db_path)
        audit_store.record_call(tool_name="t3", verdict="ok", emp_no="E001", db_path=db_path)
        rows = audit_store.query_calls(db_path=db_path)
        ids = [r["id"] for r in rows]
        assert ids == sorted(ids, reverse=True)

    def test_limit_and_offset(self, db_path):
        """limit 和 offset 生效。"""
        for i in range(10):
            audit_store.record_call(tool_name=f"t{i}", verdict="ok", emp_no="E001", db_path=db_path)
        rows = audit_store.query_calls(limit=3, offset=0, db_path=db_path)
        assert len(rows) == 3
        rows2 = audit_store.query_calls(limit=3, offset=3, db_path=db_path)
        assert len(rows2) == 3
        # offset 0 和 offset 3 不应重叠
        ids1 = {r["id"] for r in rows}
        ids2 = {r["id"] for r in rows2}
        assert ids1.isdisjoint(ids2)

    def test_get_call_by_id(self, db_path):
        """get_call 按 ID 查询返回正确记录。"""
        audit_store.record_call(tool_name="find-me", verdict="ok", emp_no="E001", db_path=db_path)
        rows = audit_store.query_calls(db_path=db_path)
        call_id = rows[0]["id"]
        record = audit_store.get_call(call_id, db_path=db_path)
        assert record is not None
        assert record["tool_name"] == "find-me"

    def test_get_call_not_found(self, db_path):
        """get_call 不存在的 ID 返回 None。"""
        record = audit_store.get_call(99999, db_path=db_path)
        assert record is None

    def test_all_verdicts(self, db_path):
        """所有 verdict 枚举都可正常写入。"""
        for v in ("ok", "denied-whitelist", "denied-side-effect", "warn"):
            audit_store.record_call(tool_name="t1", verdict=v, emp_no="E001", db_path=db_path)
        rows = audit_store.query_calls(db_path=db_path)
        assert len(rows) == 4
        verdicts = {r["verdict"] for r in rows}
        assert verdicts == {"ok", "denied-whitelist", "denied-side-effect", "warn"}

    def test_sensitive_masking(self):
        """敏感字段脱敏（unit test for _mask_sensitive）。"""
        text = 'token=sk-abc123, password="secret!@#", normal_field=hello'
        masked = audit_store._mask_sensitive(text)
        assert "sk-abc123" not in masked
        assert "secret!@#" not in masked
        assert "***" in masked
        assert "normal_field=hello" in masked  # 非敏感保留

    def test_truncate_digest(self, db_path):
        """结果摘要截断至 200 字符。"""
        long_args = '{"key": "' + "x" * 500 + '"}'
        audit_store.record_call(
            tool_name="t1", verdict="ok", emp_no="E001",
            args_raw=long_args,
            result_raw="short",
            db_path=db_path,
        )
        rows = audit_store.query_calls(db_path=db_path)
        assert len(rows[0]["args_digest"]) <= 203  # 200 + "..."

    def test_empty_db_returns_empty(self, db_path):
        """空数据库返回空列表。"""
        rows = audit_store.query_calls(db_path=db_path)
        assert rows == []

    def test_ensure_tables_idempotent(self, db_path):
        """ensure_tables 幂等，多次调用不报错。"""
        audit_store.ensure_tables(db_path)
        audit_store.ensure_tables(db_path)
        audit_store.ensure_tables(db_path)
        # 能正常写入
        audit_store.record_call(tool_name="t1", verdict="ok", emp_no="E001", db_path=db_path)
        rows = audit_store.query_calls(db_path=db_path)
        assert len(rows) == 1