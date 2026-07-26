# SpecGuard 智能层开发计划（M0–M5）

> **版本**：v2.0 | **日期**：2026-07-26 | **状态**：待评审
> **输入**：[Agent 架构设计](SpecGuard-Agent架构设计-MCP工具层与薄Harness.md)、[交互原型](SpecGuard完全体交互原型.html)、[产品演示](SpecGuard完全体产品演示.html)、Spec 工作流手册 V3（外部输入）、当前代码库实测盘点
> **原则**：引擎冻结层零改动；智能层纯增量叠加；三道闸（人工评审 → 格式校验 → 发布门禁）不变；正确性一律由确定性校验器兜底

---

## 〇、本期四项根本决策（v2.0 定稿，优先级高于一切既有引用）

| # | 决策 | 含义 |
|---|------|------|
| P1 | **工作区（Workspace）抽象** | spec 来源不再是硬编码路径：用户可①选择本地 spec 文档文件夹 ②输入 git 仓库地址克隆下载，二者都注册为工作区；接入时**必读 AGENTS.md** 作为背景知识 |
| P2 | **SpecGuard 定标准** | spec 仓库文档结构标准由 SpecGuard 定义（§二），外部 spec 仓库**必须适配该标准**才能接入；SpecGuard 不去适应任何外部私有结构 |
| P3 | **独立仓库** | SpecGuard 已从 TDM 后端项目独立，从属期遗留的过时链接/路径全部清理 |
| P4 | **不背历史包袱** | 开发期**不做任何兼容层**：旧路径引用直接替换为新抽象，不设 fallback；跨仓 subprocess 依赖（verify_delta_merge.py）重写为 SpecGuard 原生能力；现存 spec 仓库不符合标准就整改仓库，而不是在 SpecGuard 里写适配代码 |

> P4 推论：v1 计划中「M0 迁移债务清算」的提法作废——不是「修旧」，而是「立新」：旧引用所指向的能力（执行链路、spec 校验、delta 导入）直接重建在工作区抽象之上。

---

## 一、输入解析与现状对比结论

### 1.1 三份输入各自回答什么

| 输入 | 回答的问题 | 对开发计划的作用 |
|------|-----------|------------------|
| 架构设计文档 | Agent 怎么建（6 项 ADR、5 个 MCP 工具、薄 harness ~300 行、M1–M5 里程碑） | 计划的骨架，直接继承 |
| 交互原型 / 产品演示 | 完全体长什么样（9 屏交互、双反馈循环、人机分工） | 前端差距清单与验收基准 |
| Spec 工作流手册 V3 | Spec 仓库结构范式（specs/changes/archive、FR 锚点、delta 三段式、manifest、verify-delta V1–V6、签名防漂移） | **§二结构标准的素材来源**——经 SpecGuard 裁剪固化后成为唯一标准 |

### 1.2 现状盘点：三层架构完成度（实测）

| 层 | 状态 | 实测依据 |
|----|------|----------|
| 引擎层 | ✅ 已建成冻结 | `engine/` 9 模块齐全；`release_check.py`（仓库根）+ `contracts_baseline.json` 在役 |
| 工作台层 | ✅ 已建成，⚠️ 含从属期遗留引用 | 后端 5 路由 + 6 服务；前端 7 页 |
| 智能层 | ❌ 0% | `agent/`、`mcp_server/`、`drafts/`、`routers/agent.py` 全部不存在 |

### 1.3 差距清单：原型 9 屏 vs 现状 7 页

