"""YAML 格式规范 2.0 生成器 + ID 唯一性校验。

格式 2.0 核心变化（2026-07-24 定稿）：
- 步骤语法冻结为 3 原语（call/db_query/poll）+ tool 信封，领域能力全部 tool 化
- 场景新增 version 字段（契约版本，MAJOR.MINOR；0.x=活跃 delta 快照期）
- depends_on 支持 version 期望（^X / X.Y）与 optional 可选依赖
- 新增流水线 verdict：DRIFT（契约版本漂移）/ ORPHANED（上游缺失），默认 SKIP 不阻塞
- 校验规则新增 T6（契约指纹变更但 version 未 bump → ERROR）

⚠️ 语法层（第一~七章）变更才需要递增版本号；tool 目录（第八章）由
engine.tool_registry 动态生成，新增 tool 不需要修改本文档。
"""

import os
import re
import sys
from pathlib import Path

import yaml

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from engine.tool_registry import catalog_dict, catalog_markdown  # noqa: E402

# 注册各系统包的 tool 元数据（导入即注册；失败时仅使用引擎内置 tool）
try:
    import systems.tdm.steps  # noqa: E402,F401
except Exception:
    pass

# 格式规范版本与变更记录
SPEC_VERSION = "2.6.0"
SPEC_UPDATED = "2026-08-13"
SPEC_CHANGELOG = [
    ("2.6.0", "2026-08-13", "FR 编号迭代命名限制落地（specstd，方案 A 终版双右锚解析）：迭代代号禁止含 '-'（字母/数字/下划线开头可含 '.'，S24/v2.5/2026Q3 合法），conformance STRUCT 强制；schema.py 新增 ITER_CODE_RE / FR_DELTA_ID_RE / parse_fr_delta_id"),
    ("2.5.0", "2026-08-07", "新增引擎内建断言器 schema_match（结构断言 fuzzy-match-lite，T-501）：#string/#number/#boolean/#null 类型标记、## 可选键、#[] 数组模式、键集严格嵌套递归；oracle 参数化形式调用，语法层零变更"),
    ("2.4.0", "2026-08-05", "归一化场景类型：废弃 test_type 字段（unit/scenario 二分抹除，统一为场景），删除 T2/T3 校验，T5 孤例规则改通用（无 depends_on 且非 prep 标签 → 疑似孤例）"),
    ("2.3.0", "2026-08-02", "新增 2.6 requires 执行依赖声明（accounts/env/upstream）与 T8 校验——执行前预检扫描器静态读取，弹窗前预警缺失账号/环境键；requires 不进契约指纹"),
    ("2.2.0", "2026-08-01", "K-055 微服务体系适配：call 新增 service 服务前缀路由；db_query 新增 schema 多库连接；新增 resolve_account/precheck_permission 工具；internal token 服务凭证"),
    ("2.1.0", "2026-07-24", "call 升级 Apifox 参数体系（headers/cookies/body_type: json/form/urlencoded/raw/binary）；新增 python 原语（flow/verify/teardown 三段可用）"),
    ("2.0.0", "2026-07-24", "格式 2.0：3 原语 + tool 信封；version 契约版本；depends_on 版本期望与 optional；DRIFT/ORPHANED verdict；T6 契约指纹校验"),
    ("1.4.1", "2026-07-23", "修复章节编号冲突（1.7/1.9 重复），步骤类型表补 poll 轮询"),
    ("1.4.0", "2026-07-23", "新增变量插值数组下标、fn 内置函数、env.vars 环境变量段"),
    ("1.3.0", "2026-07-23", "新增 random 随机步骤（随机数/随机文本/随机池抓取/UUID + HR 词库）"),
    ("1.2.0", "2026-07-23", "新增数据库查询校验实用语法（db_query 验证模板 + DB 连接配置）"),
    ("1.1.0", "2026-07-23", "新增 poll 轮询步骤、DB 断言（db_query 裸数组直通）、len_eq 断言、oracle 参数化形式"),
    ("1.0.0", "2026-07-22", "初始版本：场景 YAML / 计划 YAML / 依赖与产出 / 变量引用 / ID 唯一性"),
]


