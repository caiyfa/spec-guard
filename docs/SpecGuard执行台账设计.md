# SpecGuard 执行台账设计（全量执行结果 × 测试绑定记录 + 查询工具）

> 状态：已确认待实施 | 日期：2026-08-07 | 关联会话：20260806_142411_a07e6713（活动名称记录缺失）

## 1. 背景与动机

引擎执行完场景测试后，现有记录机制存在两个 gap：

1. **失败索引只记失败**：`failures/index.jsonl`（K-052）仅收录 FAIL/ERROR/BLOCKED，PASS/SKIP/DRIFT/ORPHANED 无台账——查询「某场景最近执行结果（含 PASS）」无工具可用。
2. **save 变量不落盘**：`record.saved_vars` 是运行时动态属性（`scenario_runner.py` L921），`to_dict()` 不收录，`report_writer.py` L30 还显式 `pop("saved_vars")`——执行时生成的上下文（如 UT01 动态生成的活动名称 `SG历史DAG-{timestamp}`）在报告与台账中都查不到，只能拿 activityId 反查 DB。

**目标**：每次执行后，把**全部场景执行结果**与场景绑定记录（含关键上下文变量），提供 MCP 工具 + 工作台 API 查询，并修改 Agent 系统提示词引导查询动线。

## 2. 需求（已澄清）

| 项 | 决策 |
|----|------|
| 覆盖范围 | 仅引擎场景测试（scenarios/ 库 + tmp + drafts 的 YAML 场景） |
| 记录内容 | 全量 verdict（PASS/FAIL/SKIP/BLOCKED/DRIFT/ORPHANED）+ 失败/断言摘要 + **关键上下文变量（saved_vars 全量自动记录，truncate 截断）** |
| 查询形态 | MCP 工具 + 工作台 API |
| 变量来源 | 引擎自动记录全部 save 变量（不做场景显式声明） |
| 附加要求 | 修改系统提示词（agent/prompts/system.md.j2）引导 LLM 查询记录 |

## 3. 方案选择

- **方案 A（采纳）**：新建 `executions/index.jsonl` 全量台账，对称扩展 K-052 失败索引模式（文件真相源 + SQLite 投影 + 幂等追加 + 读降级）。
- 方案 B（否决）：扩展现有 failures 文件为全量——语义混乱（目录名 failures 存全量）、历史数据是失败子集无法区分「没跑过」与「没记录」。
- 方案 C（否决）：仅 SQLite 台账——违背「文件是权威、DB 是投影」既定架构约束，断送文件降级路径。

## 4. 设计

### 4.1 数据流

```
引擎执行（runner / plan_executor 两路径）
   │
   ├─► report_writer 落盘 run.json + cases/*.json
   │      └─ 变更①：cases/*.json 收录 saved_vars（truncate 截断后）
   │
   ├─► execution_index.append_executions()   ← 新增（对称 failure_index）
   │      ├─ 全量场景条目 → {reports_root}/executions/index.jsonl（append-only，幂等）
   │      └─ 投影 → SQLite run_cases 表（变更②：upsert 调用时机改为全量无条件）
   │
   └─► failure_index.append_failures()       ← 保留不动（失败子集继续可用）
```

### 4.2 组件变更

#### ① engine/execution_record.py + engine/report_writer.py（冻结层，仅报告产物扩展）

- `ExecutionRecord.to_dict()` 增加：`d["saved_vars"] = truncate(getattr(self, "saved_vars", {}))`（复用现有 `truncate()`：字符串 500 字符 / 深度 8 / 列表 20，与 `StepTrace.body_excerpt` 同级保护）。
- `report_writer.dump_json` 移除 `d.pop("saved_vars", None)`。
- 无 saved_vars 的记录（如 `_blocked_record` 构造）用 `getattr` 防御为空 dict。
- 报告 schema 向后兼容：只增字段不改既有字段，前端消费不受影响。
- **不触发 format_spec 三同步**：不新增 YAML 语法/步骤类型/断言器，属报告产物扩展。

#### ② workbench/backend/services/execution_index.py（新建）

- `EXECUTIONS_INDEX_REL = Path("executions") / "index.jsonl"`。
- `append_executions(reports_root, run_id) -> int`：从 run.json 遍历**全部** cases（不过滤 verdict），提取字段后追加；幂等（同 run_id 已收录跳过，对齐 append_failures 的 `'"run_id": "xxx"'` 检测）；run.json 不存在返回 0（离线自测不写台账，与现状一致）。
- `query_executions(reports_root, scenario_id="", run_id="", verdict="", limit=10) -> list[dict]`：DB 优先 + 文件降级（复用 failure_index 既有模式）。

**台账条目字段**（与失败索引同构扩展）：

```json
{
  "run_id": "EX-9e31916f",
  "scenario_id": "ST01-IMP-001",
  "verdict": "PASS",
  "title": "HISTORY 活动启动后自动创建 HISTORY 会话",
  "env": "sit",
  "finished_at": "2026-08-07T09:53:02",
  "duration_ms": 1234,
  "covers": ["FR-002", "FR-010", "FR-011"],
  "category": "",
  "message": "",
  "assertion_summary": {"passed": 6, "total": 6},
  "saved_vars": {"activity": {"json": {"data": {"id": 218289532070604800, "activityName": "SG历史DAG-1786020277"}}}}
}
```

