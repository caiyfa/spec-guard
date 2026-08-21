"""执行控制服务：subprocess 管理 + WebSocket 实时广播。

包装 `python -m pytest` 命令，流式读取输出并广播给前端。
不修改引擎代码。

K-047：子进程创建从 asyncio.create_subprocess_exec 改为 subprocess.Popen + 读线程——
uvicorn --reload 在 Windows 下给服务端 SelectorEventLoop（use_subprocess 语义反转），
asyncio 子进程直接 NotImplementedError；Popen 不依赖事件循环 flavor，dev/prod 通吃。
"""

import asyncio
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import WebSocket

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 仓库根


def _new_run_id() -> str:
    """K-050：任务编号——EX- 固定前缀（EXecution）+ 8 位随机 hex。

    替代时间戳 run_id：排错时报编号即可唯一定位（报告目录/日志文件/run.json 同名），
    不再靠「大概几点跑的」回忆。collision 空间 32bit，单用户串行+队列场景足够。
    """
    return "EX-" + secrets.token_hex(4)


def _run_timeout_sec() -> float:
    """T-118/T-204：看门狗超时配置——settings KV（run_timeout_sec）优先，回退环境变量 SG_RUN_TIMEOUT。

    进程挂死（网络黑洞/poll 死循环）时自动终止并标 timeout，不再永久占用队列。
    0 = 禁用（不设超时）。
    """
    raw = ""
    try:
        from services.settings_store import get_setting
        raw = get_setting("run_timeout_sec", "")
    except Exception:
        pass
    if not raw:
        raw = os.environ.get("SG_RUN_TIMEOUT", "")
    try:
        return float(raw or 0)
    except ValueError:
        return 0.0


def _get_reports_root() -> Path:
    """获取报告目录（优先工作区 .specguard/reports/，无工作区回退 SG_ROOT/reports/）。"""
    try:
        from specstd.workspace import reports_dir
        return reports_dir()
    except Exception:
        return SG_ROOT / "reports"


def _resolve_run_context(workspace: str) -> tuple[str, str]:
    """按触发工作区解析 (system, scenarios_root)——T-971 断链修复的唯一解析点。

    system：工作区绑定优先，回退 resolve_system()（contextvar/env/tdm）；
    scenarios_root：工作区 scenarios/ 存在则用（与 draft_promote._scenarios_root
    同口径），否则空串（子进程回退仓库根 scenarios/）。
    """
    system, scenarios_root = "", ""
    if workspace:
        try:
            from specstd.workspace import get_workspace
            ws = get_workspace(workspace)
            if ws:
                system = ws.system or ""
                ws_scenarios = ws.root / "scenarios"
                if ws_scenarios.is_dir():
                    scenarios_root = str(ws_scenarios)
        except Exception:
            pass
    if not system:
        from specstd.workspace import resolve_system
        system = resolve_system()
    return system, scenarios_root


def _spawn_pytest(cmd: list[str], env: str, run_id: str = "",
                  account_override: str = "", overrides: Optional[list] = None,
                  system: str = "", scenarios_root: str = "") -> subprocess.Popen:
    """创建 pytest 子进程（K-047：subprocess.Popen，不依赖事件循环 flavor）。

    uvicorn --reload 在 Windows 给服务端 SelectorEventLoop（其 use_subprocess 语义
    与直觉相反：reload 模式反而返回 Selector），asyncio.create_subprocess_exec 在该
    loop 上直接 NotImplementedError（空消息）。Popen 在任何 loop 下都可用。
    text 模式 + 行缓冲：读线程按行迭代即可。
    K-050：SG_RUN_ID 透传——引擎报告目录与任务编号同名（报告/日志/run.json 一线索）。
    T-312：SG_OVERRIDES 透传——确认弹窗输入的变量覆盖（账号/env 键），
    conftest env_config fixture 合并进环境配置（与 K-056 SG_ACCOUNT_OVERRIDE 同模式）。
    T-971 断链修复：SPEC_GUARD_SYSTEM 按触发工作区注入（此前只加 SG_ENV，
    RunControl 主执行链永远跑后端进程 env，工作区绑定的 system 形同虚设）；
    SG_SCENARIOS_ROOT 同理（工作区场景库存在时子进程加载工作区场景）。
    """
    child_env = {**os.environ, "SG_ENV": env, "SG_REPORTS_ROOT": str(_get_reports_root())}
    if system:
        child_env["SPEC_GUARD_SYSTEM"] = system
    if scenarios_root:
        child_env["SG_SCENARIOS_ROOT"] = scenarios_root
    if run_id:
        child_env["SG_RUN_ID"] = run_id
    if account_override:
        # K-056：执行时账号选择（确认弹窗选定）→ 子进程 conftest 重映射 default 别名
        child_env["SG_ACCOUNT_OVERRIDE"] = account_override
    if overrides:
        child_env["SG_OVERRIDES"] = json.dumps(overrides, ensure_ascii=False)
    # T-118：Windows 下独立进程组——terminate/kill 不殃及父进程树，
    # 避免 uvicorn reloader 僵尸占端口类事故（docs 67d69c0 运维教训）
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(SG_ROOT),
        env=child_env,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        **kwargs,
    )


