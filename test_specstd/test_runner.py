"""RunManager 断点/abort 生命周期测试（T-111 死锁 + T-112 短路与状态修正）。

T-111：断点暂停中 abort 只 terminate 进程，不置位 _resume_event →
_run_batches 永久卡在 wait()，_finish_current_run 永不执行 → 队表项永远 running。
T-112：批次执行中 abort 后 drain 返回仍继续跑下一批；_stream_output 非零退出
恒置 completed（双分支相同，应为 failed/aborted）。
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import runner as runner_mod  # noqa: E402


class FakeProc:
    """伪 pytest 子进程：stdout 可迭代（立即 EOF），returncode 可配。"""

    def __init__(self, returncode: int = 0, lines=()):
        self.stdout = list(lines)
        self.returncode = returncode
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture()
def mgr(monkeypatch, tmp_path):
    """隔离 RunManager：报告目录指向 tmp_path，spawn 返回假进程。"""
    monkeypatch.setattr(runner_mod, "_get_reports_root", lambda: tmp_path)
    m = runner_mod.RunManager()
    spawns: list = []
    spawn_args: list = []

    def fake_spawn(cmd, env, run_id="", account_override="", overrides=None):
        spawns.append(run_id)
        spawn_args.append({"run_id": run_id, "account_override": account_override,
                           "overrides": overrides})
        return FakeProc()

    monkeypatch.setattr(runner_mod, "_spawn_pytest", fake_spawn)
    m._spawns = spawns
    m._spawn_args = spawn_args
    return m


def _mk_breakpoints_run(m, scenario_ids, breakpoints):
    """构造断点运行所需状态（run_id/报告目录/断点/待执行清单）。"""
    m.run_id = "EX-test0001"
    m._run_dir = Path(runner_mod._get_reports_root()) / m.run_id
    m._run_dir.mkdir(parents=True, exist_ok=True)
    m.breakpoints = breakpoints
    m.pending_scenarios = list(scenario_ids)
    m.completed_scenarios = []
    m._strict_deps = False
    m.current_emp_no = ""
    m.current_workspace = ""


async def _wait_paused(m, timeout=3.0):
    """轮询直到暂停（断点 hit）。"""
    for _ in range(int(timeout * 100)):
        if m.is_paused:
            return True
        await asyncio.sleep(0.01)
    return False


class TestAbortDuringPause:
    def test_abort_sets_resume_event_when_paused(self, mgr):
        """T-111：暂停中 abort 必须置位 _resume_event（否则 _run_batches 永卡）。"""
        mgr.status = "paused"
        mgr.run_id = "EX-test0001"
        mgr._resume_event = asyncio.Event()
        mgr.process = FakeProc()

        async def run():
            return await mgr.abort()

        result = asyncio.run(run())
        assert result["ok"] is True
        assert mgr._resume_event.is_set()
        assert mgr.status == "aborted"

    def test_abort_at_pause_finishes_queue(self, mgr, monkeypatch):
        """T-111：断点暂停中 abort → _run_batches 醒来走收尾（队表结束），不死锁。"""
        _mk_breakpoints_run(mgr, ["A", "B"], ["B"])
        finished: list = []

        async def fake_finish(status="done"):
            finished.append(status)

        monkeypatch.setattr(mgr, "_finish_current_run", fake_finish)

        async def run():
            task = asyncio.create_task(mgr._run_batches([["A"], ["B"]], "sit"))
            assert await _wait_paused(mgr), "应在断点 B 前暂停"
            await mgr.abort()
            await asyncio.wait_for(task, timeout=3.0)  # 不死锁即可通过

        asyncio.run(run())
        assert finished, "abort 后必须执行队列收尾（此前队表永远 running）"
        assert mgr.status == "aborted"


class TestMidBatchAbort:
    def test_mid_batch_abort_stops_next_batch(self, mgr, monkeypatch):
        """T-112：批次执行中被 abort → drain 后短路，不再跑下一批。"""
        _mk_breakpoints_run(mgr, ["A", "B"], [])
        finished: list = []

        async def fake_finish(status="done"):
            finished.append(status)

        monkeypatch.setattr(mgr, "_finish_current_run", fake_finish)
        # 模拟第一批 drain 期间收到 abort（真实场景：用户点终止）
        original_drain = runner_mod.RunManager._drain_output

        async def fake_drain(self, proc):
            await original_drain(self, proc)
            self.status = "aborted"

        monkeypatch.setattr(runner_mod.RunManager, "_drain_output", fake_drain)

        async def run():
            await mgr._run_batches([["A"], ["B"]], "sit")

        asyncio.run(run())
        assert len(mgr._spawns) == 1, f"abort 后不应再执行下一批（实际 spawn {len(mgr._spawns)} 次）"
        assert finished


class BlockingProc(FakeProc):
    """stdout 永不产出数据（模拟进程挂死）——读线程永久阻塞。"""

    def __init__(self):
        super().__init__(returncode=0)
        self.terminated = False

        class _BlockingIter:
            def __iter__(self):
                return self

            def __next__(self):
                time.sleep(3600)  # 永不返回（daemon 线程，测试结束即释放）
                raise StopIteration

        self.stdout = _BlockingIter()


class TestWatchdog:
    """T-118：run 级超时看门狗——进程挂死时自动终止并标 timeout（不再永久占用队列）。"""

    def test_drain_times_out_and_marks_timeout(self, mgr, monkeypatch, tmp_path):
        import time as _time
        mgr.run_id = "EX-watch001"
        mgr._run_dir = tmp_path
        mgr._run_timeout = 0.1
        mgr._started_monotonic = _time.monotonic()
        mgr.status = "running"
        mgr._scope = ""
        proc = BlockingProc()
        mgr.process = proc
        broadcasted = []
        monkeypatch.setattr(mgr, "broadcast", _recorder(broadcasted))

        asyncio.run(mgr._drain_output(proc))
        assert mgr.status == "timeout", "超时必须标记 timeout"
        assert proc.terminated, "超时必须终止进程"
        types = [c[0]["type"] for c in broadcasted]
        assert "finished" in types

    def test_stream_output_keeps_timeout(self, mgr, monkeypatch):
        """收尾不覆盖 timeout 终态。"""
        mgr.status = "timeout"
        mgr.run_id = "EX-watch001"
        mgr.process = FakeProc(returncode=1)
        _stub_finish(mgr, monkeypatch)
        asyncio.run(mgr._stream_output())
        assert mgr.status == "timeout"


class TestBatchNotifications:
    """T-113：断点批次 case 在 {run_id}-bN 目录，通知必须一并扫描（此前只扫主目录）。"""

    def test_batch_cases_are_notified(self, mgr, monkeypatch, tmp_path):
        import json

        mgr.run_id = "EX-batch001"
        mgr._scope = ""
        root = tmp_path
        # 主目录一个 FAIL + 批次目录一个 FAIL（断点场景）
        for sub in ("EX-batch001", "EX-batch001-b0"):
            d = root / sub / "cases"
            d.mkdir(parents=True)
            (d / "TL-001.json").write_text(json.dumps(
                {"scenario_id": "TL-001", "verdict": "FAIL", "failure": {"category": "CAT_ASSERT"}}),
                encoding="utf-8")

        calls: list = []

        class FakeRegistry:
            def __init__(self, path):
                pass

            def list(self):
                return [{"id": 1}]

            def send_notification(self, *a):
                calls.append(a)

        import feedback.notify as notify_mod
        monkeypatch.setattr(notify_mod, "NotifyRegistry", FakeRegistry)

        asyncio.run(mgr._push_run_notifications())
        # 主目录 + 批次目录各一条，链接指向各自报告目录
        assert len(calls) == 2
        links = {c[-1] for c in calls}
        assert "reports/EX-batch001/report.md" in links
        assert "reports/EX-batch001-b0/report.md" in links


class TestLogHeaderContext:
    """T-310：日志头行带触发上下文（触发人/账号/工作区/选中场景）。

    EX-fc04ec0c 类日志头行只有「> EX-xxx | env=sit | pytest 命令」——
    看不出是谁触发、用的什么账号、选了哪些场景，排错要先翻 trigger.json。
    """

    def test_log_header_includes_trigger_context(self, mgr, monkeypatch, tmp_path):
        from services import user_store
        monkeypatch.setattr(user_store, "enqueue_run", lambda *a, **k: 1)
        monkeypatch.setattr(user_store, "audit", lambda *a, **k: None)
        monkeypatch.setattr(user_store, "update_run_queue", lambda *a, **k: True)
        monkeypatch.setattr(mgr, "broadcast", _recorder([]))
        monkeypatch.setattr(mgr, "_record_failures", lambda: None)
        monkeypatch.setattr(mgr, "_record_executions", lambda: None)

        async def _noop(*a, **k):
            pass

        monkeypatch.setattr(mgr, "_push_run_notifications", _noop)
        monkeypatch.setattr(mgr, "_finish_current_run", _noop)

        async def run():
            return await mgr.trigger(scope="scenario", target="EV-IMP-001",
                                     env="sit", emp_no="90024166", workspace="tdm",
                                     account_override="ad2")

        result = asyncio.run(run())
        log_path = tmp_path / result["run_id"] / "output.log"
        assert log_path.is_file()
        head = log_path.read_text(encoding="utf-8").splitlines()[0]
        assert "EV-IMP-001" in head, "头行应含选中场景"
        assert "90024166" in head, "头行应含触发人工号"
        assert "ad2" in head, "头行应含执行账号"
        assert "tdm" in head, "头行应含工作区"


class TestVariableOverrides:
    """T-312：确认弹窗变量覆盖（输入值）→ SG_OVERRIDES 注入子进程。"""

    def _stub(self, m, monkeypatch):
        from services import user_store
        monkeypatch.setattr(user_store, "enqueue_run", lambda *a, **k: 1)
        monkeypatch.setattr(user_store, "audit", lambda *a, **k: None)
        monkeypatch.setattr(user_store, "update_run_queue", lambda *a, **k: True)
        monkeypatch.setattr(m, "broadcast", _recorder([]))
        monkeypatch.setattr(m, "_record_failures", lambda: None)
        monkeypatch.setattr(m, "_record_executions", lambda: None)

        async def _noop(*a, **k):
            pass

        monkeypatch.setattr(m, "_push_run_notifications", _noop)
        monkeypatch.setattr(m, "_finish_current_run", _noop)

    def test_overrides_forwarded_to_spawn(self, mgr, monkeypatch):
        """trigger(overrides=[...]) → _spawn_pytest 收到同一份 overrides。"""
        self._stub(mgr, monkeypatch)
        ov = [{"kind": "account", "name": "platformNoCorp", "value": "caiyunfei"}]

        async def run():
            return await mgr.trigger(scope="scenario", target="TL-RC-014",
                                     env="sit", emp_no="u1", workspace="ws1",
                                     overrides=ov)

        result = asyncio.run(run())
        assert result["ok"] is True
        assert mgr._spawn_args[-1]["overrides"] == ov, "spawn 应收到覆盖值"

    def test_log_header_counts_overrides(self, mgr, monkeypatch, tmp_path):
        """T-310 头行追加「覆盖=N项」——日志可看出本次有变量覆盖。"""
        self._stub(mgr, monkeypatch)

        async def run():
            return await mgr.trigger(scope="scenario", target="TL-RC-014",
                                     env="sit", emp_no="u1", workspace="ws1",
                                     overrides=[{"kind": "account", "name": "x", "value": "y"}])

        result = asyncio.run(run())
        head = (tmp_path / result["run_id"] / "output.log").read_text(encoding="utf-8").splitlines()[0]
        assert "覆盖=1项" in head

    def test_no_overrides_no_env_flag(self, mgr, monkeypatch):
        """未填输入值时不给 spawn 传覆盖（SG_OVERRIDES 不注入）。"""
        self._stub(mgr, monkeypatch)

        async def run():
            return await mgr.trigger(scope="scenario", target="TL-RC-014",
                                     env="sit", emp_no="u1", workspace="ws1")

        asyncio.run(run())
        assert mgr._spawn_args[-1]["overrides"] is None


class TestSpawnFailureBroadcast:
    """T-115：spawn 失败必须补发终态（此前 started 先广播，前端永久卡「执行中」）。"""

    def test_spawn_failure_sends_finished(self, mgr, monkeypatch, tmp_path):
        from services import user_store

        calls: list = []
        monkeypatch.setattr(mgr, "broadcast", _recorder(calls))
        monkeypatch.setattr(user_store, "enqueue_run", lambda *a, **k: 1)
        monkeypatch.setattr(user_store, "audit", lambda *a, **k: None)
        monkeypatch.setattr(user_store, "update_run_queue", lambda *a, **k: True)

        def boom(*a, **k):
            raise RuntimeError("spawn exploded")

        monkeypatch.setattr(runner_mod, "_spawn_pytest", boom)

        async def run():
            return await mgr.trigger(scope="all", env="sit", emp_no="u1", workspace="ws1")

        result = asyncio.run(run())
        assert result["ok"] is False
        types = [c[0]["type"] for c in calls]
        assert "started" not in types, "spawn 失败前不得广播 started"
        finished = [c[0] for c in calls if c[0]["type"] == "finished"]
        assert finished and finished[0]["status"] == "failed"
        assert "spawn exploded" in finished[0]["error"]


def _stub_finish(m, monkeypatch):
    """屏蔽收尾副作用：_record_failures 同步、其余异步（供终态类测试共用）。"""
    monkeypatch.setattr(m, "_record_failures", lambda: None)
    monkeypatch.setattr(m, "_record_executions", lambda: None)

    async def _noop(*a, **k):
        pass

    monkeypatch.setattr(m, "_push_run_notifications", _noop)
    monkeypatch.setattr(m, "_finish_current_run", _noop)


def _recorder(calls: list):
    """广播记录器：把消息放进 calls（便于断言消息序列）。"""

    async def record(msg):
        calls.append((msg,))

    return record


class TestStreamOutputStatus:
    def test_nonzero_returncode_marks_failed(self, mgr, monkeypatch):
        """T-112：pytest 非零退出 → status=failed（此前两分支相同恒为 completed）。"""
        mgr.status = "running"
        mgr.run_id = "EX-test0001"
        mgr.process = FakeProc(returncode=1)
        _stub_finish(mgr, monkeypatch)

        asyncio.run(mgr._stream_output())
        assert mgr.status == "failed"

    def test_aborted_keeps_aborted(self, mgr, monkeypatch):
        """T-112：abort 过的执行收尾时保持 aborted，不被 completed 覆盖。"""
        mgr.status = "aborted"
        mgr.run_id = "EX-test0001"
        mgr.process = FakeProc(returncode=0)
        _stub_finish(mgr, monkeypatch)

        asyncio.run(mgr._stream_output())
        assert mgr.status == "aborted"


class TestParseLine:
    """T-303：pytest 输出行解析（verdict + 参数化场景 ID 正则提取）。"""

    def _parse(self, line):
        return runner_mod.RunManager()._parse_line(line)

    def test_standard_param_id(self):
        ev = self._parse(r"test_suites\test_scenarios.py::test_scenario[PP-RC-001] PASSED")
        assert ev == {"verdict": "PASSED", "scenario_id": "PP-RC-001"}

    def test_error_verdict(self):
        ev = self._parse("test_scenarios.py::test_scenario[TL-001] ERROR")
        assert ev["verdict"] == "ERROR"
        assert ev["scenario_id"] == "TL-001"

    def test_extra_brackets_no_misparse(self):
        """行内含进度/其他方括号段时不误取（原 split 实现会取到 "[ 50%]"）。"""
        ev = self._parse("[PP-RC-001] PASSED [ 50%]")
        assert ev["scenario_id"] == "PP-RC-001", ev

    def test_non_param_line_no_id(self):
        """非参数化行（engine_modes 测试）verdict 有值但场景 ID 为空。"""
        ev = self._parse("test_engine_modes.py::test_shared PASSED")
        assert ev["verdict"] == "PASSED"
        assert ev["scenario_id"] == ""

    def test_plain_output_no_verdict(self):
        assert self._parse("[SpecGuard] POST /api/x -> 200") == {}

    def test_specguard_anchor_with_verdict_words_ignored(self):
        """T-314：引擎锚点行不得参与 verdict 解析——body 摘要可能含 FAILED/ERROR 词。"""
        ev = self._parse("[SpecGuard] POST /api/system/tags → 500 | 12ms | "
                         'body={"message": "VALIDATION FAILED"} | trace=t-1')
        assert ev == {}, f"锚点行不应误判 verdict: {ev}"
        ev2 = self._parse("[SpecGuard] 断言 errResp.status == 400 → ❌FAIL | 实际状态 500 ≠ 预期 400")
        assert ev2 == {}
