# AGENTS.md — SpecGuard

> AI 协作入口（项目宪法）。被 Cursor / Claude Code / Codex / Qoder 等 28+ 工具原生识别。
> 原则：只写「偏离常识的硬约束」+ 工作流编排；完整规范去 Reference Docs 读，不在此重复。

---

## Project Overview

SpecGuard 是**契约驱动的后端场景测试引擎 + 可视化工作台**，作为**独立仓库**托管、独立演进，**不依附任何业务后端项目**。

- **定位**：Harness 五关注点闭环（上下文→约束→验证→恢复→反馈）中「验证 + 反馈」两环的工程落地。
- **被测系统解耦**：引擎与被测系统通过 `systems/{system}/` 适配包接入，当前已接入 `systems/tdm`（干部盘点），可按相同契约接入更多系统。
- **Status**：Active。引擎格式 2.0 已冻结；智能层 M0-M5（薄 Harness + MCP 工具层 + Spec 标准层）与多用户 RBAC（M6-M8）已全量落地，当前进入验收期优化（G1-G4 分阶段交付，详见 §Reference Docs）。

---

## Reference Docs（内容层 · 按需读，不在本文件重复）

| 你要做什么 | 读什么 | 备注 |
|-----------|--------|------|
| 写/改场景 YAML、理解 DSL | `workbench/backend/services/format_spec.py` | **格式规范唯一权威**（引擎注册表动态生成）；`docs/specguard-yaml-format-spec.md` 仅是导出快照 |
| 了解完全体能力与边界 | `docs/完全体SpecGuard能力边界与交互流程-测试人员指南.md` | 三层架构 + 双反馈循环 |
| 落地 Agent 智能层 | `docs/SpecGuard-Agent架构设计-MCP工具层与薄Harness.md` | MCP 工具层 + 薄 Harness，含 6 项 ADR |
| 智能层落地与阶段计划 | `docs/SpecGuard智能层开发简报.md`、`docs/SpecGuard智能层开发计划-M0至M5.md` | M0-M5 已完成，落地总结 + 阶段拆解 |
| 验收期优化（当前活跃） | `docs/SpecGuard验收期优化点总表.md`、`docs/SpecGuard优化升级开发Spec.md` | 13 模块优化点索引 + G1-G4 分阶段开发 Spec |
| 引擎语义与使用手册 | `README.md` | 详细操作手册（命令路径已去迁移前缀，与本文件 §Commands 一致） |
| 引擎演进设计 | `docs/引擎升级建议-DB断言与异步轮询.md`、`docs/引擎升级建议-第二批-变量插值与资源命名.md` | DB 断言/异步轮询、变量插值/资源命名 |
| 依赖状态管理设计 | `docs/依赖状态管理设计-V3待实施.md` | shared/exclusive 语义权威 |
| 产品演示/交互原型 | `docs/SpecGuard完全体*.html` | 对外宣讲材料 |

---

## Repository Structure

