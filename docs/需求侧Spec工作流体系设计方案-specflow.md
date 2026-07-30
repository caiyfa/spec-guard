# 需求侧 Spec 工作流体系（specflow）设计方案

> **状态**：方案待评审（2026-07-30）。本文件只做体系设计，**不含详细设计**；详细设计等其他会话完成当前开发后，以任务链文档形式另立。
> **来源**：用户需求——SpecGuard 从「测试场景编排 + spec 质量双循环引擎」扩张为「需求→验证全链路」，引入产品经理需求面试能力（参考《Spec 方法论落地手册 V3》六阶段工作流）。
> **已拍板决策**：
> 1. ✅ 定位正式扩张为「需求→验证全链路质量平台」；
> 2. ✅ 面试产物是**需求侧**资产，**独立体系维护，不与测试侧产物混放**；
> 3. ✅ 先出本方案，详细设计等其他会话完工后启动；
> 4. ✅ **统一 AgentChat 入口 + 会话级用途锁定**（2026-07-30）：不建独立面试页面；会话创建时手动选用途、创建即锁定、标记用途，提示词按用途静态装配；测试侧内部不再分子类型。
> 5. ✅ **用途选择交互采用方案 A「出发仪式」**（2026-07-30）：使命卡片舞台 + 装配清单飞入 + 身份色体系；纯 CSS/Tailwind 实现，**零新前端依赖**；键盘流（←/→ 选择、Enter 出发、Esc 取消）；单用途用户跳过舞台、记住上次选择。

---

## 一、定位扩张：从两环到全链路

### 1.1 现状

SpecGuard 当前是 Harness 五关注点闭环中「验证 + 反馈」两环的工程落地，服务对象是测试人员（QA）。其一切能力（场景 `covers: [FR-xxx]` 锚点、FR 覆盖矩阵、delta 导入生成计划、契约指纹门禁）都建立在一个**外部假设**上：

> 上游已经有人把需求面试做完了，交付了一份冻结的、锚点规范的 spec。

这个假设不受控。spec 质量参差时，下游场景生成、覆盖缺口分析全部带病工作。

### 1.2 扩张后

引入需求侧体系后，SpecGuard 覆盖五关注点中的**上下文（spec 生产）→ 验证 → 反馈**三环，价值链闭合成大循环：

```
需求面试(P0清零) → spec冻结(三闸) → 场景生成(现有generate) → 执行/归因(现有)
        ↑                                                          ↓
        └──────── 反哺spec(SPQ台账/执行证据，现有反馈环) ────────────┘
```

**注意最后一环**：现有双反馈循环（执行结果反哺 spec）恰好成为下一轮需求面试的输入——这是引入需求侧后才真正闭合的大循环，也是本体系的核心价值叙事。

### 1.3 需要同步改写的定位文档（详细设计阶段执行）

- `AGENTS.md` Project Overview（定位一句话 + Status）
- `docs/完全体SpecGuard能力边界与交互流程-测试人员指南.md`（或拆分为测试人员指南 + 产品经理指南两份）

---

## 二、核心架构决策：需求侧 / 测试侧双体系分离

> 这是用户拍板的第 2 条决策的落地展开，是本方案最重要的结构约束。

### 2.1 分离原则

两个体系**各自闭环、界面清晰**。唯一允许的耦合点是两个「界面产物」：

| 界面产物 | 方向 | 说明 |
|---------|------|------|
| **冻结的 spec 基线**（工作区 specs/ 下的 spec.md + FR/AC 锚点） | 需求侧**写** → 测试侧**读** | spec 是契约，需求侧生产、测试侧消费；specstd 是双方共用的规范层 |
| **delta 变更**（changes/ 下的 delta-spec 等） | 需求侧**生产** → 测试侧**导入** | 已有耦合点：测试计划只能由 delta 导入生成，本方案延续此设计 |

除这两个界面外，过程产物零混放。

### 2.2 分离对照表

