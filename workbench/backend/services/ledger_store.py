"""ledger_store — 业务台账投影层（K-xxx：文件真相源 + SQLite 台账）。

架构原则：**文件是权威，DB 是投影**——
- 场景/草稿/计划/报告的真相源仍是文件（引擎 pytest 直读、git 版本管理、三道闸不变）
- workbench.db（与 user_store 同库）保存可查询台账：运行记录、失败索引、
  场景元数据、草稿状态、Agent 会话元数据
- DB 任何时刻可从文件全量重建（本模块提供 sync_* 入口），不一致以文件为准

表：
- runs / run_cases：运行汇总与逐场景结果（failures 查询由 run_cases 派生，不单独建表）
- scenarios：场景元数据投影（由 scenario_store 扫描落库）
- drafts：草稿状态（draft/promoted/discarded）
- agent_sessions：Agent 会话元数据（消息数/token，由 session.save 落库）

约束：单 worker 部署，WAL + 短事务（与 user_store 同模式）；所有写入 try/except
包裹在调用侧——台账失败绝不影响引擎执行与文件主流程。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "data" / "workbench.db"
SG_ROOT = BACKEND_DIR.parent.parent

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    reports_root TEXT NOT NULL DEFAULT '',
    env TEXT NOT NULL DEFAULT '',
    workspace TEXT NOT NULL DEFAULT '',
    emp_no TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    pass_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    skip_count INTEGER NOT NULL DEFAULT 0,
    blocked_count INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    report_dir TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS run_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    verdict TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    UNIQUE(run_id, scenario_id)
);
CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    module TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'P1',
    tags TEXT NOT NULL DEFAULT '[]',
    covers TEXT NOT NULL DEFAULT '[]',
    file_path TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS drafts (
    filename TEXT NOT NULL,
    workspace TEXT NOT NULL DEFAULT '',
    scenario_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    module TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (filename, workspace)
);
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id TEXT PRIMARY KEY,
    emp_no TEXT NOT NULL DEFAULT '',
    workspace TEXT NOT NULL DEFAULT '',
    msg_count INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""

# run_cases 扩展列（执行台账：全量结果 + 断言摘要 + 上下文变量）——幂等 ALTER
_RUN_CASES_EXTRA_COLS = {
    "title": "TEXT NOT NULL DEFAULT ''",
    "covers": "TEXT NOT NULL DEFAULT '[]'",
    "assertion_passed": "INTEGER NOT NULL DEFAULT 0",
    "assertion_total": "INTEGER NOT NULL DEFAULT 0",
    "saved_vars": "TEXT NOT NULL DEFAULT '{}'",
}


def _ensure_run_cases_columns(db_path: Path | None = None):
    """run_cases 扩展列（幂等：PRAGMA table_info 检查后 ALTER）。"""
    with _LOCK, _connect(db_path) as conn:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(run_cases)")}
        for col, ddl in _RUN_CASES_EXTRA_COLS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE run_cases ADD COLUMN {col} {ddl}")


def _root_key(reports_root: Path) -> str:
    """报告根目录的台账键（相对仓库根的 posix 路径；越界时用绝对路径）——多工作区隔离。"""
    try:
        return str(Path(reports_root).resolve().relative_to(SG_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(reports_root).resolve()).replace("\\", "/")


def _active_workspace() -> str:
    """当前激活工作区名（台账隔离用；取不到返回空）。"""
    try:
        from specstd.workspace import get_active_workspace
        info = get_active_workspace()
        if info is None:
            return ""
        name = info.get("name") if isinstance(info, dict) else getattr(info, "name", "")
        return str(name or "")
    except Exception:
        return ""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_tables(db_path: Path | None = None):
    """建表（幂等），应用启动时调用。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript(SCHEMA)
    _ensure_run_cases_columns(db_path)


# ══════════════════════════════════════════════════════════
# 运行台账（runs / run_cases）——由 run.json 落库
# ══════════════════════════════════════════════════════════

