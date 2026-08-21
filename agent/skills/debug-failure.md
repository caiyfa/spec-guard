---
name: debug-failure
description: 分析运行报告中的失败场景，定位根因并给出修复建议
version: 1.0.0
author: platform-team
depends_tools: [attribution(action=report), attribution(action=log), attribution(action=case), attribution(action=failures), spec(action=read), scenario(action=read), validate]
trigger: 用户需要分析测试失败、排查断言差异、或调试场景运行错误时
keywords: [失败, 调试, 排查, 归因, 为什么, 报错, 运行失败, 失败原因, 断言失败, 怎么挂了, debug, 挂了]
---
## 失败分析技能

### 分析流程

1. **定位失败现场（K-052 任务号体系）**：
   - 已知场景名 → 用 **attribution(action=failures)** 查它最近在哪些任务号（EX-xxx）失败、失败原因摘要
   - 已知任务号 → 直接进第 2 步
2. **读取日志**：用 **attribution(action=log)** 按任务号读取执行日志（output.log）：完整调用链，
   重点看 `[SpecGuard] METHOD path → status | trace=...` 行——trace_id 是网关全链追踪 ID
3. **读取报告**：使用 `attribution(action=report)` 读取运行报告
   - 提取失败场景列表
   - 获取每个失败场景的断言差异和环境探测结果

4. **读取场景**：使用 `scenario(action=read)` 读取失败场景的 YAML 内容
   - 分析 flow 步骤和 verify 断言
   - 检查 save 变量和插值路径

5. **读取需求**：使用 `spec(action=read)` 读取相关需求文档
   - 确认预期行为与实际结果的差异

6. **DB 证据**：使用 `attribution(action=db)` 查询数据库状态
   - SQL 必须为 SELECT/SHOW/DESCRIBE/EXPLAIN（只读）
   - 校对断言时的数据库实际状态

7. **根因分析**：综合以上信息判断失败原因
   - 数据问题：测试数据缺失或不符预期
   - 环境问题：网络/DB/SSO 不可达
   - 场景问题：YAML 逻辑错误、断言条件错误
   - 权限问题：账号无权限访问目标资源

8. **修复建议**：给出具体的修复方案
   - 指明需要修改的 YAML 行号和修改内容（需要时可用 validate 验证修复后的 YAML）
   - 需要改草稿时用 draft(action=write)（写 drafts/ 草稿，不经用户确认不直接入库）
   - 如果是数据问题，说明需要准备什么测试数据
   - 如果是环境问题，说明 SKIP 语义（不报 FAIL）

### 注意事项

- 归因报告里必须带上任务号（EX-xxx），方便用户按号查证
- 修复建议以文本形式返回给用户，由用户确认后落地
- attribution(action=db) 只支持 SELECT/SHOW/DESCRIBE/EXPLAIN，不可修改数据

### SKIP vs FAIL 语义

- **SKIP**：测试数据缺失/账号未配置 → 环境问题，不报 FAIL
- **BLOCKED**：上游场景失败 → 依赖问题，不报 FAIL
- **FAIL**：断言不通过 → 真正的测试失败

绝不能把环境问题报成 FAIL。
