# SpecGuard AgentChat 材料工作流与 purpose 面板装配专项设计

- 日期：2026-08-17
- 状态：设计定稿（v1.0，总控 v1.28 登记）
- 任务区间：T-931 ~ T-936（§4.10 支线）
- 上游：飞书知识图谱支线（§4.9，T-910~T-930）材料池已就位；purposes 体系（T-012/T-013）panels 字段已透出未消费

---

## 1. 背景与问题

### 1.1 三个割裂

1. **材料维护与对话流割裂**：材料上传/解析/登记在独立「材料管理」页（MaterialsPanel，S3 交付），需求面试（requirement_interview purpose）要用材料时必须离开对话去独立页操作——材料池的正确定位是「agent 对话的背景信息源」，入口应该在对话流里。
2. **purpose 与面板割裂**：purposes 定义（agent/purposes/*.md）已有 `panels` 字段、purpose_loader 已解析、`GET /api/agent/purposes` 已透出——但前端 AgentChat 右侧面板 8 个页签（todos/gates/reading/pack/drafts/deps/focus/history）硬编码全量恒显，选择「产品工作台/测试工作台」方向后面板无任何变化。
3. **panels 值与页签实现脱节**：purposes md 里声明的 panels 值（ledger/score/deliver/plan/report）与前端真实页签 id（pack/drafts/deps/focus/history/gates）命名不一致——早期设计意图与实现演化分叉，字段形同虚设。

### 1.2 膨胀风险

页签只增不减（图谱/操作台/信息包/依赖图/提交历史/材料……），全部 purpose 共用一套面板，后期必然过载；新 purpose 接入只能继续硬编码。

## 2. 目标与定位

- **对话即工作台**：需求面试对话内直接上传材料 → 解析登记 → 引用进面试上下文（agent 可读），独立材料管理页不再是必经路径。
- **面板随方向装配**：purpose 决定专用面板集；通用面板恒显；面板清单由「页签注册表 + purposes.panels」声明式驱动，新 purpose 零前端改动接入。
- **防膨胀**：通用/专用分层是硬约束——专用页签只出现在声明它的 purpose 下。

## 3. 关键决策记录

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 面板装配机制 | **前端页签注册表 + purposes.panels 声明式装配**：`tabRegistry = { id: {label, scope: 'universal'\|'purpose', render} }`；实际页签集 = 通用集 ∪ (purpose.panels ∩ 注册表专用集)；purpose 未声明 panels → 仅通用集（向后兼容） | 声明式驱动、新 purpose 零前端改动；注册表是页签 id 的单一事实源 |
| D2 | 通用/专用划分 | **通用**：todos（待办）、drafts（更新与产物）、reading（阅读足迹）、file:*（动态文件页签）、gates（操作台，GateDock 本身跨用途）；**需求侧专用**：pack（信息包）、focus（图谱焦点）、materials（对话材料，本专项新增）；**测试侧专用**：deps（依赖图）、history（提交历史） | 通用=对话过程产物（任何方向都产生）；专用=方向特有工件；gates 归通用因 GateDock 是跨用途接管设计 |
| D3 | panels 值对齐 | purposes md 的 panels 改为真实页签 id：requirement_interview → `[pack, focus, materials]`；test_workbench → `[deps, history]`；未实现的旧值（ledger/score/deliver/plan/report）移入 md 注释作储备 | 字段值必须能在注册表命中；未实现页签声明了也不渲染（∩ 语义天然过滤） |
| D4 | 对话内上传链路 | 复用 S3 既有材料上传/解析 API（MaterialsPanel 同款端点），前端 AgentChat 输入区加「📎 材料」入口；上传成功以 reference 卡片挂入对话上下文（ChatReference 扩展 `'material'` 类型） | 零新后端上传逻辑；references 机制已有，扩展一个类型 |
| D5 | agent 读材料 | 新增 MCP 工具 `read_material`（material_id → 解析产物摘要 + 原文分页摘录），登记进 requirement_interview 的 tools 白名单；既有 material_parse_status/material_extract_topics 保留 | 面试官提问需要引用材料原文做证据；现工具集只能看状态/提话题不能读内容 |
| D6 | MaterialsPanel 不删 | 本专项只建对话流链路；独立页瘦身为储备任务 T-936（对话链路验收后再评估）——M03 入包闸门、六区重组等重操作仍在其上，保守不破坏 | 闸门操作是低频重操作，放对话流里反而挤占；先并行后收敛 |

## 4. 分块设计

### F1 purpose 面板装配（T-931 + T-932）

**purposes md 升级**（T-931）：

```yaml
# requirement_interview.md
panels: [pack, focus, materials]   # 储备：ledger/score/deliver（页签未实现，实现后登记即生效）
# test_workbench.md
panels: [deps, history]            # 储备：plan/report
```

**前端装配**（T-932，AgentChat.tsx SidePanel 改造）：

```tsx
// 页签注册表（页签 id 单一事实源；新页签在此登记 scope）
const TAB_REGISTRY = [
  { id: 'todos',   label: '📋 待办',     scope: 'universal' },
  { id: 'gates',   label: '🎛 操作台',   scope: 'universal' },
  { id: 'reading', label: '📖 阅读',     scope: 'universal' },
  { id: 'drafts',  label: '📝 更新与产物', scope: 'universal' },
  { id: 'pack',    label: '📦 信息包',   scope: 'purpose', cond: () => !!scenarioMeta },
  { id: 'focus',   label: '◎ 图谱',      scope: 'purpose' },
  { id: 'materials', label: '📎 材料',   scope: 'purpose' },   // F2 新增
  { id: 'deps',    label: '🕸 依赖图',   scope: 'purpose' },
  { id: 'history', label: '📜 提交历史', scope: 'purpose' },
] as const;

// 装配：通用恒显 + purpose 声明的专用（∩ 注册表，未知 id 静默忽略）
const purposePanelIds = new Set(purposes.find(p => p.id === pickedPurpose)?.panels || []);
const visibleTabs = TAB_REGISTRY.filter(t =>
  t.scope === 'universal' || purposePanelIds.has(t.id));
```

- 切换 purpose（会话未开时重选）即时生效；已建会话的 purpose 快照随会话（后端会话创建时已快照 panels，前端以会话 purpose 为准）。
- file:* 动态页签不进注册表（跟随打开行为，恒显）。

### F2 对话内材料上传（T-933）

- AgentChat 输入区「📎 材料」按钮 → 文件选择（多选）→ 调 S3 上传端点（specflowApi 现有材料上传 API）→ 解析异步（material_parse_status 轮询沿用独立页逻辑）。
- 上传成功：①材料引用卡片挂入输入区引用链（ChatReference type 扩展 `'material'`，随消息发送进 references）；②「📎 材料」页签列出本会话引用过的材料（标题/解析状态/摘要，复用材料池可读层 title/summary 结构）。
- 面试官侧：references 中的 material id 由 runtime 注入上下文 → agent 用 read_material 按需读原文。

### F3 read_material 工具（T-934）

```
工具名：read_material
入参：material_id（必填）、section（可选：topics|raw|summary，默认 summary）、offset/limit（raw 分页）
出参：解析产物摘要（六区结构概览）或原文分页文本
实现：mcp_server/tools/specflow_pack.py 追加 handler（复用 S3 解析产物读取服务函数）
白名单：requirement_interview.md tools 列表登记
```

## 5. 任务拆解

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| T-931 | 装配-对齐 | purposes panels 值对齐真实页签 id | agent/purposes/*.md + test_specstd/test_agent.py | 两 purpose md panels 改 [pack,focus,materials]/[deps,history]（储备注释保留）；purpose_loader 解析回归；purposes 端点透出断言 | — | 未认领 |
| T-932 | 装配-前端 | SidePanel 页签注册表 + purpose 装配 | AgentChat.tsx | 通用/专用分层渲染；选测试方向时 pack/focus/materials 隐藏、deps/history 保留；未声明 panels 的 purpose 仅通用集；前端 build | T-931 | 未认领 |
| T-933 | 材料-上传 | 对话内材料上传 + 引用类型扩展 | AgentChat.tsx + api.ts（ChatReference 扩 'material'） | 📎 上传入口走 S3 既有端点；上传成功挂引用卡片随消息进 references；「材料」页签列会话引用材料（标题/状态/摘要）；前端 build | T-932 | 未认领 |
| T-934 | 材料-读取 | read_material MCP 工具 + 白名单登记 | mcp_server/tools/specflow_pack.py + purposes md | summary/topics/raw 三视图 + raw 分页；工具白名单登记；MCP 用例 ≥3 | — | 未认领 |
| T-935 | 收口 | e2e + 全量回归 | test_specstd + 前端 build | 上传→引用→agent read_material 贯通（mock LLM）；全量回归 + release_check + build | T-931~T-934 | 未认领 |
| T-936 | 储备 | MaterialsPanel 瘦身评估 | — | 对话链路验收后评估：入包闸门/六区重组是否保留独立页、材料列表是否并入材料池页；产出评估结论，总控人拍板 | T-935 验收 | 储备 |

## 6. 测试策略

- test_agent.py：purposes panels 值解析与端点透出（T-931）
- test_specstd/test_mcp_server.py：read_material 三视图/分页/未知 material_id 诚实报错（T-934）
- 前端 build + lint 不新增 error（T-932/T-933）
- e2e：对话上传（API mock）→ reference 注入 → read_material 返回摘要（T-935）

## 7. 非目标与边界

- 不删 MaterialsPanel、不动 M03 入包闸门语义（D6，T-936 另评估）。
- 不做 ledger/score/deliver/plan/report 页签实现（储备，panels ∩ 注册表语义下实现后登记即生效）。
- 不改 engine 冻结层 / specstd 规范层；无三同步义务。
- 飞书材料池（监听拉取通道）不在本专项——两通道（自动拉取/人工上传）在材料池汇合，各自独立演进。
