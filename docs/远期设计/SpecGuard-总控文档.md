# SpecGuard Vision · 开发总控文档

> **本文档是所有开发会话的唯一协调中心。任何开发会话开工前必须完整阅读 §1-§4，并按 §3 协议注册会话、认领任务、登记文件变更。**
> 版本：v1.30 · 2026-08-21 ｜ 配套：`sg-hash.py`（文件指纹工具）｜ 上游依据：《研发顺序与里程碑验收》、13 份模块设计（M01-M13）、00 统一约定
>
> **v1.29 决策（2026-08-21，sess-arch-breakdown，总控人指令）**：新增 §4.11「架构反馈升级施工块」（T-960~T-999，依据《架构反馈升级/2026-08-21-模块化任务拆分.md》——08-20 架构体检+八点反馈判定归档 + 08-21 知识库核验翻案与总控人拍板）。六功能域六 worktree：M-A 多系统贯通（wt/multi-system，含 T-973 系统包动态注册——总控人拍板分级方案：配置型系统 UI 注册即时生效、代码型评审后热加载免重启）/ M-B 依赖翻正（wt/dep-inversion）/ M-C 智能层可信度（wt/agent-eval + wt/test-taxonomy + wt/tool-consolidation）/ M-D 材料池演进（wt/material-pool，吞并 T-933~T-935）/ M-E 前端 IA（wt/frontend-ia）/ M-F 收尾填料。P0 五项（T-960~T-964）主库小刀当天清，含 08-21 知识库翻案新增的 T-964 clarity 假分数清理。待拍板决策剩 3 项（话题 FR 锚点派生/闲聊默认过滤/管理菜单收低频区），认领 T-991/T-992/T-996 前先过。
>
> **v1.30 决策（2026-08-21，sess-arch-breakdown，总控人指令）**：第二轮归档瘦身——v1.23~v1.28 决策记录、§4.8 GateDock（T-900~T-902 ✅）、§4.9 飞书知识图谱（T-910~T-930 ✅）、§4.10 已完成任务（T-931/T-932/T-937~T-952/T-955 ✅）、已完成会话注册与 §6 非基准行，归档至《历史区/SpecGuard-总控文档-归档-2026-08-21.md》；总控仅留活跃任务（§4.6 进行中/§4.7 触发制/§4.10 未认领与储备行/§4.11 施工块）+ §6 登记中行与各文件最新基准行。
>
> **历史决策**：v1.1~v1.22 见《归档-2026-08-13》第一章；v1.23~v1.28 见《归档-2026-08-21》第一章；已完成任务验收备注见两份归档对应章节。

---

## 1. 开发会话工作协议（强制，六步）

```
① 读   —— 读本总控文档 + 你任务对应的模块设计文档（Mx §0-§9）+ 00 统一约定
② 注册 —— 在 §5 会话注册表登记：会话ID / 角色 / 认领任务ID / 开工时间
③ 认领 —— 把 §4 任务总表中目标任务的「状态」改为 进行中、填入你的会话ID
④ 登记 —— 改任何文件前，先在 §6 文件变更登记表登记：路径 + 修改前hash
           hash 命令：python3 sg-hash.py <文件路径>
⑤ 开发 —— 按模块设计文档 §6 关键流程与 §9 验收标准开发
⑥ 收口 —— 改完更新 §6 登记的「修改后hash」，任务达验收标准后 §4 状态改 已完成
```

**三条铁规：**

1. **未登记不动手**：要修改的文件没有出现在 §6 登记表（且状态=登记中、会话ID=你），不得写盘。
2. **开工先对 hash**：认领任务后，对将要修改的每个文件执行 `python3 sg-hash.py --check <文件> <登记表中的修改后hash>`。DIFF = 有人改过你不知道的版本——**停手**，去 §6 找到最后登记会话，对齐后再开工；禁止直接覆盖。
3. **一任务一会话**：状态=进行中的任务不得被第二会话认领；需要协作时在 §5 注册表「备注」列协商拆分。

---

## 2. 阶段地图：方向与目标效果

### 2.0 打磨期（P0，✅ 2026-08-07 总控人宣布结束，已归档）

四轮任务（T-101~T-131 / T-201~T-205 / T-301~T-321 / T-401~T-404）全部完成、回归 674/674 全绿，打磨期结束并恢复升级期认领。阶段小节与任务明细见归档文件第二、三章。

### 2.1 远期升级期（S0-S8，2026-08-07 起恢复认领）

> 以下为远期升级路线（v1.1 起整体后置；**2026-08-07 总控人宣布打磨期结束，恢复认领**）：
> 关键路径串行：S0→S1→S2✅→S3→S4→S5→S6→S7→S8；P-A 支路（T-070/071/072）从 S3 起可全程并行（**T-070 为咽喉，S3 起 P0**，v1.6）；**S0.5 依据透明快车道（v1.5，T-511/T-512）插在 S0 与 S1 之间但不阻塞 S1，✅ 2026-08-07 完成**；**S1 purpose 地基（T-010~T-014）✅ 2026-08-10 完成（里程碑验收五项全过，S2 依赖就绪）**；**S2 F1 面试闭环 ✅ 2026-08-10 完成（T-020~T-024 全部交付，S3 依赖就绪）**；**瘦身任务块（v1.6，T-601/T-602）先于 S1 施工（T-601 modes 退役是 T-010 硬前置）**；**飞书 CLI 支线（v1.6，T-701~T-703）✅ 2026-08-21 T-998 对账全部完成**；T-073 与 S6 并行、治理三件套按依赖前置认领（v1.6）。
> 每阶段详细验收标准见《研发顺序与里程碑验收》§3，此处给方向与目标效果。

| 阶段 | 方向（往哪里走） | 达成效果（验收门面） | 对应模块 |
|---|---|---|---|
| **S0** 会话编排单测 | agent 编排层测试先行，套件可离线复跑（**v1.2 起前置至打磨期 §4.1 T-401**） | 单测全绿 + `--mock` CI 可挂；后续所有阶段的回归底座 | agent/（runtime/session/compactor） |
| **S0.5** 依据透明（v1.5 新增快车道） | agent 读过的关键文档进面板，关键章节可见 | 用户跟上 agent 关键思路、把判断依据摊开（阅读足迹面板 + 章节提取）；**不阻塞 S1** | agent/runtime + workbench（《知识体系设计》§4.5） |
| **S1** purpose 地基 ✅ | 会话创建期锁定 + 工具白名单运行时强制 | 越权工具调用被确定性拒绝；purpose 不可变（**✅ 2026-08-10 完成：T-010~T-014 全部交付，S2 依赖就绪**） ；[2026-08-10 修复] 全量代码审查修复 6 项安全漏洞（H1/H2/M1-M6），详见 §4.2 T-010~T-014 备注与 §5 sess-s1-fix | M01 / M12 / M13(P1骨架) |
| **S2** F1 面试闭环 ★价值拐点 ✅ | specflow/interview 从零到端到端 | 产品在 AgentChat 完成面试→台账→P0 清零→归档，可演示（**[2026-08-11 修复] 审查验收修复 12 项（H1-H3/M1-M8/低危），详见 §4.2 T-020~T-024 备注与 §5 sess-s2-fix**） | M02 / M04 |
| **S2.5** 日程获取与文档权限 ✅ | 日历+会议纪要链路封装 + 无权限文档结构化引导 | 面试官可从日程获取会议上下文/纪要素材；遇到无权限文档时展示提示+申请链接（`+apply-permission`），不静默降级（**✅ 2026-08-11 完成：feishu_fetch 模块 2 工具 + 真实链路冒烟打通，详见 §4.2 T-025/T-026 与 §5 sess-s2.5-dev**） | 飞书 CLI（calendar/vc/note/docs） |
| **S3** 材料包与信息包 ✅ | 多源文档解析入包，挂载补票 | 三类文档→议题候选→人拍板入包；list_tools 回归（**✅ 2026-08-11 完成：材料管线/候选闸门/六分区装配 + 5 MCP 工具 + 8 REST 端点，详见 §4.2 T-030~T-032 与 §5 sess-s3-dev**） | M03 |
| **S4** 扫描仪与评分卡 ✅ | 草案机打校验 + 五维半自动 | 机打维度走 specstd；LLM 预打分 QA 确认才生效（**✅ 2026-08-11 完成：specflow/anchor + delta 包 + 三闸冻结，详见 §4.2 T-040~T-042/T-050~T-052 与 §5 sess-s5-dev；漏洞修复闭环（纯读化/路径净化/fail-closed）同日完成**） | M05 / M04 |
| **S5** 三闸冻结 + 禅道 ✅ | 产物规格化 + 跨系统挂链 | 三闸冻结；zentao-cli 幂等建故事/提 BUG；external_refs 登记（**✅ 2026-08-11 完成：integrations/zentao 单包 + 幂等作业 + 双入口提单 + 故事点评估 + 三表，详见 §4.2 T-053~T-056 与 §5 sess-s5-dev**） | M05 / M06 |
| **S6** 测试侧三增强 ✅ | 闸门保护下启用 Agent | 缺口泳道真实一致；数据制造/归因产物全过闸（**✅ 2026-08-11 完成：覆盖缺口三态聚合 + sg_draft_gates 三闸状态机 + 数据校验器/制造编排 + 归因证据包/SPQ 挂链 + loop-back，详见 §4.2 T-060~T-064 与 §5 sess-s6-dev；测试 1076 全绿 / release_check PASS / 前端 build PASS**） | M07 / M08 / M09 |
| **S7** 血缘与图谱 | 图谱派生 + 血缘投影（汇合 P-A） | Q1/Q2 双向 trace 不断链；演化 diff 可重建 | M10 / M11 |
| **S8** 治理件 + 对外 L0 | skill 体系化 + open/ 只读面 + 研发侧消费通道 | 旗舰 e2e：外部编码 Agent 经 MCP 读冻结 spec；研发侧 dev_context 三入口（接需求/开发接口/修BUG）从 ZT-STORY 号拿到带指纹的 dev-context-pack | M13 / M12 |

下图把上表画成关键路径：S0→S8 硬串行为主轴，瘦身任务块（T-601/T-602）先于 S1、P-A 支路（T-070/071/072 图谱索引/视图/快照）自 S3 起全程并行并在 S7 汇合主线，T-073 与 S6 并行收尾 S7，飞书 CLI 支线（T-701~T-703）与主线全程并行：

```mermaid
flowchart LR
  SLIM["瘦身任务块 T-601~T-606<br/>T-601 modes 退役 = T-010 硬前置"]
  S0["S0 会话编排单测 ✅"] --> S05["S0.5 依据透明 ✅"]
  S05 --> S1["S1 purpose 地基<br/>T-010 ∥ T-011 并行"]
  S0 --> S1
  S1 --> S2["S2 面试闭环★ ✅"]
  S2 --> S25["S2.5 日程获取与文档权限※"]
  S2 --> S3["S3 材料包与信息包"]
  S25 -.-> S3
  S3 --> S4["S4 扫描仪与评分卡"]
  S4 --> S5["S5 三闸冻结 + 禅道"]
  S5 --> S6["S6 测试侧三增强"]
  S6 --> S7["S7 血缘与图谱（T-074 收尾）"]
  S7 --> S8["S8 治理件 + 对外 L0"]
  SLIM --> S1
  subgraph PA["P-A 支路（S3 起并行，T-070 为 P0 咽喉）"]
    P70["T-070 graph_index"] --> P71["T-071 图谱视图"]
    P70 --> P72["T-072 里程碑快照"]
  end
  S3 -. 并行起点 .-> P70
  P71 -. 汇合 .-> S7
  P72 -. 汇合 .-> S7
  LINE["T-073 血缘投影<br/>S5 后开工 ∥ S6"] -. 收尾 .-> S7
  S5 -. 并行 .-> LINE
  subgraph LARK["飞书 CLI 支线（v1.6，近期可认领，依赖 T-602）"]
    L71["T-701 多用户认证服务"] --> L72["T-702 通用执行器"] --> L73["T-703 workbench 绑定页"]
  end
  subgraph SCALE["规模化升级支线（v1.22，与主线并行；T-801/T-805 随时可认领，T-802~T-806 触发制）"]
    S81["T-801 WS 订阅隔离"] --> S82["T-802 执行槽池化"] --> S83["T-803 调度忙时排队"]
    S85["T-805 服务守护"]
    S84["T-804 SQLite 写路径"]
    S86["T-806 状态外迁（储备）"]
  end
```

---

## 3. 串行 / 并行规则

### 3.1 硬串行（前置未完成不得开工，认领无效）

| 先行任务 | 后续任务 | 原因 |
|---|---|---|
| S0 全部 | S1 全部 | 编排层测试是地基回归保障 |
| T-401 编排单测收口（=S0 前置） | T-402 / T-403 / T-404 | 先有线再施工：runtime/llm_client 改动需回归网兜底 |
| T-601 modes 体系退役（v1.6） | T-010 purpose 模型 | 双轨 prompt 装配污染（modes 与 skills 同题双写）；先退役再开 T-010 一次改到位，避免三次改装配 |
| T-010 purpose 模型 | S2 全部 | 面试会话挂在 purpose 上 |
| T-025/T-026 S2.5 链路工具 | S3 全部（S2.5 不阻塞 S3，虚线依赖） | 日程/纪要虽补充素材但非解析管线前提；原则上可并行 |
| T-023 台账 schema + T-024 P0 清零 | T-042 评分门禁 → S5 全部 | 冻结三闸的③闸依赖台账与清零校验 |
| T-050 delta manifest | T-051 三闸冻结 → T-053/054/055/056 | 禅道侧一切动作消费冻结产物（铁律 6） |
| S5 全部 | S6 全部 | 数据制造/归因 Agent 需要三闸与 delta 通道在位 |
| T-070 graph_index | T-071/072/073 | 视图与血缘都是索引的投影 |
| T-056 sf_external_refs | T-073 血缘外部锚点 / T-083 refs_query / T-085 dev_context 场景A/C | 同表同源，owner 先行 |
| T-070 graph_index | T-085 dev_context 场景B/C | 锚点反查与血缘投影的算力来源 |

### 3.2 可并行（认领即可开工，互不阻塞）

- **P-A 支路**：T-070 / T-071 / T-072（图谱索引、视图、快照）——S3 起与主线全程并行（**T-070 为 P0 咽喉，v1.6 优先认领**）
- **瘦身块（v1.6）**：T-602（TOOL_MODULES 单一注册）与 T-601 并行；T-603/T-604/T-605 无依赖任意空窗；T-606 挂 T-604 后
- **S1 内（v1.7）**：T-014（多会话产物地基）与 T-010/T-011 **三会话并行**——产物目录 emp 维度与会话模型互不依赖，可独立认领独立验收
- **S5 内**：T-053 / T-054 / T-055 / T-056 四者在 T-050+T-051 完成后互相并行
- **S6 内**：T-060 / T-061 并行；T-062 / T-063 在 T-061 后并行
- **S8 内**：T-080 / T-081 / T-082 三者互相并行，均完成后才开 T-083 / T-085；T-085 另需 T-056 与 T-070（通常早于 S8 完成）
- **跨阶段**：T-032（info_pack 补票）不依赖 S2，可提前至 S1 后任意时间
- **S0.5 快车道**：T-511 / T-512 与 S1 并行，互不阻塞（依据《知识体系设计》§4.5，P0 优先）
- **治理三件套前置（v1.6）**：T-081 / T-082 在 S1（T-011）完成后即可认领（✅ 2026-08-10 已满足）、T-080 在 S2 完成后即可认领（✅ 2026-08-10 已满足）——与 S3-S7 主线零耦合，摊入空窗削 S8 峰值
- **T-073 并行（v1.6）**：S5 完成 + T-070 就绪即可认领，与 S6 并行（血缘投影建在冻结产物 + 已有 run 报告上，数据制造/归因 Agent 产物是增量而非前提）
- **引擎支线**：§4.3 T-501 / T-502 与 S1+ 主线互不依赖，认领即可开工
- **知识支线**：§4.4 T-505 / T-506 无依赖可认领；T-507~T-510 随 S1/S3/S6 阶段解锁
- **飞书 CLI 支线（v1.6）**：§4.6 T-701~T-703 ✅ 已全部落地（T-998 对账 08-21；T-703 绑定 UX 形态迁至材料池 FeishuWatchSettings）
- **S2.5（v1.11）**：T-025/T-026 随 S2 完成后可认领（S2 ✅ 2026-08-10 满足），与 S3 并行不阻塞（§3.1 虚线依赖）；**✅ 2026-08-11 完成（feishu_fetch 模块 2 工具，真实链路冒烟打通）**
- **规模化升级支线（v1.22）**：§4.7 **T-801 / T-805 无依赖、35 人起步即可认领**（广播订阅隔离 / 服务守护）；T-802~T-804 触发制（时机列见 §4.7）；T-806 储备不得认领

### 3.3 储备项（不认领，触发条件由总控人宣布）

- T-084 外部 skill 审查管线完整化 / 对外 L1 / MCP Registry 生态开放
- T-503 DB 轮询 + 通用重试原语（触发：首个需要 DB 轮询或瞬时重试的真实场景出现）
- T-504 数据驱动参数化 + 场景级超时（观察项；触发：参数化真实 ROI 成立，或 run 看门狗归因粒度不足）
- T-802 执行槽池化（触发：排队成为常态——连续一周队列长度>3 或等待>15 分钟；架构级需冻结层评审）
- T-803 调度忙时排队（挂 T-802 后；触发：定时任务 skipped_busy 用户反馈）
- T-804 SQLite 写路径演进（触发：database is locked 或写延迟>100ms；观测布点可提前）
- T-806 状态外迁/多机（触发：100+ 且 T-802/804 后仍不足，先评估报告再立项）

---

## 4. 任务总表（认领在这里改状态）

> 状态值：`未认领` / `进行中` / `已完成` / `阻塞`（阻塞须在备注写原因）
> 表行格式固定，只允许更新「状态/会话ID/备注」三列；新增任务由总控人追加。
> 分区：**§4.1 打磨期**（✅ 归档）｜**§4.2 远期升级期**（已完成归档，储备保留）｜**§4.3 引擎演进补点**（储备）｜**§4.4 知识体系**（✅ 归档）｜**§4.5 瘦身任务块**（✅ 归档）｜**§4.6 飞书 CLI 集成**（进行中）｜**§4.7 规模化升级**（触发制）｜**§4.8 对话操作台 GateDock**（✅ T-900~T-902 全完成）｜**§4.11 架构反馈升级施工块**（T-960~T-999，认领中）。
> **已完成任务明细（含验收备注/修复记录）统一见归档文件**：`docs/历史区/SpecGuard-总控文档-归档-2026-08-13.md`。

### 4.1 打磨期（P0，✅ 2026-08-07 结束，已归档）

四轮 41 项任务全部完成，明细见归档文件第三章。

### 4.2 远期升级期（S0-S8，主线任务全部完成）

> S0/S0.5/S1/S2/S2.5/S3/S4/S5/S6、P-A 支路（T-070~T-074）、S7（T-073/T-074）、S8（T-080/T-081/T-082/T-083/T-085）全部完成（2026-08-07~08-11），明细见归档文件第四章。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-084 | P3 | 审查管线完整化/对外L1/生态Registry | M13 | 储备项，触发制 | T-083 | 储备 | | 不得认领 |

