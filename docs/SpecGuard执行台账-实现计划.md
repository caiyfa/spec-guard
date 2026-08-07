# SpecGuard 执行台账 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引擎每次执行后把全部场景结果（含 PASS）与场景绑定记录（含 saved_vars 上下文变量）落盘为全量执行台账，提供 MCP 工具 `list_executions` 与工作台 API `GET /api/executions` 查询，并在系统提示词中引导 LLM 查询动线。

**Architecture:** 对称扩展 K-052 失败索引模式：文件真相源（`executions/index.jsonl` append-only）+ SQLite 投影（`run_cases` 表扩展列）+ 读降级。`ExecutionRecord.to_dict()` 收录截断后的 saved_vars（解决「活动名称执行后查不到」根因），runner/plan_executor 两处写入入口无条件调用。

**Tech Stack:** Python 3.14 / SQLite（WAL，单 worker）/ MCP stdio / FastAPI / pytest（TDD）

**依据设计文档：** `docs/SpecGuard执行台账设计.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `engine/execution_record.py` | 修改 | `to_dict()` 收录截断 saved_vars |
| `engine/report_writer.py` | 修改 | 移除 `d.pop("saved_vars", None)` |
| `test_engine/test_saved_vars_record.py` | 新建 | 上述行为的单测 |
| `workbench/backend/services/execution_index.py` | 新建 | 全量索引 append/query（文件降级） |
| `test_specstd/test_execution_index.py` | 新建 | 索引 append/幂等/查询/降级 |
| `workbench/backend/services/ledger_store.py` | 修改 | run_cases 加列（幂等 ALTER）+ upsert 填新列 + `query_executions_db` + `sync_executions_from_index_file` |
| `test_specstd/test_ledger_store.py` | 修改 | 新列/全量落库/查询过滤 |
| `workbench/backend/services/runner.py` | 修改 | `_record_executions` + 调用点 |
| `workbench/backend/services/plan_executor.py` | 修改 | 执行索引写入 |
| `test_specstd/test_plan_executor.py` | 修改 | 断言执行索引被调用 |
| `test_specstd/test_runner.py` | 修改 | 3 处 stub 补 `_record_executions` |
| `mcp_server/tools/attribution.py` | 修改 | `list_executions` 工具 |
| `test_specstd/test_mcp_server.py` | 修改 | 工具注册数/名单 + 新用例 |
| `workbench/backend/routers/executions.py` | 新建 | `GET /api/executions` |
| `workbench/backend/main.py` | 修改 | 注册 executions router |
| `agent/prompts/system.md.j2` | 修改 | 新增「执行记录查询」段 |

**依赖序：** Task 1（engine 落盘）→ Task 2（索引模块）→ Task 3（DB 投影）→ Task 4（写入入口）→ Task 5（MCP 工具）→ Task 6（API）→ Task 7（提示词）。每任务独立可测可提交。

---

## Task 1: Engine saved_vars 落盘

**Files:**
- Modify: `engine/execution_record.py:106-109`（to_dict）
- Modify: `engine/report_writer.py:30`（移除 pop）
- Test: `test_engine/test_saved_vars_record.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `test_engine/test_saved_vars_record.py`：

```python
"""ExecutionRecord.to_dict 收录截断 saved_vars（全量执行台账数据源）。"""
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_engine/test_saved_vars_record.py -v`
Expected: FAIL——`KeyError: 'saved_vars'`（to_dict 当前不含该键）

- [ ] **Step 3: 实现**

`engine/execution_record.py` 的 `to_dict`（第 106-109 行）改为：

```python
    def to_dict(self):
        d = asdict(self)
        d["warning_count"] = self.warning_count   # @property 不被 asdict 收录，手动补充
        d["saved_vars"] = truncate(getattr(self, "saved_vars", {}))
        return d
```

`engine/report_writer.py` 第 30 行删除 `d.pop("saved_vars", None)`（该行单独删除，保留前后注释与缩进结构）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_engine/test_saved_vars_record.py -v`
Expected: 3 passed

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest test_engine -v`（确认既有引擎单测不受影响）
Expected: 全绿

```bash
git add engine/execution_record.py engine/report_writer.py test_engine/test_saved_vars_record.py
git commit -m "feat: ExecutionRecord 落盘截断 saved_vars（执行上下文可追溯）"
```