```
specguard/                        # 仓库根（独立，无外层前缀）
├── conftest.py                   # pytest 装配：SG_ROOT=本目录，加载适配包+运行上下文
├── pytest.ini                    # testpaths=test_suites；markers（P0/P1/resolver/permission/snapshot/security）
├── contracts_baseline.json       # 契约基线（fingerprint+version，T6 校验依赖）
├── release_check.py              # 发布门禁（格式/环/契约指纹/DRIFT 仲裁）
├── migrate_format_2.py           # 格式 2.0 迁移器（文本外科手术，非 round-trip）
├── requirements.txt              # Python 依赖（含 mcp/jsonpath-ng/httpx）
├── start-workbench.ps1           # 本地开发一键启动（后端:9100 --reload + 前端:5173）
├── serve-prod.ps1                # 生产部署（单端口 :9100 UAC SSO）
│
├── engine/                       # 通用引擎【冻结层 · 语义改动需评审】
│   ├── scenario_runner.py        #   执行器（flow/verify/插值/依赖调度，~1080 行）
│   ├── dependency_graph.py       #   DAG：拓扑/环检测/版本仲裁
│   ├── scenario_loader.py        #   YAML 场景加载
│   ├── tool_registry.py          #   tool 元数据注册表（模块导入时注册）
│   ├── versioning.py             #   契约版本（^X/精确匹配/指纹 sha256-12）
│   ├── db_oracle.py              #   只读 DB 客户端（SELECT-only 硬守卫）
│   ├── http_client.py / token_provider.py  # HTTP 与 SSO token
│   ├── report_writer.py / execution_record.py  # 报告产物
│   └── registry.py               #   步骤/断言器/提供者注册表
│
├── specstd/                      # Spec 标准层（"定标准的代码化"·被 engine 之外的智能层共用）
│   ├── schema.py                 #   v1 规范单一事实源（目录/文件常量+锚点正则+合规规则）
│   ├── anchors.py                #   FR/AC 锚点解析
│   ├── conformance.py            #   合规校验器
│   ├── signature.py              #   内容指纹（delta diff 基础）
│   └── workspace.py              #   工作区注册/git 克隆/激活切换；contextvar 向下游透传
│       └── workspaces/           #   注册表+克隆目录（registry.yaml/_clones/_anchors，不入 git）
│
├── systems/                      # 被测系统适配包（接入新系统=新增子包）
│   └── tdm/                      #   TDM 干部盘点适配
│       ├── config/env.sit.yaml   #     环境配置（网关/账号池/资源码/DB，占位符 ${VAR:default}）
│       ├── config/emp-pool.yaml  #     工号池角色定义
│       ├── steps.py              #     select_emp / fetch_permission（4 个 tool 声明）
│       ├── oracles.py            #     DB 校对断言器（快照冻结/权限过滤等 8+）
│       └── emp_pool.py / queries.py / hr_center_oracle.py / config.py
│
├── agent/                        # 智能层薄 Harness（M0-M5）
│   ├── runtime.py                #   Agent 运行时（tool 分发/会话循环）
│   ├── session.py                #   会话管理（多用户按工号隔离，agent/sessions/{emp}/）
│   ├── llm_client.py             #   LLM 客户端（配置热加载，DB 驱动）
│   ├── compactor.py              #   长对话压缩（超限自动摘要早期轮次）
│   ├── mode_loader.py + modes/   #   工作模式加载（generate/debug/analyze/audit/chat，热加载 30s TTL）
│   ├── skill_loader.py + skills/ #   技能加载（generate-scenario/validate-conformance/debug-failure）
│   ├── prompts/system.md.j2      #   system prompt Jinja 模板（注入 modes/skills）
│   ├── cli.py                    #   POC 独立验证入口
│   └── sessions/                 #   会话产物（.jsonl，不入 git）
│
├── mcp_server/                   # MCP 工具层（stdio，Agent 通过工具操作仓库）
│   ├── server.py                 #   stdio 入口（注册 8 模块 / 24 个工具）
│   └── tools/                    #   spec_reader/scenario_tools/registry_query/draft_writer/validator/attribution/audit/meta
│       ├── info_pack.py          #     基础信息包读写（尚未挂载到 server.TOOL_MODULES）
│       └── live_registry.py      #     运行时 tool 注册器（导入时注册 engine 适配包）
│
├── feedback/                     # 反哺闭环（双反馈循环 A/B 的持久化）
│   ├── ledger.py                 #   SPQ 台账状态机（pending→in_progress→closed）
│   └── notify.py                 #   通知出口
│
├── scenarios/                    # 场景库（按模块分目录，自动发现，双层 YAML）
│   ├── employee/person-profile/  #   全景档案（_suite.yaml 声明模块元信息）
│   ├── evaluation/eval-360/      #   360 评价
│   ├── inventory/grid-placement/ #   九宫格落位
│   └── inventory/inventory-session/ # 盘点会话
│
├── test_suites/                  # pytest 入口（testpaths 指向）
│   ├── test_engine_modes.py      #   引擎离线自测（shared/exclusive/teardown，无需网络/DB）
│   └── test_scenarios.py         #   全库场景参数化入口（K-048：替代原单模块入口，tags→mark）
├── test_engine/                  # 引擎组件单测（call/python/deps_editor/versioning；需显式指定路径）
├── test_specstd/                 # specstd 包单测（conformance/anchors/signature/workspace/agent/mcp/multiuser）
│
├── (drafts/plans/reports 已迁移至各工作区的 .specguard/ 目录，见 specstd/workspace.py)
└── workbench/                    # 可视化工作台
    ├── backend/                  #   FastAPI（main.py + routers/×15 + services/×20，含 RBAC + 工作区中间件）
    │   ├── routers/              #   auth/users/scenarios/runs/reference/plans/spec_validation/
    │   │                         #   agent/workspace/feedback/drafts/settings/notify/schedules
    │   └── services/             #   auth(会话+RBAC)/runner/scenario_store/plan_store/format_spec/
    │                             #   deps_editor/spec_validator/covers_gate/user_store/crypto/
    │                             #   llm_config/model_config/scenario_meta/scheduler/file_preview
    └── frontend/                 #   React 19 + Vite 6 + TS（DAG 画布/执行控制/场景编辑器/AgentChat）
```

