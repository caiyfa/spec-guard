# SpecGuard Vision · 开发总控文档

> **本文档是所有开发会话的唯一协调中心。任何开发会话开工前必须完整阅读 §1-§4，并按 §3 协议注册会话、认领任务、登记文件变更。**
> 版本：v1.26 · 2026-08-14 ｜ 配套：`sg-hash.py`（文件指纹工具）｜ 上游依据：《研发顺序与里程碑验收》、13 份模块设计（M01-M13）、00 统一约定
>
> **v1.26 决策（2026-08-14，sess-feishu-graph，总控人指令）**：§4.9 飞书知识图谱支线二期任务登记（T-917~T-923，依据《二期设计-事件监听与智能增强》+《二期实施计划》）——采集层升级事件驱动常驻监听（FeishuWatcher 托管 3 路 consume，单用户守卫三态/5min 节流重拉/关 stdin 优雅停/退避重启）+ 视觉转述（增量自动+存量手动）+ 消息锚点自动焦点 + 文档日级轮询补位。一期 T-910~T-916 已 ✅（bb7d3d8）。**收口（2026-08-14）**：二期 T-917~T-923 全量交付（7580fc3 watcher / 5119dbe 接线 / 7189fd0 转述 / fddc272 自动焦点 / d3a6ea4 轮询）；全量 1564 绿 + release_check PASS + 前端 build 通过。
>
> **v1.25 决策（2026-08-14，sess-feishu-graph，总控人指令）**：新增 §4.9「飞书知识图谱（面试素材溯源）」支线（T-910~T-916，依据《远期设计/SpecGuard-飞书知识图谱设计-面试素材溯源.md》+《upgrade-plans/2026-08-13-飞书知识图谱一期实施计划.md》）——飞书材料（文档/妙记/群聊话题）经「拉取落池→LLM建议→人工复核→图谱派生」接入 graph_index，面试官 trace_backward 自带证据链。铁律：LLM 不写图谱（建议→人拍板→落盘事实源→确定性派生）；私有/共享双区隔离（未确认材料永不出私有区）；与 GateDock 并行采批次 A（纯新建）/批次 B（改现有代码）分拆防撞。批次 A ✅（commit 11220d3：12 新建文件 26 用例，全量 1409 绿）；T-913 派生段 ✅ 待 commit。**收口（2026-08-14）**：T-910~T-916 全量交付——批次 B 五笔 commit（af7fada 派生段+登记 / 1c89d14 接线 / 3e32e89 复核面板 / 98612da 焦点子图 / 0871641 网状镜头）；全量 1551 绿 + release_check PASS + 前端 build 通过；一期收口待笔 e2e+文档随本登记提交。
>
> **v1.24 决策（2026-08-13，sess-gatedock-dev，总控人指令）**：§4.8 GateDock 二期（T-901）+ 三期（T-902）全量交付——① MCP 只读工具 `gate_dock_status`（runtime 注入 `_session_id` 特权参数，RBAC 分级纯读）+ 前端 `gate-card`/`gate-exec` 围栏渲染（AgentChat 消息流内嵌可操作卡片，复用 GateCardView 组件）+ skills 推卡话术（gate-dock-guide.md，L1/L2/L3 分档接管）；② L3 代执行白名单硬编码（material_include/material_exclude/topic_confirm 三可逆低危 action），GateExecCard 用户确认才执行，白名单外确定性拒绝；③ 测试 MCP 6 例 + 全量 1399 全绿 + 前端 build + release_check PASS。
>
> **v1.23 决策（2026-08-13，sess-gatedock-dev，总控人指令）**：① **历史归档瘦身**——v1.1~v1.22 决策记录、打磨期（§4.1 四轮）、升级期已完成任务（S0~S8 主线/P-A 支路/引擎补点/知识体系/瘦身块）、历史会话注册与文件登记留痕，归档至《历史区/SpecGuard-总控文档-归档-2026-08-13.md》；总控文档仅保留活跃任务（进行中/未认领/储备）+ §6 登记中行与各文件最新基准行；② **新增 §4.8「对话操作台 GateDock」支线**（T-900~T-902，依据《远期设计/SpecGuard-对话操作台设计-GateDock.md》）：T-900 一期 ✅ 已完成（本会话交付，commit 23a4c60），T-901/T-902 未认领、与全部主线并行。
>
> **历史决策**：v1.1~v1.22 全部决策记录见归档文件第一章；已完成任务验收备注见归档文件第三~七章。

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
> 关键路径串行：S0→S1→S2✅→S3→S4→S5→S6→S7→S8；P-A 支路（T-070/071/072）从 S3 起可全程并行（**T-070 为咽喉，S3 起 P0**，v1.6）；**S0.5 依据透明快车道（v1.5，T-511/T-512）插在 S0 与 S1 之间但不阻塞 S1，✅ 2026-08-07 完成**；**S1 purpose 地基（T-010~T-014）✅ 2026-08-10 完成（里程碑验收五项全过，S2 依赖就绪）**；**S2 F1 面试闭环 ✅ 2026-08-10 完成（T-020~T-024 全部交付，S3 依赖就绪）**；**瘦身任务块（v1.6，T-601/T-602）先于 S1 施工（T-601 modes 退役是 T-010 硬前置）**；**飞书 CLI 支线（v1.6，T-701~T-703）与主线并行、近期可认领（依赖 T-602 单一注册面）**；T-073 与 S6 并行、治理三件套按依赖前置认领（v1.6）。
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
- **飞书 CLI 支线（v1.6）**：§4.6 T-701~T-703 与 S1+ 主线互不依赖（T-701 依赖 T-602 单一注册面），近期可认领
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
> 分区：**§4.1 打磨期**（✅ 归档）｜**§4.2 远期升级期**（已完成归档，储备保留）｜**§4.3 引擎演进补点**（储备）｜**§4.4 知识体系**（✅ 归档）｜**§4.5 瘦身任务块**（✅ 归档）｜**§4.6 飞书 CLI 集成**（进行中）｜**§4.7 规模化升级**（触发制）｜**§4.8 对话操作台 GateDock**（✅ T-900~T-902 全完成）。
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
| T-701 | 飞书-认证 | 多用户认证服务 | mcp_server/tools/lark_auth.py + specstd.workspace | 每用户独立配置目录 `{SG_ROOT}/.lark-cli/{emp_no}/`（USERPROFILE 注入，实测生效）+ .gitignore 补充；lark_auth_login 两阶段（--no-wait 返回 verification_url 给用户 → --device-code 完成；--recommend 与现状 app scope 一致）；lark_auth_status / lark_auth_logout（按 emp_no 隔离）；未绑定用户明确提示引导授权 | T-602 | 进行中 | sess-lark-dev | P0｜近期可认领，与 S1+ 并行；子进程并发锁（每用户一把，防 token 刷新互踩） |
| T-702 | 飞书-执行 | 通用执行器 | mcp_server/tools/lark_run.py + agent/runtime | lark_run 透传全部 lark-* 域命令（能力探索不限定域）：子进程注入当前用户 USERPROFILE、命令白名单校验（禁 shell 拼接）、超时 60s + 结果截断（复用 _TOOL_RESULT_MAX_CHARS 出口）；写操作（high-risk-write）强制 --yes 且需用户确认；调用留痕（工号×命令×结果摘要） | T-701 | 进行中 | sess-lark-dev | P0｜能力探索随本任务验证（calendar/im/task/approval 等域） |
| T-703 | 飞书-工作台 | workbench 绑定页与审计 | workbench 前后端 | 「个人设置 → 绑定飞书」：授权 URL / 授权状态 / scope 清单 / 解绑；Agent 会话自动带出当前用户飞书身份（emp_no → 配置目录映射）；调用审计（工号/会话/工具/入参摘要，与 T-082 口径对齐） | T-701/T-702 | 进行中 | sess-lark-dev | P1｜近期可认领 |

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