### 4.3 引擎演进补点（对标第三批评估，v1.3 新增）

> 来源：《引擎升级建议-第三批-对标开源引擎评估》+ 2026-08-07 复核修正。定位：engine 能力按需补点，非 S 链组成部分；涉断言器/语法变更一律三同步 + TDD；触及 scenario_runner 调度语义仍需冻结层评审。
> T-501（schema 结构断言）/ T-502（fixtures 文件引用预检）✅ 已完成，明细见归档文件第五章。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-503 | 引擎-储备 | DB 轮询 + 通用重试原语 | engine/scenario_runner | poll 扩展 db_query 轮询体（改动集中 step_poll）或 verify retry 原语；触发制：**首个真实场景需要时启动**——当前 4 个 poll 场景全为 HTTP 且工作正常，零真实需求证据 | 触发 | 储备 | | 第三批 P1-1，2026-08-07 复核降级为储备 |
| T-504 | 引擎-储备 | 数据驱动参数化 + 场景级超时 | engine | 观察项：参数化动语法层需冻结层评审（Agent 生成场景成本极低，ROI 不足）；场景级超时边际价值仅归因粒度（T-118 run 看门狗已兜底整轮拖死风险） | 触发 | 储备 | | 第三批 P2-1/P2-2，2026-08-07 复核降级为观察 |

### 4.4 知识体系（v1.4 新增，✅ 全部完成，已归档）

T-505~T-510 全部完成（2026-08-11，sess-know-dev），明细见归档文件第六章。

### 4.5 瘦身任务块（v1.6 新增，✅ 全部完成，已归档）

T-601~T-606 全部完成（2026-08-10，sess-slim-dev / sess-slim-v2），明细见归档文件第七章。

### 4.6 飞书 CLI 集成（v1.6 新增，近期开发规划）

> 来源：飞书 CLI（`lark-cli` v1.0.85）多用户接入需求（2026-08-10 确认：每用户独立 app；服务器多用户共享进程；能力域与现状 app `cli_a96d90ca7d7adbd9` 一致暂不限定；user + bot 身份都要）。
> 技术结论（实测验证）：lark-cli 配置/登录态存储于 `~/.lark-cli/`（机器级全局）；**`USERPROFILE`（Win）/`HOME`（Linux）环境变量可重定向配置目录（实测生效）**——每 SpecGuard 用户一个隔离目录 `{SG_ROOT}/.lark-cli/{emp_no}/`，子进程注入 USERPROFILE 即天然隔离（token/配置/缓存零串扰）；`auth login --no-wait/--device-code` 两阶段授权（Agent 友好）；`--as user|bot` 身份切换（不支持 openId）；`--domain/--scope` 按需申请。
> 定位：与 S1+ 主线并行可认领；**T-701 依赖 T-602**（TOOL_MODULES 单一注册后只注册一处，避免加剧 B1 漂移）；落地涉及 MCP 工具层（mcp_server/tools/）与 workbench 前端，不触引擎冻结层；`.lark-cli/` 目录须补 .gitignore。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-701 | 飞书-认证 | 多用户认证服务 | mcp_server/tools/lark_auth.py + specstd.workspace | 每用户独立配置目录 `{SG_ROOT}/.lark-cli/{emp_no}/`（USERPROFILE 注入，实测生效）+ .gitignore 补充；lark_auth_login 两阶段（--no-wait 返回 verification_url 给用户 → --device-code 完成；--recommend 与现状 app scope 一致）；lark_auth_status / lark_auth_logout（按 emp_no 隔离）；未绑定用户明确提示引导授权 | T-602 | ✅ 已完成（T-998 对账 08-21） | sess-lark-dev | P0｜落地核对：lark_auth.py（450 行）已注册 server.TOOL_MODULES，per-emp 目录/两阶段登录/状态/登出全在；T-982 收敛为 lark_auth(action=status/login/login_complete/logout)；子进程并发锁已随任务落地 |
| T-702 | 飞书-执行 | 通用执行器 | mcp_server/tools/lark_run.py + agent/runtime | lark_run 透传全部 lark-* 域命令（能力探索不限定域）：子进程注入当前用户 USERPROFILE、命令白名单校验（禁 shell 拼接）、超时 60s + 结果截断（复用 _TOOL_RESULT_MAX_CHARS 出口）；写操作（high-risk-write）强制 --yes 且需用户确认；调用留痕（工号×命令×结果摘要） | T-701 | ✅ 已完成（T-998 对账 08-21） | sess-lark-dev | P0｜落地核对：lark_run.py（184 行）已注册 server.TOOL_MODULES；白名单（+create/+update/+delete/logout 写操作需 confirm_write=true）、超时/截断、audit_store.record_call 留痕全在；宿主侧技能包 skills/lark-*（27 域）同期交付 |
| T-703 | 飞书-工作台 | workbench 绑定页与审计 | workbench 前后端 | 「个人设置 → 绑定飞书」：授权 URL / 授权状态 / scope 清单 / 解绑；Agent 会话自动带出当前用户飞书身份（emp_no → 配置目录映射）；调用审计（工号/会话/工具/入参摘要，与 T-082 口径对齐） | T-701/T-702 | ✅ 已完成（T-998 对账 08-21，形态变迁） | sess-lark-dev | P1｜落地核对：绑定 UX 实际由材料池承载（FeishuPool 内 FeishuWatchSettings：授权状态/重新授权/missing_scopes 清单，T-942 授权闭环入弹层），飞书身份随会话经 lark_run USERPROFILE 注入透出，审计走 audit_store；原始交付 routers/lark_binding.py + pages/LarkBinding.tsx 未挂载（main.py 未 include_router、前端无路由入口）为孤儿件，可择期清理 |

### 4.7 规模化升级（v1.22 新增，触发制，与主线并行）

> 来源：《SpecGuard-多角色服务访问流转与规模化升级设计》（2026-08-11，代码实证）——当前 35 人量级架构完全支持；100+ 人 4 大阻塞点：① RunManager 单执行槽（runner.py:877 模块级单例）② 全局 WS 广播无过滤（runner.py:199-207）③ SQLite 单文件单写（user/audit/run_queue/draft_gates/scheduler/sf_*/audit_store 全写 workbench.db）④ 调度忙时跳过不入队（scheduler.py:166-181）。
> 定位：不依赖 S 链主线，与 S8 及之后并行；**T-801/T-805 无依赖、35 人起步即可认领**；T-802~T-804 按「规模信号触发制」由总控人宣布认领；T-806 储备不得认领。触发信号：排队成为常态（连续一周队列>3 或等待>15min）/ 写锁告警（database is locked 或写延迟>100ms）/ 调度 skipped_busy 用户反馈。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-801 | 规模-广播 | WebSocket 订阅隔离 | runner + runs + useRunStream | 订阅按 run_id/workspace 过滤；broadcast 只发订阅该流的连接（scope=all 兼容存量）；执行流页按 run 订阅、全局页只收系统级事件；单次执行广播量=订阅该 run 的连接数（打点验证） | — | 未认领 | | P1｜35 人起步可认领（低风险独立）；在线 WS 连接>30 时优先 |
| T-805 | 规模-守护 | 服务守护与自动拉起 | serve-prod.ps1 + scripts/watchdog.ps1 | Windows 服务化（NSSM/计划任务+Watchdog）：崩溃退出码非零自动重启+退避；复用 /api/health 探活；重启后 fail_stale_running 恢复队列项数 WARN 日志 | — | 未认领 | | P2｜35 人起步可认领（生产正式使用即做，第一位可用性保障） |
| T-802 | 规模-执行 | 执行槽池化（RunManager→RunPool） | runner + user_store + runs + scheduler + RunControl | N 槽并发（默认 2，可配）；互斥维度全局→(workspace,env)（同工作区同环境不并发，不同可并行）；run_queue 加 slot 列；队列 ETA（历史均值）+ 优先级（manual>定时>批量）；abort/超时/断点语义池化下不回归（复用 T-111/T-112/T-118 测试） | T-801 | 未认领 | | P0｜触发制：连续一周队列>3 或等待>15min；架构级，开工前须冻结层评审 |
| T-803 | 规模-调度 | 调度忙时排队（替代跳过） | scheduler + user_store | 忙时入队而非跳过（priority=定时 标记，T-802 多槽+优先级自然消化）；保留 skipped_busy 统计（调度被挤占比=执行槽不足观测指标）；可选错峰窗口 | T-802 | 未认领 | | P1｜挂 T-802 后；触发：定时任务 skipped_busy 用户反馈 |
| T-804 | 规模-存储 | SQLite 写路径演进 | user_store/audit_store + 新增 services/db_metrics.py | 三步渐进：① 观测（写 TPS/锁等待 busy_timeout 命中打点，一周报告）→ ② 审计类批量/异步落盘（攒批 100ms 或 50 条）+ 高频读缓存 → ③ 必要时拆高频表分库或迁 PostgreSQL；验收：峰值写延迟<100ms 无 locked | — | 未认领 | | P1｜触发：database is locked 或写延迟>100ms；观测布点可提前 |
| T-806 | 规模-储备 | 状态外迁与多机横向扩展 | runner/scheduler/存储层 | RunManager 状态 Redis 化或独立执行进程；SQLite→PostgreSQL（随 T-804 ③）；调度器独立进程化；Nginx 反代+多 worker+共享存储；验收：多 worker 队列不重复消费、滚动发布零停机 | T-802/T-804 | 储备 | | 触发制：100+ 且 T-802/804 后仍不足或 HA/多团队隔离硬需求；先评估报告再立项 |

### 4.8 对话操作台 GateDock（v1.23 新增，✅ 全部完成，已归档）

> T-900~T-902 全部完成（2026-08-13，sess-gatedock-dev），明细见《历史区/SpecGuard-总控文档-归档-2026-08-21.md》第二章。

### 4.9 飞书知识图谱（v1.25 新增，✅ 全部完成，已归档）

> T-910~T-930 全部完成（2026-08-14~08-17，sess-feishu-graph/sess-agentchat-material），明细见《历史区/SpecGuard-总控文档-归档-2026-08-21.md》第三章。

### 4.10 AgentChat 材料工作流与 purpose 面板装配（v1.28 新增，与全部主线并行）

> 依据：《远期设计/SpecGuard-AgentChat材料工作流与purpose面板装配专项设计.md》（2026-08-17 定稿）。
> 定位：材料池/材料管理 = agent 对话的背景信息源——①对话即工作台（需求面试对话内上传材料→解析登记→引用进面试上下文）；②面板随方向装配（purposes.panels 声明式消费：前端页签注册表通用/专用分层，通用恒显+专用∩注册表，新 purpose 零前端改动）；③防膨胀硬约束（专用页签只出现在声明它的 purpose 下）。
> 硬边界：不删 MaterialsPanel 不动 M03 入包闸门（瘦身为储备 T-936）；不实现储备页签（ledger/score/deliver/plan/report）；不改引擎冻结层/specstd。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-933 | 材料-上传 | 对话内材料上传 + 引用类型扩展 | AgentChat.tsx + api.ts | 📎 入口走 S3 既有上传端点；上传成功挂 reference 卡片（ChatReference 扩 'material'）随消息进 references；「材料」页签列会话引用材料（标题/状态/摘要）；build | T-932 | ✅ 08-21 主库验收 | sess-material-pool | 并入 T-990 施工（20075e1），随其验收（合并 2b0691a） |
| T-934 | 材料-读取 | read_material MCP 工具 + 白名单登记 | mcp_server/tools/specflow_pack.py + purposes md | summary/topics/raw 三视图 + raw 分页；requirement_interview tools 登记；MCP 用例 ≥3 | — | ✅ 08-21 主库验收 | sess-material-pool | 并入 T-990 施工（c0273de），用例 5 例；RBAC 只读集补登记见 a7a54df |
| T-935 | 收口 | e2e + 全量回归 | test_specstd + 前端 | 上传→引用→read_material 贯通（mock）；全量回归 + release_check + build | T-931~T-934 | ✅ 08-21 主库验收 | sess-material-pool | 并入 T-990 施工（a7a54df）：主库合并形态全量 1906 绿 + engine_modes 39 绿 + release_check PASS + build 成功 |
| T-936 | 储备 | MaterialsPanel 瘦身评估 | — | 对话链路验收后评估入包闸门/六区重组去向，总控人拍板 | T-935 验收 | 储备 | | 触发制，不认领 |


> §4.10 已完成任务（T-931/T-932/T-937~T-952/T-955）明细见《历史区/SpecGuard-总控文档-归档-2026-08-21.md》第四章。

### 4.11 架构反馈升级施工块（v1.29 新增，T-960~T-999）

> 依据：《架构反馈升级/2026-08-21-模块化任务拆分.md》（任务明细/验收要点/粒度/顺序约束全在该文档，此处只登记状态）。来源：08-20 架构体检+八点反馈判定归档 + 08-21 知识库核验与用户拍板（系统包分级注册）。
> 施工纪律：一功能域一棵 worktree（建树 `pwsh new-worktree.ps1 <域>`），主库只验收；提交即推 feature/<域>。

