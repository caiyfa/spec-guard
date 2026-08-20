# ENG-T06 DB 截断可见性

> **优先级**：P1　**覆盖条目**：ENG-BUG-009
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对属实；当前场景库尚无 `length()` 用例，属"规范已文档化、尚未踩雷"的隐患，趁未爆发修成本低）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。预计 0.5 人日。

---

## 1. 背景

只读 DB 客户端 `engine/db_oracle.py` 的 `ReadOnlyDb.query(sql, params, max_rows=1000)` 供 `step_db_query`（`scenario_runner.py:349-369`）与 `systems/tdm/oracles.py` 的 DB 校对断言器使用。计数断言语法 `$.data.list.length()` 是 format_spec 文档化能力（`format_spec.py:664`）。

## 2. 问题与证据（已代码核实）

`db_oracle.py:51-60`：

```python
rows = cur.fetchmany(max_rows + 1)   # 多取一行——已经知道是否截断
if len(rows) > max_rows:
    return rows[:max_rows]           # 但截断事实被丢弃，调用方无感知
return rows
```

后果：对查询结果做计数类断言（`len_eq`/`len_gt`/`$.length()`）时，真实 1500 行会被读成 1000，断言得出错误结论且**无任何告警**。影响面 = 所有 `query` 调用方：`step_db_query`、`query_one`/`scalar`（max_rows=2，截断无实际影响但同属此通道）、`systems/tdm/` 各 oracle。

## 3. 修复方案

### 3.1 截断事实外抛（不改返回类型）

`query` 返回 `list[dict]` 的类型契约不动（调用方多，改返回类型代价大）。在 `ReadOnlyDb` 实例上记录最近一次查询的截断状态：

```python
def query(self, sql, params=None, max_rows=1000):
    self._guard(sql); self._ensure_alive()
    with self._conn.cursor() as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchmany(max_rows + 1)
    self.last_truncated = len(rows) > max_rows   # 新增：调用方可读
    self.last_rowcount_known = ...               # 可选：fetchmany 无法拿真实总行数，不强行提供
    return rows[:max_rows] if self.last_truncated else rows
```

（单线程执行模型下实例属性安全；未来并行化 ENG-PLAN-001 时需改连接池，届时一并处理——在代码注释留此伏笔。）

### 3.2 三层落痕

1. **db_traces**：`step_db_query`（`scenario_runner.py:364-366`）落盘条目加 `"truncated": db.last_truncated`；
2. **日志 WARN**：截断时 `print(f"[SpecGuard WARN] db_query 结果截断于 {max_rows} 行（实际更多），计数类断言将失真", flush=True)`；
3. **场景级告警通道**：`ExecutionRecord` 新增顶层 `warnings: list[str]` 字段（`to_dict` 落盘），`step_db_query` 截断时追加 `"db_query '{note}' 结果截断于 1000 行"`。
   - 前端展示：报告页已有 `warning_count`（AssertionTrace.warnings 的 WARN 三态）；顶层 warnings 的展示——先查前端对 case JSON 的渲染（`workbench/frontend/src` 的报告/历史页），有现成位置则接入，没有则本期只在 run.json/case JSON 落盘 + output.log WARN，前端展示单独立小项，不阻塞本任务。
4. **oracle 通道**：`systems/tdm/oracles.py` 中做全表计数校对的断言器（若有），在 `rctx.db.last_truncated` 为真时抛 AssertionError 或挂 `AssertionTrace.warnings`——逐个核对 8+ 个 oracle 的查询模式，只改确实可能超 1000 行的。

### 3.3 显式豁免

`db_query` 步骤支持可选字段 `allow_truncate: true`（默认 false）：声明后截断仍落痕但不再 WARN/告警（用于"我只取前 N 行看样本"的正当场景）。**三同步触发**：db_query 参数表加一行 + format_spec 版本号 bump + 基线确认无漂移（指纹不含 flow 参数，跑 `release_check.py` 验证）。

## 4. 改动文件清单

| 文件 | 改动 |
|------|------|
| `engine/db_oracle.py` | `last_truncated` 记录（3.1） |
| `engine/execution_record.py` | 顶层 `warnings: list[str]` 字段 + to_dict |
| `engine/scenario_runner.py` | `step_db_query` 三层落痕 + `allow_truncate` 豁免（3.2/3.3） |
| `systems/tdm/oracles.py` | 计数类 oracle 逐个核对接入（3.2.4） |
| `workbench/backend/services/format_spec.py` | db_query 参数表 + 版本号 + changelog（三同步） |
| `test_engine/` | TDD 截断测试（mock pymysql cursor） |

## 5. 硬约束

- 冻结层评审；TDD；不引入新依赖。
- **诚实语义**：截断告警不得默认豁免；`allow_truncate` 必须显式声明才生效。
- `ReadOnlyDb` 的 SELECT-only 守卫语义不变（Never：校验/只读工具不写副作用）。

## 6. 验收标准（可执行）

1. mock cursor 返回 1001 行 → `query` 返回 1000 行且 `last_truncated is True`；db_traces 条目含 `truncated: true`；output.log 有 WARN 行；case JSON 顶层 warnings 含截断条目；
2. 返回 999 行 → `last_truncated is False`，无 WARN（回归保护）；
3. `allow_truncate: true` + 截断 → 落痕保留、WARN/告警消失；
4. `query_one`/`scalar` 路径不受影响（max_rows=2 语义不变）；
5. `python -m pytest test_engine -v`、`python -m pytest -k engine_modes -v` 全绿；`python release_check.py` 全 PASS。

## 7. 关联文档

- 问题清单 ENG-BUG-009：`docs/架构升级/测试执行引擎弊端问题清单.md`
- 并行化伏笔：`docs/依赖状态管理设计-V3待实施.md` §7.2（连接池改造时处理实例属性线程安全）
- 完成后回清单标注「✅ 已修复 → {commit}」
