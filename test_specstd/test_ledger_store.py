"""ledger_store 业务台账投影层测试（K-xxx：文件真相源 + SQLite 台账）。

覆盖：建表幂等 / run.json 落库与失败查询 / index.jsonl 首次迁移 /
场景·草稿·会话台账 upsert / failure_index 查询降级路径。
"""

import json
import sqlite3
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from services import ledger_store as ls  # noqa: E402
from services import failure_index as fi  # noqa: E402

RUN_JSON = {
    "run_id": "EX-test001", "env": "sit",
    "started_at": "2026-08-03T10:00:00", "finished_at": "2026-08-03T10:01:00",
    "stats": {"pass": 1, "fail": 1, "skip": 0, "blocked": 0, "total": 2, "warnings": 0},
    "cases": [
        {"id": "TL-RC-006", "title": "通过场景", "verdict": "PASS",
         "duration_ms": 100, "covers": ["FR-006"],
         "file": "cases/TL-RC-006.json"},
        {"id": "TL-RC-014", "title": "失败场景", "verdict": "FAIL",
         "duration_ms": 200, "covers": ["FR-014"],
         "file": "cases/TL-RC-014.json"},
    ],
    "trigger": {"workspace": "tdm", "emp_no": "90024166"},
}


@pytest.fixture()
def env(tmp_path):
    """隔离环境：reports/ + 独立 SQLite（tmp db）。"""
    reports = tmp_path / "reports"
    (reports / "EX-test001" / "cases").mkdir(parents=True)
    (reports / "EX-test001" / "run.json").write_text(
        json.dumps(RUN_JSON, ensure_ascii=False), encoding="utf-8")
    (reports / "EX-test001" / "cases" / "TL-RC-006.json").write_text(
        json.dumps({"verdict": "PASS",
                    "assertions": [{"passed": True}],
                    "saved_vars": {"activityName": "SG历史DAG-1"}}),
        encoding="utf-8")
    (reports / "EX-test001" / "cases" / "TL-RC-014.json").write_text(
        json.dumps({"verdict": "FAIL",
                    "failure": {"category": "assert_failed", "message": "实际 200 ≠ 预期 400"},
                    "assertions": [{"passed": False}, {"passed": False}],
                    "saved_vars": {"activityName": "SG历史DAG-1"}}),
        encoding="utf-8")
    db = tmp_path / "test.db"
    ls.ensure_tables(db)
    return reports, db


def _conn(db: Path) -> sqlite3.Connection:
    """测试连接（与 ledger_store 同 row_factory）。"""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


