"""test_scheduler — I-2 定时任务调度器单元测试。

覆盖：
  - scheduled_jobs 表 CRUD
  - cron 表达式验证
  - 调度器生命周期（start/shutdown）
  - job 启用/禁用/删除
  - 工作区隔离
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SG_AUTH_MODE", "mock")

from services import scheduler as sched


# ══════════════════════════════════════════════════════════
# Fixture：临时 DB
# ══════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    """临时 DB 文件路径。"""
    db_path = tmp_path / "test_scheduler.db"
    sched.init_db(db_path)
    return db_path


# ══════════════════════════════════════════════════════════
# T-117 调度互斥：定时/手动触发与手动执行并发互斥
# ══════════════════════════════════════════════════════════

class TestMutualExclusion:
    @pytest.fixture()
    def busy(self, monkeypatch):
        """模拟已有执行进行中：run_manager.is_running = True。"""
        from services import runner as runner_mod
        mgr = runner_mod.RunManager()
        mgr.status = "running"
        mgr.run_id = "EX-busy0001"
        monkeypatch.setattr(runner_mod, "run_manager", mgr)
        return mgr

    def test_execute_job_skips_when_busy(self, busy, tmp_db, monkeypatch):
        """定时任务忙时跳过：不调 execute_plan，状态记 skipped_busy。"""
        from services import scheduler as sched_mod
        monkeypatch.setattr(sched_mod, "DB_PATH", tmp_db)
        sched_mod.init_db(tmp_db)
        job_id = sched_mod.create_job(
            "回归", "p1", "ws1", "0 9 * * *")["id"]

        executed = []
        async def fake_execute(**kw):
            executed.append(kw)
            return {"run_id": "EX-x", "status": "success", "results": []}
        import services.plan_executor as pe_mod
        monkeypatch.setattr(pe_mod, "execute_plan", fake_execute)

        asyncio.run(sched_mod._execute_job(job_id))
        assert not executed, "忙时不得执行计划"
        job = sched_mod.get_job(job_id, db_path=tmp_db)
        assert job["last_run_status"] == "skipped_busy"

    def test_trigger_job_now_rejects_when_busy(self, busy, monkeypatch):
        """手动触发忙时拒绝：返回 skipped_busy。"""
        from services import scheduler as sched_mod
        monkeypatch.setattr(sched_mod, "get_job", lambda jid: {
            "id": jid, "plan_id": "p1", "workspace": "ws1",
            "notify_config_id": "", "name": "回归"})
        executed = []
        async def fake_execute(**kw):
            executed.append(kw)
            return {"run_id": "EX-x", "status": "success", "results": []}
        import services.plan_executor as pe_mod
        monkeypatch.setattr(pe_mod, "execute_plan", fake_execute)

        result = asyncio.run(sched_mod.trigger_job_now("j1"))
        assert result["status"] == "skipped_busy"
        assert "已有执行进行中" in result["error"]
        assert not executed

    def test_execute_job_runs_when_idle(self, tmp_db, monkeypatch):
        """空闲时正常执行（互斥只挡忙时）。"""
        from services import runner as runner_mod
        from services import scheduler as sched_mod
        mgr = runner_mod.RunManager()  # status=idle
        monkeypatch.setattr(runner_mod, "run_manager", mgr)
        monkeypatch.setattr(sched_mod, "DB_PATH", tmp_db)
        sched_mod.init_db(tmp_db)
        job_id = sched_mod.create_job(
            "回归", "p1", "ws1", "0 9 * * *")["id"]

        executed = []
        async def fake_execute(**kw):
            executed.append(kw)
            return {"run_id": "EX-ok0001", "status": "success", "results": []}
        import services.plan_executor as pe_mod
        monkeypatch.setattr(pe_mod, "execute_plan", fake_execute)

        asyncio.run(sched_mod._execute_job(job_id))
        assert len(executed) == 1
        job = sched_mod.get_job(job_id, db_path=tmp_db)
        assert job["last_run_status"] == "success"

class TestInitDB:
    def test_creates_table(self, tmp_db):
        """init_db 幂等创建表。"""
        import sqlite3
        with sched._connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            assert any(t["name"] == "scheduled_jobs" for t in tables)

    def test_idempotent(self, tmp_db):
        """多次调用 init_db 不报错。"""
        sched.init_db(tmp_db)
        sched.init_db(tmp_db)  # 不应抛异常


# ══════════════════════════════════════════════════════════
# Job CRUD
# ══════════════════════════════════════════════════════════

class TestJobCRUD:
    def test_create_job(self, tmp_db):
        """创建定时任务。"""
        job = sched.create_job(
            name="每日回归",
            plan_id="pp-full-regression",
            workspace="test-ws",
            cron="0 2 * * *",
            created_by="90000001",
            db_path=tmp_db,
        )
        assert job["id"].startswith("job-")
        assert job["name"] == "每日回归"
        assert job["plan_id"] == "pp-full-regression"
        assert job["workspace"] == "test-ws"
        assert job["cron"] == "0 2 * * *"
        assert job["enabled"] is True
        assert job["created_by"] == "90000001"
        assert job["created_at"]
        assert job["last_run_at"] == ""
        assert job["last_run_status"] == ""

    def test_get_job(self, tmp_db):
        """获取单个任务。"""
        job = sched.create_job(
            name="test", plan_id="p1", workspace="ws1",
            cron="0 * * * *", created_by="u1", db_path=tmp_db,
        )
        fetched = sched.get_job(job["id"], tmp_db)
        assert fetched is not None
        assert fetched["id"] == job["id"]
        assert fetched["name"] == "test"

    def test_get_nonexistent_job(self, tmp_db):
        """获取不存在的任务返回 None。"""
        assert sched.get_job("nonexistent", tmp_db) is None

    def test_list_jobs(self, tmp_db):
        """列出任务。"""
        sched.create_job("job1", "p1", "ws1", "0 1 * * *",
                         created_by="u1", db_path=tmp_db)
        sched.create_job("job2", "p2", "ws1", "0 2 * * *",
                         created_by="u1", db_path=tmp_db)
        sched.create_job("job3", "p3", "ws2", "0 3 * * *",
                         created_by="u1", db_path=tmp_db)

        all_jobs = sched.list_jobs(db_path=tmp_db)
        assert len(all_jobs) == 3

        ws1_jobs = sched.list_jobs(workspace="ws1", db_path=tmp_db)
        assert len(ws1_jobs) == 2
        assert all(j["workspace"] == "ws1" for j in ws1_jobs)

        ws2_jobs = sched.list_jobs(workspace="ws2", db_path=tmp_db)
        assert len(ws2_jobs) == 1

    def test_delete_job(self, tmp_db):
        """删除任务。"""
        job = sched.create_job("test", "p1", "ws1", "0 * * * *",
                               created_by="u1", db_path=tmp_db)
        assert sched.delete_job(job["id"], tmp_db) is True
        assert sched.get_job(job["id"], tmp_db) is None

    def test_delete_nonexistent(self, tmp_db):
        """删除不存在的任务返回 False。"""
        assert sched.delete_job("nonexistent", tmp_db) is False


# ══════════════════════════════════════════════════════════
# Job 更新
# ══════════════════════════════════════════════════════════

class TestJobUpdate:
    def test_update_name(self, tmp_db):
        """更新任务名。"""
        job = sched.create_job("old", "p1", "ws1", "0 * * * *",
                               created_by="u1", db_path=tmp_db)
        updated = sched.update_job(job["id"], name="new name", db_path=tmp_db)
        assert updated["name"] == "new name"

    def test_update_cron(self, tmp_db):
        """更新 cron 表达式。"""
        job = sched.create_job("test", "p1", "ws1", "0 * * * *",
                               created_by="u1", db_path=tmp_db)
        updated = sched.update_job(job["id"], cron="0 0 * * 0", db_path=tmp_db)
        assert updated["cron"] == "0 0 * * 0"

    def test_update_invalid_cron_raises(self, tmp_db):
        """无效 cron 表达式抛 ValueError。"""
        job = sched.create_job("test", "p1", "ws1", "0 * * * *",
                               created_by="u1", db_path=tmp_db)
        with pytest.raises(ValueError):
            sched.update_job(job["id"], cron="invalid", db_path=tmp_db)

    def test_update_enabled(self, tmp_db):
        """更新启用状态。"""
        job = sched.create_job("test", "p1", "ws1", "0 * * * *",
                               created_by="u1", db_path=tmp_db)
        assert job["enabled"] is True
        updated = sched.update_job(job["id"], enabled=False, db_path=tmp_db)
        assert updated["enabled"] is False

    def test_update_nonexistent_returns_none(self, tmp_db):
        """更新不存在的任务返回 None。"""
        assert sched.update_job("nonexistent", name="x", db_path=tmp_db) is None

    def test_update_empty_fields_unchanged(self, tmp_db):
        """空字段不更新。"""
        job = sched.create_job("test", "p1", "ws1", "0 * * * *",
                               created_by="u1", db_path=tmp_db)
        updated = sched.update_job(job["id"], db_path=tmp_db)
        assert updated["name"] == "test"
        assert updated["cron"] == "0 * * * *"


# ══════════════════════════════════════════════════════════
# Cron 验证
# ══════════════════════════════════════════════════════════

class TestCronValidation:
    def test_valid_cron_5_fields(self, tmp_db):
        """标准 5 字段 cron 表达式。"""
        for cron in ["0 2 * * *", "*/5 * * * *", "0 0 1 * *", "0 0 * * 0"]:
            job = sched.create_job("test", "p1", "ws1", cron,
                                   created_by="u1", db_path=tmp_db)
            assert job["cron"] == cron

    def test_invalid_cron_raises(self, tmp_db):
        """无效 cron 抛 ValueError。"""
        for bad_cron in ["invalid", "0 0 0 0 0 0 0", "", "* * * *"]:
            with pytest.raises(ValueError):
                sched.create_job("test", "p1", "ws1", bad_cron,
                                 created_by="u1", db_path=tmp_db)


# ══════════════════════════════════════════════════════════
# 工作区隔离
# ══════════════════════════════════════════════════════════

class TestWorkspaceIsolation:
    def test_list_filtered_by_workspace(self, tmp_db):
        """list_jobs 按工作区过滤。"""
        sched.create_job("ws1-job", "p1", "ws1", "0 * * * *",
                         created_by="u1", db_path=tmp_db)
        sched.create_job("ws2-job", "p2", "ws2", "0 * * * *",
                         created_by="u1", db_path=tmp_db)

        ws1_jobs = sched.list_jobs(workspace="ws1", db_path=tmp_db)
        assert len(ws1_jobs) == 1
        assert ws1_jobs[0]["name"] == "ws1-job"

        ws2_jobs = sched.list_jobs(workspace="ws2", db_path=tmp_db)
        assert len(ws2_jobs) == 1
        assert ws2_jobs[0]["name"] == "ws2-job"


# ══════════════════════════════════════════════════════════
# 调度器生命周期
# ══════════════════════════════════════════════════════════

class TestSchedulerLifecycle:
    def test_get_scheduler_returns_singleton(self):
        """get_scheduler 返回单例。"""
        s1 = sched.get_scheduler()
        s2 = sched.get_scheduler()
        assert s1 is s2

    def test_start_and_shutdown(self):
        """调度器可以启动和停止（需事件循环）。"""
        async def _test():
            # 重置全局调度器
            sched._scheduler = None
            sched.start_scheduler()
            s = sched.get_scheduler()
            assert s.running is True
            sched.shutdown_scheduler()
            # 给调度器一点时间完成关闭
            await asyncio.sleep(0.1)
            assert s.running is False
            # 清理
            sched._scheduler = None
        asyncio.run(_test())


# ══════════════════════════════════════════════════════════
# 手动触发
# ══════════════════════════════════════════════════════════

class TestTriggerJob:
    def test_trigger_nonexistent_job(self):
        """触发不存在的任务返回错误。"""
        result = asyncio.run(sched.trigger_job_now("nonexistent"))
        assert result["status"] == "failed"
        assert "不存在" in result["error"]
