# SpecGuard YAML 格式规范

> **版本**：1.4.1 | **更新时间**：2026-07-23 | **生成方式**：SpecGuard Workbench 自动生成
> **用途**：Agent 根据此规范生成合规的 test-case YAML 文件，SpecGuard 按此规范校验格式。

## 版本变更

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.4.1 | 2026-07-23 | 修复章节编号冲突（1.7/1.9 重复），步骤类型表补 poll 轮询 |
| 1.4.0 | 2026-07-23 | 新增变量插值数组下标、fn 内置函数、env.vars 环境变量段 |
| 1.3.0 | 2026-07-23 | 新增 random 随机步骤（随机数/随机文本/随机池抓取/UUID + HR 词库） |
| 1.2.0 | 2026-07-23 | 新增数据库查询校验实用语法（db_query 验证模板 + DB 连接配置） |
| 1.1.0 | 2026-07-23 | 新增 poll 轮询步骤、DB 断言（db_query 裸数组直通）、len_eq 断言、oracle 参数化形式 |
| 1.0.0 | 2026-07-22 | 初始版本：场景 YAML / 计划 YAML / 依赖与产出 / 变量引用 / ID 唯一性 |

---

## 一、场景测试 YAML（scenario yaml）

### 1.1 文件位置与命名

```
tests/specguard/scenarios/{模块}/{功能}/{场景ID}.yaml
```

### 1.2 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 场景唯一标识，全局不可重复（格式：`{模块前缀}-{类型}-{序号}`，如 `PP-RC-001`） |
| `title` | string | 场景标题（中文描述） |
| `flow` | list | 执行步骤列表（flow 和 verify 至少有一个非空） |

### 1.3 完整示例（场景测试 — 查询校验型）

```yaml
id: PP-RC-005
title: 切片模式查询历史盘点快照（快照冻结 + 结果时点过滤）
test_type: scenario
priority: P0
tags: [snapshot]
depends_on:
  - PP-RC-001                    # shared（默认，只读复用）
  - {id: IS-PREP-001, mode: exclusive}   # exclusive（独占实例，写型场景用）
produces:
  - {resource: inv_session, state: IN_PROGRESS}
doc:
  given: 人员 90024713 存在 RESULT 快照（活动 1936）
  when: GET /api/employee/profile?empNo=90024713&activityId=1936
  then: 档案数据来自快照 JSON（冻结），盘点结果按 inventory_date 时点过滤
  covers: [FR-002, FR-003]
flow:
  - select_emp: {role: snapshot_rich, save: emp}
  - fetch_permission: {account: default, save: scope}
  - call:
      as: default
      method: GET
      path: /api/employee/profile
      params:
        empNo: "{{emp.no}}"
        resourceCode: "{{env.resource_code}}"
      save: resp
  - call:
      as: default
      method: GET
      path: /api/employee/profile
      params:
        empNo: "{{emp.no}}"
        activityId: "{{emp.activity_id}}"
        resourceCode: "{{env.resource_code}}"
      save: resp_slice
verify:
  - status: {eq: 200}
  - json: {path: "$.data.basicInfo.empNo", eq: "{{emp.no}}"}
  - json: {path: "$.data.dataSource", eq: "SNAPSHOT"}
  - oracle: snapshot_frozen
  - oracle: result_time_filtered
teardown:
  - call:
      method: POST
      path: /api/inventory/session/void
      json: {sessionId: "{{resp.json.data.sessionId}}"}
```

### 1.4 完整示例（单元测试 — 数据准备型）

```yaml
id: IS-PREP-001
title: 创建盘点会话（Step1 数据准备）
test_type: unit
priority: P1
tags: [prep]
produces:
  - {resource: inv_session, state: IN_PROGRESS}
doc:
  given: 活动 ACTIVE 状态
  when: POST /api/inventory/session
  then: 返回会话 ID，状态 IN_PROGRESS
  covers: [FR-010]
flow:
  - select_emp: {role: snapshot_rich, save: emp}
  - call:
      method: POST
      path: /api/inventory/session
      json:
        activityId: "{{emp.activity_id}}"
        empNo: "{{emp.no}}"
      save: session
verify:
  - status: {eq: 200}
  - json: {path: "$.data.id", not_null: true}
  - json: {path: "$.data.sessionStatus", eq: "IN_PROGRESS"}
teardown:
  - call:
      method: POST
      path: /api/inventory/session/void
      json: {sessionId: "{{session.json.data.id}}"}
```

### 1.5 步骤类型（flow 步骤）