---

## Build & Test Commands

> 所有命令均在**仓库根目录**执行。

```powershell
# ── 场景测试 ──
python -m pytest                          # 全量（testpaths=test_suites）
python -m pytest -k "PP-RC-005" -v        # 单场景
python -m pytest -m "P0" -v               # 按标签（P0/P1/permission/snapshot/security/resolver）
python -m pytest -k "PERM" -v             # 组合筛选
python -m pytest --env uat                # 指定环境（对应 systems/{system}/config/env.{env}.yaml）

# ── 引擎自测（离线，无需网络/DB，改引擎后必跑）──
python -m pytest -k engine_modes -v       # 依赖语义自测（test_suites/）
python -m pytest test_engine -v           # 引擎组件单测（call/python/deps_editor/versioning）

# ── specstd 包自测（改 specstd 后必跑）──
python -m pytest test_specstd -v          # 合规/锚点/指纹/工作区/agent/mcp/多用户

# ── 发布门禁 ──
python release_check.py                   # 格式/环/契约指纹校验，全 PASS 才允许入库

# ── 工作台 ──
pwsh start-workbench.ps1                  # 本地开发（后端 :9100 --reload 热重载 + 前端 :5173，依赖自检，幂等）
pwsh start-workbench.ps1 -NoBrowser       # 同上，不自动开浏览器
pwsh serve-prod.ps1                       # 生产部署（前端构建 + 单端口 :9100 UAC SSO，workers=1 不可改）
cd workbench/backend && uvicorn main:app --reload --port 9100   # 后端单独
cd workbench/frontend && npm install && npm run dev             # 前端单独（:5173）
cd workbench/frontend && npm run build                          # 前端构建（tsc + vite，产物 dist/）

# ── 智能层独立验证（POC，不依赖工作台）──
python -m agent.cli "生成 PP-RC-008 场景"             # Agent CLI（--mock 强制 mock / --session 恢复会话）
python -m mcp_server.server                          # MCP stdio server（供 Qoder 等宿主挂载）

# ── 多用户部署要点（M6-M8）──
# 认证: SG_AUTH_MODE=uac|mock（生产 uac / 开发 mock）；SG_UAC_BASE 默认 sit 内网地址
# 预置管理员: SG_ADMIN_ACCOUNTS=ad1,ad2（未设置时首个登录用户自动成为 admin）
# 数据: workbench/backend/data/workbench.db（SQLite，勿提交）；MCP stdio POC 用 SG_WORKSPACE 指定工作区
# 工作区透传: 前端 X-SG-Workspace header → specstd contextvar → agent/MCP/covers 全链路
```

**环境依赖**：
- Python 3.14（`pytest` `requests` `pymysql` `pyyaml` `fastapi` `uvicorn` `jsonpath-ng` `httpx` `mcp`；后端额外 `websockets` `watchfiles`）
- Node 18+（前端）
- 联网场景需可达 SIT 网关 + SIT MySQL；DB 密码自动回退读 `~/.qoder/skills/devops/scripts/.env.devops`，可用环境变量 `SG_DB_PASSWORD` / `SG_SSO_PASSWORD` 覆盖。

---

## Code Style（只列偏离常识的硬约束）

- **场景双层 YAML**：doc 层（given/when/then + `covers: [FR-xxx]` 唯一标签）给人看，flow/verify 层给机器跑；`covers` 是场景↔Spec 的强制锚点。
- **数组字段命名**：集合字段统一 `List` 结尾（如 `invPersonIdList`），禁止复数名词；字段一律驼峰。
- **插值**：`{{a.b.c}}` 点号路径，类型保留；`env.*` 来自环境配置，其余来自 `save` 变量或上游场景。
- **oracle/step 注册**：新断言器加到 `systems/{system}/oracles.py` 并注册；新 tool 在 `systems/{system}/steps.py` 声明，`engine/tool_registry.py` 模块导入时注册——**语法层零变更**。
- **SKIP 语义（诚实结果）**：测试数据缺失/账号未配置 → SKIP；上游失败 → BLOCKED；绝不把环境问题报成 FAIL。
- **前端**：React 函数组件 + TS 严格模式；DAG 布局用 elkjs（懒加载）；YAML 编辑用 Monaco；禁止 js-yaml 往返写回（会丢中文注释，用 deps_editor 文本外科手术）。
- **智能层 modes/skills 文件**：`agent/modes/*.md` 与 `agent/skills/*.md` 统一用 `---` YAML frontmatter（temperature/tools/description/trigger）+ Markdown 正文；loader 30s 内存缓存热加载，**新增文件无需重启**；skills 正文注入 system prompt 的 `<skills>` XML 块。

