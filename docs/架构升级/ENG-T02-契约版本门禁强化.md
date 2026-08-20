# ENG-T02 契约版本门禁强化

> **优先级**：P0　**覆盖条目**：ENG-BUG-002（含 v1.1 更正后的④）、ENG-BUG-010
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。

---

## 1. 背景

SpecGuard 场景通过 `depends_on` 声明上游依赖并可声明**契约版本期望**（`^X` 同主版本兼容 / `X.Y` 精确）。每个场景有契约指纹（sha256-12），基线落 `contracts_baseline.json`（随 git 提交）。两条校验线：

- **运行期**：`run_with_deps()` 入口 `_check_dep_versions()` 对**目标场景的直接依赖**做版本仲裁，产出 DRIFT（MAJOR 漂移）/ ORPHANED（上游缺失）verdict；
- **静态期**：`release_check.py` 第②③段（drift 清单 + T6 指纹校验）与 `workbench/backend/services/spec_validator.py` 的 T4/T6/T7 检查。

相关文件：`engine/versioning.py`（版本解析/匹配/指纹/基线/T6）、`engine/dependency_graph.py`（建图时算 `dep_status`）、`engine/scenario_runner.py`（运行期仲裁）、`engine/scenario_loader.py`（depends_on 归一化 + version 格式校验）。

## 2. 问题与证据（均已代码核实）

### 2.1 pin 可选（①）

`versioning.py:57-58`：`expected` 为空直接 `MATCH` → 不写 version 的依赖永不报漂移。**已有缓解**：spec_validator T7（`spec_validator.py:186-193`）对缺声明报 WARN。**当前全库 11 条 depends_on 仅 1 条未声明 version**（2026-08-20 实测），升 ERROR 成本极低。

### 2.2 指纹漏断言（②）

`_fingerprint(produces, saves, covers)`（`versioning.py:96-108`）不含 `verify` 断言逻辑/teardown/flow 结构 → 改断言预期（`eq:null → eq:0`）指纹不变 → T6 漏报。**注意这是文档明示的设计定义**：`versioning.py:5` 与 `format_spec.py:329` 均写「契约 = produces + save + covers」——本任务是在**修订这个定义**，属规范演进，必须三同步（见 §4）。

### 2.3 传递依赖不校验（③）

`_check_dep_versions` 仅在 `run_with_deps`（`scenario_runner.py:1070`）对目标场景调用一次；`_acquire_instance`（`:989`）递归准备上游时直接调 `run_scenario`，**依赖链深层（目标→A→B，B 的契约漂移）完全不被检查**。

### 2.4 传递孤儿依赖运行期崩溃（ENG-BUG-010，比③更严重）

`_acquire_instance` 里 `scenario = rctx.graph.by_id[scenario_id]`（`scenario_runner.py:985`）：目标场景的直接 orphan 会被 `_check_dep_versions` 拦截（不进入实例获取），但**依赖的依赖**不存在时此句抛裸 `KeyError`。`run_with_deps` 的 try 只捕获 `_UpstreamFailed`（`:1076-1081`）→ pytest 路径记 **ERROR**（无 verdict、无报告记录）；plan_executor 路径走 `:246` 兜底标 error。**复现构造**：A depends B（存在）、B depends C（不存在），跑 A。

### 2.5 DRIFT/ORPHANED 消息与 strict 语义（更正后的④）

v1.1 核对已更正初稿因果颠倒（pytest 路径 `test_scenarios.py:74` 是 `verdict != PASS → pytest.fail`，**默认拦得住**；strict_deps 退化 BLOCKED 后走 `pytest.skip` **反而放过**）。真实缺陷：

1. **失败消息为空**：`_verdict_record`（`scenario_runner.py:1016-1023`）不填 `failure`，`test_scenarios.py:75-80` 取 `record.failure or {}` → pytest 失败消息为 `[unknown] `（空）；`skip_reason` 只在 verdict==SKIP 时打印（`:67-68`），DRIFT/ORPHANED 的原因哪都不显示。
2. **strict_deps 语义反了**：strict 下 DRIFT→BLOCKED→pytest skip，门禁更松而非更严。
3. **plan_executor 路径漂移无通知**：`plan_executor.py:241` 仅 VERDICT_FAIL 触发 `_notify_failure`，DRIFT 只记 reason（`:235-237`）。（runner.py 的通知推送 `push_run_notifications` 有 DRIFT→drift 事件映射，pytest 路径覆盖，plan 路径的即时通知没有。）

