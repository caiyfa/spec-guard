"""TDM 系统适配包：向引擎注册 TDM 专属的步骤类型、断言器与数据提供者。"""

from systems.tdm.config import load_env


def register(registry, env_config, db=None):
    """引擎注册钩子。

    Args:
        registry: engine.registry.Registry
        env_config: load_env() 加载的环境配置 dict
        db: engine.db_oracle.ReadOnlyDb（可为 None，DB 不可用时相关能力降级为 SKIP）
    """
    from systems.tdm.emp_pool import EmpPool
    from systems.tdm.queries import TdmQueries
    from systems.tdm import steps as tdm_steps
    from systems.tdm import oracles as tdm_oracles

    queries = TdmQueries(db) if db else None
    pool = EmpPool(db) if db else None

    registry.provider("queries", queries)
    registry.provider("emp_pool", pool)
    tdm_steps.register_steps(registry, env_config, pool, queries)
    tdm_oracles.register_oracles(registry)
