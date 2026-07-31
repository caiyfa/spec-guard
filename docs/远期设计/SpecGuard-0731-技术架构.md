# SpecGuard 技术架构

> 版本：2026-07-31 快照 · 基于代码实测整理（非设计稿）
> 定位：契约驱动的后端场景测试引擎 + 可视化工作台，独立仓库独立演进，不依附任何业务后端项目。

---

## 1. 总体分层

```
┌─────────────────────────────────────────────────────────────────┐
│ L4 交互层  workbench/                                            │
│   React 18 + Vite 5 前端 (:5173) ── FastAPI 后端 (:9100, RBAC)   │
├─────────────────────────────────────────────────────────────────┤
│ L3 智能层  agent/ + mcp_server/                                  │
│   薄 Harness（modes/skills 热加载） ── MCP stdio 工具层（24 工具）│
├─────────────────────────────────────────────────────────────────┤
│ L2 标准层  specstd/                                              │
│   Spec 规范单一事实源（schema/锚点/合规/指纹/多工作区）           │
├─────────────────────────────────────────────────────────────────┤
│ L1 引擎层  engine/  【冻结层 · 语义改动需评审】                   │
│   场景执行器 + DAG 依赖调度 + 契约版本仲裁 + 报告产物             │
├─────────────────────────────────────────────────────────────────┤
│ L0 数据层  scenarios/ + systems/{system}/ + feedback/            │
│   场景库（双层 YAML）+ 被测系统适配包 + 反哺闭环台账              │
└─────────────────────────────────────────────────────────────────┘
```

核心设计原则：

- **被测系统解耦**：引擎与业务系统通过 `systems/{system}/` 适配包契约接入，当前已接入 `systems/tdm`（干部盘点）；接入新系统 = 新增子包，引擎层零改动。
- **确定性校验**：一切校验走确定性校验器（release_check / dependency_graph / specstd.conformance），不让 LLM 或人工目测替代。
- **Agent 产物三道闸**：人工评审 → 格式校验 → 发布门禁，才能进入 `scenarios/`。

---

## 2. L1 引擎层（`engine/`，冻结层）

| 模块 | 职责 |
|------|------|
| `scenario_runner.py`（~1100 行） | 执行器：flow/verify 双段执行、`{{a.b.c}}` 变量插值（类型保留）、shared/exclusive 依赖调度、teardown、SKIP/BLOCKED 诚实结果语义 |
| `dependency_graph.py` | DAG：拓扑排序 / 环检测 / 契约版本仲裁（DRIFT/ORPHANED verdict） |
| `scenario_loader.py` | 场景 YAML 加载与解析 |
| `tool_registry.py` | tool 元数据注册表——新 tool 在适配包 `steps.py` 声明，模块导入时注册，**语法层零变更** |
| `versioning.py` | 契约版本：`^X` / `X.Y` 精确匹配；契约指纹 sha256-12，T6 校验（指纹变更但 version 未 bump → ERROR） |
| `db_oracle.py` | 只读 DB 客户端（SELECT-only 硬守卫），供 DB 校对断言器使用 |
| `http_client.py` / `token_provider.py` | HTTP 调用与 SSO token 获取 |
| `report_writer.py` / `execution_record.py` | 执行报告与记录产物（落各工作区 `.specguard/reports/`） |
| `registry.py` | 步骤类型 / 断言器 / 提供者注册表 |

**场景格式 2.0（已冻结）**：3 原语 + tool 信封；场景携带 `version: MAJOR.MINOR` 契约版本（0.x = 活跃 delta 快照期）；`depends_on` 支持版本期望与 `optional` 可选依赖。格式规范的**唯一权威**是 `workbench/backend/services/format_spec.py`（由引擎注册表动态生成，当前 2.0.0），文档快照仅是导出。

**场景双层 YAML**：
- doc 层（given/when/then + `covers: [FR-xxx]`）给人看；
- flow/verify 层给机器跑；
- `covers` 是场景 ↔ Spec FR/AC 锚点的强制关联，是 DAG 编排的前置铁律。

---

## 3. L2 标准层（`specstd/`，SPECSTD_VERSION = 1.0）

"定标准的代码化"，被引擎之外的智能层共用：

| 模块 | 职责 |
|------|------|
| `schema.py` | v1 规范单一事实源：目录/文件常量、锚点正则、合规规则（RuleName/RuleLevel）、ConformanceReport、DeltaOperation/ParsedDeltaSpec |
| `anchors.py` | FR/AC 锚点解析 |
| `conformance.py` | 合规校验器（纯读，无副作用） |
| `signature.py` | 内容指纹（delta diff 与契约指纹的基础） |
| `workspace.py` | **多工作区**：注册表 + git 克隆 + 激活切换；通过 contextvar 向下游（agent/MCP/covers）全链路透传。物理布局在 `specstd/workspaces/`（registry.yaml / _clones / _anchors，不入 git） |