def upsert_run_from_json(reports_root: Path, run_id: str, source: str = "",
                         db_path: Path | None = None) -> int:
    """把 {reports_root}/{run_id}/run.json 落库（幂等，重复调用覆盖更新）。

    返回写入的 case 条数；run.json 不存在（如 engine_modes 离线自测）返回 0。
    """
    reports_root = Path(reports_root)
    run_json = reports_root / run_id / "run.json"
    if not run_json.is_file():
        return 0
    try:
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return 0
    stats = run_data.get("stats") or {}
    cases = run_data.get("cases") or []
    now = datetime.now().isoformat(timespec="seconds")
    trigger = run_data.get("trigger") or {}
    root_key = _root_key(reports_root)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO runs (run_id, reports_root, env, workspace, emp_no, source,
                                 started_at, finished_at, pass_count, fail_count,
                                 skip_count, blocked_count, total, report_dir)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET
                 reports_root=excluded.reports_root,
                 env=excluded.env, workspace=excluded.workspace,
                 started_at=excluded.started_at, finished_at=excluded.finished_at,
                 pass_count=excluded.pass_count, fail_count=excluded.fail_count,
                 skip_count=excluded.skip_count, blocked_count=excluded.blocked_count,
                 total=excluded.total, report_dir=excluded.report_dir""",
            (run_id, root_key,
             run_data.get("env", ""),
             trigger.get("workspace", ""),
             trigger.get("emp_no", ""),
             source,
             run_data.get("started_at", ""),
             run_data.get("finished_at", ""),
             stats.get("pass", 0), stats.get("fail", 0),
             stats.get("skip", 0), stats.get("blocked", 0),
             stats.get("total", 0),
             f"reports/{run_id}"),
        )
        n = 0
        for case in cases:
            sid = case.get("id", "")
            if not sid:
                continue
            category, message = _case_failure(reports_root, run_id, case)
            detail = _case_detail(reports_root, run_id, case)
            conn.execute(
                """INSERT INTO run_cases (run_id, scenario_id, verdict, duration_ms,
                                          category, message, title, covers,
                                          assertion_passed, assertion_total, saved_vars)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(run_id, scenario_id) DO UPDATE SET
                     verdict=excluded.verdict, duration_ms=excluded.duration_ms,
                     category=excluded.category, message=excluded.message,
                     title=excluded.title, covers=excluded.covers,
                     assertion_passed=excluded.assertion_passed,
                     assertion_total=excluded.assertion_total,
                     saved_vars=excluded.saved_vars""",
                (run_id, sid, case.get("verdict", ""),
                 case.get("duration_ms", 0) or 0, category, message,
                 case.get("title", ""),
                 json.dumps(case.get("covers") or [], ensure_ascii=False),
                 detail["assertion_passed"], detail["assertion_total"],
                 json.dumps(detail["saved_vars"], ensure_ascii=False)))
            n += 1
    return n


def _case_failure(reports_root: Path, run_id: str, case: dict) -> tuple[str, str]:
    """从 cases/{id}.json 提取失败详情（category/message），与 failure_index 同一来源。"""
    case_file = case.get("file") or ""
    case_path = None
    if case_file:
        case_path = reports_root / run_id / case_file
        if not case_path.is_file():
            case_path = reports_root / run_id / "cases" / Path(case_file).name
    if case_path and case_path.is_file():
        try:
            detail = json.loads(case_path.read_text(encoding="utf-8"))
            failure = detail.get("failure") or {}
            return (str(failure.get("category", "")),
                    str(failure.get("message", ""))[:500])
        except Exception:
            pass
    return "", ""


def _case_detail(reports_root: Path, run_id: str, case: dict) -> dict:
    """从 cases/{id}.json 提取断言摘要与 saved_vars（与 failure_index 同源）。"""
    case_file = case.get("file") or ""
    case_path = None
    if case_file:
        case_path = reports_root / run_id / case_file
        if not case_path.is_file():
            case_path = reports_root / run_id / "cases" / Path(case_file).name
    if case_path and case_path.is_file():
        try:
            detail = json.loads(case_path.read_text(encoding="utf-8"))
            assertions = detail.get("assertions") or []
            return {
                "assertion_passed": sum(1 for a in assertions if a.get("passed")),
                "assertion_total": len(assertions),
                "saved_vars": detail.get("saved_vars") or {},
            }
        except Exception:
            pass
    return {"assertion_passed": 0, "assertion_total": 0, "saved_vars": {}}


def sync_runs_from_reports(reports_root: Path, source: str = "",
                           db_path: Path | None = None) -> int:
    """全量重建运行台账：扫描 reports/ 下全部 EX-* 目录的 run.json 落库。

    首次迁移 / 手动重建用。返回导入的 run 数。
    """
    reports_root = Path(reports_root)
    n = 0
    if not reports_root.is_dir():
        return 0
    for d in sorted(reports_root.iterdir()):
        if not d.is_dir() or not (d / "run.json").is_file():
            continue
        n += upsert_run_from_json(reports_root, d.name, source, db_path)
    return n


# ══════════════════════════════════════════════════════════
# 失败查询（failures 由 run_cases 派生）
# ══════════════════════════════════════════════════════════

FAILURE_VERDICTS = ("FAIL", "ERROR", "BLOCKED")


def query_failures(reports_root: Path, scenario_id: str = "", limit: int = 10,
                   db_path: Path | None = None) -> list[dict]:
    """查询失败台账（按时间倒序，可按场景过滤）。

    与 failure_index.query_failures 返回结构一致（run_id/scenario_id/verdict/
    category/message/env/finished_at/log）——查询方无需感知数据源。
    DB 为空而 index.jsonl 有数据时先全量导入（首次迁移）。
    """
    reports_root = Path(reports_root)
    root_key = _root_key(reports_root)
    try:
        ensure_tables(db_path)
        with _LOCK, _connect(db_path) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM run_cases").fetchone()[0]
        if cnt == 0:
            sync_from_index_file(reports_root, db_path)  # 首次迁移（幂等）
            with _LOCK, _connect(db_path) as conn:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM run_cases").fetchone()[0]
        if cnt == 0:
            return []
        sql = """SELECT c.run_id, c.scenario_id, c.verdict, c.category, c.message,
                        r.env, r.finished_at
                 FROM run_cases c JOIN runs r ON r.run_id = c.run_id
                 WHERE c.verdict IN ('FAIL','ERROR','BLOCKED')
                   AND r.reports_root = ?"""
        params: list = [root_key]
        if scenario_id:
            sql += " AND c.scenario_id = ?"
            params.append(scenario_id)
        sql += " ORDER BY r.finished_at DESC, c.id DESC LIMIT ?"
        params.append(limit)
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{
            "run_id": r["run_id"], "scenario_id": r["scenario_id"],
            "verdict": r["verdict"], "category": r["category"] or "",
            "message": r["message"] or "", "env": r["env"] or "",
            "finished_at": r["finished_at"] or "",
            "log": f"reports/{r['run_id']}/output.log",
        } for r in rows]
    except Exception:
        return []


def sync_from_index_file(reports_root: Path, db_path: Path | None = None) -> int:
    """首次迁移：把 failures/index.jsonl 全量导入运行台账（幂等）。"""
    index_path = Path(reports_root) / "failures" / "index.jsonl"
    if not index_path.is_file():
        return 0
    n = 0
    try:
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            run_id = e.get("run_id", "")
            if not run_id:
                continue
            n += upsert_run_from_json(reports_root, run_id, source="migrated", db_path=db_path)
    except Exception:
        pass
    return n


def sync_executions_from_index_file(reports_root: Path, db_path: Path | None = None) -> int:
    """首次迁移：把 executions/index.jsonl 的 run_id 去重后逐次落库（幂等）。

    run.json 才是完整真相源，索引只提供 run_id 清单；从 run.json 落库保证字段完整。
    """
    index_path = Path(reports_root) / "executions" / "index.jsonl"
    if not index_path.is_file():
        return 0
    run_ids = set()
    try:
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("run_id"):
                run_ids.add(e["run_id"])
    except Exception:
        return 0
    n = 0
    for run_id in run_ids:
        n += upsert_run_from_json(reports_root, run_id, db_path=db_path)
    return n


def query_executions_db(reports_root: Path, scenario_id: str = "", run_id: str = "",
                        verdict: str = "", limit: int = 10,
                        db_path: Path | None = None) -> list[dict]:
    """全量执行台账查询（含 PASS；按时间倒序，可按场景/任务号/结果过滤）。

    与 execution_index.query_executions 返回结构一致——查询方无需感知数据源。
    DB 为空而 executions/index.jsonl 有数据时先全量导入（首次迁移）。
    """
    reports_root = Path(reports_root)
    root_key = _root_key(reports_root)
    try:
        ensure_tables(db_path)
        with _LOCK, _connect(db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM run_cases").fetchone()[0]
        if cnt == 0:
            sync_executions_from_index_file(reports_root, db_path)
        sql = """SELECT c.run_id, c.scenario_id, c.verdict, c.duration_ms,
                        c.category, c.message, c.title, c.covers,
                        c.assertion_passed, c.assertion_total, c.saved_vars,
                        r.env, r.finished_at
                 FROM run_cases c JOIN runs r ON r.run_id = c.run_id
                 WHERE r.reports_root = ?"""
        params: list = [root_key]
        if scenario_id:
            sql += " AND c.scenario_id = ?"
            params.append(scenario_id)
        if run_id:
            sql += " AND c.run_id = ?"
            params.append(run_id)
        if verdict:
            sql += " AND c.verdict = ?"
            params.append(verdict)
        sql += " ORDER BY r.finished_at DESC, c.id DESC LIMIT ?"
        params.append(limit)
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{
            "run_id": r["run_id"], "scenario_id": r["scenario_id"],
            "verdict": r["verdict"], "title": r["title"] or "",
            "env": r["env"] or "", "finished_at": r["finished_at"] or "",
            "duration_ms": r["duration_ms"] or 0,
            "covers": _json_loads(r["covers"]) or [],
            "category": r["category"] or "", "message": r["message"] or "",
            "assertion_summary": {
                "passed": r["assertion_passed"] or 0,
                "total": r["assertion_total"] or 0,
            },
            "saved_vars": _json_loads(r["saved_vars"]) or {},
        } for r in rows]
    except Exception:
        return []


def _json_loads(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# 场景台账（scenarios）——scenario_store 扫描后投影
# ══════════════════════════════════════════════════════════

def upsert_scenarios(items: list[dict], db_path: Path | None = None) -> int:
    """场景台账全量覆盖投影（文件为权威：每次扫描结果整表替换）。

    不逐行 upsert——扫描是「当前文件系统的完整快照」，删除的场景文件
    必须从台账消失；测试/脏数据也会被下一次真实扫描自动覆盖。
    """
    if not items:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect(db_path) as conn:
        conn.execute("DELETE FROM scenarios")
        for it in items:
            try:
                conn.execute(
                    """INSERT INTO scenarios (id, title, module, version, fingerprint,
                                               priority, tags, covers, file_path, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         title=excluded.title, module=excluded.module,
                         version=excluded.version, fingerprint=excluded.fingerprint,
                         priority=excluded.priority, tags=excluded.tags,
                         covers=excluded.covers, file_path=excluded.file_path,
                         updated_at=excluded.updated_at""",
                    (it.get("id", ""), it.get("title", ""), it.get("module", ""),
                     str(it.get("version", "")), it.get("fingerprint", ""),
                     it.get("priority", "P1"),
                     json.dumps(it.get("tags") or [], ensure_ascii=False),
                     json.dumps(it.get("covers") or [], ensure_ascii=False),
                     it.get("path", ""),
                     it.get("updated_at", "") or now))
            except Exception:
                continue
    return len(items)


def query_scenarios(db_path: Path | None = None) -> list[dict]:
    """查询场景台账（供统计/检索；列表主链路仍走 scenario_store 文件扫描缓存）。"""
    try:
        ensure_tables(db_path)
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM scenarios ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_drafts(db_path: Path | None = None) -> list[dict]:
    """查询草稿台账（按更新时间倒序）。"""
    try:
        ensure_tables(db_path)
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM drafts ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_scenario_runs(scenario_id: str, limit: int = 10,
                        db_path: Path | None = None) -> list[dict]:
    """某场景的执行历史（按完成时间倒序）。"""
    try:
        ensure_tables(db_path)
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(
                """SELECT c.run_id, c.scenario_id, c.verdict, c.duration_ms,
                          c.category, c.message, r.finished_at
                   FROM run_cases c JOIN runs r ON r.run_id = c.run_id
                   WHERE c.scenario_id = ?
                   ORDER BY r.finished_at DESC, c.id DESC LIMIT ?""",
                (scenario_id, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_scenario_stats(db_path: Path | None = None) -> dict[str, dict]:
    """每场景运行统计：次数/失败数/最近结果/最近 5 次 verdict 序列/修复闭环数。

    闭环定义：该场景按时间序的执行序列中出现 FAIL→PASS 转换（失败后修复，
    再执行通过）——「失败→修复」生命周期闭环的机器可测证据。
    """
    try:
        ensure_tables(db_path)
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(
                """SELECT c.scenario_id, c.verdict, c.run_id, c.category, c.message,
                          r.finished_at
                   FROM run_cases c JOIN runs r ON r.run_id = c.run_id
                   ORDER BY c.scenario_id, r.finished_at, c.id""").fetchall()
    except Exception:
        return {}
    stats: dict[str, dict] = {}
    for row in rows:
        sid = row["scenario_id"]
        st = stats.setdefault(sid, {
            "run_count": 0, "fail_count": 0,
            "last_run_id": "", "last_verdict": "", "last_run_at": "",
            "recent_verdicts": [], "closed_loops": 0,
            "last_failure": None,
        })
        st["run_count"] += 1
        st["last_run_id"] = row["run_id"]
        st["last_verdict"] = row["verdict"]
        st["last_run_at"] = row["finished_at"] or ""
        verdict = row["verdict"]
        st["recent_verdicts"].append(verdict)
        if len(st["recent_verdicts"]) > 5:
            st["recent_verdicts"] = st["recent_verdicts"][-5:]
        if verdict in FAILURE_VERDICTS:
            st["fail_count"] += 1
            st["last_failure"] = {
                "category": row["category"] or "", "message": row["message"] or "",
                "run_id": row["run_id"], "at": row["finished_at"] or "",
            }
        if verdict == "PASS" and st.get("_prev") in FAILURE_VERDICTS:
            st["closed_loops"] += 1
        st["_prev"] = verdict
    for st in stats.values():
        st.pop("_prev", None)
    return stats


# ══════════════════════════════════════════════════════════
# 草稿台账（drafts）——draft_promote / drafts router 更新
# ══════════════════════════════════════════════════════════

def upsert_draft(filename: str, scenario_id: str = "", title: str = "",
                 status: str = "draft", module: str = "", author: str = "",
                 workspace: str = "", db_path: Path | None = None):
    """草稿状态落库（幂等 upsert，按 工作区×文件名 唯一）。"""
    now = datetime.now().isoformat(timespec="seconds")
    ws = workspace or _active_workspace()
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO drafts (filename, workspace, scenario_id, title, status,
                                   module, author, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(filename, workspace) DO UPDATE SET
                 scenario_id=excluded.scenario_id, title=excluded.title,
                 status=excluded.status, module=excluded.module,
                 author=excluded.author, updated_at=excluded.updated_at""",
            (filename, ws, scenario_id, title, status, module, author, now))


