"""sg_core — SpecGuard 共享内核（T-975 依赖倒挂翻正）。

承载被 mcp_server / agent / workbench 三方共同消费的服务实体：
用户与数据层（user_store/crypto/ledger_store 等）、草稿入库流程（draft_promote）、
格式规范导出（format_spec）、经验飞轮（experience_store）等。

依赖方向（强制单向，release_check 环检查兜底）：
    sg_core → specstd / engine / stdlib
    mcp_server → sg_core；agent → sg_core；workbench.backend.services → sg_core
    sg_core 不得 import mcp_server / agent / workbench 任何模块。

workbench/backend/services/ 下同名模块是兼容 shim（仅再导出），
存量 import（`from services import X`）无需改动；新代码直接用 sg_core。
"""
