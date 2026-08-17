# SpecGuard — 契约驱动的后端场景测试流水线

> 契约驱动 + 数据库预言 + 权限预言的端到端场景测试体系。
> 当前覆盖：干部全景档案（person-profile）15 场景（14 PASS + 1 SKIP）。
>
> 📦 本仓库已**独立托管**（自 `ifelc-ms-tdm-api/tests/specguard/` 迁出），所有命令均在**仓库根目录**执行；AI 协作入口见 `AGENTS.md`。

---

## 一、快速开始（30 秒跑通）

```powershell
# 在项目根目录，一条命令跑全部场景
python -m pytest -v
```

**前置条件**（开发机默认可满足）：

- Python 依赖：`pytest`、`requests`、`pymysql`、`pyyaml`
- 网络可达 SIT 网关 `sit-ha.fehorizon.com` + SIT MySQL
- DB 密码：自动回退读取 devops 技能凭据 `~/.qoder/skills/devops/scripts/.env.devops`（无需手动配置）

每次运行自动生成报告：`reports/{时间戳}/`

| 产物 | 说明 |
|------|------|
| `report.md` | 人读报告（每场景 given/when/then + 断言表 + 失败证据） |
| `run.json` | 结构化运行数据（供 CI/看板消费） |
| `cases/{场景ID}.json` | 单场景详情：HTTP 轨迹、DB 校对证据（db_traces）、权限预言 |

---

## 二、常用运行方式

```powershell
# 1. 全量（15 场景，约 25 秒）
python -m pytest -v

# 2. 跑单个场景
python -m pytest -k "PP-RC-005" -v

# 3. 按标签跑（P0 / permission / snapshot / security / resolver）
python -m pytest -m "P0" -v
python -m pytest -m "permission" -v

# 4. 组合筛选
python -m pytest -k "PERM" -v                  # 所有权限场景
python -m pytest -k "RC-005 or SNAP-001" -v
```

---

## 三、环境配置

配置文件：`systems/tdm/config/env.sit.yaml`（UAT/生产时复制为 `env.uat.yaml` 修改）

| 配置项 | 当前值 | 何时修改 |
|--------|--------|----------|
| `tdm_base` | `http://sit-ha.fehorizon.com/femsp/hr-tdm` | 切换网关入口时 |
| `default_resource_code` | `VIEW_TELENT_SEARCH` | ⚠️ **UAT/生产必须改**为该环境权限中台实际注册的资源码（如 `TDM_SNAPSHOT_ARCHIVE`）；SIT 的 TDM 权限挂在 VIEW_TELENT_SEARCH |
| `accounts.default` | caiyunfei（TDM_ADMIN：业务单元/职层/纵向三维 ALL） | 换主测试账号时 |
| `accounts.no_access` | caiyunfei（配合假资源码 `SG_NONEXIST_RESOURCE` 模拟无权限） | fail-secure 场景专用，一般不动 |
| `accounts.restricted` | 未配置（PP-PERM-004 因此 SKIP） | 有真实受限账号（单平台权限）后取消注释填入 |
| `check_version_header` | false | 仅 sit-tdm 直连网关返回 X-Api-Version 头，sit-ha 会剥掉 |
| DB 密码 | 自动读 devops 凭据 | 可用环境变量 `SG_DB_PASSWORD` 覆盖 |
| SSO 密码 | SIT 统一密码 | 环境变量 `SG_SSO_PASSWORD` 覆盖 |

占位符语法：`${环境变量名:默认值}`。

---

## 四、场景文件结构（双层 YAML）

场景按目录自动发现（`scenarios/**/*.yaml`），无需注册。每个文件分两层：

```yaml
# ─────────── 人读层：doc（给 QA/产品看）───────────
id: PP-RC-008
title: 查询不存在人员：返回业务错误
priority: P1                  # P0 阻塞级 / P1 重要
tags: [resolver]              # resolver/permission/snapshot/security/prep
doc:
  given: 工号在 TDM/DHR 均不存在
  when: 调用 GET /api/employee/profile?empNo=99999999
  then: 返回业务错误（status≠200），不返回档案数据
  covers: [FR-001]            # 关联 Spec FR 编号
  related_ac: [AC-001]        # 关联验收标准

# ─────────── 机器读层：执行定义 ───────────
depends_on: []                # 依赖的上游场景 ID（见 §六）
flow:
  - select_emp: {role: snapshot_rich, save: emp}     # 工号池选号
  - fetch_permission: {account: default, save: scope} # 权限预言抓取（可选）
  - call:
      as: default               # 账号别名（env yaml accounts；none=匿名）
      method: GET
      path: /api/employee/profile
      params:
        empNo: "{{emp.no}}"                          # 插值：场景内变量
        resourceCode: "{{env.resource_code}}"        # 插值：环境配置
      save: resp
verify:
  - status: {eq: 200}                                # HTTP 状态码
  - json: {path: "$.data.basicInfo.empNo", eq: "{{emp.no}}"}  # JSON 路径断言
  - oracle: snapshot_frozen                          # DB 校对断言器（见 §五）
```

