# ENG-T05 渲染与断言防呆

> **优先级**：P2　**覆盖条目**：ENG-BUG-006、ENG-BUG-007、ENG-BUG-008、ENG-BUG-013、ENG-BUG-014
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对属实）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。建议 ENG-T01 合并后再做（RenderError 需归类 CAT_SCENARIO；若先做自己，临时归 CAT_ENV 并在代码注释标注待 T01 切换）。

---

## 1. 背景

变量插值由 `engine/scenario_runner.py` 的 `render()`（`:208-223`）+ `_resolve()`（`:168-205`）实现：字符串完全匹配 `{{expr}}` → 返回原始类型；内嵌 → 字符串替换；未定义变量抛 `KeyError("变量未定义: ...")`。断言默认对象机制：`last_call_ref` = flow 中最后一个带 `save` 的 **call** 步骤（`:890-895`），json/status 断言不写 `of` 时取它（`:754/768`）。`step_poll`（`:372-470`）是独立的轮询原语。

## 2. 问题与证据（均已代码核实）

### 2.1 插值语法错误静默透传（ENG-BUG-006）

`render` 用 `re.fullmatch(r"\{\{\s*(.+?)\s*\}\}", obj)` + `re.sub` 处理插值；`{{ empno }`（缺右括号）、`{{}}`（空）等**写错的插值不匹配任何分支 → 原样作为字面量发给 API**，无报错。拼错变量名的脏数据到断言/下游才暴露。当前场景库 85 个文件含 `{{` 且均为合法插值（2026-08-20 grep），上线残留扫描无存量误伤风险。

### 2.2 默认 of 易断言错对象（ENG-BUG-007，实际覆盖更窄）

- 消费点：`scenario_runner.py:754/768` `target = ns[body.get("of", last_call_ref)]`；
- `last_call_ref` **只认 call 步骤**（`:894-895` `if step_type == "call"`）——poll/db_query/tool 的 save 进不了默认 of；多 save 步骤场景不写 of 易静默断言错对象。

### 2.3 poll 把配置错误当"未满足"（ENG-BUG-008）

`step_poll` until 评估 `except (AssertionError, Exception)` 一律 `all_passed=False` 继续轮询（`:452-454`）——jsonpath 拼错（`JsonPathLexerError`）被当成"任务还没好"轮询至超时，真实错误被掩盖。附：`except (AssertionError, Exception)` 写法冗余（AssertionError 是 Exception 子类）。

### 2.4 命名空间浅拷贝跨场景污染（ENG-BUG-013）

`ns = dict(rctx.shared_ns)`（`:869`）浅拷贝——saved_vars 里的 dict/list 跨场景共享引用，python 步骤 `ns['rows'].append(...)` 会污染其他场景，无告警。注意 `_Instance.export_ns` 的"传递引用绑定同一套实例"是**有意设计**（`:941-942` docstring），修复不能破坏它。

### 2.5 step_poll 能力缺口（ENG-BUG-014）

`step_poll` 固定 `rctx.http_client(account)`（`:399`，service 恒为默认 tdm）——K-055 的多 service 路由（hr_center/oss/uac）不可用；call 段仅支持 method/path/params/json，无 headers/cookies/urlencoded。与 call 步骤能力不对齐。

## 3. 修复方案（五个子项独立可交付，按序实施）

### 3.1 插值残留扫描（治 2.1）

在 `render()` 的字符串分支末尾加反向扫描：结果字符串中仍含 `{{` → 抛 `RenderError`（自定义异常，归 CAT_SCENARIO/临时 CAT_ENV）：

```python
_PLACEHOLDER_LEFT = re.compile(r"\{\{")
# render 字符串分支：fullmatch/sub 完成后，若结果含 "{{" →
# raise RenderError(f"未解析的插值占位符: {obj!r}（渲染结果残留 '{{'，检查是否缺右括号或变量名拼错）")
```

注意：fullmatch 失败但 sub 成功的字符串（如 `"前缀 {{a}} 后缀 {{b"`）——sub 会把合法的 `{{a}}` 替换、残留 `{{b`，扫描同样命中，行为正确。**转义需求**：文档注明"需发字面量 `{{` 时"的写法（如无场景实际需要，暂不实现转义语法，只在 format_spec 注明限制）。

### 2.2 → 3.2 of 默认提示层（治 2.2，不改语义）

默认语义**不变**（避免破坏存量场景），只做提示：
- **lint**：`spec_validator.py` 新增检查项（如 T9）——场景含 ≥2 个带 save 的步骤且存在无 `of` 的 json/status 断言 → WARN"建议显式指定 of"；
- **运行期**：断言 trace 的 `expr` 已含 `body.get('of', last_call_ref)`（`:757/769`），信息已在报告里，无需额外改；
- **文档**：format_spec 的 verify 章节确认写明"默认 of 仅指最后一个带 save 的 **call** 步骤（poll/db_query/tool 的 save 不算）"——若没写则补上（三同步：文档章节措辞 + 版本号递增；lint 新增检查项本身不动语法，版本号随文档措辞一并 bump 一次即可）。

