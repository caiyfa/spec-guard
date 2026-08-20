# ENG-T01 失败归类体系改造

> **优先级**：P0　**覆盖条目**：ENG-BUG-001、ENG-BUG-012
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对属实）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。

---

## 1. 背景（读懂本任务所需的最小上下文）

SpecGuard 是契约驱动的后端场景测试引擎（仓库根即 `specguard/`）。场景 YAML 由 `engine/scenario_runner.py` 的 `run_scenario()` 执行，产出 `ExecutionRecord`（`engine/execution_record.py`），verdict ∈ PASS/FAIL/SKIP/BLOCKED/DRIFT/ORPHANED。FAIL 时通过 `record.fail(category, message, evidence)` 记录**失败归类**（category），供报告与可视化区分"补数据 / 配账号 / 修环境 / 修场景"。

执行有两条入口路径，改动对两者同时生效：
- **pytest 路径**：`test_suites/test_scenarios.py` → `run_with_deps()`（conftest.py session 级 `rctx` fixture 装配）；
- **plan_executor 路径**：`workbench/backend/services/plan_executor.py` → `run_single()` → `run_with_deps()`。

## 2. 问题与证据（均已代码核实）

### 2.1 分类常量大半闲置（ENG-BUG-001）

`engine/execution_record.py:17-23` 定义了 7 个分类常量：

```python
CAT_HTTP = "http_unexpected"     # 从未被赋值（全仓 grep 确认）
CAT_ASSERT = "assert_failed"     # 使用中
CAT_ORACLE = "oracle_mismatch"   # 使用中
CAT_DB = "db_mismatch"           # 从未被赋值
CAT_POOL = "pool_unavailable"    # 从未被赋值
CAT_UPSTREAM = "upstream_blocked"  # 从未被赋值；scenario_runner.py:20 import 未用（vulture 基线已记）
CAT_ENV = "env_error"            # 使用中
```

实际赋值点只有三处：`scenario_runner.py:922`（CAT_ASSERT）、`:924`（CAT_ENV）、`:809`（CAT_ORACLE，经 `_run_verifies` 的 `first_fail_category` 间接传入 `record.fail()`）。

### 2.2 场景编写错误被误归因"环境"

`run_scenario()` 的兜底分支（`scenario_runner.py:923-924`）：

```python
except Exception as e:
    record.fail(CAT_ENV, f"{type(e).__name__}: {e}")
```

以下**场景作者自己的错**全部被吞进 env_error：
- 未定义变量 `{{emp.no}}` → `_resolve` 抛 `KeyError("变量未定义: ...")`（`scenario_runner.py:205`）；
- step 配置错误：未注册 tool、非法 `body_type`、random 池不存在 → 各 step handler 抛 `ValueError`；
- verify 里 jsonpath 拼错 → `jsonpath_ng` 抛 `JsonPathLexerError`/`JsonPathParserError`（注意：json 断言体内的 try 只捕获 `AssertionError`，`scenario_runner.py:783-790`，解析错误直接冒出 `_run_verifies`）；
- python 步骤 / python 断言脚本本身的语法与运行异常。

排障实害：经验包 `docs/经验包/2026-08-02-EX-8200eada-变量未定义-权限缺失.md` 即为「变量未定义」类报错的排障案例。可视化按 category 分流"修场景 vs 修环境"的能力因此形同虚设。

### 2.3 上游失败无分类（ENG-BUG-001 第三条证据）

`_blocked_record`（`scenario_runner.py:1006-1013`）只设 `verdict=BLOCKED` + `skip_reason`，不带任何分类。**注意不能调 `record.fail()`**——`fail()` 会强制 `verdict=FAIL`（`execution_record.py:100-102`）。

### 2.4 断言对象写错 → 中断全部剩余断言（ENG-BUG-012）

`_run_verifies` 中 status/json 断言取目标对象无保护（`scenario_runner.py:754` 和 `:768`）：

```python
target = ns[body.get("of", last_call_ref)]   # of 写错变量名 → KeyError 冒出
```

KeyError 冒出 `_run_verifies` 后：① 该场景**后续断言全部不再执行**（断言完整性被破坏）；② 被 `:923-924` 归 CAT_ENV（误归因叠加）。对比：json 断言的路径求值（`:773` `_jsonpath_find`）有 try 保护，取 target 这一步没有。

## 3. 修复方案（设计决策已评审口径，执行时如有偏离需在 PR 描述说明）

### 3.1 分类常量表：7 → 5

- **新增** `CAT_SCENARIO = "scenario_error"`（场景编写错误）；
- **激活** `CAT_UPSTREAM`（见 3.3）；
- **删除** `CAT_HTTP` / `CAT_DB` / `CAT_POOL`——网络异常归 CAT_ENV 属诚实语义；DB 失败已有 `skip_category=db_unavailable` 与 CAT_ORACLE 覆盖；pool 语义与 skip_category 的 `pool_empty` 重复。删除前再 grep 一次确认零引用（`workbench/` 已确认无引用）。

### 3.2 `run_scenario` 异常分流

```python
except SkipScenario as e:        # 不变
    ...
except AssertionError as e:      # 不变
    record.fail(CAT_ASSERT, str(e))
except (KeyError, ValueError) as e:                       # 新增：场景编写错误
    record.fail(CAT_SCENARIO, f"{type(e).__name__}: {e}")
except Exception as e:           # 兜底仍是环境/未知
    record.fail(CAT_ENV, f"{type(e).__name__}: {e}")
```

