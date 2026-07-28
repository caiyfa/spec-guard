---
name: generate-scenario
description: 从需求文档生成 SpecGuard 测试场景 YAML
trigger: 用户需要创建新的测试场景、从 Spec 文件生成用例、或使用场景创建向导时
---
## 场景生成技能

### 核心流程

1. **读取需求**：使用 `read_info_pack`（如有 scenario_id）或 `read_spec` 读取需求文档
2. **获取 ID**：使用 `next_scenario_id` 获取下一个可用场景 ID
3. **查询注册表**：使用 `query_registry` 确认可用的 tool 和 oracle
4. **参考已有场景**：使用 `list_scenarios` 和 `read_scenario` 查看同类场景的结构
5. **生成 YAML**：按照格式规范生成场景 YAML
6. **校验**：使用 `validate` 工具校验生成的 YAML
7. **写入草稿**：校验通过后使用 `write_draft` 写入 drafts/ 目录

### 格式要点

- `doc.covers` 中的 FR ID 必须在工作区 spec.md 中存在
- `flow` 中的 tool 名称必须已注册
- `verify` 中的 oracle 名称必须已注册
- 字段命名：集合字段用 `List` 结尾，字段一律驼峰
- 插值：`{{a.b.c}}` 点号路径，类型保留

### 信息不足时

- 主动向用户提问，明确缺失的信息
- 用户确认补充文件后，使用 `add_to_info_pack` 将文件加入基础信息包
- 使用 `read_info_pack` 重新读取更新后的文件