| 步骤类型 | 格式 | 产出变量 |
|----------|------|----------|
| `select_emp` | `{role, save, exclusive?}` | `save.no`（工号）, `save.role`, `save.activity_id`, `save.session_id`, `save.snapshot_type` |
| `fetch_permission` | `{account, resource_code?, save}` | `save.corp_codes`, `save.levels`, `save.vm_codes`, `save.has_any` |
| `call` | `{as?, method, path, params?, json?, save, timeout?}` | `save.status`（HTTP状态码）, `save.json`（响应JSON）, `save.headers` |
| `oss_upload` | `{file, save, tenant?, public?}` | `save.ossKey`（OSS文件key）, `save.fileName`, `save.fileSize` |
| `oss_download` | `{ossKey, save, output_dir?}` | `save.file_path`（本地路径）, `save.file_size`, `save.fileName` |
| `poll` | `{call, until, interval_ms?, timeout_ms?, on_timeout?, save}` | `save.status`, `save.json`, `save.headers`（末轮响应，结构同 call） |
| `random` | `{type, save, ...}` | 随机值（类型决定，见下表） |
| `set_var` | `{vars: {k: v}}` | vars 中每个 key 都是变量 |
| `db_query` | `{sql, save, note?}` | 查询结果行数组 |

### 1.6 OSS 附件工作流（上传→调用→下载→校验）

人力系统中 xlsx 附件处理是常见场景（Step4 导入、文件转换）。OSS 步骤让测试场景覆盖完整链路：

```yaml
flow:
  # 1. 上传源文件到 OSS
  - oss_upload: {file: "test-data/盘点产出汇总表.xlsx", save: src}
  # 产出: src.ossKey, src.fileName, src.fileSize

  # 2. 调用文件转换接口（传 ossKey）
  - call:
      method: POST
      path: /api/data-io/file-conversion/convert
      json:
        sourceOssKey: "{{src.ossKey}}"
      save: convert
  # 产出: convert.json.data.ossKey（结果文件 ossKey）

  # 3. 下载结果文件
  - oss_download: {ossKey: "{{convert.json.data.ossKey}}", save: result}
  # 产出: result.file_path, result.file_size, result.fileName

verify:
  - status: {eq: 200, of: convert}
  - json: {path: "$.data.ossKey", not_null: true, of: convert}
```

**ossKey 格式**：`{tenantId}/{yyyy}/{MM}/{dd}/{hash}_{原始文件名}`，如 `COREHR/2026/07/23/a1b2c3_盘点表.xlsx`。

### 1.7 DB 断言（db_query 结果直接断言）

`db_query` 步骤的产出（裸数组）可直接被 `json` 断言消费，无需经过 `call` 步骤：

```yaml
flow:
  - db_query:
      sql: SELECT total_score, rank_overall FROM tdm_eval_360
           WHERE session_id = {{session.json.data.id}} AND emp_no = '{{emp.no}}'
      save: score_rows
verify:
  - json: {of: score_rows, path: "$[0].total_score", eq: null}        # 分数为 NULL
  - json: {of: score_rows, path: "$[0].rank_overall", not_null: true} # 其余字段保留
  - json: {of: score_rows, path: "$", len_eq: 3}                       # 行数不丢
```

**原理**：`json` 断言的 `of` 指向 `db_query` 的 save 变量时，引擎自动识别裸数组并直接求值 JSONPath。`of` 指向 `call` 的 save 变量时取 `.json` 键（兼容存量行为）。

**数组长度断言**：用 `$` 作为 path（返回整个数组），配合 `len_eq` / `len_gt` 判断行数。

### 1.8 数据库查询校验实用语法

数据库连接在 `systems/tdm/config/env.sit.yaml` 的 `db` 段配置（Workbench 环境设置页可直接编辑）：

```yaml
db:
  host: "mysql-sit03.fehorizon.com"
  port: 3306
  user: "mcp_read"
  password: "${SG_DB_PASSWORD:}"
  name: "hr_center"
  charset: "utf8mb4"
```

**只读守卫**：仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN，拒绝多语句和写操作。

#### 常用验证语句模板

**验证数据入库**：
```yaml
- db_query:
    sql: SELECT COUNT(*) as cnt FROM tdm_inv_person WHERE session_id = {{session.json.data.id}} AND deleted = 0
    save: person_count
verify:
  - json: {of: person_count, path: "$[0].cnt", eq: 3}
```

**验证字段值**：
```yaml
- db_query:
    sql: SELECT leader_calibrated_placement FROM tdm_result_person_grid WHERE session_id = {{session.json.data.id}} AND emp_no = '{{emp.no}}'
    save: grid_row
verify:
  - json: {of: grid_row, path: "$[0].leader_calibrated_placement", eq: "0"}
```

