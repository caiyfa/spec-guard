# SpecGuard Skill 体系与 MCP 体系建设分析

> 架构决策分析报告 · 面向平台负责人与架构组 · 2026-07
> 输入：R1《内部现状与缺口简报》、R2《外部生态扫描简报》、M12《多智能体运行时与平台基建》
> 回答两个问题：**是否需要建立成体系的 skill 管理（可导入外部成熟 skill）？是否需要成体系的 MCP 体系？**

---

## 1. 结论摘要

**问题一：是否需要成体系的 skill 管理？——需要，且现在就做「轻量体系化」。** 具体口径：skill 文件格式对齐 Agent Skills 开放规范（该规范已成 40 个平台支持的事实标准，且与自家 `agent/skill_loader.py` 同构，对齐成本极低）；在格式之上自建注册表、版本字段、入库审查门禁、运行时权限过滤四件治理件。外部成熟 skill 的导入走「适配层 + 审查管线」小步开放——静态扫描、沙箱试跑、人工评审、白名单入库、版本快照锁定，**不自建 skill 市场、不做自动评分平台**。

**问题二：是否需要成体系的 MCP 体系？——需要治理化，不需要平台化。** 具体口径：保持 `mcp_server/server.py` 单 stdio server、单 `TOOL_MODULES` 注册点不动摇，补齐四件治理件——工具副作用分级（`side_effect` 声明式元数据 + 运行时校验）、工具级权限（三层交集白名单，与 M12 §5.3 一致）、统一调用审计日志、四步挂载规范（含 `info_pack.py` 补票）。外部 MCP server 接入（MCP client 能力 + 迷你 gateway 策略）列为**储备项**，触发条件驱动：禅道生态出现厂商背书的可信 server、或平台工具数翻倍（>50）、或出现第二个外部系统接入需求时启动。

**分期剂量**：F3 随 purpose 会话模型落地权限过滤与审计骨架；G1 落地 profile 注册表、白名单三层交集、skill 格式对齐与挂载规范；G2-G3 补齐审查管线与副作用分级运行时校验；储备项不排期、只挂触发条件。当前规模（3 skill / 24 工具 / 5 个规划 Agent）下，skill 版本库、多 server 编排、独立分发市场、质量评估平台均属过度工程（与 R1 §5 初步判断一致），本报告将其显式排除并给出再启动信号。

---

## 2. 现状盘点（基于 R1 §1）

| 机制 | 实现位置 | 能力快照 | 治理现状 |
|---|---|---|---|
| skill | `agent/skill_loader.py` + `agent/skills/`（generate-scenario / validate-conformance / debug-failure） | YAML frontmatter（temperature/tools/description/trigger）+ Markdown 正文，注入 `<skills>` XML 块；30s TTL 热加载 | 无版本、无权限（tools 声明运行时不强制）、无审计、无注册表 API |
| mode | `agent/mode_loader.py` + `agent/modes/`（5 个） | 同款 frontmatter + 30s 热加载 | **移除中**（specflow 硬性前提 4），终态由 purpose 替代，治理问题随移除消失 |
| purpose | 设计已定未实现：`agent/session.py` 会话模型增 `purpose` 创建期字段 | 持久化、不可变、创建即锁定；驱动提示词装配/工具可见集/面板/产物归属 | 含 RBAC 过滤与归属留痕设计；初期仅 `requirement_interview`/`test_workbench` 两值 |
| MCP 工具层 | `mcp_server/server.py`（stdio）+ `tools/` 8 模块 24 工具 | docstring 即工具说明；Agent 与 Qoder 等宿主经 stdio 操作仓库 | 纯读纪律是约定非守卫；无副作用分级、无工具级权限、无平台审计 |
| 注册机制 | ① `TOOL_MODULES` 列表（唯一注册点）② `engine/tool_registry.py` + `tools/live_registry.py` | 单 server 单注册点，`list_tools` 可回归计数 | 无版本/依赖概念；`info_pack.py` 已实现未挂载（补票欠账）；无外部 server 接入能力 |

一句话概括：**加载机制成熟（热加载是资产），治理机制空白（注册表/版本/权限/审计皆缺）**。mode 机制的治理债务不必还——它正在消亡，投入应全部流向 purpose 终态。

---

## 3. 缺口与需求张力分析

