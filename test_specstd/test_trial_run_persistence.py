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
   - 响应带 run_id（agent_ 前缀）
   - run.json / cases/*.json / report.md / output.log 落盘
   - failures/index.jsonl + executions/index.jsonl 收录本次试跑
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
        assert result["run_id"].startswith("agent_")

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