---

## Task 2: execution_index 全量索引模块

**Files:**
- Create: `workbench/backend/services/execution_index.py`
- Test: `test_specstd/test_execution_index.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `test_specstd/test_execution_index.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_specstd/test_execution_index.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'services.execution_index'`

- [ ] **Step 3: 实现**

新建 `workbench/backend/services/execution_index.py`：

```python
"""execution_index — 全量执行索引（场景 × 执行 × 结果绑定台账）。

每次执行完成后，把 run.json 中全部场景（不过滤 verdict）追加到
`{reports_root}/executions/index.jsonl`——「场景 × 任务号 × 全量结果（含 PASS）
× 断言摘要 × 执行上下文变量 saved_vars」可查询台账，供 Agent list_executions
工具与工作台 API 查询。

设计约束（对称 failure_index）：
- 只追加不修改（jsonl append），并发安全由 runner 单实例串行保证
- 文件仍是真相源；写文件后顺带投影到 SQLite（ledger_store）
- 读路径纯读零副作用；台账不可用时降级读文件
"""

import json
from pathlib import Path

EXECUTIONS_INDEX_REL = Path("executions") / "index.jsonl"


def append_executions(reports_root: Path, run_id: str) -> int:
    """从 {reports_root}/{run_id}/run.json + cases/*.json 提取全部场景条目追加索引。

    返回追加条数；run.json 不存在（如 engine_modes 离线自测）返回 0。
    幂等：同一 run_id 重复调用不产生重复条目。
    写文件后同步落库（投影层，失败不影响主流程）。
    """
    reports_root = Path(reports_root)
    run_json = reports_root / run_id / "run.json"
    if not run_json.is_file():
        return 0
    try:
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return 0

    index_path = reports_root / EXECUTIONS_INDEX_REL
    # 幂等检查：索引中已有该 run_id 的条目则跳过
    if index_path.is_file():
        try:
            if f'"run_id": "{run_id}"' in index_path.read_text(encoding="utf-8"):
                return 0
        except Exception:
            pass

    entries = []
    for case in run_data.get("cases", []):
        sid = case.get("id", "")
        if not sid:
            continue
        # 断言摘要与 saved_vars 在 cases/{id}.json（file 字段自带 cases/ 前缀）
        detail = {}
        case_file = case.get("file") or ""
        case_path = None
        if case_file:
            case_path = reports_root / run_id / case_file
            if not case_path.is_file():
                case_path = reports_root / run_id / "cases" / Path(case_file).name
        if case_path and case_path.is_file():
            try:
                detail = json.loads(case_path.read_text(encoding="utf-8"))
            except Exception:
                detail = {}
        failure = detail.get("failure") or {}
        assertions = detail.get("assertions") or []
        entries.append({
            "run_id": run_id,
            "scenario_id": sid,
            "verdict": case.get("verdict", ""),
            "title": case.get("title", ""),
            "env": run_data.get("env", ""),
            "finished_at": run_data.get("finished_at", ""),
            "duration_ms": case.get("duration_ms", 0) or 0,
            "covers": case.get("covers") or [],
            "category": str(failure.get("category", "")),
            "message": str(failure.get("message", ""))[:500],
            "assertion_summary": {
                "passed": sum(1 for a in assertions if a.get("passed")),
                "total": len(assertions),
            },
            "saved_vars": detail.get("saved_vars") or {},
        })

    if not entries:
        return 0
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    # 投影到 SQLite 台账（失败不影响文件主流程）
    try:
        from services import ledger_store
        ledger_store.upsert_run_from_json(reports_root, run_id)
    except Exception:
        pass
    return len(entries)


def query_executions(reports_root: Path, scenario_id: str = "", run_id: str = "",
                     verdict: str = "", limit: int = 10) -> list[dict]:
    """查询执行索引（按时间倒序，可按场景/任务号/结果过滤）。纯读。

    优先查 SQLite 台账；台账不可用时回退读 index.jsonl 文件——保证降级可用。
    """
    reports_root = Path(reports_root)
    try:
        from services import ledger_store
        rows = ledger_store.query_executions_db(reports_root, scenario_id, run_id,
                                                verdict, limit)
        if rows:
            return rows
    except Exception:
        pass
    return _query_from_file(reports_root, scenario_id, run_id, verdict, limit)