工作区透传链路：前端 `X-SG-Workspace` header → specstd contextvar → agent / MCP / covers 全链路。各工作区的 `.specguard/` 目录承载 drafts / plans / reports / info_packs。

---

## 4. L3 智能层

### 4.1 薄 Harness（`agent/`）

- `runtime.py`（~420 行）：Agent 运行时，tool 分发 + 会话循环。
- `session.py`：会话管理，多用户按工号隔离（`agent/sessions/{emp}/`，.jsonl 不入 git）。
- `llm_client.py`：LLM 客户端，**DB 驱动配置热加载**。
- `compactor.py`：长对话压缩，超限自动摘要早期轮次。
- `mode_loader.py` + `modes/`：工作模式（generate / debug / analyze / audit / chat），30s TTL 热加载。
- `skill_loader.py` + `skills/`：技能（generate-scenario / validate-conformance / debug-failure），正文注入 system prompt 的 `<skills>` XML 块。
- `prompts/system.md.j2`：system prompt Jinja 模板。
- `cli.py`：POC 独立验证入口（`python -m agent.cli`，支持 `--mock` / `--session`）。

modes/skills 均为 `---` YAML frontmatter（temperature/tools/description/trigger）+ Markdown 正文，新增文件**无需重启**。

### 4.2 MCP 工具层（`mcp_server/`，stdio）

`server.py` 启动 stdio server，注册 8 个工具模块、共 **24 个工具**，Agent（及 Qoder 等宿主）通过工具操作仓库：

| 模块 | 工具 |
|------|------|
| spec_reader | read_spec / list_spec_files / read_run_report |
| scenario_tools | read_scenario / list_scenarios / next_scenario_id / run_scenario / check_dag / edit_dependency / db_evidence |
| registry_query | query_registry |
| draft_writer | write_draft / promote_draft / promote_drafts / undo_draft |
| validator | validate |
| attribution | report_vulnerability |
| audit | write_audit_report |
| meta | switch_mode / todo_write / add_to_info_pack / read_info_pack / list_info_pack_artifacts |

其中 `tools/live_registry.py` 是运行时 tool 注册器（导入时注册 engine 适配包）；`info_pack.py` 为基础信息包读写（尚未挂载到 server.TOOL_MODULES）。约束：校验类工具必须纯读，禁止副作用。

---

## 5. L0 数据层

### 5.1 场景库（`scenarios/`）

按模块分目录、自动发现，目录含 `_suite.yaml` 声明模块元信息：

```
scenarios/
├── employee/person-profile/        # 全景档案
├── evaluation/eval-360/            # 360 评价
├── inventory/grid-placement/       # 九宫格落位
├── inventory/inventory-session/    # 盘点会话
├── inventory/smart-tag/            # 智能标签
└── system-settings/tag-library/    # 标签库
```

### 5.2 被测系统适配包（`systems/{system}/`）

接入契约（5 项）：`config/env.{env}.yaml`（网关/账号/DB，`${VAR:default}` 占位符）→ `config.py` 暴露 `load_env()` → `steps.py` 声明系统专属 tool → `oracles.py` 注册 DB 校对断言器 → 运行时 `SPEC_GUARD_SYSTEM={system}` 指定（默认 tdm）。

`systems/tdm/` 现状：`env.sit.yaml` + `emp-pool.yaml` 工号池；`steps.py` 提供 select_emp / fetch_permission 等 4 个 tool；`oracles.py` 注册快照冻结、权限过滤等 8+ 断言器；配套 `emp_pool.py` / `queries.py` / `hr_center_oracle.py`。

### 5.3 反哺闭环（`feedback/`）

- `ledger.py`：SPQ 台账状态机（pending → in_progress → closed）。
- `notify.py`：通知出口。

### 5.4 契约基线

`contracts_baseline.json`：场景 ID → {fingerprint, version}，T6 校验与发布门禁的比对基准。

---

## 6. L4 工作台（`workbench/`）

### 6.1 后端（FastAPI，:9100）

`main.py` 挂载 **15 个 router**（auth 之外多数挂 `Depends(get_current_user)` 做 RBAC）：

auth / users / scenarios / runs / reference / plans / spec_validation / agent / workspace / feedback / drafts / settings / notify / schedules

`services/`（20 个）要点：

