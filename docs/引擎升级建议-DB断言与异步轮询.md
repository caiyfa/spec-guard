# SpecGuard 引擎能力升级建议报告

> **提交对象**：SpecGuard 引擎提供者（engine/ + workbench 维护方）
> **提交人**：TDM 测试场景使用方
> **日期**：2026-07-23
> **驱动需求**：三个已实现 P0 功能亟待编写自动化测试用例（① 360 导入数值校验取消、空值可导入且不丢其余数据；② 九宫格落位校验支持 0 / "-"；③ 已完成会话退回按钮），其中两个为 Excel 导入场景，对引擎提出 DB 断言与异步轮询两项硬性能力要求。
> **结论摘要**：OSS 附件能力（v1.0 规范 §1.6）与引擎实现一致、够用；但断言层存在 2 个高优先级缺口、文档存在 3 处落后。建议按 P0→P2 分三批实施，全部为向后兼容的增量改动，预估总工作量 3~5 人日。

---

## 一、现状架构评估（值得保持的设计）

引擎核心（`tests/specguard/engine/`）与系统适配层（`tests/specguard/systems/tdm/`）通过 **Registry 三张注册表** 解耦：

- `registry.step(name, handler)` — 步骤处理器（`engine/registry.py`）
- `registry.oracle(name, fn)` — DB 校对断言器，失败抛 `AssertionError`
- 系统侧经 `systems/tdm/__init__.py::register()` 钩子注入 TDM 专属步骤（select_emp / fetch_permission / oss_upload / oss_download）与 8 个断言器

该设计使本次升级**无需改动任何系统适配层代码**，所有能力补充均可收口在引擎核心 + 规范文档。OSS 步骤定义（规范 §1.5/§1.6）与 `systems/tdm/steps.py` 实现逐项核对一致，环境配置（`env.sit.yaml` 的 `oss_base` / `oss_download_base`）已就绪——**OSS 链路不是瓶颈，断言层才是**。

---

## 二、差距清单（证据 → 影响 → 根因）

### GAP-1（P0）：db_query 结果无法被 verify 断言

**证据**（`engine/scenario_runner.py`）：

```python
# json 断言分支（约 L297-300）
target = ns[body.get("of", last_call_ref)]
actual = _jsonpath_find(body["path"], target["json"])   # ← 硬性要求 save 变量含 "json" 键

# db_query 步骤返回（约 L221）
return rows                                              # ← 裸 list[dict]，无 "json" 键
```

**影响**：导入类场景的**核心验证点全部在 DB 层**，目前无法表达：

| 业务验证点 | 需要的断言（目前会 KeyError） |
|-----------|------------------------------|
| 360 分数 "-" / 空 → 入库为 NULL | `json: {of: rows, path: "$[0].total_score", eq: null}` |
| "-" 行不丢其余字段（不删其余数据） | `json: {of: rows, path: "$[0].rank_overall", not_null: true}` |
| Sheet 整表不丢行（52648d4 回归） | `json: {of: rows, path: "$.length()", len_eq: 3}` |
| 落位 "0" 合法入库 | `json: {of: rows, path: "$[0].leader_calibrated_placement", eq: "0"}` |
| revert 后 completed_at 清空 | `json: {of: rows, path: "$[0].completed_at", eq: null}` |

现状唯一退路是 `db_query` 落 `db_traces` 供人工肉眼核对——自动化断言链断裂。

**根因**：json 断言假定所有 `of` 目标都是 `call` 步骤产出（`{status, json, headers}` 结构），未考虑 `db_query` 的裸数组产出。

---

### GAP-2（P0）：无异步轮询机制

**证据**：`register_builtin_steps` 仅注册 `call / set_var / db_query`；`step_call` 的 `timeout`（约 L184）是**单次 HTTP 请求超时**，不是任务等待。

**影响**：Step4 导入是异步任务（`submit → 后台处理 → result`）。submit 后立即查 result 命中「处理中」状态，产生**假失败**，且失败模式随数据量波动、不可复现。测试稳定性无法保障。

**根因**：引擎缺少「重复调用直至条件满足」的循环原语。YAML 层无法表达等待语义（连固定 sleep 都没有）。

---

### GAP-3（P1）：规范文档落后于引擎能力