### 3.3 poll until 快速失败（治 2.3）

`step_poll` 的 until 评估区分两类失败：

```python
except AssertionError:          # 条件不满足（含 jsonpath 无匹配）→ 正常轮询
    all_passed = False; break
except Exception as e:          # 配置错误（JsonPathLexerError/KeyError/TypeError 等）→ 快速失败
    raise ValueError(f"poll until 条件配置错误: {type(e).__name__}: {e}") from e
```

`ValueError` 经 ENG-T01 的分流归 CAT_SCENARIO（未合并则 CAT_ENV）。顺手把 `except (AssertionError, Exception)` 冗余写法拆开消除。

### 3.4 浅拷贝风险文档化（治 2.4，只文档不改行为）

- `run_scenario` 的 `ns = dict(rctx.shared_ns)` 处补注释："浅拷贝——python 步骤对共享 dict/list 原地修改会泄漏到其他场景；深拷贝会破坏 export_ns 的传递引用绑定设计（见 _Instance docstring），故仅文档约束"；
- `step_python` docstring 补一条："不要对 ns 中来自上游的 dict/list 做原地修改（append/pop/改键），需要修改时先 `list(x)`/`dict(x)` 拷贝"；
- format_spec 的 python 步骤章节同步该注意事项（与 3.2 的版本号 bump 合并一次）。

### 3.5 poll 能力补齐（治 2.4→2.5 编号对应 ENG-BUG-014）

`step_poll` 的 call 段补 `service`/`headers`/`cookies` 透传（复用 step_call 的同款参数语义）：

```python
service = str(render(call_body.get("service", "tdm"), ns) or "tdm")
client = rctx.http_client(account, service)
headers = render(call_body.get("headers"), ns)
cookies = render(call_body.get("cookies"), ns)
# client.request(..., headers=headers, cookies=cookies)
```

**三同步触发**：poll 的 call 段参数表扩展 = 语法演进 → format_spec §poll 章节 + 版本号 + 基线确认无漂移（与 3.2/3.4 合并为一次 bump）。

## 4. 改动文件清单

| 文件 | 改动 |
|------|------|
| `engine/scenario_runner.py` | render 残留扫描（3.1）；poll until 快速失败（3.3）；浅拷贝注释（3.4）；poll 参数透传（3.5） |
| `workbench/backend/services/spec_validator.py` | 新增 T9 of 提示检查（3.2） |
| `workbench/backend/services/format_spec.py` | verify/poll/python 三处章节措辞 + 版本号一次 bump + changelog（三同步） |
| `test_engine/` | TDD：残留扫描 / poll 快速失败 / poll service+headers 透传 |
| `test_specstd/` 或 workbench 侧 | T9 lint 测试 |

## 5. 硬约束

- 冻结层评审；TDD；禁止 js-yaml 往返（本任务不动场景库，但 lint 提示若需批量改场景，走文本外科手术）。
- 3.1 上线前必须全库扫描确认零误伤：`grep -rn "{{" scenarios/ --include="*.yaml"` 逐一目检非标形态（当前 85 文件均合法）。
- 诚实语义：RenderError 属场景错误，不得归 env（依赖 T01 的分类）。

## 6. 验收标准（可执行）

1. call 的 path 写 `{{ empno }`（缺右括号）→ 运行期明确报"未解析的插值占位符"，请求**不发出**；
2. 合法插值全库回归：`python -m pytest -k engine_modes -v` + 离线单测全绿；
3. 场景含 call(save=a)+db_query(save=rows)+无 of 断言 → spec_validator 报 T9 WARN；
4. poll until 的 jsonpath 拼错 → 第一轮即 FAIL（scenario_error/env），消息含原始解析错误，不轮询至超时；
5. poll until 合法但条件不满足 → 行为不变（轮询至 timeout_ms 按 on_timeout 产出 FAIL/SKIP）；
6. poll 配 `service: hr_center` + 自定义 headers → mock 断言请求带正确 base 与头；
7. `python release_check.py` 全 PASS。

## 7. 关联文档

- 问题清单 ENG-BUG-006/007/008/013/014：`docs/架构升级/测试执行引擎弊端问题清单.md`
- 插值规则权威：`engine/scenario_runner.py` 头注 + format_spec §变量插值
- 依赖：ENG-T01（CAT_SCENARIO 归类）
- 完成后回清单标注「✅ 已修复 → {commit}」
