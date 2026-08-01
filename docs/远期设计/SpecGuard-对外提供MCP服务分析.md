# SpecGuard 对外提供 MCP 服务 · 可行性与场景分析

> 架构决策分析（续《Skill 与 MCP 体系建设分析》）· 2026-07
> 问题：SpecGuard 后期是否可以对外提供 MCP 服务？有什么场景可以用？

---

## 1. 结论摘要

**可以，而且这不是「要不要做」的新方向，而是已有资产的自然延伸 + 「不做编码智能体」战略的关键拼图。**

- **起点比想象高**：SpecGuard 今天就已经是 MCP server——`mcp_server/server.py`（stdio、8 模块 24 工具），Agent 与 Qoder 等宿主已在经它操作仓库。「对外」的增量不是从零建 server，而是三件事：**传输远程化（stdio → Streamable HTTP）、身份与权限（SSO/OBO + 工具分级）、开放面管控（读优先、写过闸）**。
- **战略价值**：S8 边界宣言说「编码 Agent 产出入链被治理、SpecGuard 与 Codex/Claude Code 互补」——互补不能只靠口头，**对外 MCP 服务就是互补的技术通道**：编码 Agent 写代码前经 MCP 读 spec 锚点与覆盖现状，写完经 MCP 登记外部锚点。这反而**强化**了铁律 8（不做编码智能体）的叙事：我们不做编码，但我们是所有编码 Agent 的质量上下文提供者。
- **开放节奏**：读优先、写过闸、外部写永不进；分三圈层（宿主 → 团队内远程 → 生态开放），第三圈列为储备项、触发条件驱动。

---

## 2. 现状基础（真实模块可溯）

| 已有资产 | 位置 | 对「对外」的意义 |
|---|---|---|
| MCP stdio server | `mcp_server/server.py` | 协议面已通，Agent/Qoder 已消费 24 工具 |
| 工具注册双链路 | `TOOL_MODULES` + `engine/tool_registry.py`/`live_registry.py` | 新工具模块挂载规范成熟，开放面可按模块粒度裁剪 |
| 多工作区透传 | `specstd/workspace.py` contextvar + `X-SG-Workspace` header | 天然支持「不同团队看不同工作区」的多租户语义 |
| RBAC 与认证 | workbench `services/auth.py`（`SG_AUTH_MODE=uac`）+ UAC SSO | 远程化时的身份源已有，无需另建账号体系 |
| 治理件规划 | 《Skill 与 MCP 体系建设分析》§6：`side_effect` 分级 / 三层交集白名单 / 调用审计 / 挂载规范 | 对外开放**必须等这些治理件落地**——它们本来就在 G1-G3 路线上 |

**缺口（即「对外」的真实成本）**：① stdio 只适合本机宿主，远程需 Streamable HTTP transport；② 无 per-client 的工具可见集（现在是全量 24 工具对宿主裸奔）；③ 无对外审计与配额；④ 校验/查询类工具「纯读」目前靠 docstring 自觉，对外前必须变成运行时强制。

---

## 3. 场景清单（按价值排序）

### S1 · 编码 Agent 消费质量链上下文（旗舰场景）
Codex / Claude Code / Qoder / Cursor 等编码 Agent 在研发本机或云端工作时，经 MCP 读取：
- `read_spec` / `list_spec_files`：FR 锚点、SHALL 语句、AC 验收条件——**写代码前知道「这段逻辑的合同是什么」**；
- delta 契约与版本期望（`^X`/`X.Y`）：改动落在哪个 delta 上、契约版本是否受影响；
- 影响面反查：改这个 FR 会波及哪些场景（covers 反链）。

**价值**：编码 Agent 不再凭猜测写业务逻辑；SpecGuard 成为「spec 上下文基础设施」。这是边界宣言「互补」的落地形态，也是对领导叙事里最有说服力的一条。

### S2 · 研发改动自查（提交前自检）
研发（或其编码 Agent）提交前经 MCP：
- `check_dag` / `query_registry`：确认受影响场景集的 DAG 合法性；
- `run_scenario`：跑与本改动相关的场景子集（而非全量回归）；
- `read_run_report`：读失败详情与归因建议。

**价值**：把「测试左移」从口号变成研发工作流里的一个工具调用；场景执行的确定性引擎（scenario_runner）不变，只是消费入口变宽。

### S3 · 质量数据只读开放给研发侧工具
研发自己的看板/Agent/IDE 插件经 MCP 消费：
- 覆盖缺口泳道（13 FR 零覆盖这类事实）、测试债地图（长期无执行/健康分 <80 的 FR 区域）；
- 图谱索引查询（L0/L1/L2 下钻、backlink）；
- 计划/执行状态（plan#7 v3、run#23 四态结果）。

**价值**：质量数据不再锁在测试工作台里；研发能看到「我负责的功能点欠了多少测试债」。全只读，零写面风险。

### S4 · CI/CD 发布门禁的 Agent 友好面
流水线或发布机器人查询：P0 清零状态、covers 门禁、契约指纹比对（contracts_baseline）、release_check 三项门禁结果。
**说明**：确定性校验本身有 CLI/REST（`release_check.py`、workbench routers）更适合 CI；MCP 面的价值在于**发布 Agent**（如自动发布助手）可以用同一协议边查边决策。定位是「同构补充面」，不替代 CI 直连。