| 引擎已支持 | 证据 | 规范文档状态 |
|-----------|------|-------------|
| oracle 参数化形式 `oracle: {name, params}` | `scenario_runner.py` 约 L324：`name, params = (body, {}) if isinstance(body, str) else (body["name"], body.get("params", {}))` | §1.7 仅记录字符串形式 |
| `len_eq` 断言 | 约 L269-273 | §1.7 仅列 `len_gt` |
| xlsx 文件本体内容校验 | 无对应能力 | §1.6 宣称覆盖「上传→调用→下载→校验」完整链路，实际「校验」止步于 API 响应 |

**影响**：文档是 Agent 生成 YAML 的唯一依据，文档缺失 = 能力不可用。

---

### GAP-4（P2）：fixture 文件依赖无声明机制

`oss_upload: {file: "test-data/xxx.xlsx"}` 引用本地文件，文件缺失时只能运行期 `SkipScenario("文件不存在")`。场景文件的 fixture 依赖无法静态发现，Workbench 也无法做预检提示。

---

## 三、升级方案

### U-1（P0）：db 断言支持 —— 推荐最小改法

**YAML 语法**（复用现有 json 断言，零新语法家族）：

```yaml
flow:
  - db_query:
      sql: SELECT total_score, rank_overall FROM tdm_eval_360
           WHERE session_id = {{session.json.data.id}} AND emp_no = '{{emp.no}}'
      save: score_rows
verify:
  - json: {of: score_rows, path: "$[0].total_score", eq: null}        # 分数为 NULL
  - json: {of: score_rows, path: "$[0].rank_overall", not_null: true} # 其余字段保留
  - json: {of: score_rows, path: "$.length()", len_eq: 3}             # 行数不丢
```

**引擎改动**（`_run_verifies` json 分支，一处）：

```python
target = ns[body.get("of", last_call_ref)]
# 改动前：payload = target["json"]
# 改动后：call 产出取 ["json"]，db_query 裸数组直通
payload = target["json"] if isinstance(target, dict) and "json" in target else target
actual = _jsonpath_find(body["path"], payload)
```

**安全性**：`db_oracle.py` 的 SELECT-only 守卫（SqlGuard）不受影响，断言仅消费查询结果。
**兼容性**：纯增量，存量场景行为不变。
**工作量**：0.5 人日（含单测 + 文档）。

> 备选方案 B：新增 `db: {of, row, field, eq}` 专用断言家族。语义更显式但引入新断言类型，维护成本高，**不推荐**。

### U-2（P0）：poll 轮询步骤

**YAML 语法**（复用 call + verify 既有语法，学习成本零）：

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
- 超时：`on_timeout: fail` → AssertionError（CAT_ASSERT）；`skip` → SkipScenario（CAT_ENV，归因环境慢而非产品缺陷）
- 每轮调用落 StepTrace（含轮次号），保证可审计

**引擎改动**：`register_builtin_steps` 新增 `poll` 处理器（约 60 行：循环 + 复用 `_run_verifies` 的 json 断言求值器 + trace）。
**兼容性**：纯增量。
**工作量**：1.5 人日（含单测 + 文档）。

### U-3（P1）：规范文档同步补齐

1. §1.5 断言表补 `len_eq`（引擎已实现，零开发）
2. §1.7 补 oracle 参数化形式：`oracle: {name: xxx, params: {...}}`（引擎已实现，零开发）
3. §1.6 措辞修正：明确「校验」范围 = API 响应断言；文件本体校验标注为 roadmap（或随 U-4 落地后更新）
4. U-1/U-2 落地后**重新生成格式规范文档**（文档由 Workbench 自动生成，需同步模板）

**工作量**：0.5 人日。

### U-4（P2）：fixtures 声明与预检

```yaml
fixtures:
  - {path: test-data/step4/eval360-empty-scores.xlsx, required: true}
```

- 场景加载期（非执行期）检查文件存在性：缺失 → 直接标记 SKIP 并在 Workbench 场景列表给出 ⚠ 预检图标
- 校验规则建议新增 T6（WARN）：声明的 fixtures 文件不存在
- 顺带收益：Workbench 可按 fixtures 清单生成「测试数据准备指引」

**工作量**：1 人日（含 Workbench 预检展示）。

### U-5（P3，roadmap）：xlsx 文件本体断言

文件转换类场景（上传源文件 → 转换 → 下载结果文件）需要校验下载 xlsx 的 sheet/单元格内容。建议作为 `excel_check` 系统侧步骤（非引擎内置）在 TDM 适配层实现，引擎无需改动。**本期不阻塞，列为 roadmap。**

