"""plan_executor 执行路径统一测试（T-116）。

背景：引擎直跑路径（定时/计划）与 runner 路径产物不一致——
时间戳 run_id（同一秒两次触发目录互相覆盖、无法按任务号排错）；
无 output.log/trigger.json；失败不进 failures/index.jsonl；报告目录无 plan 前缀
（list_plan_history 读 reports/{plan_id}/ 永远读不到）。

验证：
1. run_id 为 EX- 格式；报告目录 reports/{plan_id}/{run_id}/
2. output.log / trigger.json 落盘（含每场景 verdict 行）
3. 结束后失败索引被调用（root=reports_root, run_id=plan_id/run_id）
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.plan_executor as pe  # noqa: E402
from engine.execution_record import ExecutionRecord  # noqa: E402


class FakeGraph:
    def __init__(self):
        self.by_id = {
            "TL-001": SimpleNamespace(id="TL-001"),
            "TL-002": SimpleNamespace(id="TL-002"),
        }

    def topo_order(self, ids):
        return ids


@pytest.fixture()
def executor_mocks(monkeypatch, tmp_path):
    """mock 运行时装配与工作区，让 execute_plan 纯离线跑通。"""
    (tmp_path / "scenarios").mkdir()  # execute_plan 前置检查：场景库目录必须存在
    ws_info = SimpleNamespace(root=tmp_path, system="tdm")

    def fake_setup(system, env, scenarios_root, strict_deps=False):
        return ({"env_name": "sit"}, None, None, None, FakeGraph(), {})
    monkeypatch.setattr(pe, "_setup_runtime", fake_setup)

    import services.plan_store as plan_store
    from specstd import workspace as wsm
    monkeypatch.setattr(plan_store, "get_plan", lambda pid: {
        "name": "回归计划", "env": "sit", "resolved_scenarios": ["TL-001", "TL-002"]})
    monkeypatch.setattr(wsm, "get_workspace", lambda name: ws_info)
    monkeypatch.setattr(wsm, "get_active_workspace", lambda: ws_info)
    monkeypatch.setattr(wsm, "set_context_workspace", lambda name: None)
    monkeypatch.setattr(wsm, "reports_dir", lambda: tmp_path)

    # run_single：TL-001 PASS、TL-002 FAIL
    records = {
        "TL-001": ExecutionRecord(scenario_id="TL-001", title="通过场景",
                                  verdict="PASS", duration_ms=5),
        "TL-002": ExecutionRecord(scenario_id="TL-002", title="失败场景",
                                  verdict="FAIL", duration_ms=6,
                                  failure={"category": "assert_failed", "message": "boo"}),
    }
    monkeypatch.setattr(pe, "run_single", lambda sc, rctx: records[sc.id])
    monkeypatch.setattr(pe, "run_teardowns", lambda rctx: None)
    monkeypatch.setattr(pe, "_notify_failure", _async_noop)
    monkeypatch.setattr(pe, "_notify_success", _async_noop)
    return tmp_path


async def _async_noop(*a, **k):
    pass


class TestExecutorUnifiedArtifacts:
    def test_ex_run_id_and_plan_dir(self, executor_mocks, monkeypatch):
        """T-116：EX- 任务号 + reports/{plan_id}/{run_id}/ 目录。"""
        import services.failure_index as failure_index
        calls = []
        monkeypatch.setattr(failure_index, "append_failures",
                            lambda root, run_id: calls.append((root, run_id)) or 1)
        import services.execution_index as execution_index
        ecalls = []
        monkeypatch.setattr(execution_index, "append_executions",
                            lambda root, run_id: ecalls.append((root, run_id)) or 2)

        result = asyncio.run(pe.execute_plan("p1", workspace="ws1", triggered_by="schedule"))
        assert result["status"] == "failed"
        run_id = result["run_id"]
        assert run_id.startswith("EX-"), f"run_id 应为 EX- 格式: {run_id}"
        report_dir = Path(result["report_dir"])
        assert report_dir.name == run_id
        assert report_dir.parent.name == "p1", "报告目录应有 plan 前缀（历史页可读）"
        assert (report_dir / "output.log").is_file()
        assert (report_dir / "trigger.json").is_file()
        assert calls, "失败索引必须被调用（此前引擎直跑不进失败台账）"
        root, idx_run = calls[0]
        assert str(idx_run) == f"p1/{run_id}"
        assert ecalls, "执行索引必须被调用（全量结果台账）"
        assert str(ecalls[0][1]) == f"p1/{run_id}"

    def test_output_log_has_verdicts(self, executor_mocks):
        """T-116：output.log 含每场景 verdict 行（排障按任务号取日志）。"""
        result = asyncio.run(pe.execute_plan("p1", workspace="ws1"))
        log = (Path(result["report_dir"]) / "output.log").read_text(encoding="utf-8")
        assert "[PASS] TL-001" in log
        assert "[FAIL] TL-002" in log

    def test_trigger_json_context(self, executor_mocks):
        """T-116：trigger.json 含触发上下文（计划/环境/触发来源/场景清单）。"""
        result = asyncio.run(pe.execute_plan("p1", workspace="ws1", triggered_by="schedule"))
        import json
        ctx = json.loads((Path(result["report_dir"]) / "trigger.json").read_text(encoding="utf-8"))
        assert ctx["plan_id"] == "p1"
        assert ctx["triggered_by"] == "schedule"
        assert ctx["scenario_ids"] == ["TL-001", "TL-002"]
