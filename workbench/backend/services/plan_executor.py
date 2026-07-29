"""plan_executor: 引擎直跑执行器（DAG 编排 + 失败通知 + 报告落盘）。

加载 plan YAML → scenario_runner 编排 → 逐场景执行
→ 某场景失败 → 下游自动 BLOCKED + 立即通知 → 报告落盘

执行走引擎直跑（不经 pytest），复用 engine.scenario_runner 的编排能力。
"""

import asyncio
import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

# 确保仓库根在 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from engine.registry import Registry                          # noqa: E402
from engine.token_provider import TokenProvider               # noqa: E402
from engine.db_oracle import ReadOnlyDb                       # noqa: E402
from engine.scenario_loader import load_scenarios             # noqa: E402
from engine.dependency_graph import DependencyGraph           # noqa: E402
from engine.scenario_runner import (                          # noqa: E402
    RunContext, register_builtin_steps, run_single, run_teardowns,
)
from engine import report_writer                              # noqa: E402
from engine.execution_record import (                         # noqa: E402
    VERDICT_PASS, VERDICT_FAIL, VERDICT_SKIP, VERDICT_BLOCKED,
    VERDICT_DRIFT, VERDICT_ORPHANED,
)


# ══════════════════════════════════════════════════════════
# 引擎运行时装配（复刻 conftest.py 的 session 级装配）
# ══════════════════════════════════════════════════════════

def _setup_runtime(system: str, env: str, scenarios_root: Path,
                   strict_deps: bool = False):
    """装配引擎运行时（registry / env_config / token_provider / db / graph）。

    复刻 conftest.py 的 session 级 fixture 装配逻辑，供 plan_executor 独立使用。

    Args:
        system: 被测系统适配包名（如 tdm）
        env: 目标环境名（如 sit）
        scenarios_root: 场景库根路径
        strict_deps: 严格依赖模式

    Returns:
        (env_config, db, registry, token_provider, graph)
    """
    # 1. 环境配置
    mod = importlib.import_module(f"systems.{system}")
    if hasattr(mod, "load_env"):
        env_config = mod.load_env(env)
    else:
        cfg_mod = importlib.import_module(f"systems.{system}.config")
        env_config = cfg_mod.load_env(env)

    # 2. DB（只读，可选；配置缺失或连接失败时返回 None，相关能力降级为 SKIP）
    db = None
    db_cfg = env_config.get("db") or {}
    if db_cfg.get("host") and db_cfg.get("user"):
        try:
            conn = ReadOnlyDb(
                host=db_cfg["host"], port=db_cfg.get("port", 3306),
                user=db_cfg["user"], password=db_cfg.get("password", ""),
                database=db_cfg.get("name", "hr_center"),
                charset=db_cfg.get("charset", "utf8mb4"),
            )
            conn.scalar("SELECT 1")
            db = conn
        except Exception as e:
            print(f"[plan_executor WARN] DB 连接失败，DB 校对降级为 SKIP: {e}")

    # 3. Registry（引擎内置 + 系统适配包）
    registry = Registry()
    register_builtin_steps(registry)
    if hasattr(mod, "register"):
        mod.register(registry, env_config, db)

    # 4. TokenProvider
    sso = env_config.get("sso") or {}
    token_provider = TokenProvider(
        sso.get("domain", ""), sso.get("app_id", ""), sso.get("password", ""))

    # 5. 场景库 + DAG（依赖解析需要跨模块可见 → 加载全部场景）
    scenarios = load_scenarios(str(scenarios_root))
    graph = DependencyGraph(scenarios)

    return env_config, db, registry, token_provider, graph


# ══════════════════════════════════════════════════════════
# 引擎直跑执行器
# ══════════════════════════════════════════════════════════