需求侧的证据是具体的（R1 §2）：G1-G3 要落地 5 个专业化 Agent——📎材料包解析（M03，闸门：人拍板入台账）、🌐图谱索引（M11，闸门：可删可重建）、🧬测试数据制造（M08，闸门：数据校验器）、🔬失败归因（M09，闸门：人定性才生效）、📊故事点评估（M06，闸门：产品确认回写）；横切还要新增 specflow_pack、graph_index、specflow_refs、lineage、zentao 等 MCP 工具模块，工具数将从 24 向 30+ 走。每个新 Agent 都是「profile + skills + 工具白名单」三件套落盘即生效。

而供给侧仍是「文件约定」级治理（R1 §3），张力集中在五点：

1. **权限**：frontmatter 声明 tools 但 `agent/runtime.py` 分发前不过滤。5 个 Agent 各带闸门后，「data-maker 拿不到回写工具、story-point 拿不到测试数据工具」必须是运行时强制而非提示词自觉——这正是 M12 §5.3 三层交集白名单要补的位，属**必须有**。
2. **注册表**：M12 已为 profile 建 `GET /api/agent/profiles`，skill 层没有对应查询面；skill 与 profile 的绑定（profile frontmatter 的 `skills:` 字段）需要注册表才能校验悬空引用。
3. **版本**：skill 升级无变更留痕、无法声明与 MCP 工具的兼容关系；外部规范 `version` 字段仍是提案（R2 ①），不能等，须自建。
4. **审查门禁**：「文件落盘即生效」对内部作者尚可接受，对外部 skill 是敞口——36% 公开 skill 含注入（R2 ①），没有入库评审通道就不能谈导入。
5. **审计**：MCP 工具调用无统一留痕；audit 模块是业务工具不是平台审计。闸门体系（铁律 1/3）要求「谁在哪个会话调用哪个工具写了什么」可查，否则「人拍板」事后无法追溯。

反向证据同样成立：3 skill / 24 工具的规模下，多 server 编排、独立分发、质量评估平台没有需求证据——没有任何一个 Agent 或场景需要它们。故结论不是「要不要体系化」，而是「体系化的剂量」：治理件必须有，平台件暂缓。

---

## 4. 外部生态可复用性评估（基于 R2）

**Skill 格式：低成本可复用，应对齐。** Agent Skills 开放规范 2025-12 由 Anthropic 以开放标准发布、Agentic AI Foundation 托管，截至 2026-06 约 40 个平台支持（来源：https://agentman.ai/blog/agent-skills-ecosystem-report-2026 ）。其最小要求——frontmatter `name`（≤64 字符、与目录名一致）+ `description`（≤1024 字符）+ Markdown 正文、未知字段忽略、三级渐进披露（来源：https://agentman.ai/blog/build-your-first-agent-skill-skillmd-anatomy ）——与自家 `skill_loader.py` 的 frontmatter+md 同构。对齐工作≈四项小改：强制 name/description 校验、忽略未知字段、目录名=name、先加载 description 再按需加载正文。对齐的直接收益：未来导入外部 skill 零格式转换，且规范明确的「frontmatter 勿用 `<>`」（注入风险）可直接进校验器。

**生态信任根缺失：导入必须自建审查管线。** 规范无签名、无 lockfile、无版本 pinning（提案讨论中，来源：https://github.com/agentskills/agentskills/discussions/420 ）；2026 年审计在被测 skill 中发现 36% 含 prompt injection，公开 skill 平均质量 6.2/12、仅 top-quartile 真正提升 agent 表现（来源：https://www.manifold.security/blog/ai-agent-skill-registry-supply-chain-security ）。同时业界已有可参考的雏形：`moonrunnerkc/skillcheck`（frontmatter 校验 + token 预算检查的质量门）、openagentskill.com（审计评分注册表）（来源：https://github.com/appssemble/awesome-skill-md 、https://www.openagentskill.com ）。结论：审查管线自建、工具思路可抄，市场不建。

**MCP 治理：词汇吸收，成品不引入。** MCP Gateway 作为企业治理标准答案已成型（SSO/OAuth 2.1 + OBO、action 级 RBAC、「Agent X 只能用只读工具」策略、审计日志、批准 server 白名单；来源：https://www.requesty.ai/blog/mcp-gateway-comparison-2026-enterprise-scalability-security ）；协议内建 `ToolAnnotations`（readOnlyHint/destructiveHint 等）是正式字段但只是提示性 hint、不构成安全边界（来源：https://sunpeak.ai/blogs/testing-mcp-tool-annotations/ ）。24 工具单 server 远未到 N×M 问题，成品 gateway 不必引入；但「只读/写分级、身份传递、审计」这套词汇应吸收进自有 server，且只读必须在自家运行时强制而非信 server 自述。

