# AGENTS.md — SpecGuard

> AI 协作入口（项目宪法）。被 Cursor / Claude Code / Codex / Qoder 等 28+ 工具原生识别。
> 原则：只写「偏离常识的硬约束」+ 工作流编排；完整规范去 Reference Docs 读，不在此重复。

---

## Project Overview

SpecGuard 是**契约驱动的后端场景测试引擎 + 可视化工作台**，作为**独立仓库**托管、独立演进，**不依附任何业务后端项目**。

- **定位**：Harness 五关注点闭环（上下文→约束→验证→恢复→反馈）中「验证 + 反馈」两环的工程落地。
- **被测系统解耦**：引擎与被测系统通过 `systems/{system}/` 适配包接入，当前已接入 `systems/tdm`（干部盘点），可按相同契约接入更多系统。
- **Status**：Active。引擎格式 2.0 已冻结；智能层 M0-M5（薄 Harness + MCP 工具层 + Spec 标准层）与多用户 RBAC（M6-M8）已全量落地；G1-G4 验收期优化已随打磨期结束（T-601~T-606 瘦身任务块进行中）。

---

## 角色认知（开发角色 vs 使用角色）

SpecGuard 存在两类 AI 角色，认知边界必须清晰，互不越界：

1. **开发角色——本文件的读者**：开发/维护 SpecGuard 工具链本身（引擎/工作台/智能层/适配包）的 AI。遵循本文件全部规则（冻结层评审、三同步、发布门禁、git 规范）。本文件是「SpecGuard 项目宪法」，只服务开发角色，**不会注入 agent 对话的 system prompt**——agent 对话注入的是被测系统工作区的 AGENTS.md（见 specstd/workspace.read_agents_md）。
2. **使用角色——agent 对话中的 AI**：通过 AgentChat / agent CLI / MCP 挂载使用 SpecGuard，为被测系统制作单元测试、编排 DAG、验证接口、归因失败的 AI。其规则知识由 system prompt 承载：格式规范（format_spec 动态生成）+ 技能（agent/skills/*.md）+ 被测系统工作区 AGENTS.md 全量原文（P1 决策：规则层知识不允许有损压缩）。

行为边界：
- **使用角色是「SpecGuard 测试助手」，不是 SpecGuard 开发者**：不修改引擎/工作台/agent 代码，不触碰冻结层语义，不做仓库管理决策；发现 SpecGuard 本体缺陷走反馈路径上报，不自行改工具
- **开发角色进入 agent 对话时，以使用角色身份行事**：不把开发向规则（发布门禁/git 规范/三同步）带进对话，对话内聚焦被测系统的测试任务
- **两套规范互不替代**：开发向规则在本文件；使用向规则在 system prompt + 被测系统工作区 AGENTS.md。使用角色不应阅读本文件做测试决策；开发角色不得把本文件内容直接塞进对话提示词（被测系统工作区有自己的 AGENTS.md）

---

## Reference Docs（内容层 · 按需读，不在本文件重复）

| 你要做什么 | 读什么 | 备注 |
|-----------|--------|------|
| 写/改场景 YAML、理解 DSL | `sg_core/format_spec.py` | **格式规范唯一权威**（引擎注册表动态生成；T-975 下沉 sg_core，原 services 位置留 shim）；`docs/specguard-yaml-format-spec.md` 仅是导出快照 |
| 了解完全体能力与边界 | `docs/完全体SpecGuard能力边界与交互流程-测试人员指南.md` | 三层架构 + 双反馈循环 |
| 落地 Agent 智能层 | `docs/SpecGuard-Agent架构设计-MCP工具层与薄Harness.md` | MCP 工具层 + 薄 Harness，含 6 项 ADR |
| 智能层落地与阶段计划 | `docs/SpecGuard智能层开发简报.md`、`docs/SpecGuard智能层开发计划-M0至M5.md` | M0-M5 已完成，落地总结 + 阶段拆解 |
| 验收期优化（已归档） | `docs/历史区/SpecGuard验收期优化点总表.md`、`docs/历史区/SpecGuard优化升级开发Spec.md` | 13 模块优化点索引 + G1-G4 分阶段开发 Spec，T-604 已归档至 docs/历史区 |
| 引擎语义与使用手册 | `README.md` | 详细操作手册（命令路径已去迁移前缀，与本文件 §Commands 一致） |
| 引擎演进设计 | `docs/引擎升级建议-DB断言与异步轮询.md`、`docs/引擎升级建议-第二批-变量插值与资源命名.md` | DB 断言/异步轮询、变量插值/资源命名 |
| 依赖状态管理设计 | `docs/依赖状态管理设计-V3待实施.md` | shared/exclusive 语义权威 |
| S2 面试材料飞书获取背景 | `docs/远期设计/SpecGuard-飞书CLI能力背景-S2面试材料获取.md` | 飞书 CLI 四通道拉取（文档/多维表格/妙记/聊天）实测链路 + 权限边界，S2 施工必读 |
| S2 面试材料禅道读取背景 | `docs/远期设计/SpecGuard-禅道需求读取背景-S2面试材料来源.md` | 禅道需求只读引用（story get/search 薄通道）实测链路 + 设计，完整禅道写通道在 S5/M06 |
| 产品演示/交互原型 | `docs/历史区/SpecGuard完全体*.html` | 对外宣讲材料 |

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
├── start-workbench.ps1           # 本地开发一键启动（后端:9100 默认无热重载 + 前端:5173；-Reload 显式开启热重载）
├── new-worktree.ps1              # 多会话并行：建功能域 worktree + 同步主库本地运行状态（-SyncOnly 重同步）
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
├── sg_core/                      # 共享内核（T-975 下沉：mcp_server/agent/workbench 三方
│   ├── user_store.py             #   共同消费的实体；依赖单向 sg_core→specstd/engine，
│   ├── ledger_store.py           #   不得反向 import mcp_server/agent/workbench——
│   ├── draft_promote.py          #   workbench/backend/services 下同名模块为 sys.modules
│   ├── model_config.py           #   转发 shim，存量 import 零改动；monkeypatch 打桩
│   ├── format_spec.py            #   指向 sg_core.X（定义模块）；环检查见
│   └── …（共 24 模块）           #   scripts/check_import_cycles.py + release_check ④）
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
│   ├── skill_loader.py + skills/ #   技能加载（T-601：modes 退役后唯一事实源，8 技能 30s TTL）
│   ├── prompts/system.md.j2      #   system prompt Jinja 模板（注入 skills/format_spec/AGENTS）
│   ├── cli.py                    #   POC 独立验证入口
│   └── sessions/                 #   会话产物（.jsonl，不入 git）
│
├── mcp_server/                   # MCP 工具层（stdio，Agent 通过工具操作仓库）
│   ├── server.py                 #   stdio 入口（T-982 收敛：对内 24 合并工具+open 15，见 tools/tool_meta.py）
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

# ── 质量工具（报告模式，规则见「质量基线与顺手修复」）──
cd workbench/frontend && npm run lint     # oxlint 前端 lint（存量报告见 docs/质量基线/）
cd workbench/frontend && npm run test     # vitest 前端单测（--coverage 出覆盖率）
npm run dup:scan                          # jscpd 全仓查重（仓库根，只报告不卡关）
ruff check --statistics                   # Python lint 分布（ruff check 看明细）
cd workbench/frontend && npx knip         # 前端死代码/幽灵依赖
python -m pytest test_engine --cov=engine --cov-report=term-missing    # 引擎覆盖率
python -m pytest test_specstd --cov=specstd --cov-report=term-missing  # specstd 覆盖率（全套件有 94 个存量 error，见质量基线 README）
npx lefthook install                      # 克隆后一次性：装 git hooks（pre-push 门禁）

# ── 多会话并行（worktree，规程见 Git Workflow §多会话并行开发）──
pwsh new-worktree.ps1 <功能域>                # 建树 + 自动同步主库本地运行状态；-SyncOnly 仅重同步

# ── 工作台 ──
pwsh start-workbench.ps1                  # 本地开发（后端 :9100 默认无热重载 + 前端 :5173，依赖自检，幂等）
pwsh start-workbench.ps1 -NoBrowser       # 同上，不自动开浏览器
pwsh start-workbench.ps1 -Reload          # 显式开启后端热重载（改代码自动重启，WS 聊天会断连重连）
pwsh serve-prod.ps1                       # 生产部署（前端构建 + 单端口 :9100 UAC SSO，workers=1 不可改）
cd workbench/backend && uvicorn main:app --reload --ws-ping-interval 30 --ws-ping-timeout 120 --port 9100   # 后端单独（仅调试用，聊天 WS 会断连）
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
- Python 开发工具链（生产不装）：`pip install -r requirements-dev.txt`（ruff/hypothesis/pytest-cov/vulture；pypi 超时加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`）
- Node 18+（前端构建）；前端测试/lint 需 Node 20+（vitest 4 要求，24 实测可用）
- 联网场景需可达 SIT 网关 + SIT MySQL；DB 密码自动回退读 `~/.qoder/skills/devops/scripts/.env.devops`，可用环境变量 `SG_DB_PASSWORD` / `SG_SSO_PASSWORD` 覆盖。

---

## Code Style（只列偏离常识的硬约束）

- **场景双层 YAML**：doc 层（given/when/then + `covers: [FR-xxx]` 唯一标签）给人看，flow/verify 层给机器跑；`covers` 是场景↔Spec 的强制锚点。
- **数组字段命名**：集合字段统一 `List` 结尾（如 `invPersonIdList`），禁止复数名词；字段一律驼峰。
- **插值**：`{{a.b.c}}` 点号路径，类型保留；`env.*` 来自环境配置，其余来自 `save` 变量或上游场景。
- **oracle/step 注册**：新断言器加到 `systems/{system}/oracles.py` 并注册；新 tool 在 `systems/{system}/steps.py` 声明，`engine/tool_registry.py` 模块导入时注册——**语法层零变更**。
- **SKIP 语义（诚实结果）**：测试数据缺失/账号未配置 → SKIP；上游失败 → BLOCKED；绝不把环境问题报成 FAIL。
- **前端**：React 函数组件 + TS 严格模式；DAG 布局用 elkjs（懒加载）；YAML 编辑用 Monaco；禁止 js-yaml 往返写回（会丢中文注释，用 deps_editor 文本外科手术）。
- **前端体验基线（硬约束，新增页面/交互必逐条自查）**：①**操作状态持久化**——页签/选择器/筛选条件等用户选择用 localStorage 记住，进入即恢复上次状态，不遍用户重复选择；恢复值失效时诚实回退默认（不报错不空白）。②**技术侧细节不外露为用户操作面**——多模态转述/后台聚类等自动执行（同步后异步触发，模型未配置诚实跳过），不给用户设独立维护入口。③**三态分离**——加载中/空数据/错误三种状态分别呈现，占位文案不得混用（「加载中…」不得用于「无数据」，曾致 0 字节快照被误读为加载卡死）。④**长操作可单点刷新**——全局同步之外提供局部入口（如「更新本群」秒级反馈），不让用户为看一个群的变化等全量。⑤**缺失配置就地补——不报错踢人**——动作因缺配置（如未配 text/vision 模型）失败时，直接弹出配置弹层就地填写（预填可改默认值），保存后自动重试原动作；禁止只报错让用户自己去设置页找。
- **智能层 skills 文件**：`agent/skills/*.md` 统一用 `---` YAML frontmatter（name/description/trigger/keywords）+ Markdown 正文；loader 实体在 `sg_core/skill_loader.py`（T-976 解环下沉，`agent/skill_loader.py` 留转发 shim），30s 内存缓存热加载，**新增文件无需重启**；skills 正文注入 system prompt 的 `<skills>` XML 块，用户消息关键词命中 keywords 时附加技能提示（match_skills_hint）。

---

## Testing Instructions

- **TDD**：改引擎先写失败测试（`test_engine/` 或 `test_suites/test_engine_modes.py`），离线可跑者优先；改 specstd 先写 `test_specstd/`。
- **引擎能力变更三同步**（强制）：新增步骤类型/断言器/语法时，必须 ① 更新 `format_spec.py` 规范文档 ② 递增其版本号 ③ 更新 `contracts_baseline.json`——格式规范是 Agent 生成用例的唯一依据，文档滞后 = 能力不可用。
- 引擎改动后必跑离线自测（`engine_modes` + `test_engine`），全绿再跑联网场景。
- 测试计划只能由 delta 导入生成，禁止手动新建（落盘在各工作区的 `.specguard/plans/`）。

---

## 质量基线与顺手修复（Boy Scout Rule）

**规则**：任何会话修改某个文件时，先查 `docs/质量基线/` 的对应报告——若该文件有记录在案的问题（lint error、未使用导出、查重热点），顺手修复；修完重跑对应命令刷新报告数字。不追求一次性清零，只要求「碰过的文件变得更好」。批量 `--fix` 属大改动，何时做由总控人拍板。

- **报告目录**：`docs/质量基线/`（README.md 是索引 + 判读结论 + 复现命令；`*-baseline.txt` 是工具原始输出，快照会过期，以复跑为准）
- **基线摘要**（2026-08-14 首批）：oxlint 8 errors / 3100 warnings（60 文件，errors 优先清）；ruff 1331 项（F 类 175 F401 + 28 F841 是真 bug 信号）；knip 1 死文件 + 2 幽灵依赖；jscpd 36 处克隆（YAML 场景库 13.93% 是主要热点）；vulture 8 行；覆盖率 engine 46% / specstd 87%。另发现 `test_specstd` 全套件 94 个存量 error（隔离污染，与工具链无关，详见报告 README）
- **门禁状态**：pre-push 已挂 `release_check.py` + 离线测试（lefthook，约 15s，`git push --no-verify` 可紧急跳过）；lint 类处于**报告模式**不进 pre-commit——某工具报告清零后，再把它以 `glob + {staged_files}` 形式加进 `lefthook.yml` 的 pre-commit（ratchet：新代码必须干净，旧代码慢慢还）
- **修复纪律**：只限机械/语义保持类修复（删未使用导入、调整导入排序等）；任何行为变更走正常评审；不确定是否误报时保留并在报告 README 记录疑点

---

## 故障排查（按任务号，K-050/K-052）

每次执行控制触发的运行都有**任务号**（`EX-` + 8 位随机 hex，如 `EX-9e31916f`）。排错以任务号为唯一线索，不要靠时间回忆：

| 产物 | 位置 | 内容 |
|------|------|------|
| 执行日志 | `{workspace}/.specguard/reports/{EX-xxx}/output.log` | pytest 全量 stdout，含 `[SpecGuard] METHOD path → status \| trace={ifelc-trace_id}` 调用链锚点 |
| 结构化报告 | 同目录 `run.json` / `report.md` / `cases/*.json` | verdict 分布、失败 category/message、断言差异、步骤轨迹 |
| 失败索引 | `{workspace}/.specguard/reports/failures/index.jsonl` | 「场景 × 任务号 × 失败原因」台账（每次运行完成自动追加，幂等） |

**排障动线**：`failures/index.jsonl` 按场景反查任务号 → `output.log` 看调用链（trace_id 可在网关全链追踪）→ `cases/*.json` 看断言差异。
**Agent 工具链**（对话中排查/优化失败场景）：`list_failures`（某场景最近在什么任务号失败）→ `read_run_log`（任务号取日志）→ `read_run_report`（断言差异）→ `db_evidence`（DB 校对）。断点分批执行的报告在 `{EX-xxx}-b{N}/` 批次目录。
K-050 之前的旧报告只有时间戳目录 + run.json/report.md（无 output.log）。

## Agent 会话排查（T-321，开发 SpecGuard 时用）

Agent 对话**实时落盘**（`agent/runtime.py` 每轮消息/tool 后增量 `session.save()`，LLM 异常与熔断均兜底），文件为 append-only JSONL：

| 产物 | 位置 | 内容 |
|------|------|------|
| 会话消息 | `agent/sessions/{emp}/{workspace}/{sid}.jsonl` | meta + system prompt + user/assistant/tool 消息链（tool 结果全文） |
| LLM 指标 | 同目录 `{sid}_metrics.jsonl` | 调用次数/token 统计（最后一行最新） |

**排查动线**：用户报 `sessionId` → 直接跑 `python -m agent.inspect <sid> [--workspace tdm]`——错误汇总优先（LLM 失败/工具执行异常/[ERROR] 行）+ 工具调用链 + 截断消息链（system prompt 只显示长度不刷屏）；`--full` 看全文、`--json` 机器可读。**不需要用户导出会话**。

---

## 问题修复经验包（排障闭环知识沉淀）

> **入口：`docs/经验包/README.md`**（协议 + 索引表）。每个「具体问题 → 根因 → 修复 → 预防」独立一文件，本处只放入口不重复内容。

- **何时登记**：每次排障闭环后（根因确认 + 修复落盘）新增经验包文件，并在 `docs/经验包/README.md` 索引表加一行
- **文件命名**：`{日期}-{任务号}-{现象摘要}.md`（如 `2026-08-02-EX-8200eada-变量未定义-权限缺失.md`）
- **模板五段**：现象（任务号/错误消息）→ 证据链（output.log/case 摘录，附位置）→ 根因（**哪个环节缺失**一句话：环境/场景/引擎/配置）→ 修复（含提交号）→ 预防（可执行检查清单）
- **排障前先查**：`grep -l "关键词" docs/经验包/*.md`——同类案例可能已有结论（如「变量未定义」类问题先看是否权限/账号类根因）
- **纪律**：根因必须是证据链支持的事实；预防要可执行，不留「待观察」式空话

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

### 多会话并行开发（git worktree 规程）

> 多 AI 会话并行的唯一合法形态。核心分工：**主库只做验收，worktree 只做开发**。

- **主库 = master 验收线**：主库 checkout 永远停在 `master` 且工作树保持干净；用途仅限拉取最新代码 + 整体测试验收 + 联网场景串行执行。**禁止在主库直接开发**（AI 会话同样禁止——接到开发任务时，先确认目标 worktree，去那里动手）。
- **一个功能域一棵 worktree，长期复用**：按功能域建树（如 `wt/engine-upgrade`），不随单个任务新建，管控树数量。建树一律走 `pwsh new-worktree.ps1 <功能域>`——自动从主库同步本地运行状态（workbench.db / specstd/workspaces / .lark-cli 等，node_modules 除外）；**禁止手工 `git worktree add`**（漏掉状态同步，新树跑不了工作台与工作区相关功能）。
- **会话工作方式**：开发会话统一在主目录打开；agent 自行进入对应 worktree 开发——文件读写一律用 worktree 绝对路径（`D:\work\tdm-code\wt\<域>\...`），bash/git 命令用 `git -C <树路径>` 或先 `cd`。验收与联网测试指令回到主库执行。
- **树与分支的对应关系**：建树脚本幂等——分支已存在则直接挂载、不存在才从 master 新建；git 不允许同一分支挂两棵树，所以**一棵树建一次长期复用，后续会话直接进树目录工作**，树永远停在自己的 `feature/<域>` 分支上，会话无需也不应切分支。同名再建树会报路径已存在（重同步用 `-SyncOnly`）。
- **开工三件事（跨树可见性纪律）**：会话进树第一件事——① `git fetch origin` ② `git worktree list`（看在册树）③ 读**主库**总控文档 §4 任务表的状态列（主库那份是权威，树内副本是分支点冻结快照，可能滞后）。30 秒建立「哪些域活跃、进行到哪」的全局视野，不建立不得动手。
- **认领/状态回写走 push 通道，不靠跨树改文件**：wt 会话认领任务 = 改**自己树里**总控 §4 对应行的状态+会话ID → 提交 → 立刻 push `feature/<域>`（与「提交即推」同一纪律）。其他会话 fetch 后即可见；状态行随分支验收合并自然回到 master 的总控，不需要单独同步动作。每域只改自己的任务行，合并冲突概率极低。
- **总控 §6 文件登记表的作用域**：只协调**同树内**会话（它是分支内文件，A 树的登记 B 树看不到）。跨树防撞靠两道：①任务划分时按功能域文件邻区事前隔离 ②验收合并时 git 冲突兜底。不要以为在 §6 登记了就跨树安全。
- **提交即推功能分支（备份线，防本地对象库损坏）**：worktree 与主库**共享同一个 `.git` 对象库**——本地对象库损坏会同时摧毁全部树（2026-08 已发生一次，恢复时只能全量入库、丢失提交细节与 message）。worktree 内每完成一次提交立刻 `git -C <树路径> push origin feature/<域>`；目的是备份，不要求 PR、不触发合并。远端功能分支合入 master 后可随手删（本地分支随树继续复用，下次推送会重建）。
- **master 前进只在主库、验收之后**：主库 `git pull` 后在 master 上 `git merge feature/<域>`（本地分支与 origin 同名分支内容一致，用哪个都行）→ 整体测试验收 → 通过才 `git push origin master`（pre-push 门禁照常）；验收不过 `git reset --hard ORIG_HEAD`，远端 master 零污染。需要 PR 评审留痕或跨机器协作时，改走"远端合并 → 主库 pull"备选路径。
- **worktree 分支回同步**：master 前进后，worktree 继续复用前 `git -C <树路径> fetch origin && git -C <树路径> rebase origin/master`。若合入方式是 squash（远端或本地 `--squash`）导致 rebase 假冲突、且本地改动已全部入库：`git -C <树路径> switch -C feature/<域> origin/master` 重置分支再出发；功能域分支不删，随树长期复用。
- **并行纪律**：联网场景测试只在主库串行跑（SIT 是被测共享环境，进程内 LeaseRegistry 不跨树）；worktree 内只跑离线测试（`test_engine` / `engine_modes`）；工作台 :9100/:5173 不可两树同起。
- **本地状态再同步**：主库状态有大变更（新注册工作区 / LLM 配置变更）后，对对应树执行 `pwsh new-worktree.ps1 <名> -SyncOnly`。
- **删除**：先停从该目录起的 uvicorn/npm 进程（Windows 文件锁），再 `git worktree remove <路径>`。
- **在册清单**：以 `git worktree list` 实时输出为准，不在任何文档抄静态清单。

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
- 不把场景 YAML 当纯数据——`python` 步骤/断言等同执行任意代码（exec），外部贡献场景必须人工评审后才允许入库执行（ENG-SEC-001 标注；引擎不加禁用开关的决策见问题清单对应条目）。
- 不在校验器/只读工具里写任何副作用（validate 必须纯读）。
- 不把运行产物（各工作区 `.specguard/reports/`）、`node_modules/`、`__pycache__/`、`workbench/backend/data/`、`agent/sessions/` 提交进仓库。
- 不在代码里硬编码环境凭据（一律走 env 配置 + devops 凭据回退）。
- 不用 js-yaml / round-trip 方式写 YAML（丢失中文注释）。

---

## Living Learnings

<!-- Agent 在工作中发现并需要记住的事项追加在此 -->
- [2026-07-24] ✅ 仓库自 `ifelc-ms-tdm-api/tests/specguard/` 迁出为独立仓库，已 git init + 关联 gitee 远端；命令路径已去前缀，README 同步完成。
- [2026-07-28] AGENTS.md 完成首轮适配度修订：补全 specstd/agent/mcp_server/feedback 四个此前缺失的顶层包，修正 Status/Git Workflow/环境依赖等过时声明。
- [2026-08-05] AGENTS.md 新增「角色认知」章节：理清开发角色（本文件读者，不注入 agent 对话）与使用角色（agent 对话测试助手，规则知识来自 system prompt + 被测系统工作区 AGENTS.md）的边界，防止角色混淆。
- [2026-08-19] 飞书材料池共享化（T-949）：chats/docs/minutes 快照与话题库/历史落**工作区共享材料区**（`{ws}/.specflow/feishu_pool/`，即 `specflow_dir("")`）；watch 配置与话题草案留私有区（谁配置谁拉）。**授权语义升级为工作区级**：docs/minutes 对用户的可见性跟随飞书侧权限元数据（perm meta，需 `docs:permission.member:retrieve`/`docs:permission.setting:read` scope，缺失时保守仅 owner 可见）；chats 快照对工作区全员可见（拉取者必在群内，办公转述语义）。多用户重复同步靠 message_id 幂等合并无害化。
- [2026-08-20] 多会话并行确立 git worktree 规程（Git Workflow §多会话并行开发）：主库永驻 master 只做验收，功能域 worktree 长期复用、建树走 `new-worktree.ps1`（同步 workbench.db/workspaces 等本地状态；lefthook pre-push 钩子硬编码主树二进制路径，worktree 内 push 门禁天然有效）。此前多会话同树开发出过事故；另本地对象库曾损坏（36f8108 恢复性全量入库），教训沉淀为「提交即推功能分支——worktree 共享主库对象库，不是备份，远端是唯一的提交细节备份线」。
- [2026-08-21] T-975/T-976 依赖翻正（wt/dep-inversion）：21+3 个 services 实体下沉 `sg_core/`（user_store 数据层地基/ledger_store/draft_promote/format_spec/skill_loader/data_validator 等），原位置 sys.modules 转发 shim——**同名单引/打桩零改动，但 monkeypatch 必须指向 sg_core.X（定义模块）**；全仓 sys.path.insert 由 ~200 处清至 2 处合法入口引导（main.py 组合根 + backend 独立运维脚本），测试路径引导归一 pytest.ini `pythonpath`。模块级 import 环清零并进 release_check ④ 门禁（scripts/check_import_cycles.py）；函数级回边 3 条白名单登记（M-A/M-C 演进收编）。**下沉模块的 `Path(__file__)` 层数必须随新位置修正**（本次漏过 data_validator 一处，被 POOL_EXISTS 硬拒测试当场抓住）。顺手修存量 bug：audit_store.DB_DIR 幽灵路径（workbench/workbench/，主库存在该幽灵目录，可择期清理）。
- [2026-08-21] worktree 规程补三条跨树协调纪律：①树与分支 1:1 长期复用，会话进树不切分支；②开工三件事（fetch→worktree list→读主库总控状态列）建立跨树视野；③认领/状态回写走 push 通道（改自己树的总控状态行→提交即推），总控 §6 文件登记表只协调同树内会话——跨树防撞靠功能域文件邻区事前隔离 + 合并验收 git 兜底，**不复制总控到各树**（事实源分裂比没有更糟）。
