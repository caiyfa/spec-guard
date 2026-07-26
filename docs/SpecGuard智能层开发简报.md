# SpecGuard 智能层开发简报

> **版本**：1.0 | **日期**：2026-07-26 | **提交**：`c90d19e` | **状态**：M0-M5 全量交付

---

## 一、项目概述

SpecGuard 智能层是契约驱动测试引擎 SpecGuard 的上层能力扩展，在引擎格式 2.0 冻结的基础上，构建了 **MCP 工具层 → 薄 Harness → 可视化工作台 → 双反馈循环** 的完整链路。

**核心目标**：让 AI Agent 在 SpecGuard 的三道闸（人工评审 → 格式校验 → 发布门禁）约束下，安全地参与场景生成、校验、归因与反哺闭环。

---

## 二、里程碑交付总览

| 里程碑 | 名称 | 交付内容 | 文件数 | 测试 |
|--------|------|----------|--------|------|
| **M0** | Spec 标准定义 | schema / anchors / conformance / workspace / signature | 6 模块 | 22 项 |
| **M1** | MCP 工具层 | server 骨架 + 5 组 10 个工具 | 9 文件 | 17 项 |
| **M2** | 薄 Harness + CLI | llm_client / runtime / session / cli / prompts | 7 文件 | 12 项 |
| **M3** | Workbench 集成 | agent/workspace/feedback 路由 + 5 个前端页面 | 8 文件 | — |
| **M4** | 循环 B 工具 | signature 内容签名 + attribution 归因 | 2 文件 | 8 项 |
| **M5** | 反哺闭环 | ledger 台账 + notify 飞书通知 | 2 文件 | 11 项 |
| **补齐** | covers 执行闸 + UI | runs.py covers 前置闸 + 前端 3 页面 | 3 文件 | — |

**合计**：56 文件变更，6774 行新增，195 项测试全绿（1 项 SKIP 为预期）。

---

## 三、架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SpecGuard 智能层架构                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  MCP 工具层   │◄──│  薄 Harness  │◄──│  可视化工作台         │  │
│  │  (M1)        │    │  (M2)        │    │  (M3)                │  │
│  │              │    │              │    │                      │  │
│  │ 10 个工具:   │    │ LLM Client   │    │ Frontend (React)     │  │
│  │ • spec_reader│    │ Runtime 循环 │    │ • AgentChat          │  │
│  │ • scenario_*  │    │ Session 持久 │    │ • SpecCenter         │  │
│  │ • registry_*  │    │ Events 事件  │    │ • WorkspaceSettings  │  │
│  │ • draft_*    │    │ CLI 入口    │    │ • Attribution         │  │
│  │ • validator  │    │              │    │ • Feedback           │  │
│  │ • attribution│    │              │    │                      │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │                   │                       │              │
│         ▼                   ▼                       ▼              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    specstd 标准定义 (M0)                     │  │
│  │  schema → anchors → conformance → workspace → signature     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────┐    ┌─────────────────────┐                │
│  │   循环 A (正向)      │    │   循环 B (反向)      │                │
│  │   Spec → 场景 → 执行 │    │   执行 → 归因 → 反哺 │                │
│  │   (M1+M2+M3)        │    │   (M4+M5)           │                │
│  └─────────────────────┘    └─────────────────────┘                │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    引擎冻结层 (engine/)                      │  │
│  │  scenario_runner / dependency_graph / tool_registry / ...   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 双反馈循环

| 循环 | 方向 | 链路 | 实现里程碑 |
|------|------|------|-----------|
| **循环 A（正向）** | Spec → 测试 | Spec 文档 → MCP 读取 → Agent 生成场景 → 草稿 → 格式校验 → 评审 → 入库 | M0 + M1 + M2 + M3 |
| **循环 B（反向）** | 测试 → Spec | 执行报告 → 归因分析 → 内容签名 → SPQ 台账 → 飞书通知 → 研发修复 | M4 + M5 |

---

## 四、各里程碑详情

### M0：Spec 标准定义包（specstd/）