| 原型屏 | 现状 | 差距 |
|--------|------|------|
| 多系统仪表盘 | 🟡 Dashboard 单系统 | 工作区维度统计 + Spec 同步状态 + FR 覆盖率 |
| Spec 文档中心 | ❌ 无 | 工作区文件树 / 拉取更新 / commit 快照 / delta 标记 |
| Agent 场景生成 | ❌ 无 | 对话面板 + 工具调用卡片 + YAML 预览 + 评审入库流 |
| 编排与关联校验 | 🟡 DagEditor 有 DAG 画布 | covers↔Spec 关联校验、Spec 逻辑审查、未通过禁止执行 |
| 运行中心 | ✅ RunControl | 场景上下文展开（变量/轨迹/数据变化）需增强 |
| 失败归因 | ❌ 无 | 待归因列表 + 归因报告 + 证据链 + BUG 单草稿 |
| 自治回归 | ❌ 无 | 代码 diff 输入 → 影响面圈定 → 增量回归 |
| 双循环反哺 | ❌ 无 | 反哺报告台账（SPQ 编号、状态流转、闭环记录） |
| 通知与反馈路径 | ❌ 无 | 飞书 webhook 注册表（系统 × 场景 × 群）+ 掩码存储 |
| 工作区管理 | ❌ 无（原型亦未覆盖） | 本地文件夹选择 / git URL 克隆 / 激活切换 / 合规报告 |

### 1.4 从属期遗留引用处置清单（按 P3/P4：直接替换，不设兼容层）

| 位置 | 遗留 | 处置 |
|------|------|------|
| `workbench/backend/services/runner.py` | `PROJECT_ROOT = SG_ROOT.parent.parent`；命令 `pytest tests/specguard` | 直接改为仓库根 + `python -m pytest`（pytest.ini 已有 testpaths） |
| `workbench/backend/services/spec_validator.py` | `SPEC_ROOT = PROJECT_ROOT/"raw"/"spec"`；subprocess 调外部 `verify_delta_merge.py` | 删除旧逻辑，改读当前工作区 + specstd 原生校验 |
| `workbench/backend/services/plan_store.py` | 同上 `SPEC_ROOT` 失效 | 同上，改读当前工作区 |
| `workbench/backend/main.py` docstring | `tests/specguard/` 前缀启动说明 | 直接修正 |
| `README.md` / 架构设计文档 | 旧路径前缀、`engine/release_check.py`（实际在仓库根）等过时引用 | 直接修正 |
| `verify_delta_merge.py`（TDM 仓 `scripts/`） | 跨仓 subprocess 依赖 | **不迁移、不调用**——V1–V6 校验逻辑由 specstd 原生重写（§2.2），SpecGuard 自此自洽 |

### 1.5 可复用资产核对（实测验证，全部保留）

| 资产 | 实测位置 | 状态 |
|------|----------|------|
| 动态规范生成 | `services/format_spec.py generate_format_spec_md()` | ✅ 可直接 import |
| 场景扫描 | `services/scenario_store.py _scan_scenarios()` | ✅ |
| ID 分配 | `services/format_spec.py get_next_scenario_id()` | ✅（架构文档引用位置有误，以此为准） |
| WebSocket 事件通道 | `services/runner.py RunManager.broadcast` | ✅ 可复用为 agent 事件流 |
| 文本外科手术参考 | `services/deps_editor.py` | ✅ |
| 发布门禁 | `release_check.py`（仓库根） | ✅ |
| 契约指纹 | `engine/versioning.py check_t6 / fingerprint_from_raw` | ✅ 可直接服务于内容签名检测 |

---

## 二、SpecGuard Spec 仓库结构标准 v1（P2 核心交付物）

> 一句话：**SpecGuard 定标准，外部仓库来适配**。任何 spec 仓库必须通过合规校验才能成为工作区。本标准取材自 Spec 工作流手册 V3，经裁剪固化为机器可校验规则——只收录 SpecGuard 运行所需的最小强制集，不追求手册全集。

### 2.1 标准目录结构（强制）

