"""execution_index 全量执行索引测试（场景 × 执行 × 全量结果绑定台账）。

覆盖：append 全量（含 PASS）/ 幂等 / run.json 缺失 / 查询过滤（scenario/run/verdict）/
文件降级 / DB 投影。
"""
import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import execution_index as ei  # noqa: E402
from services import ledger_store as ls  # noqa: E402

RUN_JSON = {
    "run_id": "EX-full001", "env": "sit",
    "started_at": "2026-08-07T10:00:00", "finished_at": "2026-08-07T10:01:00",
    "stats": {"pass": 1, "fail": 1, "skip": 0, "blocked": 0, "total": 2, "warnings": 0},
    "cases": [
        {"id": "ST-PASS-001", "title": "通过场景", "verdict": "PASS",
         "duration_ms": 100, "covers": ["FR-001"], "file": "cases/ST-PASS-001.json"},
        {"id": "ST-FAIL-001", "title": "失败场景", "verdict": "FAIL",
         "duration_ms": 200, "covers": ["FR-002"], "file": "cases/ST-FAIL-001.json"},
    ],
    "trigger": {"workspace": "tdm", "emp_no": "90024166"},
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离环境：reports/ + 独立 SQLite（DB_PATH 指向 tmp db，不碰真实库）。"""
    reports = tmp_path / "reports"
    (reports / "EX-full001" / "cases").mkdir(parents=True)
    (reports / "EX-full001" / "run.json").write_text(
        json.dumps(RUN_JSON, ensure_ascii=False), encoding="utf-8")
    (reports / "EX-full001" / "cases" / "ST-PASS-001.json").write_text(
        json.dumps({"verdict": "PASS",
                    "assertions": [{"passed": True}, {"passed": True}],
                    "saved_vars": {"activityName": "SG历史DAG-1"}}),
        encoding="utf-8")
    (reports / "EX-full001" / "cases" / "ST-FAIL-001.json").write_text(
        json.dumps({"verdict": "FAIL",
                    "failure": {"category": "assert_failed", "message": "实际 200 ≠ 预期 400"},
                    "assertions": [{"passed": False}],
                    "saved_vars": {"activityName": "SG历史DAG-1"}}),
        encoding="utf-8")
    db = tmp_path / "test.db"
    ls.ensure_tables(db)
    monkeypatch.setattr(ls, "DB_PATH", db)   # 投影/查询全部落到 tmp db
    return reports


class TestAppendExecutions:
    def test_append_all_verdicts(self, env):
        """全量收录：PASS/FAIL 都进索引，含标题/断言摘要/saved_vars。"""
        reports = env
        n = ei.append_executions(reports, "EX-full001")
        assert n == 2
        index = reports / "executions" / "index.jsonl"
        lines = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines() if l.strip()]
        by_sid = {e["scenario_id"]: e for e in lines}
        assert by_sid["ST-PASS-001"]["verdict"] == "PASS"
        assert by_sid["ST-PASS-001"]["title"] == "通过场景"
        assert by_sid["ST-PASS-001"]["covers"] == ["FR-001"]
        assert by_sid["ST-PASS-001"]["assertion_summary"] == {"passed": 2, "total": 2}
        assert by_sid["ST-PASS-001"]["saved_vars"]["activityName"] == "SG历史DAG-1"
        assert by_sid["ST-FAIL-001"]["category"] == "assert_failed"
        assert by_sid["ST-FAIL-001"]["message"] == "实际 200 ≠ 预期 400"

    def test_append_idempotent(self, env):
        """同 run_id 重复调用不产生重复条目。"""
        reports = env
        ei.append_executions(reports, "EX-full001")
        ei.append_executions(reports, "EX-full001")
        index = reports / "executions" / "index.jsonl"
        assert len(index.read_text(encoding="utf-8").splitlines()) == 2

    def test_append_no_run_json(self, tmp_path):
        """run.json 不存在（离线自测）返回 0，不建索引。"""
        assert ei.append_executions(tmp_path / "empty", "EX-xxx") == 0


class TestQueryExecutions:
    def test_query_filter_scenario_and_verdict(self, env):
        reports = env
        ei.append_executions(reports, "EX-full001")
        rows = ei.query_executions(reports, scenario_id="ST-FAIL-001")
        assert len(rows) == 1 and rows[0]["verdict"] == "FAIL"
        rows = ei.query_executions(reports, verdict="PASS")
        assert len(rows) == 1 and rows[0]["scenario_id"] == "ST-PASS-001"

    def test_query_fallback_to_file(self, env, monkeypatch):
        """台账查询抛异常 → 降级读文件。"""
        reports = env
        ei.append_executions(reports, "EX-full001")

        def boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(ls, "query_executions_db", boom)
        rows = ei.query_executions(reports, scenario_id="ST-PASS-001")
        assert len(rows) == 1 and rows[0]["verdict"] == "PASS"