async def push_run_notifications(reports_root: Path, run_id: str,
                                 system: str = "") -> None:
    """T-304：D2 场景级通知推送（runner 与 plan_executor 共用单一实现）。

    读 {reports_root}/{run_id}/cases 的 verdicts，按反馈路径注册表推送：
    FAIL→fail，DRIFT/ORPHANED→drift，SKIP/BLOCKED→skip；
    任何异常只记 WARN，不影响执行收尾。
    system：本次执行的被测系统（T-971——通知口径跟随运行而非后端进程 env，
    未传时按 resolve_system() 兜底）。
    """
    try:
        import json as _json

        root = Path(reports_root)
        case_dirs = [root / run_id / "cases"]
        case_dirs += [d / "cases" for d in sorted(root.glob(f"{run_id}-b*"))]

        from feedback.notify import NotifyRegistry
        registry = NotifyRegistry(SG_ROOT / "feedback" / "registry.json")
        if not registry.list_webhooks():  # 未注册 webhook 时零成本退出
            return

        if not system:
            from specstd.workspace import resolve_system
            system = resolve_system()
        event_map = {"FAIL": "fail", "DRIFT": "drift", "ORPHANED": "drift",
                     "SKIP": "skip", "BLOCKED": "skip"}
        for cases_dir in case_dirs:
            if not cases_dir.is_dir():
                continue
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
                    str(conclusion)[:200], f"reports/{cases_dir.parent.name}/report.md",
                )
    except Exception as e:
        print(f"[SpecGuard WARN] 通知自动推送失败（不影响执行结果）: {type(e).__name__}: {e}")


