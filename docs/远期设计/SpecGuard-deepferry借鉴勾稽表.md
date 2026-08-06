# SpecGuard × deepferry 借鉴勾稽表

> 版本：v1.0（2026-08-06） · 状态：参考件（非任务认领文件，认领走《任务总控-TASKS.md》/ 远期总控文档）
> 用途：① 打磨期 Agent 内核加固的候选输入（不等远期 S0-S8 解锁）；② 远期 S0-S8 启动时，M01/M02/M05/M06/M12/M13 施工的「已被代码验证过的设计参考」索引。

---

## 1. 来源与使用方法

**deepferry**（`D:\work\tdm-code\deepferry`）：基于 MCP 协议的 LLM Agent 通用数据访问层 + 嵌入式 agent 运行时（tool-use 循环 / 子 agent 委派 / skill 渐进披露 / 经验记忆 / 知识库）+ Tauri 桌面端。与 SpecGuard 技术栈高度同构（Python + FastAPI + MCP SDK + React/TS + SQLite + OpenAI 兼容 LLM 客户端）。规模：src ~28k 行 Python，73 测试文件 / 1164 测试函数，mypy --strict，OpenSpec SDD 纪律（30 specs + 23 changes + 3 archive）。Alpha 阶段，未发正式版。

**使用纪律（三条）**：

1. **抄设计，不引依赖**。deepferry 奉行「开发期不背历史包袱、破坏性变更直接做」，API 契约不稳定；所有借鉴均为「读其设计/代码 → 按 SpecGuard 约束（8 铁律、冻结层、确定性校验）重写」。
2. **先正名再移植**。两项目存在同名异物术语，见 §2 术语映射。
3. **测试纪律一并借鉴**。deepferry agent 层测试密度（299 个 agent 测试函数）显著高于 SpecGuard agent 层；移植任何机制时同步移植其测试用例思路。

---

## 2. 术语映射（同名异物，移植前必读）