**插值规则**：`{{a.b.c}}` 点号路径取值，类型保留（数字不会变字符串）。`env.*` 来自环境配置，其余来自 `save` 的变量或上游场景。

---

## 五、内置能力速查

### 步骤处理器

| 步骤 | 作用 |
|------|------|
| `select_emp` | 工号池按角色选号（自动 DB 校验），附带最新 RESULT 快照上下文（activity_id/session_id/snapshot_type） |
| `fetch_permission` | 从 hr-center 抓取账号权限预言（corp/groupLevel/vm 三维），供权限断言器使用 |
| `call` | HTTP 调用（`as: none` 表示匿名不带 token） |
| `set_var` / `db_query` | 变量设置 / 只读 SQL（SELECT-only 守卫） |

### 工号池角色（`select_emp.role`）

| 角色 | 含义 |
|------|------|
| `snapshot_rich` | 快照数最多的人员 |
| `cross_platform` | 快照跨平台最多的人员 |
| `vertical_manager` | 有 use_vertical_manager=Y 盘点记录的人员 |
| `no_snapshot_tdm` | 员工表有、无快照（兜底路径） |
| `dhr_only` | DHR 有、TDM 无（降级路径） |

### DB 校对断言器（`oracle`）

| 断言器 | 用途 |
|--------|------|
| `profile_matches_db` | basicInfo ↔ tdm_emp_employee |
| `snapshot_frozen` | 状态型字段 ↔ 快照 JSON 严格比对；eval360Detail 已废弃正向断言为 null |
| `result_time_filtered` | 切片结果 ⊆ 全局模式 + inventory_date ≤ 当前活动时点过滤（需先 save 全局响应为 `resp_global`） |
| `dhr_fallback_matches` | DHR 降级 basicInfo ↔ dhr_employee 最新分区 |
| `permission_filtered` | corpCode 三维权限过滤（FR-013/015），支持 ALL/PART/无权限 fail-secure |
| `vm_filtered` | verticalManager 维度过滤（FR-016/017） |
| `inv_context_injected` | inv* 上下文注入（FR-006），annualPerf 反向校验不注入 |
| `trend_sorted_desc` | trend 接口按 inventoryDate 降序 |

### 场景类型说明

- **雪花 ID 数字/字符串归一化**：断言器内置 `_norm`（Long 序列化为 String 的公司惯例与 DB JSON 原始数字视为语义相等）
- **SKIP 语义**：工号池无候选、账号未配置等环境问题 → 场景 SKIP 而非 FAIL（测试数据缺失 ≠ 产品缺陷）

---

## 六、场景间依赖（depends_on）

**一个场景需要使用其他场景的查询结果作为入参时**：消费方声明 `depends_on`，被依赖方**零改动**（前提是它已 `save` 了你需要的变量且能独立 PASS）。

```yaml
# 消费方示例
depends_on: [PP-PREP-001]          # 执行器自动拓扑排序：先跑 PREP，PASS 后其 save 变量可引用
flow:
  - call:
      params:
        activityId: "{{PP-PREP-001.emp.activity_id}}"   # 引用上游 save 的变量
```

| 规则 | 说明 |
|------|------|
| 引用语法 | `{{上游场景ID.save变量名.嵌套字段}}` |
| 执行顺序 | 自动拓扑排序，多级依赖（A→B→C）闭包回溯，与文件位置无关 |
| 失败传播 | 上游非 PASS → 下游 BLOCKED（pytest 显示 skip，报告注明原因） |
| 会话内复用 | 同一上游在一次运行中只执行一次，多个下游共享其结果 |
| 循环检测 | 加载期发现循环依赖直接报错（带完整环路径） |
| 跨模块引用 | 依赖可跨目录（如 inventory 场景产出 sessionId，employee 场景消费） |

**两种"用前面结果"的区分**：

```yaml
# ① 同场景内步骤间传递（最常用，场景自包含可独立运行）
flow:
  - select_emp: {role: snapshot_rich, save: emp}
  - call: {params: {empNo: "{{emp.no}}"}, save: resp}

# ② 跨场景传递（前置数据准备昂贵或跨模块共享时）
depends_on: [PP-PREP-001]
```

**建议**：优先用①；只有前置准备昂贵（如导入 Excel 生成会话）或跨模块共享数据时才用②。准备类场景打 `tags: [prep]`，可用 `-m "not prep"` 跳过。