**验证状态变更**：
```yaml
- db_query:
    sql: SELECT session_status, completed_at FROM tdm_inv_session WHERE id = {{session.json.data.id}}
    save: session_row
verify:
  - json: {of: session_row, path: "$[0].session_status", eq: "IN_PROGRESS"}
  - json: {of: session_row, path: "$[0].completed_at", eq: null}
```

**验证行数完整性**：
```yaml
- db_query:
    sql: SELECT * FROM tdm_result_person_eval WHERE session_id = {{session.json.data.id}} AND deleted = 0
    save: eval_rows
verify:
  - json: {of: eval_rows, path: "$", len_eq: 5}    # 5 条评价记录不丢
```

**验证快照冻结**：
```yaml
- db_query:
    sql: SELECT snapshot_json FROM tdm_snap_profile WHERE emp_id = {{emp.id}} AND activity_id = {{emp.activity_id}} AND deleted = 0
    save: snap_row
verify:
  - json: {of: snap_row, path: "$[0].snapshot_json", not_null: true}
```

**SQL 中的变量插值**：SQL 字符串支持 `{{save名.字段}}` 插值，引用前面步骤的 save 变量。

### 1.9 random 随机步骤

生成随机数据用于测试，避免硬编码导致的唯一性冲突：

```yaml
flow:
  - random: {type: number, min: 1, max: 100, save: score}              # 随机整数 1~100
  - random: {type: float, min: 60, max: 100, precision: 1, save: f}    # 随机浮点数 60.0~100.0
  - random: {type: text, pool: activity_name, save: act_name}          # 从词库随机选
  - random: {type: text, pool: person_name, suffix: true, save: name}  # 词库+随机后缀（如"张超-482"）
  - random: {type: uuid, save: uid}                                    # 8 位短 UUID
  - random: {type: pick, items: ["A", "B", "C"], save: choice}        # 自定义列表随机选
```

**随机文本池**（HR 领域自然语言词库）：

| 词库 | 内容示例 |
|------|----------|
| `activity_name` | 年度干部盘点、半年度人才盘点、季度绩效盘点、高潜人才盘点… |
| `department` | 研发部、产品部、市场部、人事部、财务部… |
| `person_name` | 张超、李明、王芳、赵强、陈静… |
| `eval_text` | 表现优秀，能力突出、工作认真负责，团队协作好… |
| `session_desc` | 常规盘点流程、年度例行盘点、重点关注高潜人员… |
| `tag` | 核心骨干、高潜人才、技术专家、管理后备… |

**suffix: true**：在词库文本后追加 3 位随机数字（如"张超-482"），保证唯一性。

### 1.10 poll 轮询步骤（异步任务等待）

Step4 导入等异步任务需要等待后台处理完成。`poll` 步骤重复调用直至条件满足：

```yaml
flow:
  - call: {method: POST, path: /api/data-io/import/excel/task/submit, json: {...}, save: submit}
  - poll:
      call:                                        # 复用 call 步骤全语法
        method: GET
        path: /api/data-io/import/task/result
        params: {taskNo: "{{submit.json.data.taskNo}}"}
      until:                                       # 复用 verify 断言语法子集
        - json: {path: "$.data.status", eq: "DONE"}
      interval_ms: 2000
      timeout_ms: 60000
      on_timeout: fail                             # fail（默认）| skip
      save: result                                 # 末次响应按 call 产出结构保存
verify:
  - status: {eq: 200, of: result}
```

**语义**：
- 每轮执行 call → 逐条评估 until 断言 → 全部通过即退出循环并 save；任一断言失败则间隔后重试
- 超时：`on_timeout: fail` → AssertionError（CAT_ASSERT）；`skip` → SkipScenario（CAT_ENV）
- 每轮调用落 StepTrace（含轮次号 `poll:1`, `poll:2`, ...），保证可审计

### 1.11 断言类型（verify 断言）

| 断言类型 | 格式 | 说明 |
|----------|------|------|
| `status` | `{of?, eq}` | HTTP 状态码断言（of 缺省为最后一个 call 的 save 名） |
| `json` | `{of?, path, eq}` | JSONPath 等于 |
| `json` | `{of?, path, ne}` | JSONPath 不等于 |
| `json` | `{of?, path, not_null: true}` | JSONPath 非 null |
| `json` | `{of?, path, contains}` | JSONPath 包含 |
| `json` | `{of?, path, len_gt: N}` | JSONPath 数组长度 > N |
| `json` | `{of?, path, len_eq: N}` | JSONPath 数组长度 = N |
| `json` | `{of?, path, absent: true}` | JSONPath 路径不存在 |
| `oracle` | `oracle_name` | DB 校对断言器（见下表） |
| `oracle` | `{name: xxx, params: {...}}` | 参数化断言器（引擎已支持） |