| 词汇 | deepferry 语义 | SpecGuard 语义 |
|---|---|---|
| scenario | 审计分组句柄（外部 agent 多次 query 归并为一次调查，纯审计维度） | 测试场景 YAML（引擎执行单元） |
| delegate | 主子 agent 委派工具（`delegate_to_<name>`） | 无此概念（远期 M12 多智能体） |
| compaction | usage 锚点 + 切点吸附 + 增量摘要（WP7，提案态） | compactor.py 启发式压缩（G3-1，已落地） |
| skill | Anthropic Agent Skills 约定（SKILL.md 目录 + 渐进披露 + allowed-tools） | agent/skills/*.md 单文件 + 全文注入 prompt |
| knowledge doc | 策展型知识（字段语义/枚举/JOIN 键，frontmatter 绑定数据源） | 工作区 AGENTS.md / info_pack / docs/经验包 |
| 模式/mode | 无 | modes 5 个（K-023 已去模式化，工具过滤改全量常驻；远期 M01 purpose 为终态） |

---

## 3. 主表：Agent 内核 9 项硬伤勾稽

deepferry `openspec/changes/agent-core-evolution/` 提案（移植自生产级 pi harness，MIT）列出 9 项内核硬伤，逐项对照 SpecGuard agent 层现状（核查日 2026-08-06，证据为行号级）：

| # | 能力项（deepferry WP） | SpecGuard 现状 | 证据 | 差距与建议落点 |
|---|---|---|---|---|
| 1 | Provider 怪癖能力位层（WP1） | 🟡 假设 OpenAI 兼容通吃，仅两处定向适配：strip `reasoning_content`/`references`；thinking 选项双风格并发 | `agent/llm_client.py:189-194, 209-215` | 无 developer role / `max_completion_tokens` 处理。落点：**任务链 C（轻量 Provider 分支）合并做**，参考其 `ProviderCompat` dataclass + 两段解析设计 |
| 2 | LLM 错误双名单 + 可取消重试（WP2） | 🟡 5xx/网络错误指数退避 ≤3 次；流式建连失败/中途断分级；**429 不重试**、无 Retry-After；重试耗尽本轮死亡（会话不丢） | `llm_client.py:155-185`；`runtime.py:296-303` | 429 退避是低成本高收益项。**打磨期立即可做**（任务链 C 配套） |
| 3 | 工具结果大小治理（WP3：`ToolOutput` content/details 分离 + 字节级截断） | 🟡 runtime 层**零截断**，治理靠各工具自觉（spec_reader 200KB / attribution 2000 字符 / @引用 60KB 总量）；`read_run_log` 等大结果可原样进上下文，仅靠 compaction 兜底 | `runtime.py:413-417`；`mcp_server/tools/spec_reader.py:37,150-155` | **打磨期立即可做**：runtime 统一出口加字节级截断（超限落盘 + 回喂引用），与 M13 治理件不冲突 |
| 4 | 工具钩子 + 写操作人工确认门（WP4） | 🟡 无 before/after hook；**无调用级确认门**，但流程级闸门已完备（drafts 沙箱 + OVERWRITE_DENIED + promote 三道闸，铁律 3） | `runtime.py:331-345`；`mcp_server/tools/draft_writer.py:274` | 差距比表面小：SpecGuard「每产出必过闸」在流程层已覆盖。建议只在远期 M13 side_effect 三级落地时补 runtime 钩子，**不单独立项** |
| 5 | 流式工具进度事件（WP5） | 🟡 有 tool_call_start/end 事件（K-018）；工具执行中（如 180s 子进程）零进度，仅 WS heartbeat 证明存活 | `runtime.py:333-345,414`；`routers/agent.py:528-534` | 落点：**任务链 B3（流式输出）合并做**，参考其 `tool_progress` 累计快照 + settle 后 flush 语义 |
| 6 | steering / follow-up / abort（WP6） | ❌ 无 cancel 端点、无循环检查点；前端「打断」仅关 WS，**后端线程继续跑完并继续写会话**（假打断）；运行中插话被 K-015 互斥挡回，无 follow-up 队列 | `routers/agent.py:481-487,565`；`AgentChat.tsx:1808-1818`；`runtime.py:281-360` | **假打断是体验级缺陷，打磨期立即可做**：cancel 端点 + 循环检查点 + 前端 AbortController；follow-up 双队列可后置远期 M01 |
| 7 | usage 锚点 compaction（WP7） | ✅ 已落地（G3-1）：token 占比 0.7 触发、切点不拆 tool 对 + 配对校验修复、增量合并 2000 字符软上限、只压工作副本保留完整历史（K-019） | `agent/compactor.py:46-60,163-242`；`runtime.py:276-284` | **SpecGuard 领先**（对方仍是提案）。可选增强：`_generate_summary` 当前是纯启发式未调 LLM，可评估 LLM 摘要收益 |
| 8 | 会话树化（WP8：parent_id/leaf_id、fork/rewind） | ❌ 纯线性；save() 每次全量覆盖写；恢复即整链重放，无回退能力 | `agent/session.py:80-111,164-189` | 需求弱（测试场景对话短链为主）。**列远期储备项**，随 M01 purpose 体系再评估 |
| 9 | Skills 工程化（WP9 + `agent/skills.py`） | 🟡 frontmatter 解析宽松（失败静默/未知字段忽略/不校验 name==文件名）；无 version/depends；**全文注入** prompt（当前 5 个可承受，规模隐患） | `agent/skill_loader.py:24-31,75-99,111-126` | 落点：**远期 M13 skill 体系化**直接参考其三层渐进披露（扫描→目录注入→`load_skill` 按需取正文）+ allowed-tools 单调收窄 + 路径禁闭；与任务链 G（SystemPrompt 裁剪）有交集 |

**9 项小结**：✅1 / 🟡6 / ❌2。真正的新增硬伤只有 #6 abort 与 #8 会话树；#3 工具结果治理是「有哲学无机制」；#6 是唯一建议立即排期的体验缺陷。

**补充发现（M01/M12 前置事实）**：runtime 工具过滤已从 mode 级静态白名单改为**全量常驻**（K-023 去模式化，`runtime.py:222-225`；mode 的 `tools:` 字段仅展示用）；构造函数支持 `tools` 裁剪但 HTTP/WS 入口均未传参，**无 run 级过滤机制**——远期 M12「工具白名单三层交集」需新建 run 级 ToolContext，deepferry `agent/tools.py` 的 ToolContext + run 级 allowlist 是直接参考。

---

## 4. 内核之外：6 个机制级价值点勾稽

| 价值点（deepferry 位置） | 内容 | SpecGuard 对应物 | 落点（远期模块/阶段） |
|---|---|---|---|
| **OpenSpec V3 工作流**（`openspec/`） | specs 基线 11 章 + changes（delta 三段式 `[delta:代号]` + 双向锁定）+ archive 冻结 + fixes 回链协议 + glossary；已跑通 23 changes / 3 archive | specstd（代码化合规，更强）+ docs/经验包（与 fixes 协议同构） | **M02/M04/M05（S2/S4/S5）施工前精读**：六阶段流程、delta 标记、fixes↔spec Changelog 双向回链纪律可直接作为 specflow 流程输入 |
| **子 Agent 委派**（`agent/subagent.py`） | config 声明→`delegate_to_*` 工具物化；工具面只收窄不放大；**深度上限 1 由构造保证**（幻觉调用也只能吃到 TOOL_NOT_ALLOWED）；审计三列可重建调用树；超时/失败永远结构化返回 | 无（单循环） | **M12 多智能体运行时（S1 骨架/S6 承载）**参考实现；与薄 Harness 哲学一致（刻意不做 DAG/嵌套） |
| **Skill 渐进披露**（`agent/skills.py`） | 扫描只解析 frontmatter → prompt 只注入目录 → `load_skill(name[, resource])` 按需取正文/附属资源；路径禁闭；非法 skill 告警跳过不崩启动 | skill_loader 全文注入 | **M13（S8）**；同时缓解任务链 G 的 prompt 膨胀问题 |
| **MCP Client Hub**（`agent/mcp_client.py`） | 消费外部 MCP server：`mcp__<server>__<tool>` 命名空间、stdio/http 互斥校验、`${ENV_VAR}` 注入、懒连接/规格缓存/空闲回收/指数退避/「从未连上 vs 曾连上」健康语义 | 无（SpecGuard 只是 MCP server） | **M06 禅道（S5）/ M13 对外消费（S8）**：比为每个外部系统写死适配器更优；与「zentao-cli 子进程是有意的边界控制」决策需总控权衡（client hub 通用性 vs 子进程隔离性） |
| **经验记忆飞轮**（`agent/memory.py`） | run 终局落行（success/failed/corrected）+ 纠正关键词确定性检测 + `recency×hit_count` 检索注入 prompt（2KB 封顶）+ 👍/👎 API；纯结构化无向量检索 | feedback/ledger（SPQ，面向被测系统缺陷）+ docs/经验包（人工策展）；**缺 agent 运行经验的自动积累回注** | **M09 归因（S6）增强**：让 debug-failure 不再每次从零排查；与确定性哲学气味相投 |
| **知识绑定提醒**（`agent/knowledge.py`） | frontmatter 绑定数据源，触景 nudge（每篇每会话最多一次，主子委派间继承）；git staleness + depends_on 传播；agent 只提议不回写 | info_pack / AGENTS.md 注入（全量 or 没有，缺「按需+触景」层） | **M03 信息包（S3）增强**：如「该模块有未闭环 SPQ / 有经验包」触景提醒，低成本高体验收益 |
| **审计 span 树 + 诊断规则引擎**（`core/trace.py` / `diagnostics.py`） | OTel 对齐 span 树落 SQLite（fire-and-forget）；规则优先级链归因（TIMEOUT>AUTH>CONNECTION>QUERY + confidence + suggestion）；幂等列迁移 | failures/index.jsonl + 网关 trace_id + attribution 工具（粒度是场景/步骤级） | **M09（S6）工具调用级归因粒度** + **M13 `sf_mcp_call_audit` 统一审计**的表设计参考 |

**工程纪律散件（可摘抄）**：结构化错误契约补 `suggestion` 字段（`core/errors.py`）；Docker 种子迁移 Vxxx 幂等纪律（→ M08 测试数据制造直接可用）；「不背历史包袱」原则（验收期可明示采纳）；导航单一菜单树规则（工作台 19 页面渐多可参照）。

---

## 5. SpecGuard 已领先 / 无需借鉴清单（避免重复造轮子）

- **场景执行引擎**：DAG 依赖调度 / verify 断言器 / DB oracle / save 变量 / shared/exclusive 语义 —— deepferry orchestration 刻意硬限线性+foreach，全面碾压，无可借鉴
- **specstd 代码化合规层**（schema/anchors/conformance/signature/workspace）—— 对方 openspec 是流程纪律而非代码强制
- **release_check 发布门禁 + 契约指纹** —— 对方无对应物
- **多用户 RBAC / UAC SSO** —— 对方明确 Out of Scope
- **compactor（G3-1）** —— 已落地且有生产修复痕迹（K-015/K-019），对方 WP7 仍是提案
- **WS heartbeat + TCP 半开检测** —— 实时性领先对方 SSE
- **诚实结果语义（SKIP/BLOCKED）** —— 哲学一致，互相印证，无需改

---

## 6. 建议行动次序

**P0 · 打磨期立即可做**（不等 S0-S8 解锁）：**已于 2026-08-06 经总控文档 v1.2 决策登记为打磨期第四轮任务**——S0 单测收口前置为 **T-401**（其余三项的回归底座，先行施工），下列三项对应 T-402/T-403/T-404，依赖与验收口径以总控文档 §4.1/§3.1 为准：

1. **abort 真打断**（主表 #6 → **T-402**，依赖 T-401）：cancel 端点 + runtime 循环检查点 + 前端 AbortController —— 当前「打断」按钮是假打断，后端继续跑完写会话，属体验缺陷
2. **工具结果统一截断**（主表 #3 → **T-403**，依赖 T-401，∥T-404）：runtime 出口字节级治理（超限落盘 + 回喂引用）
3. **LLM 429 退避 + Retry-After**（主表 #2 → **T-404**，依赖 T-401，∥T-403）；Provider 能力位层仍归 upgrade-plans 任务链 C

**远期阶段配套**（S0-S8 解锁后，施工前精读对应 deepferry 文件）：

| 阶段 | 配套参考 |
|---|---|
| S1（purpose 地基 M01/M12/M13 骨架） | `agent/tools.py`（ToolContext + run 级 allowlist，三层交集前置）、`agent/subagent.py` |
| S2 前置（面试闭环 M02/M04） | `openspec/` 六阶段 + delta 三段式 + fixes 协议 + glossary |
| S3（材料包 M03） | `agent/knowledge.py` nudge 机制 → info_pack 增强 |
| S5（禅道 M06） | `agent/mcp_client.py`（client hub vs zentao-cli 子进程，总控权衡） |
| S6（测试侧三增强 M07/M08/M09） | `agent/memory.py` 经验飞轮、`core/trace.py`/`diagnostics.py` 归因粒度、种子迁移幂等纪律 |
| S8（治理件 M13） | `agent/skills.py` 渐进披露 + allowed-tools + 路径禁闭 |

**不建议**：任何代码级依赖引入；Tauri / keyring 多后端 / orchestration 模块；把 OpenSpec 工具链搬进来（specstd 已是更强的代码化版本）。

---

## 7. 风险与未尽事项

- deepferry 最后提交 2026-07-22（约 2 周前），desktop-first pivot 后部分模块仍在变动；借鉴时以「当前快照的设计思想」为准，不跟踪其后续演进
- 主表 #4（调用级确认门）与 #8（会话树）建议维持「不单独立项 / 储备项」判断，随远期 M01/M12/M13 评审时再议
- 本表基于 2026-08-06 两仓库快照；远期 S0-S8 启动时需按总控文档 §6 协议刷新事实源（M13「24 工具」口径等已知漂移点）