def _query_from_file(reports_root: Path, scenario_id: str = "", run_id: str = "",
                     verdict: str = "", limit: int = 10) -> list[dict]:
    """原文件读法（台账不可用时的降级路径）。"""
    index_path = Path(reports_root) / EXECUTIONS_INDEX_REL
    if not index_path.is_file():
        return []
    entries = []
    try:
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if scenario_id and e.get("scenario_id") != scenario_id:
                continue
            if run_id and e.get("run_id") != run_id:
                continue
            if verdict and e.get("verdict") != verdict:
                continue
            entries.append(e)
    except Exception:
        return []
    entries.reverse()  # 最新在前
    return entries[:limit]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_specstd/test_execution_index.py -v`
Expected: 6 passed（注意：Task 3 完成前 `query_executions` 的 DB 分支会因 `query_executions_db` 未定义走降级路径，文件分支已可测通）

- [ ] **Step 5: 提交**

```bash
git add workbench/backend/services/execution_index.py test_specstd/test_execution_index.py
git commit -m "feat: 全量执行索引 execution_index（场景×执行×全量结果绑定）"
```

---

## Task 3: ledger_store 台账扩展（run_cases 加列 + 查询）

**Files:**
- Modify: `workbench/backend/services/ledger_store.py`
- Test: `test_specstd/test_ledger_store.py`

- [ ] **Step 1: 写失败测试**

`test_specstd/test_ledger_store.py` 扩展：

1. `RUN_JSON` fixture 的 cases 补 title/covers（保留原断言不受影响）：

```python
    "cases": [
        {"id": "TL-RC-006", "title": "通过场景", "verdict": "PASS",
         "duration_ms": 100, "covers": ["FR-006"],
         "file": "cases/TL-RC-006.json"},
        {"id": "TL-RC-014", "title": "失败场景", "verdict": "FAIL",
         "duration_ms": 200, "covers": ["FR-014"],
         "file": "cases/TL-RC-014.json"},
    ],
```

2. `env` fixture 补 TL-RC-006 case 文件（TL-RC-014 已有，补 assertions/saved_vars）：

```python
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
```

3. `TestRunsLedger` 加新用例（类内追加）：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_specstd/test_ledger_store.py -v`
Expected: 新用例 FAIL——`no such column: title`（run_cases 无新列）/ `AttributeError: query_executions_db`

- [ ] **Step 3: 实现**

`workbench/backend/services/ledger_store.py` 修改 4 处：

**3a. 顶部加扩展列常量与幂等 ALTER**（放在 `SCHEMA` 之后）：

```python
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
```

**3b. `ensure_tables` 末尾追加**：

```python
    with _LOCK, _connect(db_path) as conn:
        conn.executescript(SCHEMA)
    _ensure_run_cases_columns(db_path)
```

**3c. `_case_failure` 之后新增 `_case_detail`**：

```python
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
```

**3d. `upsert_run_from_json` 的 run_cases INSERT 扩展**（第 181-195 行替换）：

```python
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
```

**3e. `sync_from_index_file` 之后新增两个函数**：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_specstd/test_ledger_store.py -v`
Expected: 全绿（原有用例 + 新增 2 用例）

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest test_specstd/test_execution_index.py test_specstd/test_ledger_store.py -v`
Expected: 全绿（Task 2 的 DB 分支此时走真实新查询路径）

```bash
git add workbench/backend/services/ledger_store.py test_specstd/test_ledger_store.py
git commit -m "feat: run_cases 台账扩展列与全量执行查询（含 PASS）"
```

---

## Task 4: 写入入口（runner + plan_executor）

**Files:**
- Modify: `workbench/backend/services/runner.py:381`（调用点）、`runner.py:408-421` 后（新方法）
- Modify: `workbench/backend/services/plan_executor.py:300-306` 后
- Test: `test_specstd/test_plan_executor.py`、`test_specstd/test_runner.py`

- [ ] **Step 1: 写失败测试**

`test_specstd/test_plan_executor.py` 的 `test_ex_run_id_and_plan_dir` 内追加（在 failure_index monkeypatch 之后）：