### S5 · 审计与合规只读通道
血缘链 Story Line 的两个审计问题（Q1「这个场景为什么存在」/ Q2「这个需求被验证了吗」）以 MCP 工具形式开放给审计方、QA 主管或合规检查工具——trace API 直接消费，无需登录工作台截图取证。

### S6 · 禅道侧反向查询（配合 external_refs）
研发在禅道或 IDE 里，经 MCP 按 ZT-STORY/ZT-BUG 反查：这个故事关联的 spec 锚点、覆盖场景、最近验证结果——`sf_external_refs` 登记的引用变成双向可查。「链可跨界」的查询面。

### S7 · 新人 onboarding 与跨团队自助
任何支持 MCP 的助手（团队内部的问答 bot、其他项目组）消费图谱 L0 星座图与场景库 doc 层（given/when/then 给人看的部分），自助认识系统全貌，降低跨团队沟通成本。

---

## 4. 开放分层：工具分级面（核心管控设计）

对外开放面按《Skill 与 MCP 体系建设分析》§6 的 `side_effect` 分级裁剪，**默认只开 L0**：

| 层级 | 内容 | 工具示例 | 开放策略 |
|---|---|---|---|
| **L0 只读查询**（side_effect: none） | spec/场景/报告/图谱/血缘/缺口/台账查询 | spec_reader 三件套、registry_query、check_dag、read_run_report、graph/lineage 查询、external_refs 反查 | **第一圈就开放**；运行时强制纯读（不信自述） |
| **L1 草稿写入**（side_effect: draft） | 写草稿、加信息包、提交归因建议 | write_draft、add_to_info_pack、report_vulnerability | 团队内开放；**产物一律草稿态，照常过三闸**——外部调用者没有任何「绕过闸门」的通道 |
| **L2 永不开放**（side_effect: external-write / admin） | 草稿晋升、禅道写、用户管理、工作区管理 | promote_draft、zentao story/bug 写、users/settings | 不走 MCP 对外面，仅人在 UI/REST 确认后执行（「外部写不进 MCP」通则的镜像：**拍板写也不进对外 MCP**） |

配套机制：per-client 工具可见集（client 注册时声明白名单，运行时三层交集过滤的对外形态）、OBO 身份传递（调用者=真实员工工号，审计到人会话）、调用配额与审计日志（谁/何时/哪个工具/入参摘要）。

---

## 5. 分期路线（对齐 F/G 里程碑）

| 阶段 | 开放圈 | 内容 | 前置条件 |
|---|---|---|---|
| 现状 | 本机宿主圈 | stdio 24 工具，Agent/Qoder 消费 | 已有 |
| **G2** | 团队内远程圈 | Streamable HTTP transport + UAC SSO + L0 只读面 + per-client 白名单 + 审计 | 《Skill 与 MCP 体系建设分析》G1-G2 治理件落地（side_effect 分级运行时强制、审计日志） |
| **G3** | 团队内 L1 | 草稿写入面开放（过闸不变）+ S2 研发自查场景打磨 | L0 运行稳定、审计无异常 |
| 储备项 | 生态开放圈 | 注册 server.json 进 MCP Registry、对外文档、配额商业化 | 触发条件：第二个团队/外部方提出接入需求 **且** L0/L1 内部跑稳一个季度以上 |

---

## 6. 风险与边界

1. **数据边界先于技术**：spec、场景、报告含业务语义（干部盘点规则、绩效域逻辑），对外开放前需定密级——L0 面里哪些工作区、哪些模块可对外，是管理决策不是技术决策。
2. **我们成为 server 后的反向 tool poisoning**：不可信 client 可能诱导平台 Agent 误用返回数据——对外面只供数据、不供「指令」；返回值视为不可信内容的纪律对消费方同样适用（文档明示）。
3. **闸门完整性不可稀释**：任何对外工具不得提供「 promote / 冻结 / 回写」能力变体；绕闸生效 = 阻断性缺陷（与 M12 验收红线同口径）。
4. **传输与标准变动**：MCP 远程传输（Streamable HTTP）与 Registry 元数据规范仍在演进，适配层做字段宽容，不锁定草案行为（承 R2 风险 7）。
5. **成本红线**：若 G2 时发现远程化需改动 `engine/` 冻结层任何文件，立即停止重新评估——对外开放不允许触碰引擎层。

---

## 7. 一句话回答

**SpecGuard 后期不但可以、而且应该对外提供 MCP 服务——它是「不做编码智能体」定位的放大器：用 L0 只读面把 spec 锚点、覆盖现状、血缘追溯变成所有编码 Agent 与研发工具都能消费的质量上下文基础设施；写面永远过闸、外部写永不进，开放节奏由治理件成熟度与真实接入需求双触发。**

---

*事实基础：《SpecGuard 技术架构》2026-07-31 快照；《Skill 与 MCP 体系建设分析》；模块设计 M06/M10/M11/M12。*
