"""mcp_server — SpecGuard MCP 工具层。

stdio + SSE 双模 MCP server，暴露 5 组工具：
  - spec_reader: read_spec / list_spec_files
  - scenario_tools: list_scenarios / read_scenario / next_scenario_id
  - registry_query: query_registry
  - draft_writer: write_draft
  - validator: validate
"""