```
<workspace>/                       # spec 仓库根（一个仓库 = 一个被测系统的 Spec）
├── AGENTS.md                      # 【必备】规则层：Project Overview + 术语 token 清单 + Always/Never
├── specs/                         # 【必备】基线——「系统当前长什么样」
│   └── {module}/{feature}/
│       ├── spec.md                #   11 章契约；FR 锚点 `### FR-<id>:`；AC 锚点 `AC-<id>`
│       └── api.yaml               #   OpenAPI 3.0.3 完整契约
├── changes/                       # 【可选】进行中的 delta（无迭代时为空目录）
│   └── <代号>/
│       ├── proposal.md            #   为什么做 + 做什么 + 影响范围
│       ├── delta-spec.md          #   三段式：## ADDED / ## MODIFIED / ## REMOVED Requirements
│       │                          #   每条 `### FR-<id>:` + [delta:代号] 标记 + → task:[id]
│       ├── api-delta.yaml         #   本次新增/修改接口（OpenAPI 3.0.3）
│       └── delta.manifest.yaml    #   【必备】机器清单：delta/baseline/baseline_sha/operations
└── archive/                       # 【必备】归档只读冻结（初始可为空）
```

### 2.2 合规校验器（conformance）——接入即门禁

工作区接入/拉取时执行，**任一 ERROR 即拒绝接入**，输出结构化整改报告：

| 规则 | 检查项 | 级别 |
|------|--------|------|
| STRUCT | §2.1 必备目录/文件存在；changes/ 下每个 delta 含 manifest | ERROR |
| AGENTS | AGENTS.md 含 Project Overview 与术语 token 清单节 | ERROR |
| ANCHOR | 所有 spec.md 的 FR 锚点匹配 `^### FR-\d+:` 且全局唯一；covers 可解析 | ERROR |
| MANIFEST | manifest operations 与 delta-spec.md 三段式解析结果逐条一致（手册 V6） | ERROR |
| MODIFY_FULL | MODIFIED 条目含 原/新/原因 三要素且「新」为全量描述（手册 V2） | ERROR |
| TRACE | delta 的 →task 与 task.md 的 ←delta 双向锁定集合相等（手册 V3） | WARN |
| API_LINT | api.yaml / api-delta.yaml 可被 OpenAPI 3.0.3 解析 | ERROR |

> 手册 verify-delta 的 V1（锚点有效）/V5（合并完整）在「delta 合入基线」动作时由同一校验器以合并模式执行；SpecGuard 本期不实现「代执行合并」，只校验不合并（合并是 spec 仓库侧动作）。

### 2.3 工作区接入层（workspace）

**注册表** `workspaces/registry.yaml`（仓库内，不入 git 凭据）：

```yaml
active: tdm
workspaces:
  tdm:
    name: TDM 干部盘点
    system: tdm                      # 关联 systems/{system} 适配包
    source: { type: local, path: "D:/work/spec-tdm" }
    last_commit: a3f8c21
    pulled_at: "2026-07-26 10:00"
  spec-pbs:
    name: PBS 薪酬核算
    system: pbs
    source: { type: git, url: "http://git.internal/spec/spec-pbs.git", branch: main }
    local_path: workspaces/_clones/spec-pbs    # git 型克隆落点
```

- **local 型**：用户选择本地文件夹 → 原地注册，只读使用；
- **git 型**：输入仓库 URL → `git clone` 到 `workspaces/_clones/` → 支持「拉取更新」（fetch + checkout，记录 commit 变化 → 触发 FR 变更检测）；
- **激活切换**：运行时单活工作区；`read_spec` / covers 校验 / delta 导入 / Spec 文档中心全部作用于当前激活工作区；
- **凭据**：git 认证走系统 git 凭据管理器，SpecGuard 不存储任何凭据（Never 条款）。

### 2.4 AGENTS.md 消费方式（P1「了解背景知识」落地）

1. **接入校验**：AGENTS.md 缺失或缺必备节 → 合规校验 ERROR（§2.2）；
2. **背景注入**：工作区 AGENTS.md **全量原文**注入 agent system prompt（手册规范其 ≤200 行，体积可控；全量而非摘要——规则层知识不允许有损压缩）；
3. **术语解析**：AGENTS.md 中的 token 清单同时注入 validator 的 covers 语义提示（hint 生成）。

### 2.5 specstd 包：标准层的代码形态（新顶层包，引擎冻结层零接触）

