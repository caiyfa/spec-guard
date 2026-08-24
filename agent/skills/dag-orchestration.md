---
name: dag-orchestration
description: 在对话中编排场景依赖 DAG（加边/删边/补孤节点/修漂移），Agent 会话是 DAG 编排的主入口
version: 1.0.0
author: platform-team
depends_tools: [scenario(action=list), scenario(action=read), scenario(action=check_dag), scenario(action=suggest_deps), scenario(action=edit), scenario(action=next_id)]
trigger: 用户要求编排场景依赖、调整 DAG 拓扑、补依赖边、修复漂移/孤节点、按计划组织场景依赖时
keywords: [编排, DAG, 拓扑, 依赖, 加依赖, 删依赖, 补边, 补依赖, 依赖边, 连线, 挂到, 依赖关系, 孤节点, 依赖建议, 漂移, 上下游, 依赖闭包]
---
## DAG 编排技能（Agent 会话 = 编排主入口）

场景依赖关系沉淀在 `scenarios/**/*.yaml` 的 `depends_on` 段（下游声明上游）。本技能覆盖
**库内场景**的依赖编排（已入库场景改依赖边用 `scenario(action=edit)` 文本外科手术，禁止直接改
scenarios/ 文件；草稿阶段把 depends_on 写进 draft YAML，见 generate-scenario 技能）。

### 核心流程（先读现状 → 确认目标 → 建议 → 落地 → 复核 → 汇报）

1. **读现状**：先调用 `scenario(action=check_dag)`（include_drafts=false）获取当前库拓扑——
   拓扑执行序、循环依赖、DRIFT/ORPHANED 版本仲裁、孤例清单。有 DRIFT/orphan 先向用户指出
2. **明确编排目标**：向用户复述本次要做的边（如「PP-RC-008 增加对 IS-TG-001 的依赖，
   mode=shared」），**批量改动超过 3 条边时必须先列清单请用户确认**，不擅自批量改
3. **依赖建议（确定性优先）**：拿不准该连哪些边时用 `scenario(action=suggest_deps)`（确定性引擎扫描
   全部 `{{...}}` 插值匹配 save 生产者，输出建议边含理由与置信度，已声明/传递依赖、
   自依赖、会成环的自动剔除）——**不要肉眼扫插值猜依赖**。采纳后：
   - 库内场景 → `scenario(action=edit)` 落地
   - 建议被拒时向用户说明理由，不静默丢弃
4. **落地单条边**：`scenario(action=edit, op=add/remove, scenario_id=下游, dep_id=上游,
   mode=shared|exclusive)`——自带守卫：自依赖拒绝、目标不存在拒绝、循环依赖 409、
   版本期望自动按上游推导 `^主版本`。remove 后若场景仍在插值引用该上游，提示用户
   该场景会出现运行时「变量未定义」（诚实提示，不擅自改场景内容）
5. **复核（必做）**：每条边落地后（或一批完成后）再跑 `scenario(action=check_dag)` 确认无环、
   无新增 ORPHANED、无新增 DRIFT；有则立即修正或回滚（remove 刚加的边）
6. **汇报**：输出变更前后拓扑对比（哪些边新增/移除、DRIFT/orphan 数量变化、
   当前环状态），不输出整库 YAML 刷屏

### 常见编排场景（按用户意图对号入座）

- **补孤节点**：`scenario(action=check_dag)` 显示孤例（无上游）→ `scenario(action=scenario(action=suggest_deps), target_id=孤节点ID)`
  出建议 → 逐条确认后 `scenario(action=edit)` 落地 → `scenario(action=check_dag)` 复核清零
- **修漂移**：DRIFT 是「下游声明版本 ≠ 上游实际版本」→ 先 `scenario(action=read)` 核对下游
  声明与上游实际产出，确认是版本过期 → `scenario(action=edit)` 重加同一条边（版本期望
  自动更新为上游当前版本）；orphan 是上游已不存在 → 向用户确认后 remove 或改挂
  真实存在的上游，**禁止改 YAML 强行匹配**
- **计划对齐**：按测试计划 `filter.scenarios` 组织依赖时，用 `scenario(action=list)` 确认
  场景存在性，只对库内场景落地；计划本身的调整不在本技能范围
- **exclusive 语义**：写型消费（上游产出被下游修改/清理）用 `mode: exclusive`
  （画布上为动画边 + 多实例重跑语义）；只读共享用默认 shared。拿不准向用户确认

### 硬约束

1. 只编排**已入库**场景；草稿的 depends_on 写进 draft YAML（generate-scenario 流程）
2. 每条边落地前向用户说明（单条 1 边可直接做，批量 >3 边必须先确认）
3. 落地后必跑 `scenario(action=check_dag)` 复核，禁止「改完不验」直接宣称完成
4. `scenario(action=edit)` 报 409 环时：如实告知成环路径，由用户决定改哪条边，不绕路
5. 不修改场景的 flow/verify/save 内容——本技能只管依赖边；涉及场景内容变更
   交给 update-scenario / generate-scenario 技能
6. 用户要求「跑一下/验证」时才用 `scenario(action=run)`（真实环境联网、产生真实数据，
   执行前先告知用户），且须在 `scenario(action=check_dag)` 确认拓扑无环之后

### 信息不足时

- 不知道上游场景 ID：`scenario(action=list)` 查（含 title/module）
- 不确定该连 shared 还是 exclusive：问用户该场景是否写型消费
- 不确定某条边是否需要：`scenario(action=suggest_deps)` 出证据（哪个插值引用、谁生产），不猜
