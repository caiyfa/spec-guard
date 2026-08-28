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
| T-1010 | M-D | 「系统配置」三栏合一（系统包/工作区/环境配置+DB）+ internal_token 提取通用配置 + 系统设置改基础设置 | wt/system-config | T-1009 | ✅ 08-24 主库验收（合并 3b18930+ec3a2f8） | sess-system-config | 08-24 总控人派工：工作区中心在前端找不到入口（种子在总览组但未授权角色），拍板三页合一——①新页 SystemConfig 三栏：栏1系统（注册/manifest启停/热重建/extensions评审闸/assertions，自 SystemsAdmin 迁入）→栏2工作区（随栏1系统过滤的卡片+注册表单系统下拉锁栏1+文档浏览折叠区，自 WorkspaceCenter 迁入）→栏3环境配置（scope=shared通用[sso+internal_token]/system本系统，Monaco 带回读+结构化预览，自 EnvironmentConfig 迁入）+数据库卡（自 Settings db tab 迁入，system 不再写死 tdm/env 选项跟随系统枚举）；②internal_token 物理搬家 systems/tdm/config/env.sit.yaml→systems/_shared/config/env.sit.yaml（共享打底合并语义引擎零改动，load_env 实测 internal_token/db/sso 键全在）；③Settings 删 db tab 改名「基础设置」（剩 models/audit/run/git）；④菜单收编：种子新增 menu-system-config、删 menu-env-config/menu-systems/menu-workspace，_MENU_REMAP 三旧键无损映射授权→menu-system-config，menu-settings label 改基础设置（upsert UPDATE 分支存量自动同步）；路由 /system-config，旧三路 REDIRECT 301；删三旧页面（仅 App.tsx 引用）；验证：build 34.8s/oxlint 8 errors 持平/vitest 92 绿/knip 持平/test_specstd 1750 绿（+4 迁移测试：旧键映射删除/label 同步/幂等/全新库）/release_check PASS；总控§6 登记 13 文件；验收补网：menu_guard API 绑定三旧键→menu-system-config（浏览器实测 /api/systems 403 抓到，ec3a2f8 修复）；浏览器实证：菜单「系统配置/基础设置」生效、三栏真实数据渲染、/systems 301→/system-config、基础设置 4 tab、shared 层 internal_token 归位（system 层已净） |
| T-1011 | M-D | 飞书话题通用召回（agent 全会话可用：摘要注入+meta常驻工具+关键词命中+技能） | wt/topic-recall | T-1010 | ✅ 08-24 复验通过（合并 f3fc9e7） | sess-topic-recall | 08-24 总控人拍板：话题池从「人工工作台+图谱」双消费面升级为 agent 通用基础聊天上下文（不让用户重复群里说过的事），非产品/测试专属。四条路线全做：A=system prompt 注入话题摘要（时效分级：近3天全部非闲聊[含draft，用户确认概率低]+近4-7天仅 high 优先级，rejected/chat 不注入，cap 防爆）；B=meta 域常驻合并工具 topic(action=list/search/read/messages)——read 返回全卡+原文口子，messages 回放共享区群聊快照消息段（群聊=T-949 已是公共资产，读共享材料区）；C=用户消息关键词命中话题 keywords/title 自动注入命中卡（仿 match_skills_hint，cap 3 条）；D=feishu-topic 技能文件（keywords 挂「群里说/讨论过/话题」类词，product 技能白名单同步补）。纪律：工具走 tool_meta consolidate+domain=meta 常驻（resolve_tools 并集 meta 域，不挤 purpose ≤15 名额），纯读 side_effect 自动 product 可见；顺手修 sg_core/feishu_paths docstring 过时口径（T-949 后快照已落共享区） 【08-24 主库验收打回】离线门禁全绿（test_specstd 1775/engine_modes 39/test_engine 230/release_check PASS 回边 5 条零新增），联网实测 FAIL：工作区共享材料区 {ws}/.specflow/feishu_pool/_topics.yaml 种子 4 卡（2 应进摘要）在位，agent 却答「话题库当前是空的（count: 0）」且 system prompt 摘要块为「近期无非闲聊话题」——有数据却答没有。根因：topic_digest._material_root() 与 topic_query._root() 均调 specflow_dir("")，而 specflow_dir 空 emp 参数会回退请求上下文工号（auth._authenticate 每个请求都 set_context_emp_no），真实会话恒解析到 {ws}/.specflow/{emp}/ 用户私有区（共享区永不可达）。钉案实证：同一种子数据复制到 admin 私有区后实测 B 全通（search→read+messages 并行、原文 4 条精确回放、群名解析正常），证明召回逻辑本身正确、仅目录解析错。修复方向：给 specflow_dir 加 force_shared（镜像 specguard_dir 既有参数），topic_digest/topic_query 改走强制共享区；修复后须补「emp 上下文下读共享区」的回归测试（现有 25 测试均显式传 material_root 或无 emp 上下文，恰好掩盖生产路径）。波及面另报总控人：同根因疑似波及 T-949 存量面——workbench feishu_pool 路由 _material_base() 与 services/specflow/feishu_watcher.py 的 specflow_dir("") 调用同样解析私有区（实证：90000001/feishu_pool/docs 落私有区、admin/ 目录被请求自动创建、topics API 在共享区有数据时返回空），飞书话题页与同步可能同样读错位置，建议另立任务排查。验收环境留痕：共享区种子数据保留在 _clones/tdm/.specflow/feishu_pool/（供修复后复测），WS 驱动验收脚本在 agent/sessions/_accept_t1011_ws.py（A/B/C/R 四模式）。【08-24 波及面同树修复·总控人指令】T-949 共享面同根因统一 force_shared（路由 _material_base/watcher resolve）+两旁路补 material_root（_trigger_pull 事件直写/user_materials_job）+migrate_legacy_pool 补 docs/minutes 缺口与 migrate_all_private_pools 全员幂等迁移（接线 sync 端点与 start_all 启动自动归拢）；+7 测试/1785 绿/release_check PASS；生产私有区实测仅空目录无可迁文件，复验时先点一次同步或重启后端即自动归拢。 【08-24 主库复验 ✅】离线：test_specstd 1786 绿（较首次 +11，含根因回归 4 与波及面 7）/engine_modes 39/test_engine 230/release_check PASS（回边 5 条零新增）；离线合并冲突两处（总控 T-1011 行取分支版+T-1012/T-1013 保留、经验包 README 索引并集）。联网：①A 摘要注入 PASS——agent 答出全部 2 条合格话题（九宫格落位接口超时修复验证 draft high + 盘点会话权限矩阵回归 confirmed high），chat/rejected 正确排除，system prompt 常驻摘要块载荷级实证；②B 工具召回 PASS——topic(action=read)+topic(action=messages) 并行直调（id 已在摘要），4 条原文（张伟/李芳/王强）精确回放、群名「TDM 研发协作群」解析正常；③C 关键词命中 PASS——「九宫格」命中，首轮消息前注入[话题命中]卡（会话 JSONL 载荷级实证），agent 零搜索直读命中卡；④用途回归 PASS——requirement_interview 会话 topic(action=list) 可用（meta 常驻不挤名额），test_workbench 白名单快照 7 域含 domain:meta 无 domain:specflow（未泄露）。波及面：sync 端点触发 migrate_all_private_pools——探针文件+meta sidecar 自 90000001 私有区迁共享区、私有清零；同步拉取 minutes×20（40 文件含 sidecar）全落共享区、私有区零新写；二次同步幂等（文件数/话题卡数不变）；话题页 API 出 4 卡（首次验收返回空的失败点修复）；watch 配置 PUT/GET 仍读写 {emp}/ 私有区（feishu_watch.yaml，共享区无文件），谁配置谁拉设计不变。留痕一项（非缺陷）：start_all 启动迁移在注册表 active 为空时静默跳过（无激活工作区诚实降级），本环境经 sync 端点完成迁移，与简报「重启或点同步二选一」一致。 验收后补网：群聊下拉变日期——list_pool_materials 从共享 base 读 watch 配置（池拨正共享后配置区错位），群名全灭回退日期文件名；修复=服务加 watch_base 参数+路由传 _sf_base()，TDD 回归 1 条（池在共享/watch 在私有生产形态），90024166 人才发展实测四群名全恢复。 |
| T-1012 | M-D | 飞书授权「缺 1 项权限」误报修复（必需 scope 名 contactuser:search→contact:user:search） | wt/material-pool | T-1009 | ✅ 08-24 主库验收（合并 45a661e） | sess-lark-scope-fix | 08-24 总控人实测上报「授权全部完成仍提示缺 1 项」——根因：lark_auth._REQUIRED_SCOPES 首项 contactuser:search 系 08-18 照抄网关报错文本（T-943 备注「实测缺 contactuser:search」），而 auth status 实际授权清单返回飞书官方命名 contact:user:search（带冒号），字符串比对永不命中→已授权用户恒报缺。钉案实证：90024166/90000001 两工号 token 授权全集 200 项含 contact:user:search，且持 token 直调 contact +search-user 成功返回 4 用户——权限真实具备，纯比对名单写错。修复：_REQUIRED_SCOPES 改官方名+回归测试钉死（用实测原始 scope 名断言 missing 为空）；test_status_missing_and_reviewing 断言同步改名。注：test_feishu_pool_page 网关报错文本 mock 保留原样（错误透传路径测的是真实网关消息，与授权清单命名两码事）。【08-24 主库验收】test_specstd 1751 绿/engine_modes 39/test_engine 230/release_check PASS；真实账号复测决定性实证：合并后主库 do_status 对 90000001/90024166 两工号 missing_scopes 均归零（[]），前端「缺 1 项权限」黄条随之后端重启即消失。 |
| T-1013 | M-D | 系统配置页三处打磨（显示模式切换/注册工作区弹层/注册系统弹层减负） | wt/system-config | T-1010 | ✅ 08-24 主库验收（合并 d15fed9，任务号因撞号由 T-1011 改记 T-1013） | sess-system-config | 08-24 总控人实测三意见：①栏3原文+预览上下同屏挤→改「显示模式」按钮切换（📝原文/👁预览/🗄数据库，各自占满栏内空间），数据库连接并入本系统配置第三显示模式不再单独占区域（通用配置层无 db 模式自动回退原文，三模式 sg_sysconf_view 持久化）；②注册工作区内联表单改弹层（与注册系统一致，z-40 让 DirectoryPicker z-50 浮上，注册成功自动关弹层）；③注册系统弹层改名「注册系统」（原「注册系统包」）、删「首个环境配置」块（引导文案：环境配置注册后到栏3维护）、接入分级加随选人话解释（config=纯配置栏3维护/template=+断言模板栏1详情/code=+extensions.py 评审闸热加载）；验证：build 56.7s/oxlint 0 errors（触碰 3 文件）/vitest 92 绿；浏览器实证：三模式按钮+弹层触发渲染到位（点击深验因 IAB 动作通道当日不稳未全通，渲染件快照实证，逻辑为 setState 条件渲染与已验证 scope 开关同构）；总控§6 登记 3 文件 |
| T-1014 | M-D | 单群同步三通道 + 话题材料页签下线群聊行 | wt/material-pool | T-1012 | ✅ 08-24 主库验收（合并 90d6d30；分支内代码注释/commit 以 T-1013 落笔——与系统配置 T-1013 撞号，登记改记 T-1014） | sess-material-pool | 08-24 总控人派工（更新群信息两入口答疑后拍板）：①「更新本群」单群模式放开 docs/minutes（删 if not chat_id 守卫——仅群聊收窄单群，文档/妙记全局资产照常同步；test_sync_all_single_chat 语义重写先红后绿）+按钮 title/notice 文案同步三通道口径；②话题材料页签下线群聊行（与话题页签原文时间轴重复展示消除；展示层过滤，materials 全集保留供 useChatOptions 派生；MatType/类型 chips/localStorage 恢复去 chat 维（存量值诚实回退 all）；ChatDetailView/openDetail chat 分支/ImageLightbox 等死代码随清）；验证：feishu 294 绿/engine_modes 39/build 36.6s/lint 8 errors 持平零新增（warnings 较基线 -15）/vitest 92 绿/release_check PASS；commit：ee157e3+7de63c5+c13a6d1。【08-24 主库验收】离线：test_specstd 1849 绿/engine_modes 39/test_engine 230/release_check PASS/build 49s/oxlint 8 errors 存量持平零新增/vitest 101 绿；合并冲突 2 处（TopicCard/TopicWorkspace 与 tag-taxonomy 各加 prop 与 import，双保留解法），总控文档无冲突。联网实证：①「↻ 更新本群」单群同步 200——chats 4/chats_empty 3/docs 0/minutes 20/errors []，notice 三通道口径「文档 N / 妙记 N」与按钮 title「同步本群聊天记录 + 文档 + 妙记」代码+接口双侧实证；②材料页签浏览器实证：chips 仅 全部(20)/文档(0)/妙记(20) 无群聊、列表 20 行全妙记无 chat 行、「群聊快照不再重复展示…」说明文案在屏、话题页签左侧时间轴消息流渲染正常；④「⇩ 立即同步」全量 200——chats 10/chats_empty 18/docs 0/minutes 20/errors []（docs 0 系 watch 未配文档通道的数据实相，非缺陷） |
| T-1015 | M-D | 话题↔文档/妙记 references 关联（话题材料融合进话题模块） | wt/material-pool | T-1014 | ✅ 08-24 主库验收（合并 90d6d30；分支内代码注释/commit 以 T-1014 落笔——随上条撞号顺延改记 T-1015） | sess-material-pool | 08-24 总控人拍板（话题已有原文关系，材料页无需重复展示；文档/妙记合并进话题模块强化关联）：①specflow 新增 topic_material 确定性预筛（时间窗±7天+标题相似0.4/关键词命中——妙记 artifacts.keywords 求交/文档文本包含；闲聊与 rejected 话题不荐；群聊材料不进范围因话题已 message_ids 直连；零 LLM，仿 T-993 D5）；②list_pool_materials 妙记附 keywords（_minutes_digest 重构委托）+list_pool_topics 响应派生每卡 materials 与 material_suggestions（不落库，同 T-992 modules 口径；links 单次加载）；③/topics/material-relate 端点人工确认/忽略写 references 边（confirmed 时材料副本 promote_node 提升图谱派生源；复用 T-993 直接确认链路，不进复核队列——队列专职 FR mentions）；④graph builder 零改动承接（edge 分派+节点存在守卫，回归测试钉契约）；⑤话题卡关联材料 chips（📄/🎙 点击开详情弹层）+工作台「🗂 材料推荐」面板（确认/忽略）；LLM 精筛本期不做（YAGNI）；顺手修 E741 l→link 三处（Boy Scout）；验证：topic_material 10/pool_page 46/t948_router 19/graph_index 38/feishu 294 绿/全量 test_specstd 1804 绿/engine_modes 39/release_check PASS/build 36.6s/lint 8 errors 持平/vitest 92 绿；commit：127c675+9d460fa+c2a2609+e27af37+500785e+d50ea37；实施计划：docs/upgrade-plans/2026-08-24-T1013-1014-话题材料融合-实施计划.md（6ee78cc）。【08-24 主库验收】联网实证：③material_suggestions 36 条带分数+理由（关键词命中）；确认 tp:b50e2cb8-20260818-01↔fm:obcniui4s786op13446t2n6g → 200 confirmed、话题卡 materials 挂卡（🎙 妙记标题）、该对即时退出候选；material-content 200 正文 824 字（chip 详情弹层数据源）；忽略同话题另一对 → 200 rejected 留痕且退出候选；material_links.yaml 双记录落盘（confirmed 1.0/rejected 0.0，confirmed_by 90024166）。浏览器实证：话题卡 keywords 行下方 🎙 chip 在屏、点击开详情弹层渲染完整（妙记徽标+飞书直链+全文+原始 JSON 折叠）。图谱侧：graph_index.db 为存量快照未重建，references 边契约由 test_references_edges_derived 钉死（confirmed 建边/rejected·断链不建），test_graph_index 38 绿含在 1849 内 |
| T-1016 | M-F | 试跑报告读写路径错位修复（scenario_tools 写私有区 / attribution 读共享区 → 统一 reports_dir 强制共享区） | wt/engine-hardening | — | ✅ 08-26 主库验收（合并 1a0346d） | sess-engine-hardening | 08-26 总控人派工（HI-PERM-001 三连败事故复盘，agent_20260826_112426/112704/113207）：08-26 晨试跑落盘（2097591）写 emp 私有区、attribution/list_failures 读共享区，Agent 排障工具链对自己试跑完全失明；修复 + emp 上下文回归测试 |
| T-1017 | M-F | format_spec §1.13 python/http 文档补全（2.15.0 三同步） | wt/engine-hardening | — | ✅ 08-26 主库验收（合并 1a0346d） | sess-engine-hardening | 同上派工：明示 script 不渲染 {{}}/save 变量非脚本全局须 ns['名'] 访问 + 三类 save 产出结构（call={status,json,headers}/db_query=裸list/tool=工具自定）+ http(account) 完整签名（json_body=）与最小示例；不采纳事故报告 §5.1/5.2 的错误写法（平铺 key/foo.text/json= 均与实现相反） |
| T-1018 | M-F | python 步骤错误消息增强（脚本 NameError/KeyError 附 ns 可用键清单） | wt/engine-hardening | — | ✅ 08-26 主库验收（合并 1a0346d） | sess-engine-hardening | 同上派工：让 Agent 下次自愈而非猜结构 |
| T-1019 | M-F | HttpClient.request 兼容 json= 别名（对齐 requests 肌肉记忆） | wt/engine-hardening | — | ✅ 08-26 主库验收（合并 1a0346d） | sess-engine-hardening | 同上派工：json= 与 json_body= 同义，双给报错；post() 同步支持 |
| T-1020 | M-F | 产物活动流水（product_activity 表：会话↔产物↔版本链落 DB）+ reset 按会话收窄 + write_draft overwrite 模式 + 更新足迹/草稿产物分签 + 面板 DB 化跨会话接管 | wt/draft-activity | — | ✅ 08-26 主库验收（合并 cd6b788 + 回退 bc62c79） | sess-draft-activity | 08-26 总控人派工（20260825_151821_3178914e 会话 draft reset 事故复盘）：Agent 五次自调 reset 清空全工作区草稿（含用户 v0.3 修复版）——根因双层：①reset 无确认环节且不分会话归属；②write_draft 禁覆盖无出口，Agent 被 OVERWRITE_DENIED 逼向 reset 绕路。方案拍板：F1 sg_core/product_activity 流水表（session_id/emp/workspace/action/version_no/sha/content 全文快照，contextvar 上下文零传参）F2 draft_writer 六 handler 挂钩+reset 会话收窄（无会话拒绝）+write mode=overwrite（旧版自动留档）F3 gate_dock 迁 contextvar（退役 _session_id 特权参数）F4 writing_feed DB 优先消息重放兜底 F5 前端草稿产物面板 DB 化（全量草稿+来源会话+版本链，跨会话可见）+更新足迹/草稿产物分两页签（草稿产物前置）；product_index 并存过渡一个迭代后废弃；验收裁决：F5 前端跨会话接管展示整体回退（bc62c79，面板维持本会话草稿口径，分签保留），后端 product_activity 流水 + /activity /versions 端点 + writing_feed version_no 保留为数据地基；验收顺手修 992f464 存量红灯（HI-PERM-001 漏标 dimensions，cae6e17） |
| T-1021 | M-F | AgentChat 会话运行中重连续传（SessionEventBus 会话级事件总线：fan-out 多订阅者 + 当前 run 事件回放缓冲 + attach/detach 协议 + 基线截断去重） | wt/agent-resume | — | ✅ 08-26 主库验收（合并 db2a8b5，含验收期竞态修复） | sess-agent-resume | 08-26 总控人派工（用户实测上报：刷新页面重进会话提示「会话仍在后台执行」只能干等）。现状：run 事件桥接到发起连接私有 queue，断连即丢事件；run 产出仅完成时落盘；重进连接无法订阅已开始的 run。方案（完整版非轻量轮询）：①services/session_event_bus.py 会话级总线（per-session 环形缓冲保留当前 run 全部事件，run_started 重置基线，done/error 广播后频道懒清理）②WS 协议加 attach/detach 消息类型（attach 回放当前 run 事件流+实时续推，归属校验，run 结束自动退出；detach 游离消息忽略）③run 事件改发布到总线，发起连接经 attach_live 订阅（行为不变）④getSession 响应加 run_in_progress/run_baseline_len⑤前端 restoreSession/重连补拉发现 run 进行中→截断消息到基线+attach+loading 态；事件带 session_id 过滤防切会话后旧流污染（顺带修不同会话并发 run 事件混流） |
| T-1022 | M-F | python 脚本 SystemExit 击穿进程防护（flow python 步骤 + verify python 断言脚本统一包装为场景编写错误并指路 SkipScenario；format_spec 2.15.1 三同步） | wt/engine-hardening | — | ✅ 08-27 主库验收（合并 a9e898f） | sess-engine-hardening | 08-27 派工（HI-PERM-004 排障复盘）：EX-dc874ada/EX-b9c359ba 脚本 raise SystemExit 裸穿 except Exception（BaseException）致运行进程崩溃——run.json 空文件、工作台 Internal Server Error、UI 回退显示老 404 报告制造「修复无效」假象；TDD 双测试（步骤级 ScenarioScriptError 包装 + 断言脚本级 trace 原地落盘） |
| T-1023 | M-D | 场景 YAML 结构化阅读视图（ScenarioReader：doc 分块/covers·related_ac 锚点芯片点击展开 spec 原文/flow 步骤卡片注释提炼+脚本折叠/verify 友好标签；FileViewer 双视图 + ScenarioFormEditor 三模式；后端 anchor-refs 接口 + sections 纯函数下沉 sg_core） | wt/scenario-reader | — | ✅ 08-27 主库验收（合并 e3a1a93，含验收期注释丢失修复） | sess-scenario-reader | 08-27 总控人派工（20260827_094125_f955645e 会话 HI-PERM-002.yaml 查看痛点）：测试人员看场景只有纯文本，covers/related_ac 只有代号须翻 spec 文档，python/SQL 注释理解门槛高。方案拍板：FileViewer + 场景编辑器双挂载，锚点原文点击就地展开；同号歧义（FR-005 全工作区 26 处）返回全部候选按 hint 路径词排序可切换 |
| T-1024 | M-D | 关联需求打开对应 spec 文档（锚点面板「📄 完整文档」弹层：全文拉取 + LocatedTextView 定位高亮锚点段；AgentChat 场景「页签打开 ›」开独立文件页签；matches 增 rel 相对路径；LocatedTextView 拆独立文件复用） | wt/scenario-reader | T-1023 | ✅ 08-27 主库验收（合并 c519d66） | sess-scenario-reader | 08-27 总控人实测 T-1023 后派工：锚点展开只有片段文本无上下文看不懂，需要能打开对应的 MD |
| T-1025 | M-D | 锚点候选按模块相关性收窄（matches 增 score，相关候选默认展示/零相关折叠「其余 N 处同号」）+ 完整文档弹层改 markdown 渲染（hast position 行区间高亮 + 自动滚动定位，替代纯文本 LocatedTextView） | wt/scenario-reader | T-1024 | ✅ 08-27 主库验收（合并 0a228e0） | sess-scenario-reader | 08-27 总控人实测派工：①制作测试用例视角应筛出对应模块 spec 而非全库扫描平铺 26 处 ②完整文档按钮打开的 MD 要渲染格式不是文本 |
| T-1026 | M-D | AgentChat 侧边面板低频页签聚合（操作台/阅读/更新足迹/合规/知识/依赖图/提交历史 七签收进「更多」面板选择器：卡片网格弹层选择打开，页签条只留高频签；活动中的低频签暂显条内、切走即隐；外部 expandSideTo 跳转入口保持直达） | wt/scenario-reader | — | ✅ 08-27 主库验收（合并 f76a5ad） | sess-sidepanel-hub | 08-27 用户直接反馈（对标 VS Code 侧栏「打开标签页」聚合样式）：七个低频功能强塞页签条挤占注意力，实测使用频率低，聚合成单一入口降噪 |
| T-1027 | M-D | 话题携带文档类材料·立项设计稿（群聊分享的云文档/妙记/文件从占位符升级为一等公民：卡片消息渲染保真 + 飞书链接确定性提取 + 话题卡 shared_materials 事实字段；本任务只交设计稿与登记，不动代码） | wt/material-pool | — | ✅ 08-27 主库验收（合并 8c33e3a） | sess-topic-docmat | 08-27 总控人拍板立项（「话题需要能有文档类的内容，不能指望什么消息都以文字的形式发到群里」）；实测排查：JSONL 事实源未丢数据、丢真在派生视图（render_md 未知类型纯占位 / _load_window_source·compose 只保 text）；设计稿《远期设计/SpecGuard-话题携带文档材料设计-T1027.md》；拍板已过（08-27 总控人：①缺失快照即时补拉+失败诚实降级 ②chips 合并渲染徽标区分——均按推荐采纳；③图谱建边本期不做、将来必做，已入灵感库挂三条可判定重启条件）；**验收节奏总控人改定（08-27）：T-1027+T-1028+T-1029 一包验收，T-1030 另起第二包**；**主库验收（08-27 合并 8c33e3a）：四门禁+ruff 全绿**，门禁数字与本包偏差注记统一记于 T-1029 行 |
| T-1028 | M-D | F1 数据层：lark-cli 卡片类消息契约实测夹具入 test_feishu_chat_store（云文档分享卡/妙记卡/post 超链接形状钉案后才动渲染代码）+ render_row_body 收敛三处渲染口径（日级视图/_load_window_source/compose）+ extract_feishu_links 确定性提取 | wt/material-pool | T-1027 | ✅ 08-27 主库验收（合并 8c33e3a） | sess-topic-docmat | 08-27 总控人拍板立项后续接派工；契约实测结论（真实池全量扫描）：本租户文档分享事实形态=纯文本 URL 三种已钉案，另钉 system/video_chat；**interactive 分享卡当前所有池子零实体**——卡片渲染按 D1 走未知类型可读化兜底，提取器与消息类型解耦将来自动网住，契约夹具随真实样本再补；TDD 先红后绿，test_feishu_chat_store 23 绿（+6）/全量 test_specstd 1944 绿 6 跳；顺手修正则回溯坑（尾段 `*` 防 token 末位被借）；一行一消息铁律不破；主库验收（08-27 合并 8c33e3a）：四门禁+ruff 全绿，详见 T-1029 行门禁记录 |
| T-1029 | M-D | F2 装配联动：cluster/draft/compose/regen 四路 shared_materials 推导 + edit/regen 重算守卫 + 缺失快照补拉钩子 + list_pool_topics 透出快照联动字段 | wt/material-pool | T-1028 | ✅ 08-27 主库验收（合并 8c33e3a） | sess-topic-docmat | 08-27 续接施工；实施细化两拍板落点：①存储事实/读取联接——yaml 卡只存消息推导事实（kind/token/url/message_id），快照挂接（snapshot_ref/title/in_pool）与 modules/materials 同为响应时派生不落库，消除回填时序复杂度；②D4 补拉走显式 POST /topics/material-fetch（topic_id 维度逐链接单条 sync、失败诚实报错列表），GET 保持纯读纪律，同时满足体验基线⑤「就地补不打断」；测试 test_topic_shared_materials 9 例（derive 去重/attach 守卫/cluster·draft·compose·regen·edit 五路/resolve 联接/补拉幂等与失败降级）+ 全量 test_specstd 1953 绿/ruff 触碰六文件 0 errors（顺手清存量 E741/SIM103/I001）；**自验收实证**：离线四门禁全绿（specstd 1954/engine_modes 39/test_engine 244/release_check PASS/ruff 触碰文件 0 errors）；真实池只读三层全过——①渲染保真（system/视频/链接行真实快照可读）②存量卡只读回放三张真实话题命中共享材料（打分表 sheets/纪要 docx/817 截图 docx，均如实标未同步）③双轨对照 references/suggestions 不受影响；沙箱隔离副本真拉端到端（不污染生产池）：fetch_topic_materials 单条 docs 直拉 **35024 chars 真实正文落盘** + resolve 回看 in_pool=True；**主库验收回标（08-27，合并 8c33e3a，ff 无冲突）**：离线门禁——test_specstd **1954 绿 6 跳**/engine_modes 39/test_engine 244/release_check PASS/ruff 触碰十文件 **0 error**（验收顺手机械清本包带入的 15 项存量 style：I001×6+E741×8+B905×1，集中 test_feishu_chat_store.py，语义零变更、该文件 23 例复跑绿）；真实池/沙箱实证按树内自验收默认采信。**偏差注记（唯一）**：test_agent::TestMaterialE2E 在本机主树现状节奏下受 **T-081 纯读守卫指纹竞态**误伤——none 级工具执行的前后目录指纹窗口内若有异步写入落盘（如审计 WAL checkpoint 刷真 workbench.db）即误判 SIDE_EFFECT_VIOLATION 替换载荷致内容断言失败；属存量测试基建脆弱点被本包新增用例改变套件节奏放大，非本包代码缺陷（归因实验链：①真库移开→四件套全绿 ②守卫快照采集加毫秒延迟→无库全量满额 1954/6 绿 ③基线树 9624be5 同码全绿 ④受害例随套件组成漂移——另一窗口命中 TestRuntime::test_tool_execution 的 JSONDecodeError 同根因）；建议另立专项治理守卫竞态（隔离易变面/quiesce 后台写入），不影响本期合并裁决；该竞态已由 T-1033 治理闭环（用户拍板：守卫只守工作区文档——覆盖面收窄为工作区产物，运行态文件与仓库面移出指纹，全量复跑 **1984 绿 0 失败 0 跳**，历史脆弱点消失）
| T-1030 | M-D | F3 召回与前端：topic_digest 摘要注入/topic query read 携带 shared 材料 + TopicCard chips（徽标区分事实/已确认）+ 时间轴与详情弹层文档行渲染 | wt/material-pool | T-1029 | ⏳ 未认领 | — | **第二包单独验收**（前端有独立浏览器实证点）；T-1011 召回四路的自然延伸——「群里那份方案文档」成为 agent 可口述可展开的事实 |
| T-1031 | M-D | 辅助会话定位升级「辅助助手」（SQL 助手通用化改名 + 父快照注入增强 + 查看指针 `<viewing_context>` 随消息携带 + SqlAuxPanel 对话渲染与主会话同链 + 上下文用量条） | wt/agent-aux | — | ✅ 08-27 主库验收（合并 68c103c + 修复 f3b406a；不过→当场修复→复验通过） | sess-agent-aux | 离线门禁记录：release_check PASS/specstd 注入 SG_AUX_TEST_TMP 后 **1980 绿 0 跳**（test_parent_digest 14 例点名过、test_mcp_server 注册钉子 41 含 parent）/engine_modes 39/test_engine 244/vitest 168/build PASS/ruff 持平达标（runtime.py 27=27、routers/agent.py 40=40、test_aux_session E402 存量 1=1、新文件 session_digest/parent_tool/session_context/test_parent_digest 全 0 error）；runtime 改动纯 +23 行不涉 T-081 守卫指纹段。**工作台实证通过点**：①页签「🤝 辅助助手」在位且「SQL 助手」全页零残留、面板头部「辅助助手（辅助会话）」✓；③折叠式工具组（draft/info_pack ▶ 块）+markdown 富渲染+用户气泡无 `<parent_context>` 等注入块裸露 ✓；④📊 上下文堆叠条完整（50.5K/400.0K tokens、系统/用户/助手/工具四角色占比、↑54.5K↓2.0K、上限随所选模型）✓；⑧⑨ parent(action=summary/recent) 双动作在真实轮次中发生且新鲜度无「落后 N 条」告警 ✓。**致命缺陷 A（②触发路径结构性不可达）**：AgentChat.tsx getViewing() 要求发送时刻活动侧签=file:*，而打字必先切到辅助面板 ⇒ focus_path 恒空、后端永不注入 `<viewing_context>`（本轮 user 消息磁盘验证无该块）——实测模型仍先搜场景库扑空再经父快照自纠 spec read 收束，「第一动作读当前文件」未达成；**连带缺陷 B（影响 ⑪）**：SqlAuxPanel sidRef 守卫致单挂载内粘死首个解析会话、头部无会话切换入口，旧 sql_assistant 辅助会话（20260826_190257_393694ca 等）经现 UI 无路径恢复回放；⑤⑥产物卡/📎引用/▶DB 因需辅助会话真实写产物未现场复现（单测+源码采信按钮文案与直发回调语义），验收过程误点一次草稿评审通过钮（HI-PERM-002 会话内门态，未触达入库/仓库，用户侧可复位）；**修复与复验（08-27 总控人拍板主库当场修）**：A 改「当前或最近活动文件签」记忆口径、收敛 utils.resolveViewingFocus 纯函数+3 例钉；B 重写 ensureSession 使绑定跟随 mainSessionId（去 sidRef 粘滞守卫与无读者 localStorage 写，换绑清态+await 后竞态复核）；复验三点全过——①真实提问的 user 消息落盘含 `<viewing_context>`（指向 HI-PERM-002.yaml 含字节与开头摘录），回答直接讲透该文件断言语义零场景库绕路；②跨主会话绑定跟随父配对（切「并行写入两份需求草稿」aux=20260827_213156_0dc83671，切回=150916），旧辅助会话经打开其父即恢复；③修复后门禁：specstd 注入版 **1982 绿 0 跳**（含双钉）/engine_modes 39/test_engine 244/release_check PASS/vitest **171 全绿**/build PASS/ruff routers 40=40 持平 |
| T-1032 | M-D | 父会话脉络感知（每轮 run 后台 refresh_digest 落盘摘要 + 新 MCP 工具 parent summary/recent 限界读父 + 快照提示行白名单门卫） | wt/agent-aux | T-1031 | ✅ 08-27 主库验收（同批：68c103c + f3b406a） | sess-agent-aux | **致命缺陷 C（⑦ 直接受害）**：workbench/backend/routers/agent.py `_refresh_parent_digest_bg` 定义了闭包 `_llm(system,user)` 却从未使用，`llm_call=use_llm` 把 **LLMClient 实例当函数传入**——session_digest.refresh_digest 以 `llm_call(system,user)` 调用必抛 `'LLMClient' object is not callable`（磁盘铁证：20260827_150916_9272e88b_digest.md 内嵌 `<!-- llm_error: 'LLMClient' object is not callable -->`，其 json 在一次完整 LLM 轮次后仍 mode=skeleton）⇒ 每轮 WS run 后的 LLM 摘要全部静默降骨架，「非骨架脉络摘要」出厂即死；修法一行级（改传 `_llm` 包装闭包），属行为级修复回树内按 TDD 补集成钉子后再送验。spawn 兜底骨架（spawn backfill llm=None 路径）符合设计钉案不需动；skeleton 兜底内容质量良好（确定性提取用户请求清单）、诚实降级链路按设计工作；⑩ 工具域隔离由离线套件采信（runtime 白名单 + 注册表钉子，主会话逐项目测未做）；**修复与复验（08-27 当场）**：缺陷 C 一行级改传 `_llm` 包装闭包，并在 test_parent_digest.py 补可调用/mock 兜底双钉子（14→16 例）；主会话完整跑一轮后 digest 实证 **mode=llm**（updated_at 21:30:40、covered_len=143/turns=48、正文为真 LLM 脉络摘要、无 llm_error 注释）——⑦ 达成；spawn 兜底骨架路径语义不变照旧工作 |
| T-1033 | 测试基建·守卫治理 | T-081 副作用守卫覆盖面收窄——指纹只守工作区产物（私有/共享区），SpecGuard 仓库六目录与 workbench.db/ledger/registry 运行态文件移出指纹面（运行态异步落盘如 SQLite WAL checkpoint 曾撞进纯读毫秒级比对窗口造成 SIDE_EFFECT_VIOLATION 误伤，受害例随套件节奏漂移） | 主库（用户拍板当场修） | T-1029 注记 | ✅ 08-27 治理完成（55c4533；全量 specstd 注入版 **1984 绿 0 失败 0 跳** 竞态消失） | sess-acceptance | 现象/证据链/根因/预防全记录见经验包《2026-08-27-T1033-守卫指纹竞态-纯读误伤与覆盖面收窄》；防回潮双钉=AST 剥 docstring 源码钉+「仓库运行态不动/工作区必动」行为钉；守卫语义自此为「纯读工具不得写用户工作区文档」，运行态完整性归各自写通道与发布闸门 |
| T-1034 | 测试基建·凭据治理 | _shared sso.password 明文默认值出库（M 扫描单凭据红线 F3）——default 位清空为 ${SG_SSO_PASSWORD:}，tdm config.py 补 resolve_secret 同款回退（env 变量 → secrets.env → devops 过渡，与 client_secret/DB 密码对齐），本机真实值迁 ~/.specguard/secrets.env | 主库（用户拍板「两者皆可」当场修） | T-1033 | ✅ 08-28 治理完成（三钉 TDD 先红后绿；本机探针 load_env 取值成功；受影响面 66 测试绿/release PASS/ruff 持平） | sess-acceptance | AGENTS 08-27 条遗留待办闭环；M 扫描单 F3 行标记闭环；预防=新凭据一律走链、default 位只留空引用 |
| T-1027 | M-F | 草稿产物面板可编辑 + 对话感知人工编辑（F1 查看页签第三模式「✏️ 编辑」进入结构化表单编辑（DraftFormEditor 复用场景编辑器，表单默认/YAML 次选，Monaco 面板内直编退役），保存走既有 PUT；F2 保存后确定性自动校验+②闸刷新+活动流水 user_edit 版本链+对话感知注入——system 角色行落会话 JSONL（LLM 可见前端不显示），run 进行中写 pending 文件由 WS 开跑前排空注入；F3 ScenarioReader 结构化视图分区块 tab（业务语义/关联需求/执行步骤/验证断言/依赖产出，持久化+失效回退首签）） | wt/draft-activity | T-1020/T-1023 | ✅ 08-27 主库验收（合并 7e3a24a；合并提交 d4ead69） | sess-draft-activity | 20260827_094125_f955645e 会话复盘用户三点反馈：①草稿产物应允许用户直接编辑 ②编辑后对话要能感知并校验 ③结构化查看从上往下堆叠不知看哪里。K-046 已有 PUT 端点与 draftsApi.update 前端无入口；T-1020 版本链只挂 MCP 写路径 REST 缺席。完工：新增 services/panel_edit_feedback.py（note 构造/注入/排空纯函数）；drafts.py PUT 扩展（validate 报告+gate2 刷新+record_activity('user_edit')+percept 三态 appended/pending/off）；agent.py WS 开跑前 drain_panel_edits 并入 <panel_edits> 前缀（parent_block 同款先例）；FileViewer 场景 YAML 增「✏️ 编辑」（Monaco+dirty 跟踪+SaveOutcomeBanner 内联回显，非场景结构草稿同样可编辑）；AgentChat handleSaveDraftFile 接线（PUT 带 session_id+页签内容对齐+感知去向话术）；ScenarioReader 五区块分签（sg_scenario_reader_tab 持久化+失效回退首签）。验证：test_specstd 1947 绿（+10）/engine_modes 39/engine 244/release_check PASS/vitest 170 绿（+7：tabs 4+edit 3）/build PASS/ruff drafts 净修 19→12 零新增（顺手修 F821 get_context_workspace 缺导入+F401 未用）/oxlint 触碰文件 0 errors、FileViewer 回归基线持平、AgentChat 3e/91w 持平。**08-27 首轮验收打回→当日返修**：活体 F2 实证 Agent 被注记指引的 draft read（不存在的 action）带偏，draft write overwrite 两连发摧毁用户草稿后谎报"永久丢失"——根因=注入指引指向不存在工具。返修：build_edit_note 重写为「变更行摘录内嵌（± 前缀原文，Agent 零工具依赖可作答）+反覆盖护栏（禁止 draft write/overwrite 重写除非用户要求）+read 指引改真实 spec(action="read", path=<工作区相对路径>)（无路径诚实省略整行）+版本链快照恢复须用户授权」；截断策略改只裁摘录保护栏；测试 +6 至 16 例含「注记引用的工具必须在 tool_meta 注册表真实存在」对照断言与 read path 可执行端到端钉案；specstd 1953 绿(+6)/ruff drafts 12=12 基线持平/test_draft_panel_edit 16 绿。**复验必须包含真实 LLM 对话感知场景**（验收人原话），pending 抽查项一并补验。**08-27 用户调试反馈追加返修（4713167 后续）**：编辑入口原为 Monaco 直编裸 YAML，用户要求落在结构化预览上——新增 DraftFormEditor 复用场景编辑器三模式（默认进表单，YAML 降为其内部次选，与 Drafts.tsx 草稿评审页同形态）；参考 registries 懒加载失败静默降级；FileViewer 面板内直编退役（EditSaveOutcome 类型移 DraftFormEditor 转发导出保持 import 兼容）；vitest 171 绿(+1 重写+4)/build PASS/ruff 不涉/oxlint 触碰文件零新增（增量全为 react-in-jsx-scope 存量噪声）；**主库验收（08-27，组合批次单支先行）**：离线门禁合并态全绿——release_check PASS/engine_modes 39/test_engine 244/specstd 注入版 **2000 绿 0 跳**（含本支 16 例新测试）/vitest **23 文件 179 绿**/build PASS/ruff（drafts 12=12 净修持平、agent 40=40、panel_edit_feedback 与 test_draft_panel_edit 零 error）/oxlint 触碰文件 0 errors（AgentChat 3 errors/91 warnings 存量持平）。工作台实证：F1 九项过七、「三模式齐备/编辑即结构化表单/表单实质修改保存（横幅 ✓已保存·校验 PASS·error0/warn2+findings≤4+对话感知话术）/磁盘更新+.bak=验收前原文/坏 YAML 422 拒绝且红色如实回显（首测样本 P0 [ 实为合法标量属测试失误，真坏样本 [unclosed 拒绝闭环）/退出编辑不落盘/YAML 次选合法保存」全过；F2 活体全过——user 消息落盘含注记五要素（变更摘要/±行摘录/反覆盖护栏/版本链 v13/spec read 真实指引），问「我刚才在面板上改了什么」回复精准覆盖全部 3 次编辑且**全程零 draft write/overwrite**，对话流不渲染注入行，DB 抽检 sg_draft_gates gate2_status=pass 与横幅一致、product_activity user_edit 已入链；F3 分签持久化过（切执行步骤签刷新后仍激活）。**采信项活体补验（08-28 用户要求能补尽补）**：①非场景草稿编辑活体达成——造临时非场景 yaml 于草稿评审页打开：编辑表单五分区签空白区块不炸（字段空值+占位符+P1 默认）、YAML 模式显示原文可编、添加步骤不报错（验后临时件已删）；②场景库文件页签无✏️入口活体达成——经结构化关联需求 FR-005 芯片→「页签打开›」开 specs/data/history-inventory/spec.md 文件签：markdown 只读阅读视图，整页无编辑入口；③参考下拉正向渲染活体达成（非场景语境无 alert 报错，下拉组合正常；「缺失态为空+手填」细粒度仍采信——需 mock 后端不做侵入）；④pending 排空维持采信：活体窗口真实尝试（发长任务造 run→抢窗口面板保存）被 run 态 UI 吞点击+浏览器截图/探针通道反复不稳阻断，磁盘零变化可证未发生误写，该路径以 test_draft_panel_edit pending 用例+合并态全量 2000 绿背书；锚点芯片/完整文档弹层在②的芯片链路中顺带活体（score 面板+页签打开均真实触发）。**登记撞号提示：本任务与本日 sess-topic-docmat 的 T-1027（M-D 设计稿）同号，总控人后续裁决是否重编号**。还原纪律已执行：HI-PERM-002.yaml 与 .bak 恢复验收前原文，product_activity 台账留痕不清 |
| T-1039 | 工作台·信息架构 | Agent 对话按用途拆双菜单（测试对话 /agent · 产品对话 /agent-product）——融合单页改为菜单级固定用途：后端 rbac_store 种子加 menu-agent-product（公开菜单，原「Agent 对话」更名「测试对话」随 upsert 对齐存量）+ menus_for_user end 前缀防撞车规则；前端 AgentChat 收 fixedPurpose 路由注入（跳过用途卡片直接锁定/角色无权诚实 🔒 态/会话树按用途过滤·无用途历史会话归测试侧/?session= 深链按真实用途改道），_store 分侧快照（ensureSideStore 交换+buffer 清空+异侧切回自愈补拉 attach），localStorage 键按菜单隔离（sg_agent_session:test|product，旧键一次性迁移），WS 事件过滤收紧（loading 窗口外不放行异侧 run 事件），/materials·/scores·/zentao 重定向归产品侧，MyActivity 跳会话按 purpose 分流 | wt/agent-split | — | 进行中 | sess-agent-split | 用户派工（「测试和产品两个模块分菜单管理」）；后端 purpose 体系（T-010~T-013）已就绪，本任务纯信息架构层拆分 |
---

## 5. 会话注册表（开工必填）
> 表行格式：`| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |`
| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |
|---|---|---|---|---|
| sess-agent-split | 工作台·信息架构 对话双菜单拆分施工（wt/agent-split 树） | T-1039（进行中） | 2026-08-28 | 用户派工；文件读写一律树路径，只跑离线测试，提交即推。完工口径：vitest 188 绿（+9：utils 5 + sessionStore 4）/test_menu_migration 7 绿（+3）/build PASS/oxlint 触碰文件 3→1 errors（新代码零 error，顺手补两个存量 exhaustive-deps）/ruff 2=2 存量持平/release_check PASS |
| sess-scenario-reader | M-D 场景结构化阅读视图施工（wt/scenario-reader 树） | T-1023（✅ 08-27 主库验收合并 e3a1a93）→ T-1024（✅ 08-27 主库验收合并 c519d66）→ T-1025（✅ 08-27 主库验收合并 0a228e0） | 2026-08-27 | 总控人派工（HI-PERM-002.yaml 查看体验）；文件读写一律树路径，只跑离线测试，提交即推。主库验收结论：离线四门禁全绿（specstd 1937/engine 238/engine_modes 39/release_check PASS；树内 ruff 触碰文件 10=10 基线持平零新增、oxlint 触碰文件 0 errors 且 FileViewer 告警 60→8 净降、vitest 157 全绿、build 成功）+ 工作台实证三点全过：①草稿评审页 HI-PERM-002 阅读模式——业务语义/关联需求芯片（FR-005 26处等同号标记）/步骤卡片+①~⑥注释/断言友好文案全上屏；②FR-005 芯片点击就地展开 spec 原文（data/history-inventory 经 hint 排序居首，同号候选可切换）；③AgentChat 恢复 094125 会话→草稿产物→查看，file: 页签默认进结构化视图（原痛点入口）。验收期发现并修复：form→read 无条件 yamlDump 致步骤注释全灭（脏标记跟踪 e3a1a93）；locator 点击超时系 IAB 动作通道不稳，CUA 坐标点击等效通过。T-1024 主库验收（08-27，合并 c519d66，无冲突）：离线门禁全绿（anchor_refs 7+sections 15/release_check PASS/oxlint 触碰文件 0 errors 且顺手修复 SidePanel 存量 exhaustive-deps error/build 55s）+ 工作台实证两点全过：①FR-005 面板「📄 完整文档」弹层——spec.md 全文自动定位 69 行高亮、上下文 FR-006~010 同屏可读、加载中/错误/就绪三态分离；②「页签打开 ›」开独立文件页签（markdown 渲染 + 大纲导航）；rel 字段接口实证 specs/data/history-inventory/spec.md。T-1025 主库验收（08-27，合并 0a228e0，无冲突）：离线门禁（anchor_refs 7 绿含 score 断言/release_check PASS/oxlint 0 errors/build 56s）+ 实证：①score 接口实证 26 候选收敛 11 相关（data/history-inventory score=2 居首），面板默认只显示相关候选、其余折叠「其余 N 处同号 ▸」；②完整文档弹层 markdown 渲染（列表/代码 span 排版正常），FR-005 行 69 高亮 + 自动滚动到位 |
| sess-sidepanel-hub | M-D 侧边面板页签聚合施工（wt/scenario-reader 树） | T-1026（✅ 08-27 主库验收合并 f76a5ad） | 2026-08-27 | 用户会话直接派工（七个低频页签聚合降噪，对标 VS Code「打开标签页」卡片样式）；文件读写一律树路径，只跑离线测试，提交即推。开工基线 9e7ac3f（T-1025 验收回标后与 master 同点）。完工：SidePanel 注册表增 lowFreq 分层（gates/reading/writing/spec/knowledge/deps/history 七签收进「更多」选择器，活动签暂显条内、expandSideTo 跳转不受影响）+ MorePanelsMenu 卡片网格弹层（打开面板标题+足迹计数徽标+Escape/外点关闭）；SidePanel.test 6 例（高频签常驻/卡片网格含计数/点选回跳/Escape 重开/暂显含计数+面板就地渲染/外点关闭）。离线门禁：vitest 163 全绿（157+6）/oxlint 触碰三文件 0 errors 且零新增告警类型（仅 react-in-jsx-scope 全仓环境噪声）/build 57s PASS。主库验收（08-27，ff 合并 f76a5ad）：离线四门禁全绿（release_check PASS/vitest 163/oxlint 触碰文件 0 errors/build 58s）+ 工作台实证四点全过（9100 生产构建新 bundle，AX 树+截图双证据）：①页签条只剩 待办/草稿产物(2)/技能/SQL 助手 + 「⊞ 更多」，七低频签全部不再常驻；②「更多」弹层「打开面板」标题+副文案+七卡片网格（与用户参考图同款）；③点「合规」卡片→弹层收起+「📏 合规」暂显条内+🛡 Spec 校验面板就地渲染；④切回待办→暂显签消失。验证页签已关闭还原现场 |

| sess-multi-system | M-A 多系统贯通施工 | T-970（✅33682ba）→ T-971（✅0fbcd9e）→ T-972（✅f52d3a9）→ T-973（✅9d4bf6c）→ T-974（✅ea2b6c0） | 2026-08-21 | M-A 全部完成待验收。要点：bootstrap组合根（顺带修复plan_executor漏注册oracles）、resolve_system唯一口径+runner断链修复（SPEC_GUARD_SYSTEM/SG_SCENARIOS_ROOT按工作区注入）、引擎grep零tdm（format_spec 2.12.0/2.13.0三同步）、系统包分级动态注册（sha256评审闸不可绕）；离线全绿227+39+1622+release_check PASS |
| sess-lark-dev | 飞书 CLI 集成施工 | T-701（✅）→ T-702（✅）→ T-703（✅ 形态变迁） | 2026-08-11 | T-998 对账 08-21 全部落地；T-703 孤儿件（lark_binding router + LarkBinding 页未挂载）留痕可清理 |
| sess-agentchat-material | AgentChat 材料工作流 + purpose 面板装配施工 | T-930（✅）→ T-931/T-932（✅）→ T-937~T-942（✅）→ T-933 ~ T-935（✅ 由 sess-material-pool 并入 T-990 施工，08-21 主库验收） | 2026-08-17 | T-930 监听选择器+可读层（aefd802/e4633a2/b1d15ff）；T-931/T-932 面板装配（42c851a）；T-937 同步设置体验（b002749）；T-938 群聊后台预热（cdf8d6e）；T-939 材料原文+图片直出（f66330b+1c90b83）；T-940 监听用户视图+按人切换+飞书直链（4a7f656）；T-941 同步设置去重+错误人话化+搜索解耦（871d64c）；T-942 授权闭环入弹层（006c5c2）；T-933~T-935 已随 T-990 吞并完成并验收，T-936 储备 |
| sess-material-pool | M-D 材料池演进施工（wt/material-pool 树） | T-990（✅ 08-21 验收合并 2b0691a）→ T-991（✅ 同批验收）→ T-992（✅ 6ec3989 已验收）→ T-993（✅ 871f2a3 已验收）→ T-1001（✅ 08-23 验收合并 66cb8e7） | 2026-08-21 | T-990 五提交+T-991 fd7747e+T-992 6ec3989+T-993 871f2a3；T-1001 话题工作台体验升级（总控人直接派工）；树已 reset 至 origin/master 6e7d79b 再出发；本会话文件读写一律用树路径，只跑离线测试与前端 build，提交即推 |
| sess-topic-docmat | M-D 话题×文档材料立项施工（wt/material-pool 树） | T-1027（✅ 08-27 主库验收）→ T-1028（✅ 08-27 主库验收）→ T-1029（✅ 08-27 主库验收） | 2026-08-27 | 总控人对话内拍板立项并改定打包验收节奏（T-1027~T-1029 一包/T-1030 二包）；文件读写一律树路径，只跑离线测试，提交即推 |
| sess-agent-aux | M-D 辅助助手升级施工（wt/agent-aux 树→总控人拍板主库当场修收口） | T-1031（✅ 08-27 主库验收 合并 68c103c+修复 f3b406a）→ T-1032（✅ 同批验收通过，mode=llm 实证） | 2026-08-27 | 用户实测派工（aux 问 HI-PERM-002 迷航）；首验三缺陷退回后当场修复；复验三点全过+全量门禁绿（specstd 注入版 1982 绿 0 跳/vitest 171/build PASS/engine 39+244/release PASS）；远端 feature/agent-aux 已随真合并入库，分支可随手删 |
| sess-acceptance | 主库验收 + 验收后追修施工 | T-1001 主库验收（66cb8e7 回标 fe6c34f）→ T-1001 追修（✅ 0f49a25，搜索/排序根因修+标签筛选）→ T-1002（✅ e1a9309，wt 清理+定位按钮+勾选生成话题）→ T-1003（✅ 4eb9c85，文案改名飞书话题）→ T-1004（✅ 3eee8f2，监听状态/范围收进同步设置）→ T-1005（✅ 1846999，话题页签提前）→ T-1006（✅ 745e109，群聊详情消息流）→ T-1007（✅ d385300，材料分类tab+分页）→ T-1008（✅ 644046c，同步设置4tab+监听用户答疑+自动话题分类双阈值）→ T-1009（✅ b3c489a，定位原文右栏话题消失修复）→ T-1033 守卫收窄治理（✅ 55c4533，用户拍板当场修，specstd 全量 1984 绿竞态消失）→ T-1034 SSO 口令出库（✅ 同日当场修，三钉 TDD） | 2026-08-23 | 追修起因：总控人实测搜索/排序未生效；诊断走浏览器实证+真实数据复演（根因=同 id 双份 key 撞车，见经验包 2026-08-23 条目）；施工在 wt/material-pool 树（规程），主库只验收合并 |
| sess-test-taxonomy | M-C 测试类型学施工（wt/test-taxonomy 树） | T-981（✅ 8df59e1+ef1547c 待主库复验） | 2026-08-21 | 当日完工+当日返修：sg_core/test_dimensions 八维词表+证据提取+映射检查（DIM_VOCAB/DIM_MISSING/DIM_MAP）；format_spec 2.14.0 三同步（§1.2 doc 选填字段+§五 T10，baseline 重建比对零漂移）；validator 双路+spec_validator T10；compute_coverage 维度聚合+CoveragePanel 维度分布区块；generate-scenario 1.1.0 测试设计方法；24 入库场景补标注零告警；返修：存量回归测试口径磁盘 rglob→git ls-files（主库本地 gitignored 草稿约 80 个被误卷根因），合并形态 108 文件复演零误炸；离线全绿（39+1948）+release_check PASS+前端 build 成功 |
| sess-lark-scope-fix | M-D 飞书授权误报修复（wt/material-pool 树） | T-1012（✅ 08-24 主库验收合并 45a661e） | 2026-08-24 | 总控人实测上报授权误报；诊断在主库实跑 do_status+真实 token 调 contact 搜索钉案，施工在树内；文件读写一律树路径 |
| sess-draft-activity | M-F 草稿产物活动流水施工（wt/draft-activity 树） | T-1020（✅ 08-26 主库验收合并 cd6b788 + 回退 bc62c79）→ T-1027（✅ 08-27 主库验收，合并 7e3a24a/d4ead69） | 2026-08-26 | 起因：reset 事故复盘（会话 20260825_151821_3178914e）；总控人决策：版本全文存 DB/旧表并存过渡/无会话 reset 拒绝/overwrite 显式模式；本会话文件读写一律树路径，只跑离线测试，提交即推。主库验收结论：离线四门禁全绿（specstd 1911+4s/engine_modes 39/engine 236/release_check PASS/ruff 六文件基线对照零新增）+联网五点全过（reset 会话收窄钉案：RS-A1/A2 清除、MANUAL-KEEP 与 HI-PERM 六件完好、skipped 如实报告；reset_delete 留档含全文快照可恢复；overwrite 正道：版本链 create→reset_delete→create→overwrite 端点可查；分签 📝/✏️ 独立计数；前端回退无外会话/版本徽标）。T-1027 续工（20260827_094125_f955645e 会话三点反馈：面板可编辑/对话感知编辑并校验/结构化视图分 tab）；开工基线 9624be5（T-1026 回标后 ff 同步）。主库验收（08-27 单支先行）：合并态门禁全绿（specstd 注入版 2000 绿 0 跳/vitest 179/build/engine/release/ruff·oxlint 持平）+F1/F2/F3 实证过（零 draft write 判据达成、②闸 gate2_status=pass 一致、user_edit 入链、分签持久化）；现场还原纪律执行（草稿+.bak 复原） |
| sess-tool-consolidation | M-C 工具收敛 → M-F 收尾施工（wt/tool-consolidation 树） | T-982（✅ 08-21 主库验收合并 33931c6）→ T-998（✅ 待验收）→ T-999（✅ a/b/c/d 四分次，待验收）→ T-997（✅ 待验收） | 2026-08-21 | tool_meta 元数据单一事实源+consolidate 合并器（17 组 77→24）；side_effect/RBAC/doc 足迹全派生（_KNOWN_WRITERS 与 _RBAC_READONLY_TOOLS 手工清单废除）；purpose domains 领域子集两用途 15 工具；顺手修 specflow_refs 缺 handle 与 audit 未登记两存量缺口；eval 前后 3/3 持平 |
| sess-db-aux | DB证据面板与辅助会话施工（wt/db-aux 树，superpowers 计划体系） | SP-DB-AUX Task1-16（✅ 08-25 主库验收合并 8a1728d + 修复 2f7fd13/0303bff/9860e05，已推远端） | 2026-08-25 | 施工 16 Task 全交付（82a35f9~0fef8ab，19 commit）；主库验收：离线全绿（engine 39+230/specstd 1873/acceptance_fixes 红线48零修改/aux隔离14/vitest 119/tsc 0/build 43s/release_check PASS）+端到端 8 步全过；验收发现3缺陷当日修复：①sql_assistant缺draft域致write_draft不可用（设计遗漏补域）②purpose页签刷新/SPA跳回消失+激活竞态（既有缺陷暴露，_store缓存purposes+恢复路径补拉+pending改WS就绪消费）③守卫误判注释头SQL（剥前导注释）；④08-26 用户实测：sql_assistant混入新会话选择卡片（语义错位）→ spawn_only 标记（7d2cde4，选择卡过滤+直建403） |
| sess-engine-hardening | 引擎加固施工（wt/engine-hardening 树） | T-1016（✅ 08-26 主库验收合并 1a0346d）→ T-1017（✅ 同批验收）→ T-1018（✅ 同批验收）→ T-1019（✅ 同批验收）→ T-1022（✅ 08-27 主库验收合并 a9e898f） | 2026-08-26 | HI-PERM-001 三连败事故复盘派工；文件读写一律树路径，只跑离线测试，提交即推。T-1016~1019 主库验收（fast-forward 合并 1a0346d）：离线全绿（engine 236/engine_modes 39/specstd 1884+4s/release_check PASS/ruff 五文件 29=29 零新增）+联网实证四点全过。T-1022 主库验收（08-27，HI-PERM-004 排障复盘派工）：离线全绿（engine 238/engine_modes 39/specstd 1884+4s/release_check PASS/ruff 触碰文件零新增）；修复后联网实证 EX-6cf8ab64——接口 200→python 客户端筛选→SIT 无匹配成员→诚实 SKIP 落盘正常 |
| sess-agent-resume | 会话运行中重连续传施工（wt/agent-resume 树） | T-1021 | 2026-08-26 | 总控人拍板做完整版（不做轮询轻量版）；文件读写一律树路径，只跑离线测试，提交即推。完工：后端 services/session_event_bus.py 会话级总线（Subscriber 记录 loop + 跨 loop call_soon_threadsafe 投递 + per-sub 异常隔离 + 懒清理）+ agent.py attach/detach 分支（回放分批+实时续推+归属校验+终态兜底合成 attached(false)）+ getSession 增 run_in_progress/run_baseline_len；前端 AgentChat.tsx（restoreSession/重连补拉发现 run 进行中→截断基线+attach+loading；事件会话过滤防旧流污染；done 全量对齐；切/建会话发 detach）+ agent.ts 类型。施工中踩坑：TestClient 每 WS 连接独立 portal loop，总线跨 loop 裸 put_nowait 撞 future 取消竞态致终态事件静默丢失、组合测试挂死——已修并登记经验包 2026-08-26-T-1021。验证：test_agent_resume 15 绿（核心=断连后 attach 续上完整流/第二标签页 fan-out/异常广播）；全量 test_specstd 1926+4s 绿；engine_modes 39/engine 236/release_check PASS；前端 build 成功（tsc 0 错误）+ oxlint 触碰文件 errors 3=3 持平 warnings 91→86；ruff agent.py 40=40 基线持平。主库验收（08-27，合并提交 db2a8b5，无冲突）：离线五门禁全绿（test_agent_resume 15 绿 × 35+ 轮压测无 flake、test_specstd 1926+6s、engine_modes 39、test_engine 236、release_check PASS；ruff agent.py 40=40 持平、oxlint errors 3=3/warnings 91≤91；组合 test_agent_resume+test_acceptance_fixes 63/63 绿，分支声称的挂死坑已根治）。联网实证（90024166/人才发展，222s 长 run）：①刷新重进「↻ 恢复执行现场」+事件流实时续上至完成，红条不再出现 ②断连不打断 66s 后台完成落盘 ③切会话不串台 ④停止按钮解除 loading 均通过；双标签页因自动化工具开新标签受限，以同页第二条 WS attach 订阅收 107 事件等效验证（离线层另有 fan-out 双连接测试）。验收期发现并修复三处竞态（已随验收提交）：①主循环退出前在飞投递防护（sleep(0) 重查，防末事件丢失）②done/error 先 publish 再注销 _ACTIVE_RUNS（防兜底条件提前成立致 attach 订阅者退订错过终态）③attach 终态兜底条件增总线频道 done 标记（_run_in_progress 与 queue.empty 非原子）；测试侧同步改确定性等待 + 强制独立 portal（starlette 1.0 TestClient 复用 lifespan portal 与双连接拓扑不符）。双标签页 UI 目检留人工复验口子 |
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
| workbench/backend/routers/agent.py | sess-agent-aux | 2026-08-27 | 89d053ab16e6 | 7475abf36bfb | 已完成 | T-1031：_parent_snapshot 增强（草稿指路/聚焦场景/阅读足迹）+ 新增 _viewing_context_block + WS 收 focus_path |
| agent/purposes/sql_assistant.md | sess-agent-aux | 2026-08-27 | 0b5dfb970805 | 7037cfd0503c | 已完成 | T-1031：定位升级辅助助手（title/icon/chips/description/正文重写；id 不变兼容存量） |
| sg_core/session_context.py | sess-agent-aux | 2026-08-27 | 5407f3b3d51b | 7877508ab05b | 已完成 | T-1032：扩展运行时作用域 contextvar（runtime_scope：kind/purpose/parent_sid/sessions_dir），复用 T-1000 set_session_id 同位注入点 |
| agent/runtime.py | sess-agent-aux | 2026-08-27 | 09a7d5815b5b | d25952066814 | 已完成 | T-1032：run() 开头解析一次会话作用域，_execute_tool 同点注入 |
| mcp_server/server.py | sess-agent-aux | 2026-08-27 | b018e0b81e83 | 7bcfa0fb821a | 已完成 | T-1032：build_tool_modules 挂载 parent_tool |
| sg_core/session_digest.py | sess-agent-aux | 2026-08-27 | NEW | 6d3f72ca0b69 | 已完成 | T-1032：转录渲染/LLM 摘要 prompt/骨架兜底/覆盖度纯函数 |
| mcp_server/tools/parent_tool.py | sess-agent-aux | 2026-08-27 | NEW | 0c28fc19b09d | 已完成 | T-1032：parent 工具（summary/recent），独立域 aux，门卫限辅助会话 |
| test_specstd/test_parent_digest.py | sess-agent-aux | 2026-08-27 | NEW | 688824bb819c | 已完成 | T-1032：digest 单测+工具门卫+触发链路 |
| agent/purposes/test_workbench.md | sess-agent-aux | 2026-08-27 | 0a008649a0be | 2ac203c01c1c | 已完成 | T-1031：panels 注释口径 sql_aux=辅助助手页签 |
| test_specstd/test_aux_session.py | sess-agent-aux | 2026-08-27 | 46771bc079ab | b14bb6e2e742 | 已完成 | T-1031：快照增强/viewing 块回归测试 |
| test_specstd/test_mcp_server.py | sess-agent-aux | 2026-08-27 | f44cec5b5078 | 24640253e7c0 | 已完成 | T-1032：注册表钉子测试随 parent 工具更新（40→41、名单补 parent）【补记：改前未预登记，流程违规已在会话注记】|
| workbench/frontend/src/pages/agentChat/utils.ts | sess-agent-aux | 2026-08-27 | 3d9c93be1367 | 60159738bdd6 | 已完成 | T-1031：stripInjectedBlocks（references/parent_context/knowledge_refs 三块统一剥离） |
| workbench/frontend/src/pages/agentChat/utils.test.ts | sess-agent-aux | 2026-08-27 | 1c3d374f6c46 | e61a019164e1 | 已完成 | T-1031：剥离工具单测 |
| workbench/frontend/src/pages/agentChat/SidePanel.tsx | sess-agent-aux | 2026-08-27 | 5d875e05d206 | c5a04139f3c2 | 已完成 | T-1031：sql_aux 页签 label 改「🤝 辅助助手」 |
| workbench/frontend/src/pages/agentChat/SqlAuxPanel.tsx | sess-agent-aux | 2026-08-27 | 1c63da0612ac | 37963c54fd94 | 已完成 | T-1031：对话渲染同主会话链/上下文用量条/焦点指针随发送/产物区即时+计数 |
| workbench/frontend/src/pages/agentChat/SqlAuxPanel.test.tsx | sess-agent-aux | 2026-08-27 | d3e61c8de677 | df83db76f4d2 | 已完成 | T-1031：更新断言（改用共享 stripInjectedBlocks） |
| workbench/frontend/src/pages/agentChat/contexts.ts | sess-agent-aux | 2026-08-27 | 92d514addff0 | 2fc2370d9621 | 已完成 | T-1031：SqlAuxBridgeValue 增 getViewing 焦点提供者 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-agent-aux | 2026-08-27 | 2bd39193bf8f | 947c0eabf27b | 已完成 | T-1031：桥实现补 getViewing（活动文件页签→焦点） |
| workbench/frontend/src/pages/agentChat/DbPanel.tsx | sess-agent-aux | 2026-08-27 | 36a2440debdd | aecad9643956 | 已完成 | T-1031：「🤖 交给 SQL 助手」文案改「交给辅助助手」 |
| workbench/frontend/src/pages/DbConsole.tsx | sess-agent-aux | 2026-08-27 | 9e95d12b02eb | 243b93bd411a | 已完成 | T-1031：同上口径 |
| workbench/frontend/src/pages/agentChat/DbPanel.test.tsx | sess-agent-aux | 2026-08-27 | a4f94f8353b4 | 0791b1997dfb | 已完成 | T-1031：选择器正则随 title 改名同步 |
| mcp_server/tools/lark_auth.py | sess-lark-scope-fix | 2026-08-24 | 8bdb475d568b | c2b08099fb3c | 已完成 | T-1012：_REQUIRED_SCOPES 首项改官方名 contact:user:search |
| sg_core/product_activity.py | sess-draft-activity | 2026-08-26 | NEW | fb8903b83d16 | 已完成 | T-1020 F1：活动流水表（contextvar 取值/版本链/全文快照） |
| sg_core/draft_gates.py | sess-draft-activity | 2026-08-26 | da892bf304a9 | c91557695e1d | 已完成 | T-1020：delete_draft_gate 单文件三闸删除 |
| sg_core/ledger_store.py | sess-draft-activity | 2026-08-26 | 92ce01936a07 | d6bdad24eb03 | 已完成 | T-1020：delete_draft 单文件台账删除 |
| mcp_server/tools/draft_writer.py | sess-draft-activity | 2026-08-26 | 4e9f79cce1aa | 727be90bd32f | 已完成 | T-1020 F2：overwrite 模式+六 handler 挂流水+reset 会话收窄 |
| mcp_server/tools/gate_dock.py | sess-draft-activity | 2026-08-26 | 814609df5994 | 640788516b7d | 已完成 | T-1020 F3：迁 current_session_id contextvar |
| agent/runtime.py | sess-draft-activity | 2026-08-26 | 74499571ba44 | 09a7d5815b5b | 已完成 | T-1020 F3：退役 _session_id 特权参数注入 |
| workbench/backend/routers/agent.py | sess-draft-activity | 2026-08-26 | 2064df3b602f | c12e8930e97d | 已完成 | T-1020 F4：writing_feed 双源（重放+DB 增强/兜底） |
| workbench/backend/routers/drafts.py | sess-draft-activity | 2026-08-26 | b46d5f7b85e3 | d52a9e461014 | 已完成 | T-1020 F5：GET /activity + /{filename}/versions 端点 |
| test_specstd/test_product_activity.py | sess-draft-activity | 2026-08-26 | NEW | a34844ba3cf3 | 已完成 | T-1020 F1 测试（11） |
| test_specstd/test_draft_activity.py | sess-draft-activity | 2026-08-26 | NEW | ea9404c77f5c | 已完成 | T-1020 F2 测试（8：overwrite/undo/reset 收窄钉案） |
| test_specstd/test_mcp_server.py | sess-draft-activity | 2026-08-26 | 3ac0deb9cac1 | 1c4235d2b5f3 | 已完成 | T-1020：reset 测试适配会话收窄 |
| workbench/frontend/src/api/drafts.ts | sess-draft-activity | 2026-08-26 | 4b1eaa9f1a3b | 2fd220f192e5 | 已完成 | T-1020 F5：activity/versions API |
| workbench/frontend/src/pages/agentChat/DraftArtifactsPanel.tsx | sess-draft-activity | 2026-08-26 | 06b0a8848c5a | 1ba36e64d720 | 已完成 | T-1020 F5：全量草稿+本会话/外会话/版本徽标 |
| workbench/frontend/src/pages/agentChat/SidePanel.tsx | sess-draft-activity | 2026-08-26 | 183062b3be4f | b8123721144b | 已完成 | T-1020：分签（认领提交）+sessionId 透传 |
| workbench/frontend/src/pages/agentChat/WritingPanel.tsx | sess-draft-activity | 2026-08-26 | fc4e99e6dbef | d2d1e9bca04e | 已完成 | T-1020：卡片版本徽标 v{N}/{M} |
| workbench/frontend/src/pages/agentChat/types.ts | sess-draft-activity | 2026-08-26 | 782f10a3f94a | 9ee70953bca2 | 已完成 | T-1020：DocWriteItem 版本字段 |
| workbench/frontend/src/api/drafts.ts | sess-acceptance | 2026-08-26 | 2fd220f192e5 | 4b1eaa9f1a3b | 已完成 | T-1020 验收回退（bc62c79）：撤 activity/versions API 与类型（决策 7） |
| workbench/frontend/src/pages/agentChat/DraftArtifactsPanel.tsx | sess-acceptance | 2026-08-26 | 1ba36e64d720 | 06b0a8848c5a | 已完成 | T-1020 验收回退（bc62c79）：面板回本会话草稿口径（撤全量渲染/外会话/版本徽标） |
| workbench/frontend/src/pages/agentChat/SidePanel.tsx | sess-acceptance | 2026-08-26 | b8123721144b | 183062b3be4f | 已完成 | T-1020 验收回退（bc62c79）：补撤 DraftArtifactsPanel sessionId 透传（分签保留） |
| workbench/frontend/src/pages/agentChat/WritingPanel.tsx | sess-acceptance | 2026-08-26 | d2d1e9bca04e | fc4e99e6dbef | 已完成 | T-1020 验收回退（bc62c79）：撤卡片版本徽标 |
| workbench/frontend/src/pages/agentChat/types.ts | sess-acceptance | 2026-08-26 | 9ee70953bca2 | 782f10a3f94a | 已完成 | T-1020 验收回退（bc62c79）：撤 DocWriteItem 版本字段 |
| scenarios/权限测试/HI-PERM-001.yaml | sess-acceptance | 2026-08-26 | 3e83bbd92080 | a5f9bb2c422e | 已完成 | 验收顺手修（cae6e17）：补标 doc.dimensions=[regression]，灭 992f464 入库漏标存量红灯 |
| test_specstd/test_lark_auth.py | sess-lark-scope-fix | 2026-08-24 | 2477266780d3 | aceadf1ae025 | 已完成 | T-1012：断言同步改名+canonical 命名回归测试 |
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
| workbench/frontend/src/components/system-config/EnvConfigPanel.tsx | sess-system-config | 2026-08-24 | 53c98ab3501c | 8816e62f2f55 | 已完成 | T-1013：原文/预览/数据库显示模式切换（DB 卡并入本系统配置视图，通用层无 db 模式） |
| workbench/frontend/src/components/system-config/WorkspacesPanel.tsx | sess-system-config | 2026-08-24 | 0455753c7a14 | addafcd25513 | 已完成 | T-1013：注册工作区内联表单改弹层（z-40，成功自动关） |
| workbench/frontend/src/components/system-config/SystemsPanel.tsx | sess-system-config | 2026-08-24 | 6e1b70a99af9 | efeaf4188c31 | 已完成 | T-1013：注册弹层改名注册系统/删 env_yaml 块/接入分级随选解释 |
| | | | | | | |
| workbench/backend/services/rbac_store.py | sess-agent-split | 2026-08-28 | 853758daf841 | ed0139e2708d | 已完成 | T-1039：SEED_MENUS 加 menu-agent-product（公开）+ menu-agent 更名测试对话 + menus_for_user end 前缀防撞车规则 |
| test_specstd/test_menu_migration.py | sess-agent-split | 2026-08-28 | 199a33bacc03 | 25cfa93c4f9f | 已完成 | T-1039：TestAgentSplitMenus 三例（种子落库/存量 label 对齐/公开可见+end 规则） |
| workbench/frontend/src/App.tsx | sess-agent-split | 2026-08-28 | 798f94b6e227 | 3c3ca6c3c9fe | 已完成 | T-1039：双路由 /agent·/agent-product（fixedPurpose 注入）+ 材料/评分/禅道重定向归产品侧 + noPadding 前缀 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-agent-split | 2026-08-28 | cf80d95f0b82 | 7b4f8d5daca3 | 已完成 | T-1039：fixedPurpose 贯穿（锁用途/无权态/路由守卫/分侧挂载/自愈补拉/WS 过滤收紧/存储键隔离+旧键迁移） |
| workbench/frontend/src/pages/MyActivity.tsx | sess-agent-split | 2026-08-28 | d8d2b7a71064 | 13804bc12bfe | 已完成 | T-1039：openSession 按 purpose 分流双菜单 |
| workbench/frontend/src/utils/home.ts | sess-agent-split | 2026-08-28 | 2aae17921f28 | 2b53771ba650 | 已完成 | T-1039：PUBLIC_MENU_PATHS 加 /agent-product |
| workbench/frontend/src/pages/agentChat/utils.ts | sess-agent-split | 2026-08-28 | bbb0930751e8 | 6ece3eb61610 | 已完成 | T-1039：chatRouteForPurpose/chatStorageKeys/filterMenuSessions 三纯函数 |
| workbench/frontend/src/pages/agentChat/sessionStore.ts | sess-agent-split | 2026-08-28 | b09127134cd8 | a77bfa885a70 | 已完成 | T-1039：_store 分侧（side/sides 快照 + ensureSideStore 交换） |
| workbench/frontend/src/pages/agentChat/utils.test.ts | sess-agent-split | 2026-08-28 | 818dcc9f24b2 | 2b503443c838 | 已完成 | T-1039：三纯函数测试 5 例 |
| workbench/frontend/src/pages/agentChat/sessionStore.test.ts | sess-agent-split | 2026-08-28 | NEW | 24f95ba0e253 | 已完成 | T-1039：ensureSideStore 交换/stash/切回/不分侧字段 4 例 |

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
| mcp_server/tools/scenario_tools.py | sess-engine-hardening | 2026-08-26 | 46093889d642 | c3a787cb06e9 | 已完成 | T-1016：run_dir 改 reports_dir() 强制共享区 |
| test_specstd/test_trial_run_persistence.py | sess-engine-hardening | 2026-08-26 | e0d6e2e055cb | 25bbad97cac8 | 已完成 | T-1016：emp 上下文试跑→attribution 可读回归测试 |
| sg_core/format_spec.py | sess-engine-hardening | 2026-08-26 | d9db54a5feb3 | f0a280372320 | 已完成 | T-1017：§1.13 补全 + 2.15.0 版本 bump |
| docs/specguard-yaml-format-spec.md | sess-engine-hardening | 2026-08-26 | eca84d4c5e11 | ccbd8e23c3fb | 已完成 | T-1017 三同步：快照重导出 |
| engine/scenario_runner.py | sess-engine-hardening | 2026-08-26 | 71b1914bc44f | 0740c35d5dd6 | 已完成 | T-1018：脚本异常消息附 ns 可用键清单 |
| test_engine/test_call_and_python.py | sess-engine-hardening | 2026-08-26 | 550a3b2f41dd | 71c51d2b006e | 已完成 | T-1018/T-1019：回归测试 |
| engine/http_client.py | sess-engine-hardening | 2026-08-26 | 829edf9f6c17 | 679043897758 | 已完成 | T-1019：request/post 兼容 json= 别名 |
| docs/远期设计/SpecGuard-总控文档.md | sess-engine-hardening | 2026-08-26 | 04df3b9ada25 | 30823d9f0e57 | 已完成 | §4 T-1016~1019 登记/回填 + §5 会话注册 + §6 文件登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| sg_core/spec_baseline.py | sess-engine-hardening | 2026-08-26 | c54b86f9cadf | 2ff283aafcb1 | 已完成 | T-1016 波及面：_baseline_path 补 force_shared（签名基线=工作区级共享资产，emp 上下文下误落私有区致变更检测静默失明） |
| test_specstd/test_spec_baseline.py | sess-engine-hardening | 2026-08-26 | 14fab8e7cbd3 | 19d29e68a125 | 已完成 | T-1016 波及面：emp 上下文基线路径回归测试 |
| test_engine/test_http_retry.py | sess-engine-hardening | 2026-08-26 | 0e0f8286448e | e8e8f109e9ce | 已完成 | T-1019：json= 别名回归测试（复用 FakeSession 基建） |
| docs/经验包/2026-08-26-agent_20260826_112426-python原语三连败-试跑报告读写错位.md | sess-engine-hardening | 2026-08-26 | NEW | 4259300068e6 | 已完成 | T-1016~T-1019 排障闭环经验包 |
| docs/经验包/README.md | sess-engine-hardening | 2026-08-26 | 59cfcbba2f98 | 994a8f4a87ce | 已完成 | 经验包索引追加 |
| docs/远期设计/SpecGuard-总控文档.md | sess-acceptance | 2026-08-26 | 42a6b8a3ad2d | dc77b5b7306e | 已完成 | T-1016~T-1019 主库验收收口：§4 四行状态改验收（合并 1a0346d）+§5 补验收结论+本行登记 |
| workbench/backend/services/session_event_bus.py | sess-agent-resume | 2026-08-26 | NEW | 7d08b8424447 | 已完成 | T-1021：会话级事件总线（fan-out+回放缓冲+生命周期） |
| workbench/backend/routers/agent.py | sess-agent-resume | 2026-08-26 | ae0c8718b0f0 | 9fc0bf40e684 | 已完成 | T-1021：run 事件发布到总线+attach/detach 分支+getSession 增字段 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-agent-resume | 2026-08-26 | 78c8f7fb7710 | cadf720efa2d | 已完成 | T-1021：restoreSession/重连补拉 attach 续传+基线截断+事件会话过滤 |
| workbench/frontend/src/api/agent.ts | sess-agent-resume | 2026-08-26 | 81eacfddabe4 | 775997b90934 | 已完成 | T-1021：getSession 类型加 run_in_progress/run_baseline_len |
| test_specstd/test_agent_resume.py | sess-agent-resume | 2026-08-26 | NEW | a70aa7cd605b | 已完成 | T-1021：总线单测+WS attach 端到端（TestClient 双连接） |
| docs/远期设计/SpecGuard-总控文档.md | sess-agent-resume | 2026-08-26 | 29770fbc165e | f10bfba081fe | 已完成 | T-1021：§4/§5/§6 开工登记 |
| docs/远期设计/SpecGuard-总控文档.md | 主库验收（T-1021） | 2026-08-27 | 730778e18c0f | 683128e1ef72 | 已完成 | T-1021 主库验收回写：§4 状态改已验收 + §5 补验收结论（离线五门禁+联网实证+验收期三处竞态修复） |
| workbench/frontend/src/pages/agentChat/DraftArtifactsPanel.tsx | sess-draft-activity | 2026-08-27 | 7730af71fee9 | 139e6f5843b6 | 已完成 | 草稿去向判定竞态修复：conflict 预检等列表就绪后才开始 + libHit 渲染加 !meta 守卫——「库内同 ID 旧版+草稿新版」不再误判为已入库（卡片只剩 DAG 编排按钮的根因，20260827_094125_f955645e 会话复盘） |
| workbench/frontend/src/pages/agentChat/DraftArtifactsPanel.test.tsx | sess-draft-activity | 2026-08-27 | NEW | d4355251217d | 已完成 | 去向判定三态守卫 3 例（挂载竞态不复现已入库误判/昨日入库真命中→DAG 卡/库内未命中→已删除卡） |
| docs/远期设计/SpecGuard-总控文档.md | sess-draft-activity | 2026-08-27 | 4d7738e1c031 | 76b4bc2963d6 | 已完成 | §6 登记：草稿面板去向判定修复两文件 |
| sg_core/spec_sections.py | sess-scenario-reader | 2026-08-27 | NEW | 04ab25c4f114 | 已完成 | T-1023：sections 纯函数下沉（mcp_server 与 workbench 共同消费） |
| mcp_server/tools/sections.py | sess-scenario-reader | 2026-08-27 | 9e316168e0cf | a38692b60b62 | 已完成 | T-1023：改 sys.modules 转发 shim（存量 15 测试零改动绿） |
| workbench/backend/services/anchor_refs.py | sess-scenario-reader | 2026-08-27 | NEW | 5810f4c58122 | 已完成 | T-1023：FR/AC → spec 原文解析（同号全候选 + hint 排序 + AC 反查） |
| workbench/backend/routers/workspace.py | sess-scenario-reader | 2026-08-27 | 104751e34ddf | 0922c972b660 | 已完成 | T-1023：+GET /api/workspace/anchor-refs |
| test_specstd/test_anchor_refs.py | sess-scenario-reader | 2026-08-27 | NEW | 589c9f94635c | 已完成 | T-1023：anchor_refs 7 例（标题式/列表式/AC/未命中/同号排序/空目录/上限） |
| workbench/frontend/src/utils/scenarioReader.ts | sess-scenario-reader | 2026-08-27 | NEW | 52110e342509 | 已完成 | T-1023：阅读视图纯函数层（步骤归一/注释提取/描述/hint） |
| workbench/frontend/src/utils/scenarioReader.test.ts | sess-scenario-reader | 2026-08-27 | NEW | 803e3d95a04b | 已完成 | T-1023：纯函数 vitest 11 例（钉脚本内注释不串行守卫） |
| workbench/frontend/src/components/ScenarioReader.tsx | sess-scenario-reader | 2026-08-27 | NEW | a1aa4263dff8 | 已完成 | T-1023：结构化阅读视图主组件 + 锚点芯片/原文展开面板 |
| workbench/frontend/src/components/FileViewer.tsx | sess-scenario-reader | 2026-08-27 | 9c2d3931fd77 | 38f0a0c2b4c6 | 已完成 | T-1023：场景 YAML 双视图切换（localStorage 记忆；顺手清 react-in-jsx-scope 存量告警） |
| workbench/frontend/src/components/ScenarioFormEditor.tsx | sess-scenario-reader | 2026-08-27 | bc8e5f2186b6 | ba5f04556d55 | 已完成 | T-1023：阅读/表单/YAML 三模式 + 验收期修复（表单脏标记，未编辑进阅读保留原注释） |
| workbench/frontend/src/api/workspace.ts | sess-scenario-reader | 2026-08-27 | db10b138f99c | e0e7f4faa424 | 已完成 | T-1023：+anchorRefs API 与类型 |
| docs/远期设计/SpecGuard-总控文档.md | sess-scenario-reader | 2026-08-27 | 509d661fc339 | 1d93b82b863c | 已完成 | T-1023：§4 任务登记 + §5 会话注册 + §6 文件登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| workbench/backend/services/anchor_refs.py | sess-scenario-reader | 2026-08-27 | 5810f4c58122 | e22b6ffa99be | 已完成 | T-1024：matches 增 rel 工作区相对路径（打开文档页签用） |
| test_specstd/test_anchor_refs.py | sess-scenario-reader | 2026-08-27 | 589c9f94635c | 7cb74a3221b8 | 已完成 | T-1024：rel 字段断言 |
| workbench/frontend/src/components/LocatedTextView.tsx | sess-scenario-reader | 2026-08-27 | NEW | 6167ee481997 | 已完成 | T-1024：LocatedTextView 拆独立文件（防 FileViewer↔ScenarioReader 循环依赖） |
| workbench/frontend/src/components/ScenarioReader.tsx | sess-scenario-reader | 2026-08-27 | a1aa4263dff8 | 278207d7ae99 | 已完成 | T-1024：锚点面板「📄 完整文档」弹层 + 页签打开入口 |
| workbench/frontend/src/components/FileViewer.tsx | sess-scenario-reader | 2026-08-27 | 38f0a0c2b4c6 | 3e89b451a9d5 | 已完成 | T-1024：onOpenFile 透传 + LocatedTextView 改再导出 |
| workbench/frontend/src/pages/agentChat/SidePanel.tsx | sess-scenario-reader | 2026-08-27 | 183062b3be4f | 3ac4c224ac21 | 已完成 | T-1024：FileViewer 接 onOpenFile；Boy Scout 修存量 exhaustive-deps error（purposePanelSet useMemo 化） |
| workbench/frontend/src/api/workspace.ts | sess-scenario-reader | 2026-08-27 | e0e7f4faa424 | c684522dc737 | 已完成 | T-1024：AnchorMatch 增 rel 字段 |
| docs/远期设计/SpecGuard-总控文档.md | sess-scenario-reader | 2026-08-27 | 0f74029e2e87 | 95d891323540 | 已完成 | T-1024：§4 任务登记 + §5 认领 + §6 文件登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| workbench/backend/services/anchor_refs.py | sess-scenario-reader | 2026-08-27 | e22b6ffa99be | 76a3ec865404 | 已完成 | T-1025：matches 增 score 相关性分数 |
| test_specstd/test_anchor_refs.py | sess-scenario-reader | 2026-08-27 | 7cb74a3221b8 | e3340c1f7a25 | 已完成 | T-1025：score 断言 |
| workbench/frontend/src/components/ScenarioReader.tsx | sess-scenario-reader | 2026-08-27 | 278207d7ae99 | 56de62a74a2f | 已完成 | T-1025：候选相关/零相关分组折叠 + 弹层 markdown 渲染定位高亮 |
| workbench/frontend/src/api/workspace.ts | sess-scenario-reader | 2026-08-27 | c684522dc737 | 93084aa99822 | 已完成 | T-1025：AnchorMatch 增 score |
| docs/远期设计/SpecGuard-总控文档.md | sess-scenario-reader | 2026-08-27 | 8f877d23d435 | 6e5c77271204 | 已完成 | T-1025：§4/§5/§6 登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| docs/远期设计/SpecGuard-总控文档.md | 主库验收（T-1023） | 2026-08-27 | 1d93b82b863c | — | 已完成 | T-1023 主库验收回写：§4 状态改已验收 + §5 补验收结论 + ScenarioFormEditor 行 hash 追更（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| workbench/frontend/src/pages/agentChat/SidePanel.tsx | sess-sidepanel-hub | 2026-08-27 | 3ac4c224ac21 | 5d875e05d206 | 已完成 | T-1026：SIDE_TABS 增 lowFreq 分层 + 页签条聚合装配（活动低频签暂显） |
| workbench/frontend/src/pages/agentChat/MorePanelsMenu.tsx | sess-sidepanel-hub | 2026-08-27 | NEW | 92ca6f823a15 | 已完成 | T-1026：「更多」面板选择器（卡片网格弹层，对标 VS Code 打开标签页空态） |
| workbench/frontend/src/pages/agentChat/SidePanel.test.tsx | sess-sidepanel-hub | 2026-08-27 | NEW | 29f7299d2c45 | 已完成 | T-1026：聚合装配/菜单选择回跳/活动低频签暂显/Escape·外点关闭 6 测试 |
| docs/远期设计/SpecGuard-总控文档.md | sess-sidepanel-hub | 2026-08-27 | be00e44b2cb8 | 553abb7ab6f3 | 已完成 | T-1026：§4 任务登记 + §5 认领 + §6 文件登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| docs/远期设计/SpecGuard-总控文档.md | 主库验收（T-1026） | 2026-08-27 | 553abb7ab6f3 | — | 已完成 | T-1026 主库验收回写：§4 状态改已验收 + §5 补验收结论（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| docs/远期设计/SpecGuard-话题携带文档材料设计-T1027.md | sess-topic-docmat | 2026-08-27 | NEW | 2b4f532603bf | 已完成 | T-1027：立项设计稿新建（现状实测/关键决策 D1-D5/分块 F1-F3/任务拆解 T-1028~T-1030/测试策略/非目标/待拍板 §8） |
| docs/远期设计/SpecGuard-总控文档.md | sess-topic-docmat | 2026-08-27 | cff081531166 | 01edb999fd06 | 已完成 | T-1027：§4 任务拆解四行登记 + §5 会话注册 + §6 文件登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| docs/灵感/2026-08-27-话题共享材料图谱建边-事实字段入图构想.md | sess-topic-docmat | 2026-08-27 | NEW | 544de3305ccb | 已完成 | T-1027 拍板③：图谱建边延后立项构想入库（设计要点+三条重启条件） |
| docs/灵感/README.md | sess-topic-docmat | 2026-08-27 | 65f06b09eb68 | 527e66658251 | 已完成 | T-1027 拍板③：索引表追加一行 |
| docs/远期设计/SpecGuard-话题携带文档材料设计-T1027.md | sess-topic-docmat | 2026-08-27 | 2b4f532603bf | 28d2ff46306b | 已完成 | T-1027 拍板①②③回写：§8 改决策拍板记录 + §3 D4 标记已采纳 |
| docs/远期设计/SpecGuard-总控文档.md | sess-topic-docmat | 2026-08-27 | 220ee8313217 | 9ecb8c642ecc | 已完成 | T-1027 拍板回写 + 四文件登记（§6 行自身 hash 固有滞后一次编辑） |
| specflow/feishu_pool/chat_store.py | sess-topic-docmat | 2026-08-27 | b84a24651b20 | 363752efa399 | 已完成 | T-1028：extract_feishu_links（实测形状/域族白名单/尾部标点不吞）+ render_row_body 共享渲染（system/video_chat 钉案 + 未知类型保真降级） |
| specflow/feishu_pool/topic_cluster.py | sess-topic-docmat | 2026-08-27 | 8fc845dd1995 | 101b1796e673 | 已完成 | T-1028：_load_window_source/compose_topic_from_messages 改走共享渲染 |
| test_specstd/test_feishu_chat_store.py | sess-topic-docmat | 2026-08-27 | 0df9f6491082 | bec8b8287d13 | 已完成 | T-1028：+6 用例（新钉案类型归一化/链接三形状与边界/md 视图逐行等价/未知类型降级/窗口同源）23 绿 |
| test_specstd/feishu_cli_contract.py | sess-topic-docmat | 2026-08-27 | fee61146fa79 | 3e89ae03e19f | 已完成 | T-1028：契约扩充 system/video_chat/text 链接三形状（真实池扫描钉案，卡片类零实体如实留痕） |
| docs/远期设计/SpecGuard-总控文档.md | sess-topic-docmat | 2026-08-27 | a833bab918ad | — | 已完成 | T-1028：§4 状态收口 + §5/§6 回填（§6 行自身 hash 固有滞后一次编辑） |
| specflow/feishu_pool/shared_materials.py | sess-topic-docmat | 2026-08-27 | NEW | debfa677ca89 | 已完成 | T-1029：事实推导（行索引/derive_from_rows）+ 快照联接 resolve（纯读派生，sheets 无通道如实灰显） |
| specflow/feishu_pool/topic_cluster.py | sess-topic-docmat | 2026-08-27 | 101b1796e673 | c3619f4ab872 | 已完成 | T-1029：四路 attach + edit/regen 重算守卫 + 变更留痕 history；顺手修 E741/I001 存量 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-topic-docmat | 2026-08-27 | 62cb06025337 | e34482b8768e | 已完成 | T-1029：list_pool_topics 注入联接 + fetch_topic_materials 看门狗补拉（fetched/skipped/errors 三段）；Boy Scout 修 SIM103 存量 |
| workbench/backend/routers/feishu_pool.py | sess-topic-docmat | 2026-08-27 | 523ff5ea39e1 | 2ba7da335478 | 已完成 | T-1029：POST /topics/material-fetch 端点 |
| test_specstd/test_topic_shared_materials.py | sess-topic-docmat | 2026-08-27 | NEW | 1e899204994a | 已完成 | T-1029：纯函数层+五路集成+resolve 联接+补拉降级 9 例 |
| docs/远期设计/SpecGuard-总控文档.md | sess-topic-docmat | 2026-08-27 | d330f8eca6f3 | e6ab50ed966d | 已完成 | T-1029：§4 验收打包口径+认领收口、§5 登记、§6 六文件登记（自身 hash 固有滞后一次编辑） |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-topic-docmat | 2026-08-27 | e34482b8768e | 31ed45c0ca4a | 已完成 | 自验收追加：sync_doc 契约键修正（实测 data.document.content 嵌套层，扁平键兜底——存量真 bug，docs 内容路径生产从未跑通故未暴露）+ `<title>` 提取落 meta.title |
| test_specstd/feishu_cli_contract.py | sess-topic-docmat | 2026-08-27 | 3e89ae03e19f | 26c9ebffdff8 | 已完成 | 自验收钉案：DOCS_FETCH_NESTED 真实嵌套形状（结构原样正文脱敏）+ docs_fetch_nested() |
| test_specstd/test_feishu_sync.py | sess-topic-docmat | 2026-08-27 | （同会话连续施工，以终态登记） | 1a75fcdb8617 | 已完成 | +test_sync_doc_real_nested_document_shape（嵌套形状→非空落盘+title 断言）；旧扁平夹具经兼容仍绿 |
| docs/远期设计/SpecGuard-总控文档.md | sess-topic-docmat | 2026-08-27 | e6ab50ed966d | 29e3ea30388f | 已完成 | 自验收回写：§4 三行改「✅ 树内自验收」+T-1029 行补四点实证证据+本批 §6 登记 |
| agent/runtime.py | sess-acceptance | 2026-08-27 | 0e078778640f | — | 已完成 | T-1033：_take_snapshot_fingerprint 收窄为工作区产物（含无上下文恒等指纹兜底） |
| test_specstd/test_skill_governance.py | sess-acceptance | 2026-08-27 | a4c338720a07 | — | 已完成 | T-1033：旧源码钉改写为覆盖面收窄钉（剥 docstring）+ 新增行为双钉，33 绿 |
| docs/经验包/2026-08-27-T1033-守卫指纹竞态-纯读误伤与覆盖面收窄.md | sess-acceptance | 2026-08-27 | NEW | 90aed408ef15 | 已完成 | 排障闭环五段登记（竞态归因四步实验链+治理+预防清单） |
| docs/经验包/README.md | sess-acceptance | 2026-08-27 | — | 9a6f5a5236fc | 已完成 | 索引表追加 T-1033 行 |
| docs/远期设计/SpecGuard-总控文档.md | sess-acceptance | 2026-08-27 | — | — | 已完成 | T-1033 §4/§5/§6 登记+T-1029 行治理闭环注记（自登记固有滞后一次编辑） |
| docs/经验包/2026-08-27-T1031-T1032-辅助助手三缺陷-离线全绿工作台实证拦获.md | sess-acceptance | 2026-08-27 | NEW | a8fd12649a8d | 已完成 | ②包验收三缺陷（A/B/C）排障闭环五段登记：现象/证据链/根因/f3b406a 修复/可执行预防清单 |
| docs/经验包/README.md | sess-acceptance | 2026-08-27 | — | c24d09dc741a | 已完成 | 索引表追加 T-1031/T-1032 三缺陷行 |
| workbench/backend/routers/drafts.py | sess-draft-activity | 2026-08-27 | d52a9e461014 | ac05e8229853 | 已完成 | T-1027 F2：PUT 保存挂自动校验+②闸刷新+user_edit 活动流水+对话感知注入 |
| workbench/backend/routers/agent.py | sess-draft-activity | 2026-08-27 | 89d053ab16e6 | 328196c1d011 | 已完成 | T-1027 F2：WS 开跑前排空面板编辑 pending 注入消息前缀 |
| workbench/backend/services/panel_edit_feedback.py | sess-draft-activity | 2026-08-27 | NEW | 9754827c8e1d | 已完成 | T-1027 F2：编辑感知纯函数（note 构造/pending 写读排空/注入判定） |
| workbench/frontend/src/components/FileViewer.tsx | sess-draft-activity | 2026-08-27 | 3e89b451a9d5 | 4e4b9afa5ebb | 已完成 | T-1027 F1：场景 YAML 双视图增「✏️ 编辑」模式（draft 可保存回调） |
| workbench/frontend/src/components/ScenarioReader.tsx | sess-draft-activity | 2026-08-27 | 56de62a74a2f | becca5987488 | 已完成 | T-1027 F3：结构化阅读视图分区块 tab（持久化+失效回退） |
| workbench/frontend/src/pages/agentChat/SidePanel.tsx | sess-draft-activity | 2026-08-27 | 5d875e05d206 | dc0b4c971516 | 已完成 | T-1027 F1：file 页签 draft 编辑回调透传 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-draft-activity | 2026-08-27 | 2bd39193bf8f | c731900df9df | 已完成 | T-1027 F1/F2：onSaveDraft 接线（PUT+session_id+保存后刷新） |
| workbench/frontend/src/api/drafts.ts | sess-draft-activity | 2026-08-27 | 4b1eaa9f1a3b | 587b01b8e39b | 已完成 | T-1027：update 增 sessionId 与扩展响应类型（validate/percept） |
| workbench/backend/routers/drafts.py | sess-draft-activity | 2026-08-27 | ac05e8229853 | 38b1a97f4f48 | 已完成 | T-1027 返修：PUT 感知分支传 read_path（工作区相对路径，解析不出诚实省略）与 version_no |
| workbench/backend/services/panel_edit_feedback.py | sess-draft-activity | 2026-08-27 | 9754827c8e1d | adbd3e2cae17 | 已完成 | T-1027 返修（验收打回 58bb6b8）：build_edit_note 重写——变更行摘录内嵌+反覆盖护栏 GUARD_TEXT+read 指引改真实 spec(action=read)+截断只裁摘录保护栏 |
| test_specstd/test_draft_panel_edit.py | sess-draft-activity | 2026-08-27 | 0632fa0b88bc | 2d055622d5f5 | 已完成 | T-1027 返修：+6 测试（摘录嵌入/护栏钉死/read 真实且无路径诚实省略/禁 phantom draft read/工具注册表对照/溢出保护栏）+ read path 可执行端到端钉案 |
| workbench/frontend/src/components/DraftFormEditor.tsx | sess-draft-activity | 2026-08-27 | NEW | 324dbe1b03a7 | 已完成 | T-1027 用户反馈：草稿编辑结构化——复用 ScenarioFormEditor 三模式包装（参考 registries 懒加载降级+保存桥 EditSaveOutcome）|
| workbench/frontend/src/components/FileViewer.edit.test.tsx | sess-draft-activity | 2026-08-27 | 09cd4236b5ac | 7e844fb6c5e6 | 已完成 | T-1027 重写为结构化编辑器口径（SFE 桩件驱动保存成败两路，4 例）|
| workbench/frontend/src/components/FileViewer.tsx | sess-draft-activity | 2026-08-27 | 4e4b9afa5ebb | 29b20eade12b | 已完成 | T-1027 编辑分支改挂 DraftFormEditor；退役面板内 Monaco 直编（类型 EditSaveOutcome 移 DraftFormEditor 转发导出）|
| workbench/frontend/src/components/ScenarioReader.tabs.test.tsx | sess-draft-activity | 2026-08-27 | NEW | dface5e805cb | 已完成 | T-1027 F3 测试（tab 装配/空区块隐藏/持久化恢复/失效回退） |
| workbench/frontend/src/components/FileViewer.edit.test.tsx | sess-draft-activity | 2026-08-27 | NEW | 09cd4236b5ac | 已完成 | T-1027 F1 测试（编辑入口仅 draft、保存回调、结果反馈） |
| docs/远期设计/SpecGuard-总控文档.md | sess-draft-activity | 2026-08-27 | 553abb7ab6f3 | 9924ef7d0639 | 已完成 | T-1027：§4 任务登记 + §5 认领 + §6 文件登记（自登记 hash 为回填前一刻，固有滞后一次编辑） |
| systems/_shared/config/env.sit.yaml | sess-acceptance | 2026-08-28 | dc58d11e86bf | — | 已完成 | T-1034：sso.password default 位清空（明文口令出库） |
| systems/tdm/config.py | sess-acceptance | 2026-08-28 | b513f19d4c84 | — | 已完成 | T-1034：sso.password 补 resolve_secret 同款回退 |
| test_engine/test_local_secrets.py | sess-acceptance | 2026-08-28 | 2fb9fea4b9c2 | — | 已完成 | T-1034：+3 钉（链路取值/全空诚实为空/源码红线防回潮）9 绿 |
| AGENTS.md | sess-acceptance | 2026-08-28 | — | 38f13514ad8e | 已完成 | T-1034：08-27 条遗留待办标记闭环 |
| docs/经验包/2026-08-23-M系列代码升级-全库扫描检查单.md | sess-acceptance | 2026-08-28 | — | 50d413875d6c | 已完成 | 凭据红线 F3 实测基线标记闭环 |
| docs/远期设计/SpecGuard-总控文档.md | sess-acceptance | 2026-08-28 | — | — | 已完成 | T-1034 §4/§5/§6 登记（自登记固有滞后一次编辑） |
