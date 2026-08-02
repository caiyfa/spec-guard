"""scheduler: APScheduler 定时任务调度器。

功能：
  - AsyncIOScheduler + SQLite jobstore（持久化，重启不丢）
  - scheduled_jobs 表 CRUD（DB 存储 job 元信息）
  - 生命周期：FastAPI startup 启动 / shutdown 停止
  - 执行入口：调 plan_executor.execute_plan（引擎直跑）
  - workers=1 单进程（serve-prod.ps1 不可改 workers）

DB 表 scheduled_jobs:
    id, name, plan_id, workspace, cron, notify_config_id,
    enabled, created_by, created_at, last_run_at, last_run_status, last_run_id
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

# ── 路径 ──
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "workbench.db"

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ══════════════════════════════════════════════════════════
# 建表
# ══════════════════════════════════════════════════════════

def init_db(db_path: Path | None = None):
    """建 scheduled_jobs 表（幂等）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                workspace TEXT NOT NULL,
                cron TEXT NOT NULL,
                notify_config_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_run_at TEXT DEFAULT '',
                last_run_status TEXT DEFAULT '',
                last_run_id TEXT DEFAULT ''
            );
        """)


# ══════════════════════════════════════════════════════════
# 调度器单例
# ══════════════════════════════════════════════════════════

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """获取全局调度器实例（懒初始化）。"""
    global _scheduler
    if _scheduler is None:
        jobstore = SQLAlchemyJobStore(
            url=f"sqlite:///{DB_PATH}",
            tablename="apscheduler_jobs",
        )
        _scheduler = AsyncIOScheduler(
            jobstores={"default": jobstore},
            job_defaults={"coalesce": True, "max_instances": 1},
        )
    return _scheduler


def start_scheduler():
    """启动调度器（FastAPI startup 调用）。"""
    init_db()
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        # 恢复所有 enabled 的 job
        _restore_jobs(sched)


def shutdown_scheduler():
    """停止调度器（FastAPI shutdown 调用）。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


def _restore_jobs(sched: AsyncIOScheduler):
    """从 DB 恢复所有 enabled 的定时任务到调度器。"""
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_jobs WHERE enabled = 1"
        ).fetchall()

    for row in rows:
        job_id = row["id"]
        # 已存在于调度器中的 job 跳过（APScheduler 的 jobstore 持久化会自动恢复）
        if sched.get_job(job_id):
            continue
        try:
            trigger = CronTrigger.from_crontab(row["cron"])
            sched.add_job(
                _execute_job,
                trigger=trigger,
                args=[job_id],
                id=job_id,
                replace_existing=True,
            )
        except Exception as e:
            print(f"[scheduler WARN] 恢复 job {job_id} 失败: {e}")


# ══════════════════════════════════════════════════════════
# Job 执行入口
# ══════════════════════════════════════════════════════════

async def _execute_job(job_id: str):
    """调度器触发 job 时的执行入口。

    1. 从 DB 读取 job 元信息
    2. 调 plan_executor.execute_plan（引擎直跑）
    3. 更新 last_run_at / last_run_status / last_run_id
    """
    # 读取 job 信息
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)
        ).fetchone()

    if not row:
        print(f"[scheduler WARN] job {job_id} 不存在于 DB，从调度器移除")
        sched = get_scheduler()
        sched.remove_job(job_id)
        return

    plan_id = row["plan_id"]
    workspace = row["workspace"]
    notify_config_id = row["notify_config_id"]

    # T-117：调度与手动执行互斥——已有执行进行中（runner 队列占用）时跳过本次触发。
    # 引擎直跑与 pytest 子进程并发打同一 SIT 环境会互相干扰数据；定时任务周期触发，
    # 忙时跳过记录 skipped_busy，等下次 cron 即可。
    from services.runner import run_manager
    if run_manager.is_running:
        with _LOCK, _connect() as conn:
            conn.execute(
                """UPDATE scheduled_jobs
                   SET last_run_at = ?, last_run_status = 'skipped_busy', last_run_id = ''
                   WHERE id = ?""",
                (_now(), job_id),
            )
            conn.commit()
        print(f"[scheduler WARN] 任务 {row['name']} 跳过："
              f"已有执行进行中（run_id={run_manager.run_id}）")
        return

    print(f"[scheduler] 执行定时任务: {row['name']} (plan={plan_id}, ws={workspace})")

    try:
        from services.plan_executor import execute_plan
        result = await execute_plan(
            plan_id=plan_id,
            workspace=workspace,
            triggered_by="schedule",
            notify_config_id=notify_config_id,
        )

        status = result.get("status", "unknown")
        run_id = result.get("run_id", "")

        with _LOCK, _connect() as conn:
            conn.execute(
                """UPDATE scheduled_jobs
                   SET last_run_at = ?, last_run_status = ?, last_run_id = ?
                   WHERE id = ?""",
                (_now(), status, run_id, job_id),
            )
            conn.commit()

        print(f"[scheduler] 任务完成: {row['name']} → {status} (run_id={run_id})")

    except Exception as e:
        print(f"[scheduler ERROR] 任务执行异常: {row['name']}: {e}")
        with _LOCK, _connect() as conn:
            conn.execute(
                """UPDATE scheduled_jobs
                   SET last_run_at = ?, last_run_status = 'error', last_run_id = ''
                   WHERE id = ?""",
                (_now(), job_id),
            )
            conn.commit()


# ══════════════════════════════════════════════════════════
# Job CRUD
# ══════════════════════════════════════════════════════════

