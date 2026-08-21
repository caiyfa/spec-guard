"""SpecGuard pytest 装配：加载系统适配包 + session 级运行上下文。

环境变量：
- SPEC_GUARD_SYSTEM  被测系统适配包名（默认 tdm；runner 按触发工作区注入，T-971）
- SG_ENV             目标环境（默认 sit），也可用 --env 覆盖
- SG_SCENARIOS_ROOT  场景库根（runner 按触发工作区注入；缺省仓库根 scenarios/）
"""

import os
import sys
from datetime import datetime

import pytest

SG_ROOT = os.path.dirname(os.path.abspath(__file__))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine import report_writer  # noqa: E402
from engine.bootstrap import (  # noqa: E402
    build_registry,
    build_scenario_graph,
    build_token_provider,
    load_system_env,
)
from engine.scenario_runner import RunContext, run_teardowns  # noqa: E402

# T-971：SG_SCENARIOS_ROOT 与 SG_REPORTS_ROOT 同模式（F-1-2）——RunControl
# 按触发工作区注入工作区场景库；CLI 直跑缺省仓库根 scenarios/
SCENARIOS_ROOT = os.environ.get("SG_SCENARIOS_ROOT") or os.path.join(SG_ROOT, "scenarios")
# F-1-2: 支持 runner.py 通过环境变量指定报告目录（落 .specguard/reports/）
REPORTS_ROOT = os.environ.get("SG_REPORTS_ROOT") or os.path.join(SG_ROOT, "reports")


def pytest_addoption(parser):
    parser.addoption("--env", action="store", default=os.environ.get("SG_ENV", "sit"),
                     help="目标环境（sit/uat），对应 systems/{system}/config/env.{env}.yaml")
    parser.addoption("--skip-upstream-verify", action="store_true", default=False,
                     help="上游场景仅执行 flow（跳过其 verify 断言）")
    parser.addoption("--prep-only", action="store_true", default=False,
                     help="仅执行依赖闭包的上游 flow 准备环境，目标场景不执行")
    parser.addoption("--strict-deps", action="store_true",
                     default=os.environ.get("SG_STRICT_DEPS", "").lower() in ("1", "true", "yes"),
                     help="严格依赖模式：DRIFT/ORPHANED 升格为 FAIL（发版门禁用；也可用 SG_STRICT_DEPS 环境变量）")


@pytest.fixture(scope="session")
def sg_system():
    return os.environ.get("SPEC_GUARD_SYSTEM", "tdm")


@pytest.fixture(scope="session")
def env_config(sg_system, pytestconfig):
    """加载 systems/{system}/config/env.{env}.yaml

    K-056：SG_ACCOUNT_OVERRIDE 环境变量——执行控制确认弹窗选定的账号别名，
    将其配置重映射到 default 别名（场景 as: default 即以所选账号执行）。
    """
    env_name = pytestconfig.getoption("--env")
    cfg = load_system_env(sg_system, env_name)
    override = os.environ.get("SG_ACCOUNT_OVERRIDE", "").strip()
    if override:
        accounts = cfg.get("accounts") or {}
        if override in accounts:
            accounts["default"] = accounts[override]
            cfg["_account_override"] = override
        else:
            print(f"[SpecGuard WARN] SG_ACCOUNT_OVERRIDE={override} 不在 accounts 中，忽略")
    # T-312：执行前预检变量覆盖（确认弹窗输入值）——SG_OVERRIDES JSON 数组
    # [{kind: account|env, name, value}]，runner spawn 时注入，合并进环境配置。
    # services 包在 workbench/backend 下，需补 path（runner 侧同源逻辑）
    overrides_json = os.environ.get("SG_OVERRIDES", "").strip()
    if overrides_json:
        try:
            import json
            backend_dir = os.path.join(SG_ROOT, "workbench", "backend")
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            from services.preflight import apply_overrides
            cfg = apply_overrides(cfg, json.loads(overrides_json))
        except ImportError:
            print("[SpecGuard WARN] SG_OVERRIDES 存在但无法加载 services.preflight，忽略覆盖")
        except Exception as e:
            print(f"[SpecGuard WARN] SG_OVERRIDES 应用失败: {e}")
    return cfg


@pytest.fixture(scope="session")
def db_registry(env_config):
    """K-055：命名 DB 连接注册表（多 schema）——(dbs dict, default_name)。

    env yaml db 段双形态：旧单 dict（视为 default）/ 新 dict-of-dicts。
    连接失败单个降级（WARN + 跳过），不阻断其他 schema。
    """
    from engine.db_oracle import build_db_connections
    dbs, default_name = build_db_connections(env_config.get("db"))
    yield dbs, default_name
    for conn in dbs.values():
        conn.close()


@pytest.fixture(scope="session")
def db(db_registry):
    """默认只读 DB 连接（缺失/失败为 None，相关能力降级为 SKIP）"""
    dbs, default_name = db_registry
    return dbs.get(default_name)


@pytest.fixture(scope="session")
def registry(sg_system, env_config, db):
    """引擎内置注册 + 系统适配包注册（传入 db 供系统包构建工号池/查询库）"""
    return build_registry(sg_system, env_config, db)


@pytest.fixture(scope="session")
def token_provider(env_config):
    return build_token_provider(env_config)


@pytest.fixture(scope="session")
def scenario_graph():
    """全场景库 + DAG（依赖解析需要跨模块可见）"""
    return build_scenario_graph(SCENARIOS_ROOT)


@pytest.fixture(scope="session")
def rctx(registry, env_config, token_provider, scenario_graph, sg_system, pytestconfig, db_registry):
    """运行上下文：session 结束时统一落盘 JSON + MD 报告

    K-050：SG_RUN_ID 环境变量优先——工作台执行控制传入任务编号（EX-xxxxxxxx），
    报告目录与任务编号同名；CLI 直跑回退时间戳。
    """
    run_id = os.environ.get("SG_RUN_ID") or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    started_at = datetime.now().isoformat(timespec="seconds")
    run_dir = os.path.join(REPORTS_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    dbs, default_name = db_registry
    ctx = RunContext(
        registry=registry,
        env_config=env_config,
        token_provider=token_provider,
        graph=scenario_graph,
        run_dir=run_dir,
        skip_upstream_verify=pytestconfig.getoption("--skip-upstream-verify"),
        prep_only=pytestconfig.getoption("--prep-only"),
        db=dbs.get(default_name),
        dbs=dbs,
        strict_deps=pytestconfig.getoption("--strict-deps"),
    )
    yield ctx

    # 先捕获租约快照（run_teardowns 会 release_all 清空），再执行 teardown，再落盘报告
    lease_snapshot = ctx.leases.snapshot()
    # 先执行全部实例的 teardown（LIFO），再落盘报告——teardown 轨迹才能进入 case JSON
    run_teardowns(ctx)

    meta = {
        "run_id": run_id,
        "env": env_config.get("env_name", "sit"),
        "system": sg_system,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "module": "",
        "leases": lease_snapshot,   # 租约快照落入 run.json（谁持有什么）
    }
    report_writer.dump_json(ctx.records, run_dir, meta)
    report_path = report_writer.render_md(ctx.records, run_dir, meta)
    print(f"\n[SpecGuard] 报告已生成: {report_path}")
    print(f"[SpecGuard] 结构化数据: {os.path.join(run_dir, 'run.json')}")