class TestRunsLedger:
    def test_ensure_tables_idempotent(self, env):
        """建表幂等（重复调用不报错）。"""
        _reports, db = env
        ls.ensure_tables(db)
        ls.ensure_tables(db)
        with _conn(db) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"runs", "run_cases", "scenarios", "drafts", "agent_sessions"} <= tables

    def test_upsert_run_from_json(self, env):
        """run.json 落库：runs 汇总 + run_cases 逐场景。"""
        reports, db = env
        n = ls.upsert_run_from_json(reports, "EX-test001", source="unit", db_path=db)
        assert n == 2
        with _conn(db) as conn:
            run = conn.execute("SELECT * FROM runs WHERE run_id='EX-test001'").fetchone()
            cases = conn.execute(
                "SELECT scenario_id, verdict, category, message FROM run_cases").fetchall()
        assert run["fail_count"] == 1 and run["total"] == 2 and run["emp_no"] == "90024166"
        fail_case = [c for c in cases if c["scenario_id"] == "TL-RC-014"][0]
        assert fail_case["verdict"] == "FAIL"
        assert fail_case["category"] == "assert_failed"
        assert "400" in fail_case["message"]

    def test_upsert_run_idempotent(self, env):
        """同 run_id 重复落库不产生重复行。"""
        reports, db = env
        ls.upsert_run_from_json(reports, "EX-test001", db_path=db)
        ls.upsert_run_from_json(reports, "EX-test001", db_path=db)
        with _conn(db) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM run_cases WHERE run_id='EX-test001'").fetchone()[0] == 2

    def test_query_failures_filter_and_order(self, env):
        """失败查询：只返回 FAIL/ERROR/BLOCKED，可按场景过滤。"""
        reports, db = env
        ls.upsert_run_from_json(reports, "EX-test001", db_path=db)
        rows = ls.query_failures(reports, "", 10, db_path=db)
        assert len(rows) == 1 and rows[0]["scenario_id"] == "TL-RC-014"
        assert rows[0]["log"] == "reports/EX-test001/output.log"
        assert ls.query_failures(reports, "TL-RC-006", 10, db_path=db) == []

    def test_upsert_run_cases_new_columns(self, env):
        """run_cases 新列：title/covers/断言摘要/saved_vars 落库。"""
        reports, db = env
        ls.upsert_run_from_json(reports, "EX-test001", db_path=db)
        with _conn(db) as conn:
            rows = conn.execute(
                "SELECT scenario_id, title, covers, assertion_passed, assertion_total, "
                "saved_vars FROM run_cases").fetchall()
        by_sid = {r["scenario_id"]: r for r in rows}
        assert by_sid["TL-RC-006"]["title"] == "通过场景"
        assert json.loads(by_sid["TL-RC-006"]["covers"]) == ["FR-006"]
        assert by_sid["TL-RC-006"]["assertion_passed"] == 1
        assert by_sid["TL-RC-006"]["assertion_total"] == 1
        assert json.loads(by_sid["TL-RC-006"]["saved_vars"])["activityName"] == "SG历史DAG-1"
        assert by_sid["TL-RC-014"]["assertion_total"] == 2
        assert by_sid["TL-RC-014"]["assertion_passed"] == 0

    def test_query_executions_db_filters(self, env):
        """全量台账查询：scenario/run_id/verdict 过滤 + 含 PASS。"""
        reports, db = env
        ls.upsert_run_from_json(reports, "EX-test001", db_path=db)
        rows = ls.query_executions_db(reports, verdict="PASS", db_path=db)
        assert len(rows) == 1 and rows[0]["scenario_id"] == "TL-RC-006"
        rows = ls.query_executions_db(reports, scenario_id="TL-RC-014", db_path=db)
        assert len(rows) == 1 and rows[0]["verdict"] == "FAIL"
        assert rows[0]["title"] == "失败场景"
        assert rows[0]["saved_vars"]["activityName"] == "SG历史DAG-1"

    def test_query_failures_migrates_empty_db(self, env):
        """空 DB + 有 index.jsonl → 首次迁移后能查到（与文件读法一致）。"""
        reports, db = env
        # 先写文件索引（模拟旧版落盘数据）
        index_path = reports / "failures" / "index.jsonl"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(
            json.dumps({"run_id": "EX-test001", "scenario_id": "TL-RC-014",
                        "verdict": "FAIL", "category": "assert_failed",
                        "message": "x", "env": "sit", "finished_at": "2026-08-03T10:01:00",
                        "log": "reports/EX-test001/output.log"}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        rows = ls.query_failures(reports, "", 10, db_path=db)  # 空 run_cases → 自动迁移
        assert len(rows) == 1 and rows[0]["run_id"] == "EX-test001"

    def test_failure_index_query_falls_back_to_file(self, env, monkeypatch):
        """failure_index.query_failures：台账不可用时降级读文件。"""
        reports, db = env
        # 只写文件索引、不落库 → 台账查询空 → 降级文件读法（DB_PATH 隔离，不碰真实库）
        index_path = reports / "failures" / "index.jsonl"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(
            json.dumps({"run_id": "EX-test001", "scenario_id": "TL-RC-014",
                        "verdict": "FAIL"}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        from services import ledger_store as ls_mod
        monkeypatch.setattr(ls_mod, "DB_PATH", db)
        rows = fi.query_failures(reports, "", 10)
        assert rows and rows[0]["scenario_id"] == "TL-RC-014"


class TestEntityLedgers:
    def test_scenarios_upsert(self, env):
        """场景台账：幂等 upsert，字段投影完整。"""
        _reports, db = env
        ls.upsert_scenarios([
            {"id": "TL-RC-014", "title": "创建 PLATFORM 标签", "module": "inv",
             "version": "0.4", "priority": "P2", "tags": ["tag-library"],
             "covers": [], "path": "inventory/x/TL-RC-014.yaml", "updated_at": "2026-08-03 10:00"},
        ], db)
        ls.upsert_scenarios([
            {"id": "TL-RC-014", "title": "创建 PLATFORM 标签（改）", "module": "inv",
             "version": "0.5", "priority": "P2", "tags": ["tag-library"],
             "covers": [], "path": "inventory/x/TL-RC-014.yaml", "updated_at": "2026-08-03 11:00"},
        ], db)
        rows = ls.query_scenarios(db)
        assert len(rows) == 1
        assert rows[0]["version"] == "0.5" and rows[0]["title"].endswith("（改）")

    def test_draft_status_flow(self, env):
        """草稿台账：draft → promoted 状态流转（按 工作区×文件名 唯一）。"""
        _reports, db = env
        ls.upsert_draft("TL-RC-066.yaml", "TL-RC-066", "测试", "draft", "",
                        "90024166", workspace="tdm", db_path=db)
        ls.set_draft_status("TL-RC-066.yaml", "promoted",
                            "inventory/smart-tag/标签库维护", workspace="tdm", db_path=db)
        with _conn(db) as conn:
            row = conn.execute(
                "SELECT status, module, author, workspace FROM drafts "
                "WHERE filename='TL-RC-066.yaml' AND workspace='tdm'"
            ).fetchone()
        assert row["status"] == "promoted" and row["module"] == "inventory/smart-tag/标签库维护"
        assert row["author"] == "90024166" and row["workspace"] == "tdm"

    def test_draft_isolated_by_workspace(self, env):
        """多工作区同名草稿互不覆盖（主键 工作区×文件名）。"""
        _reports, db = env
        ls.upsert_draft("TL-RC-066.yaml", "TL-RC-066", "工作区A", "draft", "", "a",
                        workspace="ws-a", db_path=db)
        ls.upsert_draft("TL-RC-066.yaml", "TL-RC-066", "工作区B", "draft", "", "b",
                        workspace="ws-b", db_path=db)
        with _conn(db) as conn:
            rows = conn.execute("SELECT workspace, author FROM drafts").fetchall()
        assert len(rows) == 2
        assert {r["workspace"] for r in rows} == {"ws-a", "ws-b"}

    def test_session_upsert(self, env):
        """会话台账：幂等 upsert（同一 session 重复保存取最新计数）。"""
        _reports, db = env
        ls.upsert_session("sess1", "90024166", "tdm", 10, 2, db)
        ls.upsert_session("sess1", "90024166", "tdm", 20, 5, db)
        with _conn(db) as conn:
            row = conn.execute(
                "SELECT msg_count, tool_calls FROM agent_sessions WHERE session_id='sess1'"
            ).fetchone()
        assert row["msg_count"] == 20 and row["tool_calls"] == 5