def generate_format_spec_md() -> str:
    """生成完整的 YAML 格式规范 Markdown 文档（语法层冻结 + tool 目录动态段）"""
    changelog_table = "\n".join(
        f"| {v} | {d} | {c} |" for v, d, c in SPEC_CHANGELOG
    )
    header = (
        f"# SpecGuard YAML 格式规范\n\n"
        f"> **版本**：{SPEC_VERSION} | **更新时间**：{SPEC_UPDATED} | **生成方式**：SpecGuard Workbench 自动生成\n"
        f"> **用途**：Agent 根据此规范生成合规的 test-case YAML 文件，SpecGuard 按此规范校验格式。\n"
        f"> **结构**：第一~七章为语法层（冻结，变更需递增版本号）；第八章为 tool 目录（引擎注册表动态生成）。\n\n"
        f"## 版本变更\n\n"
        f"| 版本 | 日期 | 变更 |\n"
        f"|------|------|------|\n"
        f"{changelog_table}\n\n"
        f"---\n\n"
    )
    return header + _BODY + _tool_catalog_section()


def _tool_catalog_section() -> str:
    return (
        "\n---\n\n## 八、tool 目录（引擎注册表动态生成）\n\n"
        "tool 是领域能力的插件化封装。新增能力 = 引擎/系统包注册新 tool，**语法层不变**。\n"
        "调用形式：`- tool: {use: 工具名, with: {参数...}, save: 变量名}`（save 可省略）。\n\n"
        + catalog_markdown()
        + "\n\n### 8.1 tool 调用示例\n\n"
        "```yaml\n"
        "flow:\n"
        "  - tool: {use: select_emp, with: {role: snapshot_rich}, save: emp}\n"
        "  - tool: {use: fetch_permission, with: {account: default}, save: scope}\n"
        "  - tool: {use: oss_upload, with: {file: \"test-data/x.xlsx\"}, save: up}\n"
        "  - tool: {use: random, with: {type: text, pool: activity_name, suffix: true}, save: act_name}\n"
        "  - tool: {use: set_var, with: {vars: {marker: \"SG-{{fn.timestamp}}\"}}}\n"
        "```\n"
    )


def get_tool_catalog() -> list:
    """tool 目录结构化数据（/api/reference/tools 用）"""
    return catalog_dict()


def generate_format_spec_skeleton() -> str:
    """生成 format_spec 骨架（T-507 激进档：常驻骨架 + read_format_spec 按需取细节）。

    骨架组成（目标 ~4KB）：
    - 标题 + 版本 + 使用指引（read_format_spec 取细节章节）
    - 章节索引（从 _BODY 标题行自动派生，防漂移）
    - 硬约束核心：1.2 必填字段 / 1.6 步骤语法 / 1.7 断言类型 全文
    - tool 目录（动态段，~0.5KB）

    骨架是 _BODY 的派生投影（标题行 + 指定章节原文），不手抄正文，
    语法层变更时骨架自动跟随——无第二事实源。
    """
    import re as _re
    lines = _BODY.splitlines()

    # 章节索引：从 _BODY 标题行派生（## 一、… / ### 1.x …）
    index: list[str] = []
    for line in lines:
        m = _re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2)
        if level == 2:
            index.append(f"- **{title}**")
        elif level == 3 and _re.match(r"^\d+\.\d+", title):
            index.append(f"  - {title}")
    index_text = "\n".join(index)

    # 硬约束核心：提取 1.2 / 1.6 / 1.7 三个关键章节原文（到下一同级标题）
    def _chapter(chapter: str) -> str:
        out: list[str] = []
        capture = False
        for line in lines:
            m = _re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
            if m:
                if capture and len(m.group(1)) <= 3:
                    break
                if not capture and m.group(2).startswith(chapter):
                    capture = True
            if capture:
                out.append(line)
        return "\n".join(out)

    core = "\n\n".join(_chapter(c) for c in ("1.2 ", "1.6 ", "1.7 "))

    return (
        f"# SpecGuard YAML 格式规范（骨架）\n\n"
        f"> **版本**：{SPEC_VERSION} | **更新时间**：{SPEC_UPDATED}\n"
        f"> **用法**：本骨架为常驻摘要；写场景前用 `read_format_spec(section=…)` 取所需章节全文"
        f"（章节号或标题子串，如 1.6/2.1/3.2/八）。\n\n"
        f"## 章节索引\n\n{index_text}\n\n---\n\n"
        f"## 硬约束核心\n\n{core}\n\n---\n\n"
        f"{_tool_catalog_section()}\n"
    )


