# AGENTS.md — SpecGuard

> AI 协作入口（项目宪法）。被 Cursor / Claude Code / Codex / Qoder 等 28+ 工具原生识别。
> 原则：只写「偏离常识的硬约束」+ 工作流编排；完整规范去 Reference Docs 读，不在此重复。

---

## Project Overview

SpecGuard 是**契约驱动的后端场景测试引擎 + 可视化工作台**，作为**独立仓库**托管、独立演进，**不依附任何业务后端项目**。

- **定位**：Harness 五关注点闭环（上下文→约束→验证→恢复→反馈）中「验证 + 反馈」两环的工程落地。
- **被测系统解耦**：引擎与被测系统通过 `systems/{system}/` 适配包接入，当前已接入 `systems/tdm`（干部盘点），可按相同契约接入更多系统。
- **Status**：Active（引擎格式 2.0 已冻结；智能层 Agent 能力为下阶段，见 §Reference Docs 架构设计）。

---

## Reference Docs（内容层 · 按需读，不在本文件重复）

| 你要做什么 | 读什么 | 备注 |
|-----------|--------|------|
| 写/改场景 YAML、理解 DSL | `workbench/backend/services/format_spec.py` | **格式规范唯一权威**（引擎注册表动态生成）；`docs/specguard-yaml-format-spec.md` 仅是导出快照 |
| 了解完全体能力与边界 | `docs/完全体SpecGuard能力边界与交互流程-测试人员指南.md` | 三层架构 + 双反馈循环 |
| 落地 Agent 智能层 | `docs/SpecGuard-Agent架构设计-MCP工具层与薄Harness.md` | MCP 工具层 + 薄 Harness，含 6 项 ADR |
| 引擎语义与使用手册 | `README.md` | 详细操作手册（⚠️ 其中 `tests/specguard/` 路径前缀为迁移前遗留，以本文件 §Commands 为准） |
| 依赖状态管理设计 | `docs/依赖状态管理设计-V3待实施.md` | shared/exclusive 语义权威 |
| 产品演示/交互原型 | `docs/SpecGuard完全体*.html` | 对外宣讲材料 |

---

## Repository Structure

```
specguard/                        # 仓库根（独立，无外层前缀）
├── conftest.py                   # pytest 装配：SG_ROOT=本目录，加载适配包+运行上下文
├── pytest.ini                    # testpaths=test_suites；markers（P0/P1/resolver/permission/snapshot/security）
├── contracts_baseline.json       # 契约基线（produces+save 名+covers 指纹，T6 校验依赖）
├── release_check.py              # 发布门禁（格式/环/契约指纹/DRIFT 仲裁）
├── migrate_format_2.py           # 格式 2.0 迁移器（文本外科手术，非 round-trip）
├── start-workbench.ps1           # 一键启动工作台（后端:9100 + 前端:5173）
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
├── systems/                      # 被测系统适配包（接入新系统=新增子包）
│   └── tdm/                      #   TDM 干部盘点适配
│       ├── config/env.sit.yaml   #     环境配置（网关/账号池/资源码/DB，占位符 ${VAR:default}）
│       ├── config/emp-pool.yaml  #     工号池角色定义
│       ├── steps.py              #     select_emp / fetch_permission（4 个 tool 声明）
│       ├── oracles.py            #     DB 校对断言器（快照冻结/权限过滤等 8+）
│       ├── emp_pool.py / queries.py / hr_center_oracle.py / config.py
│
├── scenarios/                    # 场景库（按模块分目录，自动发现，双层 YAML）
│   ├── employee/person-profile/  #   全景档案（_suite.yaml 声明模块元信息）
│   ├── evaluation/eval-360/      #   360 评价
│   ├── inventory/grid-placement/ #   九宫格落位
│   └── inventory/inventory-session/ # 盘点会话
│
├── test_suites/                  # pytest 入口（testpaths 指向）
│   ├── test_engine_modes.py      #   引擎离线自测（shared/exclusive/teardown，无需网络/DB）
│   └── test_person_profile.py    #   场景参数化入口
├── test_engine/                  # 引擎组件单测（call/python/deps_editor/versioning；需显式指定路径）
│
├── plans/                        # 测试计划 YAML（delta 导入生成，禁止手动新建）
├── reports/                      # 运行产物（时间戳目录，.gitignore，勿提交）
├── drafts/                       # Agent 草稿区（评审通过才移入 scenarios/）
└── workbench/                    # 可视化工作台
    ├── backend/                  #   FastAPI（main.py + routers/×6 + services/×6）
    └── frontend/                 #   React 18 + Vite 5 + TS（DAG 画布/执行控制/场景编辑器）
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
python -m pytest test_engine -v           # 组件单测（call/python/deps_editor/versioning）

# ── 发布门禁 ──
python release_check.py                   # 格式/环/契约指纹校验，全 PASS 才允许入库

# ── 工作台 ──
pwsh start-workbench.ps1                  # 一键启动（后端 :9100 + 前端 :5173，幂等）
cd workbench/backend && uvicorn main:app --reload --port 9100   # 后端单独
cd workbench/frontend && npm install && npm run dev             # 前端单独（:5173）
cd workbench/frontend && npm run build                          # 前端构建（tsc + vite）
```