```python
        import services.execution_index as execution_index
        ecalls = []
        monkeypatch.setattr(execution_index, "append_executions",
                            lambda root, run_id: ecalls.append((root, run_id)) or 2)
```

并在既有断言后追加：

```python
        assert ecalls, "执行索引必须被调用（全量结果台账）"
        assert str(ecalls[0][1]) == f"p1/{run_id}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_specstd/test_plan_executor.py::TestExecutorUnifiedArtifacts::test_ex_run_id_and_plan_dir -v`
Expected: FAIL——`assert ecalls` 空列表（plan_executor 尚未调用 append_executions）

- [ ] **Step 3: 实现**

**3a. `plan_executor.py`**：在 T-116 失败索引块（L300-306）之后追加：

```python
    # 全量执行索引（与 runner 侧 _record_executions 对齐）——
    # 定时/引擎直跑执行的全部结果同样进 executions/index.jsonl 台账
    try:
        from services import execution_index
        n = execution_index.append_executions(reports_root, f"{plan_id}/{run_id}")
        if n:
            print(f"[plan_executor] {n} 条执行记录已记入 executions/index.jsonl")
    except Exception as e:
        print(f"[SpecGuard WARN] 执行索引写入失败（不影响执行结论）: {type(e).__name__}: {e}")
```

**3b. `runner.py`**：

调用点（L381 `self._record_failures()  # K-052...` 之后）追加：

```python
        self._record_executions()  # 执行台账：全量结果（场景×任务号×verdict×saved_vars）
```

新方法（`_record_failures` 之后追加）：

```python
    def _record_executions(self):
        """执行完成后把全部场景结果写入执行索引（executions/index.jsonl）——
        「场景 × 任务号 × 全量结果（含 PASS）」台账，Agent list_executions 与工作台 API 共用。"""
        try:
            from services import execution_index
            root = _get_reports_root()
            n = execution_index.append_executions(root, self.run_id)
            # 断点分批执行的报告在 {run_id}-bN 目录，逐批收录
            for batch_dir in sorted(root.glob(f"{self.run_id}-b*")):
                n += execution_index.append_executions(root, batch_dir.name)
            if n:
                self._write_output_log(f"> {self.run_id} | {n} 条执行记录已记入 executions/index.jsonl")
        except Exception:
            pass  # 索引失败不影响执行结论
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_specstd/test_plan_executor.py -v`
Expected: 全绿

- [ ] **Step 5: 同步 runner 测试 stub**

`test_specstd/test_runner.py` 3 处 `monkeypatch.setattr(m, "_record_failures", lambda: None)`（L253/L285/L363）之后各补一行：

```python
        monkeypatch.setattr(m, "_record_executions", lambda: None)
```

Run: `python -m pytest test_specstd/test_runner.py -v`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add workbench/backend/services/runner.py workbench/backend/services/plan_executor.py test_specstd/test_plan_executor.py test_specstd/test_runner.py
git commit -m "feat: runner/plan_executor 执行后写入全量执行台账"
```

---

## Task 5: MCP 工具 list_executions

**Files:**
- Modify: `mcp_server/tools/attribution.py`
- Test: `test_specstd/test_mcp_server.py`

- [ ] **Step 1: 写失败测试**

`test_specstd/test_mcp_server.py` 修改：

1. `test_11_tools_registered`：`assert len(ALL_TOOLS) == 25` → `== 26`
2. `test_tool_names` 的 expected 集合加 `"list_executions"`（放在 `"list_failures", "read_run_log"` 同一行前）
3. 文件尾部追加新测试类：

```python
# ══════════════════════════════════════════════════════════
# list_executions（全量执行台账）
# ══════════════════════════════════════════════════════════

