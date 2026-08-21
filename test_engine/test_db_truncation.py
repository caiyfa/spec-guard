"""ENG-T06 DB 截断可见性：ReadOnlyDb.last_truncated + step_db_query 三层落痕 + allow_truncate 豁免。

覆盖 ENG-BUG-009：max_rows=1000 静默截断致计数断言失真。全部离线（mock cursor/db）。

设计依据：docs/架构升级/ENG-T06-DB截断可见性.md §6。
"""

import os

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engine.db_oracle import ReadOnlyDb  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.scenario_loader import Scenario  # noqa: E402
from engine.scenario_runner import RunContext, register_builtin_steps, run_scenario  # noqa: E402


# ══════════════════════════════════════════════════════════
# mock 基建
# ══════════════════════════════════════════════════════════

class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchmany(self, n):
        return self._rows[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return FakeCursor(self._rows)

    def ping(self, reconnect=True):
        pass


def _db_returning(n_rows):
    """构造绕过真实连接的 ReadOnlyDb（fetchmany 吐 n_rows 行）。"""
    db = object.__new__(ReadOnlyDb)
    db._conn = FakeConn([{"id": i} for i in range(n_rows)])
    db.last_truncated = False
    return db


class FakeDb:
    """step_db_query 集成用假连接：预置返回行数与截断标志。"""

    def __init__(self, n_rows, truncated):
        self.rows = [{"id": i} for i in range(n_rows)]
        self.last_truncated = truncated

    def query(self, sql):
        return self.rows


def _run_db_query(fakedb, allow_truncate=None, capsys=None):
    reg = Registry()
    register_builtin_steps(reg)
    rc = RunContext(registry=reg, env_config={}, token_provider=None,
                    graph=None, run_dir=".", dbs={"default": fakedb}, db=fakedb)
    body = {"sql": "SELECT id FROM t", "save": "rows"}
    if allow_truncate is not None:
        body["allow_truncate"] = allow_truncate
    sc = Scenario(id="T-DBT", flow=[{"db_query": body}], verify=[])
    return run_scenario(sc, rc)


# ══════════════════════════════════════════════════════════
# ReadOnlyDb.query（验收 1/2/4 单元层）
# ══════════════════════════════════════════════════════════

def test_query_truncates_and_flags():
    """验收1单元：1001 行 → 返回 1000 且 last_truncated=True。"""
    db = _db_returning(1001)
    rows = db.query("SELECT id FROM t")
    assert len(rows) == 1000
    assert db.last_truncated is True


def test_query_under_limit_no_flag():
    """验收2单元：999 行 → 全量返回且 last_truncated=False（回归）。"""
    db = _db_returning(999)
    rows = db.query("SELECT id FROM t")
    assert len(rows) == 999
    assert db.last_truncated is False


def test_query_one_scalar_unaffected():
    """验收4：query_one/scalar 走 max_rows=2 通道，行为不变。"""
    db = _db_returning(1)
    assert db.query_one("SELECT id FROM t") == {"id": 0}
    assert db.scalar("SELECT COUNT(*) FROM t") == 0
    assert db.last_truncated is False


# ══════════════════════════════════════════════════════════
# step_db_query 三层落痕（验收 1/2/3 集成层）
# ══════════════════════════════════════════════════════════

def test_truncated_query_three_layer_visibility(capsys):
    """验收1：截断 → db_traces 含 truncated:true + output.log WARN + record.warnings 条目。"""
    rec = _run_db_query(FakeDb(1000, truncated=True))
    assert rec.verdict == "PASS"
    assert rec.db_traces[0]["truncated"] is True, "db_traces 必须落截断标记"
    assert any("截断" in w for w in rec.warnings), f"场景级 warnings 应含截断条目: {rec.warnings}"
    out = capsys.readouterr().out
    assert "WARN" in out and "截断" in out, f"执行日志应有 WARN 行:\n{out[-400:]}"


def test_untruncated_query_silent(capsys):
    """验收2：999 行无截断 → 无 WARN、warnings 为空（回归保护）。"""
    rec = _run_db_query(FakeDb(999, truncated=False))
    assert rec.verdict == "PASS"
    assert rec.db_traces[0]["truncated"] is False
    assert rec.warnings == []
    out = capsys.readouterr().out
    assert "截断" not in out


def test_allow_truncate_suppresses_warn_keeps_trace(capsys):
    """验收3：allow_truncate:true + 截断 → 落痕保留、WARN/告警消失。"""
    rec = _run_db_query(FakeDb(1000, truncated=True), allow_truncate=True)
    assert rec.verdict == "PASS"
    assert rec.db_traces[0]["truncated"] is True, "落痕必须保留（诚实可见）"
    assert rec.warnings == [], "显式豁免后不再挂场景级告警"
    out = capsys.readouterr().out
    assert "截断" not in out, "显式豁免后不再打 WARN"


def test_warnings_in_to_dict():
    """顶层 warnings 落盘（to_dict 序列化可见）。"""
    rec = _run_db_query(FakeDb(1000, truncated=True))
    d = rec.to_dict()
    assert any("截断" in w for w in d["warnings"])