async def execute_plan(plan_id: str, workspace: str = "",
                       triggered_by: str = "schedule",
                       notify_config_id: str = "") -> dict:
    """引擎直跑一组场景（DAG 编排）。

    流程：
    1. 加载 plan YAML → 解析场景 ID 列表
    2. 装配引擎运行时（registry / env / token / db / graph）
    3. 拓扑排序 → 逐场景 run_single（依赖闭包由引擎内部处理）
    4. 场景失败 → 下游自动 BLOCKED + 立即通知（不等全部跑完）
    5. teardown（LIFO 清理）
    6. 报告落盘（复用 report_writer，JSON + MD）

    Args:
        plan_id: 测试计划 ID（plans/{id}.yaml）
        workspace: 工作区名（空时使用当前激活工作区）
        triggered_by: 触发来源（schedule / manual）
        notify_config_id: 通知配置 ID（空时通知所有订阅 plan_failure 的配置）

    Returns:
        {"run_id": str, "status": "success|failed|partial",
         "results": [{"scenario_id", "status", "verdict", ...}],
         "report_dir": str}
    """
    from services import plan_store
    from specstd.workspace import (
        get_workspace, get_active_workspace, set_context_workspace,
        specguard_dir,
    )

    # ── 设置工作区上下文 ──
    if workspace:
        set_context_workspace(workspace)
        ws_info = get_workspace(workspace)
    else:
        ws_info = get_active_workspace()

    if not ws_info:
        return {"run_id": "", "status": "failed",
                "error": "无激活工作区", "results": []}

    ws_root = ws_info.root
    system = ws_info.system or os.environ.get("SPEC_GUARD_SYSTEM", "tdm")

    # ── 1. 加载 plan ──
    plan = plan_store.get_plan(plan_id)
    if not plan:
        return {"run_id": "", "status": "failed",
                "error": f"计划不存在: {plan_id}", "results": []}

    scenario_ids = plan.get("resolved_scenarios") or plan_store.resolve_scenarios(plan)
    env_name = plan.get("env", "sit")
    strict_deps = bool(plan.get("strict_deps", False))
    plan_name = plan.get("name", plan_id)

    if not scenario_ids:
        return {"run_id": "", "status": "success",
                "error": "计划无场景", "results": []}

    # ── 2. 装配引擎运行时 ──
    scenarios_root = ws_root / "scenarios"
    if not scenarios_root.is_dir():
        return {"run_id": "", "status": "failed",
                "error": f"场景库目录不存在: {scenarios_root}", "results": []}

    env_config, db, registry, token_provider, graph = _setup_runtime(
        system, env_name, scenarios_root, strict_deps)

    # ── 3. 构建运行上下文 ──
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    started_at = datetime.now().isoformat(timespec="seconds")

    # 报告目录：优先 {workspace}/.specguard/reports/（F-1-1 已 ✅），
    # 降级 SG_ROOT/reports/
    try:
        sg_dir = specguard_dir(workspace_root=ws_root)
        run_dir = sg_dir / "reports" / run_id
    except Exception:
        run_dir = SG_ROOT / "reports" / run_id

    run_dir.mkdir(parents=True, exist_ok=True)

    rctx = RunContext(
        registry=registry,
        env_config=env_config,
        token_provider=token_provider,
        graph=graph,
        run_dir=str(run_dir),
        db=db,
        strict_deps=strict_deps,
    )

    # ── 4. 拓扑排序 + 逐场景执行 ──
    # 只执行 plan 中的场景；依赖闭包（上游）由 run_single → run_with_deps 内部处理
    missing = [sid for sid in scenario_ids if sid not in graph.by_id]
    if missing:
        print(f"[plan_executor WARN] 计划中的场景在场景库中不存在，跳过: {missing}")

    plan_scenario_ids = [sid for sid in scenario_ids if sid in graph.by_id]
    topo_ids = graph.topo_order(plan_scenario_ids)

    results = []
    try:
        for sid in topo_ids:
            scenario = graph.by_id[sid]
            try:
                # run_single 是同步的引擎执行器，用 asyncio.to_thread 避免阻塞事件循环
                record = await asyncio.to_thread(run_single, scenario, rctx)

                result = {
                    "scenario_id": sid,
                    "status": record.verdict.lower(),
                    "verdict": record.verdict,
                    "title": record.title,
                    "duration_ms": record.duration_ms,
                }
                if record.verdict == VERDICT_FAIL and record.failure:
                    result["error"] = record.failure.get("message", "")
                elif record.verdict in (VERDICT_SKIP, VERDICT_BLOCKED,
                                        VERDICT_DRIFT, VERDICT_ORPHANED):
                    result["reason"] = record.skip_reason
                results.append(result)

                # 失败时立即通知（不等全部跑完）
                if record.verdict == VERDICT_FAIL:
                    await _notify_failure(
                        plan_id, plan_name, sid, record,
                        run_id, notify_config_id)

            except Exception as e:
                # 引擎外异常（如场景加载错误）→ 标记 error 并通知
                results.append({
                    "scenario_id": sid,
                    "status": "error",
                    "verdict": "ERROR",
                    "error": str(e),
                })
                await _notify_failure(
                    plan_id, plan_name, sid, {"error": str(e)},
                    run_id, notify_config_id)

        # ── 5. teardown（LIFO 清理） ──
        run_teardowns(rctx)

    finally:
        # 确保 DB 连接关闭
        if db:
            try:
                db.close()
            except Exception:
                pass

    # ── 6. 报告落盘（复用 report_writer） ──
    finished_at = datetime.now().isoformat(timespec="seconds")
    lease_snapshot = rctx.leases.snapshot()
    meta = {
        "run_id": run_id,
        "env": env_config.get("env_name", env_name),
        "system": system,
        "started_at": started_at,
        "finished_at": finished_at,
        "module": plan_name,
        "leases": lease_snapshot,
    }
    report_writer.dump_json(rctx.records, str(run_dir), meta)
    report_writer.render_md(rctx.records, str(run_dir), meta)
    print(f"[plan_executor] 报告已生成: {run_dir / 'report.md'}")

    # ── 7. 汇总状态 ──
    has_fail = any(r["status"] in ("fail", "error") for r in results)
    has_skip = any(r["status"] in ("skip", "blocked", "drift", "orphaned")
                   for r in results)
    if has_fail:
        status = "failed"
    elif has_skip:
        status = "partial"
    else:
        status = "success"

    # 全部成功时发送成功通知
    if status == "success":
        await _notify_success(
            plan_id, plan_name, len(results), run_id, notify_config_id)

    return {
        "run_id": run_id,
        "status": status,
        "results": results,
        "report_dir": str(run_dir),
    }


