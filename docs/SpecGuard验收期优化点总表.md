# SpecGuard 验收期优化点总表

> 创建时间：2026-07-27
> 最后更新：2026-07-27
> 状态：验收期持续记录，定期评审后纳入升级计划

---

## 模块索引

| # | 模块 | 优化点数 | 优先级分布 |
|---|------|---------|-----------|
| 1 | [工作区管理](#1-工作区管理) | 2 | - |
| 2 | [数据架构与产物归属](#2-数据架构与产物归属) | 1 | - |
| 3 | [认证与权限（RBAC）](#3-认证与权限rbac) | - | - |
| 4 | [场景管理](#4-场景管理) | 2 | - |
| 5 | [测试计划](#5-测试计划) | - | - |
| 6 | [执行引擎](#6-执行引擎) | - | - |
| 7 | [报告与历史](#7-报告与历史) | - | - |
| 8 | [Agent 智能层](#8-agent-智能层) | 6 | - |
| 9 | [草稿管理](#9-草稿管理) | - | - |
| 10 | [Spec 校验](#10-spec-校验) | - | - |
| 11 | [反馈闭环](#11-反馈闭环) | - | - |
| 12 | [前端工作台](#12-前端工作台) | - | - |
| 13 | [开源项目借鉴分析（Pi / OpenCode）](#13-开源项目借鉴分析pi--opencode) | - | - |

> 空模块表示验收期间暂未发现优化点，持续补充。

---

## 1. 工作区管理

### 1.1 Git 克隆时应支持自定义克隆目录

**提出时间**：2026-07-27
**现状**：

当前 Git 克隆的目标路径硬编码在 `specstd/workspaces/_clones/{工作区名称}/`，用户无法指定。

**问题**：

1. **磁盘空间**：`_clones/` 落在 SpecGuard 仓库内部，大型 Spec 仓库克隆可能撑爆系统盘
2. **权限隔离**：多用户场景下，所有克隆集中在同一目录，缺乏物理隔离
3. **运维灵活性**：无法将克隆落到外挂存储 / 网络挂载盘

**优化方向**：

Git 克隆时增加一个**可选的"克隆目录"字段**（类似本地文件夹选择）：

- 留空 → 默认落到 `_clones/{name}/`（兼容现有行为）
- 填写路径 → 克隆到指定位置（如 `/data/specguard-clones/{name}/`）

**注意事项**：
- 路径穿越防护（断言解析后仍在允许的根目录之内）
- 路径合法性校验（不能包含特殊字符、不能是系统关键目录）

---

### 1.2 Git 克隆与本地注册的体验统一

**提出时间**：2026-07-27
**现状**：

目前两种工作区注册途径的体验差异较大：

| 方式 | 入口 | 需要用户操作 |
|------|------|-------------|
| 本地文件夹 | `register-local` | 选择/输入服务器路径 |
| Git 克隆 | `register-git` | 仅输入 URL + 分支 |

**优化方向**：

Git 克隆也应支持选择文件夹（克隆落点），让两种途径的交互模型趋于一致：都是"选择一个目录作为工作区根"，区别仅在于目录来源（已有 vs 从 Git 拉取）。

---

## 2. 数据架构与产物归属

### 2.1 SpecGuard 产生的各类文件存在哪里？

**提出时间**：2026-07-27
**背景**：这是个好问题，直接影响架构演进方向。

**当前文件分布**：

| 文件类型 | 当前位置 | 说明 |
|----------|----------|------|
| 场景 YAML | `scenarios/` 目录 | 在 Spec 仓库内，需手动/Git 提交 |
| 测试计划 | `plans/` 目录 | 由 delta 导入生成，禁止手动新建 |
| 运行报告 | `reports/{timestamp}/` | 在 Spec 仓库内，`.gitignore` 排除，不提交 |
| Agent 草稿 | `drafts/` 目录 | 评审通过才移入 `scenarios/` |
| 工作区注册表 | `specstd/workspaces/registry.yaml` | 在 SpecGuard 服务器本地 |
| 用户/队列数据 | `workbench/backend/data/workbench.db` | SQLite，服务器本地，不提交 |
| Git 克隆 | `specstd/workspaces/_clones/` | 服务器本地 |

**需要回答的问题**：

1. **场景文件（scenarios/）的归属**
   - 当前场景文件存在于 Spec 仓库中（通过工作区挂载）
   - Agent 生成的新场景草稿（drafts/）如何入库？目前需人工评审后手动移入
   - **问题**：是否应该支持 Agent 直接向 Spec 仓库提交 PR/MR？

2. **运行报告（reports/）的归属**
   - 当前报告产物（`run.json`、`cases/*.md`）存在 SpecGuard 服务器本地
   - `.gitignore` 排除了 `reports/`，不会进入 Spec 仓库
   - **问题**：报告是否需要归档到 Spec 仓库的某个分支/tag？还是独立存储（如 OSS）？

3. **工作区注册表（registry.yaml）的归属**
   - 这是 SpecGuard 服务器的运行时状态，与 Spec 仓库无关
   - 当前设计合理（服务器本地）

4. **Delta 导入产物（plans/）的归属**
   - 测试计划由 Spec 变更（delta）驱动生成
   - **问题**：计划是否应该随 Spec 一起版本化？还是作为一次性消耗品？

**架构决策方向**：

```
选项 A：Spec 仓库中心化
  - 场景、计划、报告都提交到 Spec 仓库（不同目录/分支）
  - 优点：版本追溯完整，Spec 与测试结果强绑定
  - 缺点：仓库膨胀，并发写冲突

选项 B：服务器本地 + 按需推送
  - 运行时产物存服务器，关键节点（如发布门禁通过）推送到 Spec 仓库
  - 优点：轻量，灵活
  - 缺点：服务器宕机可能丢数据

选项 C：混合模式（当前接近此方案）
  - 场景/计划 → Spec 仓库（版本化资产）
  - 报告/草稿/队列 → 服务器本地（运行时产物）
  - 需要明确边界并文档化
```

---

## 3. 认证与权限（RBAC）

_验收期间发现的优化点记录于此。_

（待补充）

---

## 4. 场景管理

_涵盖场景创建、Spec 文件关联、单元测试生成、场景编排、工作模式区分等。_

### 4.1 场景创建流程重构：从 Spec 文件到编排的渐进式流水线

**提出时间**：2026-07-27
**现状**：

当前场景管理仅支持对已有 `scenarios/**/*.yaml` 文件的读写编辑（`GET/PUT /api/scenarios/{id}`），**没有「新建场景」的完整流程**。场景文件必须先按 SpecGuard 双层 YAML 格式手工编写，再通过 Agent 或手动编辑。Spec 文件（`spec.md` 等）在工作区中存在但与场景创建无显式关联，`covers` 锚点靠人工在 YAML 中声明。

**问题**：

1. **接入门槛高**：外部 Spec 文件必须遵循 SpecGuard 格式才能使用，不兼容已有需求文档/接口文档/PRD
2. **无场景创建向导**：从需求到测试场景的转化全靠人工编写 YAML，缺少引导式流程
3. **Spec 文件与场景割裂**：场景 `covers` 依赖人工声明 FR ID，无法自动从 Spec 文件提取并关联

**优化方向：渐进式场景创建流水线**

```
步骤 1：新建场景（输入名称/模块）
    │
    ▼
步骤 2：选择关联 Spec 文件（多文件、多类型）
    │   - 从工作区文件树勾选相关文档（spec.md / API 文档 / PRD / Excel 等）
    │   - 这些文件作为场景的「基础信息包」
    │
    ▼
步骤 3：Agent 分析文档 → 生成基础单元测试
    │   - Agent 读取选中的文件内容
    │   - 自动提取 FR/AC 锚点，生成单元测试场景草稿
    │   - 生成过程中如发现缺失内容（如接口字段未说明），
    │     Agent 在会话中主动提问 → 用户确认后自动补充文件到基础信息包
    │
    ▼
步骤 4：进入场景编排模式
    │   - 单元测试就绪后，在 DAG 画布上编排场景执行顺序
    │   - 设置依赖关系（shared/exclusive）、断点、环境
    │
    ▼
步骤 5：执行与验证
```

**关键设计点**：

- **文件多类型支持**：不限制文件格式，Markdown / Word / Excel / JSON / YAML 均可作为基础信息
- **动态补充机制**：Agent 在分析过程中发现信息不足时，可在会话中向用户提出补充请求（如「需要补充权限矩阵文档吗？」），用户确认后自动将文件加入该场景的基础信息包
- **降低接入门槛**：不再要求外部文件必须遵循 SpecGuard 格式，只要有相关需求/接口/设计内容即可接入进行测试编排
- **基础信息包持久化**：场景与关联文件列表的映射关系需持久化（如 `scenario_meta.yaml` 或数据库），Agent 会话可随时回溯

---

### 4.2 工作模式显式区分

**提出时间**：2026-07-27
**现状**：

当前工作台各功能通过左侧导航栏页面切换（DAG 编辑器、场景编辑器、Agent 对话、执行控制等），但**没有明确的「工作模式」概念**。用户在 AgentChat 页面时，不区分当前是在「场景生成模式」还是「场景调试模式」还是「自由对话模式」。

**问题**：

1. **上下文混淆**：Agent 在不同模式下的行为预期不同（生成场景 vs 修复场景 vs 闲聊查询），但没有模式切换导致 prompt 和工具集不区分
2. **用户认知负担**：新手不清楚当前该做什么操作

**优化方向**：

引入显式的工作模式切换，候选方案：

| 方案 | 形式 | 优点 | 缺点 |
|------|------|------|------|
| **A. 模式按钮** | 页面顶部 Tab/按钮组切换 | 直观，全局可见 | 占用顶部空间 |
| **B. Skill / 斜杠命令** | 聊天框输入 `/generate`、`/debug`、`/chat` | 轻量，符合 AI 产品习惯 | 需要用户记忆命令 |
| **C. 混合模式** | 按钮切换主模式 + 聊天框命令做细分操作 | 兼顾可见性与灵活性 | 实现复杂度稍高 |

**建议的工作模式定义**：

| 模式 | 触发场景 | Agent 行为 |
|------|---------|-----------|
| **场景生成** | 新建场景后进入 | 读取基础信息包 → 分析 → 生成单元测试草稿 |
| **场景编排** | 单元测试就绪后进入 | DAG 画布操作，依赖编排 |
| **场景调试** | 执行失败后进入 | 分析失败原因，修复 YAML |
| **自由对话** | 任意时刻 | 查询 spec/tool/oracle，不写文件 |

**决策待定**：需进一步讨论确定采用哪种方案，以及模式切换是否影响 Agent 的 system prompt 和可用工具集。

---

## 5. 测试计划

_涵盖 delta 导入、计划生成、计划执行编排等。_

（待补充）

---

## 6. 执行引擎

_涵盖 scenario_runner、依赖调度、断点、队列、环境切换等。_

（待补充）

---

## 7. 报告与历史

_涵盖报告生成、运行历史、用例级详情、导出等。_

（待补充）

---

## 8. Agent 智能层

_涵盖 Agent 对话、场景生成、草稿产出、会话管理、模型配置等。_

### 8.1 会话管理缺失：需按用户 + 工作区绑定会话记录

**提出时间**：2026-07-27
**现状**：

当前会话存储结构为 `agent/sessions/{emp_no}/{session_id}.jsonl`，仅按用户工号隔离目录，**未绑定工作区**。

**问题**：

1. **工作区混淆**：同一用户在不同工作区下产生的对话混在同一个目录，无法区分上下文
2. **无会话元数据**：JSONL 文件仅记录消息流，不记录所属工作区、创建时间、主题摘要等元信息
3. **会话列表无筛选**：前端会话列表无法按工作区过滤，admin 视图也只看用户维度

**优化方向**：

- 会话存储路径调整为 `agent/sessions/{emp_no}/{workspace}/{session_id}.jsonl`
- 会话元数据（首条消息或独立 meta 文件）记录 `emp_no`、`workspace`、`created_at`、`summary`
- 前端会话列表支持按工作区筛选
- admin 视图支持按工作区聚合查看

---

### 8.2 大模型配置需可视化 + 热加载

**提出时间**：2026-07-27
**现状**：

当前 LLM 配置在 `agent/llm_client.py` 中通过环境变量读取，进程启动后固定不可变：

```
SG_LLM_BASE_URL  — 网关地址
SG_LLM_API_KEY   — API 密钥
SG_LLM_MODEL     — 模型名称（默认 gpt-4o）
```

**问题**：

1. **无 UI 配置入口**：切换模型/密钥只能改环境变量重启服务，运维不友好
2. **不支持热加载**：`LLMClient.__init__` 一次性读入，运行期间无法更新
3. **无配置样例**：用户不知道该填什么格式的地址和密钥

**优化方向**：

1. **环境设置页面**新增「大模型配置」区块，包含以下字段：

   | 字段 | 说明 | 样例 |
   |------|------|------|
   | 网关地址（base_url） | OpenAI 兼容 API 的基础 URL | `https://api.openai.com` 或内网网关地址 |
   | API 密钥（api_key） | Bearer Token 认证密钥 | `sk-xxxxxxxxxxxx` |
   | 模型 ID（model） | 对话补全接口使用的模型标识 | `gpt-4o`、`qwen-max`、`deepseek-chat` |
   | 超时时间（timeout） | 单次请求超时（秒），默认 120 | `120` |
   | 温度（temperature） | 生成温度，默认 0.7 | `0.7` |

2. **配置热加载**：
   - 前端保存后调用 `POST /api/settings/llm-config` 后端即时生效
   - `LLMClient` 支持 `reload()` 方法或每次 `chat()` 时检测配置版本
   - 配置持久化到 `workbench.db` 或独立 `llm_config.yaml`

3. **配置校验**：保存前发一次轻量探测请求（如发送 `"hi"` 验证连通性），失败则提示用户检查配置

4. **环境变量兼容**：
   - 优先读 UI 配置（数据库/文件）
   - 未配置时回退到环境变量（兼容 CLI 模式）
   - 环境变量存在时 UI 页面显示「当前由环境变量控制」提示

---

### 8.3 会话上下文管理：引入 compaction 机制

**提出时间**：2026-07-27
**借鉴来源**：Pi（compaction 系统）、OpenCode（Context Epochs）

**现状**：

SpecGuard Agent 会话使用 JSONL append-only 存储，`max_turns=12` 熔断。长对话会直接撑满模型上下文窗口，无任何压缩/摘要机制。

**问题**：

1. **上下文溢出**：复杂场景生成（多文件分析 + 多轮工具调用）容易超过 12 轮熔断，用户被迫新建会话从头开始
2. **无历史压缩**：早期轮次的工具调用结果（如大段 spec 文件内容）占据大量 token 但信息密度低
3. **prompt cache 浪费**：每次全量发送历史消息，无法利用 provider 的 prompt caching

**借鉴设计**：

- **Pi 的 compaction**：在安全边界点（如工具调用序列完成后）将历史消息压缩为摘要，保留最近 N 轮原始消息 + 文件操作记录（读了哪些文件、改了哪些文件）
- **OpenCode 的 Context Epochs**：持久化 system context 快照，环境变化时以「时间线 system 消息」注入而非全量重建

**优化方向**：

1. 实现 `SessionCompactor`：超过阈值时自动压缩旧消息为摘要，保留最近 3-5 轮原始上下文
2. 压缩时保留文件操作摘要（读了哪些 spec 文件、写了哪些 draft）
3. 摘要消息标记为 `_type: "compaction_summary"`，加载时作为 system 消息注入

---

### 8.4 工作模式系统：借鉴 OpenCode 的 Mode 机制

**提出时间**：2026-07-27
**借鉴来源**：OpenCode（Build/Plan/Custom Modes）
**关联优化点**：4.2（工作模式显式区分）

**现状**：

SpecGuard Agent 只有一种运行模式，所有工具始终可用，system prompt 固定不变。

**借鉴设计**：

OpenCode 的 Mode 机制非常成熟：
- **Build 模式**：全部工具可用，用于实际开发
- **Plan 模式**：禁用 write/edit/bash，只读分析
- **自定义模式**：通过 Markdown 文件定义（前置元数据 + prompt 正文），可独立配置 model、temperature、可用工具集

```markdown
# .opencode/modes/review.md 示例
---
temperature: 0.1
tools:
  write: false
  edit: false
  bash: false
---
You are in code review mode. Focus on...
```

**优化方向**：

SpecGuard 可定义以下模式（Markdown 文件放在 `agent/modes/`）：

| 模式 | 文件 | 可用工具 | 用途 |
|------|------|---------|------|
| 场景生成 | `generate.md` | read_spec, query_registry, validate, write_draft | 新场景创建 |
| 场景调试 | `debug.md` | read_spec, query_registry, read_report | 分析失败原因 |
| 只读分析 | `analyze.md` | read_spec, query_registry | 规格查询、架构分析 |
| 自由对话 | `chat.md` | 全部工具（只读优先） | 通用问答 |

每个模式独立配置：system prompt 片段、temperature、可用 MCP 工具白名单。

---

### 8.5 Skills 系统：可复用的 Agent 能力声明

**提出时间**：2026-07-27
**借鉴来源**：Pi（SKILL.md + skills.ts）、OpenCode（skills 配置）

**现状**：

SpecGuard 的 Agent 工具（MCP tools）是代码级静态注册的，无法运行时增减。用户无法定义自己的「技能」组合。

**借鉴设计**：

Pi 的 Skills 系统：
- `SKILL.md` 文件包含 YAML 前置元数据（name + description）+ Markdown 正文（详细指令）
- 自动从 `.pi/skills/` 目录加载，注入 system prompt 的 XML 块中
- 支持 `disable-model-invocation`：技能存在但不暴露给模型，仅供显式调用
- 支持从多个目录加载、`.gitignore` 风格的排除规则

**优化方向**：

1. 在 `agent/skills/` 目录放置 `SKILL.md` 文件，每个文件定义一个 SpecGuard 专用技能：
   - `generate-scenario.md`：场景生成完整流程指令
   - `validate-conformance.md`：合规校验流程指令
   - `debug-failure.md`：失败分析流程指令
   - `import-delta.md`：delta 导入流程指令
2. Skills 注入 system prompt，模型根据用户意图自动选择合适技能
3. 前端可展示可用技能列表，用户可手动触发

---

### 8.6 Agent 操作可撤销 + 成本可观测

**提出时间**：2026-07-27
**借鉴来源**：OpenCode（undo/redo）、Pi（cost tracking + TPS 扩展）

**现状**：

SpecGuard Agent 写 draft 后无法撤销；LLM 调用有基础 metrics 记录但无前端展示。

**借鉴设计**：

- **OpenCode undo/redo**：`/undo` 回滚 Agent 的上一次文件修改，`/redo` 重做
- **Pi TPS 扩展**：每次 agent_end 时计算 tokens/sec、input/output/cache_read/cache_write/total，UI 实时展示
- **Pi 成本追踪**：跨会话累计 token 成本，HTML/JSON 导出

**优化方向**：

1. **操作撤销**：Agent 写 draft 前自动备份（`.bak`），支持 `/undo` 回滚上一次写入
2. **成本面板**：前端 AgentChat 页面底部显示实时 TPS、本轮 token 消耗、累计成本
3. **会话导出**：支持将会话导出为 JSON/HTML，便于审计和分享

---

## 9. 草稿管理

_涵盖草稿校验、评审流程、入库（promote）等。_

（待补充）

---

## 10. Spec 校验

_涵盖 format_spec 规范、合规校验器、conformance 门禁等。_

（待补充）

---

## 11. 反馈闭环

_涵盖反馈台账（ledger）、通知（notify）、问题归因等。_

（待补充）

---

## 12. 前端工作台

_涵盖 DAG 画布、场景编辑器、执行控制面板、Monaco YAML 等。_

（待补充）

---

## 13. 开源项目借鉴分析（Pi / OpenCode）

> 本节系统对比两个成熟开源 Agent 项目的设计，提炼对 SpecGuard 有益的架构思路。
> 参考源码：`D:\work\tdm-code\参考资料\pi-main`、`D:\work\tdm-code\参考资料\opencode-dev`

### 13.1 项目概况

| 维度 | Pi | OpenCode |
|------|-----|----------|
| **定位** | 极简可扩展 Agent 框架 | 终端 AI 编码助手 |
| **语言** | TypeScript monorepo | TypeScript monorepo（原 Go） |
| **核心理念** | 最小化内置功能 + 最大化可扩展性 | 功能完备 + 插件化扩展 |
| **包结构** | ai / agent / coding-agent / tui / server / storage / evals | tui / server / plugin / protocol / schema / sdk / session-ui / web |
| **TerminalBench** | 第二名（仅次于 Terminus） | - |

### 13.2 Pi 核心设计提炼

源码路径：`packages/agent/src/harness/`

#### (1) 会话树结构（Session Tree）

Pi 的会话不是线性列表，而是**树结构**：
- 每条消息是树的一个节点，支持分支（branching）
- 用户可在不同分支间导航，回溯到某个节点重新发问
- 分支摘要可带回主干（`branch-summarization.ts`）
- 存储后端可插拔：JSONL / SQLite / Memory（`session/jsonl-storage.ts`、`session/memory-storage.ts`）

**对 SpecGuard 的启示**：当前 JSONL 线性存储无法支持「试错回溯」场景。Agent 生成场景失败后，用户想从中间某轮重新引导，只能新建会话。树结构允许「从第 5 轮分叉重试」。

#### (2) Compaction 系统

`compaction/compaction.ts`（880 行）实现了成熟的上下文压缩：
- 在安全边界点触发压缩（非每轮压缩）
- 压缩时保留**文件操作记录**（读了哪些文件、改了哪些文件）
- 保留最近 N 轮原始消息（`retainedTail`）
- 压缩摘要作为特殊消息类型注入历史
- 不破坏 provider 的 prompt caching（对比 OpenCode 每轮裁剪 40K token 的做法被 Pi 作者批评）

#### (3) Extension 热加载

`.pi/extensions/*.ts` 文件自动加载，**支持热重载**：
- Agent 修改了 extension 文件 → 立即生效，无需重启会话
- Extension 可注册自定义工具、UI 组件、事件处理器
- 示例 `tps.ts`：监听 `agent_start`/`agent_end` 事件，计算 TPS 并通过 `ctx.ui.notify` 展示

**对 SpecGuard 的启示**：MCP 工具目前是 `import` 级静态注册。如果支持运行时加载 `.py` extension 文件，用户可自定义工具而无需改引擎代码。

#### (4) Skills 系统

`harness/skills.ts`（375 行）：
- `SKILL.md` 文件 = YAML 前置（name + description + disable-model-invocation）+ Markdown 正文
- 自动递归扫描目录，支持 `.gitignore` 风格排除
- Skills 注入 system prompt 的 XML 块：`<skill name="..." location="...">...</skill>`
- 模型可见的 skill 列表自动生成，模型按需调用

#### (5) Prompt Templates

`.pi/prompts/*.md` 定义可复用 prompt 模板（如 `cl.md`=changelog、`pr.md`=pull request、`sa.md`=system architecture），支持参数插值，通过命令显式调用。

#### (6) 成本可观测性

- 每条 assistant 消息记录 `usage`（input/output/cacheRead/cacheWrite/totalTokens）
- `scripts/cost.ts` 计算跨会话成本
- `scripts/session-context-stats.mjs` 分析上下文构成
- HTML/JSON 会话导出

### 13.3 OpenCode 核心设计提炼

源码路径：`packages/` + `specs/v2/`

#### (1) Mode 系统（最值得借鉴）

`specs/v2/` + 文档 `open-code.ai/en/docs/modes`：
- **Build**：全部工具可用（write/edit/bash/read/grep/glob/list/patch/todowrite/webfetch）
- **Plan**：禁用 write/edit/patch/bash，只读分析
- **自定义模式**：Markdown 文件定义（前置 YAML 元数据 + 正文 prompt）
  ```markdown
  ---
  model: anthropic/claude-sonnet-4-20250514
  temperature: 0.1
  tools:
    write: false
    edit: false
    bash: false
  ---
  You are in code review mode...
  ```
- 模式切换：Tab 键，会话中途可切换
- 每个模式可独立配置 model / temperature / tools / prompt

#### (2) Plugin 事件钩子系统

`opencode.ai/docs/plugins/`：
- 插件是 JS/TS 模块，导出返回 hooks 对象的函数
- 事件类型覆盖全生命周期：
  - 工具级：`tool.execute.before` / `tool.execute.after`
  - 会话级：`session.created` / `session.idle` / `session.compacted`
  - 文件级：`file.edited` / `file.watcher.updated`
  - 权限级：`permission.asked` / `permission.replied`
  - TUI 级：`tui.prompt.append` / `tui.command.execute`
- 示例：`.env` 文件保护插件（read 前拦截）、环境变量注入插件（shell.env 钩子）

#### (3) Provider 策略管控

`specs/v2/provider-policy.md`：
- 配置与策略分离：`providers` 描述端点，`policies` 控制是否允许使用
- 策略语法：`{ effect: "allow"|"deny", action: "provider.use", resource: "openai" }`
- 通配符匹配：`company-*` 匹配 `company-us`、`company-eu`
- 优先级：用户策略 > 仓库策略（后续支持组织策略）

#### (4) References + Instructions

`specs/v2/config.md`：
- **References**：命名外部上下文引用（本地路径或 Git 仓库），可按 `@alias/path` 引用
  ```json
  { "references": { "design-system": { "path": "../ui-library" } } }
  ```
- **Instructions**：环境指令源（文件/glob/URL），自动注入模型上下文
  ```json
  { "instructions": ["CONTRIBUTING.md", "docs/guidelines.md"] }
  ```

**对 SpecGuard 的启示**：References 机制可直接映射到优化点 4.1 的「基础信息包」——每个场景关联一组命名文件引用，Agent 通过 `@alias` 引用。

#### (5) Undo/Redo

- `/undo` 回滚 Agent 上一次修改，恢复原始消息重新编辑
- `/redo` 重做
- 基于操作日志而非 Git diff

### 13.4 SpecGuard 差距矩阵

| 能力维度 | SpecGuard 现状 | Pi | OpenCode | 差距 |
|---------|--------------|-----|----------|------|
| 会话存储 | JSONL 线性 | 树结构 + 可插拔后端 | Durable inbox + Context Epoch | 缺少分支/压缩 |
| 上下文管理 | max_turns=12 熔断 | Compaction + 文件操作保留 | Context Epoch + 压缩 | 无压缩机制 |
| 模式系统 | 单一模式 | 无内置模式 | Build/Plan/Custom + Markdown 定义 | 完全缺失 → 见 8.4 |
| 工具注册 | Python import 静态 | Extension 热加载 | Plugin 事件钩子 + 自定义工具 | 无法运行时扩展 |
| Skills | 无 | SKILL.md + XML 注入 | skills 配置源 | 完全缺失 → 见 8.5 |
| 模型配置 | 环境变量一次性 | 多 provider + 会话内切换 | Provider catalog + policy | 见 8.2 |
| 成本可观测 | JSONL metrics 无 UI | TPS 实时 + 跨会话成本 | - | 见 8.6 |
| 操作撤销 | 无 | - | undo/redo | 见 8.6 |
| 外部引用 | 无 | - | References @alias | 可借鉴 → 见 4.1 |
| 会话导出 | 无 | HTML/JSON | share 链接 | 见 8.6 |

### 13.5 借鉴优先级排序

| 优先级 | 借鉴点 | 来源 | 关联优化点 | 理由 |
|--------|--------|------|-----------|------|
| **P0** | Mode 系统 | OpenCode | 8.4 / 4.2 | 直接解决工作模式混淆，Markdown 定义轻量易实现 |
| **P0** | 模型配置可视化 | OpenCode | 8.2 | 当前无法切换模型是硬伤 |
| **P1** | Compaction 机制 | Pi | 8.3 | 长对话熔断是高频痛点 |
| **P1** | Skills 系统 | Pi | 8.5 | 将 system prompt 中硬编码的流程指令外置为可维护文件 |
| **P2** | 成本可观测 | Pi | 8.6 | 运营成本管控需要 |
| **P2** | 操作撤销 | OpenCode | 8.6 | 用户体验提升 |
| **P2** | References 机制 | OpenCode | 4.1 | 基础信息包的命名引用 |
| **P3** | 会话树结构 | Pi | 8.1 | 分支回溯是高级需求，先解决绑定工作区 |
| **P3** | Extension 热加载 | Pi | 新 | 运行时工具扩展，依赖较重 |

---

## 升级计划（待定）

验收期结束后，根据本表中的优化点按优先级与模块依赖关系规划升级批次：

| 批次 | 模块范围 | 预计内容 | 状态 |
|------|---------|---------|------|
| V1 | 待定 | 待定 | 规划中 |
| V2 | 待定 | 待定 | 规划中 |

---

_本文档随验收进展持续更新，每次评审后同步升级计划。_
