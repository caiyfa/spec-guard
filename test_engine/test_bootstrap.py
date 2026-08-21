"""引擎离线单测：bootstrap 组合根（T-970 装配归一）——不依赖 DB/HTTP。

此前 conftest.py / plan_executor._setup_runtime / live_registry.get_live_registry
三处复刻装配逻辑且已漂移（plan_executor 漏注册内置 oracles，引擎直跑的计划
里 schema_match 等断言器不可用）。本测试锁定组合根契约：

- load_system_env：systems/{system} 的 load_env / config.load_env 回退
- build_registry：内置 steps + 内置 oracles + 系统适配包 register（db 可为 None）
- build_token_provider：从 env_config 的 sso/internal_token 段构建
- build_scenario_graph：场景库目录 → DependencyGraph
"""

import os
import sys

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.bootstrap import (  # noqa: E402
    build_registry,
    build_scenario_graph,
    build_token_provider,
    load_system_env,
)


def test_load_system_env_returns_dict():
    cfg = load_system_env("tdm", "sit")
    assert isinstance(cfg, dict)
    # env.sit.yaml 必有段：网关与账号池
    assert "gateway" in cfg or "sso" in cfg or "accounts" in cfg


def test_build_registry_includes_builtin_oracles():
    # 回归锚点：plan_executor 复刻版曾漏 register_builtin_oracles——
    # 组合根必须同时注册内置 steps 与内置 oracles
    reg = build_registry("tdm", {})
    assert "schema_match" in reg.oracles
    for step in ("call", "set_var", "db_query", "poll", "random", "tool", "python"):
        assert step in reg.step_handlers, f"内置步骤缺失: {step}"


def test_build_registry_system_package_registered():
    # tdm 适配包：系统专属 oracle 与 step（db=None 只注册元数据，不连库）
    reg = build_registry("tdm", {})
    assert "snapshot_frozen" in reg.oracles
    assert "permission_filtered" in reg.oracles
    assert "select_emp" in reg.step_handlers
    assert "fetch_permission" in reg.step_handlers


def test_build_registry_system_pools_injected():
    # T-972：领域词库由适配包注入 registry.pools（引擎本体零领域词）
    reg = build_registry("tdm", {})
    assert "activity_name" in reg.pools
    assert "person_name" in reg.pools
    assert any("盘点" in w for w in reg.pools["activity_name"])


def test_build_token_provider_from_env_config():
    tp = build_token_provider({
        "sso": {"domain": "https://sso.example", "app_id": "app", "password": "pw"},
        "internal_token": {"mode": "static"},
    })
    assert tp is not None


def test_build_scenario_graph_loads_repo_scenarios():
    graph = build_scenario_graph(os.path.join(SG_ROOT, "scenarios"))
    assert graph.by_id, "场景库为空——DAG 未加载任何场景"