# ══════════════════════════════════════════════════════════
# 通知（复用 feedback.notify.send_notification + services.notify_config）
# ══════════════════════════════════════════════════════════

async def _notify_failure(plan_id: str, plan_name: str, scenario_id: str,
                          record_or_error, run_id: str,
                          notify_config_id: str = ""):
    """场景失败时立即发送通知。

    通知走 feedback.notify.send_notification（J-2 已 ✅），配置来自
    services.notify_config（J-1 已 ✅）。通知失败静默记录，不阻塞主流程。

    Args:
        record_or_error: ExecutionRecord 对象 或 {"error": str} dict
    """
    try:
        from feedback.notify import send_notification
        from services.notify_config import get_configs_by_event, get_config

        # 解析通知配置列表
        if notify_config_id:
            cfg = get_config(notify_config_id)
            configs = [cfg] if (cfg and cfg.get("enabled")
                                and "plan_failure" in cfg.get("events", [])) else []
        else:
            configs = get_configs_by_event("plan_failure")

        if not configs:
            return

        # 提取错误信息
        if isinstance(record_or_error, dict) and "error" in record_or_error:
            error_msg = record_or_error["error"]
        else:
            failure = getattr(record_or_error, "failure", None) or {}
            error_msg = failure.get("message", str(record_or_error))

        payload = {
            "plan_name": plan_name,
            "scenario_id": scenario_id,
            "error": str(error_msg)[:300],
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "debug_url": f"/agent?debug_run_id={run_id}",
        }

        for config in configs:
            await send_notification(config, "plan_failure", payload)

    except Exception as e:
        print(f"[plan_executor WARN] 失败通知发送异常（不阻塞主流程）: "
              f"{type(e).__name__}: {e}")


async def _notify_success(plan_id: str, plan_name: str, scenario_count: int,
                          run_id: str, notify_config_id: str = ""):
    """全部场景通过后发送成功通知。"""
    try:
        from feedback.notify import send_notification
        from services.notify_config import get_configs_by_event, get_config

        if notify_config_id:
            cfg = get_config(notify_config_id)
            configs = [cfg] if (cfg and cfg.get("enabled")
                                and "plan_success" in cfg.get("events", [])) else []
        else:
            configs = get_configs_by_event("plan_success")

        if not configs:
            return

        payload = {
            "plan_name": plan_name,
            "scenario_count": scenario_count,
            "run_at": datetime.now().isoformat(timespec="seconds"),
        }

        for config in configs:
            await send_notification(config, "plan_success", payload)

    except Exception as e:
        print(f"[plan_executor WARN] 成功通知发送异常（不阻塞主流程）: "
              f"{type(e).__name__}: {e}")
