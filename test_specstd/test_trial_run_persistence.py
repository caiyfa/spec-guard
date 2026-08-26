"""试跑（trial-run）链路回归测试（2026-08-26 排障修复）。

背景：HTTP 试跑端点把同步 MCP handler 包进 asyncio.run() → 必抛 TypeError
（"a coroutine was expected, got list"）→ 前端恒收 500 Internal Server Error；
且试跑 in-process 路径不落 run.json/cases、不写 failures/executions 索引、
无 output.log——Agent 排障工具链（attribution）对试跑失败完全失明。

本文件锁死修复后契约：
A. routers/drafts.trial_run_draft 端点：
   - 同步 handler 正常返回 → 端点返回结果 dict（不再抛 TypeError/500）
   - handler 抛异常 → 结构化 {ok: False, error}（不再裸 500）
B. scenario_tools._handle_run_scenario 试跑落盘：
   - 响应带 run_id（EX- 任务号，同 runner/plan_executor）
   - run.json / cases/*.json / report.md / output.log 落盘
   - failures/index.jsonl + executions/index.jsonl 收录本次试跑
C. 早期失败任务号（2026-08-26 HI-PERM-001 事故后续）：
   - 草稿解析失败 / 装配失败 / 执行异常等任何失败都带 EX- 任务号
   - 失败统一落 output.log 现场 + 最小 run.json（单 ERROR case）+ 双索引
   - Agent attribution(log) 对早期失败可读（排障不瞎）
"""

import asyncio
import json
from pathlib import Path

import pytest

import specstd.workspace as wsm
from specstd.workspace import drafts_dir, register_local, unregister
from test_specstd.helpers import create_valid_workspace


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path, monkeypatch):
    """台账投影隔离到 tmp 库——试跑落索引时不得污染真实 workbench.db。"""
    from sg_core import ledger_store
    monkeypatch.setattr(ledger_store, "DB_PATH", tmp_path / "ledger.db")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """隔离注册表 + 激活合规工作区（不落真实 registry.yaml），返回工作区根。"""
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    ws_path = create_valid_workspace(tmp_path / "ws")
    register_local("test-trial", str(ws_path), "tdm", activate=True)
    yield ws_path
    unregister("test-trial")