def set_draft_status(filename: str, status: str, module: str = "",
                     workspace: str = "", db_path: Path | None = None):
    """草稿状态更新（promoted/discarded），其余字段保留。"""
    now = datetime.now().isoformat(timespec="seconds")
    ws = workspace or _active_workspace()
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE drafts SET status=?, module=?, updated_at=? "
            "WHERE filename=? AND workspace=?",
            (status, module, now, filename, ws))


def clear_drafts(workspace: str = "", db_path: Path | None = None):
    """删除指定工作区的草稿台账全部记录（草稿区重置时调用）。"""
    ws = workspace or _active_workspace()
    with _LOCK, _connect(db_path) as conn:
        conn.execute("DELETE FROM drafts WHERE workspace = ?", (ws,))


# ══════════════════════════════════════════════════════════
# Agent 会话台账（agent_sessions）——session.save 投影
# ══════════════════════════════════════════════════════════

def upsert_session(session_id: str, emp_no: str = "", workspace: str = "",
                   msg_count: int = 0, tool_calls: int = 0,
                   db_path: Path | None = None):
    """会话元数据落库（幂等 upsert）。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO agent_sessions (session_id, emp_no, workspace, msg_count,
                                           tool_calls, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                 msg_count=excluded.msg_count, tool_calls=excluded.tool_calls,
                 updated_at=excluded.updated_at""",
            (session_id, emp_no, workspace, msg_count, tool_calls, now, now))
