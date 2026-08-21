"""run_queue 轻量选项持久化测试（T-114）。

背景：排队等待的执行只存 strict_deps/breakpoints，prep_only/skip_upstream_verify/
account_override（K-046/K-056 用户选择）入队即丢失——队列重放后执行静默改变。

验证：
1. enqueue_run 带轻量选项 → 读回一致（含老库迁移补列）
2. _start_next_from_queue 重放时透传三项（此前只透传 strict_deps）
"""

from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from services import user_store  # noqa: E402
from services import runner as runner_mod  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    return db_file


class TestEnqueueOptions:
    def test_options_survive_roundtrip(self, db):
        """T-114：轻量选项入队后读回一致。"""
        qid = user_store.enqueue_run(
            emp_no="u1", scope="scenario", target="TL-001", env="sit", plan_id="",
            breakpoints=[], strict_deps=True, workspace="ws1",
            prep_only=True, skip_upstream_verify=True, account_override="acc2")
        row = user_store.get_run_queue_item(qid, db_path=db)
        assert row["prep_only"] == 1
        assert row["skip_upstream_verify"] == 1
        assert row["account_override"] == "acc2"

    def test_legacy_db_migrates_columns(self, tmp_path):
        """老库（无新列）init_db 幂等补列。"""
        import sqlite3
        db_file = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_file)
        conn.executescript("""
        CREATE TABLE run_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_no TEXT NOT NULL, scope TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
            env TEXT NOT NULL DEFAULT 'sit', plan_id TEXT NOT NULL DEFAULT '',
            breakpoints TEXT NOT NULL DEFAULT '[]', strict_deps INTEGER NOT NULL DEFAULT 0,
            workspace TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL, started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT ''
        );
        """)
        conn.close()
        user_store.init_db(db_file)
        cols = {r[1] for r in sqlite3.connect(db_file).execute("PRAGMA table_info(run_queue)")}
        assert {"prep_only", "skip_upstream_verify", "account_override", "overrides"} <= cols

    def test_overrides_survive_roundtrip(self, db):
        """T-312：变量覆盖（确认弹窗输入值）入队后读回一致。"""
        ov = [{"kind": "account", "name": "platformNoCorp", "value": "caiyunfei"},
              {"kind": "env", "name": "vars.xx", "value": "1"}]
        qid = user_store.enqueue_run(
            emp_no="u1", scope="scenario", target="TL-RC-014", env="sit", plan_id="",
            breakpoints=[], strict_deps=False, workspace="ws1", overrides=ov)
        row = user_store.get_run_queue_item(qid, db_path=db)
        import json
        assert json.loads(row["overrides"]) == ov


class TestQueueReplay:
    def test_replay_forwards_light_options(self, monkeypatch):
        """T-114：队列重放时透传持久化的轻量选项（此前静默丢失）。"""
        mgr = runner_mod.RunManager()
        calls: dict = {}

        async def fake_trigger(**kw):
            calls.update(kw)

        async def fake_audit(*a, **k):
            pass

        monkeypatch.setattr(user_store, "list_run_queue", lambda: [{
            "id": 9, "status": "queued", "scope": "scenario", "target": "TL-001",
            "env": "sit", "plan_id": "", "breakpoints": "[]", "strict_deps": 1,
            "workspace": "ws1", "emp_no": "u1",
            "prep_only": 1, "skip_upstream_verify": 1, "account_override": "acc2",
            "overrides": '[{"kind": "account", "name": "platformNoCorp", "value": "ad9"}]',
        }])
        monkeypatch.setattr(mgr, "trigger", fake_trigger)
        monkeypatch.setattr(mgr, "broadcast", fake_audit)
        monkeypatch.setattr(runner_mod, "_get_reports_root", lambda: Path("."))

        import asyncio
        asyncio.run(mgr._start_next_from_queue())
        assert calls["prep_only"] is True
        assert calls["skip_upstream_verify"] is True
        # T-312：变量覆盖随队列重放透传（解析回列表）
        assert calls["overrides"] == [{"kind": "account", "name": "platformNoCorp", "value": "ad9"}]
        assert calls["account_override"] == "acc2"
        assert calls["queue_id"] == 9