```
specstd/                    # 【新增】Spec 标准层——SpecGuard 定标准的代码化
├── schema.py               #   标准定义：目录结构/锚点正则/manifest schema（§2.1 单一事实源）
├── conformance.py          #   合规校验器（§2.2，含 verify-delta V1–V6 原生实现）
├── anchors.py              #   FR/AC 锚点解析 → 清单快照（covers 校验与签名检测共用）
├── signature.py            #   内容签名：spec 主体（剔除 §11 Changelog）+ api 每 path 入参/出参
├── workspace.py            #   工作区注册/本地接入/git 克隆/拉取/激活切换/AGENTS.md 读取
└── workspaces/             #   registry.yaml + _clones/（git 型落点，.gitignore）
```

消费方：`mcp_server/tools/*`、`workbench/backend/services/*`、`release_check.py`（后续版本接入 covers 校验时）。**引擎 `engine/` 既有模块一行不改。**

---

## 三、目标目录结构总图（独立仓库真实形态）

```
specguard/                        # 仓库根（独立）
├── specstd/                      # 【新增】Spec 标准层（§2.5）
├── agent/                        # 【新增】薄 harness
│   ├── runtime.py                #   核心循环 LLM⇄tools⇄stop（~150 行）
│   ├── session.py                #   JSONL 会话持久化（agent/sessions/{uuid}.jsonl）
│   ├── events.py                 #   事件总线（复用 runner broadcast 通道）
│   ├── llm_client.py             #   企业大模型网关客户端（OpenAI 兼容 + 计量 + 缓存）
│   ├── prompts/system.md.j2      #   system prompt：format_spec + 工作区 AGENTS.md + 硬约束
│   └── cli.py                    #   POC 独立验证入口
├── mcp_server/                   # 【新增】MCP 工具层（stdio + SSE 双模）
│   ├── server.py
│   └── tools/
│       ├── spec_reader.py        #   read_spec / list_spec_files（当前工作区，含 delta 标记）
│       ├── scenario_tools.py     #   list_scenarios / read_scenario / next_scenario_id
│       ├── registry_query.py     #   query_registry（oracle/step/tool）
│       ├── draft_writer.py       #   write_draft（drafts/ 限定 + 禁覆盖 + patch）
│       └── validator.py          #   validate（格式 + 门禁 + covers 关联 + 注册表）
├── drafts/                       # 【新增】Agent 草稿区（评审通过才移入 scenarios/）
├── workbench/backend/
│   ├── routers/agent.py          # 【新增】/agent/* WebSocket 对话 + 会话管理
│   ├── routers/workspace.py      # 【新增】工作区管理 + Spec 文档中心 API
│   └── services/                 #   spec_validator / plan_store / runner 改读工作区（P4 直接替换）
└── workbench/frontend/src/pages/ # 【新增】AgentChat / SpecCenter / Attribution / AutoRegression / Feedback / NotifyConfig；设置页增加工作区管理
```

---

## 四、里程碑计划（6 个里程碑，约 28 人日）

### M0 · Spec 标准层 + 工作区接入（4 人日）——一切智能能力的前置

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| specstd/schema.py + 标准文档落库（docs/） | 标准 v1 单一事实源 | 评审通过；标准即 §2.1/2.2 的代码化 |
| conformance.py 合规校验器（含 V1–V6 原生重写） | 校验器 + 结构化整改报告 | 对手册范例仓库全 PASS；对构造的 7 类违规样本全部正确拦截 |
| anchors.py + workspace.py（local/git 两型 + 注册表 + AGENTS.md 读取） | 工作区服务 | 本地文件夹注册、git URL 克隆、拉取后 commit 变化可观测、越界访问拒绝，单测全覆盖 |
| 从属期遗留引用直接替换（§1.4 全表） | runner / spec_validator / plan_store / main.py / README 改读工作区与仓库根 | Workbench 执行链路、Spec 校验页、delta 导入在独立仓库全链路跑通；全仓 grep 无 `tests/specguard` 残留 |
| TDM spec 仓库合规评估 | 对 `ifelc-ms-tdm-api/raw/spec` 跑 conformance，输出整改报告 | 报告列出全部 ERROR/WARN；整改动作在 spec 仓库侧排期（非本仓工作量） |