class TestListExecutions:
    def test_list_executions_empty(self, workspace):
        """无执行记录时返回空列表 + hint。"""
        result = _call(attribution, "list_executions", {})
        data = json.loads(result[0].text)
        assert data["ok"] is True and data["count"] == 0
        assert "hint" in data

    def test_list_executions_filters(self, workspace, monkeypatch, tmp_path):
        """按 scenario_id 过滤 + saved_vars 可见（台账不可用 → 文件降级）。"""
        import services.ledger_store as ledger_store
        monkeypatch.setattr(ledger_store, "query_executions_db", lambda *a, **k: [])
        index = tmp_path / "reports" / "executions"
        index.mkdir(parents=True)
        (index / "index.jsonl").write_text(
            json.dumps({"run_id": "EX-001", "scenario_id": "ST-01", "verdict": "PASS",
                        "title": "t", "env": "sit", "finished_at": "2026-08-07T10:00:00",
                        "duration_ms": 1, "covers": [], "category": "", "message": "",
                        "assertion_summary": {"passed": 1, "total": 1},
                        "saved_vars": {"activityName": "SG历史DAG-1"}}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        monkeypatch.setattr(attribution, "_get_reports_root", lambda: tmp_path / "reports")
        result = _call(attribution, "list_executions", {"scenario_id": "ST-01"})
        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["executions"][0]["saved_vars"]["activityName"] == "SG历史DAG-1"
```

（顶部 import 需加 `from mcp_server.tools import attribution`）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_specstd/test_mcp_server.py -v`
Expected: FAIL——`assert len(ALL_TOOLS) == 26` 实际 25；新用例 FAIL（`attribution` 未导入 / 未知工具）

- [ ] **Step 3: 实现**

`mcp_server/tools/attribution.py` 修改 3 处：

**3a. TOOLS 追加**（`read_run_log` Tool 定义之后）：

```python
    Tool(
        name="list_executions",
        description="查询全量执行索引（执行台账）：返回「场景 × 任务号（EX-xxx）× 全量结果"
                    "（含 PASS）」，最新在前。每条含断言摘要与执行上下文变量 saved_vars"
                    "（如动态生成的活动 ID/名称）。可按 scenario_id/run_id/verdict 过滤。"
                    "查某测试最近执行结果（含成功）或执行用的参数用它；只查失败用 list_failures。",
        inputSchema={
            "type": "object",
            "properties": {
                "scenario_id": {"type": "string", "description": "可选：只看该场景的执行记录"},
                "run_id": {"type": "string", "description": "可选：只看某次执行的全部场景"},
                "verdict": {"type": "string",
                            "description": "可选：按结果过滤（PASS/FAIL/SKIP/BLOCKED/DRIFT/ORPHANED）"},
                "limit": {"type": "integer", "description": "返回条数（默认 10）"},
            }
        }
    ),
```

**3b. handle 分发**（`elif name == "read_run_log":` 分支后）：

```python
    elif name == "list_executions":
        return _handle_list_executions(arguments)
```

**3c. 处理函数**（`_handle_read_run_log` 之前）：

```python
def _handle_list_executions(arguments: dict) -> list[TextContent]:
    """全量执行索引查询：services.execution_index 的 MCP 出口。"""
    from services import execution_index

    scenario_id = str(arguments.get("scenario_id", "") or "")
    run_id = str(arguments.get("run_id", "") or "")
    verdict = str(arguments.get("verdict", "") or "")
    limit = int(arguments.get("limit", 10) or 10)
    entries = execution_index.query_executions(_get_reports_root(), scenario_id, run_id,
                                               verdict, limit)
    out = {
        "ok": True,
        "count": len(entries),
        "executions": entries,
        "note": "拿到 run_id 后：read_run_log 看完整执行日志（含 trace_id），"
                "read_run_report 看断言差异与步骤轨迹",
    }
    if not entries:
        out["hint"] = ("索引为空或该场景近期无执行记录；索引由执行控制在每次运行完成后写入 "
                       "executions/index.jsonl（本功能上线后的执行才有）")
    return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_specstd/test_mcp_server.py -v`
Expected: 全绿（工具数 26，名单含 list_executions，新用例通过）

- [ ] **Step 5: 提交**

```bash
git add mcp_server/tools/attribution.py test_specstd/test_mcp_server.py
git commit -m "feat: MCP 工具 list_executions 查询全量执行台账"
```

---

## Task 6: 工作台 API GET /api/executions

**Files:**
- Create: `workbench/backend/routers/executions.py`
- Modify: `workbench/backend/main.py:107` 附近（router 注册）

- [ ] **Step 1: 实现 router**

新建 `workbench/backend/routers/executions.py`：

```python
"""执行台账查询 API：GET /api/executions（场景 × 执行 × 全量结果绑定记录）。

数据源为 services.execution_index（文件真相源 + SQLite 投影 + 文件降级），
响应结构与 MCP 工具 list_executions 一致。
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends

from services.auth import CurrentUser, get_current_user

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from services import execution_index  # noqa: E402
from specstd.workspace import reports_dir  # noqa: E402

router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("")
async def api_list_executions(scenario_id: str = "", run_id: str = "",
                              verdict: str = "", limit: int = 10,
                              user: CurrentUser = Depends(get_current_user)):
    """查询执行台账（全量含 PASS，最新在前；可按场景/任务号/结果过滤）。"""
    try:
        root = reports_dir()
    except Exception:
        root = SG_ROOT / "reports"
    entries = execution_index.query_executions(root, scenario_id, run_id, verdict, limit)
    return {"ok": True, "count": len(entries), "executions": entries}
```

- [ ] **Step 2: main.py 注册**

`workbench/backend/main.py` 的 router 导入区（`from routers import ...` 处）加：

```python
from routers import executions as executions_router
```

`app.include_router` 区（如 `reference.router` 附近）加：

```python
app.include_router(executions.router, dependencies=[Depends(get_current_user)])
```

- [ ] **Step 3: 冒烟验证**

```powershell
cd workbench/backend && uvicorn main:app --port 9100
```

另开终端（需登录态，`SG_AUTH_MODE=mock` 时用 mock 登录）：
`GET http://localhost:9100/api/executions?scenario_id=ST01-IMP-001`
Expected: `{"ok": true, "count": N, "executions": [...]}`（N≥0；此时引擎尚未写入也可返回空列表）

- [ ] **Step 4: 提交**

```bash
git add workbench/backend/routers/executions.py workbench/backend/main.py
git commit -m "feat: 工作台 API GET /api/executions 查询执行台账"
```

---

## Task 7: 系统提示词引导 LLM 查询记录

**Files:**
- Modify: `agent/prompts/system.md.j2`

- [ ] **Step 1: 实现**

`agent/prompts/system.md.j2` 在「## 切换工作区后」段与「## 任务行为指引」段之间插入：

```markdown
## 执行记录查询

引擎每次执行后会把全部场景结果写入执行台账（executions/index.jsonl + SQLite 投影）：
- list_executions：查某场景/某次执行的执行记录（**全量含 PASS**，最新在前；每条含
  执行上下文变量 saved_vars，如动态生成的活动 ID/名称）——查「某测试执行结果/执行
  用的参数」用它
- list_failures：只查失败子集（FAIL/ERROR/BLOCKED）——归因优化失败场景时用它
- read_run_log / read_run_report：拿到 run_id（EX-xxx）后看完整日志与断言差异

动线示例：查 ST01 最近执行用的活动名称 → list_executions(scenario_id=UT01-PREP-001)
看 saved_vars.activity.json.data.activityName → 需要更多证据再 read_run_report(run_id)。
```

- [ ] **Step 2: 回归验证**

Run: `python -m pytest test_specstd/test_agent.py -v`
Expected: 全绿（提示词段为追加，不破坏既有断言；若存在对 system.md.j2 全文/长度的断言则同步更新）

Run: `python -m pytest test_specstd -v`
Expected: 全绿（含 Task 2-5 全部新增）

- [ ] **Step 3: 提交**

```bash
git add agent/prompts/system.md.j2
git commit -m "docs: 系统提示词新增执行记录查询指引（list_executions 动线）"
```

---

## 自审清单（实现前对照）

- [ ] **Spec 覆盖**：设计文档 §4.2 ①-⑤ 均有对应 Task（①→T1，②→T2，③→T3，④→T4，⑤→T5/T6/T7）；§5 测试计划全部落位
- [ ] **占位符**：无 TBD/TODO；所有代码完整可执行
- [ ] **类型一致**：`query_executions` / `query_executions_db` / `append_executions` 签名在 T2/T3/T5/T6 中一致；`saved_vars` 字段名贯穿 T1-T5
- [ ] **三同步**：不新增 YAML 语法/步骤/断言器，无需 format_spec 变更；`contracts_baseline.json` 不受影响（报告产物扩展）
- [ ] **幂等**：文件层 run_id 检测 + DB `ON CONFLICT`，双路径重复执行安全
- [ ] **冻结层评审**：execution_record.py / report_writer.py 仅报告产物扩展，已按项目惯例在设计文档 §6 声明