---

## 四、实施排期建议

| 批次 | 项 | 内容 | 工作量 | 交付物 |
|------|----|------|--------|--------|
| 第一批（P0） | U-1 + U-2 | db 断言 + poll 步骤 | 2 人日 | 引擎版本 + 单测 + 规范文档重生成 |
| 第二批（P1） | U-3 | 文档同步（len_eq / oracle params / §1.6 措辞） | 0.5 人日 | 规范文档 v1.1 |
| 第三批（P2） | U-4 | fixtures 声明 + Workbench 预检 | 1 人日 | 引擎 + Workbench |

**时序约束**：TDM 三个 P0 测试场景（360 空值导入 / 落位 0 / 会话退回）的 YAML 交付**依赖第一批落地**；在第一批未交付前，使用附录 A 的临时方案过渡（自定义 oracle，能力等价但场景可移植性差）。

---

## 五、验收标准

| 项 | 验收用例 | 通过标准 |
|----|---------|---------|
| U-1 | `db_query` save 后接 `json: {of, path, eq/len_eq/not_null}` 断言 | 断言正确求值；of 指向 call save 时存量行为不变（回归通过） |
| U-2 | mock 一个「前 2 次返回处理中、第 3 次返回 DONE」的接口 | poll 在第 3 轮退出并 save 末次响应；超时路径按 on_timeout 分别产出 FAIL/SKIP；StepTrace 含 3 条轮次记录 |
| U-3 | 文档 §1.5/§1.6/§1.7 与引擎代码逐项核对 | 无遗漏项；Workbench 自动生成的文档含新增内容 |
| U-4 | 场景声明存在/不存在的 fixture 各一 | 加载期预检结果正确；缺失场景标记 SKIP 而非执行期报错 |

---

## 六、风险与备注

1. **无破坏性变更**：全部升级为增量能力，存量 15 个 PP-* 场景无需任何修改，可直接回归验证。
2. **安全边界不变**：U-1 仅消费 `db_query` 结果，SELECT-only 守卫、max_rows 截断（1000 行）维持原状。
3. **引擎/适配层边界**：U-1/U-2/U-4 均在引擎核心实现，TDM 适配层零改动；U-5 明确划归适配层，防止引擎膨胀。
4. **文档自动生成链路**：规范文档头部注明「由 SpecGuard Workbench 自动生成」，U-1/U-2 的语法表需同步进生成模板，避免下次生成时被覆盖丢失。

---

## 附录 A：临时过渡方案（引擎升级交付前）

不阻塞测试用例编写，两个 P0 缺口可在 TDM 适配层绕开：

| 缺口 | 临时方案 | 代价 |
|------|---------|------|
| db 断言 | 在 `systems/tdm/oracles.py` 新增自定义 oracle（如 `eval360_null_scores`、`import_rows_preserved`），经 `registry.oracle()` 注册；YAML 用 `oracle: {name, params}` 调用（引擎已支持参数化形式） | oracle 与具体表结构耦合，场景 YAML 可读性下降；引擎 U-1 落地后建议回迁为标准 json 断言 |
| 轮询 | flow 中串联 2~3 次相同 result 查询 call，依赖任务在首次调用前已完成（小数据量导入通常 <2s）；不稳定场景在测试计划配 `breakpoints` 人工放行 | 存在假失败概率，需人工甄别报告 |

## 附录 B：关键代码位置索引

| 位置 | 说明 |
|------|------|
| `tests/specguard/engine/scenario_runner.py` 约 L279-320 | `_run_verifies` 断言执行（U-1 改动点） |
| `tests/specguard/engine/scenario_runner.py` 约 L224-227 | `register_builtin_steps`（U-2 注册点） |
| `tests/specguard/engine/scenario_runner.py` 约 L171-205 | `step_call`（poll 复用的调用原语） |
| `tests/specguard/engine/registry.py` | 三张注册表（扩展机制基座） |
| `tests/specguard/engine/db_oracle.py` | SELECT-only 守卫（安全边界） |
| `tests/specguard/systems/tdm/steps.py` | oss_upload / oss_download 实现（与规范 §1.5 一致） |
| `tests/specguard/systems/tdm/__init__.py` | 系统注册钩子（适配层扩展点） |
