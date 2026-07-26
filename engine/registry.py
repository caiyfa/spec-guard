"""注册中心：步骤处理器 / 断言器 / 数据提供者三张注册表。

引擎内置注册通用能力（call / set_var / db_query），
被测系统通过 systems/{system}/__init__.py 的 register(registry, ctx) 钩子
注册自己的步骤类型与断言器，实现引擎与业务解耦。
"""


class Registry:
    def __init__(self):
        self.step_handlers = {}
        self.oracles = {}
        self.data_providers = {}

    # ── 注册 ─────────────────────────────────────────────
    def step(self, name, handler):
        """注册步骤处理器。handler 签名: (step_body, rctx, ns, record) -> saved_value"""
        self.step_handlers[name] = handler

    def oracle(self, name, fn):
        """注册断言器。fn 签名: (params, rctx, ns, record) -> None（失败抛 AssertionError）"""
        self.oracles[name] = fn

    def provider(self, name, provider):
        """注册数据提供者（如工号池）"""
        self.data_providers[name] = provider

    # ── 获取 ─────────────────────────────────────────────
    def get_step(self, name):
        if name not in self.step_handlers:
            raise KeyError(f"未注册的步骤类型: {name}（已注册: {sorted(self.step_handlers)}）")
        return self.step_handlers[name]

    def get_oracle(self, name):
        if name not in self.oracles:
            raise KeyError(f"未注册的断言器: {name}（已注册: {sorted(self.oracles)}）")
        return self.oracles[name]

    def get_provider(self, name):
        if name not in self.data_providers:
            raise KeyError(f"未注册的数据提供者: {name}")
        return self.data_providers[name]

    def has_step(self, name):
        return name in self.step_handlers