**禅道：不可直接用，zentao-cli 通道保持。** 现有 `ruan11223344/zentao-mcp` 为个人项目、LobeHub 标注 "Unvalidated"、凭证走 .env 明文（来源：https://lobehub.com/mcp/ruan11223344-zentao-mcp ）；对比 Jira 有 Atlassian 官方远程 server（来源：https://www.gamut.so/mcp/project-management/atlassian ），禅道是赛道短板。当前 zentao-cli 子进程通道是有意的边界控制（R1 §3），保持不动；M06 的「story/bug 创建与点数回写不暴露给 MCP」维持个案执行，并泛化为通则（见 §6）。

---

## 5. Skill 体系方案设计

### 5.1 格式规范对齐（低成本，G1 完成）

在 `agent/skills/` 与 `skill_loader.py` 上落实四条，全部与 Agent Skills 开放规范兼容：

- `name`、`description` 强制校验（长度上限同规范），缺失即拒绝加载并告警；
- 目录/文件名与 `name` 一致（多文件 skill 用目录形态，目录名=name）；
- 未知 frontmatter 字段一律忽略不报错（宽容解析，应对规范仍在变动，呼应 R2 风险 7）；
- 渐进披露：装配 system prompt 时先注入全部 skill 的 name+description，正文按 profile `skills:` 声明按需注入——顺带获得 token 预算控制能力；
- 校验器固化「frontmatter 禁用 `<>`」，注入红线进 CI。

现有 3 个 skill 仅需补齐 name/description 即自然合规，无迁移成本。

### 5.2 Skill 注册表与元数据

- frontmatter 增加自建字段：`version`（SemVer，自建不等规范提案）、`author`、`depends_tools`（声明依赖的 MCP 工具，供兼容性检查）。字段落在规范的宽容区内（未知字段被忽略），未来规范若正式收纳 version，无缝切换。
- 注册表查询面：扩展 `GET /api/agent/profiles` 的返回，或在 `agent/agents/` 同款机制下增加 skills 清单端点，返回 name/version/description/绑定 profile/depends_tools；注册表数据源即目录扫描 + frontmatter 解析，保持「落盘即生效、30s 可见」的热加载资产不变。
- 绑定关系：profile frontmatter 的 `skills:` 字段为唯一绑定通道；purpose 驱动默认 profile（M12 §4.3），skill 随之间接挂到用途。注册表校验悬空引用（profile 声明了不存在的 skill）为加载期错误。

### 5.3 权限：三层交集白名单运行时强制

与 M12 §5.3 口径完全一致，不发明新机制：

```
resolve_tools(session) = TOOL_REGISTRY ∩ profile.tools ∩ rbac_visible_tools
```

skill frontmatter 的 `tools` 声明作为**第二重收窄**：skill 被注入时，其声明工具集与 profile 白名单再取交集，skill 声明超出 profile 白名单的部分不生效并在审计日志记 WARNING。越权调用由 `runtime.py` 分发前确定性拒绝，不依赖提示词自觉（铁律 2 的运行时形态）。

### 5.4 外部 skill 导入审查管线

五级管线，全部入库动作留痕（呼应铁律 1/2/3：确定性校验打底、人拍板收口）：

1. **静态扫描**（确定性）：注入模式、frontmatter `<>`、捆绑可执行脚本、超 token 预算——参考 skillcheck 思路自建脚本；扫描器 warn 误报率约 42%（R2 风险 5），故扫描结果只分级、不自动阻断；
2. **沙箱试跑**：在隔离工作区用 mock 工具集跑样例输入，观察工具调用序列是否越界；
3. **人工评审**：架构组双人 review，重点看 description 是否诱导工具误选（tool poisoning 的 skill 形态）；
4. **白名单入库**：登记来源 URL、作者、评审人、评审日期，落 `agent/skills/external/{name}/`；
5. **版本快照锁定**：入库即冻结源码快照 + 记录 version；**禁止外部 skill 走 30s 热更新通道**——升级 = 重新走管线（防 rug-pull，R2 风险 2）。

导入节奏：小步开放，首批只考虑厂商官方仓（anthropics/skills 等）中与现有三 skill 互补的条目；生态质量数据（平均 6.2/12）说明多数公开 skill 不值得导入，宁缺毋滥。