| 维度 | 测试侧（现有，不动） | 需求侧（新建，specflow） |
|------|---------------------|--------------------------|
| 工作区产物目录 | `{workspace}/.specguard/`（drafts/plans/reports/info_packs） | `{workspace}/.specflow/`（interviews/decisions/changes/archive） |
| 顶层包 | engine / agent / mcp_server / feedback | **specflow/**（新顶层包） |
| 后端路由/服务 | routers/drafts、plans、runs… | routers/specflow_*.py + services/specflow/（独立前缀） |
| DB 表 | users/scenario_meta/settings… | `sf_*` 前缀独立表（决策台账、面试会话元数据、评分记录） |
| 前端入口 | Scenarios/Drafts/Plans/Runs/AgentChat | **统一 AgentChat 入口 + 会话级用途锁定**（用户拍板 2026-07-30）：新建会话时手动选用途（RBAC 过滤清单），创建即锁定不可变；用途驱动提示词装配/工具集/右侧面板/产物归属四件事；换用途=新会话（可带引用跳转）；非独立页面组；选择交互见 §4.5「出发仪式」 |
| RBAC 角色 | admin / tester 视角 | 新增 **product（产品经理）** 角色，权限只覆盖 specflow 路由 |
| 会话用途 | 测试工作台（模式移除后的统一行为：全量工具+统一提示词，内部不再分子类型） | 需求面试（创建期锁定的第二种用途；初期用途清单仅此两个，防模式机制借尸还魂） |
| MCP 工具 | scenario_tools/draft_writer/validator… | 独立 specflow 工具模块（与测试工具不同模块） |
| 治理闸门 | draft 三闸（人工评审→格式校验→发布门禁） | **复用同一哲学、独立实现**：面试产物冻结走自己的三闸（产品确认→specstd 合规校验→P0 清零门禁） |

### 2.3 为什么规范层（specstd）可以共用而不算"混"

specstd 是「定标准的代码化」——它定义的是 spec.md 的格式规范（目录/锚点/合规规则），**规范本身无立场**，需求侧和测试侧都是规范的遵守者。如同交通规则不属于任何一辆车。specflow **依赖** specstd（面试产出的 spec 草案必须过 specstd.conformance 校验），但**不在 specstd 里放任何需求侧产物**。

### 2.4 .specguard/ 与 .specflow/ 的 git 策略

沿用现有模式（各工作区产物目录自带 .gitignore）：

- `.specflow/interviews/`（面试会话记录）——**版本化保留**（手册铁律：面试归档、记录可追溯）
- `.specflow/decisions/`（P0/P1/P2 决策台账）——**版本化保留**
- `.specflow/changes/`（进行中的 delta）——**版本化保留**（对应手册 changes/ 目录）
- `.specflow/archive/`（已冻结归档）——**版本化保留、只读冻结**（对应手册 archive/）
- 面试过程的临时 LLM 上下文/缓存——gitignore

> 与手册的差异说明：手册中 changes/archive 直接放业务项目根目录；SpecGuard 场景下工作区是克隆的 spec 仓库，统一收纳在 `.specflow/` 下，避免污染业务仓库结构，最终冻结的 spec.md 才合入工作区 `specs/`（业务仓库正文）。

---

## 三、手册六阶段的范围裁剪

手册是完整流水线，但不是六个阶段都归 SpecGuard。**裁剪原则：SpecGuard 只做「文档与质量」环节，不做「代码开发」环节**（分步开发/TDD 是业务项目内的事，由业务项目自己的 Harness 承担）。

| 手册阶段 | 是否进 specflow | 说明 |
|---------|----------------|------|
| ① 需求面试 | ✅ **核心** | AI 面试官、P0/P1/P2 决策清单、五维打分、面试归档 |
| ② 规格锚定 | ✅ **核心** | proposal/spec/api 草案产出、三方冻结 |
| ③ QA 用例 | ❌ 已有 = 测试侧 | 手册的 test-cases.yaml 对应 SpecGuard 现有场景 YAML + 生成模式 |
| ④ 分步开发 | ❌ 不做 | 属业务项目开发流程，出 SpecGuard 边界 |
| ⑤ 质量裁判（TDD） | ❌ 不做 | 同上（SpecGuard 自己的开发纪律另算） |
| ⑥ 规格归档 | ✅ **核心** | delta 生命周期（changes→合并基线→archive 冻结）、verify-delta 机械校验 |

**结论：specflow = 手册的 ①②⑥ 三个阶段 + 第 3 章 Delta 机制 + 第 4 章跨模块结构（V2 再议）。**

---

## 四、specflow 体系架构（方案级）

### 4.1 分层结构

```
specflow/                        # 新顶层包【需求侧，与 engine 平级】
├── interview/                   # ① 需求面试
│   ├── question_bank.py         #   提问维度库（按 spec 11 章组织扫描清单）
│   ├── decision_ledger.py       #   P0/P1/P2 决策台账状态机（pending→resolved）
│   └── gate.py                  #   P0 清零门禁（确定性：台账无 pending P0 → 放行）
├── anchor/                      # ② 规格锚定
│   ├── proposal_schema.py       #   proposal.md 四段式结构定义
│   ├── spec_draft.py            #   spec 草案管理（待定项标记「待确认」）
│   └── scoring.py               #   QA 五维评分卡（确定性维度机打 + 主观维度 LLM 建议）
├── delta/                       # ⑥ 规格归档（手册第 3 章）
│   ├── manifest.py              #   delta.manifest.yaml 读写（机器清单，合并单一真相）
│   ├── merge.py                 #   ADDED 追加 / MODIFIED 整块替换 / REMOVED 删除
│   └── verify.py                #   verify-delta V1-V6 机械校验（spec.md 的 oasdiff）
└── archive.py                   # 归档冻结（changes→archive，只读）
```

**确定性校验边界**（与项目宪法「校验走确定性校验器」一致）：

- ✅ 确定性：P0 清零检查、11 章齐全性、FR/AC 锚点格式（复用 specstd）、MODIFIED 全量性检查、verify-delta V1-V6、双向锁定集合比对；
- ❌ 不可确定性化：提问质量、需求理解深度、五维中的主观维度（预期清晰度等）——永远「LLM 建议 + 人拍板」。

### 4.2 复用现有资产（不重造）

| 需求 | 复用对象 | 方式 |
|------|---------|------|
| 多轮面试对话 | agent/runtime.py 会话循环 + compactor + 会话隔离 | 面试行为指引写成 markdown 片段文件，按会话用途装配进系统提示词（**不写进 agent/modes/**——模式层正在移除）；会话模型增加 `purpose` 创建期字段（持久化、不可变），替代一切运行时模式状态 |
| spec 格式校验 | specstd/conformance + anchors | specflow 调用，不复制规则 |
| 内容指纹/比对 | specstd/signature | 面试中引用存量模块时做「现状 vs 目标」比对输入 |
| 决策台账模式 | feedback/ledger.py 的 SPQ 状态机设计 | 同模式独立实现（不共用表，保分离） |
| 面试 UI | Workbench AgentChat（统一入口） | 复用同一 AgentChat 页面壳与会话基础设施；「需求面试」作为会话用途之一，由会话用途字段驱动专属提示词章节、specflow 工具可见集、右侧面板（决策台账/五维评分卡/草案预览）；会话树按用途标记过滤 |
| 工作区透传 | specstd contextvar（X-SG-Workspace） | specflow 产物同样按工作区隔离 |
| 三方冻结治理 | draft 三闸哲学 | 独立实现需求侧三闸：产品确认 → specstd 合规校验 → P0 清零门禁 |

### 4.3 RBAC 角色扩展

新增 `product` 角色，三方分工映射手册：

| 动作 | product（产品） | dev（开发） | tester（QA） |
|------|----------------|------------|--------------|
| 回答面试问题 / 确认决策 | ✅ 拍板权 | 主导面试 | — |
| 编写 proposal/spec/api 草案 | 审稿 | ✅ 编写权 | — |
| 五维打分 | — | — | ✅ 打分权 |
| P0 清零后冻结 spec | ✅ 三方确认之一 | ✅ | ✅ |
| specflow 路由访问 | ✅ | ✅ | 只读 |

### 4.4 数据流（界面产物只有两个出口）

```
.specflow/interviews/ ──决策台账──> .specflow/decisions/ ──P0清零──>
    草案(proposal+spec+api) ──[需求侧三闸]──> 【出口1】冻结spec合入工作区 specs/
                                            【出口2】changes/<delta>/ 供测试侧 delta 导入生成计划
归档：.specflow/changes/<delta>/ → verify-delta(V1-V6) → 合并基线 → .specflow/archive/<delta>/ 只读
```

---

### 4.5 用途选择交互（方案 A「出发仪式」，已拍板）

**概念**：用途创建即锁定是 UX 约束，包装成仪式感——选用途不是填表单，是「装配你的 Agent，然后出发」。锁定 = 「使命已确认」的承诺感。

**交互流程**：

```
点击「+ 新会话」→ 聊天区中央升起选择舞台（页面内全宽，非弹窗，背景网格微光缓动）
  → 使命卡片并排悬浮（每用途一张卡，未来新用途直接加卡）
  → hover：卡片浮起 + 渐变描边流动 + 3D 微倾斜（4-6°，跟随鼠标）
  → 选中：选中卡向中心放大，其余卡淡出退场 → 下方展开「装配清单」逐行飞入
       ✓ 系统提示词已装载 / ✓ N 个工具已就绪 / ✓ 右侧面板已挂载 / 🔒 用途创建后锁定
  → 「出发 →」（或 Enter）→ 舞台收起进入会话，顶部用途色带标记身份
```

**身份色体系**（贯穿全程，不止选择页）：测试工作台=青蓝（沿用现有 info 蓝）、需求面试=紫（Stripe purple 系）；应用于卡片描边、会话树徽标、聊天顶部色带、面板点缀；新用途=加卡加色，体系自然扩展。

**实现约束**：纯 CSS/Tailwind（conic-gradient 描边流光、perspective+mousemove 3D 倾斜、staggered animation-delay 清单飞入、radial-gradient 网格背景），**零新前端依赖**；动画库（framer-motion 等）如未来需要须先过依赖评审。

**效率保护（酷炫的边界）**：
- 单用途用户（RBAC 过滤后仅一个用途，如 product 角色）→ 跳过舞台直接创建；
- 记住上次选择，默认聚焦，Enter 即走；
- 键盘流全程可用：←/→ 切换、Enter 出发、Esc 取消。

**演进路径**：用途 ≥ 5 个卡片摆不下时，可演进为 ⌘K 命令面板式（方案 B），键盘流习惯无缝迁移。

---

## 五、分阶段路线图

| 阶段 | 内容 | 触层 | 门禁/评审要求 |
|------|------|------|--------------|
| **F1 面试最小闭环** | interview 模式 + 决策台账 schema + `.specflow/` 目录约定 + P0 清零确定性校验 + 面试归档 | specflow/interview + agent/modes（仅新增文件） | 不动 specstd，无 Ask First 项 |
| **F2 扫描仪与评分卡** | 11 章齐全性/SHALL/AC 可执行性校验（调 specstd，如需扩规则则属规范演进）；五维评分卡半自动 | specflow/anchor（+ 可能触及 specstd） | ⚠️ 触及 specstd 规则扩展 = Ask First，需评审 |
| **F3 锚定与归档** | proposal/spec 草案三闸、delta manifest、verify-delta V1-V6、合并归档、RBAC product 角色、前端需求工作室页面组 | specflow/delta + workbench（独立路由/页面/表） | RBAC 变更评审；DB 新表（sf_* 前缀，不动现有表） |
| **F4（V2 候选）** | 跨模块两层结构（delta-index/e2e-cases/modules）、glossary 七维术语字典、api.yaml/api-delta.yaml 契约管理 | specflow 扩展 | 单独立项评审 |

**F1 是价值拐点**：只做 F1 就已经能让产品经理在 AgentChat 里完成结构化面试、产出 P0 清零的决策清单和可追溯的面试归档。F2/F3 逐步把产出物规格化、闸门化。

---

## 六、风险与开放问题（留待详细设计）

| # | 问题 | 倾向 | 备注 |
|---|------|------|------|
| Q1 | specflow 产物是否需要多用户协作（产品+开发+QA 同一会话不同角色操作）？ | 台账按记录级归属（谁确认谁留痕），会话归属发起人 | 详细设计时定 |
| Q2 | 面试产出的 spec 草案合入工作区 specs/ 的写路径：直接写克隆目录 + git commit，还是走工作台导出由人提交？ | 倾向后者（人提交），与「Agent 产物不入库不经人」铁律对齐 | 详细设计时定 |
| Q3 | api.yaml / api-delta.yaml（OpenAPI 契约）纳入 F3 还是 F4？ | F4——测试侧当前不消费 api.yaml，需求侧可后置 | 待评审 |
| Q4 | interview 模式与现有 generate 模式的衔接（面试冻结后一键转场景生成）？ | F3 做「冻结→生成场景草稿」跳转入口，不做自动串联 | 待评审 |
| Q5 | 五维评分的主观维度是否允许 LLM 预打分？ | 允许预打分但必须 QA 人工确认才生效 | 与「Agent 只建议、人拍板」边界一致 |
| Q6 | 手册的 glossary 七维术语字典是否引入？ | V2 候选——价值高但依赖「token 触发机制」设计，单独立项 | 手册第 2 章 |

---

## 七、开工前提（硬性）

1. **等其他会话完成当前开发**（用户明确要求）；开工前查 `docs/upgrade-plans/任务总控-TASKS.md` §5 文件占用表，确认无冲突；
2. 详细设计以任务链文档形式补充到 `docs/upgrade-plans/`，并在任务总控登记任务卡片后领取开发；
3. F1 开工前需用户确认：Q2（写路径）、以及 specflow 包名（本方案暂定 `specflow`，备选 `reqline`）；
4. **specflow 不得依赖模式机制**（modes/mode_router/locked_mode 等正在被另一会话移除）：会话用途（purpose）是**创建期一次性参数**（用户手动选择、创建即锁定、持久化），不引入任何运行时切换/路由/锁定中间件——与模式移除改造互为终态、落地顺序无关；详细设计需与模式移除会话对齐会话模型的 `purpose` 字段落点；
4. 触及 specstd 规范扩展（F2）一律先评审后动手（AGENTS.md Ask First）。

---

## 附：手册关键机制摘要（详细设计时的依据）

- **需求面试五步**：AI 提问 15-20 问多轮迭代 → P0/P1/P2 分级 → Dev 写契约（待定项标「待确认」）→ QA 五维打分（逻辑完整性/预期清晰度/覆盖率/边界异常/前置条件，≥70 及格）→ 面试归档；
- **AI 三重角色**：比对引擎（code vs spec）、扫描仪（checklist=spec 11 章模板）、记录员（决策结构化、100% 可追溯）；
- **spec.md 11 章**：目标/非目标/用户场景/功能需求(FR-xxx+SHALL+版本标记)/数据实体/边界异常/接口契约/验收标准(AC 可执行)/交付物/上线回滚/变更日志；
- **delta 三段式**：ADDED/MODIFIED/REMOVED；MODIFIED 必须写全量（原/新/原因三要素）；每条带 `[delta:代号]` + `→ task:[id]` 双向锁定；
- **verify-delta V1-V6**：锚点有效/全量替换/双向锁定/可追溯/合并后完整/manifest 一致——**脚本验证不靠 agent**；
- **归档铁律**：只有合并后的 spec.md + api.yaml 进基线；archive/ 只读冻结。
