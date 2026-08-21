"""bootstrap —— 引擎运行时装配组合根（T-970 装配归一）。

此前 conftest.py / plan_executor._setup_runtime / live_registry.get_live_registry
三处各自复刻装配逻辑，已出现漂移（plan_executor 漏注册内置 oracles）。本模块
是装配的唯一事实源；三处调用点一律经由这里，不允许再各自 importlib 拼装。

约定：
- 纯装配无副作用：不在模块导入时做任何注册/IO；函数失败直接抛，降级语义
  （如 live_registry 的 env 缺失容忍）由调用方自行 try/except。
- 不读 pytest 配置：pytest 特有选项（--env/--skip-upstream-verify 等）与执行
  期环境变量覆盖（SG_ACCOUNT_OVERRIDE/SG_OVERRIDES）留在 conftest，装配后叠加。
- db 参数可为 None：只注册元数据不连库（离线查询/元数据快照场景）。
"""

import importlib

from engine.dependency_graph import DependencyGraph
from engine.registry import Registry
from engine.scenario_loader import load_scenarios
from engine.scenario_runner import register_builtin_steps
from engine.schema_match import register_builtin_oracles
from engine.token_provider import TokenProvider


def load_system_env(system: str, env_name: str) -> dict:
    """加载 systems/{system} 的环境配置（env.{env}.yaml）。

    适配包契约：优先模块级 load_env，未暴露时回退 config 子模块。
    """
    mod = importlib.import_module(f"systems.{system}")
    if hasattr(mod, "load_env"):
        return mod.load_env(env_name)
    cfg_mod = importlib.import_module(f"systems.{system}.config")
    return cfg_mod.load_env(env_name)


def build_registry(system: str, env_config: dict, db=None) -> Registry:
    """引擎内置注册（steps + oracles）+ 系统适配包注册。

    内置 oracles 与内置 steps 必须同位注册——曾因漏调导致引擎直跑计划里
    schema_match 断言器不可用（漂移根因，回归锚点见 test_bootstrap.py）。
    """
    reg = Registry()
    register_builtin_steps(reg)
    register_builtin_oracles(reg)
    mod = importlib.import_module(f"systems.{system}")
    if hasattr(mod, "register"):
        mod.register(reg, env_config, db)
    return reg


def build_token_provider(env_config: dict) -> TokenProvider:
    """从环境配置的 sso / internal_token 段构建 token 提供者。"""
    sso = env_config.get("sso") or {}
    return TokenProvider(sso.get("domain", ""), sso.get("app_id", ""), sso.get("password", ""),
                         internal_token_cfg=env_config.get("internal_token"))


def build_scenario_graph(scenarios_root) -> DependencyGraph:
    """场景库目录 → 全量 DAG（依赖解析需要跨模块可见，故加载全部场景）。"""
    scenarios = load_scenarios(str(scenarios_root))
    return DependencyGraph(scenarios)
