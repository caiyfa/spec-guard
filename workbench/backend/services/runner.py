"""执行控制服务：subprocess 管理 + WebSocket 实时广播。

包装 `python -m pytest` 命令，流式读取输出并广播给前端。
不修改引擎代码。
"""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import WebSocket

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 仓库根


class RunManager:
    """管理单次 pytest 执行的生命周期 + WebSocket 广播 + 断点暂停/恢复"""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.run_id: Optional[str] = None
        self.plan_id: str = ""
        self.status: str = "idle"  # idle / running / paused / completed / aborted
        self.started_at: Optional[str] = None
        self.subscribers: list[WebSocket] = []
        self._output_lines: list[str] = []
        # 多用户队列（M8）：当前执行的归属与持久化队列项
        self.current_emp_no: str = ""
        self.current_workspace: str = ""
        self._queue_id: Optional[int] = None
        self._scope: str = ""
        # 断点状态
        self.breakpoints: list[str] = []          # 断点场景 ID 列表
        self.pending_scenarios: list[str] = []    # 待执行场景（断点分段用）
        self.completed_scenarios: list[str] = []  # 已完成场景
        self.current_batch: list[str] = []        # 当前批次场景
        self.paused_at: str = ""                  # 暂停在哪个场景前
        self._resume_event: Optional[asyncio.Event] = None

    @property
    def is_running(self) -> bool:
        return self.status in ("running", "paused")

    @property
    def is_paused(self) -> bool:
        return self.status == "paused"

    async def subscribe(self, ws: WebSocket):
        await ws.accept()
        self.subscribers.append(ws)
        # 发送当前状态
        await ws.send_json({"type": "status", "status": self.status, "run_id": self.run_id})
        # 回放已有输出
        for line in self._output_lines[-100:]:
            await ws.send_json({"type": "output", "line": line})

    def unsubscribe(self, ws: WebSocket):
        self.subscribers = [s for s in self.subscribers if s is not ws]

    async def broadcast(self, msg: dict):
        dead = []
        for ws in self.subscribers:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subscribers.remove(ws)

    async def trigger(self, scope: str = "all", target: str = "", env: str = "sit",
                      plan_id: str = "", strict_deps: bool = False,
                      emp_no: str = "", workspace: str = "",
                      queue_id: Optional[int] = None) -> dict:
        """触发执行

        scope: all / module / scenario / tag / engine_modes
        target: 场景ID / 模块路径 / 标签名（scope != all 时有效）
        plan_id: 测试计划 ID（非空时报告归档到 reports/{plan_id}/）
        strict_deps: 严格依赖模式（SG_STRICT_DEPS=1 注入子进程，DRIFT/ORPHANED → BLOCKED）
        emp_no/workspace: 触发人与工作区（多用户归属，M8）
        queue_id: 来自队列的消费（内部用；为 None 时新建队表记录）

        已有执行时进入 FIFO 队列（run_queue 表持久化），返回 queued + position。
        """
        if self.is_running:
            from services import user_store
            qid = user_store.enqueue_run(
                emp_no=emp_no, scope=scope, target=target, env=env, plan_id=plan_id,
                breakpoints=[], strict_deps=strict_deps, workspace=workspace)
            user_store.audit(emp_no, "enqueue_run", scope, f"queue_id={qid}")
            queued = [r for r in user_store.list_run_queue() if r["status"] == "queued"]
            position = next((i + 1 for i, r in enumerate(queued) if r["id"] == qid), len(queued))
            await self.broadcast({"type": "queued", "queue_id": qid, "position": position,
                                  "emp_no": emp_no, "scope": scope})
            return {"ok": True, "queued": True, "queue_id": qid, "position": position}

        # 启动执行：登记队表（running）
        from services import user_store
        if queue_id:
            user_store.update_run_queue(queue_id, "running", started=True)
            self._queue_id = queue_id
        else:
            self._queue_id = user_store.enqueue_run(
                emp_no=emp_no, scope=scope, target=target, env=env, plan_id=plan_id,
                breakpoints=[], strict_deps=strict_deps, workspace=workspace, status="running")
        self.current_emp_no = emp_no
        self.current_workspace = workspace

        # 构建 pytest 命令
        cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short"]
        if scope == "scenario" and target:
            cmd += ["-k", target]
        elif scope == "tag" and target:
            cmd += ["-m", target]
        elif scope == "engine_modes":
            cmd += ["-k", "engine_modes"]
        elif scope == "module" and target:
            cmd += ["-k", target]
        # all: 不加过滤
        if strict_deps:
            cmd += ["--strict-deps"]

        self.run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.plan_id = plan_id
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.status = "running"
        self._output_lines = []
        self._scope = scope  # D2：通知推送豁免 engine_modes 用
        if queue_id is None:
            user_store.audit(emp_no, "trigger_run", scope, f"queue_id={self._queue_id}")

        await self.broadcast({
            "type": "started",
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "cmd": " ".join(cmd),
            "started_at": self.started_at,
        })

        # 启动子进程
        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(SG_ROOT),
                env={**os.environ, "SG_ENV": env},
            )
        except Exception as e:
            self.status = "idle"
            return {"ok": False, "error": f"启动失败: {e}"}

        # 后台读取输出
        asyncio.create_task(self._stream_output())

        return {"ok": True, "run_id": self.run_id}

    async def _stream_output(self):
        """逐行读取子进程输出，解析 pytest 结果并广播"""
        proc = self.process
        if not proc or not proc.stdout:
            return

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            self._output_lines.append(text)

            # 解析 pytest 输出中的场景结果
            event = self._parse_line(text)
            await self.broadcast({"type": "output", "line": text, **event})

        await proc.wait()
        self.status = "completed" if proc.returncode == 0 else "completed"
        await self.broadcast({
            "type": "finished",
            "run_id": self.run_id,
            "returncode": proc.returncode,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        self.process = None
        # D2 修复：执行完成后按注册表自动推送飞书通知（fail/drift/skip 事件）
        await self._push_run_notifications()
        # M8：收尾并消费队列下一个
        await self._finish_current_run()

    def _parse_line(self, line: str) -> dict:
        """解析 pytest 输出行，提取场景 verdict"""
        # 匹配: test_suites\test_person_profile.py::test_scenario[PP-RC-001] PASSED
        if " PASSED" in line or " FAILED" in line or " SKIPPED" in line or " ERROR" in line:
            for verdict in ("PASSED", "FAILED", "SKIPPED", "ERROR"):
                if f" {verdict}" in line:
                    # 提取场景 ID
                    scenario_id = ""
                    if "[" in line and "]" in line:
                        scenario_id = line.split("[")[-1].split("]")[0]
                    return {"verdict": verdict, "scenario_id": scenario_id}
        return {}

    async def abort(self) -> dict:
        """终止执行"""
        if not self.is_running or not self.process:
            return {"ok": False, "error": "当前无执行中的任务"}
        try:
            self.process.terminate()
            await asyncio.sleep(1)
            if self.process.returncode is None:
                self.process.kill()
        except Exception:
            pass
        self.status = "aborted"
        await self.broadcast({"type": "aborted", "run_id": self.run_id})
        return {"ok": True}

    async def trigger_with_breakpoints(self, scenario_ids: list[str], breakpoints: list[str],
                                       env: str = "sit", plan_id: str = "",
                                       strict_deps: bool = False,
                                       emp_no: str = "", workspace: str = "",
                                       queue_id: Optional[int] = None) -> dict:
        """带断点的分段执行

        将场景列表按断点切分为多个批次，逐批执行：
        - 批次间遇到断点场景时暂停，广播上下文，等待 resume 信号
        - 无断点时退化为一次性全量执行
        - 已有执行时进入 FIFO 队列（M8）
        """
        if self.is_running:
            from services import user_store
            target = " or ".join(scenario_ids)
            qid = user_store.enqueue_run(
                emp_no=emp_no, scope="breakpoint", target=target, env=env, plan_id=plan_id,
                breakpoints=breakpoints, strict_deps=strict_deps, workspace=workspace)
            user_store.audit(emp_no, "enqueue_run", "breakpoint", f"queue_id={qid}")
            queued = [r for r in user_store.list_run_queue() if r["status"] == "queued"]
            position = next((i + 1 for i, r in enumerate(queued) if r["id"] == qid), len(queued))
            await self.broadcast({"type": "queued", "queue_id": qid, "position": position,
                                  "emp_no": emp_no, "scope": "breakpoint"})
            return {"ok": True, "queued": True, "queue_id": qid, "position": position}

        from services import user_store
        if queue_id:
            user_store.update_run_queue(queue_id, "running", started=True)
            self._queue_id = queue_id
        else:
            self._queue_id = user_store.enqueue_run(
                emp_no=emp_no, scope="breakpoint", target=" or ".join(scenario_ids), env=env,
                plan_id=plan_id, breakpoints=breakpoints, strict_deps=strict_deps,
                workspace=workspace, status="running")
        self.current_emp_no = emp_no
        self.current_workspace = workspace

        self.run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.plan_id = plan_id
        self.breakpoints = breakpoints
        self.pending_scenarios = list(scenario_ids)
        self.completed_scenarios = []
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self._output_lines = []

        # 无断点 → 直接全量执行
        if not breakpoints:
            target = " or ".join(scenario_ids)
            return await self.trigger(scope="scenario", target=target, env=env, plan_id=plan_id,
                                      strict_deps=strict_deps, emp_no=emp_no, workspace=workspace,
                                      queue_id=queue_id)

        self._strict_deps = strict_deps

        # 有断点 → 分批执行
        batches = self._split_batches(scenario_ids, breakpoints)
        await self.broadcast({
            "type": "started",
            "run_id": self.run_id,
            "plan_id": plan_id,
            "breakpoints": breakpoints,
            "total_batches": len(batches),
            "started_at": self.started_at,
        })

        # 后台逐批执行
        asyncio.create_task(self._run_batches(batches, env))
        return {"ok": True, "run_id": self.run_id, "batches": len(batches)}

    def _split_batches(self, scenario_ids: list[str], breakpoints: list[str]) -> list[list[str]]:
        """按断点将场景列表切分为批次

        断点场景作为下一批次的第一个场景（在断点场景之前暂停）。
        例：[A,B,C,D,E] 断点=[C] → [[A,B],[C,D,E]]
        """
        batches = []
        current = []
        for sid in scenario_ids:
            if sid in breakpoints and current:
                batches.append(current)
                current = []
            current.append(sid)
        if current:
            batches.append(current)
        return batches

    async def _run_batches(self, batches: list[list[str]], env: str):
        """逐批执行场景，批次间遇断点暂停"""
        self.status = "running"

        for batch_idx, batch in enumerate(batches):
            # 如果当前批次的第一个场景是断点，先暂停
            first_in_batch = batch[0] if batch else ""
            if first_in_batch in self.breakpoints and batch_idx > 0:
                self.status = "paused"
                self.paused_at = first_in_batch
                self.current_batch = batch
                await self.broadcast({
                    "type": "breakpoint_hit",
                    "run_id": self.run_id,
                    "paused_at": first_in_batch,
                    "batch_index": batch_idx,
                    "total_batches": len(batches),
                    "completed": self.completed_scenarios,
                    "pending": batch + self.pending_scenarios[len(batch):],
                    "context": self._build_breakpoint_context(),
                })

                # 等待放行信号
                self._resume_event = asyncio.Event()
                await self._resume_event.wait()
                self._resume_event = None

                if self.status == "aborted":
                    return
                self.status = "running"
                self.paused_at = ""

            # 执行当前批次
            target = " or ".join(batch)
            self.current_batch = batch
            await self.broadcast({
                "type": "batch_start",
                "batch_index": batch_idx,
                "scenarios": batch,
            })

            cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short", "-k", target]
            if getattr(self, "_strict_deps", False):
                cmd += ["--strict-deps"]
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(SG_ROOT),
                    env={**os.environ, "SG_ENV": env},
                )
            except Exception as e:
                await self.broadcast({"type": "error", "message": f"批次 {batch_idx} 启动失败: {e}"})
                continue

            # 读取输出
            if self.process and self.process.stdout:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    self._output_lines.append(text)
                    event = self._parse_line(text)
                    await self.broadcast({"type": "output", "line": text, **event})

                await self.process.wait()

            self.completed_scenarios.extend(batch)
            self.pending_scenarios = [s for s in self.pending_scenarios if s not in batch]
            await self.broadcast({
                "type": "batch_done",
                "batch_index": batch_idx,
                "completed": self.completed_scenarios,
            })

        self.status = "completed"
        await self.broadcast({
            "type": "finished",
            "run_id": self.run_id,
            "completed": self.completed_scenarios,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        self.process = None
        # D2 修复：断点分段执行完成后同样自动推送通知
        await self._push_run_notifications()
        # M8：收尾并消费队列下一个
        await self._finish_current_run()

    def _build_breakpoint_context(self) -> dict:
        """构建断点处的上下文信息（供前端展示数据状态）"""
        # 读取最近输出中的 verdict 信息
        recent_verdicts = []
        for line in self._output_lines[-50:]:
            event = self._parse_line(line)
            if event.get("verdict"):
                recent_verdicts.append({
                    "scenario_id": event.get("scenario_id", ""),
                    "verdict": event["verdict"],
                })
        return {
            "completed_count": len(self.completed_scenarios),
            "completed": self.completed_scenarios,
            "recent_verdicts": recent_verdicts[-10:],
            "output_tail": self._output_lines[-20:],
        }

    async def _finish_current_run(self):
        """M8：当前执行收尾（队表标记完成）并自动启动队列下一个。"""
        from services import user_store
        if self._queue_id:
            user_store.update_run_queue(self._queue_id, "done", finished=True)
        self._queue_id = None
        self.current_emp_no = ""
        self.current_workspace = ""
        await self._start_next_from_queue()

    async def _start_next_from_queue(self):
        """M8：取队列最老 queued 项启动（FIFO）。"""
        from services import user_store
        queued = [r for r in user_store.list_run_queue() if r["status"] == "queued"]
        if not queued:
            return
        row = queued[0]
        import json as _json
        try:
            breakpoints = _json.loads(row.get("breakpoints") or "[]")
        except Exception:
            breakpoints = []
        # 队列执行的上下文（原请求上下文已结束，用存储的工作区重建）
        from specstd.workspace import set_context_workspace
        set_context_workspace(row.get("workspace") or None)
        await self.broadcast({"type": "queue_dequeued", "queue_id": row["id"],
                              "emp_no": row["emp_no"], "scope": row["scope"]})
        if breakpoints:
            scenario_ids = row["target"].split(" or ") if row["target"] else []
            await self.trigger_with_breakpoints(
                scenario_ids=scenario_ids, breakpoints=breakpoints,
                env=row["env"], plan_id=row["plan_id"],
                strict_deps=bool(row["strict_deps"]), emp_no=row["emp_no"],
                workspace=row.get("workspace", ""), queue_id=row["id"])
        else:
            await self.trigger(scope=row["scope"], target=row["target"], env=row["env"],
                               plan_id=row["plan_id"], strict_deps=bool(row["strict_deps"]),
                               emp_no=row["emp_no"], workspace=row.get("workspace", ""),
                               queue_id=row["id"])

    async def _push_run_notifications(self):
        """D2：运行结束后读取 case verdicts，按反馈路径注册表自动推送通知。

        事件映射：FAIL→fail，DRIFT/ORPHANED→drift，SKIP/BLOCKED→skip；
        engine_modes 自测不推送；任何异常只记 WARN，不影响执行收尾。
        """
        try:
            if getattr(self, "_scope", "") == "engine_modes" or not self.run_id:
                return
            import json as _json

            cases_dir = SG_ROOT / "reports" / self.run_id / "cases"
            if not cases_dir.is_dir():
                return

            from feedback.notify import NotifyRegistry
            registry = NotifyRegistry(SG_ROOT / "feedback" / "registry.json")
            if not registry.list():  # 未注册 webhook 时零成本退出
                return

            system = os.environ.get("SPEC_GUARD_SYSTEM", "tdm")
            event_map = {"FAIL": "fail", "DRIFT": "drift", "ORPHANED": "drift",
                         "SKIP": "skip", "BLOCKED": "skip"}
            for case_file in sorted(cases_dir.glob("*.json")):
                try:
                    case = _json.loads(case_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                verdict = case.get("verdict", "")
                event = event_map.get(verdict)
                if not event:
                    continue
                scenario_id = case.get("scenario_id", case_file.stem)
                failure = case.get("failure") or {}
                conclusion = failure.get("category") or case.get("skip_reason") or f"判定 {verdict}"
                await asyncio.to_thread(
                    registry.send_notification,
                    system, scenario_id, event, verdict,
                    str(conclusion)[:200], f"reports/{self.run_id}/report.md",
                )
        except Exception as e:
            print(f"[SpecGuard WARN] 通知自动推送失败（不影响执行结果）: {type(e).__name__}: {e}")

    async def resume(self) -> dict:
        """断点放行：继续执行下一批场景"""
        if not self.is_paused or not self._resume_event:
            return {"ok": False, "error": "当前无暂停中的执行"}
        self._resume_event.set()
        return {"ok": True}

    def get_status(self) -> dict:
        queue = []
        try:
            from services import user_store
            queue = user_store.list_run_queue()
        except Exception:
            pass
        return {
            "status": self.status,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "started_at": self.started_at,
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "paused_at": self.paused_at,
            "breakpoints": self.breakpoints,
            "completed_scenarios": self.completed_scenarios,
            "pending_scenarios": self.pending_scenarios,
            "subscriber_count": len(self.subscribers),
            "current_emp_no": self.current_emp_no,
            "current_workspace": self.current_workspace,
            "queue": queue,
        }


# 全局单例
run_manager = RunManager()