def generate_format_spec_product() -> str:
    """生成产品友好的格式规范（仅含 Spec 模板结构与 FR/AC 写作规范，
    不含执行层技术细节——供 requirement_interview 等产品用途使用）。
    """
    import re as _re
    lines = _BODY.splitlines()

    def _chapter(chapter: str) -> str:
        out: list[str] = []
        capture = False
        for line in lines:
            m = _re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
            if m:
                if capture and len(m.group(1)) <= 3:
                    break
                if not capture and m.group(2).startswith(chapter):
                    capture = True
            if capture:
                out.append(line)
        return "\n".join(out)

    # 仅含产品关心的章节：必填字段 + ID 唯一性规则
    core = "\n\n".join(_chapter(c) for c in ("1.2 ", "四、"))

    NL = chr(10)
    return (
        f"# Spec 编写规范{NL}{NL}"
        f"> **版本**：{SPEC_VERSION} | **更新时间**：{SPEC_UPDATED}{NL}"
        f"> 本规范面向需求面试与 Spec 编写任务：列出 Spec 文档的结构模板、"
        f"FR/AC 写作约定和场景锚点规则；"
        f"> 执行层细节（步骤语法/断言类型/tool 目录/轮询/DB 断言等）不在此处，{NL}"
        f"> 属于研发与测试的工作范畴。{NL}{NL}"
        f"## Spec 文档结构模板（11 章节）{NL}{NL}"
        f"| 序号 | 章节 | 作者 | 说明 |{NL}"
        f"|------|------|------|------|{NL}"
        f"| §1 | Goal（一句话目标） | 🧑\u200d💼💻 | 产品 + 技术共同 |{NL}"
        f"| §2 | Non-Goals（明确排除） | 🧑\u200d💼💻 | 防止范围蔓延 |{NL}"
        f"| §3 | User Scenarios | 🧑\u200d💼 | Given/When/Then，P1/P2/P3 |{NL}"
        f"| §4 | Functional Requirements | 🧑\u200d💼💻 | FR-xxx 编号 |{NL}"
        f"| §5 | Key Entities | 💻 | 表结构摘要 + 状态流转图 |{NL}"
        f"| §6 | Edge Cases | 🧑\u200d💼 | 空数据/重复/并发/权限/边界 |{NL}"
        f"| §7 | API Contract | 💻 | 5 列表格 + YAML 链接 |{NL}"
        f"| §8 | Acceptance Criteria | 🧑\u200d💼 | 二值化 AC |{NL}"
        f"| §9 | Deliverables | 💻 | 交付清单 |{NL}"
        f"| §10 | Rollout & Rollback | 💻 | 上线/回滚/数据兼容 |{NL}"
        f"| §11 | Changelog | 💻 | 版本变更记录 |{NL}"
        f"{NL}"
        f"使用 `templates/spec.md` 查看完整模板。{NL}{NL}"
        f"---{NL}{NL}"
        f"## FR/AC 写作约定{NL}{NL}"
        f"- **FR（Functional Requirement）**：以「系统 SHALL」开头，可独立验证的单条业务规则{NL}"
        f"- **AC（Acceptance Criteria）**：二值化（通过/不通过），对应一个或多个 FR{NL}"
        f"- **FR 编号**：基线 `FR-{序号}`（模块内唯一）；delta 新增 `FR-{功能}-{迭代}-{流水号}`{NL}"
        f"   （如 FR-person-profile-0817-001），全局唯一、永久保留（编号即溯源）。{NL}"
        f"   功能=模块目录名（可含 `-`，同前缀子模块如 person-search / person-search-v2 共存无歧义）；{NL}"
        f"   流水=恒 3 位数字；迭代=delta 代号——**禁止含 `-`**（字母/数字/下划线开头、可含 `.`：{NL}"
        f"   0817/S24/v2.5 合法，`2026-08-17` 非法请转写 `2026_08_17`），conformance STRUCT 强制校验{NL}"
        f"- **covers 锚点**：场景 YAML 的 `doc.covers` 引用 FR 编号，{NL}"
        f"  是场景与需求的强制关联（场景测试引擎据此做覆盖分析）{NL}"
        f"- **Delta 更新**：用 `[delta:代号]` 标记每条 FR 的变更来源{NL}{NL}"
        f"---{NL}{NL}"
        f"## 必填字段（场景 YAML）{NL}{NL}{_chapter('1.2 ')}"
        f"---{NL}{NL}"
        f"## ID 命名规则{NL}{NL}{_chapter('四、')}"
    )


