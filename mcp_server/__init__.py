"""mcp_server — SpecGuard MCP 工具层（T-982 收敛后）。

stdio 单模 MCP server，list_tools 可见 39 个工具：
  - 对内 24 个合并工具（action 参数化，原 77 个碎片化工具收敛而来；
    元数据 tool_meta 声明 side_effect/domain/rbac/doc_track，下游全部派生）
  - S8 open/ 15 个对外开放面（L0 只读契约，名称不变）
工具注册单一入口：server.build_tool_modules()（runtime 复用，info_pack 仅对内）。
"""
