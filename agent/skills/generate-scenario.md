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
- **call 请求体一律用 `json:` 键**（2.1.0 起）：`json: {tagName: x}`；`body:` 是 2.1.0 前
  废弃键，引擎只认 `json:/form:/urlencoded:/raw:/file:`（body_type 推断），写 `body:` 会
  静默丢请求体（validate 会报 BODY_KEY WARN——生成后务必 validate 确认无此告警）
- **声明执行依赖（格式 2.3.0 起，预检扫描数据源）**：在机器读层加 `requires` 段，声明
  flow/verify 用到的账号别名、环境键与跨场景变量引用（缺失 → 执行前预检弹窗预警）：
  ```yaml
  requires:
    accounts: [platformNoCorp]      # flow as:/fetch_permission 引用的账号别名
    env: [resource_code]            # {{env.*}} 引用的环境键（vars.xxx 子键用点号）
    upstream: [IS-PREP-001]         # {{上游ID.*}} 变量来源场景（须已在 depends_on）
  ```
  `accounts` 别名必须是目标环境 `env.{env}.yaml` 的 `accounts` 段已定义的真实 AD 账号；
  拿不准环境有没有该账号时，向用户确认或参考环境配置页。requires 不进契约指纹，
  增删无需 bump version；未声明时预检扫描器会从 flow 文本静态兜底提取。

### 信息不足时

- 主动向用户提问，明确缺失的信息
- 用户确认补充文件后，使用 `add_to_info_pack` 将文件加入基础信息包
- 使用 `read_info_pack` 重新读取更新后的文件
