"""lifecycle 生命周期聚合测试（K-xxx：单元测试完整生命周期监控）。

覆盖：状态机判定（草稿待评审/更新中/已入库/已废弃）、闭环推导（FAIL→PASS）、
时间线事件合并、未入库草稿与已废弃草稿入列、统计汇总。
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import ledger_store as ls  # noqa: E402
from services import lifecycle as lc  # noqa: E402


def _seed_run(conn: sqlite3.Connection, run_id: str, scenario_id: str,
              verdict: str, finished_at: str, category: str = "", message: str = ""):
    conn.execute(
        """INSERT INTO runs (run_id, reports_root, env, workspace, emp_no, source,
                             started_at, finished_at, total)
           VALUES (?,?,?,?,?,?,?,?,1)""",
        (run_id, "specstd/x/.specguard/reports", "sit", "tdm", "90024166", "test",
         finished_at, finished_at))
    conn.execute(
        """INSERT INTO run_cases (run_id, scenario_id, verdict, duration_ms, category, message)
           VALUES (?,?,?,?,?,?)""",
        (run_id, scenario_id, verdict, 100, category, message))


@pytest.fixture()
def env(tmp_path):
    """独立台账库 + 预置数据：场景 TL-RC-014（库内）+ 草稿状态 + 执行史。"""
    db = tmp_path / "test.db"
    ls.ensure_tables(db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        # 库内场景（必须传 db_path——默认库是真实 workbench.db，测试不得污染）
        ls.upsert_scenarios([
            {"id": "TL-RC-014", "title": "创建 PLATFORM 标签", "module": "inventory",
             "version": "0.4", "priority": "P2", "tags": ["tag-library"],
             "covers": ["FR-001"], "path": "inventory/x/TL-RC-014.yaml",
             "updated_at": "2026-08-03 13:26"},
            {"id": "TL-RC-007", "title": "平台标签创建成功", "module": "inventory",
             "version": "0.3", "priority": "P1", "tags": [],
             "covers": [], "path": "inventory/x/TL-RC-007.yaml",
             "updated_at": "2026-08-03 12:00"},
        ], db_path=db)
        # 草稿：TL-RC-014 有 draft 草稿（更新中）；TL-RC-066 未入库草稿（新建中）
        ls.upsert_draft("TL-RC-014.yaml", "TL-RC-014", "更新版", "draft", "",
                        "90024166", workspace="tdm", db_path=db)
        ls.upsert_draft("TL-RC-066.yaml", "TL-RC-066", "新场景草稿", "draft", "",
                        "90024166", workspace="tdm", db_path=db)
        # 执行史：TL-RC-014 FAIL → FAIL → PASS（一个闭环）；TL-RC-007 FAIL（未修复）
        _seed_run(conn, "EX-r1", "TL-RC-014", "FAIL", "2026-08-03T10:00:00",
                  "assert_failed", "实际 200 ≠ 400")
        _seed_run(conn, "EX-r2", "TL-RC-014", "FAIL", "2026-08-03T11:00:00",
                  "env_error", "变量未定义")
        _seed_run(conn, "EX-r3", "TL-RC-014", "PASS", "2026-08-03T12:00:00")
        _seed_run(conn, "EX-r4", "TL-RC-007", "FAIL", "2026-08-03T13:00:00",
                  "assert_failed", "数据不一致")
    return db


class TestLifecycleList:
    def test_summary_and_status(self, env):
        """状态机 + 统计汇总。"""
        r = lc.list_lifecycle(db_path=env)
        s = r["summary"]
        assert s["total"] == 3  # TL-RC-014 / TL-RC-007 / TL-RC-066（未入库草稿）
        assert s["in_library"] == 1      # TL-RC-007（无草稿记录）
        assert s["draft_updating"] == 1  # TL-RC-014（库内 + draft 草稿）
        assert s["draft_pending"] == 1   # TL-RC-066（库内无 + draft 草稿）
        assert s["closed_loops"] == 1    # TL-RC-014 的 FAIL→PASS
        by_id = {it["id"]: it for it in r["items"]}
        assert by_id["TL-RC-014"]["status"] == "draft_updating"
        assert by_id["TL-RC-014"]["run_count"] == 3
        assert by_id["TL-RC-014"]["fail_count"] == 2
        assert by_id["TL-RC-014"]["closed_loops"] == 1
        assert by_id["TL-RC-014"]["last_verdict"] == "PASS"
        assert by_id["TL-RC-014"]["last_failure"]["category"] == "env_error"  # 最后一次失败
        assert by_id["TL-RC-014"]["recent_verdicts"] == ["FAIL", "FAIL", "PASS"]
        assert by_id["TL-RC-007"]["status"] == "in_library"
        assert by_id["TL-RC-066"]["status"] == "draft_pending"

    def test_discarded_draft_listed(self, env):
        """已废弃草稿（库内无）→ 已废弃行。"""
        ls.upsert_draft("TL-RC-099.yaml", "TL-RC-099", "废弃草稿", "discarded", "",
                        "90024166", workspace="tdm", db_path=env)
        r = lc.list_lifecycle(db_path=env)
        by_id = {it["id"]: it for it in r["items"]}
        assert by_id["TL-RC-099"]["status"] == "discarded"
        assert r["summary"]["total"] == 4

    def test_promoted_draft_is_in_library(self, env):
        """草稿已入库（promoted）→ 已入库。"""
        ls.upsert_draft("TL-RC-007.yaml", "TL-RC-007", "更新版", "promoted", "inventory",
                        "90024166", workspace="tdm", db_path=env)
        r = lc.list_lifecycle(db_path=env)
        by_id = {it["id"]: it for it in r["items"]}
        assert by_id["TL-RC-007"]["status"] == "in_library"
        assert by_id["TL-RC-007"]["draft_status"] == "promoted"


class TestLifecycleDetail:
    def test_timeline_events(self, env):
        """时间线：run 事件 + 闭环事件，按时间倒序。"""
        d = lc.scenario_detail("TL-RC-014", db_path=env)
        assert d["status"] == "draft_updating"
        # 草稿事件 1 + run 事件 3 + 闭环事件 1 = 5
        types = [e["type"] for e in d["timeline"]]
        assert types.count("run") == 3
        assert types.count("loop_closed") == 1
        assert types.count("draft_updated") == 1
        # 按时间倒序（草稿 updated_at=当前时间，应排最前）
        ats = [e.get("at", "") for e in d["timeline"]]
        assert ats == sorted(ats, reverse=True), "时间线必须按时间倒序"
        assert d["timeline"][0]["type"] == "draft_updated"
        # 闭环事件对应 EX-r3（FAIL→PASS 转换点）
        closed = [e for e in d["timeline"] if e["type"] == "loop_closed"][0]
        assert closed["run_id"] == "EX-r3"
        # runs 列表倒序
        assert d["runs"][0]["run_id"] == "EX-r3"

    def test_detail_no_runs(self, env):
        """无执行史的场景：时间线只有草稿事件。"""
        d = lc.scenario_detail("TL-RC-066", db_path=env)
        assert d["status"] == "draft_pending"
        assert [e["type"] for e in d["timeline"]] == ["draft_updated"]
        assert d["runs"] == []