### 1.12 DB 校对断言器（oracle）

| 断言器 | 用途 |
|--------|------|
| `profile_matches_db` | basicInfo ↔ tdm_emp_employee |
| `snapshot_frozen` | 状态型字段 ↔ 快照 JSON 严格比对 |
| `result_time_filtered` | 切片结果时点过滤校验 |
| `dhr_fallback_matches` | DHR 降级 basicInfo ↔ dhr_employee |
| `permission_filtered` | corpCode 三维权限过滤（FR-013/015） |
| `vm_filtered` | verticalManager 维度过滤（FR-016/017） |
| `inv_context_injected` | inv* 上下文注入（FR-006） |
| `trend_sorted_desc` | trend 接口按 inventoryDate 降序 |

---

## 二、依赖与产出（DAG 关系声明）

### 2.1 depends_on — 声明上游依赖

```yaml
# 字符串形式 = shared（只读共享，上游 session 内只执行一次）
depends_on:
  - PP-RC-001

# 对象形式 = 可指定模式
depends_on:
  - {id: IS-PREP-001, mode: exclusive}   # 独占实例（写型场景，防止多消费者踩踏同一数据）
  - {id: PP-RC-001, mode: shared}        # 等价于字符串形式
```

**模式选择规则**：
- **shared**（默认）：只读消费上游结果（查询、校验）。上游执行一次，所有消费者共享。
- **exclusive**：变更消费上游结果（状态推进、数据修改）。上游为每个 exclusive 消费者新建独立实例。

### 2.2 引用上游变量

```yaml
flow:
  - call:
      params:
        activityId: "{{IS-PREP-001.session.json.data.id}}"   # 引用上游场景 save 的变量
        empNo: "{{PP-RC-001.emp.no}}"                        # 引用上游 select_emp 的工号
```

### 2.3 produces — 声明产出资源

```yaml
produces:
  - {resource: inv_session, state: IN_PROGRESS}   # 我产出了一个 IN_PROGRESS 状态的会话
  - {resource: inv_person, state: LOCKED}          # 我产出了锁定状态的人员
```

**resource 命名规则**：`{模块}_{实体}`，如 `inv_session`、`inv_person`、`eval_360`。
**state 命名规则**：大写蛇形，如 `IN_PROGRESS`、`COMPLETED`、`LOCKED`、`DRAFT`。

### 2.4 save — 步骤级产出变量

每个 flow 步骤的 `save` 字段声明了该步骤的产出变量名，后续步骤和下游场景通过 `{{save名.字段}}` 引用。

```yaml
flow:
  - select_emp: {role: snapshot_rich, save: emp}     # 产出 emp.no, emp.activity_id, ...
  - call: {method: GET, path: /api/employee/profile, save: resp}   # 产出 resp.status, resp.json
  # 后续步骤引用
  - call:
      method: GET
      path: "/api/employee/profile/{{emp.no}}"   # 引用同场景内变量
```

---

## 三、变量引用语法

### 3.1 同场景内变量

```
{{save名}}              — 引用整个 save 变量
{{save名.字段}}          — 引用 save 变量的字段
{{save名.嵌套.字段}}     — 多级嵌套
```

### 3.2 跨场景引用（上游变量）

```
{{上游场景ID.save名}}          — 引用上游场景的 save 变量
{{上游场景ID.save名.字段}}      — 引用上游 save 变量的字段
```

### 3.3 环境变量

```
{{env.resource_code}}         — 环境配置的默认资源码
{{env.vars.*}}                — env yaml 中 vars 自定义段的任意键
```

env yaml 的 `vars` 段可自定义环境差异常量：

```yaml
# systems/tdm/config/env.sit.yaml
vars:
  fixture_corp: {code: "1002", name: "远东租赁"}
  fixture_emp_nos: ["90024713", "90027339", "90027338"]
```

场景引用：`{{env.vars.fixture_corp.code}}`、`{{env.vars.fixture_emp_nos}}`（list 整体替换）。

### 3.4 fn 内置函数（运行时生成新值）

```
{{fn.timestamp}}    — 秒级时间戳（如 "1721740800"），用于唯一命名
{{fn.date}}         — 当前日期 YYYYMMDD（如 "20260723"）
{{fn.uuid_short}}   — 8 位短 UUID（如 "a3f2b1c9"）
```