| 任务ID | 阶段 | 任务 | worktree | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|
| T-960 | P0 | 凭据出库（env.sit.yaml client_secret→环境变量回退） | 主库小刀 | — | ✅ 08-21 主库清 | sess-acceptance | 总控人拍板：SIT 公开值但不硬编码仓库——env.sit.yaml client_secret 改 `${SG_TDM_CLIENT_SECRET:}`（仓库零明文），config.py 加回退链（环境变量→devops .env.devops），token_provider 空 secret 诚实报错不发空请求，AGENTS.md 部署要点补说明；实证 load_env 端到端（无变量留空/设 SG_TDM_CLIENT_SECRET 正确注入）+ token/config/env 116 绿 |
| T-961 | P0 | 飞书池 API 绑定 RBAC + 三处错位绑定对齐 | 主库小刀 | — | ✅ 08-21（随 T-996 闭环） | sess-acceptance | feishu-pool→menu-feishu-pool 补绑、三处错位（spec/specflow/zentao/knowledge/workspace→menu-agent、coverage→menu-lifecycle、notify→menu-feedback）随 T-996 menu_guard 对齐一并修正 |
| T-962 | P0 | /quality 死菜单清理 | 主库小刀 | — | ✅ 08-21（随 T-996 闭环） | sess-acceptance | menu-quality 死菜单（/quality 无路由）随 T-996 SEED_MENUS 迁移移除并映射授权至 menu-dashboard，menus 表已无该项 |
| T-963 | P0 | P0/P1 mark 断链修复（priority→mark 映射） | 主库小刀 | — | ✅ 08-21 主库清 | sess-acceptance | scenario_loader priority 注入 tags（P0/P1 已注册 mark）；实证 pytest -m P0 选中 22/-m P1 选中 40（修复前 -m P0 为 0） |
| T-964 | P0 | clarity 假分数清理（specflow_ledger.py:179 占位 62.0） | 主库小刀 | — | ✅ 08-21 主库清 | sess-acceptance | 两处占位（specflow_ledger.py:182 MCP + specflow_decisions.py:193 REST）62.0→诚实降级 pending_manual 不入库；机打 4 维保留；test_specflow_rest 3 处断言同步（5→4 入库/confirm 过滤 id=None/空文本 pending_manual）；test_specstd+engine 1950 绿 |
| T-970 | M-A | 装配归一 bootstrap.py | wt/multi-system | — | ✅ 33682ba（08-21 主库验收） | sess-multi-system | 1 天；顺带修复plan_executor漏注册内置oracles漂移bug |
| T-971 | M-A | system 一等公民化（9 调用点归一+runner 断链+分键缓存） | wt/multi-system | T-970 | ✅ 0fbcd9e（08-21 主库验收） | sess-multi-system | 2-3 天；多用户多系统切换硬前置 |
| T-972 | M-A | 引擎 TDM 泄漏清理 | wt/multi-system | — | ✅ f52d3a9（08-21 主库验收） | sess-multi-system | 1 天；format_spec 2.12.0 三同步 |
| T-973 | M-A | 系统包动态注册（分级：配置型 UI 即时生效/代码型评审后热加载） | wt/multi-system | T-970/T-971 | ✅ 9d4bf6c（08-21 主库验收） | sess-multi-system | 2-3 天；08-21 用户拍板分级方案；sha256评审闸不可绕已测试锁定；前端管理页留M-E/T-996评估，API已全量落地 |
| T-974 | M-A | 多系统 e2e 收口（新系统注册到跑通不重启） | wt/multi-system | T-971~T-973 | ✅ ea2b6c0（08-21 主库验收） | sess-multi-system | 1 天；M-A 五任务全部完成，待主库验收合并 |
| T-975 | M-B | 依赖倒挂翻正（sg_core 下沉，消灭 sys.path.insert） | wt/dep-inversion | — | ✅ 7becec2~a8d2f6f（08-21 主库验收） | sess-dep-inversion | 三步：24 实体下沉+shim；全仓 insert ~200→2（main.py 组合根+backend 运维脚本）；pythonpath 归一；顺手修 audit_store 幽灵路径存量 bug |
| T-976 | M-B | 解环（agent↔mcp_server、graph_index↔specflow）+ 环检查进 release_check | wt/dep-inversion | T-975 | ✅ 2208b0c（08-21 主库验收） | sess-dep-inversion | skill_loader/feishu_paths 下沉解两环；check_import_cycles 进 release_check ④；模块级无环+函数级回边白名单；离线 1599+236 全绿 |
| T-980 | M-C | Agent 评测体系（轨迹断言 golden case + MockLLM 升基建 + metrics 工具维度） | wt/agent-eval | — | ✅ 2026-08-21 主库验收（a10105d：evals 3/3 + test_evals 36/36 + release_check PASS） | sess-agent-eval | 3-5 天；智能层后续一切的地基；T-982 解锁 |
| T-981 | M-C | 测试类型学（dimensions 受控词表+维度断言映射，format_spec 三同步） | wt/test-taxonomy | — | ✅ 08-21 主库验收（合并含返修 ef1547c，1948 绿） | sess-test-taxonomy | 当日完工+返修：八维词表+T10 自检+覆盖面板维度聚合；返修根因=测试以磁盘 rglob 误卷主库本地 gitignored 草稿（约 80 个），改 git ls-files 跟踪事实源；format_spec 2.14.0 三同步+baseline 零漂移 |
| T-982 | M-C | 工具收敛（79→≤30，元数据派生 RBAC/写工具登记，eval 集验证收益） | wt/tool-consolidation | T-980 | ✅ 08-21 主库验收（合并 33931c6 + 修正 e875be2，1949 绿+evals 3/3） | sess-tool-consolidation | stdio 92→39/对内 24≤30，两用途会话可见 15≤15；eval 前后 3/3 持平（收敛未伤正确性，序列 scenario/validate/spec→draft→validate）；元数据派生 RBAC/_KNOWN_WRITERS；合并冲突：AgentChat 取 T-995 重构形态+T-982 合并工具适配（TOOL_TO_STEP name.action 键/toolStepKey/draftWriteUndo）移植 groupMessages.ts+主组件；**修正 e875be2**：33931c6 合并时前端两文件改动漏入库（仅存在于工作树），修正提交补回 |
| T-990 | M-D | 群类型标签 + 吞并 T-933/T-934/T-935（对话内上传/read_material/e2e） | wt/material-pool | — | ✅ 08-21 主库验收（合并 2b0691a） | sess-material-pool | 2-3 天；2026-08-21 认领，当日完工（c0273de/60a1874/ea6d094/20075e1/a7a54df） |
| T-991 | M-D | 话题 category/priority（schema v3，闲聊保留默认过滤） | wt/material-pool | T-990 | ✅ 08-21 主库验收（合并 2b0691a） | sess-material-pool | 2-3 天；拍板③已过（08-21）；当日完工（fd7747e） |
| T-992 | M-D | link 死链修复 + 话题模块 FR 锚点派生 | wt/material-pool | T-991 | ✅ 08-21 主库验收（ff 合并 af4a1cf） | sess-material-pool | 1-2 天；拍板②已过（08-21：FR 锚点派生+留空后补）；当日完工（6ec3989） |
| T-993 | M-D | 跨群话题关联（先设计文档） | wt/material-pool | T-992 | ✅ 08-21 主库验收（合并 3e6ae5b） | sess-material-pool | 3-5 天；设计稿《远期设计/SpecGuard-跨群话题关联设计-T993.md》08-21 总控人评审通过；当日完工（871f2a3） |
| T-995 | M-E | 拆 AgentChat.tsx（行为零变化纯重构） | wt/frontend-ia | T-990 | ✅ 08-21 主库验收（ff 合并 ccb92ef） | sess-frontend-ia | 当日完工：4129→1390 行，22 模块入 pages/agentChat/；后端零改动；M-D 已收官排他约定满足 |
| T-996 | M-E | 菜单收缩 29→15 + SEED_MENUS 迁移 + lifespan 换 on_event + T-973 系统包管理页挂「系统管理」分组 | wt/frontend-ia | T-995 | ✅ 08-21 主库验收（合并 95a4abf，1950 绿） | sess-frontend-ia | 08-21 完工：5 组 17 叶（总览/Agent/场景/执行/系统管理）；后端 f21152e（SEED_MENUS 幂等迁移授权无损映射 _MENU_REMAP_T996+menu_guard 绑定对齐+webhook 二合一+lifespan）+前端 8c380cf（重定向矩阵 14 条/History 三 tab/Lifecycle 两 tab/双审计统一/GitLog·WorkspaceCenter 删除/SystemsAdmin 系统包管理页接 T-973 九端点）；拍板④已过（08-21 按推荐方案）；主库验收：全量 1950 绿/release_check PASS/build 48s/lint 8 持平零新增/vitest 全绿 |
| T-997 | M-E | api.ts 按域拆分 + 前端关键路径 vitest | wt/tool-consolidation（总控人 08-21 指令改挂） | — | ✅ 08-21 主库验收（合并含，1950 绿/vitest 73） | sess-tool-consolidation | 当日完工：api.ts 2033 行 163 export 拆 api/ 24 域模块+门面，vitest 12→73 |
| T-998 | M-F | 文档滞后批量修 + 总控状态对账（T-701~703） | wt/tool-consolidation（空窗复用） | — | ✅ 08-21 主库验收（合并含） | sess-tool-consolidation | 0.5 天；当日完工 |
| T-999 | M-F | workspace.py 拆分 / scenario_runner 抽插值器 / print→logging / user_store 治理 | wt/tool-consolidation（空窗复用） | — | ✅ 08-21 主库验收（合并含；冲突修正 6a0ebc4+1ef8d9c） | sess-tool-consolidation | 各 1-2 天分次；当日四分次全部完工（a print→logging / b user_store 公共化 / c scenario_runner 抽插值器+实例池 / d workspace.py 拆四块） |
| T-1000 | M-E | 工作区自管理 + 系统/工作区二级模型 + 产出反查 | wt/frontend-ia | T-995 | ✅ 08-21 主库验收（合并 177e57c，test_specstd 1720 绿） | sess-frontend-ia | 08-21 当日完工：F1 注册放开登录+owner_emp+system_pending 软校验（runner ensure_system_ready 诚实报错）/F2 /workspace/tree 分组+选择器二级+卡片墙/F3 product_index 三反查+我的活动页+audit 本人查自己；顺手修真 bug：ConformanceReport verdict 重算守卫失效（内容级 ERROR 从未生效）+STRUCT 缺失降级 WARN；合并冲突：与 T-999d/T-999b 交叉——workspace.py 取 T-999d 拆分门面形态+移植 ensure_system_ready、ws_registry 补 owner_emp 五处、api.ts 取 T-997 api/ 目录形态+改动移植 workspace.ts+新 products.ts、product_index/notify 测试 user_store 旧名 _connect/_LOCK→db_connect/DB_LOCK（修正 6a0ebc4/1ef8d9c）；拍板已过（08-21 按推荐方案）；设计单《架构反馈升级/2026-08-21-M-E-工作区自管理与产出反查-设计单.md》 |
| T-1001 | M-D | 话题工作台体验升级：专注模式 + 话题列表化（搜索/排序）+ 编辑弹框（原文并排）+ 手动重关联原文 | wt/material-pool | T-993 | ✅ 08-23 主库验收（合并 66cb8e7，1726 绿/vitest 83/lint 8 持平；追修合并 0f49a25，vitest 92） | sess-material-pool | 08-23 当日完工（总控人直接派工四点需求）。F1 页面级专注模式（类 AgentChat K-039：临时态不持久化+ESC 退出，隐藏页头/状态卡/监听卡/页签条，双栏 h-calc 占满）/F2 泳道平铺→紧凑列表行+搜索（标题/摘要/关键词多词AND）+排序（时间双向/消息数/优先级）+搜索排序持久化（体验基线①），筛选逻辑抽 topicList.ts 纯函数 10 单测/F3 TopicEditModal 编辑弹框：左原文右话题并排（1080px/70vh，消息渲染抽 ChatMessageView.tsx 共享：loadChatMessages+useChatMedia+MessageBody）/F4 message_ids 勾选重关联（按话题全日加载防静默丢关联；window/days 前端按选中消息换算；md 伪 id 诚实禁改提示更新本群；快照缺失关联如实计数提示；edit_candidate 扩参+空集 400）；验证：test_specstd 1726 绿（+6）/vitest 83 绿（+10）/build 成功/lint 8 errors 持平零新增/release_check PASS。**追修 0f49a25**（sess-acceptance，总控人实测搜索/排序未生效上报）：根因=已确认话题双存（_topics.yaml+facts）致 candidates/confirmed 同 id 双份，列表 key 撞车撕裂渲染（计数变列表不变）——dedupeTopics 前端去重（页头 byId 同口径）+标签筛选新需求落地（词频芯片行多选 AND 持久化）；浏览器实证：BUG→2 项精确命中/全部 18→9 去重/排序生效；经验包已登记；后端 confirmed 遗留重叠退役另立任务 |
| T-1002 | M-D | wt 清理（删 7 棵已收官树保留 material-pool）+ hover 联动改按钮定位原文 + 勾选原文生成话题（补充内容） | wt/material-pool | T-1001 | ✅ 08-23 主库验收（合并 e1a9309，test_specstd 1735 绿/vitest 92/lint 8 持平） | sess-acceptance | 08-23 总控人直接派工三项：①删 7 棵已收官树（agent-eval/dep-inversion/engine-upgrade/frontend-ia/multi-system/test-taxonomy/tool-consolidation，零未提交改动+本地远端全并入 master，释放 frontend-ia 459MB node_modules）；②hover 联动退役（总控人拍板）：TopicCard 去 onSelect/容器 onClick，「⌖ 定位原文」按钮显式驱动时间轴高亮+滚动（入库卡与草案段一致，再点取消）；③勾选原文生成话题+补充内容：时间轴勾选模式（md 伪 id 诚实禁用）→ComposeTopicModal（左已选可移除/右表单留空 LLM 补全，extra_context 拼 prompt）→后端 compose_topic_from_messages（id 反查所属日/缺失 KeyError 404 防静默丢关联/草案追加同键不动话题库）→路由 /topics/compose（空关联 400/模型未配 400 弹层就地配）；测试：服务 5+路由 4（topic_cluster+t948_router 75 绿）/test_specstd 1735 绿（+9）/engine_modes 39/vitest 92 绿/build 42s/lint 8 errors 持平（触碰 4 文件 0 errors）/release_check PASS；浏览器实证：定位按钮×4/勾选模式 60 复选框/动作条计数联动（弹框深验因 IAB 动作通道不稳未全通，组件已挂载+逻辑经单测）；总控§6 登记 8 文件 |
| T-1003 | M-D | 「飞书材料池」文案改「飞书话题」 | wt/material-pool | T-1002 | ✅ 08-23 主库验收（合并 4eb9c85） | sess-acceptance | 08-23 总控人拍板改名：页面标题/📦 话题材料页签/空态文案 + 左侧菜单种子 label（_migrate_menus_t996 启动 UPDATE 分支同步存量库，实证 init_db 后=飞书话题/旧 label 再迁移=飞书话题，多用户部署重启即生效）；路径 /feishu-pool 与 menu_key 不动（授权/路由零影响）；build 41s/lint 8 errors 持平/rbac+menu 8 绿/release_check PASS；浏览器实证菜单/标题/页签三处新名生效旧名零残留 |
| T-1004 | M-D | 监听运行中 + 监听范围收进同步设置弹层 | wt/material-pool | T-1003 | ✅ 08-23 主库验收（合并 3eee8f2） | sess-acceptance | 08-23 总控人拍板：主页移除监听状态/范围两卡（只留计数条，信息密度回归内容本体）；FeishuWatchSettings 弹层顶部加监听运行状态条（watcherStatus 开弹层即拉）+当前监听范围只读摘要（用户 scope/群 kind/文档计数+页签引导）——状态/范围与配置入口同处；材料页签承接「按监听用户筛选」芯片行（筛选入口不丢）；主页 watcher 状态清理；build 38s/lint 8 errors 持平（触碰 2 文件 0 errors）/vitest 92 绿/feishu 259 绿/release_check PASS；浏览器实证主页两卡移除+计数条保留（弹层深验因 IAB 动作通道不稳未全通，组件编译挂载已证） |
| T-1005 | M-D | 话题页签挪到材料池前面 | wt/material-pool | T-1004 | ✅ 08-23 主库验收（合并 1846999） | sess-acceptance | 08-23 总控人拍板：页签顺序对调（💬 话题 在前 / 📦 话题材料 在后）+默认落地页由材料池改话题（话题是主工作面；localStorage 恢复逻辑不变——存 materials 仍恢复材料页，非法值/隐私模式回退话题页）；build 38s/lint 8 errors 持平/vitest 92 绿/release_check PASS；浏览器实证页签顺序+默认话题页生效 |
| T-1006 | M-D | 材料池群聊详情弹层优化（消息流渲染） | wt/material-pool | T-1005 | ✅ 08-23 主库验收（合并 745e109） | sess-acceptance | 08-23 总控人反馈「群聊类型点开显示需要优化」：群聊详情不再整段 md 一坨（消息粘连/图片全占位符）——openDetail 并行拉 JSONL 事实源，有消息行时改 ChatDetailView 消息流（与话题工作台时间轴/编辑弹框同源 MessageBody+useChatMedia：发送人配色/图片真实加载·失败标注·转述 caption/附件下载/大图预览），md 视图收折叠底稿供对照，无 JSONL/失败回退原 md 渲染；文档/妙记详情不动；build 42s/lint 8 errors 持平/vitest 92 绿/release_check PASS（浏览器深验因 IAB 动作通道当日持续不稳未全通，渲染件三处已实证同源复用） |
| T-1007 | M-D | 材料列表分类型 tab + 分页（附：群聊材料存储口径查证） | wt/material-pool | T-1006 | ✅ 08-23 主库验收（合并 d385300） | sess-acceptance | 08-23 总控人两问：①查证——群聊消息非按话题维度保存：按「群×日」快照（chats/{sha8}/{yyyymmdd}.jsonl+md），message_id 幂等合并（同键覆盖/撤回刷新，多用户重复同步无害化），话题卡只引用 message_ids 不复制内容——材料-话题是引用关系非双份存储，无重复记录问题；②材料 tab 全部/群聊/文档/妙记（计数徽标持久化，与监听用户筛选叠加）+分页 10 条/页（>1 页出上下页条，换 tab/筛选回第 1 页）+tab 行口径说明上墙+空态分用户/类型两口径；顺手修两 TS 坑（组件内 type 声明与 as const[] 断言均触发 TS2304）；build 39s/lint 8 errors 持平/vitest 92 绿/release_check PASS；浏览器实证 tab 计数（全12/聊12/文0/记0）/切换过滤/空态/分页第1-2页共12条全过 |
| T-1008 | M-D | 同步设置分 tab 减负 + 监听用户定位答疑/入口引导 + 自动话题分类双阈值 | wt/material-pool | T-1007 | ✅ 08-23 主库验收（合并 644046c，test_specstd 1746 绿/vitest 92/lint 8 持平） | sess-material-pool | 08-23 总控人三点派工：①弹层拥挤→4 tab（新增「⚙ 通用」承接监听状态详情/范围摘要/定时同步/自动分类阈值），页头收敛一行合并状态，保存移固定页脚，页签持久化 sg-feishu-watch-tab；②监听用户答疑——添加入口本在（先搜后加两步），空态补引导+诚实语义文案（群消息始终来自授权群全量；用户=妙记/文档按人拉取+材料页筛选维度；group_sender 仅影响事件直写发送人过滤，每日 03:00 校对全量覆盖）；③自动拉取查证——已内建（lark-cli event consume im.message.receive_v1 秒级直写+每日 03:00 校对+chat_sync_minutes 定时），本任务补自动话题分类双阈值：事件直写记账积累≥50 条 scoped 重聚 / 未达条数距上次≥60 分钟且有新消息也触发（.auto_cluster.json 持久化，topic_days=0 不记账）；顺手修真缺口×2——watcher-status running 注册表存活即 true（0 用户也显示「监听运行中」，总控人截图实锤）改 running=count>0；PUT /watch start_user 幂等跳过致运行中改 chat_sync_minutes 需进程重启（T-952 缺口）改 reconfigure_user 热重挂；scoped 聚类 only_chat_ids 单群重聚不全量跑 LLM；验证：test_specstd 1746 绿（+11：双阈值 7/归一化/scoped 2/热重载 1）/engine_modes 39/test_engine 230/release_check PASS/build 41s/lint 8 errors 持平（触碰 7 文件 ruff 清零+顺手修 router F401/E741）/vitest 92 绿；总控§6 登记 7 文件 |
| T-1009 | M-D | 定位原文后右栏话题卡消失修复 | wt/material-pool | T-1008 | ✅ 08-23 主库验收（合并 b3c489a） | sess-material-pool | 08-23 总控人实测「点击定位找到了原文但话题没了」——根因双因叠加：①专注模式双栏行无高度上限被内容撑高（时间轴数千 px），右栏话题卡内容停在行顶，flex stretch 只拉长容器，页面滚动后右栏可见区只剩拉伸空白；②定位 scrollIntoView(block:center) 连带滚动全部可滚动祖先（含 window）把右栏顶出视口。修复：专注模式行高钉死 h-[calc(100vh-130px)] 两栏各自内部滚动（Dashboard 同款先例）+定位改容器内 scrollTo（getBoundingClientRect 换算，只滚时间轴不动页面）；非专注模式同样受益（此前页面也小幅跳动）；验证：build 38s/lint 8 errors 持平/vitest 92 绿/release_check PASS（纯前端 1 文件零后端 delta，免全量 test_specstd）；总控§6 登记 1 文件 |
| T-1010 | M-D | 「系统配置」三栏合一（系统包/工作区/环境配置+DB）+ internal_token 提取通用配置 + 系统设置改基础设置 | wt/system-config | T-1009 | 🔧 开发完成待验收 | sess-system-config | 08-24 总控人派工：工作区中心在前端找不到入口（种子在总览组但未授权角色），拍板三页合一——①新页 SystemConfig 三栏：栏1系统（注册/manifest启停/热重建/extensions评审闸/assertions，自 SystemsAdmin 迁入）→栏2工作区（随栏1系统过滤的卡片+注册表单系统下拉锁栏1+文档浏览折叠区，自 WorkspaceCenter 迁入）→栏3环境配置（scope=shared通用[sso+internal_token]/system本系统，Monaco 带回读+结构化预览，自 EnvironmentConfig 迁入）+数据库卡（自 Settings db tab 迁入，system 不再写死 tdm/env 选项跟随系统枚举）；②internal_token 物理搬家 systems/tdm/config/env.sit.yaml→systems/_shared/config/env.sit.yaml（共享打底合并语义引擎零改动，load_env 实测 internal_token/db/sso 键全在）；③Settings 删 db tab 改名「基础设置」（剩 models/audit/run/git）；④菜单收编：种子新增 menu-system-config、删 menu-env-config/menu-systems/menu-workspace，_MENU_REMAP 三旧键无损映射授权→menu-system-config，menu-settings label 改基础设置（upsert UPDATE 分支存量自动同步）；路由 /system-config，旧三路 REDIRECT 301；删三旧页面（仅 App.tsx 引用）；验证：build 34.8s/oxlint 8 errors 持平/vitest 92 绿/knip 持平/test_specstd 1750 绿（+4 迁移测试：旧键映射删除/label 同步/幂等/全新库）/release_check PASS；总控§6 登记 12 文件 |

---

