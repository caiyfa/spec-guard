# ENG-T03 HTTP 重试与超时看门狗

> **优先级**：P1　**覆盖条目**：ENG-BUG-003、ENG-BUG-004、ENG-BUG-011
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对属实）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。

---

## 1. 背景

引擎的 HTTP 出口是 `engine/http_client.py` 的 `HttpClient.request()`（场景 `call` 步骤与 `poll` 步骤共用），底层 `requests.Session`。SSO token 由 `engine/token_provider.py` 提供（自身已有 3 次指数退避重试，`token_provider.py:102-129`）。workbench 执行控制通过 `workbench/backend/services/runner.py` 起 pytest 子进程跑场景。

## 2. 问题与证据（均已代码核实）

### 2.1 无 5xx/网络重试（ENG-BUG-003 上半）

`http_client.py:97-100` 只有 401 → 刷新 token 重试一次；对 5xx、`ConnectionError`、`Timeout` **无任何 retry/backoff**。SIT 网关偶发 500/503 → 响应照常捕获 → 断言失败 → 假 FAIL。

### 2.2 401 重试复用已耗尽文件流（ENG-BUG-011，比 2.1 更隐蔽）

401 重试（`http_client.py:97-100`）把同一组 `files`/`data` 原样重发；而 `step_call` 的 form/binary 传的是**流式句柄**（`scenario_runner.py:276` `open(fpath,"rb")`、`:294` 同款）——第一次请求已把流读尽，**重试发出空 body，无任何报错**。本任务若新增 5xx 重试会立刻踩中同一问题，必须先治。

### 2.3 文件句柄从不关闭（ENG-BUG-004）

`scenario_runner.py:276/294` 的 `open()` 无 `close`，requests 不保证关闭传入文件对象 → fd 泄漏风险（高频上传场景真实存在）。

### 2.4 无场景级超时（ENG-BUG-003 下半）

单请求有 `timeout=30`，但场景级无 wall-clock 看门狗：`step_python` 里 `while True` 永久挂起整个 run。**已知兜底**：workbench runner 层有 run 级看门狗（T-118，`runner.py:481-526`，settings KV `run_timeout_sec` 优先、回退环境变量 `SG_RUN_TIMEOUT`，**默认 0=禁用**）——超时可强杀进程，但粒度是整轮、且默认关。

## 3. 修复方案

### 3.1 文件改 bytes（一箭三雕：ENG-BUG-004 + ENG-BUG-011 + 为重试铺路）

`step_call`（`scenario_runner.py`）的 form/binary 分支改读字节：

```python
# form 分支（:272-276）
files[k] = (os.path.basename(fpath), pathlib.Path(fpath).read_bytes())
# binary 分支（:291-294）
data = pathlib.Path(fpath).read_bytes()
```

requests 的 `files` 接受 `(filename, bytes)` 元组，`data` 接受 bytes——语义不变，句柄不再存在，重试任意次安全。文件不存在时 `read_bytes` 抛 `FileNotFoundError`（OSError 子类），保持现有"环境/文件缺失 → 异常上抛"的路径不变（ENG-T01 合并后归 CAT_ENV；fixture 加载期预检是 ENG-PLAN-003 的范畴，不在本任务）。

### 3.2 可配置重试（治 2.1）

`HttpClient.request` 增加 `retry` 参数（默认 None=不重试，行为完全向后兼容）：

```python
retry = {"times": 2, "backoff": 1.0, "on_status": [500, 502, 503, 504]}
```

判定规则：
- 网络异常（`requests.ConnectionError` / `requests.Timeout`）**总是可重试**（请求未必到达服务端，幂等性由调用方声明担保，见下）；
- 响应状态命中 `on_status` 才重试；4xx（除 401 既有逻辑）永不重试；
- **幂等门禁**：`step_call` 默认仅对 GET/HEAD/OPTIONS 自动附默认重试（times=1）；其他方法需在 call 步骤显式声明才重试，二选一语法：`retry: {times: N}` 或 `idempotent: true`（后者等价 times=1 的语义糖）。
- 重试顺序：401 刷新优先（现有逻辑），其后按 retry 配置对 5xx/网络异常重试；每次重试打 `[SpecGuard] WARN 重试第N次` 日志（K-049 日志锚点风格保持一致）。
- `retry` 配置从 `step_call` 的 body 读取并透传；`step_poll` 内部调用固定不重试（poll 本身就是重试语义）。