## 3. 修复方案

### 3.1 版本仲裁下沉每一跳（治 ③ + 2.4）

在 `_acquire_instance` 内、`rctx.graph.by_id[...]` 取值**之前**插入仲裁：

```python
def _acquire_instance(scenario_id, rctx, consumer_id, mode):
    pool = rctx.instances.setdefault(scenario_id, [])
    if mode == MODE_SHARED:
        for inst in pool:
            if inst.mode == MODE_SHARED:
                return inst
    scenario = rctx.graph.by_id.get(scenario_id)
    if scenario is None:
        # 传递 orphan：不崩溃，按上游失败语义传播
        raise _UpstreamFailed(scenario_id, VERDICT_ORPHANED)
    verdict, reason = _check_dep_versions(scenario, rctx)   # 每一跳都仲裁
    if verdict:
        record = _verdict_record(scenario, verdict, reason)
        record.upstream_of = consumer_id
        rctx.records.append(record)
        raise _UpstreamFailed(scenario_id, verdict)
    ...
```

效果：深层漂移 → 该层产出 DRIFT/ORPHANED 记录，其消费者（含根目标）经既有 `_UpstreamFailed` 链路得 BLOCKED——不再有 KeyError、不再有 pytest ERROR。`run_with_deps` 顶层的 `_check_dep_versions` 保留（目标场景的 DRIFT/ORPHANED 是它自己的结论，语义不同）。

**注意**：`_UpstreamFailed` 的 verdict 参数目前是上游执行失败 verdict；扩展携带 ORPHANED/DRIFT 后，`_blocked_record` 的 skip_reason 文案保持现有格式即可（"上游场景 X 未通过（DRIFT）"）。

### 3.2 指纹纳入 verify（治 ②）

`_fingerprint` 增加 verify 段，取**规范化结构摘要**（不渲染插值，保留 `{{}}` 原文）：

```python
def _verify_key(verify):
    out = []
    for v in (verify or []):
        if not isinstance(v, dict):
            out.append(str(v)); continue
        # 每条约言取：类型键(status/json/oracle/python) + 规范化后的内容
        # json: path + 出现的操作符键(eq/ne/contains/len_eq/len_gt/not_null/absent) + 预期值的 sort_keys JSON
        # status: eq 原文；oracle: name + params 的 sort_keys JSON；python: script 原文 hash
        ...
    return out
```

实现要点：`json.dumps(..., ensure_ascii=False, sort_keys=True)` 保证跨机器稳定；doc 注释与 `versioning.py` 头注的契约定义同步改写。

**基线迁移（必做步骤）**：指纹算法变更 → 全量指纹变化 → 直接跑 `release_check.py` 会全量 T6 ERROR。提交中包含重建后的基线：

```powershell
python -c "import sys; sys.path.insert(0,'.'); from engine.scenario_loader import load_scenarios; from engine.versioning import build_baseline, save_baseline; save_baseline('.', build_baseline(load_scenarios('scenarios')))"
python release_check.py   # 应恢复全 PASS
```

### 3.3 T7 升 ERROR（治 ①）

1. 先补全库唯一 1 条缺 version 的 depends_on（快照期 0.x 上游用 `^0`——`^0` 对任意 0.x 宽容，标准 caret 语义）；
2. `spec_validator.py` T7 两处 `"level": "WARN"` → `"ERROR"`，message 不变；
3. 检查 spec_validator 单测（`test_specstd/` 或 workbench 侧测试）是否断言 T7 等级，同步更新。

### 3.4 DRIFT 消息与 strict 语义修正（治 2.5）

1. `_verdict_record` 填充 failure（**不调 `fail()`**，避免 verdict 被改写）：

```python
record.failure = {"category": "contract_drift" if verdict == VERDICT_DRIFT else "contract_orphan",
                  "message": reason, "evidence": None}
```

新增两个常量到 `execution_record.py`（与 ENG-T01 的分类表改造若并行，约定：T01 动常量表，T02 只追加这两个，合并冲突时以 T01 的表为准）。`test_scenarios.py:75-80` 随即能打出完整消息，无需改测试入口。