**典型用法**（活动名全局唯一）：
```yaml
flow:
  - set_var: {vars: {activity_name: "SG导入校验-{{fn.timestamp}}"}}
  - call:
      method: POST
      path: /api/system/activities
      json: {activityName: "{{activity_name}}"}
```

### 3.5 数组元素访问

响应 JSON 含数组时，在 verify 断言中使用 JSONPath：

```yaml
verify:
  # 第一个元素的字段
  - json: {path: "$.data.gridPlacement[0].activityId", not_null: true}
  # 数组长度断言
  - json: {path: "$.data.gridPlacement.length()", len_gt: 0}
  # 数组中所有元素
  - json: {path: "$.data.list[*].empNo", contains: "90024713"}
```

在 flow 步骤参数中引用数组元素（使用 jsonpath 插值）：

```yaml
flow:
  - call:
      params:
        activityId: "{{resp.json.data.gridPlacement[0].activityId}}"
        personId: "{{persons_q.json.data.records[0].id}}"
        lastId: "{{rows[-1].id}}"
```

**数组下标支持**：`[0]` 正索引、`[-1]` 负索引、嵌套路径 `records[0].id`。

---

## 四、ID 唯一性规则

### 4.1 ID 命名格式

```
{模块前缀}-{类型}-{序号}
```

| 前缀 | 模块 | 示例 |
|------|------|------|
| `PP` | employee/person-profile | PP-RC-001 |
| `IS` | inventory/inventory-session | IS-PREP-001 |
| `IP` | inventory/inventory-person | IP-001 |
| `SS` | system-settings | SS-ACT-001 |
| `EV` | evaluation/eval-360 | EV-001 |

### 4.2 类型缩写

| 缩写 | 含义 | 用途 |
|------|------|------|
| `RC` | Resolver Chain | 职责链路由/兜底场景 |
| `SNAP` | Snapshot | 快照相关场景 |
| `PERM` | Permission | 权限过滤场景 |
| `SEC` | Security | 安全 fail-secure 场景 |
| `PREP` | Preparation | 数据准备场景（unit 类型） |

### 4.3 序号分配

序号从 001 开始递增，不可重复。使用 API 查询下一可用序号：

```
GET /api/reference/next-id?prefix=PP&type=RC
→ { "next_id": "PP-RC-008", "existing": ["PP-RC-001", ..., "PP-RC-007"] }
```

---

## 五、格式校验规则（TestCase Validation）

| 规则 | 级别 | 说明 |
|------|------|------|
| T1 | ERROR | YAML 可解析，有 id + flow/verify（不可为空） |
| T2 | WARN | test_type 必须为 unit/scenario（缺省为 scenario） |
| T3 | WARN | unit 类型必须有 output/produces 或 save 声明 |
| T4 | ERROR | depends_on 引用必须指向已存在的场景 ID |
| T5 | WARN | scenario 类型无 depends_on 且非 prep 标签 → 疑似孤例 |

---

## 六、工号池角色（select_emp.role）

| 角色 | 说明 | 候选数 |
|------|------|--------|
| `snapshot_rich` | 有快照记录的人员 | 5 |
| `cross_platform` | 快照跨 ≥2 平台的人员 | 5 |
| `vertical_manager` | use_vertical_manager=Y 的人员 | 2 |
| `no_snapshot_tdm` | TDM 员工表有、无快照 | 5 |
| `dhr_only` | 仅 DHR 存在（TDM 无记录） | 3 |
| `nonexistent` | 不存在的工号（404 场景） | 1 |

---

## 七、测试计划 YAML（plan yaml）

```yaml
id: post-launch-fixes
name: 上线后问题修复（第一批）
description: 修复上线后发现的 8 个 BUG
env: sit
tags: [imported, post-launch-fixes]
filter:
  scenarios:
    - PP-RC-001
    - PP-RC-005
    - PP-SNAP-001
breakpoints:
  - PP-RC-005          # 执行到 PP-RC-005 前暂停，人工确认后放行
source_delta: post-launch-fixes
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 计划唯一标识 |
| `name` | ✅ | 计划名称 |
| `filter.scenarios` | — | 显式场景 ID 列表 |
| `filter.tags` | — | 按标签过滤场景 |
| `breakpoints` | — | 断点场景 ID 列表（执行到该场景前暂停） |
| `source_delta` | — | 来源 delta 代号 |
| `env` | — | 目标环境（sit/uat），默认 sit |