### 4.8 对话操作台 GateDock（v1.23 新增，与全部主线并行）

> 依据：《远期设计/SpecGuard-对话操作台设计-GateDock.md》（2026-08-13 定稿）。
> 定位：材料管理/评分冻结/禅道集成三个人拍板面板的单条拍板动作收进 AgentChat「🎛 操作台」页签（GateCard 统一组件），菜单面板降级保留为管理/审计视图。
> 硬边界：**不新增 MCP 写工具**（禅道写铁律 1 不动）；**分档接管**——L1 引导全量兜底 / L2 预填（评分/冻结/禅道写永远人拍板）/ L3 代执行仅可逆白名单（材料入包/移出、议题确认），白名单扩缩比照冻结层评审。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-900 | GD-一期 | 操作台页签 + 只读汇总端点 + 分档卡片 | workbench 前后端（gate_dock_service / specflow_gate_dock / GateDockPanel / AgentChat SidePanel） | gate-dock 纯读汇总（session_id 经 sf_interviews 反查面试上下文）+ 五类卡片（议题确认/材料入包/评分确认/冻结三闸/禅道建故事）人拍板按钮直调原有 REST + 「🤖 帮我」L1 引导；菜单三面板零回退；测试 11 例 + release_check PASS | — | 已完成 | sess-gatedock-dev | P0 ✅ 2026-08-13（commit 23a4c60）：GET /api/specflow/gate-dock（纯读零写副作用，session_id/interview_id 双入参，未绑定面试返回空态）+ GateDockPanel（L3 档可逆卡绿色标签、L2 档人拍板黄色标签）+ AgentChat 操作台页签 + askAgentGuide（复用 askAgentFix 直发模式）；test_gate_dock.py 11 例全绿 + 63 回归 + 前端 build + release_check 全 PASS |
| T-901 | GD-二期 | 对话流主动推卡 + L2 参数预填 | AgentChat（gate-card 围栏渲染）+ mcp_server/tools/gate_dock + agent/runtime + agent/skills | MCP 只读工具 `gate_dock_status`（runtime 注入 `_session_id` 特权参数，RBAC 纯读分级）+ 前端 `language-gate-card` 围栏拦截渲染（复用 GateCardView 组件，操作台与消息内嵌共用）+ skills 推卡话术（gate-dock-guide.md，推卡时机表 + L1/L2 分档接管）+ requirement_interview 白名单加 gate_dock_status | T-900 | 已完成 | sess-gatedock-dev | P1 ✅ 2026-08-13：gate_dock_status MCP 工具（纯读零写副作用，side_effect 默认 none）+ runtime._execute_tool 注入 `_session_id`（下划线前缀防伪造）+ _RBAC_READONLY_TOOLS 加 gate_dock_status + server.py 注册 + AgentChat PreBlock gate-card 围栏拦截（GateDockCtx Provider）+ GateCardView 抽组件（GateDockPanel 瘦容器复用）+ gate-dock-guide.md skills（推卡时机表 + 围栏格式 + 分档话术）；test_gate_dock MCP 6 例 + 全量 1399 全绿 + 前端 build + release_check PASS |
| T-902 | GD-三期 | L3 白名单代执行 | GateCardView（GateExecCard）+ AgentChat gate-exec 围栏 | 白名单硬编码前端常量 `GATE_EXEC_ACTIONS`（material_include/material_exclude/topic_confirm，均可逆低危）+ `language-gate-exec` 围栏渲染 GateExecCard（确认/忽略双按钮，用户点「确认执行」才以用户身份调原 REST，RBAC 兜底）；白名单外 action 确定性拒绝（黄框提示）；评分/冻结/禅道写**永远停 L2** | T-901 | 已完成 | sess-gatedock-dev | P2 ✅ 2026-08-13：GateExecCard 组件（白名单校验→确认卡→执行→结果回显）+ GATE_EXEC_ACTIONS 三 action 硬编码（扩缩需评审）+ AgentChat PreBlock gate-exec 围栏拦截；白名单外 action 黄框拦截提示；与 T-901 共用同一前端 build + 测试 + release_check 验证批次 |

### 4.9 飞书知识图谱（v1.25 新增，面试素材溯源，与全部主线并行）