`saved_vars` 与 `category/message` 从 cases/*.json 读取（变更①后的截断版）。

#### ③ workbench/backend/services/ledger_store.py（台账投影）

- `run_cases` 表加列：`title`、`covers`、`assertion_passed`、`assertion_total`、`saved_vars`（ALTER TABLE 幂等：先查 `PRAGMA table_info(run_cases)` 再补列）。
- `upsert_run_from_json` 填新列（title/covers 来自 run.json cases 索引，断言数与 saved_vars 从 cases/*.json 提取）。
- 新增 `query_executions_db(...)`：JOIN runs 按 `reports_root` 隔离，`scenario_id`/`run_id`/`verdict` 可选过滤，`ORDER BY r.finished_at DESC, c.id DESC LIMIT ?`。
- **关键修正**：现有 `upsert_run_from_json` 只在有失败条目时被调用（failure_index.append_failures 内，`if not entries: return 0` 提前返回）——**全 PASS 的运行不进台账**。变更后 runner/plan_executor 每次执行完**无条件**调用，堵住该 gap。

#### ④ 写入入口（2 处，对齐 K-052）

- `workbench/backend/services/runner.py`：`_record_failures` 旁新增 `_record_executions`（含 `-bN` 批次目录循环），内部调用 `execution_index.append_executions` + `ledger_store.upsert_run_from_json`。
- `workbench/backend/services/plan_executor.py`：append_failures 旁追加同样两调用。

#### ⑤ 查询面（MCP 工具 + 工作台 API + 系统提示词）

**MCP 工具 `list_executions`**（挂在 mcp_server/tools/attribution.py，TOOLS 注册 + handle 分发）：

| 参数 | 类型 | 说明 |
|------|------|------|
| scenario_id | string | 可选，只看该场景的全部执行记录 |
| run_id | string | 可选，只看某次执行的全部场景 |
| verdict | string | 可选，按结果过滤（PASS/FAIL/SKIP/BLOCKED/DRIFT/ORPHANED） |
| limit | integer | 返回条数（默认 10） |

返回：最新在前，每条含 saved_vars——按场景 ID 直接看到最近执行的完整结果与上下文变量（如活动名称）。

**工作台 API**：`GET /api/executions?scenario_id=&run_id=&verdict=&limit=`（新增 router，读 services.execution_index.query_executions，响应结构与 MCP 工具一致）。

**系统提示词**（agent/prompts/system.md.j2 新增「执行记录查询」段）：

```markdown
## 执行记录查询

引擎每次执行后会把全部场景结果写入执行台账（executions/index.jsonl + SQLite 投影）：
- list_executions：查某场景/某次执行的执行记录（**全量含 PASS**，最新在前；每条含
  执行上下文变量 saved_vars，如动态生成的活动 ID/名称）——查「某测试执行结果/执行
  用的参数」用它
- list_failures：只查失败子集（FAIL/ERROR/BLOCKED）——归因优化失败场景时用它
- read_run_log / read_run_report：拿到 run_id（EX-xxx）后看完整日志与断言差异

动线示例：查 ST01 最近执行用的活动名称 → list_executions(scenario_id=UT01-PREP-001)
看 saved_vars.activity.json.data.activityName → 需要更多证据再 read_run_report(run_id)。
```

### 4.3 错误处理与约束

- 台账写入全部 try/except 包裹——失败绝不影响执行结论（对齐既有注释约束）。
- 读路径纯读零副作用；DB 不可用自动降级读文件。
- 敏感面：saved_vars 经 truncate 截断后落盘，风险等级与既有 body_excerpt 一致，不新增字段黑名单（YAGNI）。
- 幂等性：同 run_id 重复执行/重复调用不产生重复条目（文件层检测 + DB upsert ON CONFLICT）。

## 5. 测试计划

| 测试 | 内容 |
|------|------|
| test_specstd/test_execution_index.py（新增） | append 全量（含 PASS）/ 幂等 / verdict 过滤 / run_id 过滤 / DB 投影 / 文件降级 |
| test_specstd/test_ledger_store.py（扩展） | run_cases 新列 / 全 PASS 运行也落库 / query_executions_db 过滤 |
| test_engine（扩展） | ExecutionRecord.to_dict() 含截断 saved_vars；无 saved_vars 防御 |
| 回归 | 现有 test_ledger_store / test_plan_executor / test_engine_modes 全绿（确认 run.json 结构变化不破坏既有断言） |

## 6. 影响面与风险

- **冻结层**：execution_record.py / report_writer.py 改动仅为报告产物扩展（新增字段），不触碰调度/依赖仲裁语义——按项目惯例需评审，风险低。
- **前端**：cases/*.json 与 run.json 新增字段向后兼容，现有消费方不受影响。
- **历史数据**：存量报告不回填（YAGNI）；DB 台账可从既有 run.json 用 `sync_runs_from_reports` 全量重建，天然兼容新列（空值）。
- **list_failures 兼容**：保留不动，行为不变。