_BODY = """## 一、场景测试 YAML（scenario yaml）

### 1.1 文件位置与命名

```
scenarios/{模块}/{功能}/{场景ID}.yaml
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
version: 0.1
title: 切片模式查询历史盘点快照（快照冻结 + 结果时点过滤）
priority: P0
tags: [snapshot]
depends_on:
  - {id: PP-RC-001, version: ^0}                      # shared（默认，只读复用）
  - {id: IS-PREP-001, mode: exclusive, version: ^0}   # exclusive（独占实例，写型场景用）
produces:
  - {resource: inv_session, state: IN_PROGRESS}
doc:
  given: 人员 90024713 存在 RESULT 快照（活动 1936）
  when: GET /api/employee/profile?empNo=90024713&activityId=1936
  then: 档案数据来自快照 JSON（冻结），盘点结果按 inventory_date 时点过滤
  covers: [FR-002, FR-003]
flow:
  - tool: {use: select_emp, with: {role: snapshot_rich}, save: emp}
  - tool: {use: fetch_permission, with: {account: default}, save: scope}
  - call:
      as: default
      method: GET
      path: /api/employee/profile
      params:
        empNo: "{{emp.no}}"
        resourceCode: "{{env.resource_code}}"
      save: resp
verify:
  - status: {eq: 200}
  - json: {path: "$.data.basicInfo.empNo", eq: "{{emp.no}}"}
  - json: {path: "$.data.dataSource", eq: "SNAPSHOT"}
  - oracle: snapshot_frozen
teardown:
  - call:
      method: POST
      path: /api/inventory/session/void
      json: {sessionId: "{{resp.json.data.sessionId}}"}
```

### 1.4 完整示例（数据准备型场景）

```yaml
id: IS-PREP-001
version: 0.1
title: 创建盘点会话（Step1 数据准备）
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
  - tool: {use: select_emp, with: {role: snapshot_rich}, save: emp}
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

### 1.5 版本字段（version）

每个场景声明自己的**契约版本**（Maven 风格 MAJOR.MINOR）：

| 变更类型 | 版本动作 | 例子 |
|----------|----------|------|
| 契约破坏性变更（删产出资源 / 改 save 变量名 / covers 移除 FR） | **bump MAJOR** | `1.2` → `2.0` |
| 契约兼容增强（新增产出 / 新增 save 变量 / covers 追加 FR） | **bump MINOR** | `1.2` → `1.3` |
| 契约无关改动（改断言阈值 / 修 doc 描述 / 调 flow 步骤） | 不动版本 | — |

**生命周期**：
- `0.x` = 活跃 delta 快照期（SNAPSHOT 语义）：契约可变，下游 `^0` 期望宽容匹配
- delta 归档时 bump 到 `1.0` 冻结为 release
- 归档后契约变更必须 bump MAJOR（T6 规则机器强制）

**契约 = produces（资源+状态） + save 输出变量名 + doc.covers（FR 列表）**。引擎对
每个场景计算契约指纹（sha256-12），与 `contracts_baseline.json` 基线比对（见 T6）。

### 1.6 步骤语法：4 原语 + tool 信封

flow/teardown 的每个步骤是单键 dict。语法层**冻结**为以下 5 种：

| 步骤类型 | 格式 | 产出变量 |
|----------|------|----------|
| `call` | `{as?, service?, method, path, params?, headers?, cookies?, body_type?, json?/form?/urlencoded?/raw?/file?, save, timeout?}` | `save.status`、`save.json`、`save.headers` |
| `db_query` | `{sql, schema?, save, note?}` | 查询结果行数组（裸数组，可直接被 json 断言消费） |
| `poll` | `{call, until, interval_ms?, timeout_ms?, on_timeout?, save}` | 末轮响应（结构同 call） |
| `python` | `{script 或 file, save?}` | `output` 变量 / `ns` 直写 / `save(k,v)` |
| `tool` | `{use, with?, save?}` | 由工具声明决定（见第八章 tool 目录） |

**call 原语（Apifox 风格参数体系）**：
- `as`：账号别名（default 等），`none`/`anonymous` 表示不带 token 的匿名调用；`internal` = internal token 服务凭证（K-055，无用户身份，限参数驱动接口）
- `service`：服务前缀路由（K-055，默认 tdm）——取 env 配置 `{service}_base`（如 hr_center/oss/uac），场景只写服务内相对路径，服务段不再丢失
- `headers` / `cookies`：KV dict，支持 `{{var}}` 插值；`headers` 可显式覆盖 `Authorization`（负向测试用）
- `body_type`（默认按 `json` 字段推断）：

| body_type | 字段 | 说明 |
|-----------|------|------|
| `json`（默认） | `json: {...}` | application/json |
| `form` | `form: {k: v, file_field: "@path"}` | multipart；`@` 前缀值=文件上传字段 |
| `urlencoded` | `urlencoded: {k: v}` | application/x-www-form-urlencoded |
| `raw` | `raw: "文本"` + `content_type`（默认 text/plain） | 原始文本 body |
| `binary` | `file: "path/to/file"` | 文件字节流 body（octet-stream） |

- `db_query.sql`：只读 SELECT/SHOW/DESCRIBE/EXPLAIN，支持 `{{var}}` 插值
- `db_query.schema`：多库连接名（K-055，默认 default）——env db 段 dict-of-dicts 的键（如 default=hr_center / tdm / uac），未配置该连接时场景 SKIP
- `poll`：异步轮询。`on_timeout: fail`（默认，AssertionError）| `skip`（SKIP 场景）；每轮调用落 StepTrace（`poll:1`, `poll:2`...）

### 1.7 断言类型（verify 断言）

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
| `oracle` | `oracle_name` | DB 校对断言器（见 1.8） |
| `oracle` | `{name: xxx, params: {...}}` | 参数化断言器 |

### 1.8 DB 校对断言器（oracle）

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

### 1.8.1 引擎内建断言器：schema_match（结构断言）

`schema_match` 按结构模板断言响应形状（fuzzy-match-lite，Karate 子集），适合「字段集合与类型稳定、具体值不固定」的接口：

```yaml
verify:
  - oracle:
      name: schema_match
      params:
        of: createResp            # save 引用，缺省 resp；call 产出取 json，其余裸值直通
        spec:
          code: 200
          data:
            id: "#number"
            name: "#string"
            tags: "#[] #string"   # 数组模式：每元素为 string，空数组通过
            remark: "##string"    # 可选键：可缺席，出现则必须是 string
```

| 标记 | 语义 |
|------|------|
| `#string` / `#number` / `#boolean` / `#null` | 类型标记（`#number` 不匹配 true/false） |
| `##key` | 可选键（缺席通过，出现按规则匹配） |
| `#[] <rule>` | 数组模式，每元素匹配 rule，空数组通过 |
| 其他字面值 | 精确相等（==，bool 与数字不混） |

**键集严格**：对象多出未声明键即失败（结构漂移检测核心语义），嵌套递归全程生效；失败消息定位到字段级路径（如 `$.data.list[2].status: 期望 #string，实际 42`）。
**明确不支持**：`#regex`、`#?` JS 表达式、`#(var)` 引用、`#present`——写出即断言失败并提示支持的标记集。

### 1.9 DB 断言（db_query 裸数组直通）

`db_query` 步骤的产出（裸数组）可直接被 `json` 断言消费：

```yaml
flow:
  - db_query:
      sql: SELECT total_score, rank_overall FROM tdm_eval_360
           WHERE session_id = {{session.json.data.id}} AND emp_no = '{{emp.no}}'
      save: score_rows
verify:
  - json: {of: score_rows, path: "$[0].total_score", eq: null}
  - json: {of: score_rows, path: "$", len_eq: 3}
```

**原理**：`json` 断言的 `of` 指向 `db_query` 的 save 变量时，引擎自动识别裸数组并直接求值 JSONPath；
指向 `call` 的 save 变量时取 `.json` 键。数组长度断言用 `$` 作为 path 配合 `len_eq` / `len_gt`。

### 1.10 数据库查询校验实用语法

数据库连接在 `systems/tdm/config/env.sit.yaml` 的 `db` 段配置（Workbench 环境设置页可直接编辑）。
**只读守卫**：仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN，拒绝多语句和写操作。

常用模板：

```yaml
# 验证数据入库行数
- db_query:
    sql: SELECT COUNT(*) as cnt FROM tdm_inv_person WHERE session_id = {{session.json.data.id}} AND deleted = 0
    save: person_count
verify:
  - json: {of: person_count, path: "$[0].cnt", eq: 3}

# 验证状态变更
- db_query:
    sql: SELECT session_status, completed_at FROM tdm_inv_session WHERE id = {{session.json.data.id}}
    save: session_row
verify:
  - json: {of: session_row, path: "$[0].session_status", eq: "IN_PROGRESS"}
```

### 1.11 OSS 附件工作流（上传→调用→下载→校验）

```yaml
flow:
  - tool: {use: oss_upload, with: {file: "test-data/盘点产出汇总表.xlsx"}, save: src}
  - call:
      method: POST
      path: /api/data-io/file-conversion/convert
      json: {sourceOssKey: "{{src.ossKey}}"}
      save: convert
  - tool: {use: oss_download, with: {ossKey: "{{convert.json.data.ossKey}}"}, save: result}
verify:
  - status: {eq: 200, of: convert}
  - json: {path: "$.data.ossKey", not_null: true, of: convert}
```

**ossKey 格式**：`{tenantId}/{yyyy}/{MM}/{dd}/{hash}_{原始文件名}`。

### 1.12 poll 轮询步骤（异步任务等待）

```yaml
flow:
  - call: {method: POST, path: /api/data-io/import/excel/task/submit, json: {...}, save: submit}
  - poll:
      call:
        method: GET
        path: /api/data-io/import/task/result
        params: {taskNo: "{{submit.json.data.taskNo}}"}
      until:
        - json: {path: "$.data.status", eq: "DONE"}
      interval_ms: 2000
      timeout_ms: 60000
      on_timeout: fail
      save: result
```

### 1.13 python 原语（复杂逻辑逃生舱）

flow/teardown 中可嵌入 Python 脚本处理插值无法表达的复杂逻辑（对齐 Dify code 节点定位）：

```yaml
flow:
  - python:
      script: |
        rows = ns['rows']
        output = [r for r in rows if r['total_score'] is None]
        print(f'过滤出 {len(output)} 行')
      save: null_rows        # 可选：取脚本 output 变量注入 ns
  # 或引用外部文件（相对 specguard 根目录）
  - python: {file: "scripts/normalize.py", save: out}
```

**verify 中断言脚本**：

```yaml
verify:
  - python: |
      rows = ns['rows']
      assert len(rows) == 3, f"期望 3 行，实际 {len(rows)}"
      assert rows[0]['total_score'] is None, "首行分数应为 NULL"
```

**脚本可用上下文**：

| 名称 | 说明 |
|------|------|
| `ns` | 变量命名空间 dict（直接读写；`ns['x']=1` 对下游步骤与场景可见） |
| `save(k, v)` | 等价 `ns[k] = v` |
| `output` | 约定产出变量（step 声明 `save` 时被取走） |
| `rctx` / `record` | 运行上下文 / 执行记录 |
| `http(account)` | 取 HTTP 客户端（含 token，可发任意请求） |
| `db` | 只读 DB 连接（不可用时为 None） |
| `fn` | 内置函数：`fn.timestamp()` / `fn.date()` / `fn.uuid_short()` |
| `json` / `re` / `time` / `datetime` / `uuid` | 预导入模块 |
| `SkipScenario` | 主动跳过场景（`raise SkipScenario('原因', category='pool_empty')`） |
| `print` | 输出捕获进 StepTrace |

**断言语义**：脚本抛 `AssertionError` → 断言失败（CAT_ASSERT）；其他异常 → CAT_ENV。

---

## 二、依赖与产出（DAG 关系声明）

### 2.1 depends_on — 声明上游依赖

```yaml
depends_on:
  - PP-RC-001                                            # 字符串形式 = shared + 接受任意版本
  - {id: PP-RC-001, version: ^1}                         # 版本期望：同主版本兼容（推荐）
  - {id: IS-PREP-001, mode: exclusive, version: ^0}      # 独占实例 + 快照期宽容匹配
  - {id: PP-SNAP-001, version: 1.2}                      # 精确锁定（强耦合场景）
  - {id: XX-001, optional: true}                         # 可选依赖：缺失时场景 SKIP 而非 ORPHANED
```

**字段语义**：
- `mode`：`shared`（默认，只读共享，上游 session 内只执行一次）/ `exclusive`（为本消费者新建独立实例，写型场景用）
- `version`：契约版本期望。`^X` = 同主版本兼容（**推荐默认值**）；`X.Y` = 精确锁定（实际 minor 更高时放行 + INFO）；省略 = 接受任意版本（lint 提示补全）
- `optional`：`true` 时上游缺失 → 场景 SKIP（两种 strict 模式一致）

### 2.2 依赖版本仲裁（DRIFT / ORPHANED verdict）

执行前的依赖版本检查结果：

| 状态 | 触发条件 | 默认行为 | strict_deps 模式 |
|------|----------|----------|------------------|
| match | 期望满足 | 正常执行 | 同左 |
| minor_drift | 精确期望，实际 minor 更高 | 执行 + INFO（record.given.dep_version_note） | 同左 |
| **major_drift** | 主版本不符 / 精确期望高于实际 | verdict=**DRIFT** → SKIP + 报告，**不阻塞流水线** | 退化为 BLOCKED |
| **orphan** | 上游场景不存在 | verdict=**ORPHANED** → SKIP + 报告 | 退化为 BLOCKED |
| orphan + optional | 可选依赖缺失 | verdict=SKIP | 同左 |

**strict_deps 启用方式**：`pytest --strict-deps` 或环境变量 `SG_STRICT_DEPS=1`（发版门禁用）。

### 2.3 引用上游变量

```yaml
flow:
  - call:
      params:
        activityId: "{{IS-PREP-001.session.json.data.id}}"
        empNo: "{{PP-RC-001.emp.no}}"
```

### 2.4 produces — 声明产出资源

```yaml
produces:
  - {resource: inv_session, state: IN_PROGRESS}
  - {resource: inv_person, state: LOCKED}
```

**resource 命名规则**：`{模块}_{实体}`；**state 命名规则**：大写蛇形。
produces 是契约的一部分：删改产出 = MAJOR bump。

### 2.5 save — 步骤级产出变量

每个步骤的 `save` 声明产出变量名，后续步骤和下游场景通过 `{{save名.字段}}` 引用。
save 变量名是契约的一部分：改名 = MAJOR bump，新增 = MINOR bump。

### 2.6 requires — 声明执行依赖（可选，2.3.0 起）

声明本场景执行所依赖的账号别名、环境键与上游变量来源——供**执行前预检**扫描器
静态读取（选中场景后、确认执行弹窗前，缺失项先行预警，避免跑完才 SKIP）：

```yaml
requires:
  accounts: [platformNoCorp]      # flow as:/fetch_permission 引用的账号别名（须在 env accounts 定义）
  env: [resource_code]            # {{env.*}} 引用的环境键（顶层键或 vars.xxx 点号路径）
  upstream: [IS-PREP-001]         # {{上游ID.*}} 变量来源场景（须已在 depends_on 声明）
```

**字段语义**：
- `accounts`：账号别名清单。别名必须能在当前环境 `env.{env}.yaml` 的 `accounts` 段找到；
  缺失时引擎运行期会 SKIP（诚实语义），预检提前暴露
- `env`：环境键点号路径（`resource_code` / `vars.xxx` / `tdm_base` 等）。缺失时引擎运行期
  按步骤类型 SKIP 或报环境配置缺口，预检提前暴露
- `upstream`：跨场景变量引用的来源场景 ID（`{{IS-PREP-001.session.json.data.id}}` 的
  `IS-PREP-001`）。必须已在 `depends_on` 声明，否则校验报错

**约束**：
- `requires` 是**执行依赖声明**，不是契约产出——**不进契约指纹**（指纹 = produces + save + covers），
  增删 requires 无需 bump version
- 未声明时预检扫描器会**静态兜底**：从 flow/verify 文本正则提取 `as:` 账号别名、
  `{{env.*}}` 环境键与 `{{上游ID.*}}` 跨场景引用，声明与静态提取合并去重
- 存量场景未声明 requires 亦可预检（静态兜底），新写场景建议声明

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

### 3.4 fn 内置函数（运行时生成新值）

```
{{fn.timestamp}}    — 秒级时间戳，用于唯一命名
{{fn.date}}         — 当前日期 YYYYMMDD
{{fn.uuid_short}}   — 8 位短 UUID
```

**典型用法**：`- tool: {use: set_var, with: {vars: {activity_name: "SG导入校验-{{fn.timestamp}}"}}}`

### 3.5 数组元素访问

verify 断言用 JSONPath：`$.data.list[0].id`、`$.data.list.length()`、`$.data.list[*].empNo`。
flow 参数插值支持数组下标：`{{resp.json.data.records[0].id}}`、`{{rows[-1].id}}`（正/负索引、嵌套路径）。

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
| `PREP` | Preparation | 数据准备场景 |

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
| T4 | ERROR | depends_on 引用必须指向已存在的场景 ID |
| T5 | WARN | 无 depends_on 且非 prep 标签 → 疑似孤例 |
| T6 | ERROR | 契约指纹已变更但 version 未 bump（比对 contracts_baseline.json） |
| T7 | WARN | 依赖未声明版本期望（接受任意版本），建议补 version: ^X |

**T8 补充（2.3.0）**：`requires` 段格式校验：
- `accounts` 非空字符串数组；`env` 为点号路径（`vars.xxx` 合法）；`upstream` 必须指向
  已存在场景 ID **且**已在 `depends_on` 声明（否则 ERROR）
- requires 不进契约指纹（指纹 = produces + save + covers），增删无需 bump version

**T6 补充**：version 已 bump 但契约未变化 → WARN（冗余 bump）；新场景未入基线 → INFO（需更新基线）。
基线文件 `contracts_baseline.json` 随 git 提交，由迁移脚本或发布检查流程更新。

---

## 六、工号池角色（select_emp.role）

| 角色 | 说明 |
|------|------|
| `snapshot_rich` | 有快照记录的人员 |
| `cross_platform` | 快照跨 ≥2 平台的人员 |
| `vertical_manager` | use_vertical_manager=Y 的人员 |
| `no_snapshot_tdm` | TDM 员工表有、无快照 |
| `dhr_only` | 仅 DHR 存在（TDM 无记录） |
| `nonexistent` | 不存在的工号（404 场景） |

---

## 七、测试计划 YAML（plan yaml）

```yaml
id: post-launch-fixes
name: 上线后问题修复（第一批）
description: 修复上线后发现的 8 个 BUG
env: sit
tags: [imported, post-launch-fixes]
strict_deps: false        # true 时 DRIFT/ORPHANED 退化为 BLOCKED（发版门禁）
filter:
  scenarios:
    - PP-RC-001
    - PP-RC-005
    - PP-SNAP-001
breakpoints:
  - PP-RC-005
source_delta: post-launch-fixes
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 计划唯一标识 |
| `name` | ✅ | 计划名称 |
| `filter.scenarios` | — | 显式场景 ID 列表 |
| `filter.tags` | — | 按标签过滤场景 |
| `strict_deps` | — | 严格依赖模式（默认 false） |
| `breakpoints` | — | 断点场景 ID 列表（执行到该场景前暂停） |
| `source_delta` | — | 来源 delta 代号 |
| `env` | — | 目标环境（sit/uat），默认 sit |
"""