> 依据：《远期设计/SpecGuard-飞书知识图谱设计-面试素材溯源.md》（2026-08-13 定稿）+《upgrade-plans/2026-08-13-飞书知识图谱一期实施计划.md》。
> 定位：飞书材料（文档/妙记/群聊话题）成为 graph_index 一等节点——LLM 出候选边（依据+置信度）→ 人批量复核 → 落盘事实源 → 确定性派生；面试官 trace_backward 自带素材证据链；双层视图（全景网状镜头 + AgentChat 焦点子图）。
> 硬边界：① LLM 不写图谱（只出建议，人拍板落盘才生效）；② 私有/共享双区隔离（未确认材料/原始群聊快照永不出 .specflow/{emp} 私有区）；③ 飞书侧只读红线；④ 图片走替身文本（imgmap 分离，纯文本模型透明）。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-910 | 图谱-地基 | 材料池落盘 + 事实源读写 | specflow/feishu_pool（paths/pool_store/facts） | 私有区三通道快照（fd/fm/群×天）+ sha256-12 指纹 + imgmap 分离；共享区 topics.yaml/material_links.yaml 排序写入幂等覆盖；6 用例 | — | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 11220d3） |
| T-911 | 图谱-提炼 | LLM 话题聚类 + 建边建议 + 替身文本 | specflow/feishu_pool（topic_cluster/link_suggest/captions） | 话题增量归并保 id 稳定（图谱不依赖 LLM 复现）；三重防幻觉（锚点存在性/evidence 子串/rejected 过滤）；替身文本拼装纯文本模型透明；10 用例 | T-910 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 11220d3） |
| T-912 | 图谱-采集闸门 | 拉取入库 + 复核服务 | lark_cli + feishu_sync_service + feishu_review_service + routers/feishu_pool | watch 配置即显式授权载体；三通道只读拉取（错误诚实入 errors）；复核队列 emp 隔离；确认提升共享区/拒绝工作区留痕；invalid 不可确认；10 用例 | T-911 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 11220d3；路由文件新建未挂 main.py，挂载在 T-914） |
| T-913 | 图谱-派生 | graph_index 飞书派生段 | graph_index store/builder/service | feishu_doc/feishu_minutes/topic 节点 + mentions 边（仅 confirmed、断链不建边）；共享区事实源纳入 source_fingerprint；backlink 增 mentioned_by；3 用例 + 删库重建一致性回归全绿 | T-912 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（32 用例全绿，待 commit） |
| T-914 | 图谱-接线 | main.py 挂路由 + feishu_fetch 复用切换 | workbench main.py + mcp_server/tools/feishu_fetch.py | feishu_pool 路由挂载（watch/sync/复核五端点生效）；feishu_fetch 改 import specflow.feishu_pool.lark_cli（29 用例回归） | T-912/T-913 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 1c89d14：main.py import+include_router 挂载；feishu_fetch 内联封装删除改 import；test_non_win_command_prefix 等 2 例 patch 目标随迁移修正；44 用例全绿） |
| T-915 | 图谱-呈现 | 复核面板 + 双层视图前端 | MaterialsPanel/api.ts/AgentChat/GraphPanorama + graph.py（focus/network） | 材料页签关联复核面板（置信度条+批量确认/拒绝）；/api/graph/focus N 跳子图 + AgentChat 侧栏；全景第 4 镜头网状（elkjs 力导向零新增依赖，500 节点护栏） | T-913 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（三笔：3e32e89 复核面板 FeishuReviewPanel + api.ts；98612da focus_subgraph 端点 + AgentChat「◎ 图谱」页签 FocusGraph；0871641 network_view + elk force 网状镜头 NetworkGraph + GraphPanorama 第 4 镜头；35 图谱用例全绿 + 前端 build 通过） |
| T-916 | 图谱-收口 | e2e 贯通 + 发布门禁 | 全链路 | mock e2e（同步→聚类→建议→确认→建图→子图）；真实环境面试官链路验证；全量回归 + release_check 全 PASS；设计文档状态已实施 | T-915 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14：test_e2e_pipeline 六段贯通（mock lark/LLM：同步→聚类→建议→确认→build_index→focus_subgraph 含 fd/tp 节点与 mentions 边）；全量 1551 用例全绿 + release_check 全 PASS；设计文档 v1.1 已实施（§5.3 rejected 口径修订为共享区留痕） |
| T-917 | 图谱二期-监听 | watcher 骨架（单用户守卫） | services/specflow/feishu_watcher.py | 扫描 .lark-cli/{emp}×watch 配置×token 有效；0 静默/1 启动/>1 告警不启动（二期单用户边界）；3 用例 | T-916 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（7580fc3：守卫三态 3 用例） |
| T-918 | 图谱二期-监听 | watcher 核心（节流/恢复/优雅停） | feishu_watcher.py | 3 路 consume 托管（IM bot+minutes/vc user）；stdin PIPE 保活+stderr ready 阻塞就绪；5min 节流合并→复用一期 sync 重拉；指数退避重启（连续 5 次停摆告警）；关 stdin 优雅停禁 kill -9；3 用例 | T-917 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（随 7580fc3 入库：节流合并/优雅停/退避重启 3 用例） |
| T-919 | 图谱二期-接线 | main.py 挂载 watcher | workbench/backend/main.py | startup 启动（守卫静默跳过）+ shutdown 优雅停；start/stop_background 幂等；import 冒烟 | T-918 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（5119dbe：251 routes + 幂等 2 用例） |
| T-920 | 图谱二期-转述 | 图片视觉转述实装 | captions.py + feishu_pool 路由 + FeishuReviewPanel | vision model_id 未配置全链路跳过；增量落池自动转+存量面板手动转；下载/模型失败落 failed 诚实呈现；3 用例 + 前端 build | T-916 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（7189fd0：transcribe_images 实装 + POST /transcribe + 面板🖼按钮） |
| T-921 | 图谱二期-焦点 | 消息锚点自动焦点 | utils/focusAnchor.ts + FocusGraph/AgentChat | 最近消息最后提及锚点（FR/AC/tp/fd/fm）自动渲染；手动输入优先可覆盖；tsc build 通过 | T-916 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（fddc272：extractLastAnchor 纯函数 + FocusGraphTab messages 接线） |
| T-922 | 图谱二期-轮询 | 文档日级轮询补位 | feishu_sync_service.sync_recent_docs + watcher 挂 job | drive +search --edited-since 1d ∩ watch.docs 授权清单交集落池（未授权不进池）；APScheduler 每日 job 不落 jobs 表；1 用例 | T-919 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（d3a6ea4：交集过滤用例 + watcher cron 挂载） |
| T-923 | 图谱二期-收口 | e2e + 发布门禁 | 全链路 | 事件 NDJSON→节流→重拉→聚类→建议入队全 mock 贯通；全量回归 + release_check PASS；设计 v1.1 已实施 | T-918/T-920/T-921/T-922 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14：test_e2e_event_to_review_queue 贯通（事件→节流一次重拉→落池→聚类→建议 pending 入队）；全量 1564 绿 + release_check PASS；设计 v1.1 |

