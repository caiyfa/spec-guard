"""failure_index 失败索引测试（K-052）。

验证：
1. append_failures：FAIL/BLOCKED/ERROR 入索引，PASS 不入；message 取自 case 详情
2. 幂等：同一 run_id 重复追加不产生重复条目
3. 无 run.json（engine_modes）返回 0
4. query_failures：倒序、按场景过滤、limit
5. MCP read_run_log：白名单/越界守卫 + 尾部截取
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

from services import failure_index


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path, monkeypatch):
    """K-xxx：台账投影隔离到 tmp 库——append_failures 落库不得污染真实 workbench.db。"""
    from services import ledger_store
    monkeypatch.setattr(ledger_store, "DB_PATH", tmp_path / "ledger.db")


def _mk_run(root: Path, run_id: str, cases: list, details: dict | None = None):
    """构造一次运行的报告目录。cases: run.json 的 cases 数组；details: {file: failure dict}"""
    run_dir = root / run_id
    (run_dir / "cases").mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_id, "env": "sit", "finished_at": "2026-08-01T18:00:00",
        "stats": {}, "cases": cases,
    }, ensure_ascii=False), encoding="utf-8")
    for fname, detail in (details or {}).items():
        (run_dir / "cases" / fname).write_text(
            json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    return run_dir


class TestAppendFailures:
    def test_failures_indexed_with_message(self, tmp_path):
        _mk_run(tmp_path, "EX-aaa00001", [
            {"id": "PP-RC-001", "verdict": "PASS", "file": "cases/PP-RC-001.json"},
            {"id": "IS-PREP-002", "verdict": "FAIL", "file": "cases/IS-PREP-002_upstream.json"},
            {"id": "EV-IMP-001", "verdict": "BLOCKED", "file": "cases/EV-IMP-001.json"},
        ], {
            "IS-PREP-002_upstream.json": {"verdict": "FAIL", "failure": {
                "category": "env_error", "message": "变量未定义: activity_name"}},
            "EV-IMP-001.json": {"verdict": "BLOCKED", "failure": {}},
        })
        n = failure_index.append_failures(tmp_path, "EX-aaa00001")
        assert n == 2
        entries = failure_index.query_failures(tmp_path)
        assert len(entries) == 2
        fail_entry = next(e for e in entries if e["scenario_id"] == "IS-PREP-002")
        assert fail_entry["category"] == "env_error"
        assert "activity_name" in fail_entry["message"]
        assert fail_entry["log"] == "reports/EX-aaa00001/output.log"
        blocked_entry = next(e for e in entries if e["scenario_id"] == "EV-IMP-001")
        assert blocked_entry["verdict"] == "BLOCKED"

    def test_idempotent(self, tmp_path):
        _mk_run(tmp_path, "EX-aaa00002", [
            {"id": "X-1", "verdict": "FAIL", "file": "X-1.json"}])
        assert failure_index.append_failures(tmp_path, "EX-aaa00002") == 1
        assert failure_index.append_failures(tmp_path, "EX-aaa00002") == 0
        assert len(failure_index.query_failures(tmp_path)) == 1

    def test_no_run_json_returns_zero(self, tmp_path):
        assert failure_index.append_failures(tmp_path, "EX-nonexist") == 0

    def test_all_pass_no_entries(self, tmp_path):
        _mk_run(tmp_path, "EX-aaa00003", [{"id": "X-1", "verdict": "PASS", "file": "X-1.json"}])
        assert failure_index.append_failures(tmp_path, "EX-aaa00003") == 0
        assert failure_index.query_failures(tmp_path) == []


class TestQueryFailures:
    def test_order_filter_limit(self, tmp_path):
        for i in range(5):
            _mk_run(tmp_path, f"EX-{i:08d}", [
                {"id": "X-1" if i % 2 == 0 else "X-2", "verdict": "FAIL", "file": "a.json"}])
            failure_index.append_failures(tmp_path, f"EX-{i:08d}")
        all_entries = failure_index.query_failures(tmp_path)
        assert len(all_entries) == 5
        assert all_entries[0]["run_id"] == "EX-00000004"  # 最新在前
        x1 = failure_index.query_failures(tmp_path, scenario_id="X-1")
        assert len(x1) == 3
        limited = failure_index.query_failures(tmp_path, limit=2)
        assert len(limited) == 2

    def test_empty_index(self, tmp_path):
        assert failure_index.query_failures(tmp_path) == []


class TestReadRunLog:
    def test_read_log_tail(self, tmp_path):
        run_dir = _mk_run(tmp_path, "EX-bbb00001", [])
        (run_dir / "output.log").write_text("\n".join(f"line{i}" for i in range(50)),
                                            encoding="utf-8")
        import asyncio
        from mcp_server.tools import attribution
        attribution._get_reports_root = lambda: tmp_path  # 测试注入
        out = asyncio.run(attribution.handle("read_run_log", {"run_id": "EX-bbb00001", "tail": 10}))
        r = json.loads(out[0].text)
        assert r["ok"] and r["total_lines"] == 50 and r["returned_lines"] == 10
        assert "line49" in r["log"] and "line40" in r["log"] and "line39" not in r["log"]

    def test_guard_illegal_run_id(self, tmp_path):
        import asyncio
        from mcp_server.tools import attribution
        attribution._get_reports_root = lambda: tmp_path
        out = asyncio.run(attribution.handle("read_run_log", {"run_id": "../etc"}))
        assert "OUT_OF_SCOPE" in out[0].text

    def test_missing_log_friendly(self, tmp_path):
        import asyncio
        from mcp_server.tools import attribution
        attribution._get_reports_root = lambda: tmp_path
        out = asyncio.run(attribution.handle("read_run_log", {"run_id": "2026-01-01_000000"}))
        r = json.loads(out[0].text)
        assert not r["ok"] and "K-050" in r["hint"]