**环境依赖**：
- Python 3.14（`pytest` `requests` `pymysql` `pyyaml` `fastapi` `uvicorn`）
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

---

## Testing Instructions

- **TDD**：改引擎先写失败测试（`test_engine/` 或 `test_suites/test_engine_modes.py`），离线可跑者优先。
- **引擎能力变更三同步**（强制）：新增步骤类型/断言器/语法时，必须 ① 更新 `format_spec.py` 规范文档 ② 递增其版本号 ③ 更新 `contracts_baseline.json`——格式规范是 Agent 生成用例的唯一依据，文档滞后 = 能力不可用。
- 引擎改动后必跑离线自测（`engine_modes` + `test_engine`），全绿再跑联网场景。
- 测试计划（`plans/`）只能由 delta 导入生成，禁止手动新建。

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

- **独立仓库**：当前目录尚未初始化 git。独立开发前请先 `git init`、关联独立远端、并补充 `.gitignore`（`__pycache__/` `.pytest_cache/` `node_modules/` `reports/` `*.pyc`）。
- **commit 规范**：中文，格式 `{类型}: {中文简述}`（类型：feat/fix/docs/refactor/test/chore）。
- 迁移自 TDM 后端项目的历史路径引用（`tests/specguard/`）属遗留，逐步清理，以本文件为准。

---

## Always

- 写场景前先读 `format_spec.py` 的最新规范（版本号 + 第八章 tool 目录）。
- 场景 `covers` 标签必须能在当前 Spec 快照中找到对应 FR/AC（关联完整性是 DAG 编排前置铁律）。
- 校验逻辑一律走确定性校验器（release_check / dependency_graph），不让 LLM 或人工目测替代。

## Ask First

- 新增 Python / 前端依赖（评估冲突与安全）。
- 改动引擎冻结层语义（`scenario_runner` 调度、`dependency_graph` 仲裁）。
- 接入新被测系统、新增环境配置（env.{env}.yaml 含网关/凭据）。

## Never

- 不让 Agent 产物绕过三道闸（人工评审 → 格式校验 → 发布门禁）直接入 `scenarios/`。
- 不在校验器/只读工具里写任何副作用（validate 必须纯读）。
- 不把 `reports/` 运行产物、`node_modules/`、`__pycache__/` 提交进仓库。
- 不在代码里硬编码环境凭据（一律走 env 配置 + devops 凭据回退）。
- 不用 js-yaml / round-trip 方式写 YAML（丢失中文注释）。

---

## Living Learnings

<!-- Agent 在工作中发现并需要记住的事项追加在此 -->
- [2026-07-24] 仓库自 `ifelc-ms-tdm-api/tests/specguard/` 迁出为独立仓库；命令路径去前缀，README 中旧路径待同步。