## 5. 会话注册表（开工必填）
> 表行格式：`| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |`
| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |
|---|---|---|---|---|
| sess-multi-system | M-A 多系统贯通施工 | T-970（✅33682ba）→ T-971（✅0fbcd9e）→ T-972（✅f52d3a9）→ T-973（✅9d4bf6c）→ T-974（✅ea2b6c0） | 2026-08-21 | M-A 全部完成待验收。要点：bootstrap组合根（顺带修复plan_executor漏注册oracles）、resolve_system唯一口径+runner断链修复（SPEC_GUARD_SYSTEM/SG_SCENARIOS_ROOT按工作区注入）、引擎grep零tdm（format_spec 2.12.0/2.13.0三同步）、系统包分级动态注册（sha256评审闸不可绕）；离线全绿227+39+1622+release_check PASS |
| sess-lark-dev | 飞书 CLI 集成施工 | T-701（✅）→ T-702（✅）→ T-703（✅ 形态变迁） | 2026-08-11 | T-998 对账 08-21 全部落地；T-703 孤儿件（lark_binding router + LarkBinding 页未挂载）留痕可清理 |
| sess-agentchat-material | AgentChat 材料工作流 + purpose 面板装配施工 | T-930（✅）→ T-931/T-932（✅）→ T-937~T-942（✅）→ T-933 ~ T-935（✅ 由 sess-material-pool 并入 T-990 施工，08-21 主库验收） | 2026-08-17 | T-930 监听选择器+可读层（aefd802/e4633a2/b1d15ff）；T-931/T-932 面板装配（42c851a）；T-937 同步设置体验（b002749）；T-938 群聊后台预热（cdf8d6e）；T-939 材料原文+图片直出（f66330b+1c90b83）；T-940 监听用户视图+按人切换+飞书直链（4a7f656）；T-941 同步设置去重+错误人话化+搜索解耦（871d64c）；T-942 授权闭环入弹层（006c5c2）；T-933~T-935 已随 T-990 吞并完成并验收，T-936 储备 |
| sess-material-pool | M-D 材料池演进施工（wt/material-pool 树） | T-990（✅ 08-21 验收合并 2b0691a）→ T-991（✅ 同批验收）→ T-992（✅ 6ec3989 已验收）→ T-993（✅ 871f2a3 已验收）→ T-1001（✅ 08-23 验收合并 66cb8e7） | 2026-08-21 | T-990 五提交+T-991 fd7747e+T-992 6ec3989+T-993 871f2a3；T-1001 话题工作台体验升级（总控人直接派工）；树已 reset 至 origin/master 6e7d79b 再出发；本会话文件读写一律用树路径，只跑离线测试与前端 build，提交即推 |
| sess-acceptance | 主库验收 + 验收后追修施工 | T-1001 主库验收（66cb8e7 回标 fe6c34f）→ T-1001 追修（✅ 0f49a25，搜索/排序根因修+标签筛选）→ T-1002（✅ e1a9309，wt 清理+定位按钮+勾选生成话题）→ T-1003（✅ 4eb9c85，文案改名飞书话题）→ T-1004（✅ 3eee8f2，监听状态/范围收进同步设置）→ T-1005（✅ 1846999，话题页签提前）→ T-1006（✅ 745e109，群聊详情消息流）→ T-1007（✅ d385300，材料分类tab+分页）→ T-1008（✅ 644046c，同步设置4tab+监听用户答疑+自动话题分类双阈值）→ T-1009（✅ b3c489a，定位原文右栏话题消失修复） | 2026-08-23 | 追修起因：总控人实测搜索/排序未生效；诊断走浏览器实证+真实数据复演（根因=同 id 双份 key 撞车，见经验包 2026-08-23 条目）；施工在 wt/material-pool 树（规程），主库只验收合并 |
| sess-test-taxonomy | M-C 测试类型学施工（wt/test-taxonomy 树） | T-981（✅ 8df59e1+ef1547c 待主库复验） | 2026-08-21 | 当日完工+当日返修：sg_core/test_dimensions 八维词表+证据提取+映射检查（DIM_VOCAB/DIM_MISSING/DIM_MAP）；format_spec 2.14.0 三同步（§1.2 doc 选填字段+§五 T10，baseline 重建比对零漂移）；validator 双路+spec_validator T10；compute_coverage 维度聚合+CoveragePanel 维度分布区块；generate-scenario 1.1.0 测试设计方法；24 入库场景补标注零告警；返修：存量回归测试口径磁盘 rglob→git ls-files（主库本地 gitignored 草稿约 80 个被误卷根因），合并形态 108 文件复演零误炸；离线全绿（39+1948）+release_check PASS+前端 build 成功 |
| sess-tool-consolidation | M-C 工具收敛 → M-F 收尾施工（wt/tool-consolidation 树） | T-982（✅ 08-21 主库验收合并 33931c6）→ T-998（✅ 待验收）→ T-999（✅ a/b/c/d 四分次，待验收）→ T-997（✅ 待验收） | 2026-08-21 | tool_meta 元数据单一事实源+consolidate 合并器（17 组 77→24）；side_effect/RBAC/doc 足迹全派生（_KNOWN_WRITERS 与 _RBAC_READONLY_TOOLS 手工清单废除）；purpose domains 领域子集两用途 15 工具；顺手修 specflow_refs 缺 handle 与 audit 未登记两存量缺口；eval 前后 3/3 持平 |
| | | | | |

---

## 6. 文件变更登记表（改文件前必填）
> 协议：
> ① 改文件**前**登记一行：路径 + 你的会话ID + 登记时间 + **修改前hash**（`python3 sg-hash.py <路径>`），状态=登记中，修改后hash留空；
> ② 改完**立刻**回填修改后hash，状态=已完成；
> ③ 同一文件已有「登记中」行且会话ID不是你 → **停手**，该文件正被别的会话修改；
> ④ 你要改的文件实际hash ≠ 登记表最新「修改后hash」 → **停手**，存在未登记变更，先对齐；
> ⑤ 新文件：修改前hash填 `NEW`；删除文件：修改后hash填 `DELETED`。

