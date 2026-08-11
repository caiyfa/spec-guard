---
name: fabricate-test-data
description: 为缺口 FR 制造测试数据准备场景（IS-PREP 数据实例草稿）
version: 1.0.0
author: platform-team
depends_tools: [read_spec, query_registry, next_scenario_id, write_draft, validate]
trigger: 用户需要制造测试数据、准备数据实例、生成 IS-PREP 场景、数据制造时
keywords: [数据制造, 数据准备, IS-PREP, 测试数据, 造数据, 准备数据, 工号池, data-contract]
---
## 测试数据制造技能

> 依据 M08 §5.3：输入 spec 锚点 + delta 场景契约 → 设计数据拓扑 → 生成 IS-PREP
> 数据实例草稿（batch 0 候选）；**产物一律走三闸**，promote 必须三闸全过（铁律 3）。

### 核心流程

1. **查缺口**：`query_coverage_gaps` 确认目标 FR 是否为缺口（草稿不计覆盖）
2. **读锚点**：`read_spec` 带 `anchor=FR-xxx` 只取目标锚点章节——提取数据前置条件
   （如「作废需 COMPLETED 会话」「名单需 3 名快照人员」）
3. **复用优先**：`list_scenarios` 按 IS-PREP 前缀检索既有数据实例——covers 命中
   目标 FR 的既有实例**优先复用/参数化，不新造**（评审指标：复用率）
4. **查适配包**：`query_registry` 确认可用 tool/oracle；数据来源只允许
   `systems/{system}/` 适配包资产（emp-pool 工号池 / oracles.py 注册断言器），
   **引擎零改动**（铁律 5）
5. **生成草稿**：`fabricate_data` 编排入口（确定性骨架：data_contract
   声明块 + source_delta 挂链）——之后按 spec 锚点补全 flow/verify：
   - `data_contract.provides` 必须含 activity（实例完整性）
   - members 引用 emp-pool 角色必须存在于 `emp-pool.yaml`
   - 独占实例（isolation: exclusive）必须 cleanup: teardown 回收
   - `depends_on` 版本期望用 `^0`（活跃 delta 快照期宽容）
6. **自验**：`validate` + 数据校验器（fabricate 返回 validation 报告）；草稿态
   `run_scenario` 试跑 + `db_evidence` 校对（SELECT-only）
7. **上报评审**：产物是草稿——向用户说明「需走三闸（人工评审→格式校验→发布门禁）
   后入库」，**不自行 promote**

### 硬约束

- 产物 100% 草稿态落地（write_draft 自动登记三闸 + gate2 自动校验），无一绕过
- 不直接写业务库——数据由场景执行经适配包 tool 创建，Agent 只产场景 YAML
- 数据校验器硬拒（实例不完整/角色不在池/隔离非法/版本不可仲裁）→ 不落盘，改设计
- 已有可复用实例时不新造（复用优先是确定性规则，不是建议）