def get_next_scenario_id(prefix: str = "", type_abbr: str = "") -> dict:
    """获取下一可用场景 ID

    扫描全部场景 YAML，找到指定前缀+类型的最大序号，返回下一可用 ID。
    """
    scenarios_dir = SG_ROOT / "scenarios"
    existing = []
    max_num = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-{re.escape(type_abbr)}-(\d+)$") if prefix and type_abbr else None

    for dirpath, _dirs, filenames in os.walk(scenarios_dir):
        for fn in filenames:
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                sid = raw.get("id", "")
                if not sid:
                    continue
                existing.append(sid)
                if pattern:
                    m = pattern.match(sid)
                    if m:
                        max_num = max(max_num, int(m.group(1)))
            except Exception:
                continue

    next_id = f"{prefix}-{type_abbr}-{max_num + 1:03d}" if prefix and type_abbr else ""
    return {
        "next_id": next_id,
        "next_num": max_num + 1,
        "existing": sorted(existing),
        "total": len(existing),
    }


def validate_scenario_id(scenario_id: str) -> dict:
    """校验场景 ID 是否唯一"""
    scenarios_dir = SG_ROOT / "scenarios"
    conflicts = []
    for dirpath, _dirs, filenames in os.walk(scenarios_dir):
        for fn in filenames:
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                if raw.get("id") == scenario_id:
                    conflicts.append(str(Path(path).relative_to(scenarios_dir)))
            except Exception:
                continue
    return {
        "id": scenario_id,
        "unique": len(conflicts) == 0,
        "conflicts": conflicts,
    }
