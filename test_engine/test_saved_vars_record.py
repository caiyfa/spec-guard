"""ExecutionRecord.to_dict 收录截断 saved_vars（全量执行台账数据源）。"""
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

from engine.execution_record import ExecutionRecord


def test_to_dict_includes_saved_vars():
    rec = ExecutionRecord(scenario_id="T-001", verdict="PASS")
    rec.saved_vars = {"activity": {"json": {"data": {"activityName": "SG历史DAG-1786020277"}}}}
    d = rec.to_dict()
    assert d["saved_vars"]["activity"]["json"]["data"]["activityName"] == "SG历史DAG-1786020277"


def test_to_dict_saved_vars_missing_safe():
    """无 saved_vars 的记录（如 _blocked_record 构造）防御为空 dict。"""
    rec = ExecutionRecord(scenario_id="T-002", verdict="BLOCKED")
    assert rec.to_dict()["saved_vars"] == {}


def test_to_dict_saved_vars_truncated():
    """超长字符串截断（与 body_excerpt 同级保护）。"""
    rec = ExecutionRecord(scenario_id="T-003", verdict="PASS")
    rec.saved_vars = {"long": "x" * 600}
    d = rec.to_dict()
    assert "…" in d["saved_vars"]["long"]
    assert len(d["saved_vars"]["long"]) < 600