还需把 **jsonpath 解析错误**归入场景错误：在 `run_scenario` 的 except 链加 `jsonpath_ng` 的 `JsonPathError`（`from jsonpath_ng.exceptions import JsonPathError`），或在 `_run_verifies` 的 json 断言 try 里把 `except AssertionError` 扩为 `except (AssertionError, JsonPathError)` 并区分消息前缀。**推荐后者**（断言原地落 trace，报告里能看到是哪一条断言拼错，而非整个场景只剩一条 env_error）。

python 步骤/断言脚本的 `SyntaxError`、`NameError` 等随 `Exception` 兜底进 CAT_ENV 不对——脚本错误是场景错误。处理：`step_python` 与 python 断言的 `exec` 调用包一层，把脚本内异常重抛为带明确前缀的场景错误（如 `raise ScenarioScriptError(...)`，自定义 `ScenarioScriptError(Exception)`，在 except 链映射 CAT_SCENARIO）。注意脚本内主动 `raise SkipScenario` 的语义必须保留（现有用法，见 `scenario_runner.py:632` docstring）。

### 3.3 `_blocked_record` 补分类

复用现有 `skip_category` 字段（BLOCKED 与 SKIP 在报告消费侧同通道，`plan_executor.py:235-237`、`runner.py:140` 均已透传）：

```python
record.skip_category = CAT_UPSTREAM   # "upstream_blocked"
```

不加新字段、不改 `fail()` 语义。

### 3.4 断言取 target 容错（ENG-BUG-012）

`_run_verifies` 的 status/json 分支，把 `target = ns[...]` 包 try：

```python
try:
    target = ns[body.get("of", last_call_ref)]
except KeyError:
    trace.passed = False
    trace.message = f"断言对象 {body.get('of', last_call_ref)!r} 不存在（flow 未 save 该变量）"
    record.assertions.append(trace); print(format_assertion_log(trace), flush=True)
    if not first_fail_category: first_fail_category = CAT_SCENARIO
    continue   # 关键：不中断后续断言
```

## 4. 改动文件清单

| 文件 | 改动 |
|------|------|
| `engine/execution_record.py` | 常量表 7→5（增 CAT_SCENARIO、删 3 个闲置）；注释更新 |
| `engine/scenario_runner.py` | except 链分流（3.2）；`_blocked_record` 补 skip_category（3.3）；`_run_verifies` target 容错（3.4）；jsonpath 解析错误原地落 trace；python 脚本异常包装；删除未用的 CAT_UPSTREAM import（改为实际使用） |
| `test_engine/` | **TDD：先写失败测试**——新增 `test_failure_classification.py`（见 §6） |
| `docs/质量基线/` | 改完重跑 vulture 刷新基线（CAT_UPSTREAM 未使用条目应消失） |

不触及 `format_spec.py`（分类是执行语义不是 YAML 语法），**无三同步义务**。报告 schema 新增一个 category 取值，前端为透传展示（`runner.py:140` 拼 conclusion 字符串），无需前端改动。

## 5. 硬约束（AGENTS.md）

- **冻结层**：`engine/` 语义改动需评审——本任务方案即评审底稿，动手前由总控确认。
- **TDD**：先写 `test_engine/` 失败测试再改实现；离线可跑者优先。
- **诚实语义**：SKIP/BLOCKED 不得报成 FAIL 的红线不变——3.3 用 `skip_category` 而非 `fail()` 正是为此。
- 改引擎后必跑离线自测全绿再谈联网场景。

## 6. 验收标准（可执行）

新增 `test_engine/test_failure_classification.py`（离线 mock，不依赖网络/DB），至少覆盖：

1. 场景引用未定义变量 `{{nonexistent.x}}` → verdict=FAIL 且 `failure.category == "scenario_error"`（**不是** env_error）；
2. tool 步骤 `use` 未注册 → scenario_error；
3. json 断言 jsonpath 拼错（如 `$.data..`）→ 该断言 FAIL 落 trace，verdict=FAIL，category=scenario_error；
4. 断言 `of: typo_var`（不存在）→ 该断言 FAIL + category=scenario_error，**且同场景后续断言照常执行**（断言数 = 预期总数）；
5. python 步骤脚本 `raise RuntimeError("boom")` → scenario_error；脚本内 `raise SkipScenario("x")` → 仍为 SKIP；
6. 上游 FAIL 的场景 → verdict=BLOCKED 且 `skip_category == "upstream_blocked"`；
7. DB 连接缺失的 db_query → 仍为 SKIP/db_unavailable（诚实语义回归保护）。

必跑命令（仓库根）：

```powershell
python -m pytest test_engine -v        # 新增测试 + 存量回归
python -m pytest -k engine_modes -v    # 依赖语义自测
python release_check.py                # 发布门禁不回归
ruff check engine/                     # lint 不新增问题
```

## 7. 关联文档

- 问题清单：`docs/架构升级/测试执行引擎弊端问题清单.md`（ENG-BUG-001 / ENG-BUG-012）
- 排障动线惯例：`AGENTS.md` §故障排查、§问题修复经验包
- 完成后动作：回清单标注「✅ 已修复 → {commit}」；若产出可复用排障结论，登记 `docs/经验包/`