### 5.5 明确不做

- **不自建 skill 市场/分发中心**：内部 git 跟代码走已够用（R1 §3），无跨仓分发需求证据；触发条件：出现第二个部署 SpecGuard 的团队且需要共享 skill 时。
- **不做自动评分平台**：无质量基准数据集，评分无锚点；触发条件：skill 数 >20 且出现「同场景多 skill 选型」问题时，先建人工回归集再谈自动化。

---

## 6. MCP 体系方案设计

### 6.1 保持单 server 单注册点

`mcp_server/server.py` stdio 单 server、`TOOL_MODULES` 唯一注册点的架构不变（与 M12 §5.2 一致）。四步挂载规范固化为 checklist 并补票：

1. 新建 `mcp_server/tools/{module}.py`，每工具一个纯函数，docstring 即工具说明；
2. `TOOL_MODULES` 追加模块名（唯一注册点）；
3. 副作用声明与分类纪律（见 6.2）；
4. `python -m mcp_server.server` 启动后 `list_tools` 计数回归。

**补票项**：`info_pack.py` 挂入 `TOOL_MODULES`（M12 G2 验收口径：计数与实际挂载一致）。「实现了但没进体系」这类欠账由第 4 步回归防止再发。

### 6.2 工具分类治理：side_effect 分级

将 R1 §3 的缺口元数据化，吸收 ToolAnnotations 词汇但在自家运行时强制（不信自述，R2 风险 4）：

- 每个工具声明 `side_effect: none | draft | external-write`（docstring 声明起步，随 G2-G3 落为结构化元数据）；
- **运行时校验**：`none` 级工具强制纯读——执行前后对仓库状态做指纹比对（或经只读文件句柄层），产生副作用即报错并记审计；这把「校验/查询类工具纯读」从约定升级为守卫（铁律 2）；
- `draft` 级工具（draft_writer/audit）产物一律草稿态，闸门口径在声明中注明，与 profile `gate` 字段联动校验；
- `external-write` 级默认为空集——见 6.3。

### 6.3 「外部写不进 MCP」从个案升为通则

M06 的个案决策（story/bug 创建与点数回写不暴露给 MCP，触外部系统的写必须人在 UI/REST 确认）泛化为平台通则：**任何触外部系统的写动作不得经 MCP 工具暴露给 Agent**；外部系统的读（如 specflow_refs 只读外部锚点查询）可以进 MCP，但归 `none` 级并走白名单。依据是铁律 1（人拍板）与铁律 4（资产不跨界）；这也使未来接入外部 MCP server 时的边界自洽——外部 server 的写工具同样不适用。

### 6.4 工具调用审计日志

新建平台级审计（区别于业务 audit 模块）：每次 MCP 工具调用记录 **谁（emp）/ 会话（session_id + purpose）/ 工具名 / 入参摘要 / 结果摘要 / 工作区 / 时间戳**， append-only 落盘。消费场景：闸门追溯（人拍板前的 Agent 行为链）、越权拒绝留痕、数据制造与归因 Agent 的合规复核（铁律 3/7 的证据面）。入参摘要做长度截断与敏感字段脱敏。

### 6.5 储备项：MCP client + 迷你 gateway 策略

不排期，只定义触发条件与预案：

- **触发条件**（任一即启动评审）：① 禅道生态出现厂商背书或经社区充分验证的 server（当前仅 Unvalidated 个人项目，R2 ③）；② 平台工具数翻倍（>50）或多团队并发贡献工具模块；③ 出现第二个外部系统（如迁 Jira——可直接接 Atlassian 官方 server）的接入需求。
- **预案要点**：MCP client 能力挂 `agent/` 侧；迷你 gateway 只做三件事——工具白名单、readOnly 强制（自行校验不信 annotations）、参数与输出审计；外部 server 输出一律视为不可信数据（防 tool poisoning / 间接注入，R2 风险 3）；外部 server 快照锁定、禁自动热更（防 postmark-mcp 式 rug-pull）。

---

## 7. 风险与铁律一致性

R2 风险清单逐条缓解，并映射 8 条铁律：