**定位**：Spec 仓库的合规标准与工作区管理，是 Agent 安全操作 Spec 的基础设施。

| 模块 | 文件 | 职责 |
|------|------|------|
| schema | [specstd/schema.py](file:///d:/work/tdm-code/specguard/specstd/schema.py) | 目录结构常量 / 锚点正则 / manifest schema / Finding & Report 数据类 |
| anchors | [specstd/anchors.py](file:///d:/work/tdm-code/specguard/specstd/anchors.py) | spec.md FR 锚点解析 / delta-spec.md 三段式解析 / covers YAML 提取 |
| conformance | [specstd/conformance.py](file:///d:/work/tdm-code/specguard/specstd/conformance.py) | V1-V6 原生重写（ANCHOR/MODIFY_FULL/TRACE/MANIFEST/STRUCT/AGENTS/API_LINT） |
| workspace | [specstd/workspace.py](file:///d:/work/tdm-code/specguard/specstd/workspace.py) | 工作区注册（local/git）/ 激活切换 / 合规校验 / 文件读取守卫 |
| signature | [specstd/signature.py](file:///d:/work/tdm-code/specguard/specstd/signature.py) | FR 级内容签名（sha256-12）/ 跨版本 diff |

**关键设计**：
- 工作区注册表 `specstd/workspaces/registry.yaml` 不入 git（含路径信息）
- git 型工作区克隆到 `specstd/workspaces/_clones/`，支持 `pull` 拉取更新
- `safe_resolve()` 路径守卫防止越界读取

### M1：MCP 工具层（mcp_server/）

**定位**：标准化工具接口，供 Agent 和外部 MCP 客户端调用。

| 工具组 | 工具 | 功能 |
|--------|------|------|
| spec_reader | read_spec / list_spec_files | 读取 Spec 文档内容 / 列出文件树（含 delta 标记） |
| scenario_tools | list_scenarios / read_scenario / next_id | 场景列表 / 单场景读取 / 下一个可用 ID |
| registry_query | query_registry | 查询 tool / oracle / step 元数据 |
| draft_writer | write_draft | 草稿写入（路径守卫：仅 drafts/ 目录，禁止覆盖） |
| validator | validate | YAML 格式校验 + 10 条门禁规则 + covers 关联完整性 |
| attribution | read_run_report / db_evidence | 运行报告读取 / DB 证据收集（循环 B） |

**安全约束**：
- `write_draft` 强制路径前缀 `drafts/`，禁止覆盖已有文件（除非 `overwrite=True`）
- `validate` 检查 covers 引用的 FR ID 是否在当前工作区 spec.md 中存在
- `read_spec` / `read_file` 通过 `safe_resolve()` 防止路径越界

### M2：薄 Harness + CLI（agent/）

**定位**：LLM 与工具之间的编排层，实现 Agent 自主循环。

| 模块 | 文件 | 职责 |
|------|------|------|
| llm_client | [agent/llm_client.py](file:///d:/work/tdm-code/specguard/agent/llm_client.py) | LLM 网关调用 / 计量统计 / 响应缓存 / 退避重试 |
| runtime | [agent/runtime.py](file:///d:/work/tdm-code/specguard/agent/runtime.py) | 核心循环：LLM → tool_calls → 执行 → 结果回填 → stop 判定 |
| session | [agent/session.py](file:///d:/work/tdm-code/specguard/agent/session.py) | JSONL 会话持久化（append-only，支持历史回放） |
| events | [agent/events.py](file:///d:/work/tdm-code/specguard/agent/events.py) | 事件总线（tool_call / tool_result / llm_response / session_end） |
| cli | [agent/cli.py](file:///d:/work/tdm-code/specguard/agent/cli.py) | 命令行入口（`python -m agent.cli "生成场景 PP-RC-008"`） |
| prompts | [agent/prompts/system.md.j2](file:///d:/work/tdm-code/specguard/agent/prompts/system.md.j2) | 系统提示模板（Jinja2，注入工具清单 + 格式规范摘要） |

**核心循环伪代码**：
```
while not should_stop:
    response = llm_client.chat(messages, tools=tool_schemas)
    if response.has_tool_calls:
        for call in response.tool_calls:
            result = dispatch_tool(call.name, call.arguments)
            messages.append(tool_result(call.id, result))
    else:
        break  # LLM 给出最终回答
```

### M3：Workbench 集成

**定位**：将 Agent 能力嵌入可视化工作台，实现人机协作。

**后端路由**：

| 路由 | 文件 | 端点 |
|------|------|------|
| Agent | [routers/agent.py](file:///d:/work/tdm-code/specguard/workbench/backend/routers/agent.py) | `POST /api/agent/chat`（同步）/ `GET /api/agent/sessions` / `GET /api/agent/sessions/{id}` |
| Workspace | [routers/workspace.py](file:///d:/work/tdm-code/specguard/workbench/backend/routers/workspace.py) | 工作区 CRUD + 合规校验 + Spec 文件树 + 文件读取 |
| Feedback | [routers/feedback.py](file:///d:/work/tdm-code/specguard/workbench/backend/routers/feedback.py) | 台账 CRUD + 状态流转 + webhook 注册/注销/发送 |

**前端页面**：

| 页面 | 文件 | 功能 |
|------|------|------|
| Agent 对话 | [AgentChat.tsx](file:///d:/work/tdm-code/specguard/workbench/frontend/src/pages/AgentChat.tsx) | 对话式场景生成，展示 tool_calls 过程 |
| Spec 文档中心 | [SpecCenter.tsx](file:///d:/work/tdm-code/specguard/workbench/frontend/src/pages/SpecCenter.tsx) | 浏览激活工作区的 Spec 文件树 |
| 工作区管理 | [WorkspaceSettings.tsx](file:///d:/work/tdm-code/specguard/workbench/frontend/src/pages/WorkspaceSettings.tsx) | 注册/激活/注销工作区 + 合规报告展示 |
| 失败归因 | [Attribution.tsx](file:///d:/work/tdm-code/specguard/workbench/frontend/src/pages/Attribution.tsx) | 运行报告分析 + 失败场景 + 断言差异 + BUG 单草稿 |
| 反哺闭环 | [Feedback.tsx](file:///d:/work/tdm-code/specguard/workbench/frontend/src/pages/Feedback.tsx) | SPQ 台账管理 + 飞书 webhook 通知配置 |

**covers 执行闸**（集成于 [runs.py](file:///d:/work/tdm-code/specguard/workbench/backend/routers/runs.py)）：
- 触发执行前调用 `_check_covers()` 校验全部场景的 covers 是否可解析为有效 FR ID
- 校验未通过返回 HTTP 422，禁止执行
- `skip_covers_check=True` 可跳过（engine_modes 自测用）

### M4：循环 B 工具（归因 + 内容签名）

**定位**：从执行结果反推 Spec 问题，形成"测试 → Spec"的反馈闭环。

| 模块 | 文件 | 功能 |
|------|------|------|
| signature | [specstd/signature.py](file:///d:/work/tdm-code/specguard/specstd/signature.py) | FR 级内容签名（sha256-12），跨版本 diff 检测变更 |
| attribution | [mcp_server/tools/attribution.py](file:///d:/work/tdm-code/specguard/mcp_server/tools/attribution.py) | 读取运行报告 JSON / 提取失败场景 / 收集 DB 证据 |

### M5：反哺闭环 + 飞书通知（feedback/）

**定位**：将归因结果沉淀为可追踪的 SPQ 台账，并通过飞书 webhook 通知相关人。

| 模块 | 文件 | 功能 |
|------|------|------|
| ledger | [feedback/ledger.py](file:///d:/work/tdm-code/specguard/feedback/ledger.py) | SPQ 台账（SPQ-001~），状态机 pending → in_progress → closed |
| notify | [feedback/notify.py](file:///d:/work/tdm-code/specguard/feedback/notify.py) | webhook 注册表 / URL 掩码存储 / fnmatch 场景匹配 / 仅出站通知 |

**安全约束**：
- webhook URL 掩码存储（如 `https://open.feishu.cn/a3f***`）
- 通知消息只含 ID / 结论 / 链接，不泄露敏感信息
- 持久化文件 `ledger.json` / `registry.json` 不入 git

---

## 五、测试验证

### 测试矩阵

| 测试套件 | 测试数 | 结果 | 说明 |
|----------|--------|------|------|
| test_suites/test_engine_modes.py | 39 | ✅ 全绿 | 引擎离线自测（shared/exclusive/teardown/插值/poll/random） |
| test_engine/ | 62 | ✅ 全绿 | 引擎组件单测（call/python/deps_editor/versioning/tool_and_deps） |
| test_specstd/ | 80+14 | ✅ 全绿 | specstd + MCP + Agent + feedback 全覆盖 |
| test_suites/test_person_profile.py | 14 | ✅ 13 绿 1 SKIP | SKIP 为预期（restricted 账号未配置） |
| **合计** | **195+14** | **✅ 全绿** | |

### 发布门禁

```
python release_check.py
→ 发布检查: PASS（可归档）
```

### 前端编译

```
tsc -b && vite build
→ ✓ 1216 modules transformed
→ ✓ built in 17.56s
```

### 浏览器验证

通过 browser-use 工具验证：
- Dashboard 主页面加载正常，侧边栏 12 项导航全部可见
- 工作区管理页：注册表单渲染正常（local/git 切换）
- 反哺闭环页：台账 Tab + 通知配置 Tab 正常切换
- 失败归因页：运行历史加载 + 报告分析正常（15 场景，0 失败）
- API 端点全部返回正确响应

---

## 六、文件清单

### 新增文件（42 个）

```
specstd/
  __init__.py          # 包入口
  schema.py             # 标准定义（282 行）
  anchors.py            # 锚点解析（314 行）
  conformance.py        # 合规校验器（541 行）
  workspace.py          # 工作区管理（445 行）
  signature.py          # 内容签名（179 行）
  workspaces/.gitignore  # 注册表排除

mcp_server/
  __init__.py
  server.py             # MCP server 骨架（94 行）
  tools/
    __init__.py
    spec_reader.py      # Spec 读取工具（91 行）
    scenario_tools.py   # 场景工具（124 行）
    registry_query.py   # 注册表查询（78 行）
    draft_writer.py     # 草稿写入（76 行）
    validator.py        # 校验工具（131 行）
    attribution.py      # 归因工具（148 行）

agent/
  __init__.py
  llm_client.py         # LLM 客户端（148 行）
  runtime.py            # 运行时循环（196 行）
  session.py            # 会话持久化（70 行）
  events.py             # 事件总线（33 行）
  cli.py                # CLI 入口（90 行）
  prompts/system.md.j2  # 系统提示模板

feedback/
  __init__.py
  ledger.py             # 台账（96 行）
  notify.py             # 通知（124 行）

test_specstd/
  __init__.py
  conftest.py
  helpers.py
  test_conformance.py
  test_mcp_server.py
  test_agent.py
  test_m4_m5.py

workbench/backend/routers/
  agent.py              # Agent 路由（143 行）
  workspace.py          # 工作区路由（173 行）
  feedback.py           # 反哺路由（141 行）

workbench/frontend/src/pages/
  AgentChat.tsx         # Agent 对话页（181 行）
  SpecCenter.tsx        # Spec 文档中心（130 行）
  WorkspaceSettings.tsx # 工作区管理页（175 行）
  Attribution.tsx       # 失败归因页（204 行）
  Feedback.tsx          # 反哺闭环页（214 行）

docs/
  SpecGuard智能层开发计划-M0至M5.md
```

### 修改文件（14 个）

| 文件 | 变更说明 |
|------|---------|
| .gitignore | 新增 specstd/agent/feedback 排除规则 |
| start-workbench.ps1 | 适配新路由 |
| test_suites/test_engine_modes.py | 新增 random/poll/fn 测试 |
| test_suites/test_person_profile.py | 路径引用修正 |
| workbench/backend/main.py | 注册 agent/workspace/feedback 路由 |
| workbench/backend/routers/reference.py | 引用修正 |
| workbench/backend/routers/runs.py | 新增 covers 校验前置闸 |
| workbench/backend/routers/spec_validation.py | 引用修正 |
| workbench/backend/services/format_spec.py | 引用修正 |
| workbench/backend/services/plan_store.py | 遗留引用替换 |
| workbench/backend/services/runner.py | 引用修正 |
| workbench/backend/services/spec_validator.py | 原生重写（specstd 集成） |
| workbench/frontend/src/App.tsx | 新增 5 个页面路由 |
| workbench/frontend/src/api.ts | 新增 workspace/agent API 客户端 |

---

## 七、安全设计要点

| 关注点 | 措施 |
|--------|------|
| Agent 产物入库 | 三道闸：人工评审 → 格式校验（validator）→ 发布门禁（release_check） |
| 草稿写入 | `drafts/` 目录守卫，禁止覆盖，禁止越界 |
| Spec 文件读取 | `safe_resolve()` 路径守卫，仅限激活工作区根目录 |
| covers 完整性 | 执行触发前置闸，未通过禁止执行（HTTP 422） |
| webhook URL | 掩码存储（`a3f***`），列表接口不暴露完整 URL |
| 通知内容 | 仅含 ID / 结论 / 链接，不泄露敏感数据 |
| 凭据 | 环境配置 + devops 凭据回退，不硬编码 |
| 持久化文件 | `ledger.json` / `registry.json` / `sessions/*.jsonl` 不入 git |

---

## 八、如何使用

### 启动工作台

```powershell
pwsh start-workbench.ps1    # 后端 :9100 + 前端 :5173
```

### 注册 Spec 工作区

1. 打开工作台 → 侧边栏「🗂 工作区」
2. 选择「本地文件夹」或「Git 仓库」
3. 输入名称和路径/URL → 点击注册
4. 注册时自动执行合规校验（V1-V6）

### Agent 生成场景

1. 打开侧边栏「🤖 Agent 生成」
2. 输入指令（如「生成 PP-RC-008：切片模式查询历史盘点快照」）
3. Agent 读取 Spec → 生成场景草稿 → 自动校验
4. 草稿写入 `drafts/`，人工评审通过后移入 `scenarios/`

### 失败归因

1. 打开侧边栏「🔍 失败归因」
2. 选择或输入运行 ID
3. 查看失败场景的断言差异与根因分类
4. 勾选失败场景生成 BUG 单草稿

### 反哺闭环

1. 打开侧边栏「🔄 反哺闭环」
2. 台账 Tab：创建 SPQ 条目，流转状态（pending → in_progress → closed）
3. 通知配置 Tab：注册飞书 webhook，选择事件类型（fail/drift/skip）

### 运行测试

```powershell
# 引擎离线自测
python -m pytest -k engine_modes -v

# 引擎组件单测
python -m pytest test_engine -v

# 智能层全量测试
python -m pytest test_specstd -v

# 发布门禁
python release_check.py
```

---

## 九、后续展望

| 方向 | 说明 |
|------|------|
| Agent 流式对话 | WebSocket 实时推送 tool_calls 过程（当前为同步） |
| 多系统接入 | 按 `systems/{system}/` 契约接入更多被测系统 |
| 归因自动化 | 从执行报告自动生成 SPQ 台账条目（当前需手动创建） |
| Spec 变更检测 | signature 跨版本 diff 自动触发影响面分析 |
| 工作区 git push | Agent 修复 Spec 后自动提交 PR（当前仅本地草稿） |

---

> **文档版本**：1.0 | **维护者**：SpecGuard Team | **关联文档**：[SpecGuard-Agent架构设计-MCP工具层与薄Harness.md](file:///d:/work/tdm-code/specguard/docs/SpecGuard-Agent架构设计-MCP工具层与薄Harness.md)