def _write_draft(name="TT-TRIAL-001.yaml", sid="TT-TRIAL-001") -> Path:
    d = drafts_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(
        f'id: {sid}\ntitle: 试跑落盘回归\nversion: "0.1"\n'
        "flow:\n  - set_var: {k1: v1}\n",
        encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════
# A. HTTP 试跑端点（路由函数直调，mock 掉真实执行的 MCP handler）
# ══════════════════════════════════════════════════════════

class TestTrialRunEndpoint:
    def _call_endpoint(self, monkeypatch, handler, filename="TT-TRIAL-001.yaml"):
        """设置 emp 上下文 + mock handler/audit，直调路由函数。

        注意 drafts_dir() 是 emp 私有区（{.specguard}/{emp}/drafts/）——草稿必须
        在 emp 上下文内写入，否则端点按私有区解析会 404。
        """
        from mcp_server.tools import scenario_tools
        from sg_core import user_store
        monkeypatch.setattr(scenario_tools, "_handle_run_scenario", handler)
        monkeypatch.setattr(user_store, "audit", lambda *a, **k: None)
        from routers import drafts as drafts_router
        tok = wsm.set_context_emp_no("E10001")
        try:
            _write_draft()
            return asyncio.run(drafts_router.trial_run_draft(filename))
        finally:
            wsm.reset_context_emp_no(tok)

    def test_sync_handler_result_reaches_frontend(self, workspace, monkeypatch):
        """同步 handler 正常返回时，端点必须返回结果 dict（原 bug：asyncio.run
        包同步函数必抛 TypeError → 500 Internal Server Error）。"""
        from mcp.types import TextContent

        def fake_handler(arguments):
            return [TextContent(type="text", text=json.dumps(
                {"ok": True, "verdict": "PASS", "run_id": "agent_x"}, ensure_ascii=False))]

        result = self._call_endpoint(monkeypatch, fake_handler)
        assert result["ok"] is True
        assert result["verdict"] == "PASS"

    def test_handler_exception_returns_structured_error(self, workspace, monkeypatch):
        """handler 抛异常时返回结构化错误 JSON（原行为：未捕获 → Starlette 裸 500，
        前端只有 'Internal Server Error' 六个单词，无任何异常信息）。"""

        def boom_handler(arguments):
            raise RuntimeError("boom-装配失败")

        result = self._call_endpoint(monkeypatch, boom_handler)
        assert result["ok"] is False
        assert "boom-装配失败" in result["error"]


# ══════════════════════════════════════════════════════════
# B. 试跑落盘（mock 运行时装配与 run_single，验证报告/索引/run_id 契约）
# ══════════════════════════════════════════════════════════

class TestTrialRunPersistence:
    def _run(self, workspace, monkeypatch):
        """mock _setup_runtime / run_single / run_teardowns 后执行试跑 handler。"""
        import workbench.backend.services.plan_executor as plan_executor
        from engine.dependency_graph import DependencyGraph
        from engine.execution_record import ExecutionRecord
        from engine import scenario_runner
        from mcp_server.tools import scenario_tools

        _write_draft()
        fake_env = {"env_name": "sit"}

        monkeypatch.setattr(
            plan_executor, "_setup_runtime",
            lambda *a, **k: (fake_env, None, object(), None, DependencyGraph([]), {}))

        def fake_run_single(scenario, rctx):
            # 模拟真实执行的调用链日志（output.log 捕获断言依赖此行）
            print("[SpecGuard] GET /api/fake → 200 | trace=fake-trace-1")
            rec = ExecutionRecord(
                scenario_id=scenario.id, title=scenario.title, verdict="FAIL",
                failure={"category": "assert_failed",
                         "message": "expected 1 got 2", "evidence": None},
                duration_ms=5)
            rctx.records.append(rec)
            return rec

        monkeypatch.setattr(scenario_runner, "run_single", fake_run_single)
        monkeypatch.setattr(scenario_runner, "run_teardowns", lambda rctx: None)

        out = scenario_tools._handle_run_scenario({"draft": "TT-TRIAL-001.yaml"})
        return json.loads(out[0].text)

    def test_response_carries_run_id(self, workspace, monkeypatch):
        """响应必须带 run_id（前端展示 + 用户甩给 Agent 排查的唯一线索）。"""
        result = self._run(workspace, monkeypatch)
        assert result["ok"] is False  # FAIL  verdict
        assert result["run_id"].startswith("EX-"), (
            f"试跑任务号应与 runner/plan_executor 同格式（EX- 前缀），实际: {result['run_id']}")

    def test_report_files_persisted(self, workspace, monkeypatch):
        """run.json / cases / report.md / output.log 全部落盘（原行为：空目录）。"""
        result = self._run(workspace, monkeypatch)
        run_dir = Path(result["report_dir"])
        run_json = run_dir / "run.json"
        assert run_json.is_file(), "run.json 未落盘"
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
        assert run_data["stats"]["fail"] == 1
        assert (run_dir / "cases" / "TT-TRIAL-001.json").is_file()
        assert (run_dir / "report.md").is_file()
        log = run_dir / "output.log"
        assert log.is_file(), "output.log 未落盘"
        assert "fake-trace-1" in log.read_text(encoding="utf-8")

    def test_failures_and_executions_indexed(self, workspace, monkeypatch):
        """试跑结果进 failures/executions 索引（attribution 工具链的发现入口）。"""
        result = self._run(workspace, monkeypatch)
        reports_root = Path(result["report_dir"]).parent

        failures = (reports_root / "failures" / "index.jsonl").read_text(encoding="utf-8")
        assert result["run_id"] in failures
        assert "TT-TRIAL-001" in failures

        executions = (reports_root / "executions" / "index.jsonl").read_text(encoding="utf-8")
        assert result["run_id"] in executions

    def test_report_shared_readable_under_emp_context(self, workspace, monkeypatch):
        """T-1016 回归：emp 上下文下试跑报告必须落共享区 .specguard/reports/。

        原 bug（2026-08-26 HI-PERM-001 三连败事故的隐形推手）：run_dir 用
        specguard_dir(workspace_root=ws.root)（无 force_shared），emp 上下文下落到
        私有区 {emp}/reports/；而 attribution(action=report/log/case) 与
        failures/executions 索引统一经 reports_dir() 读共享区 → 读写错位，
        Agent 排障工具链对自己的试跑完全失明（"运行报告不存在"）。
        """
        from specstd.workspace import reports_dir
        tok = wsm.set_context_emp_no("E10001")
        try:
            result = self._run(workspace, monkeypatch)
        finally:
            wsm.reset_context_emp_no(tok)
        shared = reports_dir()
        run_dir = Path(result["report_dir"])
        assert run_dir.parent == shared, (
            f"试跑报告应落共享区 {shared}，实际落在 {run_dir.parent}")
        # 不停留在路径相等——以 attribution 读者视角实证可读
        from mcp_server.tools.attribution import _handle_read_report
        out = _handle_read_report({"run_id": result["run_id"]})
        assert "运行报告不存在" not in out[0].text


# ══════════════════════════════════════════════════════════
# C. 早期失败任务号（目标确定后一切失败都有任务号 + 报告现场）
# ══════════════════════════════════════════════════════════

class TestEarlyFailurePersistence:
    """早期失败（原 run_id 生成点之前的异常）也必须有任务号 + 落盘 + 索引。

    背景：草稿解析失败（如 version 非法）、运行时装配失败、执行异常等分支
    原先只返回错误文本——无任务号、无报告，Agent attribution 工具链完全
    失明（会话 20260825_151821_3178914e LINE 166：'0.4-debug' 解析失败无任务号）。
    """

    def _write_bad_draft(self, name="TT-BAD-001.yaml", sid="TT-BAD-001") -> None:
        """version 非法的坏草稿（解析必败，复现 LINE 166 事故形态）。"""
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(
            f'id: {sid}\ntitle: 坏草稿\nversion: "0.4-debug"\n'
            "flow:\n  - set_var: {k1: v1}\n", encoding="utf-8")

    def _mock_runtime_ok(self, monkeypatch) -> None:
        import workbench.backend.services.plan_executor as plan_executor
        from engine.dependency_graph import DependencyGraph
        monkeypatch.setattr(
            plan_executor, "_setup_runtime",
            lambda *a, **k: ({"env_name": "sit"}, None, object(), None,
                             DependencyGraph([]), {}))

    def _assert_failure_report(self, result: dict, needle: str,
                               scenario_ref: str) -> Path:
        """失败五件套断言：EX- 任务号 + 落盘 + ERROR case + 双索引 + agent 可读。"""
        assert result["ok"] is False
        assert result["run_id"].startswith("EX-"), (
            f"失败任务号应为 EX- 前缀，实际: {result.get('run_id')}")
        assert needle in result["error"]
        run_dir = Path(result["report_dir"])
        log = (run_dir / "output.log").read_text(encoding="utf-8")
        assert needle in log, "output.log 未含错误现场"
        run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        error_cases = [c for c in run_data["cases"] if c["verdict"] == "ERROR"]
        assert error_cases, "run.json 应含 ERROR case（否则 list_failures 查不到）"
        assert error_cases[0]["id"] == scenario_ref
        reports_root = run_dir.parent
        failures = (reports_root / "failures" / "index.jsonl").read_text(encoding="utf-8")
        assert result["run_id"] in failures, "失败未进 failures 索引"
        assert scenario_ref in failures
        executions = (reports_root / "executions" / "index.jsonl").read_text(encoding="utf-8")
        assert result["run_id"] in executions, "失败未进 executions 索引"
        # Agent 排障视角实证：read_run_log 可读
        from mcp_server.tools.attribution import _handle_read_run_log
        out = _handle_read_run_log({"run_id": result["run_id"]})
        assert "执行日志不存在" not in out[0].text
        return run_dir

    def test_draft_parse_failure_carries_ex_run_id(self, workspace, monkeypatch):
        """草稿解析失败（version 非法）→ EX- 任务号 + 落盘 + 索引。"""
        from mcp_server.tools import scenario_tools
        self._mock_runtime_ok(monkeypatch)
        _write_draft()
        self._write_bad_draft()
        out = scenario_tools._handle_run_scenario({"draft": "TT-BAD-001.yaml"})
        self._assert_failure_report(json.loads(out[0].text), "0.4-debug", "TT-BAD-001")

    def test_runtime_setup_failure_carries_ex_run_id(self, workspace, monkeypatch):
        """运行时装配失败（环境不可达/配置错）→ EX- 任务号 + 落盘 + 索引。"""
        import workbench.backend.services.plan_executor as plan_executor
        from mcp_server.tools import scenario_tools

        def boom(*a, **k):
            raise RuntimeError("SIT 网关不可达")

        monkeypatch.setattr(plan_executor, "_setup_runtime", boom)
        _write_draft()
        out = scenario_tools._handle_run_scenario({"draft": "TT-TRIAL-001.yaml"})
        self._assert_failure_report(json.loads(out[0].text), "SIT 网关不可达", "TT-TRIAL-001")

    def test_execution_exception_enters_failure_index(self, workspace, monkeypatch):
        """执行异常（rctx.records 空）→ 最小 ERROR case 进失败索引。"""
        from engine import scenario_runner
        from mcp_server.tools import scenario_tools
        self._mock_runtime_ok(monkeypatch)

        def boom(scenario, rctx):
            raise RuntimeError("引擎爆炸")

        monkeypatch.setattr(scenario_runner, "run_single", boom)
        monkeypatch.setattr(scenario_runner, "run_teardowns", lambda rctx: None)
        _write_draft()
        out = scenario_tools._handle_run_scenario({"draft": "TT-TRIAL-001.yaml"})
        self._assert_failure_report(json.loads(out[0].text), "引擎爆炸", "TT-TRIAL-001")