### M1 · MCP 工具层（5 人日）——POC 即可用

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| server.py 骨架（stdio + SSE） | MCP server 可启动 | Qoder 挂载后 `list_tools` 可见全部工具 |
| spec_reader（基于工作区）/ scenario_tools / registry_query | 3 组只读工具 | 单测覆盖；越界路径正确报 `OUT_OF_SCOPE`；`list_spec_files` 正确标注 delta；`read_spec("AGENTS.md")` 可用 |
| draft_writer + 路径守卫 | 写工具 | 仅 `drafts/` 可写；已存在文件返回 `OVERWRITE_DENIED`；patch 模式单测全过 |
| validator 工具（格式 + 门禁 + covers 关联） | 结构化校验报告 | 对存量场景校验结果与 `release_check.py` 一致；covers 校验走 specstd/anchors 清单，编造 FR 必报 `COVERS` 错误并给 hint |
| **POC 验证** | 用 Qoder 挂载生成 3 个真实场景 | 3 场景全部通过发布门禁（资源申请演示弹药） |

### M2 · 薄 harness + CLI（5 人日）

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| llm_client（网关 + 计量 + 缓存 + 退避重试） | 客户端 | 计量数据落 JSONL；system prompt 缓存命中可观测 |
| runtime 核心循环 + session | harness | max_turns=12 熔断；kill 后重跑可从 JSONL 续会话 |
| system.md.j2：format_spec + 工作区 AGENTS.md 全量注入 | skill 组装 | 新增测试 oracle 注册后下次会话 prompt 自动包含；切换工作区后 AGENTS.md 内容随之切换 |
| cli.py 端到端 | CLI | 一条命令生成 IS-GRID-007 并过门禁；幻觉注入用例（诱导编造 oracle）被 validate 拦截并自修复 |

### M3 · Workbench 集成（6 人日）

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| routers/agent.py（WebSocket 对话 + 会话列表） | 后端 | 事件流三类型齐全（assistant / tool_call+tool_result / state） |
| 工作区管理 UI（本地选择 / git URL / 激活切换 / 合规报告展示） | 前端+后端 | 接入不合规仓库时展示整改报告并拒绝激活 |
| 前端 Agent 对话面板（工具调用卡片 + YAML 预览 + covers 锚点确认） | 前端 | 与交互原型视觉一致 |
| Spec 文档中心页（文件树 / 拉取 / commit 快照 / delta 标记） | 前端+后端 | 拉取后 FR 变更检测 → 受影响场景标 DRIFT |
| 三道闸 UI + drafts 区管理 + 编排关联校验 | 入库流 + 前置闸 | 入库后 DAG 画布与覆盖矩阵自动刷新；未评审草稿永不进入执行队列；covers 校验未通过禁止触发执行 |

### M4 · 循环 B 工具：归因 + 内容签名（5 人日）

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| read_run_report / db_evidence 归因工具 | 2 个 MCP 工具 | 对历史 FAIL run 可复现原型中的归因证据链（断言差异 + DB 校对 + 环境探测 + 关联变更） |
| specstd/signature.py 内容签名检测 | 签名基线落盘 `specstd/workspaces/_signatures/` | spec 主体/api 出入参签名变化检测正确；变更命中 covers 反查正确 |
| 用例同步建议（patch 草稿） | Agent 流 | 签名变化场景生成修复草稿并入评审流 |
| 失败归因页 + BUG 单草稿 | 前端 | 归因四类（环境/数据/场景/缺陷）；BUG 单草稿人工确认后才可导出 |

### M5 · 反哺闭环 + 飞书通知（3 人日）

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 反哺报告台账（SPQ 编号 + 状态机：待讨论/研发修改中/已闭环） | 存储 + 管理页 | 循环 A/B 事件自动生成台账条目 |
| 反馈路径注册表（系统 × 场景 × webhook） | 配置 + 管理页 | webhook 掩码存储（如 `a3f***`）；仅出站调用；消息只含 ID/结论/链接 |
| 循环 A/B 事件推送（反馈报告 / 运行监控 / 缺陷通知三类卡片） | 通知集成 | 各触发点消息送达率 100%，含回执记录 |