def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "plan_id": row["plan_id"],
        "workspace": row["workspace"],
        "cron": row["cron"],
        "notify_config_id": row["notify_config_id"],
        "enabled": bool(row["enabled"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "last_run_at": row["last_run_at"],
        "last_run_status": row["last_run_status"],
        "last_run_id": row["last_run_id"],
    }


def list_jobs(workspace: str = "", db_path: Path | None = None) -> list[dict]:
    """列出定时任务（可按工作区过滤）。"""
    with _LOCK, _connect(db_path) as conn:
        if workspace:
            rows = conn.execute(
                "SELECT * FROM scheduled_jobs WHERE workspace = ? ORDER BY created_at DESC",
                (workspace,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scheduled_jobs ORDER BY created_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job(job_id: str, db_path: Path | None = None) -> Optional[dict]:
    """获取单个定时任务。"""
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_job(name: str, plan_id: str, workspace: str, cron: str,
               notify_config_id: str = "", created_by: str = "",
               enabled: bool = True, db_path: Path | None = None) -> dict:
    """创建定时任务。

    Args:
        name: 任务名（用户填）
        plan_id: 关联的测试计划 ID
        workspace: 工作区名
        cron: cron 表达式（如 "0 2 * * *"）
        notify_config_id: 通知配置 ID（可选）
        created_by: 创建者工号
        enabled: 是否启用

    Returns:
        创建的 job 字典

    Raises:
        ValueError: cron 表达式无效
    """
    # 验证 cron 表达式
    try:
        trigger = CronTrigger.from_crontab(cron)
    except Exception:
        raise ValueError(f"无效的 cron 表达式: {cron}")

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    now = _now()

    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO scheduled_jobs
               (id, name, plan_id, workspace, cron, notify_config_id,
                enabled, created_by, created_at, last_run_at, last_run_status, last_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '')""",
            (job_id, name, plan_id, workspace, cron, notify_config_id,
             1 if enabled else 0, created_by, now),
        )
        conn.commit()

    # 注册到调度器（如果启用）
    if enabled:
        sched = get_scheduler()
        if sched.running:
            sched.add_job(
                _execute_job,
                trigger=trigger,
                args=[job_id],
                id=job_id,
                replace_existing=True,
            )

    return get_job(job_id, db_path)


def update_job(job_id: str, name: str = "", plan_id: str = "",
               cron: str = "", notify_config_id: str = "",
               enabled: Optional[bool] = None,
               db_path: Path | None = None) -> Optional[dict]:
    """更新定时任务。

    只更新非空字段。如果 cron 变更，重新注册调度器 job。
    """
    job = get_job(job_id, db_path)
    if not job:
        return None

    updates = {}
    if name:
        updates["name"] = name
    if plan_id:
        updates["plan_id"] = plan_id
    if cron:
        # 验证 cron
        try:
            CronTrigger.from_crontab(cron)
        except Exception:
            raise ValueError(f"无效的 cron 表达式: {cron}")
        updates["cron"] = cron
    if notify_config_id is not None:
        updates["notify_config_id"] = notify_config_id
    if enabled is not None:
        updates["enabled"] = 1 if enabled else 0

    if not updates:
        return job

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job_id]

    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            f"UPDATE scheduled_jobs SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()

    # 同步调度器
    updated = get_job(job_id, db_path)
    sched = get_scheduler()
    if sched.running:
        # 移除旧 job
        try:
            sched.remove_job(job_id)
        except Exception:
            pass
        # 如果启用，重新添加
        if updated and updated["enabled"]:
            try:
                trigger = CronTrigger.from_crontab(updated["cron"])
                sched.add_job(
                    _execute_job,
                    trigger=trigger,
                    args=[job_id],
                    id=job_id,
                    replace_existing=True,
                )
            except Exception as e:
                print(f"[scheduler WARN] 重新注册 job {job_id} 失败: {e}")

    return updated


def delete_job(job_id: str, db_path: Path | None = None) -> bool:
    """删除定时任务。"""
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM scheduled_jobs WHERE id = ?", (job_id,)
        )
        conn.commit()
        deleted = cur.rowcount > 0

    # 从调度器移除
    if deleted:
        sched = get_scheduler()
        if sched.running:
            try:
                sched.remove_job(job_id)
            except Exception:
                pass

    return deleted


async def trigger_job_now(job_id: str) -> dict:
    """手动触发一次定时任务执行（不等 cron 到点）。

    T-117：与手动执行互斥——已有执行进行中时拒绝并发触发。

    Returns:
        执行结果（来自 plan_executor.execute_plan）
    """
    job = get_job(job_id)
    if not job:
        return {"run_id": "", "status": "failed", "error": "任务不存在", "results": []}

    from services.runner import run_manager
    if run_manager.is_running:
        return {"run_id": "", "status": "skipped_busy",
                "error": f"已有执行进行中（{run_manager.run_id}），拒绝并发触发", "results": []}

    from services.plan_executor import execute_plan
    result = await execute_plan(
        plan_id=job["plan_id"],
        workspace=job["workspace"],
        triggered_by="manual",
        notify_config_id=job["notify_config_id"],
    )

    # 更新 last_run
    with _LOCK, _connect() as conn:
        conn.execute(
            """UPDATE scheduled_jobs
               SET last_run_at = ?, last_run_status = ?, last_run_id = ?
               WHERE id = ?""",
            (_now(), result.get("status", "unknown"),
             result.get("run_id", ""), job_id),
        )
        conn.commit()

    return result