### 六之二、写型场景状态管理（shared / exclusive + teardown）

人力系统以工作流推进为主，写型场景（创建会话/导入/锁人/状态流转）会**消耗**上游产出的状态。
例如：上游产出 IN_PROGRESS 会话，消费者 A 把它推进到 COMPLETED——同样需要 IN_PROGRESS 的消费者 B 就不能复用这份。
为此 depends_on 支持消费模式声明：

```yaml
# 上游（写型 prep 场景）
id: IS-PREP-001
produces:                                # 可选：产出资源声明（文档化 + 报告展示）
  - {resource: inv_session, state: IN_PROGRESS}
flow:
  - call: {method: POST, path: /api/inventory/session, save: session}
teardown:                                # 清理钩子：session 末 LIFO 执行，可引用 flow 产出的变量
  - call: {method: POST, path: /api/inventory/session/void,
           json: {sessionId: "{{session.id}}"}}

# 下游：两种消费模式
depends_on:
  - PP-PREP-001                          # 字符串 = shared（只读，复用缓存实例，完全兼容现状）
  - {id: IS-PREP-001, mode: exclusive}   # 独占：为本场景新建一份全新实例，可变更其状态
```

| 语义 | 规则 |
|------|------|
| shared（默认） | 上游 session 内只执行一次，所有只读消费者共享同一实例 |
| exclusive | 每个独占消费者获得全新实例（懒重跑），变更不影响共享实例与其他独占者 |
| 实例绑定 | 消费者引用 `{{上游ID.x}}` 自动绑定到自己那份实例（含传递依赖，世界观一致） |
| 失败隔离 | 独占实例失败只 BLOCK 绑定它的消费者 |
| teardown | 声明 teardown 的场景每个已执行实例都登记清理；失败仅记 trace 不改 verdict |
| 报告 | 多实例落盘为 `cases/{id}_inst{n}.json`，run.json 含 instance_no/dep_mode |
| 守卫 | 被独占消费但无 teardown 的场景加载时告警（SIT 数据堆积风险） |

引擎语义由离线自测全覆盖（无需网络/DB）：`python -m pytest -k engine_modes -v`。
设计背景、决策过程与未实施部分（统一租约模型 LeaseRegistry、produces/consumes 调度器、并行化）
见 `docs/依赖状态管理设计-V3待实施.md`（含原始设计对话存档）。

---

## 七、当前场景清单（15 个）

目录：`scenarios/employee/person-profile/`，对应 Spec 模块 `employee/person-profile`（FR-001~FR-017）

| 场景 | 标题 | 断言要点 |
|------|------|----------|
| PP-RC-001 | 当前模式：职责链路由到全局聚合 | basicInfo ↔ 员工表 |
| PP-RC-002 | 员工表兜底（无快照有员工记录） | basicInfo ↔ 员工表 |
| PP-RC-003 | DHR 降级（TDM 无、DHR 有） | basicInfo ↔ dhr_employee |
| PP-RC-004 | 快照缺失自动回退全局聚合 | dataSource=GLOBAL |
| PP-RC-005 | 切片模式：快照冻结 + 结果时点过滤 | snapshot_frozen + result_time_filtered |
| PP-RC-006 | 切片指定无快照活动 → 回退最新快照 | 按实际行为校准 |
| PP-RC-007 | trend 接口盘点时间降序 | trend_sorted_desc |
| PP-SNAP-001 | 切片数据保真 | snapshot_frozen + result_time_filtered |
| PP-SNAP-002 | 切片快照覆盖正确性 | snapshot_frozen |
| PP-PERM-001 | 跨平台人员：corpCode 权限过滤 | permission_filtered |
| PP-PERM-002 | trend 接口权限过滤 | permission_filtered |
| PP-PERM-003 | verticalManager 维度过滤 | vm_filtered |
| PP-PERM-004 | 受限账号跨平台过滤 | ⏭ SKIP（待 restricted 账号） |
| PP-SEC-001 | 匿名访问被拒绝 | fail-secure |
| PP-SEC-002 | 无资源权限访问被拒绝（假资源码） | fail-secure |

---

## 八、目录结构