2. **strict_deps 语义反转修正**：`_check_dep_versions` 中 strict 分支由"退化为 BLOCKED"改为"退化为 FAIL"——`record.fail(...)` 语义契约漂移即失败。同步更新：`execution_record.py:12` 注释、`conftest.py:40-42` 的 `--strict-deps` help 文案、`run_scenario.py` RunContext docstring。效果：strict 下 pytest fail（消息完整）、plan_executor 走 FAIL 通知路径，两处门禁行为一致。

3. plan_executor 即时通知覆盖 DRIFT：`plan_executor.py:241` 的通知条件扩为 `record.verdict in (VERDICT_FAIL, VERDICT_DRIFT, VERDICT_ORPHANED)`（或 strict 修正后 DRIFT 已变 FAIL，此项自然解决——二选一，推荐做 strict 修正即可，不要双重通知）。

## 4. 三同步义务（本任务触发）

指纹定义变更 = 格式规范演进，按 AGENTS.md「引擎能力变更三同步」：

1. `workbench/backend/services/format_spec.py`：§版本化依赖章节的契约定义（`:329`「契约 = produces + save + covers」）改为含 verify 的新定义；`requires 不进契约指纹`（`:41`）等措辞核对不变；
2. `format_spec.py` 顶部版本号递增（MINOR，如 2.3.x → 2.4.0，changelog 段补一条）；
3. `contracts_baseline.json` 重建（见 3.2 命令）。

## 5. 改动文件清单

| 文件 | 改动 |
|------|------|
| `engine/scenario_runner.py` | `_acquire_instance` 仲裁下沉 + orphan 容错（3.1）；`_verdict_record` 填 failure（3.4.1）；`_check_dep_versions` strict 分支改 FAIL（3.4.2） |
| `engine/versioning.py` | `_fingerprint` 加 verify 段（3.2）；docstring 契约定义改写 |
| `engine/execution_record.py` | 新增 contract_drift/contract_orphan 分类常量；注释更新 |
| `workbench/backend/services/spec_validator.py` | T7 WARN→ERROR（3.3） |
| `workbench/backend/services/format_spec.py` | 契约定义 + 版本号 + changelog（§4 三同步） |
| `contracts_baseline.json` | 重建 |
| `conftest.py` | `--strict-deps` help 文案 |
| `scenarios/**` | 补 1 条缺 version 的依赖声明（文本外科手术，禁止 js-yaml 往返） |
| `test_engine/` + `test_specstd/` | TDD 新增/更新测试 |

## 6. 验收标准（可执行）

`test_engine/` 新增离线测试（构造内存 Scenario/DependencyGraph，不触网）：

1. 链 A→B→C，C 不存在 → 跑 A：B 得 ORPHANED 记录（含 failure.message），A 得 BLOCKED，**无异常冒出**；
2. 链 A→B→C，B 对 C 声明 `version: ^2` 而 C 实为 v1 → B 得 DRIFT 记录，A BLOCKED；
3. 改某场景 verify 一条断言的预期 → `contract_fingerprint` 变化；`check_t6` 对旧基线报 ERROR；
4. 缺 version 声明 → spec_validator T7 报 ERROR；
5. `strict_deps=True` 时 MAJOR 漂移 → verdict=FAIL（category=contract_drift）而非 BLOCKED；
6. 非 strict 时 DRIFT verdict 的 record.failure.message 非空（pytest 侧 `[unknown]` 空消息消失——可断言 record.failure 字段）。

必跑命令（仓库根）：

```powershell
python -m pytest test_engine -v
python -m pytest -k engine_modes -v
python -m pytest test_specstd -v -k "validator or versioning"   # 相关子集（test_specstd 全套件有 94 个存量 error，见质量基线 README，别被吓到）
python release_check.py    # 基线重建后必须全 PASS
```

## 7. 关联文档

- 问题清单 ENG-BUG-002 / ENG-BUG-010：`docs/架构升级/测试执行引擎弊端问题清单.md`
- 版本语义权威：`engine/versioning.py` 头注；格式规范：`workbench/backend/services/format_spec.py`
- 与 ENG-T01 的合并约定：见 3.4.1（分类常量表归 T01 所有，本任务只追加）
- 完成后回清单标注「✅ 已修复 → {commit}」
