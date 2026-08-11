---
name: update-scenario
description: 按最新格式要求更新已有测试场景 YAML（格式升级迁移、requires 声明补全、修复校验告警）
version: 1.0.0
author: platform-team
depends_tools: [read_scenario, list_scenarios, validate, scan_compliance, read_spec, suggest_deps, edit_dependency]
trigger: 用户要求更新/迁移已有场景、格式规范升级后存量场景合规、scan_compliance 发现缺口、修改已入库场景
keywords: [更新, 修改, 迁移, 升级, 改造, 存量场景, 格式升级, 补 requires, 修复校验, 场景合规, 更新草稿]
---
## 场景更新技能

### 核心流程（更新已有场景必须走草稿→入库链路，禁止直接改 scenarios/）

1. **扫描缺口**：使用 `scan_compliance` 获取全库格式合规缺口清单
   （missing_accounts/missing_env/missing_upstream = flow 用到但 requires 未声明；
   extra_requires = 冗余声明；t8_violations = 上游引用不在 depends_on）
2. **读原文**：使用 `read_scenario`（参数 scenario_id）读取场景当前 YAML
3. **最小 diff 改写**：只改动需要更新的部分——
   - 补 `requires` 段（格式 2.3.0）：accounts/env/upstream 与 flow 实际引用一致
   - 修复 T8 违规：requires.upstream 必须在 depends_on（或移除声明）
   - **保留原文的中文注释、doc 段、其他步骤结构**——不是重写整个文件
4. **写入草稿**：使用 `write_draft` 写入 drafts/（文件名与场景同名，如 TL-RC-014.yaml；
   已存在同名草稿时先删除旧草稿或用 patch 追加）
5. **校验**：使用 `validate`（content=草稿内容）确认 PASS，无 T8/REGISTRY/COVERS ERROR
6. **依赖复核（必做）**：调用 `suggest_deps`（带 scenario_id）复核依赖边——更新引入
   新上游引用（{{上游ID.*}}）或改动 save 变量后，依赖关系可能变化；采纳建议写入草稿
   depends_on 后重新 validate；存量依赖边若已变化（如 save 改名），一并修正
7. **覆盖入库**：使用 `promote_draft`（filename, module, replace=true）——
   replace=true 覆盖同名场景（原文件自动备份，校验/门禁失败自动回滚，成功即 git 可 diff）
8. **确认结果**：核对返回的 scenario_id 与 target；发布门禁失败时按 gate_output 修正后重试

### 格式要点（2.3.0 起）

- requires 声明 flow/verify 实际引用的依赖，**与静态提取一致**（scan_compliance 会查不一致）：
  ```yaml
  requires:
    accounts: [platformNoCorp]      # flow as:/fetch_permission 引用的账号别名
    env: [resource_code]            # {{env.*}} 引用的环境键（vars.xxx 子键用点号）
    upstream: [IS-PREP-001]         # {{上游ID.*}} 变量来源场景（必须在 depends_on！）
  ```
- 账号别名必须是目标环境 env.{env}.yaml accounts 段已定义的真实 AD 账号（拿不准向用户确认）
- requires 不进契约指纹——补声明无需 bump version；但改了 produces/save/covers 必须
  bump version（T6 校验会拦）
- 更新后契约指纹变化的场景，scan_compliance 不会提醒 version——用 validate 的 T6 检查
- **插值只允许四种形态**（T-318/T-319）：`{{fn.*}}` / `{{env.*}}` / `{{上游ID.*}}` /
  本场景 save 与 set_var vars 裸名。存量场景里的 `{{random:N}}`（Apifox 语法）必须改为
  `{{fn.uuid_short}}`——validate 报 UNKNOWN_TPL ERROR 即为此类
- 存量场景的 `body:` 键（2.1.0 前废弃）改为 `json:`——validate 报 BODY_KEY WARN 即为此类

### 批量更新

- 缺口清单可能很大（如 2.3.0 升级后全库 90 场景缺 requires）——**逐场景更新**，
  每批 5-10 个场景走完「读→改→写→校验→promote」再继续，避免一次性大改引入错误
- 更新过程中 validate 报 T4/T8/COVERS/UNKNOWN_TPL/BODY_KEY 时停下修正，不要跳过

### 信息不足时

- 不确定场景的模块归属：用 `list_scenarios` 查 module；promote 的 module 参数必须与
  原场景所在模块目录一致
- 不确定账号别名是否真实存在：向用户确认或参考环境配置页
