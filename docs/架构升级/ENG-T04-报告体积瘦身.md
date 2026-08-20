# ENG-T04 报告体积瘦身

> **优先级**：P1　**覆盖条目**：ENG-BUG-005
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对，定性修正为"有意 trade-off 需复审"）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。预计 0.5 人日。

---

## 1. 背景

每次运行产出的结构化报告落在 `{workspace}/.specguard/reports/{EX-xxx}/`（`run.json` + `cases/*.json`），数据源是 `engine/execution_record.py` 的 `ExecutionRecord`/`StepTrace`。工作台报告页/历史页读这些 JSON 渲染。

## 2. 问题与证据（已代码核实）

`StepTrace.response_body` 存**完整未截断**响应（`execution_record.py:57`，注释明写"完整响应体（未截断，用于详细查询）"）；`step_call` 还把**完整请求体**并入 `record.steps[-1].request["body"]`（`scenario_runner.py:326-329`，注释"不截断，供详细查询"）。同一条 trace 里 `body_excerpt` 才是截断摘要（`truncate()`，500 字符/20 列表项/8 层深度上限）。

**这是 T-316 的有意设计，不是疏漏**——但两个事实让 trade-off 不再成立：
1. **消费端未兑现**：前端全仓 grep 零引用 `response_body` 字段（2026-08-20 确认），"详细查询"视图尚未落地——全量落盘的成本在付、收益为零；
2. **代价真实**：大列表响应（1000+ 行场景）让每个 case JSON 膨胀数倍，run.json 体积与内存随之升高，与 `truncate` 的设计初衷相悖。

## 3. 修复方案

### 3.1 大阈值截断（而非复用 excerpt 阈值）

`execution_record.py` 新增大阈值截断函数，与 `truncate` 并存：

```python
_BODY_MAX_CHARS = 20_000   # 详细查询需要的"足够大"上限，防失控为目的

def truncate_body(text_or_obj):
    """response_body/request body 专用：JSON 序列化后超 20KB 截断并标注原始长度。"""
```

- `step_call` 落 `response_body` 与 `request["body"]` 时经 `truncate_body`（`scenario_runner.py:324, 327-329`）；
- `body_excerpt` 逻辑**完全不动**（报告摘要视图依赖它）；
- 截断发生时在字符串尾部附 `…(已截断，原始共N字符)`，保持诚实可见；
- 同步更新 `execution_record.py:57` 与 `scenario_runner.py:326` 的注释（从"未截断"改为"20KB 上限截断"）。

### 3.2 不改动的部分

- 不改 `StepTrace` 字段结构（schema 不变，历史报告仍可被前端解析）；
- 不动 output.log 的响应摘要打印（`http_client.py` T-314 锚点行已是 truncate 后的）。

### 3.3 迁移说明

未来若"详细查询"视图落地需要全量响应，再从 output.log 回捞或按需重放——在本任务文档与清单中留此伏笔即可，不预先建设。

## 4. 改动文件清单

| 文件 | 改动 |
|------|------|
| `engine/execution_record.py` | 新增 `truncate_body` + 注释更新 |
| `engine/scenario_runner.py` | `step_call` 两处落盘点接 `truncate_body` |
| `test_engine/` | 新增截断单测 |

无三同步义务（报告 schema 字段不变、YAML 语法不变）。前端零改动。

## 5. 硬约束

- 冻结层评审；TDD。
- **诚实可见**：截断必须留痕（字符数标注），不允许无声丢弃——曾发生 0 字节快照被误读为加载卡死的前科（AGENTS.md 前端体验基线③的三态分离精神在此同样适用）。

## 6. 验收标准

1. mock 返回 5 万字符响应的 call → case JSON 中 `response_body` ≤ 20KB 且尾部含"已截断"标注；`body_excerpt` 仍为原 500 字符摘要；
2. 小响应（<20KB）→ `response_body` 与改动前**逐字节一致**（回归保护）；
3. 构造 1000+ 行列表响应的场景跑一轮 → run.json 体积较改动前显著下降（对比同一 fixture 的前后字节数，写入 PR 描述）；
4. `python -m pytest test_engine -v` 与 `python -m pytest -k engine_modes -v` 全绿。

## 7. 关联文档

- 问题清单 ENG-BUG-005：`docs/架构升级/测试执行引擎弊端问题清单.md`
- T-316 原始设计意图（请求/响应体进报告）：`scenario_runner.py:312-329` 注释
- 完成后回清单标注「✅ 已修复 → {commit}」