| R2 风险 | 缓解措施 | 铁律映射 |
|---|---|---|
| 1. Skill 注入面（36% 含注入、可捆绑脚本、`<>` 注入） | §5.4 五级管线；`<>` 校验进 CI；导入即代码审查 | 铁律 2（确定性校验打底） |
| 2. 供应链无信任根（无签名/pinning、rug-pull 先例） | 版本快照锁定 + 外部 skill/server 禁自动热更；升级重走管线 | 铁律 3（每个产出必过闸） |
| 3. Tool poisoning（描述劫持、输出间接注入） | description 人工评审项；外部输出视为不可信数据；高权限工具白名单隔离 | 铁律 1、2 |
| 4. Annotations 不可信（hint 非边界） | 只读在自家运行时强制（§6.2），不信 server 自述 | 铁律 2 |
| 5. 误报疲劳（扫描器 warn 误报 ~42%） | 扫描分级不自动阻断 + 人工复核层（§5.4 第 3 级） | 铁律 1（人拍板） |
| 6. 禅道 server 质量未知（Unvalidated、明文凭证） | 不接入；zentao-cli 通道保持；触发条件见 §6.5 | 铁律 4（资产不跨界） |
| 7. 标准仍在变动（version 字段、信任指导在提案期） | 未知字段宽容忽略；version 自建落在宽容区，可无缝切换 | 铁律 5（解耦）的同款精神 |

铁律覆盖检查：铁律 6（delta 导入唯一通道）由数据制造 Agent 走草稿三闸保证，skill/MCP 体系不开旁路；铁律 7（诚实语义）由归因 profile 提示词 + 校验双侧固化，审计日志提供证据面；铁律 8（不做编码智能体）落为注册表评审项——任何新 profile/skill 的工具白名单不得含代码生成/研发管理类工具，外部 skill 导入评审同查。

---

## 8. 分期路线图

| 阶段 | Skill 体系 | MCP 体系 |
|---|---|---|
| **F3**（随 purpose 会话模型，与 M01 共建） | profile/skill 绑定关系随 purpose 装配生效 | 三层交集白名单运行时过滤上线；审计日志骨架（who/session/tool/结果） |
| **G1**（图谱索引 + 材料包解析） | 格式对齐四项（§5.1）+ `version` 等自建字段 + 注册表查询面 + 悬空引用校验 | 四步挂载规范 checklist 化；`side_effect` docstring 声明全覆盖 |
| **G2**（失败归因 + info_pack 补票） | 外部 skill 导入审查管线上线（首批≤3 个厂商官方 skill 试跑） | `info_pack.py` 挂载补票；`none` 级纯读运行时校验上线；「外部写不进 MCP」通则写入规范 |
| **G3**（数据制造 + 故事点评估） | skill 版本升级留痕（变更记录入库） | `external-write` 空集校验进 CI；审计日志消费面（闸门追溯页） |
| **储备项**（不排期，触发条件驱动） | skill 市场/评分平台：触发条件见 §5.5 | MCP client + 迷你 gateway：触发条件见 §6.5 |

---

## 9. 验收标准

每条结论对应可检验条件：

**Skill 体系（需要，轻量体系化）**
1. 缺 name/description 或含 `<>` 的 skill 文件被加载器拒绝并告警；含未知字段的合规 skill 正常加载；
2. `version`/`depends_tools` 字段进注册表返回；profile 声明不存在的 skill 时报悬空引用错误；
3. 构造 profile 白名单外的工具调用被运行时拒绝且无副作用（M12 G1 验收口径）；skill 声明超出 profile 白名单的部分不生效且审计日志有 WARNING；
4. 一个外部 skill 完整走完五级管线入库，来源/评审人/快照可查；修改其源文件后 30s 内热加载**不生效**（快照锁定证据）。

**MCP 体系（需要治理化，不需要平台化）**
5. 四步挂载 checklist 进评审模板；`info_pack.py` 挂载后 `list_tools` 计数与实际一致（M12 G2 验收口径）；
6. 全部工具带 `side_effect` 声明；对一个 `none` 级工具注入副作用的测试用例被运行时拦截并记审计；
7. 规范文档中检索得到「外部写不进 MCP」通则条款；新工具模块评审记录含该条检查项；
8. 任意一次 MCP 调用后，审计日志可按 emp + session_id + 工具名检索到完整记录（含入参摘要与工作区）。

**储备项（暂缓有据）**
9. 路线图中储备项无排期任务；三项触发条件写入评审 checklist，任一满足时自动生成评审议题。

**不做项（边界显式）**
10. 无任何自建 skill 市场/评分平台的代码与排期；多 MCP server 编排无设计文档之外的投入。