- `auth.py`（会话 + RBAC）、`user_store.py`、`crypto.py`：认证与多用户。`SG_AUTH_MODE=uac|mock`（生产 uac / 开发 mock）；`SG_ADMIN_ACCOUNTS` 预置管理员。
- `runner.py` + `plan_executor.py` + `scheduler.py`：场景执行、计划执行、定时调度。
- `scenario_store.py` / `plan_store.py` / `scenario_meta.py`：场景与计划持久化。
- `format_spec.py`：**格式规范唯一权威**（动态生成，引擎能力变更三同步的强制点：更新规范 → 递增版本号 → 更新 contracts_baseline.json）。
- `deps_editor.py`：YAML 文本外科手术（禁止 js-yaml round-trip，保中文注释）。
- `spec_validator.py` / `covers_gate.py` / `spec_baseline.py`：Spec 合规校验、covers 关联门禁、基线。
- `draft_promote.py`：草稿晋升通道。
- `llm_config.py` / `model_config.py` / `settings_store.py` / `notify_config.py`：配置存储（DB 驱动热加载）。
- `info_pack_freshness.py` / `file_preview.py`：信息包新鲜度、文件预览。
- 数据落盘：`workbench/backend/data/workbench.db`（SQLite，勿提交）。

### 6.2 前端（React 18 + Vite 5 + TS 严格模式，:5173）

16 个页面：Dashboard / Scenarios / DagEditor / RunControl / History / Drafts / AgentChat / SpecValidation / WorkspaceCenter / Feedback / Attribution / Schedules / NotifyConfigs / Settings / AdminUsers / Login。

关键组件与技术选型：DAG 画布用 **elkjs**（懒加载）布局；YAML 编辑用 **Monaco**；`useRunStream` hook 承接执行流式输出；WorkspaceSelector 注入 `X-SG-Workspace`。

---

## 7. 关键技术机制

### 7.1 变量插值
`{{a.b.c}}` 点号路径，类型保留；`env.*` 来自环境配置，其余来自 `save` 变量或上游场景输出。

### 7.2 依赖语义（shared / exclusive / teardown）
- shared：共享资源场景可并发复用；
- exclusive：独占资源互斥调度；
- 上游失败 → 下游 BLOCKED；测试数据缺失/账号未配置 → SKIP；**绝不把环境问题报成 FAIL**（诚实结果）。

### 7.3 契约版本仲裁
`depends_on` 声明版本期望（`^X` 兼容 / `X.Y` 精确 / `optional`）；dependency_graph 产出 DRIFT（版本漂移）/ ORPHANED（依赖缺失）verdict；`release_check.py` 做格式 / 环 / 契约指纹三项门禁，全 PASS 才允许入库。

### 7.4 双反馈循环
- 循环 A（执行侧）：场景执行 → 报告 → 问题归因（attribution）→ SPQ 台账；
- 循环 B（Spec 侧）：delta spec 导入 → 生成测试计划（**计划只能由 delta 导入生成，禁止手动新建**）→ 场景补齐 → covers 门禁。

### 7.5 多用户与多工作区
RBAC（M6-M8 已落地）+ 工作区隔离；SSO 走 UAC（生产单端口 :9100，`serve-prod.ps1`，workers=1 不可改）。

---

## 8. 运行入口速查

| 场景 | 命令 |
|------|------|
| 全量场景测试 | `python -m pytest`（testpaths=test_suites） |
| 引擎离线自测（改引擎后必跑） | `python -m pytest -k engine_modes -v` + `python -m pytest test_engine -v` |
| specstd 自测（改 specstd 后必跑） | `python -m pytest test_specstd -v` |
| 发布门禁 | `python release_check.py` |
| 本地工作台 | `pwsh start-workbench.ps1`（后端 :9100 --reload + 前端 :5173，幂等） |
| 生产部署 | `pwsh serve-prod.ps1`（前端构建 + 单端口 :9100 UAC SSO） |
| Agent CLI（POC） | `python -m agent.cli "生成 PP-RC-008 场景"` |
| MCP stdio server | `python -m mcp_server.server` |

## 9. 技术栈

- **后端/引擎**：Python 3.14；pytest、requests、pymysql、pyyaml、fastapi、uvicorn、jsonpath-ng、httpx、mcp（后端额外 websockets、watchfiles）。
- **前端**：Node 18+、React 18、Vite 5、TypeScript 严格模式、elkjs、Monaco。
- **存储**：SQLite（workbench.db）+ 文件系统（场景 YAML / 会话 .jsonl / 各工作区 `.specguard/`）。
- **外部依赖**：SIT 网关（SSO/业务 API）、SIT MySQL（只读 DB 断言）；DB 密码回退读 `~/.qoder/skills/devops/scripts/.env.devops`，可用 `SG_DB_PASSWORD` / `SG_SSO_PASSWORD` 覆盖。

---

*本文档为架构快照；格式规范细节以 `workbench/backend/services/format_spec.py` 为准，依赖语义以 `docs/依赖状态管理设计-V3待实施.md` 为准。*