class RunManager:
    """管理单次 pytest 执行的生命周期 + WebSocket 广播 + 断点暂停/恢复"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.run_id: Optional[str] = None
        self.plan_id: str = ""
        self.status: str = "idle"  # idle / running / paused / completed / aborted
        self.started_at: Optional[str] = None
        self.subscribers: list[WebSocket] = []
        self._output_lines: list[str] = []
        # 多用户队列（M8）：当前执行的归属与持久化队列项
        self.current_emp_no: str = ""
        self.current_workspace: str = ""
        # T-971：当前执行的被测系统与场景库根（断链修复——spawn/通知/断点上下文共用）
        self.current_system: str = ""
        self._run_scenarios_root: str = ""
        self._queue_id: Optional[int] = None
        self._scope: str = ""
        # 断点状态
        self.breakpoints: list[str] = []          # 断点场景 ID 列表
        self.pending_scenarios: list[str] = []    # 待执行场景（断点分段用）
        self.completed_scenarios: list[str] = []  # 已完成场景
        self.current_batch: list[str] = []        # 当前批次场景
        self.paused_at: str = ""                  # 暂停在哪个场景前
        self._resume_event: Optional[asyncio.Event] = None
        self._run_dir: Optional[Path] = None      # K-050：报告目录（output.log 落盘处）
        # T-118：看门狗——run 级超时（SG_RUN_TIMEOUT 秒，0=禁用）与起始时刻
        self._run_timeout: float = 0.0
        self._started_monotonic: float = 0.0

    @property
    def is_running(self) -> bool:
        return self.status in ("running", "paused")

    @property
    def is_paused(self) -> bool:
        return self.status == "paused"

    async def subscribe(self, ws: WebSocket):
        """订阅实时流（T-123：accept 由调用方负责——首帧认证需先 accept 才能收消息）。"""
        self.subscribers.append(ws)
        # 发送当前状态
        await ws.send_json({"type": "status", "status": self.status, "run_id": self.run_id})
        # T-122：回放行数与前端 events 上限（500）对齐——此前只回放 100 行，
        # 前端重连清空 events 后收到不连续日志（中间段丢失）
        for line in self._output_lines[-500:]:
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
                      queue_id: Optional[int] = None,
                      prep_only: bool = False, skip_upstream_verify: bool = False,
                      account_override: str = "",
                      overrides: Optional[list] = None) -> dict:
        """触发执行

        scope: all / module / scenario / tag / engine_modes
        target: 场景ID / 模块路径 / 标签名（scope != all 时有效）
        plan_id: 测试计划 ID（非空时报告归档到 reports/{plan_id}/）
        strict_deps: 严格依赖模式（SG_STRICT_DEPS=1 注入子进程，DRIFT/ORPHANED → BLOCKED）
        emp_no/workspace: 触发人与工作区（多用户归属，M8）
        queue_id: 来自队列的消费（内部用；为 None 时新建队表记录）
        prep_only / skip_upstream_verify / account_override: K-046/K-056 轻量执行与账号选项。
            T-114：run_queue 表已持久化这三项，排队后重放不丢（此前静默丢失）。
        overrides: T-312 执行变量覆盖 [{kind: account|env, name, value}]——确认弹窗
            预检缺失项的输入值，SG_OVERRIDES 注入子进程由 conftest 合并。

        已有执行时进入 FIFO 队列（run_queue 表持久化），返回 queued + position。
        """
        if self.is_running:
            from services import user_store
            qid = user_store.enqueue_run(
                emp_no=emp_no, scope=scope, target=target, env=env, plan_id=plan_id,
                breakpoints=[], strict_deps=strict_deps, workspace=workspace,
                prep_only=prep_only, skip_upstream_verify=skip_upstream_verify,
                account_override=account_override, overrides=overrides)
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
                breakpoints=[], strict_deps=strict_deps, workspace=workspace, status="running",
                prep_only=prep_only, skip_upstream_verify=skip_upstream_verify,
                account_override=account_override, overrides=overrides)
        self.current_emp_no = emp_no
        self.current_workspace = workspace
        # T-971 断链修复：按触发工作区解析被测系统与场景库根，注入子进程
        self.current_system, self._run_scenarios_root = _resolve_run_context(workspace)

        # 构建 pytest 命令（K-049：-s 关闭输出捕获，trace_id 等调用上下文实时流入执行日志）
        cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short", "-s"]
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
        if prep_only:
            cmd += ["--prep-only"]
        if skip_upstream_verify:
            cmd += ["--skip-upstream-verify"]

        self.run_id = _new_run_id()
        self.plan_id = plan_id
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.status = "running"
        self._output_lines = []
        # T-118：看门狗计时起点（SG_RUN_TIMEOUT 秒，0=禁用）
        self._run_timeout = _run_timeout_sec()
        self._started_monotonic = time.monotonic()
        # K-050：执行日志落盘——与引擎报告同目录（{reports}/{run_id}/output.log）
        self._run_dir = _get_reports_root() / self.run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._scope = scope  # D2：通知推送豁免 engine_modes 用
        if queue_id is None:
            user_store.audit(emp_no, "trigger_run", scope, f"queue_id={self._queue_id}")

        # K-053：触发上下文结构化落盘（Agent 按任务号可查到选了哪些场景/什么环境）
        self._write_trigger_context({
            "run_id": self.run_id, "scope": scope, "target": target,
            "selected_scenarios": target.split(" or ") if (scope == "scenario" and target) else [],
            "env": env, "plan_id": plan_id, "system": self.current_system,
            "prep_only": prep_only, "skip_upstream_verify": skip_upstream_verify,
            "strict_deps": strict_deps, "account_override": account_override,
            "overrides": overrides,
            "emp_no": emp_no, "workspace": workspace, "started_at": self.started_at,
        })

        # 启动子进程（K-047：Popen；失败时队表标记 failed，不再遗留 running 卡死队列）
        try:
            self.process = _spawn_pytest(cmd, env, self.run_id, account_override,
                                         overrides, system=self.current_system,
                                         scenarios_root=self._run_scenarios_root)
        except Exception as e:
            # T-115：spawn 失败补发终态广播（此前 started 先广播且无 finished →
            # 前端永久卡「执行中」显示一个不存在的任务号）
            await self.broadcast({
                "type": "finished",
                "run_id": self.run_id,
                "returncode": None,
                "status": "failed",
                "error": f"启动失败: {type(e).__name__}: {e}",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            })
            self.status = "idle"
            if self._queue_id:
                user_store.update_run_queue(self._queue_id, "failed", finished=True)
                self._queue_id = None
            self.current_emp_no = ""
            self.current_workspace = ""
            self.current_system = ""
            self._run_scenarios_root = ""
            # K-047：异常带类型名——空 str(e) 的异常（如 NotImplementedError）不再无法排查
            return {"ok": False, "error": f"启动失败: {type(e).__name__}: {e}"}

        # T-115：started 在 spawn 成功后广播（此前先广播 started 再 Popen，
        # spawn 抛异常时前端已置 running 且永无终态）
        await self.broadcast({
            "type": "started",
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "cmd": " ".join(cmd),
            "started_at": self.started_at,
        })
        # T-310：日志头行带触发上下文（触发人/账号/工作区/选中场景）——
        # 此前只有 env + 命令，排错要另翻 trigger.json 才知道谁触发、什么账号
        ctx_parts = [f"env={env}"]
        if self.current_system:
            ctx_parts.append(f"system={self.current_system}")
        if scope == "scenario" and target:
            ctx_parts.append(f"选中={target}")
        if emp_no:
            ctx_parts.append(f"触发人={emp_no}")
        if account_override:
            ctx_parts.append(f"账号={account_override}")
        if workspace:
            ctx_parts.append(f"工作区={workspace}")
        if plan_id:
            ctx_parts.append(f"计划={plan_id}")
        if overrides:
            ctx_parts.append(f"覆盖={len(overrides)}项")
        self._write_output_log(f"> {self.run_id} | {' | '.join(ctx_parts)} | {' '.join(cmd)}")

        # 后台读取输出
        asyncio.create_task(self._stream_output())

        return {"ok": True, "run_id": self.run_id}

    async def _stream_output(self):
        """读取子进程输出并广播，收尾（通知 + 队列消费）"""
        proc = self.process
        if not proc:
            return
        await self._drain_output(proc)
        # T-112/T-118：终态修正——abort/timeout 保持原状态；非零退出置 failed
        # （此前两分支相同恒为 completed，pytest 崩溃/超时被误报为成功）
        if self.status == "aborted":
            final_status = "aborted"
        elif self.status == "timeout":
            final_status = "timeout"
        else:
            final_status = "completed" if proc.returncode == 0 else "failed"
        self.status = final_status
        await self.broadcast({
            "type": "finished",
            "run_id": self.run_id,
            "returncode": proc.returncode,
            "status": final_status,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        self.process = None
        # D2 修复：执行完成后按注册表自动推送飞书通知（fail/drift/skip 事件）
        self._record_failures()  # K-052：失败索引（场景×任务号×原因台账）
        self._record_executions()  # 执行台账：全量结果（场景×任务号×verdict×saved_vars）
        self._record_experience()  # T-510：经验飞轮落行（失败场景 → 五段式经验草稿）
        await self._push_run_notifications()
        # M8：收尾并消费队列下一个
        await self._finish_current_run()

    def _write_output_log(self, text: str):
        """K-050：执行日志落盘（{reports}/{run_id}/output.log）——此前 stdout 流只存内存，
        后端重启即失，排错只能靠回忆。与引擎报告同目录，报任务编号即可拿到完整现场。"""
        if not self._run_dir:
            return
        try:
            with open(self._run_dir / "output.log", "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass  # 落盘失败不影响执行与直播

    def _write_trigger_context(self, ctx: dict):
        """K-053：触发上下文结构化落盘（{reports}/{run_id}/trigger.json）——
        选中场景/环境/轻量选项/触发人/工作区。Agent 按任务号排查时不用解析 cmd 文本。"""
        if not self._run_dir:
            return
        try:
            with open(self._run_dir / "trigger.json", "w", encoding="utf-8") as f:
                json.dump(ctx, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _record_experience(self):
        """T-510：经验飞轮落行——失败场景自动落五段式经验草稿（幂等）。

        从 run.json 提取 FAIL/BLOCKED/ERROR 场景 → {ws}/.specguard/experience/；
        断点分批报告的批次目录（{run_id}-bN）逐批收录。
        """
        try:
            from services import experience_store
            root = _get_reports_root()
            ws_root = None
            try:
                from specstd.workspace import get_workspace_root
                ws_root = get_workspace_root()
            except Exception:
                pass
            if not ws_root:
                return
            n = experience_store.append_experience(root, self.run_id, ws_root)
            for batch_dir in sorted(root.glob(f"{self.run_id}-b*")):
                n += experience_store.append_experience(root, batch_dir.name, ws_root)
            if n:
                self._write_output_log(f"> {self.run_id} | {n} 条失败经验已落行（.specguard/experience/）")
        except Exception:
            pass  # 经验落行失败不影响执行主流程

    def _record_failures(self):
        """K-052：执行完成后把失败场景写入失败索引（failures/index.jsonl）——
        「场景 × 任务号 × 失败原因」台账，Agent list_failures 工具与人工追溯共用。"""
        try:
            from services import failure_index
            root = _get_reports_root()
            n = failure_index.append_failures(root, self.run_id)
            # 断点分批执行的报告在 {run_id}-bN 目录，逐批收录
            for batch_dir in sorted(root.glob(f"{self.run_id}-b*")):
                n += failure_index.append_failures(root, batch_dir.name)
            if n:
                self._write_output_log(f"> {self.run_id} | {n} 条失败已记入 failures/index.jsonl")
        except Exception:
            pass  # 索引失败不影响执行结论

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

    async def _drain_output(self, proc: subprocess.Popen):
        """读线程逐行推入 asyncio.Queue 并广播，直到进程输出 EOF（K-047 共用模式）。"""
        if not proc or not proc.stdout:
            return
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def _reader():
            try:
                for raw in proc.stdout:
                    loop.call_soon_threadsafe(q.put_nowait, raw.rstrip("\r\n"))
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        threading.Thread(target=_reader, daemon=True).start()

        # T-118：看门狗——总超时截止（从触发时刻起算，0=禁用）
        deadline = None
        if getattr(self, "_run_timeout", 0) and getattr(self, "_started_monotonic", 0):
            deadline = self._started_monotonic + self._run_timeout

        while True:
            try:
                remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
                text = await asyncio.wait_for(q.get(), timeout=remaining)
            except asyncio.TimeoutError:
                # T-118：进程挂死超时——终止并标记 timeout（此前无超时，队列永久占用）
                await self._timeout_abort()
                break
            if text is None:
                break
            self._output_lines.append(text)
            self._write_output_log(text)
            event = self._parse_line(text)
            await self.broadcast({"type": "output", "line": text, **event})

        await asyncio.to_thread(proc.wait)

    async def _timeout_abort(self):
        """T-118：看门狗超时——终止进程、标 timeout、广播终态并留痕。

        超时是执行失败（不是用户主动中止），队表收尾走 failed。
        """
        try:
            if self.process:
                self.process.terminate()
                await asyncio.sleep(0.5)
                if self.process.returncode is None:
                    self.process.kill()
        except Exception:
            pass
        self.status = "timeout"
        self._write_output_log(
            f"> {self.run_id} | TIMEOUT 超过 {self._run_timeout}s，已强制终止")
        await self.broadcast({
            "type": "finished",
            "run_id": self.run_id,
            "returncode": self.process.returncode if self.process else None,
            "status": "timeout",
            "error": f"执行超过 {self._run_timeout}s 超时（SG_RUN_TIMEOUT 可调），已强制终止",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })

    # T-303：verdict 与参数化场景 ID 的正则（替代字符串切片——行内含额外 [..] 时
    # 原 split("[")[-1] 会取错段，如 "[PP-RC-001] PASSED [ 50%]" 会误取 " 50%"）
    _VERDICT_RE = re.compile(r"\b(PASSED|FAILED|SKIPPED|ERROR)\b")
    _PARAM_ID_RE = re.compile(r"\[([A-Z][A-Z0-9_-]*)\]")  # 场景 ID 形态：XX-XXX-NNN（大写字母数字连字符）

    def _parse_line(self, line: str) -> dict:
        """解析 pytest 输出行，提取场景 verdict 与参数化场景 ID。

        T-303：正则提取——仅匹配场景 ID 形态的 [XX-XXX-NNN]；
        非参数化行（如 engine_modes 的 test_shared）verdict 有值但 scenario_id 为空。
        T-314：引擎锚点行（[SpecGuard] 前缀）跳过——body 摘要可能含 FAILED/ERROR 词，
        误判会污染 verdictMap（响应体里 "VALIDATION FAILED" 会让场景显示 FAILED）。
        """
        if line.lstrip().startswith("[SpecGuard]"):
            return {}
        m = self._VERDICT_RE.search(line)
        if not m:
            return {}
        verdict = m.group(1)
        # 取行内最后一个场景 ID 形态的参数化段（pytest -k "A or B" 逐行输出）
        scenario_id = ""
        for pm in self._PARAM_ID_RE.finditer(line):
            scenario_id = pm.group(1)
        return {"verdict": verdict, "scenario_id": scenario_id}

    async def abort(self) -> dict:
        """终止执行（T-111：断点暂停中 abort 置位 resume 事件，收尾不再卡死队列）"""
        if not self.is_running:
            return {"ok": False, "error": "当前无执行中的任务"}
        # 断点暂停（批次间隙）可能没有存活子进程——abort 语义同样成立
        if self.process:
            try:
                self.process.terminate()
                await asyncio.sleep(1)
                if self.process.returncode is None:
                    self.process.kill()
            except Exception:
                pass
        self.status = "aborted"
        # T-111：暂停等待 resume 信号时置位事件，让 _run_batches 醒来走 abort 收尾
        # （此前仅 terminate+置状态，_run_batches 永卡 wait()，队表项永远 running）
        if self._resume_event:
            self._resume_event.set()
        await self.broadcast({"type": "aborted", "run_id": self.run_id})
        return {"ok": True}

    async def trigger_with_breakpoints(self, scenario_ids: list[str], breakpoints: list[str],
                                       env: str = "sit", plan_id: str = "",
                                       strict_deps: bool = False,
                                       emp_no: str = "", workspace: str = "",
                                       queue_id: Optional[int] = None,
                                       overrides: Optional[list] = None) -> dict:
        """带断点的分段执行

        将场景列表按断点切分为多个批次，逐批执行：
        - 批次间遇到断点场景时暂停，广播上下文，等待 resume 信号
        - 无断点时退化为一次性全量执行
        - 已有执行时进入 FIFO 队列（M8）
        overrides: T-312 执行变量覆盖（SG_OVERRIDES 透传每批次）。
        """
        if self.is_running:
            from services import user_store
            target = " or ".join(scenario_ids)
            qid = user_store.enqueue_run(
                emp_no=emp_no, scope="breakpoint", target=target, env=env, plan_id=plan_id,
                breakpoints=breakpoints, strict_deps=strict_deps, workspace=workspace,
                overrides=overrides)
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
                workspace=workspace, status="running", overrides=overrides)
        self.current_emp_no = emp_no
        self.current_workspace = workspace
        # T-971 断链修复：断点路径同样按工作区解析（批次 spawn 共用）
        self.current_system, self._run_scenarios_root = _resolve_run_context(workspace)

        self.run_id = _new_run_id()
        self.plan_id = plan_id
        self.breakpoints = breakpoints
        self.pending_scenarios = list(scenario_ids)
        self.completed_scenarios = []
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self._output_lines = []
        # T-118：看门狗计时起点（跨批次的总超时）
        self._run_timeout = _run_timeout_sec()
        self._started_monotonic = time.monotonic()
        # K-050：执行日志落盘目录（与引擎报告同目录）
        self._run_dir = _get_reports_root() / self.run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        # K-053：断点路径的触发上下文
        self._write_trigger_context({
            "run_id": self.run_id, "scope": "breakpoint", "target": " or ".join(scenario_ids),
            "selected_scenarios": list(scenario_ids), "breakpoints": breakpoints,
            "env": env, "plan_id": plan_id, "system": self.current_system,
            "strict_deps": strict_deps,
            "emp_no": emp_no, "workspace": workspace, "started_at": self.started_at,
        })

        # 无断点 → 直接全量执行
        if not breakpoints:
            target = " or ".join(scenario_ids)
            return await self.trigger(scope="scenario", target=target, env=env, plan_id=plan_id,
                                      strict_deps=strict_deps, emp_no=emp_no, workspace=workspace,
                                      queue_id=queue_id, overrides=overrides)

        self._strict_deps = strict_deps
        self._overrides = overrides  # T-312：批次 spawn 时透传 SG_OVERRIDES

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
                    # T-111：暂停中被 abort → 收尾（队表结束+失败索引+队列消费），不死锁
                    await self._abort_finish()
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

            cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short", "-s", "-k", target]
            if getattr(self, "_strict_deps", False):
                cmd += ["--strict-deps"]
            self._write_output_log(f"> batch {batch_idx} | {' '.join(cmd)}")
            try:
                # 批次报告目录加 -bN 后缀：同属一个任务编号族，又避免批次间 run.json 相互覆盖
                self.process = _spawn_pytest(cmd, env, f"{self.run_id}-b{batch_idx}",
                                             overrides=getattr(self, "_overrides", None),
                                             system=self.current_system,
                                             scenarios_root=self._run_scenarios_root)
            except Exception as e:
                await self.broadcast({"type": "error", "message": f"批次 {batch_idx} 启动失败: {type(e).__name__}: {e}"})
                # T-112：abort 后不再尝试下一批
                if self.status == "aborted":
                    await self._abort_finish()
                    return
                continue

            # 读取输出（K-047：与 _stream_output 同一读线程模式）
            await self._drain_output(self.process)

            # T-112/T-118：批次执行中被 abort / 超时 → 短路退出（此前 drain 返回后仍继续下一批）
            if self.status in ("aborted", "timeout"):
                await self._abort_finish()
                return

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
        self._record_failures()  # K-052：失败索引（场景×任务号×原因台账）
        self._record_executions()  # 执行台账：全量结果（场景×任务号×verdict×saved_vars）
        self._record_experience()  # T-510：经验飞轮落行
        await self._push_run_notifications()
        # M8：收尾并消费队列下一个
        await self._finish_current_run()

    async def _abort_finish(self):
        """T-111/T-112/T-118：abort / timeout 后统一收尾——失败索引 + 队表结束 + 队列消费。

        此前 abort 路径只置状态，_finish_current_run 永不执行，队表项永远 running
        （只能靠重启 fail_stale_running 清理）；abort 是用户主动行为，不推失败通知；
        timeout 是执行失败，队表标 failed。
        """
        self.process = None
        self._record_failures()  # K-052：已执行批次的失败收录
        self._record_executions()  # 执行台账：已执行批次的全量结果收录
        final_status = self.status or "aborted"
        await self.broadcast({
            "type": "finished",
            "run_id": self.run_id,
            "completed": self.completed_scenarios,
            "aborted": final_status == "aborted",
            "status": final_status,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        await self._finish_current_run(
            status="cancelled" if final_status == "aborted" else "failed")

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
            "system": self.current_system,
        }

    async def _finish_current_run(self, status: str = "done"):
        """M8：当前执行收尾（队表标记完成）并自动启动队列下一个。

        T-111：abort 路径传 status="cancelled"——队表状态诚实反映用户终止，
        不再以 done 掩盖中止。
        """
        from services import user_store
        if self._queue_id:
            user_store.update_run_queue(self._queue_id, status, finished=True)
        self._queue_id = None
        self.current_emp_no = ""
        self.current_workspace = ""
        self.current_system = ""
        self._run_scenarios_root = ""
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
        # T-312：重放时透传持久化的变量覆盖（确认弹窗输入值）
        try:
            overrides = _json.loads(row.get("overrides") or "[]")
        except Exception:
            overrides = []
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
                workspace=row.get("workspace", ""), queue_id=row["id"],
                overrides=overrides)
        else:
            # T-114：重放时透传持久化的轻量选项（此前排队后静默丢失用户选择）
            await self.trigger(scope=row["scope"], target=row["target"], env=row["env"],
                               plan_id=row["plan_id"], strict_deps=bool(row["strict_deps"]),
                               emp_no=row["emp_no"], workspace=row.get("workspace", ""),
                               queue_id=row["id"],
                               prep_only=bool(row.get("prep_only")),
                               skip_upstream_verify=bool(row.get("skip_upstream_verify")),
                               account_override=row.get("account_override", ""),
                               overrides=overrides)

    async def _push_run_notifications(self):
        """D2：运行结束后推送场景级通知（T-304：实现收口到模块级 push_run_notifications）。

        engine_modes 自测不推送；T-113：断点分批执行的 case 在 {run_id}-bN 目录一并扫描。
        """
        if getattr(self, "_scope", "") == "engine_modes" or not self.run_id:
            return
        await push_run_notifications(_get_reports_root(), self.run_id,
                                     system=self.current_system)

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