**三同步触发**：call 步骤新增 `retry`/`idempotent` 字段 = YAML 语法演进 → ① `format_spec.py` call 参数表加行 ② 格式版本号递增 + changelog ③ `contracts_baseline.json` 不受影响（指纹不含 flow 参数——但若 ENG-T02 已合并，指纹含 verify 也不含 retry，确认无基线漂移即可，跑一遍 `release_check.py` 验证）。

### 3.3 场景级软看门狗（治 2.4）

Python 无法安全硬中断线程内 `exec`，本任务做**软看门狗**：

1. `run_scenario` 入口记录 `started`（已有，`:867`）；新增阈值：环境变量 `SG_SCENARIO_TIMEOUT`（秒，默认 300）；
2. **检查点**：flow 循环每个步骤执行后、`_run_verifies` 每条断言后检查累计耗时，超阈值抛 `ScenarioTimeout(Exception)`（自定义异常，message 含"场景执行超过 Ns"）；`run_scenario` except 链把 `ScenarioTimeout` 归 `CAT_ENV`（ENG-T01 合并后）并保留超时提示；
3. `step_poll` 循环内同样检查（poll 有 `timeout_ms` 自控，但场景级阈值可能更小——取 `min(poll.timeout_ms 剩余, 场景剩余)` 语义，超场景阈值也抛 `ScenarioTimeout`）；
4. **文档注明**：`exec` 内死循环（`while True` 不回到步骤边界）软看门狗拦不住，进程级兜底靠 runner 层 T-118——建议执行控制在 settings 配置 `run_timeout_sec`（本任务只改文档与代码注释，不改默认值）。

## 4. 改动文件清单

| 文件 | 改动 |
|------|------|
| `engine/http_client.py` | `request` 增 retry 参数 + 退避循环（3.2） |
| `engine/scenario_runner.py` | step_call 文件 bytes 化（3.1）+ retry 透传；`ScenarioTimeout` 异常 + 检查点（3.3）；step_poll 场景阈值检查 |
| `workbench/backend/services/format_spec.py` | call 步骤参数表 + 版本号 + changelog（三同步） |
| `test_engine/` | TDD 新增 `test_http_retry.py` / `test_scenario_timeout.py` |
| `docs/架构升级/测试执行引擎弊端问题清单.md` | 完成后回标 |

## 5. 硬约束

- **冻结层评审**：方案即底稿，动手前总控确认。
- **TDD**：mock 先行，离线可跑。
- **诚实语义**：重试必须打 WARN 日志，不允许"静默重试后 PASS 却不留痕"（排障时需要知道发生过抖动）。
- 不引入新依赖（用 requests 原生能力，不拉 tenacity）。

## 6. 验收标准（可执行）

1. mock 首次 503、二次 200 的 GET → 自动重试后 PASS，output.log 含重试 WARN 行；
2. mock 持续 503 的 GET → 重试耗尽后按既有路径 FAIL（断言或 CAT_ENV），总耗时 ≈ 退避之和；
3. POST 不写 retry/idempotent → 503 不重试（向后兼容回归）；
4. mock 首次 401、刷新后 200 的**文件上传** → 重试后服务端收到的字节与源文件一致（ENG-BUG-011 修复验证）；
5. 连续 100 次上传单测，进程 fd 数不持续增长（ENG-BUG-004 修复验证；Windows 下可用 `psutil.Process().num_handles()` 或跳过计数仅跑通）；
6. python 步骤 `time.sleep(999)` 拆成多步骤场景 + `SG_SCENARIO_TIMEOUT=2` → 场景在步骤边界被 `ScenarioTimeout` 中断，verdict=FAIL/env_error 带超时提示；
7. `python release_check.py` 全 PASS（三同步完成后）。

## 7. 关联文档

- 问题清单 ENG-BUG-003/004/011：`docs/架构升级/测试执行引擎弊端问题清单.md`
- T-118 run 级看门狗：`workbench/backend/services/runner.py:39-52, 481-526`
- 依赖：ENG-T01（ScenarioTimeout 归类用其 CAT_ENV 链）；与 ENG-T02 无交集