---

## Testing Instructions

- **TDD**：改引擎先写失败测试（`test_engine/` 或 `test_suites/test_engine_modes.py`），离线可跑者优先；改 specstd 先写 `test_specstd/`。
- **引擎能力变更三同步**（强制）：新增步骤类型/断言器/语法时，必须 ① 更新 `format_spec.py` 规范文档 ② 递增其版本号 ③ 更新 `contracts_baseline.json`——格式规范是 Agent 生成用例的唯一依据，文档滞后 = 能力不可用。
- 引擎改动后必跑离线自测（`engine_modes` + `test_engine`），全绿再跑联网场景。
- 测试计划只能由 delta 导入生成，禁止手动新建（落盘在各工作区的 `.specguard/plans/`）。

---

## 多系统接入（systems/{system}/ 适配包契约）

接入新被测系统 = 新增 `systems/{system}/` 子包，需提供：
1. `config/env.{env}.yaml`（网关/账号/DB，支持 `${VAR:default}` 占位符）
2. `config.py` 暴露 `load_env(env_name)`
3. `steps.py` 声明系统专属 tool（可选）
4. `oracles.py` 注册 DB 校对断言器（可选）
5. 运行时用 `SPEC_GUARD_SYSTEM={system}` 指定适配包（默认 `tdm`）

引擎层零改动——这是"独立仓库、多系统复用"的核心设计。

---

## Git Workflow

- **独立仓库**：已初始化并关联远端（`origin` → gitee `spec-guard`）。`.gitignore` 已覆盖 `__pycache__/` `.pytest_cache/` `node_modules/` `*.pyc` `workbench/backend/data/` `agent/sessions/` `feedback/*.json` `specstd/workspaces/*` 等；各工作区的 `.specguard/` 目录有自己的 `.gitignore`（忽略 reports/drafts，保留 plans/info_packs）；新增运行产物/凭据类文件前先确认是否需补 `.gitignore`。
- **commit 规范**：中文，格式 `{类型}: {中文简述}`（类型：feat/fix/docs/refactor/test/chore）。
- 迁移自 TDM 后端项目的历史路径引用（`tests/specguard/`）已在命令侧清理完毕，README 与本文件命令路径一致。

---

## Always

- 写场景前先读 `format_spec.py` 的最新规范（版本号 + 第八章 tool 目录）。
- 场景 `covers` 标签必须能在当前 Spec 快照中找到对应 FR/AC（关联完整性是 DAG 编排前置铁律）。
- 校验逻辑一律走确定性校验器（release_check / dependency_graph / specstd.conformance），不让 LLM 或人工目测替代。

## Ask First

- 新增 Python / 前端依赖（评估冲突与安全）。
- 改动引擎冻结层语义（`scenario_runner` 调度、`dependency_graph` 仲裁）。
- 改动 specstd 规范层（`schema.py` 是 v1 规范单一事实源，改动等同规范演进）。
- 接入新被测系统、新增环境配置（env.{env}.yaml 含网关/凭据）。

## Never

- 不让 Agent 产物绕过三道闸（人工评审 → 格式校验 → 发布门禁）直接入 `scenarios/`。
- 不在校验器/只读工具里写任何副作用（validate 必须纯读）。
- 不把运行产物（各工作区 `.specguard/reports/`）、`node_modules/`、`__pycache__/`、`workbench/backend/data/`、`agent/sessions/` 提交进仓库。
- 不在代码里硬编码环境凭据（一律走 env 配置 + devops 凭据回退）。
- 不用 js-yaml / round-trip 方式写 YAML（丢失中文注释）。

---

## Living Learnings

<!-- Agent 在工作中发现并需要记住的事项追加在此 -->
- [2026-07-24] ✅ 仓库自 `ifelc-ms-tdm-api/tests/specguard/` 迁出为独立仓库，已 git init + 关联 gitee 远端；命令路径已去前缀，README 同步完成。
- [2026-07-28] AGENTS.md 完成首轮适配度修订：补全 specstd/agent/mcp_server/feedback 四个此前缺失的顶层包，修正 Status/Git Workflow/环境依赖等过时声明。