---

## 五、风险与依赖审批（按 AGENTS.md Ask First 条款，启动前需确认）

| 项 | 说明 | 决策点 |
|----|------|--------|
| 新增 Python 依赖 | MCP Python SDK（`mcp`）、`httpx`（llm_client）、`jsonschema`（manifest/合规校验，若现有环境无） | 评估冲突与安全后批准 |
| 新增前端依赖 | 对话面板 Markdown 渲染组件（候选 `react-markdown`） | 同上 |
| 企业大模型网关 | 接入地址、凭据、计量口径、开发积分额度 | 需运维/平台组提供 |
| git 克隆能力 | 内网 git 服务可达性；认证走系统凭据管理器（SpecGuard 不存凭据） | POC 期可用 local 型先行，git 型不阻塞 M1 |
| TDM spec 仓库整改 | `raw/spec` 按标准 v1 整改（补 manifest、统一 FR 锚点等），工作量在 spec 仓库侧 | 需与 spec 仓库维护方排期协同；整改完成前可用「合规豁免白名单」临时接入（仅限 POC，入正库前必须合规） |
| 多工作区 | 原型为三系统，实际仅 TDM 有适配包 | M3 仪表盘做可扩展结构，PBS/HRC 占位 |

---

## 六、验收指标（完全体智能层整体）

| 指标 | 目标 | 度量方式 |
|------|------|----------|
| 生成场景一次过门禁率 | ≥ 70% | validate 首次 PASS / 总生成数 |
| 幻觉拦截率 | 100% | 未注册引用入库数（应为 0） |
| 人工评审通过率 | ≥ 85% | 评审通过 / 提交评审数 |
| 单场景平均 token | ≤ 25k | 会话计量报表 |
| 场景编写效率 | 人天级 → 分钟级 | 对比手工基线（~0.5 人天/场景） |
| harness 可替换性 | 工具零改动 | 外部 Agent 挂载 MCP 完成同质量生成 |
| covers 关联校验确定性 | 100% 脚本判定 | 校验逻辑零 LLM 参与（手册铁律） |
| 工作区接入合规率 | 100% | 激活的工作区全部通过 conformance（无豁免白名单残留） |
| 历史包袱清零 | 0 处 | 全仓 grep 无 `tests/specguard` / `raw/spec` 跨仓引用残留 |

---

## 七、版本变更与架构文档差异说明

### v1.0 → v2.0 变更（对应四项根本决策）

| 变更 | v1.0 | v2.0 |
|------|------|------|
| spec 来源 | 配置化路径指向 `raw/spec` | 工作区抽象：本地文件夹 / git URL 克隆（P1） |
| 结构关系 | SpecGuard 读外部仓库现状 | SpecGuard 定义结构标准 v1 + 合规校验门禁，外部仓库适配（P2） |
| 遗留引用 | 「迁移债务清算」（修复导向） | 直接替换，不设兼容层（P3/P4） |
| verify_delta_merge.py | 待决策归属 | 不迁移不调用，V1–V6 由 specstd 原生重写（P4） |
| M0 定位 | 债务清算 + spec 接入（3 人日） | 标准层 + 工作区接入（4 人日） |
| AGENTS.md | 未提 | 接入必备 + 全量注入 system prompt + token 清单服务 validator（P1） |

### 与架构设计文档的差异（继承性修正）

| 差异点 | 架构文档 | 本计划 | 原因 |
|--------|----------|--------|------|
| 目录前缀 | `tests/specguard/` | 仓库根 | 2026-07-24 已迁出独立仓库 |
| 复用资产引用 | `engine/release_check.py`、`routers/reference.py` | 仓库根 `release_check.py`、`services/format_spec.py` | 实测修正 |
| read_spec 的作用域 | 「已注册的 spec 仓库根」 | 当前激活工作区（经合规校验） | P1/P2 落地 |
| M3 工作量 | 5 人日 | 6 人日 | 增加 Spec 文档中心页与工作区管理 UI |