---

## 5. 会话注册表（开工必填）
> 表行格式：`| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |`
| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |
|---|---|---|---|---|
| sess-lark-dev | 飞书 CLI 集成施工 | T-701 → T-702 → T-703 | 2026-08-11 | T-701→T-702→T-703 顺序施工，与 S8 主线全程并行；依赖 T-602 ✅ |
| sess-gatedock-dev | GateDock 对话操作台施工 + 总控 v1.23/v1.24 归档编排 | T-900 + T-901 + T-902 + 归档瘦身 | 2026-08-13 | T-900 一期 ✅（commit 23a4c60）→ T-901 二期 ✅ + T-902 三期 ✅（MCP 工具 + 围栏渲染 + 白名单代执行 + skills 话术）；总控 v1.23 归档瘦身 + v1.24 二三期完成收口 |
| sess-feishu-graph | 飞书知识图谱施工（面试素材溯源） | T-910 ~ T-916（一期✅）→ T-917 ~ T-923（二期） | 2026-08-14 | 一期批次 A（11220d3）+ 批次 B（af7fada~bb7d3d8）全量收口；二期事件监听/转述/自动焦点/轮询开工 |
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
| docs/引擎升级建议-第三批-对标开源引擎评估.md | sess-master | 2026-08-07 | 477f8c866bf4 | 07f403994fe0 | 已完成 | 补写 v2 复核修正与施工规格（§六） |
| docs/远期设计/verifier/runs/2026-08-07T-task-sync-v1.md | sess-master | 2026-08-07 | NEW | 571ec4a458a1 | 已完成 | 原型更新验收运行记录：屏完整性/ID 抽查/node --check 全 PASS；截图项本环境未执行已注明；28功能/298FR 口径存疑留待复核 |
| docs/远期设计/verifier/runs/2026-08-07T-s1-plain-v1.md | sess-master | 2026-08-07 | NEW | 91ce655d4c20 | 已完成 | S1 改写验收运行记录：屏完整性/新增内容/node --check 全 PASS；截图项未执行已注明 |
| docs/远期设计/verifier/runs/2026-08-07T-s8-flow-v1.md | sess-master | 2026-08-07 | NEW | 9262af31bf84 | 已完成 | S8 流转图验收运行记录：屏完整性/新增内容/node --check 全 PASS；截图项未执行已注明 |
| docs/远期设计/specguard-vision/index.html | sess-master | 2026-08-07 | 19759ec51183 | 64d328aaaad3 | 已完成 | 文案修订：标语「未来 AI 时代」→「AI 时代」（S8 tip-bar + ctx-term 两处，现在已是 AI 时代）；轻量改动屏结构未动，grep 复验「未来」零残留 |
| docs/远期设计/app/index.html | sess-master | 2026-08-07 | 19759ec51183 | 64d328aaaad3 | 已完成 | specguard-vision 同内容副本，同步覆盖（cmp 一致） |
| docs/远期设计/SpecGuard-知识体系设计.md | sess-master | 2026-08-07 | cba09a346b8c | faa5074979ee | 已完成 | 补 §4.5 面板呈现（依据透明·阅读足迹 V1/V2/V3）+ §8 分期新增 S0.5 行 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-s05-dev | 2026-08-07 | b9c44f504ab1 | a8899625b861 | 已完成 | T-511：WS doc_read case + readingFeed state（_store 跨导航保持）+ 阅读页签接线 + openFileViewer hunks/fallback 透传 + openDocRead；顺带修复预存构建红（React.memo UMD→memo import、删除 hint 死代码） |
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
| test_specstd/test_feishu_fetch.py | sess-s2.5-dev | 2026-08-11 | NEW | 6717fdf9231c | 已完成 | T-025/T-026 测试 19 例（agenda/链路分支/权限块/subprocess 封装） |
| specflow/materials/__init__.py | sess-s3-dev | 2026-08-11 | NEW | e8c9ae224ff2 | 已完成 | S3：materials 包（store/pipeline/coverage/pack_assembler） |
| specflow/materials/store.py | sess-s3-dev | 2026-08-11 | NEW | ce823b89d454 | 已完成 | T-030/T-031：sf_materials/sf_material_topics 表 + CRUD（MAT-xxx 全局唯一 + sha256_12 + 状态机 + workspace 隔离 + 候选确认闸门） |
| specflow/materials/pipeline.py | sess-s3-dev | 2026-08-11 | NEW | f2b699791432 | 已完成 | T-030：sniff（magic bytes + 控制字符比例防误判）/extract（md/docx 解包 XXE 拒绝/pdf 文本层无 OCR）/chunk（md 标题/PRD § 锚点/页标） |
| specflow/materials/coverage.py | sess-s3-dev | 2026-08-11 | NEW | 295e805b9c64 | 已完成 | T-034：coverage_map 机打依据（FR 标题关键词片段+2-gram 词表，high/low 置信分层，缺口摘要） |
| specflow/materials/pack_assembler.py | sess-s3-dev | 2026-08-11 | NEW | da9a70fed2a0 | 已完成 | T-032/T-033：六分区确定性装配 → info_pack.yaml（回调注入只读数据源 + 双闸门） |
| workbench/backend/services/specflow/materials_service.py | sess-s3-dev | 2026-08-11 | NEW | c509b574a13b | 已完成 | T-030~T-034：上传/解析/候选/入包/装配/新鲜度服务编排（REST/MCP 共用） |
| mcp_server/tools/specflow_pack.py | sess-s3-dev | 2026-08-11 | NEW | 72b3ae801ebc | 已完成 | T-032：pack_assemble/pack_read_section/material_parse_status/material_extract_topics/pack_freshness_check 5 工具 |
| workbench/frontend/src/pages/ZentaoPanel.tsx | sess-s5-dev | 2026-08-11 | NEW | 798e2e66d21f | 已完成 | T-057：禅道集成面板四区（冻结 delta 交付/提 BUG 双入口/对话草案确认/锚点作业） |
| mcp_server/tools/feishu_fetch.py | sess-s5-dev | 2026-08-11 | e02940f0973f | 12f62fd0d601 | 已完成 | T-057：+feishu_doc_read/feishu_base_query（lark-cli 纯读，权限结构化提示） |
| mcp_server/tools/specflow_refs.py | sess-s5-dev | 2026-08-11 | 7c28e7ac6e71 | 75b1e53ffd61 | 已完成 | T-057：+sf_suggest_story_draft（草案建议恒 draft 态，不触禅道） |
| workbench/backend/services/specflow/sf_refs_store.py | sess-s5-dev | 2026-08-11 | 5ddc936214c8 | 58e52807b6b7 | 已完成 | T-057：+sf_story_drafts 表（draft→created/cancelled 状态机） |
| workbench/backend/services/zentao/client.py | sess-s5-dev | 2026-08-11 | 28c0cf9f4ce2 | 2029b0ba931f | 已完成 | T-057：create_story_from_draft_job（幂等优先）+ list_frozen_deltas |
| workbench/backend/routers/zentao.py | sess-s5-dev | 2026-08-11 | 3b8367208ecb | 3d0f9f8dc3c2 | 已完成 | T-057：+from-draft/story-drafts/cancel/frozen-deltas/jobs 列表端点 |
| agent/runtime.py | sess-s5-dev | 2026-08-11 | 4e8fb4f0bbe9 | b31bb4e2bb2c | 已完成 | T-057：product 只读集 +3 工具（feishu_doc_read/base_query/sf_suggest_story_draft） |
| test_specstd/test_s5_zentao.py | sess-s5-dev | 2026-08-11 | ab4e3476a6f7 | e0aa9829d071 | 已完成 | T-057：+18 例（草案链路/幂等/角色闸门/feishu handler） |
| workbench/backend/routers/specflow_materials.py | sess-s3-dev | 2026-08-11 | NEW | d55ff8e23fdc | 已完成 | T-030~T-032：上传/列表/预览/候选/confirm/include/pack/reassemble 8 端点（confirm/include 仅 product） |
| agent/purposes/requirement_interview.md | sess-s3-dev | 2026-08-11 | 47b8bc180367 | d87717aa7964 | 已完成 | 白名单加 specflow_pack 5 工具 + info_pack 三件套（14→22 工具） |
| test_specstd/test_specflow_materials.py | sess-s3-dev | 2026-08-11 | NEW | 2fa75bffb15f | 已完成 | T-030~T-034 测试 38 例（store/pipeline/coverage/装配器/MCP/REST） |
| graph_index/__init__.py | sess-pa-dev | 2026-08-11 | NEW | 56aaf37d6421 | 已完成 | T-070：graph_index 包（确定性派生服务入口） |
| graph_index/store.py | sess-pa-dev | 2026-08-11 | NEW | b9dce4a2f1ab | 已完成 | T-070：SQLite 存储（nodes/edges/index_meta + 类型枚举 + 谱系阶段映射） |
| graph_index/builder.py | sess-pa-dev | 2026-08-11 | NEW | 4d2f139c4bc9 | 已完成 | T-070/T-073：确定性派生（两遍扫描建 depends_on 边；锚点行号 source_ref；T-073 挂链节点 interview/decision/external_ref 读 workbench.db） |
| graph_index/service.py | sess-pa-dev | 2026-08-11 | NEW | fbe14900172e | 已完成 | T-070/T-073：查询服务（status/rebuild/保鲜/L0/L1/L2/backlink/健康分）+ 谱系 trace BFS（流方向逐边映射） |
| graph_index/snapshot.py | sess-pa-dev | 2026-08-11 | NEW | 27e08746d468 | 已完成 | T-072：里程碑快照（导出/列表/指纹）+ 两档演化 diff（+/-/~ + per_module） |
| specflow/lineage/__init__.py | sess-pa-dev | 2026-08-11 | NEW | e8d57c3529c5 | 已完成 | T-074：血缘链谱系口径子包 |
| specflow/lineage/broken_link_rules.yaml | sess-pa-dev | 2026-08-11 | NEW | bc8bc9d87162 | 已完成 | T-074：断链规则集 BL-01~BL-06（WARNING 级） |
| specflow/lineage/lineage_check.py | sess-pa-dev | 2026-08-11 | NEW | 6b3831932f0a | 已完成 | T-074：断链确定性校验器（纯图遍历+规则集，结果可删可重建） |
| mcp_server/tools/graph_index.py | sess-pa-dev | 2026-08-11 | NEW | 816f22ad1c45 | 已完成 | T-070/T-072/T-073/T-074：MCP 工具 8 个（graph_query/backlink/rebuild/snapshot/diff + lineage_trace/check） |
| workbench/backend/routers/graph.py | sess-pa-dev | 2026-08-11 | NEW | c783a17626dc | 已完成 | T-070/T-072：graph 路由（status/panorama L0-L2/backlink/source 受控前缀/snapshots/diff/rebuild） |
| workbench/backend/routers/lineage.py | sess-pa-dev | 2026-08-11 | NEW | 51c4d5584b9f | 已完成 | T-073/T-074：lineage 路由（trace/node/check GET+POST） |
| workbench/backend/main.py | sess-pa-dev | 2026-08-11 | 2a040f72b8b4 | d012bf97b127 | 已完成 | T-070~T-074：注册 graph/lineage 路由（与 S6 data_fab/coverage 追加式共存） |
| test_specstd/test_graph_index.py | sess-pa-dev | 2026-08-11 | NEW | 4a8fc17fea97 | 已完成 | T-070/T-072/T-073/T-074：测试 29 例（构建/source_ref/确定性/指纹/三层视图/backlink/快照 diff/血缘 trace/断链规则/红线） |
| workbench/frontend/src/App.tsx | sess-pa-dev | 2026-08-11 | c732bde8efe5 | c17d99d6317e | 已完成 | T-071/T-073：菜单+路由（全景图谱/血缘链，总览组） |
| workbench/frontend/src/pages/GraphPanorama.tsx | sess-pa-dev | 2026-08-11 | NEW | efdd4366e5ce | 已完成 | T-071/T-072：三层下钻 + 三镜头 + backlink + 里程碑时间轴/diff + 📍 源头定位行高亮 |
| workbench/frontend/src/pages/LineageStory.tsx | sess-pa-dev | 2026-08-11 | NEW | 7c5500d0d9a8 | 已完成 | T-073/T-074：四阶段分带 + Q1/Q2 追溯 + 外部锚点虚线 + 断链 WARNING 面板 |
| workbench/backend/services/preflight.py | sess-engine-t502 | 2026-08-11 | 754a746b9fa1 | f562b4d593a9 | 已完成 | T-502：_static_file_refs（with.file 提取）+ _split_file_refs（插值→unknown/缺失→missing）+ scan_dependencies/scan_compliance 收录 missing_files/unknown_file_refs（含 _group 聚合与 summary 计数），相对项目根（场景库根上层）判存在性，纯读零写路径 |
| mcp_server/tools/validator.py | sess-engine-t502 | 2026-08-11 | be02323a5a8c | 79e241ef5561 | 已完成 | T-502：MISSING_FILE WARN（with.file 存在性校验，解析根=工作区根回退仓库根；插值路径跳过；与 BODY_KEY/UNKNOWN_TPL 同族） |
| test_specstd/test_preflight.py | sess-engine-t502 | 2026-08-11 | 489991496228 | 08e3145023f9 | 已完成 | T-502：TDD 追加 7 例（文件存在无缺口/缺失报 missing_files/插值进 unknown_file_refs 与 gaps/teardown 扫描/多场景归组/绝对路径/scan_compliance 收录） |
| test_specstd/test_acceptance_fixes.py | sess-engine-t502 | 2026-08-11 | 49f92b81e30e | e64a8bbbc7cd | 已完成 | T-502：validator MISSING_FILE 2 例（缺失 WARN/存在不报） |
| workbench/frontend/src/api.ts | sess-engine-t502 | 2026-08-11 | 31f0f87cb42f | 34f217a4e478 | 已完成 | T-502：PreflightResult/PreflightScenario 扩展 file_refs/missing_files/unknown_file_refs(_gaps) |
| workbench/frontend/src/pages/RunControl.tsx | sess-engine-t502 | 2026-08-11 | 9bd6c6dee39c | 5e7b55a3a413 | 已完成 | T-502：弹窗预警区 📎 fixtures 分组 + ❓ 文件引用分组（复用 T-318 通道，无覆盖输入框）+ 底部说明区分仓库缺陷语义 |
| mcp_server/tools/lark_auth.py | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-701：MCP 3 工具（lark_auth_status/login/logout）+ RPEST 共用底层函数 |
| mcp_server/tools/lark_run.py | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-702：lark_execute 通用执行器（白名单/写保护/审计） |
| mcp_server/server.py | sess-lark-dev | 2026-08-11 | 5176e99713cc | | 登记中 | T-701/T-702：TOOL_MODULES 注册 lark_auth + lark_run |
| .gitignore | sess-lark-dev | 2026-08-11 | a9c6c2c5be38 | | 登记中 | T-701：补充 .lark-cli/ |
| workbench/backend/routers/lark_binding.py | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-703：REST 端点 4 个（status/login/logout/scopes） |
| workbench/backend/main.py | sess-lark-dev | 2026-08-11 | 3bbd4741ac30 | | 登记中 | T-703：include_router lark_binding |
| workbench/frontend/src/api.ts | sess-lark-dev | 2026-08-11 | 886a405dcca0 | | 登记中 | T-703：larkApi 类型+方法 |
| workbench/frontend/src/App.tsx | sess-lark-dev | 2026-08-11 | b43a13ab3d15 | | 登记中 | T-703：菜单「绑定飞书」+ 路由 /lark-binding |
| workbench/frontend/src/pages/LarkBinding.tsx | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-703：绑定页 UI（状态卡片/scope 清单/绑定引导） |
| agent/purposes/requirement_interview.md | sess-lark-dev | 2026-08-11 | 1cb823842e19 | | 登记中 | T-702：白名单加 lark_auth_* 3 + lark_execute |
| docs/远期设计/SpecGuard-多角色服务访问流转与规模化升级设计.md | sess-master | 2026-08-11 | NEW | f4d3b3ba01f3 | 已完成 | v1.22：规模化升级支线设计文档（角色服务访问流转图 + T-801~T-806 详细设计 + 开发时机总表） |
| docs/远期设计/SpecGuard-飞书CLI集成设计-T701-T703.md | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-701~T-703 设计文档 |
| docs/远期设计/SpecGuard-飞书CLI集成计划-T701-T703.md | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-701~T-703 实施计划 |
| mcp_server/tools/open/__init__.py | sess-s8-dev | 2026-08-11 | NEW | 1ae7b5896e2b | 已完成 | T-083：open/ 命名空间包（L0 只读面红线注释 + 共享只读辅助：工作区解析/changes 扫描/图谱只读打开） |
| mcp_server/tools/open/specflow_refs.py | sess-s8-dev | 2026-08-11 | NEW | 9417260214fa | 已完成 | T-083：get_frozen_spec/get_proposal/query_decisions/get_interview_status/get_delta_contract 五工具（M05/M04 数据源） |
| mcp_server/tools/open/lineage_query.py | sess-s8-dev | 2026-08-11 | NEW | 7785e721724d | 已完成 | T-083：trace_forward/trace_backward/query_graph 三工具（只读存量索引，不调 ensure_fresh；panorama_* 直读） |
| mcp_server/tools/open/refs_query.py | sess-s8-dev | 2026-08-11 | NEW | 42e1cf1fb0f0 | 已完成 | T-083：lookup_external_ref（M06 sf_external_refs 读面 + 谱系提示） |
| mcp_server/tools/open/dev_context.py | sess-s8-dev | 2026-08-11 | NEW | c057061178a3 | 已完成 | T-085：dev_context_by_zt_ref/by_anchor/by_fr 三入口 + 六分区 pack + 聚合指纹 + 默认取版（自动发现当前冻结版）+ 未冻结不可达 + 草稿零泄漏 |
| test_specstd/test_failure_index.py | sess-s8-dev | 2026-08-11 | NEW | b3c11cd1af97 | 已完成 | T-083 顺带：预存测试污染修复——attribution._get_reports_root 直接赋值改 monkeypatch（3 处），防模块级残留污染后续测试 |
| mcp_server/server.py | sess-s8-dev | 2026-08-11 | d7ee368841d9 | a418eebb1325 | 已完成 | 并发提交事故修复：3092367 合并提交的 server.py 丢失 open/lark 挂载（mods 仅含 knowledge），重新追加挂载（open 五模块 + lark_auth/lark_run，追加式）；工具数恢复 84 |
| mcp_server/tools/open/quality_query.py | sess-s8-dev | 2026-08-11 | 44f2756dff52 | 2d332d82c40c | 已完成 | 验收修复：read_run_report 不重复注册 Tool 对象（重名触发 LLM API 400「Tool names must be unique」），改 handle 层映射 attribution，open 注册面 15 工具 |
| mcp_server/tools/side_effect_registry.py | sess-s8-dev | 2026-08-11 | 5a7bd7b767c8 | d7761f8f7aa7 | 已完成 | 验收修复：lark_auth_login/logout/lark_execute 改标 draft（7513b38 误标 external-write 破坏空集红线 + runtime 拒用），遵循 zentao 先例暂标 draft |
| test_specstd/test_open_surface.py | sess-s8-dev | 2026-08-11 | c52c7bf574b2 | b326770ae3ea | 已完成 | 验收修复：open 注册断言 16→15 + 新增 read_run_report 不重复注册断言 |
| test_specstd/test_mcp_server.py | sess-s8-dev | 2026-08-11 | 25c97e028453 | 366756de0725 | 已完成 | 验收修复：工具数 84→83（read_run_report 去重） |
| docs/远期设计/SpecGuard-总控文档.md | sess-s8-dev | 2026-08-11 | 52bc0e4a082d | 5cd365e9b502 | 已完成 | v1.22 自身登记（补二）：全量验收修复登记——read_run_report 去重 + lark 分级 draft；修改后hash = 登记中形态指纹 5cd365e9b502（v1.3 约定） |
| docs/远期设计/SpecGuard-总控文档.md | sess-gatedock-dev | 2026-08-13 | 252391d90885 | 29b6ad154684 | 已完成 | v1.23 自身登记：历史归档瘦身（版本决策/§4.1/§4.2 已完成/§4.3 完成行/§4.4/§4.5/§5 历史/§6 历史入归档文件）+ §4.8 GateDock 支线（T-900 ✅ / T-901 / T-902）+ §5 注册；修改后hash 29b6ad154684 |
| docs/历史区/SpecGuard-总控文档-归档-2026-08-13.md | sess-gatedock-dev | 2026-08-13 | NEW | 3d69155ce15f | 已完成 | v1.23：归档文件落盘 |
| mcp_server/tools/gate_dock.py | sess-gatedock-dev | 2026-08-13 | NEW | 976fcd933520 | 已完成 | T-901：gate_dock_status MCP 只读工具（_session_id 特权参数 + interview_id 可选，纯读零写副作用，side_effect 默认 none） |
| agent/skills/gate-dock-guide.md | sess-gatedock-dev | 2026-08-13 | NEW | 095feb02c8bb | 已完成 | T-901：推卡时机表 + gate-card/gate-exec 围栏格式 + L1/L2/L3 分档接管话术 + 白名单约束 |
| workbench/frontend/src/components/GateCardView.tsx | sess-gatedock-dev | 2026-08-13 | NEW | 041b7680f51d | 已完成 | T-901/T-902：GateCardView 单卡渲染（操作台与消息内嵌共用）+ GateExecCard 三期确认卡 + GATE_EXEC_ACTIONS 白名单 |
| agent/runtime.py | sess-gatedock-dev | 2026-08-13 | — | 2420441bc0e2 | 已完成 | T-901：_RBAC_READONLY_TOOLS 加 gate_dock_status + _execute_tool 注入 _session_id 特权参数 |
| mcp_server/server.py | sess-gatedock-dev | 2026-08-13 | — | 09b16feaeb4c | 已完成 | T-901：import gate_dock + mods 列表注册（工具数 89→90） |
| agent/purposes/requirement_interview.md | sess-gatedock-dev | 2026-08-13 | — | f9d25c7b4375 | 已完成 | T-901：tools 白名单加 gate_dock_status |
| workbench/frontend/src/pages/GateDockPanel.tsx | sess-gatedock-dev | 2026-08-13 | — | f89a4352cc47 | 已完成 | T-901：瘦容器重写（复用 GateCardView，251→77 行） |
| workbench/frontend/src/pages/AgentChat.tsx | sess-gatedock-dev | 2026-08-13 | — | be39793869bc | 已完成 | T-901/T-902：GateDockCtx Provider + PreBlock gate-card/gate-exec 围栏拦截 |
| test_specstd/test_gate_dock.py | sess-gatedock-dev | 2026-08-13 | — | cb512a5b0e80 | 已完成 | T-901：追加 TestGateDockMcp 6 例（会话反查/空态/显式 ID/未找到/纯读分级） |
| test_specstd/test_mcp_server.py | sess-gatedock-dev | 2026-08-13 | — | 317c13bc9141 | 已完成 | T-901：工具注册断言 89→90 + gate_dock_status 加入 expected 集合 |
| docs/远期设计/SpecGuard-总控文档.md | sess-gatedock-dev | 2026-08-13 | 29b6ad154684 | 52e1245a26e4 | 已完成 | v1.24 自身登记：T-901/T-902 已完成收口 + §5 更新 + §6 新增 10 文件登记 |
| specflow/feishu_pool/__init__.py | sess-feishu-graph | 2026-08-14 | NEW | 06dded07d114 | 已完成 | T-910：批次 A（11220d3） |
| specflow/feishu_pool/paths.py | sess-feishu-graph | 2026-08-14 | NEW | dfb40de0f09e | 已完成 | T-910：私有/共享路径函数 |
| specflow/feishu_pool/pool_store.py | sess-feishu-graph | 2026-08-14 | NEW | 5313d3687aa3 | 已完成 | T-910：快照落盘+imgmap |
| specflow/feishu_pool/facts.py | sess-feishu-graph | 2026-08-14 | NEW | 88273b81b4be | 已完成 | T-910：事实源读写 |
| specflow/feishu_pool/topic_cluster.py | sess-feishu-graph | 2026-08-14 | NEW | 32d9a654e87b | 已完成 | T-911：话题聚类增量归并 |
| specflow/feishu_pool/link_suggest.py | sess-feishu-graph | 2026-08-14 | NEW | 6cf7e048129a | 已完成 | T-911：建边建议三重防幻觉 |
| specflow/feishu_pool/captions.py | sess-feishu-graph | 2026-08-14 | NEW | 583595de91d0 | 已完成 | T-911：替身文本拼装 |
| specflow/feishu_pool/lark_cli.py | sess-feishu-graph | 2026-08-14 | NEW | b5e07a19d065 | 已完成 | T-912：lark-cli 封装（与 feishu_fetch 同源） |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-feishu-graph | 2026-08-14 | NEW | 373d714a93ea | 已完成 | T-912：三通道拉取入库 |
| workbench/backend/services/specflow/feishu_review_service.py | sess-feishu-graph | 2026-08-14 | NEW | 7b2746fe2aee | 已完成 | T-912：复核服务提升闸门 |
| workbench/backend/routers/feishu_pool.py | sess-feishu-graph | 2026-08-14 | NEW | abcfaebaf464 | 已完成 | T-912：REST 五端点（挂载在 T-914） |
| test_specstd/test_feishu_pool.py | sess-feishu-graph | 2026-08-14 | NEW | 9aa9d0f23703 | 已完成 | T-910/T-911 用例 |
| test_specstd/test_feishu_topic_cluster.py | sess-feishu-graph | 2026-08-14 | NEW | 4ad2f054a85b | 已完成 | T-911 用例 |
| test_specstd/test_feishu_link_suggest.py | sess-feishu-graph | 2026-08-14 | NEW | d50ae9851171 | 已完成 | T-911 用例 |
| test_specstd/test_feishu_sync.py | sess-feishu-graph | 2026-08-14 | NEW | e404fa02465b | 已完成 | T-912 用例 |
| test_specstd/test_feishu_review.py | sess-feishu-graph | 2026-08-14 | NEW | 06cdc787fdad | 已完成 | T-912 用例 |
| graph_index/store.py | sess-feishu-graph | 2026-08-14 | 09dc90236192 | be64c9ff64e6 | 已完成 | T-913：节点/边类型枚举扩展 |
| graph_index/builder.py | sess-feishu-graph | 2026-08-14 | 2a2aafc4034e | 22c5c1e74dfa | 已完成 | T-913：飞书派生段+指纹 |
| graph_index/service.py | sess-feishu-graph | 2026-08-14 | afcfcf7c2414 | c40a9db4c14d | 已完成 | T-913：backlink mentioned_by |
| test_specstd/test_graph_index.py | sess-feishu-graph | 2026-08-14 | 176c77d59602 | 304b8c38f5ce | 已完成 | T-913：TestFeishuNodes 3 例 |
| docs/远期设计/SpecGuard-飞书知识图谱设计-面试素材溯源.md | sess-feishu-graph | 2026-08-14 | NEW | 35a82e984324 | 已完成 | 设计定稿（d5a4142） |
| docs/upgrade-plans/2026-08-13-飞书知识图谱一期实施计划.md | sess-feishu-graph | 2026-08-14 | NEW | 29da3e3b5717 | 已完成 | 实施计划+批次 A/B 执行序（ad11696） |
| workbench/backend/main.py | sess-feishu-graph | 2026-08-14 | — | 8ba9c7bcf36d | 已完成 | T-914：feishu_pool 路由挂载（1c89d14） |
| mcp_server/tools/feishu_fetch.py | sess-feishu-graph | 2026-08-14 | — | 0047c5e25e40 | 已完成 | T-914：复用 lark_cli 统一封装（1c89d14） |
| test_specstd/test_feishu_fetch.py | sess-feishu-graph | 2026-08-14 | — | 9841616cbe4c | 已完成 | T-914：patch 目标随迁移修正（1c89d14） |
| workbench/frontend/src/api.ts | sess-feishu-graph | 2026-08-14 | — | 8cb1e087ccf1 | 已完成 | T-915：feishuPoolApi+graphApi.focus/network（3e32e89/98612da/0871641） |
| workbench/frontend/src/components/FeishuReviewPanel.tsx | sess-feishu-graph | 2026-08-14 | NEW | c82e85045496 | 已完成 | T-915：关联复核面板（3e32e89） |
| workbench/frontend/src/pages/MaterialsPanel.tsx | sess-feishu-graph | 2026-08-14 | — | 1958c72d5a16 | 已完成 | T-915：挂载复核面板（3e32e89） |
| graph_index/service.py | sess-feishu-graph | 2026-08-14 | — | 31c9344877f1 | 已完成 | T-915：focus_subgraph+network_view（98612da/0871641） |
| workbench/backend/routers/graph.py | sess-feishu-graph | 2026-08-14 | — | 094d006c9b38 | 已完成 | T-915：/focus 端点+lens=network（98612da/0871641） |
| workbench/frontend/src/components/FocusGraph.tsx | sess-feishu-graph | 2026-08-14 | NEW | 776bd858f98a | 已完成 | T-915：焦点子图组件（98612da） |
| workbench/frontend/src/pages/AgentChat.tsx | sess-feishu-graph | 2026-08-14 | — | 484db7dccb0e | 已完成 | T-915：「◎ 图谱」页签（98612da） |
| workbench/frontend/src/utils/elkLayout.ts | sess-feishu-graph | 2026-08-14 | — | fc2c9de4843f | 已完成 | T-915：layoutNetworkByELK 力导向（0871641） |
| workbench/frontend/src/components/NetworkGraph.tsx | sess-feishu-graph | 2026-08-14 | NEW | d1bd15e09015 | 已完成 | T-915：网状全景组件（0871641） |
| workbench/frontend/src/pages/GraphPanorama.tsx | sess-feishu-graph | 2026-08-14 | — | e7934063b4cc | 已完成 | T-915：第 4 镜头接入（0871641） |
| test_specstd/test_graph_index.py | sess-feishu-graph | 2026-08-14 | — | abbddcbb86ac | 已完成 | T-915：focus/network 用例（98612da/0871641） |
| test_specstd/test_feishu_sync.py | sess-feishu-graph | 2026-08-14 | — | 233703329b5c | 已完成 | T-916：e2e 贯通（收口笔） |
| docs/远期设计/SpecGuard-总控文档.md | sess-feishu-graph | 2026-08-14 | 918a20f96c61 | 4e09855feb68 | 已完成 | v1.25：§4.9 任务块+§5 会话+§6 登记+收口状态 |
| docs/远期设计/SpecGuard-飞书知识图谱二期设计-事件监听与智能增强.md | sess-feishu-graph | 2026-08-14 | NEW | 72c391148d1e | 已完成 | 二期设计定稿（64ccc29） |
| docs/upgrade-plans/2026-08-14-飞书知识图谱二期实施计划.md | sess-feishu-graph | 2026-08-14 | NEW | c49b3ff25b2c | 已完成 | 二期计划 Task0-7（64ccc29） |
| docs/远期设计/SpecGuard-总控文档.md | sess-feishu-graph | 2026-08-14 | 58b09aab4c31 | 4130088d3b1e | 已完成 | v1.26：二期任务登记 |
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