| 文件路径 | 会话ID | 登记时间 | 修改前hash | 修改后hash | 状态 | 备注 |
|---|---|---|---|---|---|---|
| AGENTS.md | sess-tool-consolidation | 2026-08-21 | a9a84429c233 | | 0890c0155353 | 已完成 | T-982：mcp_server 结构行工具计数 |
| agent/compactor.py | sess-tool-consolidation | 2026-08-21 | 98128bba2653 | | ee2ed56dc04f | 已完成 | T-982 F3：压缩分类按逻辑 id 归一 |
| agent/doc_read.py | sess-tool-consolidation | 2026-08-21 | c766d64a688b | | e06784638d93 | 已完成 | T-982 F3：足迹 guard 元数据 doc_track 派生 + 逻辑 id 归一 |
| agent/doc_write.py | sess-tool-consolidation | 2026-08-21 | b6a88f20afee | | 98875f25adc8 | 已完成 | T-982 F3：同上（写足迹） |
| agent/prompts/system.md.j2 | sess-tool-consolidation | 2026-08-21 | b081e46e60c1 | | 1a6c4b89230d | 已完成 | T-982：合并/声明改造 |
| agent/purpose_loader.py | sess-tool-consolidation | 2026-08-21 | 5d7cb1d7af5c | | a4812303ab10 | 已完成 | T-982 F4：PurposeDef 增 domains 字段 |
| agent/purposes/requirement_interview.md | sess-tool-consolidation | 2026-08-21 | 79b019f9bdcf | | 33c92eec8492 | 已完成 | T-982 F4：领域子集 11+显式 4=15 工具 |
| agent/purposes/test_workbench.md | sess-tool-consolidation | 2026-08-21 | bee6da6ce19e | | 6370378abbc2 | 已完成 | T-982 F4：领域子集 15 工具（specflow/feishu/graph/open 不下发） |
| agent/runtime.py | sess-tool-consolidation | 2026-08-21 | fad14ab896fb | | 86f7f414e630 | 已完成 | T-982 F3：RBAC 派生 + action 粒度白名单/越权拒绝 + resolve_tools 领域子集 + 逻辑 id 文件依赖 |
| agent/session.py | sess-tool-consolidation | 2026-08-21 | b328c5bb4068 | | 187045d01c92 | 已完成 | T-982 F4：白名单快照含 domain: 领域标识 |
| agent/skills/analyze-workspace.md | sess-tool-consolidation | 2026-08-21 | fbe60ed0f9dc | | 3289b815989c | 已完成 | T-982：合并/声明改造 |
| agent/skills/audit-spec.md | sess-tool-consolidation | 2026-08-21 | 0dcb47882999 | | 9080c0105896 | 已完成 | T-982：合并/声明改造 |
| agent/skills/dag-orchestration.md | sess-tool-consolidation | 2026-08-21 | 12b10495dc4d | | 703bddc53c48 | 已完成 | T-982：合并/声明改造 |
| agent/skills/debug-failure.md | sess-tool-consolidation | 2026-08-21 | f4f961b18329 | | 6fdfeafc8b62 | 已完成 | T-982：合并/声明改造 |
| agent/skills/fabricate-test-data.md | sess-tool-consolidation | 2026-08-21 | df560fd674b0 | | bbce4b2c8b18 | 已完成 | T-982：合并/声明改造 |
| agent/skills/feishu-chat.md | sess-tool-consolidation | 2026-08-21 | d2d2e3131ff7 | | 254ccef75fbb | 已完成 | T-982：合并/声明改造 |
| agent/skills/gate-dock-guide.md | sess-tool-consolidation | 2026-08-21 | 91100c7a7f7e | | 2b3143b539af | 已完成 | T-982：合并/声明改造 |
| agent/skills/generate-scenario.md | sess-tool-consolidation | 2026-08-21 | 0639af8ae44d | | e699c5e2a125 | 已完成 | T-982：合并/声明改造 |
| agent/skills/renumber-fr.md | sess-tool-consolidation | 2026-08-21 | f2ddb0071243 | | 9caed7b9821d | 已完成 | T-982：合并/声明改造 |
| agent/skills/spec-chat.md | sess-tool-consolidation | 2026-08-21 | b2284c2d2735 | | 8ea6cb2da38f | 已完成 | T-982：合并/声明改造 |
| agent/skills/update-scenario.md | sess-tool-consolidation | 2026-08-21 | 47548ded0927 | | b9c9c5809a46 | 已完成 | T-982：合并/声明改造 |
| agent/skills/validate-conformance.md | sess-tool-consolidation | 2026-08-21 | 896f93994a19 | | 5c75577a0b4c | 已完成 | T-982：合并/声明改造 |
| agent/skills/zentao-story-point.md | sess-tool-consolidation | 2026-08-21 | f68f8e7c71b8 | | 4068c7b355ab | 已完成 | T-982：合并/声明改造 |
| evals/README.md | sess-tool-consolidation | 2026-08-21 | c62e5954c653 | | 0c235eb2bac3 | 已完成 | T-982：case 格式文档工具名更新 |
| evals/cases/001-list-scenarios.json | sess-tool-consolidation | 2026-08-21 | dfc547d8d4cc | | 455879cc671d | 已完成 | T-982 eval：scenario(action=list) |
| evals/cases/003-draft-write-validate.json | sess-tool-consolidation | 2026-08-21 | d733807c8d93 | | 5728fe53c0c8 | 已完成 | T-982 eval：spec/draft 合并工具名 |
| mcp_server/__init__.py | sess-tool-consolidation | 2026-08-21 | 27717615f717 | | a46f050887ce | 已完成 | T-982：包 docstring 收敛后面貌 |
| mcp_server/server.py | sess-tool-consolidation | 2026-08-21 | c378764baa2f | | 71f79a02271e | 已完成 | T-982：docstring 工具计数 39 |
| mcp_server/tools/attribution.py | sess-tool-consolidation | 2026-08-21 | 62fd54ff9aca | | 5fafd7b38797 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/audit.py | sess-tool-consolidation | 2026-08-21 | 39249c1f5b3d | | 5c0d58656eb7 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/compliance.py | sess-tool-consolidation | 2026-08-21 | 8fed4d213866 | | 5c37edd04299 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/coverage.py | sess-tool-consolidation | 2026-08-21 | 93b055310fa9 | | 1f3ddd35f4ad | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/delta_doc_writer.py | sess-tool-consolidation | 2026-08-21 | 1194806c0684 | | 64ff918ec308 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/draft_writer.py | sess-tool-consolidation | 2026-08-21 | ce1576593260 | | bbf3d669c473 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/fabrication.py | sess-tool-consolidation | 2026-08-21 | 1698a90c7672 | | d14f31ef9d55 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/feishu_fetch.py | sess-tool-consolidation | 2026-08-21 | 540749abc5bf | | ea586deb896b | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/gate_dock.py | sess-tool-consolidation | 2026-08-21 | 0efe269e407b | | 814609df5994 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/graph_index.py | sess-tool-consolidation | 2026-08-21 | 3fc295d33e6c | | 0cdc9a7f4f51 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/info_pack.py | sess-tool-consolidation | 2026-08-21 | 4e84fc0d5917 | | d969adadb447 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/knowledge.py | sess-tool-consolidation | 2026-08-21 | 4790dc4736e9 | | e0aa3a9a745e | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/lark_auth.py | sess-tool-consolidation | 2026-08-21 | 59a99048f1cf | | 8bdb475d568b | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/lark_run.py | sess-tool-consolidation | 2026-08-21 | 5de3ecd69b5b | | 418c445a9115 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/meta.py | sess-tool-consolidation | 2026-08-21 | 65d1fd7d7975 | | db0f47ae2e9f | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/open/dev_context.py | sess-tool-consolidation | 2026-08-21 | 2b75312b6bce | | dc6feda5c64b | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/open/lineage_query.py | sess-tool-consolidation | 2026-08-21 | 8b1dbdee3afd | | 8baa4fbe0b0c | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/open/quality_query.py | sess-tool-consolidation | 2026-08-21 | 67677c467e83 | | 1ebe443a4aff | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/open/refs_query.py | sess-tool-consolidation | 2026-08-21 | 1f0fe8d43c93 | | b20909d3112a | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/open/specflow_refs.py | sess-tool-consolidation | 2026-08-21 | 4ac92512cb31 | | 3af0a191d52e | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/registry_query.py | sess-tool-consolidation | 2026-08-21 | 633c2d2bfef2 | | add28cf21b1d | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/scenario_tools.py | sess-tool-consolidation | 2026-08-21 | 06da4547603c | | d9a1a96339a2 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/side_effect_registry.py | sess-tool-consolidation | 2026-08-21 | 4fb40e43ac26 | | 4d0fcd0221df | 已完成 | T-982 F3：_KNOWN_WRITERS 手工登记废除，分级从 tool_meta 派生（legacy 名兼容查询） |
| mcp_server/tools/spec_reader.py | sess-tool-consolidation | 2026-08-21 | 425cd69269bb | | 8400aa1917c2 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/spec_search.py | sess-tool-consolidation | 2026-08-21 | 61fc8a0ac58d | | 4e41323ccb1e | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/specflow_interview.py | sess-tool-consolidation | 2026-08-21 | 06c4589adf7d | | a3269f04d247 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/specflow_ledger.py | sess-tool-consolidation | 2026-08-21 | 62b8301e61cb | | 4b02316bebff | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/specflow_pack.py | sess-tool-consolidation | 2026-08-21 | 00dfc046b897 | | 3d10c5ff4f10 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/specflow_refs.py | sess-tool-consolidation | 2026-08-21 | 7235c890504e | | 66595cf0a696 | 已完成 | T-982：合并/声明改造 |
| mcp_server/tools/tool_meta.py | sess-tool-consolidation | 2026-08-21 | NEW | | e55ed355b6bf | 已完成 | T-982 F1：元数据单一事实源（side_effect/domain/rbac/doc_track + consolidate 合并器 + 单元派生） |
| mcp_server/tools/validator.py | sess-tool-consolidation | 2026-08-21 | cb035f284120 | | 094927014e9d | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_agent.py | sess-tool-consolidation | 2026-08-21 | 6e1d7f1c10a5 | | ed7f34404c27 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_delta_committer.py | sess-tool-consolidation | 2026-08-21 | b7ed10bdd41d | | 9dc6d5ef1894 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_delta_doc_writer.py | sess-tool-consolidation | 2026-08-21 | 021e18f9b47e | | ba1af69ca018 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_doc_read.py | sess-tool-consolidation | 2026-08-21 | a5bdc90aea13 | | 76cb3f1cff27 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_evals.py | sess-tool-consolidation | 2026-08-21 | 920f1f6ba178 | | 2913bdf91d9e | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_lark_auth.py | sess-tool-consolidation | 2026-08-21 | a1cf98246da7 | | 2477266780d3 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_mcp_server.py | sess-tool-consolidation | 2026-08-21 | e10dfbd0861e | | d8c4556406b0 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_meta_tools.py | sess-tool-consolidation | 2026-08-21 | 0d84ca4f60b9 | | ef0fa4fa8689 | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_open_surface.py | sess-tool-consolidation | 2026-08-21 | 7381fec4bf17 | | dfec78c92d6f | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_purpose.py | sess-tool-consolidation | 2026-08-21 | a443c1601170 | | 4fd458834d4c | 已完成 | T-982：合并/声明改造 |
| test_specstd/test_skill_governance.py | sess-tool-consolidation | 2026-08-21 | cae4f4f15b2c | | efb062d9ddd1 | 已完成 | T-982：合并/声明改造 |
| workbench/backend/routers/agent.py | sess-tool-consolidation | 2026-08-21 | 78b134425d8f | | e7006941acb3 | 已完成 | T-982 F4：resolve_tools 透传 domains；材料引用引导文案改 pack(action=read_material) |
| workbench/frontend/src/pages/AgentChat.tsx | sess-tool-consolidation | 2026-08-21 | 9751a8d0ae12 | | 9b851426e197 | 已完成 | T-982：步骤分组 name.action 键 + draft action 判定 + 调试文案 |
| specflow/feishu_pool/cross_chat.py | sess-material-pool | 2026-08-21 | NEW | | 6817c23c773e | 已完成 | T-993 F1：跨群关联推荐引擎（确定性预筛零LLM + LLM精筛可选降级） |
| workbench/backend/routers/feishu_pool.py | sess-material-pool | 2026-08-21 | 82d150372549 | | 9901c72cb301 | 已完成 | T-993 F2：relate/relations/cross-refine 三端点 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-material-pool | 2026-08-21 | eeeec105a941 | | e5d6e83591a4 | 已完成 | T-993 D5：list_pool_topics 附确定性预筛 cross_suggestions |
| graph_index/builder.py | sess-material-pool | 2026-08-21 | a79cb643f5dd | | cf3dbc61cbe6 | 已完成 | T-993 D6：links 按 edge 分派边类型（mentions/relates 复用预留类型仅 tp↔tp）——现状不分会全建成 mentions |
| workbench/frontend/src/api.ts | sess-material-pool | 2026-08-21 | 9002b3a6cbee | | a9d0966a5501 | 已完成 | T-993：TopicRelation/CrossChatCandidate 类型 + relate/relations/crossRefine API |
| workbench/frontend/src/components/TopicCard.tsx | sess-material-pool | 2026-08-21 | a8fb2c696369 | | 4df8474ddb93 | 已完成 | T-993 D7：「🔗 N 群」徽标 + onOpenRelations 回调 |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-material-pool | 2026-08-21 | c756b53474fe | | 3223e898263e | 已完成 | T-993 D7：关联抽屉（并排卡+跳原文）+ 跨群推荐位（预筛清单+精筛按钮+关联/忽略） |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-material-pool | 2026-08-21 | 5c528aea0760 | | 8c1a8138a1df | 已完成 | T-993：loadTopics 透传 cross_suggestions 给工作台 |
| test_specstd/test_cross_chat.py | sess-material-pool | 2026-08-21 | NEW | | 19732d04bde7 | 已完成 | T-993 F1：预筛条件矩阵/连通分量/LLM精筛降级 |
| test_specstd/test_feishu_t948_router.py | sess-material-pool | 2026-08-21 | d3e6ec7a19ab | | 0af0ba15ed19 | 已完成 | T-993 F2：relate 确认/忽略/404 端点用例 |
| test_specstd/test_feishu_pool_page.py | sess-material-pool | 2026-08-21 | 12ca6ee8ccfa | | 8eca7566a1d3 | 已完成 | T-993：list_pool_topics 附 cross_suggestions 用例 |
| test_specstd/test_graph_index.py | sess-material-pool | 2026-08-21 | bb24301c21f1 | | 32aee1d7707b | 已完成 | T-993：relates 边派生 + 非 tp 端防御 + 存量无 edge 字段兼容 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-material-pool | 2026-08-21 | aa90cb398c61 | eeeec105a941 | 已完成 | T-992：_cluster_once 尾部挂 _suggest_links_for_pool（死链修复：话题/docs/minutes 逐对象建议入队，anchors 空诚实跳过）+ list_pool_topics 模块 FR 锚点派生 |
| workbench/frontend/src/api.ts | sess-material-pool | 2026-08-21 | b0c9c83ec94b | 9002b3a6cbee | 已完成 | T-992：FeishuTopic 加 modules（派生字段，响应时计算不落库） |
| workbench/frontend/src/components/TopicCard.tsx | sess-material-pool | 2026-08-21 | 43b43adecefe | a8fb2c696369 | 已完成 | T-992：模块 chips 展示（关联不到 FR 留空不显示） |
| test_specstd/test_feishu_pool_page.py | sess-material-pool | 2026-08-21 | ad93a8a62aba | 12ca6ee8ccfa | 已完成 | T-992：建议入队/anchors 空跳过/docs+minutes 对象/模块派生 3 用例 |
| specflow/feishu_pool/topic_cluster.py | sess-material-pool | 2026-08-21 | 3c092804048b | ed300417f3d7 | 已完成 | T-991 schema v3：category/priority 枚举 + 三 prompt rubric/few-shot + _PROMPT_VERSION pv3 + derive_priority + normalize/edit/regen + chat_kinds 参数 |
| specflow/feishu_pool/facts.py | sess-material-pool | 2026-08-21 | c272f7e22852 | 7284fc5b74c8 | 已完成 | T-991：_TOPIC_KEY_FIELDS 加 category/priority（confirm 提升不丢） |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-material-pool | 2026-08-21 | 64b1c0dcdad6 | aa90cb398c61 | 已完成 | T-991：_cluster_once 建 chat_kinds（watch kind）传聚类 |
| workbench/backend/services/specflow/feishu_review_service.py | sess-material-pool | 2026-08-21 | 3fd320c6a146 | 40d33f73da98 | 已完成 | T-991：复核队列共享可选（base 参数化语义说明） |
| workbench/backend/routers/feishu_pool.py | sess-material-pool | 2026-08-21 | cbb1f284201d | 82d150372549 | 已完成 | T-991：CardUpdate 加 category/priority + draft 端点传 chat_kind + review 三端点 scope 参数 |
| workbench/frontend/src/api.ts | sess-material-pool | 2026-08-21 | cca8e0525a4d | b0c9c83ec94b | 已完成 | T-991：FeishuTopic 加 category/priority 类型 + editTopicCard 参数 + review scope |
| workbench/frontend/src/components/TopicCard.tsx | sess-material-pool | 2026-08-21 | c758631988c6 | 43b43adecefe | 已完成 | T-991：分类/优先级徽标 + 编辑表单两下拉 |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-material-pool | 2026-08-21 | 2f968442a1e3 | c756b53474fe | 已完成 | T-991：分类筛选 + 闲聊默认过滤开关（localStorage）+ 泳道优先级排序 |
| workbench/frontend/src/components/FeishuReviewPanel.tsx | sess-material-pool | 2026-08-21 | 2c2c408508bb | 46d0d12545d5 | 已完成 | T-991：复核队列「我的/共享」切换（useCallback 修 exhaustive-deps） |
| test_specstd/test_feishu_topic_cluster.py | sess-material-pool | 2026-08-21 | 3e951b846c5b | ad57c201c8f1 | 已完成 | T-991：TestSchemaV3 8 用例（推导/聚类产出/闲聊保留/修订保留/normalize/edit/draft/regen） |
| test_specstd/test_feishu_t948_router.py | sess-material-pool | 2026-08-21 | 69658b0a31da | 48ca673614ab | 已完成 | T-991：PUT card category/priority 成功 + 非法枚举 400 |
| test_specstd/test_audit.py | sess-tool-consolidation | 2026-08-21 | 5c0e8abf4ff1 | | 82bb332ca03f | 已完成 | T-982：audit 技能断言改合并工具名 |
| evals/baseline_t982/metrics_before.jsonl | sess-tool-consolidation | 2026-08-21 | NEW | | af9c5253817a | 已完成 | T-982 eval 收敛前后对比证据 |
| evals/baseline_t982/report_before.md | sess-tool-consolidation | 2026-08-21 | NEW | | c008fcb361e5 | 已完成 | T-982 eval 收敛前后对比证据 |
| evals/baseline_t982/metrics_after.jsonl | sess-tool-consolidation | 2026-08-21 | NEW | | 988cec6bce4f | 已完成 | T-982 eval 收敛前后对比证据 |
| evals/baseline_t982/report_after.md | sess-tool-consolidation | 2026-08-21 | NEW | | d807ab97a421 | 已完成 | T-982 eval 收敛前后对比证据 |
| test_specstd/test_feishu_review.py | sess-material-pool | 2026-08-21 | bbab61374d7f | 18bc3b5f8de7 | 已完成 | T-991：共享队列跨用户可见 + 路由 scope 路由 2 用例 |
| test_specstd/test_feishu_pool_page.py | sess-material-pool | 2026-08-21 | 20b0abaf2d33 | 6861071765a3 | 已完成 | T-991：_cluster_once mock 签名适配 chat_kinds + kinds 断言（补登记：动它时才发现未列） |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-material-pool | 2026-08-21 | da519c270d54 | 64b1c0dcdad6 | 已完成 | T-990 群类型标签：_CHAT_KINDS 枚举 + _clean_chats 归一化（镜像 users 模式） |
| workbench/frontend/src/api.ts | sess-material-pool | 2026-08-21 | 88b5bebaad67 | cca8e0525a4d | 已完成 | T-990/T-933：FeishuWatch.chats 加 kind + FEISHU_CHAT_KINDS 导出 + previewMaterial 客户端 |
| workbench/frontend/src/components/FeishuWatchSettings.tsx | sess-material-pool | 2026-08-21 | c2d0ebae46d4 | 4fe721777def | 已完成 | T-990 群类型标签：表单行 kind 选择 + 回显/提交 |
| workbench/frontend/src/components/useChatOptions.ts | sess-material-pool | 2026-08-21 | 3179db312d82 | 4de23f8b2c46 | 已完成 | T-990：ChatOption 透传 kind（快照群+watch 群双路径） |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-material-pool | 2026-08-21 | c68ee50bf444 | 2f968442a1e3 | 已完成 | T-990：群下拉文案带 kind |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-material-pool | 2026-08-21 | ede4f3cac462 | 5c528aea0760 | 已完成 | T-990：授权群聊卡 kind 徽标 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-material-pool | 2026-08-21 | 961c92ee762c | 9751a8d0ae12 | 已完成 | T-933：🧾上传走 S3 端点 + ChatReference 扩 material + 📎材料页签（SIDE_TABS+MaterialsRefPanel 三态+刷新） |
| workbench/backend/routers/agent.py | sess-material-pool | 2026-08-21 | 03d797ed5cd1 | 8bcbb9327474 | 已完成 | T-933：_process_references 加 material 分支（标识/文件名/状态注入+workspace 校验） |
| agent/runtime.py | sess-material-pool | 2026-08-21 | 2420441bc0e2 | 4a3bb7f20d46 | 已完成 | T-933/T-935：system prompt 补 @材料说明 + _RBAC_READONLY_TOOLS 登记 read_material |
| agent/purposes/requirement_interview.md | sess-material-pool | 2026-08-21 | d27cfa18e450 | 79b019f9bdcf | 已完成 | T-934：tools 白名单登记 read_material |
| mcp_server/tools/specflow_pack.py | sess-material-pool | 2026-08-21 | b4ce4c04cf01 | 00dfc046b897 | 已完成 | T-934：read_material 工具（summary/topics/raw 三视图 + raw 分页） |
| test_specstd/test_feishu_sync.py | sess-material-pool | 2026-08-21 | a1872f5da59d | cc6efc90efe2 | 已完成 | T-990：kind roundtrip 2 用例（非法枚举归空/旧配置兼容） |
| test_specstd/test_specflow_materials.py | sess-material-pool | 2026-08-21 | eee48fc93262 | 24b18b53efa4 | 已完成 | T-934：TestReadMaterial 5 用例（三视图/分页/未知id/非法section） |
| test_specstd/test_mcp_server.py | sess-material-pool | 2026-08-21 | a5747952d23d | ddad8e227c7f | 已完成 | T-934：ALL_TOOLS 计数 91→92 + expected 集合加 read_material |
| test_specstd/test_agent.py | sess-material-pool | 2026-08-21 | 022fe6e8fd73 | ae585044d7de | 已完成 | T-935：TestMaterialE2E 2 用例（上传→引用→read_material 贯通 + 诚实 missing） |
| docs/远期设计/SpecGuard-AgentChat材料工作流与purpose面板装配专项设计.md | sess-agentchat-material | 2026-08-17 | NEW | fcd7c6055d45 | 已完成 | §4.10 专项设计定稿（T-931~T-936 拆解 + D1-D6 决策：页签注册表装配/上传链路复用 S3/read_material 工具/MaterialsPanel 不删） |
| docs/superpowers/specs/2026-08-18-同步设置体验修复-design.md | sess-agentchat-material | 2026-08-18 | NEW | 9f11b2e2081a | 已完成 | T-937 设计定稿（D1-D5：弹层秒开/手填删除/下拉搜索化/resolve-doc 链接解析/回显统一） |
| test_specstd/test_feishu_pool_page.py | sess-agentchat-material | 2026-08-18 | 988569618cc5 | 2752d304d5cc | 已完成 | T-941+T-942：search_docs/错误包装 4 用例；文案断言改指向弹层内授权 |
| workbench/frontend/src/components/FeishuWatchSettings.tsx | sess-agentchat-material | 2026-08-18 | 96a59ec09b85 | c79d66899165 | 已完成 | T-942：弹层内嵌授权块（状态/发起/二维码+3s轮询/完成自动重载群聊） |
| docs/upgrade-plans/2026-08-18-T947-话题人工介入工作流-开发任务.md | sess-agentchat-material | 2026-08-18 | NEW | ca4df2ae5289 | 已完成 | T-947 自包含开发任务文档（需求决策/代码地图/函数签名/TDD 清单/验收标准/治理），待新会话领取开发 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-t947-dev | 2026-08-18 | — | b0bd110cf6b3 | 已完成 | T-947：话题工作区（选源拉原文/AI 分类分段卡勾选/生成覆盖）+单卡编辑/重生成 |
| test_specstd/test_reference_envs.py | sess-agentchat-material | 2026-08-17 | — | 5ded3b3dff1e | 已完成 | 顺手修复：多系统改造后 patch 点迁移 SYSTEMS_TDM→_SYSTEMS_ROOT（旧 patch 失效曾污染真实 env.sit.yaml，已恢复+守卫验证） |
| docs/引擎升级建议-第三批-对标开源引擎评估.md | sess-master | 2026-08-07 | 477f8c866bf4 | 07f403994fe0 | 已完成 | 补写 v2 复核修正与施工规格（§六） |
| docs/远期设计/verifier/runs/2026-08-07T-task-sync-v1.md | sess-master | 2026-08-07 | NEW | 571ec4a458a1 | 已完成 | 原型更新验收运行记录：屏完整性/ID 抽查/node --check 全 PASS；截图项本环境未执行已注明；28功能/298FR 口径存疑留待复核 |
| docs/远期设计/verifier/runs/2026-08-07T-s1-plain-v1.md | sess-master | 2026-08-07 | NEW | 91ce655d4c20 | 已完成 | S1 改写验收运行记录：屏完整性/新增内容/node --check 全 PASS；截图项未执行已注明 |
| docs/远期设计/verifier/runs/2026-08-07T-s8-flow-v1.md | sess-master | 2026-08-07 | NEW | 9262af31bf84 | 已完成 | S8 流转图验收运行记录：屏完整性/新增内容/node --check 全 PASS；截图项未执行已注明 |
| docs/远期设计/specguard-vision/index.html | sess-master | 2026-08-07 | 19759ec51183 | 64d328aaaad3 | 已完成 | 文案修订：标语「未来 AI 时代」→「AI 时代」（S8 tip-bar + ctx-term 两处，现在已是 AI 时代）；轻量改动屏结构未动，grep 复验「未来」零残留 |
| docs/远期设计/app/index.html | sess-master | 2026-08-07 | 19759ec51183 | 64d328aaaad3 | 已完成 | specguard-vision 同内容副本，同步覆盖（cmp 一致） |
| docs/远期设计/SpecGuard-知识体系设计.md | sess-master | 2026-08-07 | cba09a346b8c | faa5074979ee | 已完成 | 补 §4.5 面板呈现（依据透明·阅读足迹 V1/V2/V3）+ §8 分期新增 S0.5 行 |
| workbench/frontend/src/components/FileViewer.tsx | sess-s05-dev | 2026-08-07 | efdc8aea6a7d | 0c53577cf2a9 | 已完成 | T-511：DocHunk 类型 + LinedText 行号渲染 + hunks 行区间高亮 + ▲ n/N 处 ▼ 导航条（打开即定位） |
| test_specstd/test_doc_read.py | sess-s05-dev | 2026-08-07 | NEW | b1223be9ce32 | 已完成 | T-511：doc_read 事件单测 14 例（触发/不触发/错误跳过/tail hunk/thinking/excerpt 预算） |
| workbench/frontend/src/theme.ts | sess-s05-dev | 2026-08-07 | 1dc0dc5093e4 | 7dc356ad123c | 已完成 | T-511 顺带：删除 rgbTripletToHex 死代码（master 预存构建红之一，npm run build 恢复全绿） |
| mcp_server/tools/sections.py | sess-s05-dev | 2026-08-07 | NEW | 9e316168e0cf | 已完成 | T-512：章节提取纯函数（FR 标题式/列表式锚点、AC 定位、md 标题树、yaml part 行区间；import specstd 正则常量，specstd 零改动） |
| mcp_server/tools/spec_reader.py | sess-s05-dev | 2026-08-07 | d20d1efc9ad7 | 81a7735818df | 已完成 | T-512：read_spec 加可选 anchor/section 参数（章节提取分支不受 200KB 截断影响 + 未命中自愈提示 + 互斥校验） |
| mcp_server/tools/scenario_tools.py | sess-s05-dev | 2026-08-07 | c0b19d070d5f | 8705ccddc0f0 | 已完成 | T-512：read_scenario 加可选 part 参数（doc/flow/verify/covers，保注释文本边界） |
| agent/doc_read.py | sess-s05-dev | 2026-08-07 | 7ddaf7f7f414 | c766d64a688b | 已完成 | T-512：章节标头解析→真实行区间 hunk；read_run_report 改 memo+失败断言段摘录（聚合 JSON 无法映射 run.json 行区间，诚实降级） |
| test_specstd/test_sections.py | sess-s05-dev | 2026-08-07 | NEW | 4f70e4fd4a48 | 已完成 | T-512：sections.py 提取单测 15 例（双形态 FR/AC/标题树/yaml part/未命中） |
| workbench/frontend/src/components/ReadingPanel.tsx | sess-s05-dev | 2026-08-07 | 7181fd2ce1d2 | 671db9bd6fa2 | 已完成 | T-512：卡片摘录跳过章节标头行直接展示段落摘要（hunk 清单/导航已随 T-511 落地） |
| engine/schema_match.py | sess-engine-t501 | 2026-08-07 | NEW | 29bcac60b30b | 已完成 | T-501：fuzzy-match-lite 匹配核心（纯函数 match + oracle_schema_match + register_builtin_oracles），零依赖 |
| test_engine/test_schema_match.py | sess-engine-t501 | 2026-08-07 | NEW | 1dc9bb09f60a | 已完成 | T-501：TDD 先行测试 31 例（类型标记/可选键/数组模式/嵌套递归/键集严格/字面值/失败消息路径/空数组/oracle 包装/注册） |
| conftest.py | sess-engine-t501 | 2026-08-07 | 27e8b2e9d3b7 | 11a7e1ae34a7 | 已完成 | T-501：registry fixture 挂 register_builtin_oracles |
| mcp_server/tools/live_registry.py | sess-engine-t501 | 2026-08-07 | aa8a088ae6f6 | ed6806cb76c7 | 已完成 | T-501：live registry 挂 register_builtin_oracles（validator V9 幻觉拦截可见） |
| workbench/backend/services/format_spec.py | sess-engine-t501 | 2026-08-07 | da58c49856ab | 712087f01d26 | 已完成 | T-501 三同步：§1.8.1 schema_match 用法文档 + 版本 2.4.0→2.5.0 |
| docs/specguard-yaml-format-spec.md | sess-engine-t501 | 2026-08-07 | 5a97f9c939bd | bef8b1511f31 | 已完成 | T-501 三同步：快照重导出 v2.5.0（generate_format_spec_md 直写，导出约定已 diff 验证） |
| mcp_server/tools/meta.py | sess-slim-dev | 2026-08-10 | 654b2805cac8 | 05d4ac5a5674 | 已完成 | T-601：删 switch_mode 工具，META_TOOL_NAMES 仅剩 todo_write |
| agent/prompts/system.md.j2 | sess-slim-dev | 2026-08-10 | a095153ee6c4 | f3b6aa614891 | 已完成 | T-601：删「任务行为指引」章节与 {{ mode_guidance }}，顶部引用改「可用技能」 |
| agent/skills/generate-scenario.md | sess-slim-dev | 2026-08-10 | 81efa43f5605 | 20de32580a5c | 已完成 | T-601：并入 generate.md 独有内容（交互式生成流程 K-021/K-055/硬约束/K-020 工具报错处理） |
| agent/skills/debug-failure.md | sess-slim-dev | 2026-08-10 | 58f61cb47d22 | 31850c7e2ad0 | 已完成 | T-601：并入 debug.md 独有内容（K-052 任务号定位动线），清理「没有 write_draft」腐化表述 |
| agent/skills/audit-spec.md | sess-slim-dev | 2026-08-10 | NEW | b60dcccf5f7c | 已完成 | T-601：新建（audit.md 迁移，V1-V4 分类/分级/硬约束） |
| agent/skills/spec-chat.md | sess-slim-dev | 2026-08-10 | NEW | 0747d2479edd | 已完成 | T-601：新建（chat.md 迁移；keywords 收紧防闲聊误触发，test_skill_trigger 回归验证） |
| agent/skills/analyze-workspace.md | sess-slim-dev | 2026-08-10 | NEW | 6db06e9c6f2c | 已完成 | T-601：新建（analyze.md 迁移，清理「没有 write_draft/validate」腐化表述） |
| agent/mode_loader.py | sess-slim-dev | 2026-08-10 | a30106334b01 | DELETED | 已完成 | T-601：删除（modes 体系退役，无运行时消费者） |
| agent/modes/generate.md | sess-slim-dev | 2026-08-10 | 7a21bf635202 | DELETED | 已完成 | T-601：删除（内容已并入 generate-scenario） |
| agent/modes/debug.md | sess-slim-dev | 2026-08-10 | cbd094ee0d88 | DELETED | 已完成 | T-601：删除（内容已并入 debug-failure） |
| agent/modes/audit.md | sess-slim-dev | 2026-08-10 | 9096796ff16f | DELETED | 已完成 | T-601：删除（内容已迁 audit-spec） |
| agent/modes/chat.md | sess-slim-dev | 2026-08-10 | 68e69765de66 | DELETED | 已完成 | T-601：删除（内容已迁 spec-chat） |
| agent/modes/analyze.md | sess-slim-dev | 2026-08-10 | e7caecd60d4c | DELETED | 已完成 | T-601：删除（内容已迁 analyze-workspace） |
| test_specstd/test_mode_loader.py | sess-slim-dev | 2026-08-10 | 75596c4a1a6e | DELETED | 已完成 | T-601：删除（mode_loader 退役） |
| test_specstd/test_audit.py | sess-slim-dev | 2026-08-10 | 0c24825d1f9b | 893b8d048d6d | 已完成 | T-601：TestAuditMode → TestAuditSkill（断言 load_skill("audit-spec") 内容） |
| test_specstd/test_meta_tools.py | sess-slim-dev | 2026-08-10 | e9f0b595b473 | 79aa8f9c8694 | 已完成 | T-601：TestSwitchModeDeprecated → TestMetaToolsDeprecated（switch_mode 未知工具断言）；META_TOOL_NAMES 断言 1 个 |
| test_specstd/test_agent.py | sess-slim-dev | 2026-08-10 | a7a03731dea1 | 16da42a9e990 | 已完成 | T-601：prompt 断言改 skills 内容（交互式生成流程/Spec 审计技能）；删 test_switch_mode_meta_tool |
| test_specstd/test_multiuser.py | sess-slim-dev | 2026-08-10 | 9fdc455ac0be | 8642c31de60c | 已完成 | T-601：/chat 409 测试改 _run_in_progress 直测；viewer 403 断言移除 |
| AGENTS.md | sess-slim-dev | 2026-08-10 | 274e16b00911 | ea60fa95b6c4 | 已完成 | T-601 同步：去 modes 引用（使用角色/目录结构/智能层约定 3 处） |
| docs/远期设计/specguard-module-design/M03-材料包与信息包.md | sess-master | 2026-08-10 | 9cc20afc3528 | 966ab2f2cb93 | 已完成 | v1.7 同步：specflow 文件布局加 {emp} 层级（未确认私有 → 确认后共享，T-014 验收要点⑤） |
| workbench/backend/routers/drafts.py | sess-s1-foundation | 2026-08-10 | 47cc6fe9d0a4 | 47cc6fe9d0a4 | 已完成 | T-014：经评估无需改动——drafts_dir() 自动感知 emp contextvar，调用点零修改即落私有区 |
| workbench/backend/services/draft_promote.py | sess-s1-foundation | 2026-08-10 | 4891c33a0a53 | 4891c33a0a53 | 已完成 | T-014：经评估无需改动——promote 源读 drafts_dir() 自动落当前用户私有区（确认动作→共享 scenarios） |
| workbench/backend/services/plan_store.py | sess-s1-foundation | 2026-08-10 | b8fbdb9d9796 | b8fbdb9d9796 | 已完成 | T-014：经评估无需改动——plans_dir() 自动感知 emp contextvar |
| workbench/backend/routers/scenarios.py | sess-s1-foundation | 2026-08-10 | d5f164a5e69d | a89aa6b9cb9a | 已完成 | T-014：uploads 走 uploads_dir（私有区） |
| agent/session.py | sess-s1-foundation | 2026-08-10 | 8bd0fd66acaf | 29a1b9bd3063 | 已完成 | T-010：create 加 purpose + _meta.json + list_sessions 返回 purpose |
| workbench/backend/routers/agent.py | sess-s1-foundation | 2026-08-10 | 0739140faa41 | 4b6794cf42fa | 已完成 | T-010/T-011/T-012：POST/PATCH sessions、/purposes 端点、WS purpose 透传+resolve_tools 装配 |
| workbench/backend/services/user_store.py | sess-s1-foundation | 2026-08-10 | 59da70bcae34 | e6d29fc5c8a1 | 已完成 | T-013：VALID_ROLES 加 product、roles 多值列、set_roles（set_role 兼容） |
| workbench/backend/services/auth.py | sess-s1-foundation | 2026-08-10 | c86756bc842f | 011934b73ca8 | 已完成 | T-013：CurrentUser.roles、require_role 交集语义、认证链注入 emp contextvar |
| agent/purpose_loader.py | sess-s1-foundation | 2026-08-10 | NEW | 049e757b2939 | 已完成 | T-012：purpose 加载器（30s TTL，仿 skill_loader） |
| agent/purposes/test_workbench.md | sess-s1-foundation | 2026-08-10 | NEW | 6f9dd1f5974b | 已完成 | T-012：测试工作台用途定义（roles: admin/tester） |
| workbench/backend/services/agent_session_store.py | sess-s1-foundation | 2026-08-10 | NEW | b62481163451 | 已完成 | T-010：agent_sessions 索引表（upsert/list/update_title/archive） |
| scripts/migrate_drafts_emp.py | sess-s1-foundation | 2026-08-10 | NEW | b52611cf82b9 | 已完成 | T-014：存量 drafts 按会话 emp_no 归位（会话 JSONL 扫描归属，无归属保留共享） |
| test_specstd/test_purpose.py | sess-s1-foundation | 2026-08-10 | NEW | 9e954a4993ed | 已完成 | T-010/T-011/T-012/T-013：purpose 不可变/接口/过滤/白名单/审计 17 例 |
| test_specstd/test_workspace_emp.py | sess-s1-foundation | 2026-08-10 | NEW | 0bd56379098c | 已完成 | T-014：emp 维度路径 + 越权校验 + 迁移脚本 12 例 |
| docs/远期设计/specguard-module-design/M01-使命卡片与会话路由.md | sess-master | 2026-08-10 | 1d06e04a6131 | 35a33af18275 | 已完成 | v1.8 同步：用途 roles 并集语义 + 多用途用户多卡（效率保护不变） |
| docs/远期设计/specguard-module-design/M12-多智能体运行时与平台基建.md | sess-master | 2026-08-10 | 324857b1ea01 | 76b0f72ed233 | 已完成 | v1.8 同步：RBAC 角色枚举加 product + 单角色→多角色（require_role 包含任一） |
| specstd/workspace.py | sess-s2-dev | 2026-08-10 | 91f23c8efd9e | 91f23c8efd9e | 已完成 | S2：specflow_dir() 需求侧目录路径函数（emp 维度，随 f804048 提交） |
| specflow/__init__.py | sess-s2-dev | 2026-08-10 | NEW | 129654a7470b | 已完成 | T-020：specflow 顶层包 |
| specflow/interview/__init__.py | sess-s2-dev | 2026-08-10 | NEW | d7a768a3d39d | 已完成 | T-020：interview 子包 |
| specflow/interview/question_bank.py | sess-s2-dev | 2026-08-10 | NEW | 11c266569e9d | 已完成 | T-020：11 章扫描提问维度库 + SPQ/评分缺口反哺模板 |
| specflow/interview/gate.py | sess-s2-dev | 2026-08-10 | NEW | f12f52e2edf6 | 已完成 | T-024：P0 清零确定性纯函数 + 门禁聚合 + 冻结校验 |
| workbench/backend/services/specflow/__init__.py | sess-s2-dev | 2026-08-10 | NEW | 81f7e8abc976 | 已完成 | T-020：specflow 服务包 |
| test_specstd/test_specflow_interview.py | sess-s2-dev | 2026-08-10 | NEW | 3ae2e9850672 | 已完成 | T-020/T-021/T-024：议题卡/生命周期/门禁/提问库单测 36 例 |
| mcp_server/tools/specflow_interview.py | sess-s2-fix | 2026-08-11 | 916de44d261e | c41195259dce | 已完成 | H2 新增 iv_ask_question 登记通道 / M4 emp 留痕 + workspace 缺失拒绝 / M5 read_baseline 真实摘录 / iv_id 格式校验 |
| mcp_server/tools/specflow_ledger.py | sess-s2-fix | 2026-08-11 | 7f98e6fa4610 | 5f6ca1b19598 | 已完成 | M2 workspace 透传 + 评分幂等去重 + 占位分 TODO(F2/S4) 标注 |
| specflow/interview/decision_ledger.py | sess-s2-fix | 2026-08-11 | c77276784b3b | ab0451921457 | 已完成 | M2 gate 函数 workspace 隔离 fail-closed + D-xxx 编号全局唯一（原跨工作区撞主键）+ content_sha 落锤重算 + amend 跨面试拒绝 |
| specflow/interview/iv_lifecycle.py | sess-s2-fix | 2026-08-11 | e7c99e25e920 | b1e944b99911 | 已完成 | validate_iv_id 格式校验（路径拼接入口防穿越）+ 状态机常量区 |
| specflow/interview/topic.py | sess-s2-fix | 2026-08-11 | e477758f688d | 4e7e90152bba | 已完成 | _next_iv_id 并发锁 + load_topic iv_id 校验 |
| workbench/backend/routers/specflow_decisions.py | sess-s2-fix | 2026-08-11 | ded72086eaf3 | 55fe313adb0d | 已完成 | H1 require_role 传 list 致 500 修正（Depends 注入）+ H3 评分 confirm 端点 + M3 resolve_workspace 授权 + 路由遮蔽修复（/scores 前移）+ 跨工作区 404 |
| workbench/backend/routers/specflow_interview.py | sess-s2-fix | 2026-08-11 | 1f752557ca69 | d848432731c2 | 已完成 | M1 freeze/impact-confirm product 闸门 + M3 resolve_workspace + M6 冻结状态机全链推进 + M7 record_answer 归属校验 |
| workbench/backend/services/specflow/decision_service.py | sess-s2-fix | 2026-08-11 | 4f90f7afc469 | be97b66ff1bd | 已完成 | workspace 透传（gate/scores/export）+ 评分幂等 skip_if_suggested |
| workbench/backend/services/specflow/interview_service.py | sess-s2-fix | 2026-08-11 | e61780e25c1c | 9860a62809f4 | 已完成 | M8 impact-confirm 缺 commit 修复 + 静默异常改日志 + specflow_base 防御 + DB 路径单一事实源 |
| workbench/backend/services/specflow/sf_store.py | sess-s2-fix | 2026-08-11 | c140abeb6f4e | d364e8cce704 | 已完成 | M8 create_* 事务返回 None 修复 + sf_questions workspace 列迁移 + 面试存在性校验 |
| test_specstd/test_specflow_ledger.py | sess-s2-fix | 2026-08-11 | 4144c5bb7592 | cf0c2e60afd7 | 已完成 | workspace 参数适配 + 新增跨工作区隔离/sha 审计/增补跨面试 4 例 |
| test_specstd/test_specflow_mcp.py | sess-s2-fix | 2026-08-11 | NEW | 6278cc15404a | 已完成 | MCP 层测试 10 例（iv_ask_question/read_baseline 真实摘录/emp 留痕/workspace 隔离） |
| test_specstd/test_specflow_rest.py | sess-s2-fix | 2026-08-11 | NEW | f41e2a113756 | 已完成 | REST 层测试 13 例（角色闸门/409 缺口/评分 confirm/幂等/跨面试 404/授权 403） |
| specflow/materials/__init__.py | sess-s3-dev | 2026-08-11 | NEW | e8c9ae224ff2 | 已完成 | S3：materials 包（store/pipeline/coverage/pack_assembler） |
| specflow/materials/store.py | sess-s3-dev | 2026-08-11 | NEW | ce823b89d454 | 已完成 | T-030/T-031：sf_materials/sf_material_topics 表 + CRUD（MAT-xxx 全局唯一 + sha256_12 + 状态机 + workspace 隔离 + 候选确认闸门） |
| specflow/materials/pipeline.py | sess-s3-dev | 2026-08-11 | NEW | f2b699791432 | 已完成 | T-030：sniff（magic bytes + 控制字符比例防误判）/extract（md/docx 解包 XXE 拒绝/pdf 文本层无 OCR）/chunk（md 标题/PRD § 锚点/页标） |
| specflow/materials/coverage.py | sess-s3-dev | 2026-08-11 | NEW | 295e805b9c64 | 已完成 | T-034：coverage_map 机打依据（FR 标题关键词片段+2-gram 词表，high/low 置信分层，缺口摘要） |
| specflow/materials/pack_assembler.py | sess-s3-dev | 2026-08-11 | NEW | da9a70fed2a0 | 已完成 | T-032/T-033：六分区确定性装配 → info_pack.yaml（回调注入只读数据源 + 双闸门） |
| workbench/backend/services/specflow/materials_service.py | sess-s3-dev | 2026-08-11 | NEW | c509b574a13b | 已完成 | T-030~T-034：上传/解析/候选/入包/装配/新鲜度服务编排（REST/MCP 共用） |
| mcp_server/tools/specflow_pack.py | sess-s3-dev | 2026-08-11 | NEW | 72b3ae801ebc | 已完成 | T-032：pack_assemble/pack_read_section/material_parse_status/material_extract_topics/pack_freshness_check 5 工具 |
| workbench/frontend/src/pages/ZentaoPanel.tsx | sess-s5-dev | 2026-08-11 | NEW | 798e2e66d21f | 已完成 | T-057：禅道集成面板四区（冻结 delta 交付/提 BUG 双入口/对话草案确认/锚点作业） |
| mcp_server/tools/specflow_refs.py | sess-s5-dev | 2026-08-11 | 7c28e7ac6e71 | 75b1e53ffd61 | 已完成 | T-057：+sf_suggest_story_draft（草案建议恒 draft 态，不触禅道） |
| workbench/backend/services/specflow/sf_refs_store.py | sess-s5-dev | 2026-08-11 | 5ddc936214c8 | 58e52807b6b7 | 已完成 | T-057：+sf_story_drafts 表（draft→created/cancelled 状态机） |
| workbench/backend/services/zentao/client.py | sess-s5-dev | 2026-08-11 | 28c0cf9f4ce2 | 2029b0ba931f | 已完成 | T-057：create_story_from_draft_job（幂等优先）+ list_frozen_deltas |
| workbench/backend/routers/zentao.py | sess-s5-dev | 2026-08-11 | 3b8367208ecb | 3d0f9f8dc3c2 | 已完成 | T-057：+from-draft/story-drafts/cancel/frozen-deltas/jobs 列表端点 |
| test_specstd/test_s5_zentao.py | sess-s5-dev | 2026-08-11 | ab4e3476a6f7 | e0aa9829d071 | 已完成 | T-057：+18 例（草案链路/幂等/角色闸门/feishu handler） |
| workbench/backend/routers/specflow_materials.py | sess-s3-dev | 2026-08-11 | NEW | d55ff8e23fdc | 已完成 | T-030~T-032：上传/列表/预览/候选/confirm/include/pack/reassemble 8 端点（confirm/include 仅 product） |
| test_specstd/test_specflow_materials.py | sess-s3-dev | 2026-08-11 | NEW | 2fa75bffb15f | 已完成 | T-030~T-034 测试 38 例（store/pipeline/coverage/装配器/MCP/REST） |
| graph_index/__init__.py | sess-pa-dev | 2026-08-11 | NEW | 56aaf37d6421 | 已完成 | T-070：graph_index 包（确定性派生服务入口） |
| graph_index/snapshot.py | sess-pa-dev | 2026-08-11 | NEW | 27e08746d468 | 已完成 | T-072：里程碑快照（导出/列表/指纹）+ 两档演化 diff（+/-/~ + per_module） |
| specflow/lineage/__init__.py | sess-pa-dev | 2026-08-11 | NEW | e8d57c3529c5 | 已完成 | T-074：血缘链谱系口径子包 |
| specflow/lineage/broken_link_rules.yaml | sess-pa-dev | 2026-08-11 | NEW | bc8bc9d87162 | 已完成 | T-074：断链规则集 BL-01~BL-06（WARNING 级） |
| specflow/lineage/lineage_check.py | sess-pa-dev | 2026-08-11 | NEW | 6b3831932f0a | 已完成 | T-074：断链确定性校验器（纯图遍历+规则集，结果可删可重建） |
| mcp_server/tools/graph_index.py | sess-pa-dev | 2026-08-11 | NEW | 816f22ad1c45 | 已完成 | T-070/T-072/T-073/T-074：MCP 工具 8 个（graph_query/backlink/rebuild/snapshot/diff + lineage_trace/check） |
| workbench/backend/routers/lineage.py | sess-pa-dev | 2026-08-11 | NEW | 51c4d5584b9f | 已完成 | T-073/T-074：lineage 路由（trace/node/check GET+POST） |
| workbench/frontend/src/pages/LineageStory.tsx | sess-pa-dev | 2026-08-11 | NEW | 7c5500d0d9a8 | 已完成 | T-073/T-074：四阶段分带 + Q1/Q2 追溯 + 外部锚点虚线 + 断链 WARNING 面板 |
| workbench/backend/services/preflight.py | sess-engine-t502 | 2026-08-11 | 754a746b9fa1 | f562b4d593a9 | 已完成 | T-502：_static_file_refs（with.file 提取）+ _split_file_refs（插值→unknown/缺失→missing）+ scan_dependencies/scan_compliance 收录 missing_files/unknown_file_refs（含 _group 聚合与 summary 计数），相对项目根（场景库根上层）判存在性，纯读零写路径 |
| mcp_server/tools/validator.py | sess-engine-t502 | 2026-08-11 | be02323a5a8c | 79e241ef5561 | 已完成 | T-502：MISSING_FILE WARN（with.file 存在性校验，解析根=工作区根回退仓库根；插值路径跳过；与 BODY_KEY/UNKNOWN_TPL 同族） |
| test_specstd/test_preflight.py | sess-engine-t502 | 2026-08-11 | 489991496228 | 08e3145023f9 | 已完成 | T-502：TDD 追加 7 例（文件存在无缺口/缺失报 missing_files/插值进 unknown_file_refs 与 gaps/teardown 扫描/多场景归组/绝对路径/scan_compliance 收录） |
| test_specstd/test_acceptance_fixes.py | sess-engine-t502 | 2026-08-11 | 49f92b81e30e | e64a8bbbc7cd | 已完成 | T-502：validator MISSING_FILE 2 例（缺失 WARN/存在不报） |
| workbench/frontend/src/pages/RunControl.tsx | sess-engine-t502 | 2026-08-11 | 9bd6c6dee39c | 5e7b55a3a413 | 已完成 | T-502：弹窗预警区 📎 fixtures 分组 + ❓ 文件引用分组（复用 T-318 通道，无覆盖输入框）+ 底部说明区分仓库缺陷语义 |
| docs/远期设计/SpecGuard-多角色服务访问流转与规模化升级设计.md | sess-master | 2026-08-11 | NEW | f4d3b3ba01f3 | 已完成 | v1.22：规模化升级支线设计文档（角色服务访问流转图 + T-801~T-806 详细设计 + 开发时机总表） |
| mcp_server/tools/open/__init__.py | sess-s8-dev | 2026-08-11 | NEW | 1ae7b5896e2b | 已完成 | T-083：open/ 命名空间包（L0 只读面红线注释 + 共享只读辅助：工作区解析/changes 扫描/图谱只读打开） |
| mcp_server/tools/open/specflow_refs.py | sess-s8-dev | 2026-08-11 | NEW | 9417260214fa | 已完成 | T-083：get_frozen_spec/get_proposal/query_decisions/get_interview_status/get_delta_contract 五工具（M05/M04 数据源） |
| mcp_server/tools/open/lineage_query.py | sess-s8-dev | 2026-08-11 | NEW | 7785e721724d | 已完成 | T-083：trace_forward/trace_backward/query_graph 三工具（只读存量索引，不调 ensure_fresh；panorama_* 直读） |
| mcp_server/tools/open/refs_query.py | sess-s8-dev | 2026-08-11 | NEW | 42e1cf1fb0f0 | 已完成 | T-083：lookup_external_ref（M06 sf_external_refs 读面 + 谱系提示） |
| mcp_server/tools/open/dev_context.py | sess-s8-dev | 2026-08-11 | NEW | c057061178a3 | 已完成 | T-085：dev_context_by_zt_ref/by_anchor/by_fr 三入口 + 六分区 pack + 聚合指纹 + 默认取版（自动发现当前冻结版）+ 未冻结不可达 + 草稿零泄漏 |
| test_specstd/test_failure_index.py | sess-s8-dev | 2026-08-11 | NEW | b3c11cd1af97 | 已完成 | T-083 顺带：预存测试污染修复——attribution._get_reports_root 直接赋值改 monkeypatch（3 处），防模块级残留污染后续测试 |
| mcp_server/tools/open/quality_query.py | sess-s8-dev | 2026-08-11 | 44f2756dff52 | 2d332d82c40c | 已完成 | 验收修复：read_run_report 不重复注册 Tool 对象（重名触发 LLM API 400「Tool names must be unique」），改 handle 层映射 attribution，open 注册面 15 工具 |
| mcp_server/tools/side_effect_registry.py | sess-s8-dev | 2026-08-11 | 5a7bd7b767c8 | d7761f8f7aa7 | 已完成 | 验收修复：lark_auth_login/logout/lark_execute 改标 draft（7513b38 误标 external-write 破坏空集红线 + runtime 拒用），遵循 zentao 先例暂标 draft |
| test_specstd/test_open_surface.py | sess-s8-dev | 2026-08-11 | c52c7bf574b2 | b326770ae3ea | 已完成 | 验收修复：open 注册断言 16→15 + 新增 read_run_report 不重复注册断言 |
| docs/历史区/SpecGuard-总控文档-归档-2026-08-13.md | sess-gatedock-dev | 2026-08-13 | NEW | 3d69155ce15f | 已完成 | v1.23：归档文件落盘 |
| mcp_server/tools/gate_dock.py | sess-gatedock-dev | 2026-08-13 | NEW | 976fcd933520 | 已完成 | T-901：gate_dock_status MCP 只读工具（_session_id 特权参数 + interview_id 可选，纯读零写副作用，side_effect 默认 none） |
| agent/skills/gate-dock-guide.md | sess-gatedock-dev | 2026-08-13 | NEW | 095feb02c8bb | 已完成 | T-901：推卡时机表 + gate-card/gate-exec 围栏格式 + L1/L2/L3 分档接管话术 + 白名单约束 |
| workbench/frontend/src/components/GateCardView.tsx | sess-gatedock-dev | 2026-08-13 | NEW | 041b7680f51d | 已完成 | T-901/T-902：GateCardView 单卡渲染（操作台与消息内嵌共用）+ GateExecCard 三期确认卡 + GATE_EXEC_ACTIONS 白名单 |
| agent/runtime.py | sess-gatedock-dev | 2026-08-13 | — | 2420441bc0e2 | 已完成 | T-901：_RBAC_READONLY_TOOLS 加 gate_dock_status + _execute_tool 注入 _session_id 特权参数 |
| mcp_server/server.py | sess-gatedock-dev | 2026-08-13 | — | 09b16feaeb4c | 已完成 | T-901：import gate_dock + mods 列表注册（工具数 89→90） |
| agent/purposes/requirement_interview.md | sess-gatedock-dev | 2026-08-13 | — | f9d25c7b4375 | 已完成 | T-901：tools 白名单加 gate_dock_status |
| workbench/frontend/src/pages/GateDockPanel.tsx | sess-gatedock-dev | 2026-08-13 | — | f89a4352cc47 | 已完成 | T-901：瘦容器重写（复用 GateCardView，251→77 行） |
| test_specstd/test_gate_dock.py | sess-gatedock-dev | 2026-08-13 | — | cb512a5b0e80 | 已完成 | T-901：追加 TestGateDockMcp 6 例（会话反查/空态/显式 ID/未找到/纯读分级） |
| test_specstd/test_mcp_server.py | sess-gatedock-dev | 2026-08-13 | — | 317c13bc9141 | 已完成 | T-901：工具注册断言 89→90 + gate_dock_status 加入 expected 集合 |
| specflow/feishu_pool/__init__.py | sess-feishu-graph | 2026-08-14 | NEW | 06dded07d114 | 已完成 | T-910：批次 A（11220d3） |
| specflow/feishu_pool/paths.py | sess-feishu-graph | 2026-08-14 | NEW | dfb40de0f09e | 已完成 | T-910：私有/共享路径函数 |
| specflow/feishu_pool/pool_store.py | sess-feishu-graph | 2026-08-14 | NEW | 5313d3687aa3 | 已完成 | T-910：快照落盘+imgmap |
| specflow/feishu_pool/facts.py | sess-feishu-graph | 2026-08-14 | NEW | 88273b81b4be | 已完成 | T-910：事实源读写 |
| specflow/feishu_pool/topic_cluster.py | sess-feishu-graph | 2026-08-14 | NEW | 32d9a654e87b | 已完成 | T-911：话题聚类增量归并 |
| specflow/feishu_pool/link_suggest.py | sess-feishu-graph | 2026-08-14 | NEW | 6cf7e048129a | 已完成 | T-911：建边建议三重防幻觉 |
| specflow/feishu_pool/lark_cli.py | sess-feishu-graph | 2026-08-14 | NEW | b5e07a19d065 | 已完成 | T-912：lark-cli 封装（与 feishu_fetch 同源） |
| workbench/backend/services/specflow/feishu_review_service.py | sess-feishu-graph | 2026-08-14 | NEW | 7b2746fe2aee | 已完成 | T-912：复核服务提升闸门 |
| test_specstd/test_feishu_pool.py | sess-feishu-graph | 2026-08-14 | NEW | 9aa9d0f23703 | 已完成 | T-910/T-911 用例 |
| test_specstd/test_feishu_topic_cluster.py | sess-feishu-graph | 2026-08-14 | NEW | 4ad2f054a85b | 已完成 | T-911 用例 |
| test_specstd/test_feishu_link_suggest.py | sess-feishu-graph | 2026-08-14 | NEW | d50ae9851171 | 已完成 | T-911 用例 |
| test_specstd/test_feishu_review.py | sess-feishu-graph | 2026-08-14 | NEW | 06cdc787fdad | 已完成 | T-912 用例 |
| graph_index/store.py | sess-feishu-graph | 2026-08-14 | 09dc90236192 | be64c9ff64e6 | 已完成 | T-913：节点/边类型枚举扩展 |
| graph_index/builder.py | sess-feishu-graph | 2026-08-14 | 2a2aafc4034e | 22c5c1e74dfa | 已完成 | T-913：飞书派生段+指纹 |
| docs/远期设计/SpecGuard-飞书知识图谱设计-面试素材溯源.md | sess-feishu-graph | 2026-08-14 | NEW | 35a82e984324 | 已完成 | 设计定稿（d5a4142） |
| docs/upgrade-plans/2026-08-13-飞书知识图谱一期实施计划.md | sess-feishu-graph | 2026-08-14 | NEW | 29da3e3b5717 | 已完成 | 实施计划+批次 A/B 执行序（ad11696） |
| mcp_server/tools/feishu_fetch.py | sess-feishu-graph | 2026-08-14 | — | 0047c5e25e40 | 已完成 | T-914：复用 lark_cli 统一封装（1c89d14） |
| test_specstd/test_feishu_fetch.py | sess-feishu-graph | 2026-08-14 | — | 9841616cbe4c | 已完成 | T-914：patch 目标随迁移修正（1c89d14） |
| workbench/frontend/src/pages/MaterialsPanel.tsx | sess-feishu-graph | 2026-08-14 | — | 1958c72d5a16 | 已完成 | T-915：挂载复核面板（3e32e89） |
| graph_index/service.py | sess-feishu-graph | 2026-08-14 | — | 31c9344877f1 | 已完成 | T-915：focus_subgraph+network_view（98612da/0871641） |
| workbench/backend/routers/graph.py | sess-feishu-graph | 2026-08-14 | — | 094d006c9b38 | 已完成 | T-915：/focus 端点+lens=network（98612da/0871641） |
| workbench/frontend/src/utils/elkLayout.ts | sess-feishu-graph | 2026-08-14 | — | fc2c9de4843f | 已完成 | T-915：layoutNetworkByELK 力导向（0871641） |
| workbench/frontend/src/components/NetworkGraph.tsx | sess-feishu-graph | 2026-08-14 | NEW | d1bd15e09015 | 已完成 | T-915：网状全景组件（0871641） |
| workbench/frontend/src/pages/GraphPanorama.tsx | sess-feishu-graph | 2026-08-14 | — | e7934063b4cc | 已完成 | T-915：第 4 镜头接入（0871641） |
| test_specstd/test_graph_index.py | sess-feishu-graph | 2026-08-14 | — | abbddcbb86ac | 已完成 | T-915：focus/network 用例（98612da/0871641） |
| docs/远期设计/SpecGuard-飞书知识图谱二期设计-事件监听与智能增强.md | sess-feishu-graph | 2026-08-14 | NEW | 72c391148d1e | 已完成 | 二期设计定稿（64ccc29） |
| docs/upgrade-plans/2026-08-14-飞书知识图谱二期实施计划.md | sess-feishu-graph | 2026-08-14 | NEW | c49b3ff25b2c | 已完成 | 二期计划 Task0-7（64ccc29） |
| docs/远期设计/SpecGuard-飞书知识图谱三期设计-多用户编排与演进追踪.md | sess-feishu-graph | 2026-08-14 | NEW | abd732b1b17c | 已完成 | 三期设计定稿 |
| docs/upgrade-plans/2026-08-14-飞书知识图谱三期实施计划.md | sess-feishu-graph | 2026-08-14 | cc3f67739ddc | cc522275c16b | 已完成 | 三期计划 Task0-5+T-929 并入 |
| docs/远期设计/SpecGuard-总控文档.md | sess-feishu-graph | 2026-08-14 | 09e02ad565f8 | 22b97172b1f7 | 已完成 | v1.27：三期任务登记 |
| workbench/backend/services/specflow/feishu_watcher.py | sess-feishu-graph | 2026-08-14 | NEW | 718acf84e977 | 已完成 | T-917~T-919/T-922：watcher 托管器（7580fc3/d3a6ea4） |
| test_specstd/test_feishu_watcher.py | sess-feishu-graph | 2026-08-14 | NEW | c254d34a0e3a | 已完成 | T-917~T-919/T-923：watcher 用例 9 例 |
| workbench/backend/main.py | sess-feishu-graph | 2026-08-14 | — | 773886894a6e | 已完成 | T-919：watcher 挂载（5119dbe） |
| specflow/feishu_pool/captions.py | sess-feishu-graph | 2026-08-14 | — | 19347950c947 | 已完成 | T-920：transcribe_images 实装（7189fd0） |
| workbench/backend/routers/feishu_pool.py | sess-feishu-graph | 2026-08-14 | — | 4cfca5aeda24 | 已完成 | T-920：POST /transcribe（7189fd0） |
| workbench/frontend/src/components/FeishuReviewPanel.tsx | sess-feishu-graph | 2026-08-14 | — | 6ab8736d9a5b | 已完成 | T-920：🖼转述按钮（7189fd0） |
| workbench/frontend/src/utils/focusAnchor.ts | sess-feishu-graph | 2026-08-14 | NEW | 6b286a743018 | 已完成 | T-921：锚点提取纯函数（fddc272） |
| workbench/frontend/src/components/FocusGraph.tsx | sess-feishu-graph | 2026-08-14 | — | 8e4bdd44c2bb | 已完成 | T-921：自动焦点（fddc272） |
| workbench/frontend/src/pages/AgentChat.tsx | sess-feishu-graph | 2026-08-14 | — | 29d052286d2c | 已完成 | T-921：messages 接线（fddc272） |
| workbench/frontend/src/api.ts | sess-feishu-graph | 2026-08-14 | — | 2e1b876fc550 | 已完成 | T-920：transcribe 方法（7189fd0） |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-feishu-graph | 2026-08-14 | — | 4b48ba14394a | 已完成 | T-922：sync_recent_docs（d3a6ea4） |
| test_specstd/test_feishu_transcribe.py | sess-feishu-graph | 2026-08-14 | NEW | c5d28b59f28e | 已完成 | T-920：转述用例 3 例（7189fd0） |
| test_specstd/test_feishu_sync.py | sess-feishu-graph | 2026-08-14 | — | 242d95e91fd0 | 已完成 | T-922：轮询交集用例（d3a6ea4） |
| sg_core/test_dimensions.py | sess-test-taxonomy | 2026-08-21 | NEW | f13ba260c0af | 已完成 | T-981：dimensions 受控词表+证据提取+映射检查 |
| test_specstd/test_dimensions.py | sess-test-taxonomy | 2026-08-21 | NEW | d0fb48f262ed | 已完成 | T-981：维度词表/映射/存量标注回归测试 25 例 |
| test_specstd/test_dimensions.py | sess-test-taxonomy | 2026-08-21 | d0fb48f262ed | f77239cfcae5 | 已完成 | T-981 返修：存量回归口径磁盘 rglob→git ls-files 跟踪事实源（主库验收 2 FAILED 根因修复） |
| test_engine/test_dimensions.py | sess-test-taxonomy | 2026-08-21 | NEW | cc7202d56210 | 已完成 | T-981：loader dimensions property 测试 3 例 |
| engine/scenario_loader.py | sess-test-taxonomy | 2026-08-21 | 27455b814da7 | 3b2674af034b | 已完成 | T-981：Scenario.dimensions 只读 property |
| mcp_server/tools/validator.py | sess-test-taxonomy | 2026-08-21 | cb035f284120 | 207453609332 | 已完成 | T-981：validate 接入维度检查 |
| workbench/backend/services/spec_validator.py | sess-test-taxonomy | 2026-08-21 | ee481a629526 | 8b28c27493e7 | 已完成 | T-981：全库校验接入 T10 |
| workbench/backend/services/coverage_gaps.py | sess-test-taxonomy | 2026-08-21 | 4016b91ff88c | a1c28c48b0fb | 已完成 | T-981：compute_coverage 维度聚合 |
| workbench/frontend/src/api.ts | sess-test-taxonomy | 2026-08-21 | a9d0966a5501 | 6160ff127475 | 已完成 | T-981：CoverageGaps.dimensions 类型 |
| workbench/frontend/src/pages/CoveragePanel.tsx | sess-test-taxonomy | 2026-08-21 | 7ff1ddf86ba6 | 1a7fcdf845e7 | 已完成 | T-981：维度分布区块 |
| sg_core/format_spec.py | sess-test-taxonomy | 2026-08-21 | 76b6d010e1df | d9db54a5feb3 | 已完成 | T-981：§1.2 doc 选填字段+§五 T10+2.14.0 三同步 |
| docs/specguard-yaml-format-spec.md | sess-test-taxonomy | 2026-08-21 | c452d19cc3ee | df4e072d9841 | 已完成 | T-981：快照重导出 |
| agent/skills/generate-scenario.md | sess-test-taxonomy | 2026-08-21 | 0639af8ae44d | 7310217168a3 | 已完成 | T-981：注入测试设计方法章节（1.1.0） |
| scenarios/{employee,evaluation,inventory}/*/*.yaml（24 个场景文件） | sess-test-taxonomy | 2026-08-21 | —（doc 层补标注不进指纹，逐文件核对见提交） | —（每文件 +1 行 dimensions；契约指纹零漂移已用 build_baseline 全量比对证实） | 已完成 | T-981：存量补标注 doc.dimensions |
| specflow/feishu_pool/topic_cluster.py | sess-material-pool | 2026-08-23 | ed300417f3d7 | 58b3116935fd | 已完成 | T-1001 F4：edit_candidate 扩 message_ids/window/days 重关联参数 |
| workbench/backend/routers/feishu_pool.py | sess-material-pool | 2026-08-23 | 9901c72cb301 | ba119d550b0c | 已完成 | T-1001 F4：CardUpdate 扩参透传 |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-material-pool | 2026-08-23 | 3223e898263e | 6d1d4f1e3be4 | 已完成 | T-1001 F1/F2：右栏列表化+搜索排序+专注模式+编辑弹框接线 |
| workbench/frontend/src/components/TopicCard.tsx | sess-material-pool | 2026-08-23 | 4df8474ddb93 | 00c59164123e | 已完成 | T-1001 F2/F3：卡片改紧凑列表行，编辑迁出到弹框 |
| workbench/frontend/src/components/ChatMessageView.tsx | sess-material-pool | 2026-08-23 | NEW | 8e9ffa85ea2e | 已完成 | T-1001：MessageBody+useChatMedia+loadChatMessages 从 TopicWorkspace 抽离共享（弹框复用富渲染） |
| workbench/frontend/src/components/TopicEditModal.tsx | sess-material-pool | 2026-08-23 | NEW | 609bd88026f3 | 已完成 | T-1001 F3/F4：编辑弹框（左原文右话题并排+勾选重关联） |
| workbench/frontend/src/components/topicList.ts | sess-material-pool | 2026-08-23 | NEW | 67b5b1173113 | 已完成 | T-1001 F2：搜索/排序纯函数（可测） |
| workbench/frontend/src/components/topicList.test.ts | sess-material-pool | 2026-08-23 | NEW | 0142e8ae326d | 已完成 | T-1001 F2：搜索/排序单测 10 例 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-material-pool | 2026-08-23 | 8c1a8138a1df | 28f6956c7c0c | 已完成 | T-1001 F1：页面级专注模式（隐藏页头/状态卡/监听卡/页签条，ESC 退出） |
| workbench/frontend/src/api/feishuPool.ts | sess-material-pool | 2026-08-23 | b083f0cfdc37 | 30f569d8f430 | 已完成 | T-1001：editTopicCard 改参数对象+messageIds/window/days |
| test_specstd/test_feishu_topic_cluster.py | sess-material-pool | 2026-08-23 | ad57c201c8f1 | 5fba340a353b | 已完成 | T-1001 F4：重关联用例（成功/未变不推rev/空集拒绝/坏window拒绝） |
| test_specstd/test_feishu_t948_router.py | sess-material-pool | 2026-08-23 | 0af0ba15ed19 | d739b6c5f7ea | 已完成 | T-1001 F4：路由层重关联透传+空集 400 两例 |
| workbench/frontend/src/components/topicList.ts | sess-acceptance | 2026-08-23 | 67b5b1173113 | 9895d8028225 | 已完成 | T-1001 追修：dedupeTopics 同 id 去重 + collectKeywords 词频 + filterTopics tags 参（AND） |
| workbench/frontend/src/components/topicList.test.ts | sess-acceptance | 2026-08-23 | 0142e8ae326d | 62704049dc32 | 已完成 | T-1001 追修：去重/词频/标签单测 +9 例（83→92） |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-acceptance | 2026-08-23 | 6d1d4f1e3be4 | df44ce328be4 | 已完成 | T-1001 追修：dayTopics 按 id 去重（根因修复）+ 标签芯片行 + tags 持久化 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-acceptance | 2026-08-23 | 28f6956c7c0c | 55545bbfd445 | 已完成 | T-1001 追修：allTopicCards 内联 byId 收敛为 dedupeTopics（零漂移） |
| docs/经验包/2026-08-23-话题列表搜索排序看似未生效-同id双份key撞车.md | sess-acceptance | 2026-08-23 | NEW | 0e6d1dfe4c41 | 已完成 | T-1001 追修排障闭环经验包 |
| docs/经验包/README.md | sess-acceptance | 2026-08-23 | f1a311807972 | abdc33ba36d6 | 已完成 | T-1001 追修：经验包索引行 |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-acceptance | 2026-08-23 | df44ce328be4 | ea89aa9ec809 | 已完成 | T-1002：hover 联动退役改定位按钮接线 + 勾选生成话题（模式开关/行勾选框/动作条/ComposeModal 接线） |
| workbench/frontend/src/components/TopicCard.tsx | sess-acceptance | 2026-08-23 | 00c59164123e | ca81ea735718 | 已完成 | T-1002：onSelect/hover 退役，「⌖ 定位原文」按钮（入库卡+草案段一致） |
| workbench/frontend/src/components/ComposeTopicModal.tsx | sess-acceptance | 2026-08-23 | NEW | 588dbdea2b19 | 已完成 | T-1002：生成话题弹框（左已选可移除/右表单+补充说明拼 LLM 输入） |
| workbench/frontend/src/api/feishuPool.ts | sess-acceptance | 2026-08-23 | 30f569d8f430 | a1dd903abaa3 | 已完成 | T-1002：composeTopic API |
| specflow/feishu_pool/topic_cluster.py | sess-acceptance | 2026-08-23 | 58b3116935fd | 318f090ceb95 | 已完成 | T-1002：compose_topic_from_messages（id 反查所属日/缺失 KeyError/草案追加同键） |
| workbench/backend/routers/feishu_pool.py | sess-acceptance | 2026-08-23 | ba119d550b0c | 1c15bb4f7553 | 已完成 | T-1002：/topics/compose 端点（空关联 400/缺失 404/模型未配 400） |
| test_specstd/test_feishu_topic_cluster.py | sess-acceptance | 2026-08-23 | 5fba340a353b | e051c5da6aa7 | 已完成 | T-1002：compose 服务测试 5 例 |
| test_specstd/test_feishu_t948_router.py | sess-acceptance | 2026-08-23 | d739b6c5f7ea | c7822d2e20eb | 已完成 | T-1002：compose 路由测试 4 例（get_model 打桩隔离） |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-acceptance | 2026-08-23 | 55545bbfd445 | a88b4443d91f | 已完成 | T-1003：页面标题/页签/空态文案「飞书材料池→飞书话题」 |
| workbench/frontend/src/App.tsx | sess-acceptance | 2026-08-23 | 434bafab2ac5 | 4476d4670c31 | 已完成 | T-1003：路由注释同步 |
| workbench/frontend/src/api/feishuPool.ts | sess-acceptance | 2026-08-23 | a1dd903abaa3 | 9c172f82b76e | 已完成 | T-1003：API 区块注释同步 |
| workbench/frontend/src/components/useChatOptions.ts | sess-acceptance | 2026-08-23 | 4de23f8b2c46 | d20c6080aae6 | 已完成 | T-1003：注释同步 |
| workbench/backend/routers/feishu_pool.py | sess-acceptance | 2026-08-23 | 1c15bb4f7553 | f78ae1fa6204 | 已完成 | T-1003：模块 docstring 同步 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-acceptance | 2026-08-23 | e5d6e83591a4 | ffee0894c24e | 已完成 | T-1003：模块 docstring 同步 |
| workbench/backend/services/rbac_store.py | sess-acceptance | 2026-08-23 | c789a19ffb5e | 619cf42c8148 | 已完成 | T-1003：菜单种子 label 改「飞书话题」（_migrate_menus_t996 启动同步存量库，已实证） |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-acceptance | 2026-08-23 | a88b4443d91f | ecb0c3942871 | 已完成 | T-1004：主页移除监听状态/范围两卡，材料页签承接用户筛选芯片行，watcher 状态清理 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-acceptance | 2026-08-23 | 7a135c71a67c | a977f86d1a94 | 已完成 | T-1006：群聊详情弹层改消息流渲染（ChatDetailView 同源富渲染+md 折叠底稿） |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-acceptance | 2026-08-23 | a977f86d1a94 | 3c60d9181a03 | 已完成 | T-1007：材料列表分类型 tab+分页（MatType 外提/const 断言坑记录） |
| workbench/frontend/src/components/FeishuWatchSettings.tsx | sess-acceptance | 2026-08-23 | 4fe721777def | 01909d515269 | 已完成 | T-1004：弹层顶部加监听运行状态条+当前监听范围只读摘要（开弹层拉 watcherStatus） |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-acceptance | 2026-08-23 | ecb0c3942871 | 7a135c71a67c | 已完成 | T-1005：页签顺序对调（话题在前）+默认落地页改话题 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-material-pool | 2026-08-23 | ffee0894c24e | 07de9fb0dee8 | 已完成 | T-1008：watch 配置加 topic_auto_count/minutes 双阈值+数值键归一；_cluster_once/maybe_cluster_async 支持 only_chat_ids scoped 聚类 |
| workbench/backend/services/specflow/feishu_watcher.py | sess-material-pool | 2026-08-23 | 474345626522 | cb6bae8ba6fb | 已完成 | T-1008：事件直写记账 note_chat_message+auto_cluster_job 时间阈值检查+_fire_auto_cluster；_schedule_auto_cluster/reschedule_jobs；registry.reconfigure_user |
| workbench/backend/routers/feishu_pool.py | sess-material-pool | 2026-08-23 | f78ae1fa6204 | e1afcb6be129 | 已完成 | T-1008：WatchConfig 双阈值字段；put_watch 热重载三态；watcher-status 诚实 running=count>0；顺手修 F401/E741 |
| test_specstd/test_feishu_sync.py | sess-material-pool | 2026-08-23 | bf18754d1624 | 08bf1ecb187c | 已完成 | T-1008：默认字典纳新键/归一化/scoped 聚类 3 新测；顺手修 F401/I001 |
| test_specstd/test_feishu_watcher.py | sess-material-pool | 2026-08-23 | 82f24276dac9 | 93c4096c4485 | 已完成 | T-1008：TestAutoCluster 7 例（条数/时间/禁用/stale/持久化）+reconfigure 热重载 1 例；顺手修 I001 |
| workbench/frontend/src/api/feishuPool.ts | sess-material-pool | 2026-08-23 | 9c172f82b76e | 969ab784807f | 已完成 | T-1008：FeishuWatch 双阈值字段+FeishuWatcherState 三态类型 |
| workbench/frontend/src/components/FeishuWatchSettings.tsx | sess-material-pool | 2026-08-23 | 01909d515269 | ad5c47d5f899 | 已完成 | T-1008：弹层 4 tab（通用 tab 承接状态/摘要/定时/自动分类阈值）+footer 保存+tab 持久化+监听用户空态引导+保存三态诚实提示 |
| workbench/frontend/src/components/TopicWorkspace.tsx | sess-material-pool | 2026-08-23 | ea89aa9ec809 | 1f5465e49309 | 已完成 | T-1009：专注模式双栏行高钉死视口（两栏各自内滚）+定位改容器内 scrollTo（修「定位找到原文但话题没了」） |
| workbench/backend/services/rbac_store.py | sess-system-config | 2026-08-24 | 619cf42c8148 | 13ef3b73a2f4 | 已完成 | T-1010：种子新增 menu-system-config/删三旧菜单/menu-settings 改基础设置；_MENU_REMAP 三旧键→menu-system-config |
| workbench/frontend/src/pages/SystemConfig.tsx | sess-system-config | 2026-08-24 | 09d4f14d56ad | 09d4f14d56ad | 已完成 | T-1010：新增——三栏父页（系统目录加载+选中持久化+角色分发） |
| workbench/frontend/src/components/system-config/SystemsPanel.tsx | sess-system-config | 2026-08-24 | 6e1b70a99af9 | 6e1b70a99af9 | 已完成 | T-1010：新增——栏1系统（自 SystemsAdmin 迁入，env 编辑移栏3） |
| workbench/frontend/src/components/system-config/WorkspacesPanel.tsx | sess-system-config | 2026-08-24 | 0455753c7a14 | 0455753c7a14 | 已完成 | T-1010：新增——栏2工作区（自 WorkspaceCenter 迁入，按栏1系统过滤+文档浏览折叠区） |
| workbench/frontend/src/components/system-config/EnvConfigPanel.tsx | sess-system-config | 2026-08-24 | 53c98ab3501c | 53c98ab3501c | 已完成 | T-1010：新增——栏3环境配置+数据库卡（自 EnvironmentConfig/Settings DbTab 迁入，system 跟随栏1） |
| workbench/frontend/src/pages/Settings.tsx | sess-system-config | 2026-08-24 | 2b0e826dc344 | 3740bceb768b | 已完成 | T-1010：删 db tab 改名基础设置（剩 models/audit/run/git） |
| workbench/frontend/src/App.tsx | sess-system-config | 2026-08-24 | 4476d4670c31 | 056d0d7e0c4c | 已完成 | T-1010：/system-config 路由+三旧路 REDIRECT+删三旧页面 import |
| workbench/frontend/src/components/WorkspaceSelector.tsx | sess-system-config | 2026-08-24 | bf8be43599f9 | 8f52baaa2d34 | 已完成 | T-1010：空态指引文案改「系统配置」 |
| systems/_shared/config/env.sit.yaml | sess-system-config | 2026-08-24 | 2df1327fccdb | 6c3f64b650f2 | 已完成 | T-1010：internal_token 段迁入（通用配置） |
| systems/tdm/config/env.sit.yaml | sess-system-config | 2026-08-24 | 29a2a2db363f | 0347b19db146 | 已完成 | T-1010：internal_token 段迁出（搬至 _shared） |
| test_specstd/test_menu_migration.py | sess-system-config | 2026-08-24 | 199a33bacc03 | 199a33bacc03 | 已完成 | T-1010：新增——菜单迁移 4 测试（映射删除/label/幂等/全新库） |
| workbench/backend/services/menu_guard.py | sess-system-config | 2026-08-24 | f7ad58eeced2 | 612a0bd87df1 | 已完成 | T-1010：API_MENU_BINDINGS 三旧键改 menu-system-config（验收实测 /api/systems 403 抓到） |
| test_workbench/test_menu_guard.py | sess-system-config | 2026-08-24 | e905415a3dbe | 1196a5efd46f | 已完成 | T-1010：/api/systems 绑定断言同步 menu-system-config |
| | | | | | | |

## 7. 冲突与异常处理

| 情况 | 处理 |
|---|---|
| --check 报 DIFF | 停手 → 查 §6 该文件最后登记行 → 联系该会话（§5 备注）→ 确认是「已完成的合法变更」则以新hash重新登记开工；确认是「未登记的脏变更」则上报总控人 |
| 发现别的会话正在改同一文件（登记中） | 等待或改认领 §3.2 的并行任务；禁止抢改 |
| 任务做不下去（依赖未就绪/设计有洞） | §4 状态改 阻塞 + 备注原因 + 上报总控人；不得绕开依赖另起炉灶 |
| 需要新增文件/新表/新任务 | 文件直接 §6 登记（hash=NEW）；新任务一律由总控人追加进 §4，会话不得自行添加任务行 |
| 触及红线 | 立即停手上报：engine/ 冻结层改动、specstd 规则扩展（Ask First）、绕闸生效、外部写入MCP |

## 8. 阶段完成判定

- 单任务完成 = 该任务「产出/验收要点」全部达成 + §6 相关登记行全部回填；
- 阶段完成 = 阶段内任务全 已完成 + 《研发顺序与里程碑验收》§3 对应阶段验收清单逐项通过 + 回归门禁全绿（引擎改动 `pytest -k engine_modes` + `pytest test_engine`；specstd 改动 `pytest test_specstd`；入库前 `release_check.py`）；
- **打磨期完成（v1.1）** = §4.1 任务按优先级（P0→P1→P2）全部达成 + 回归门禁全绿 + 总控人在 §2.0 标注 ✅ 并宣布恢复 §4.2 远期认领；
- 阶段完成后由总控人在 §2 对应行标注 ✅ 及日期。

---

*本文件本身被修改时，同样需要在 §6 登记（第一行登记者是总控人）。hash 工具：`sg-hash.py`（sha256-12，与 specstd 契约指纹同口径）。*
| AGENTS.md | sess-tool-consolidation | 2026-08-21 | 0890c0155353 | 94c0c4400b15 | 已完成 | T-998：补 specflow/graph_index/integrations/skills 四包 + skills 8→13/routers×34/services×41 计数 + mcp tools 名单归一 |
| README.md | sess-tool-consolidation | 2026-08-21 | fdf199e7fdc7 | 1f08e9558404 | 已完成 | T-998：§八目录树重写（补 10 顶层包/去 reports 幽灵）+ §一报告路径改 .specguard/{EX-任务号} |
| workbench/backend/services/scheduler.py | sess-tool-consolidation | 2026-08-21 | 7522d0e59dea | 199be0da9846 | 已完成 | T-999a：print→logging |
| workbench/backend/services/plan_executor.py | sess-tool-consolidation | 2026-08-21 | 7d8958906289 | 5f286c6ee682 | 已完成 | T-999a：print→logging |
| workbench/backend/services/covers_gate.py | sess-tool-consolidation | 2026-08-21 | 6534816656b3 | 086e1f39466d | 已完成 | T-999a：print→logging |
| workbench/backend/services/scenario_store.py | sess-tool-consolidation | 2026-08-21 | 5ad129574cf9 | 4e90ea3e76e4 | 已完成 | T-999a：print→logging |
| workbench/backend/services/runner.py | sess-tool-consolidation | 2026-08-21 | 36aff40d71dc | 467f4e13fe38 | 已完成 | T-999a：print→logging |
| workbench/backend/services/preflight.py | sess-tool-consolidation | 2026-08-21 | 161bc3d7a4a7 | 2d266badf788 | 已完成 | T-999a：print→logging |
| sg_core/crypto.py | sess-tool-consolidation | 2026-08-21 | a10f5531f1c7 | 3658a36b97c5 | 已完成 | T-999a：print→logging |
| feedback/notify.py | sess-tool-consolidation | 2026-08-21 | c6a6431e65eb | ce24cb1fca37 | 已完成 | T-999a：print→logging |
| sg_core/user_store.py | sess-tool-consolidation | 2026-08-21 | 5a2a6753c189 | 19c1729a846f | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| sg_core/git_config.py | sess-tool-consolidation | 2026-08-21 | 4de054b9317e | 77179fd0ce93 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| sg_core/model_config.py | sess-tool-consolidation | 2026-08-21 | 5b11eeb06d31 | 131475987a7d | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| sg_core/settings_store.py | sess-tool-consolidation | 2026-08-21 | be56ed6a37dd | b1ded52d0f97 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| sg_core/llm_config.py | sess-tool-consolidation | 2026-08-21 | 3d09e284ec71 | 983466e34edb | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| sg_core/scenario_meta.py | sess-tool-consolidation | 2026-08-21 | d10f8334b053 | c0084ce454d4 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| sg_core/notify_config.py | sess-tool-consolidation | 2026-08-21 | 709734ca39cd | cfbff8f23791 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| test_specstd/test_crypto.py | sess-tool-consolidation | 2026-08-21 | 4aaef8f54b10 | 2c8a6232bed3 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| test_specstd/test_notify_config.py | sess-tool-consolidation | 2026-08-21 | 0314751fae62 | 3b7c528d1c6d | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| test_specstd/test_scenario_meta_pack.py | sess-tool-consolidation | 2026-08-21 | 089a969de8e4 | 3c8984cce813 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| workbench/backend/scripts/migrate_encrypt_apikeys.py | sess-tool-consolidation | 2026-08-21 | 5cd6f1f26ef8 | 800243c26366 | 已完成 | T-999b：user_store 去私有化（db_connect/DB_LOCK） |
| engine/scenario_runner.py | sess-tool-consolidation | 2026-08-21 | 5cbd737f0537 | 71b1914bc44f | 已完成 | T-999c：抽插值器/实例池，再导出兼容 |
| engine/interpolation.py | sess-tool-consolidation | 2026-08-21 | NEW | 9ae71bd74771 | 已完成 | T-999c：新模块（render/_resolve/RenderError/_FNS） |
| engine/instance_pool.py | sess-tool-consolidation | 2026-08-21 | NEW | 7ef70896d589 | 已完成 | T-999c：新模块（LeaseRegistry/实例池/依赖仲裁辅助） |
| AGENTS.md | sess-tool-consolidation | 2026-08-21 | 94c0c4400b15 | 0b8a7406cde7 | 已完成 | T-999c：引擎块同步 interpolation/instance_pool |
| specstd/workspace.py | sess-tool-consolidation | 2026-08-21 | 9511b325911e | a64b96da7e19 | 已完成 | T-999d：拆为门面+再导出（constants/contextvars/resolve_system 保留） |
| specstd/ws_registry.py | sess-tool-consolidation | 2026-08-21 | NEW | b36a090d3d08 | 已完成 | T-999d：新模块（注册表块） |
| specstd/ws_dirs.py | sess-tool-consolidation | 2026-08-21 | NEW | 24c3d2830aa9 | 已完成 | T-999d：新模块（路径与产物目录块） |
| specstd/ws_git.py | sess-tool-consolidation | 2026-08-21 | NEW | 5bc336104bb3 | 已完成 | T-999d：新模块（git 历史/远程同步块） |
| AGENTS.md | sess-tool-consolidation | 2026-08-21 | 0b8a7406cde7 | 1ea6a5858d07 | 已完成 | T-999d：specstd 块同步四分块 |
| workbench/frontend/src/api/core.test.ts | sess-tool-consolidation | 2026-08-21 | NEW | 44aa988b822f | 已完成 | T-997b：core 会话/请求/上传关键路径 13 例 |
| workbench/frontend/src/api/index.test.ts | sess-tool-consolidation | 2026-08-21 | NEW | 3c7a2c147db5 | 已完成 | T-997b：拆分完整性守卫 39 例 |
| workbench/frontend/src/pages/agentChat/groupMessages.test.ts | sess-tool-consolidation | 2026-08-21 | NEW | e2d728f7d96e | 已完成 | T-997b：消息分组/产物卡片关键路径 13 例 |
