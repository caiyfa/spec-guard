---
name: validate-conformance
description: 校验场景 YAML 的格式合规性和 Spec 关联完整性
trigger: 用户需要校验场景格式、检查 covers 锚点、或验证 tool/oracle 引用时
keywords: [校验, 合规, validate, 自检, 检查, 格式检查, 能入库吗, 校验草稿, 覆盖检查]
---
## 合规校验技能

### 校验维度

1. **格式合规（T1-T7）**
   - T1：YAML 语法正确，无解析错误
   - T2：必填字段完整（id / title / covers / flow / verify）
   - T3：flow 步骤类型合法（call / python / verify）
   - T4：tool/oracle 名称已注册
   - T5：依赖声明格式正确（shared / exclusive）
   - T6：契约版本指纹一致
   - T7：save 变量引用链完整

2. **covers 关联完整性**
   - doc.covers 中的 FR ID 必须在工作区 spec.md 中存在
   - 编造的 FR ID 会报 COVER 错误并给出 hint

3. **注册表引用有效性**
   - flow 中的 tool 名称必须在 query_registry 结果中存在
   - verify 中的 oracle 名称必须已注册

### 使用方法

- 使用 `validate` 工具校验 YAML 内容
- 校验结果包含 verdict（PASS/FAIL）和 findings 列表
- 每个 finding 有 level（ERROR/WARN）、rule、message、hint

### 常见问题

- **COVER 错误**：FR ID 不存在 → 检查 spec.md 中的 FR 编号
- **TOOL_NOT_FOUND**：tool 名称未注册 → 用 query_registry 查询可用工具
- **ORACLE_NOT_FOUND**：oracle 名称未注册 → 检查 systems/ 下的 oracles.py
- **VERSION_MISMATCH**：版本指纹不匹配 → 检查 depends_on 中的版本声明