```
specguard/
├── pytest.ini                  # testpaths + markers（P0/P1/resolver/permission/snapshot/security）
├── conftest.py                 # 会话级夹具：环境加载/场景发现/报告生成
├── engine/                     # 通用引擎（系统无关）
│   ├── scenario_loader.py      #   YAML 场景加载
│   ├── dependency_graph.py     #   DAG 依赖图（循环检测/拓扑排序）
│   ├── scenario_runner.py      #   执行器（flow/verify/插值/依赖调度）
│   ├── http_client.py          #   HTTP 客户端（token/重试）
│   ├── token_provider.py       #   SSO 登录换 token（账号池）
│   ├── db_oracle.py            #   只读 DB 客户端（SELECT-only 守卫）
│   ├── execution_record.py     #   执行记录模型
│   ├── report_writer.py        #   报告生成（md + json）
│   └── registry.py             #   步骤/断言器/提供者注册表
├── systems/tdm/                # TDM 系统专属
│   ├── config/env.sit.yaml     #   环境配置（网关/账号池/资源码/DB）
│   ├── config.py               #   配置加载（占位符替换/凭据回退）
│   ├── steps.py                #   select_emp / fetch_permission
│   ├── oracles.py              #   DB 校对断言器
│   ├── queries.py              #   TDM 表查询封装
│   ├── emp_pool.py             #   工号池角色定义与校验
│   └── hr_center_oracle.py     #   hr-center 权限预言机
├── scenarios/                  # 场景库（按模块分目录，自动发现）
│   └── employee/person-profile/*.yaml
├── test_suites/                # pytest 入口（场景参数化）
└── reports/                    # 运行产物（时间戳目录，不入库）
```

---

## 九、Workbench 多用户部署（M6-M8）

工作台支持多用户 + RBAC（admin/tester/viewer 三角色），可部署到服务器为团队提供服务。

### 开发模式（本地热更新）

```powershell
pwsh start-workbench.ps1
# 后端 :9100（SG_AUTH_MODE=mock，默认无热重载——改后端代码需重跑本脚本，WS 聊天不受影响）
# 前端 :5173（热更新）
# 浏览器打开 http://localhost:5173 → mock 登录页输工号直接登录
# 需要后端热重载时加 -Reload（改代码自动重启，但 WS 聊天会断连重连）
```

### 生产模式（服务器部署）

```powershell
pwsh serve-prod.ps1                                            # SIT 联调
pwsh serve-prod.ps1 -UacBase 'http://ha.fehorizon.com/femsp/uac'  # 生产环境
# ① 依赖自检 + 前端构建（dist 过期自动重建）
# ② 单端口 :9100 托管 API + 前端（SG_AUTH_MODE=uac，集团 Authing SSO 登录）
# ③ 健康等待 + 部署检查清单输出
```

生产部署关键配置（环境变量）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `SG_AUTH_MODE` | `uac` | `uac`（集团 SSO）/ `mock`（本地开发降级） |
| `SG_UAC_BASE` | `http://sit-ha.fehorizon.com/femsp/uac` | UAC 地址（SIT 内网）；生产切换 `http://ha.fehorizon.com/femsp/uac` |
| `SG_ADMIN_ACCOUNTS` | 空 | 预置管理员（逗号分隔 AD 账号）；未设置时**首个登录用户自动成为 admin** |

硬约束：

- **uvicorn 必须 workers=1**：RunManager 全局单例 + SQLite，多 worker 会破坏执行队列与共享状态
- 执行并发模型为**全局 FIFO 队列**（running 时触发自动排队，完成后自动消费）
- 数据文件 `workbench/backend/data/workbench.db`（用户/授权/审计/队列/菜单，勿提交）
- 工作区治理：admin 注册 → 授权开通给用户 → 用户在顶栏选择器预选（可设个人默认）

## 菜单与角色授权（RBAC）

- 菜单树入库可配置（admin 默认仅「菜单管理 + 用户管理」，其余菜单由管理员在「菜单管理 → 角色授权」页签勾选开通）
- 自定义角色：管理员可新增/删除角色（内置 admin/tester/viewer/product 不可删），用户可被赋予任意角色组合
- 前后端双控：菜单授权同时控制侧边栏可见性与后端 API 访问（无权限直接输 URL 返回 403）
- 系统保护菜单（菜单管理/用户管理）：admin 的授权不可取消（自举保底）
- 逃生通道：admin 被锁死时直接改 SQLite——
  `sqlite3 workbench/backend/data/workbench.db "INSERT OR IGNORE INTO role_menus (role_key, menu_key) VALUES ('admin','menu-menu-manage')"`

---

## 十、待补项

1. **PP-PERM-004 SKIP**：在 `env.sit.yaml` 的 `accounts.restricted` 配置真实受限账号（单平台权限）即激活
2. **UAT 环境**：复制 `env.sit.yaml` → `env.uat.yaml`，修改 `tdm_base` / `default_resource_code` / SSO 域名 / DB 凭据（回退读 `DB_PASSWORD_UAT`）
3. **新模块扩展**：在 `scenarios/` 下按模块建目录放 YAML 即可；新断言器加到 `systems/tdm/oracles.py` 并在 `register_oracles` 注册
