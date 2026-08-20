# ENG-T07 清理与安全标注

> **优先级**：P2　**覆盖条目**：ENG-SEC-001、ENG-MNT-001、ENG-MNT-002
> **来源**：`docs/架构升级/测试执行引擎弊端问题清单.md`（v1.1 已核对属实）
> **执行方式**：本文件自含全部上下文，可独立开会话执行。小任务合集，预计 0.5 人日，可随时插入任何批次间隙。

---

## 1. 背景

引擎故意开放了场景内 Python 执行能力（`step_python` 步骤与 python 断言），这是格式 2.1 的设计特性；同时代码库积累了少量死代码与文档漂移。本任务是三项独立小清理的合集，互无依赖，可拆可并。

## 2. 子项一：exec 风险标注（ENG-SEC-001）

**证据**：`step_python` 用 `exec` 执行场景内任意 Python（`scenario_runner.py:665`；python 断言 `:835` 同款）。当前仅限受信任场景作者，风险低；但"执行场景 YAML 等同执行代码"这一事实没有任何文档显式声明，随着场景库可能接入 Agent 生成物或外部贡献，supply-chain 风险上升。

**修复**（纯文档，不改行为）：
1. `AGENTS.md`「Never」节补一条：**"不把场景 YAML 当纯数据——`python` 步骤/断言等同执行任意代码，外部贡献场景必须人工评审后才允许入库执行"**（与既有"Agent 产物三道闸"条目相邻）；
2. `README.md` 的场景语法章节补同款警示一句；
3. `step_python` docstring 开头补一行安全提示。
4. 决策留痕：是否需要在引擎加显式开关（如 `SG_ALLOW_PYTHON_STEP=0` 禁用）——当前结论：**不加**（受信任作者 + 三道闸已覆盖），若未来接入外部贡献再单独立项。把该结论写进清单对应条目的核对注记。

## 3. 子项二：死代码删除（ENG-MNT-001）

**证据**（2026-08-20 全仓 grep 零调用确认）：
- `engine/versioning.py:72-74` `version_satisfies_snapshot_tolerance()`——`^0` 宽容语义已内化在 `match_expectation` 的 caret 分支，本函数是残留；
- `engine/http_client.py:64-66` `HttpClient.as_user()`——账号切换由 `RunContext.http_client(account, service)` 的缓存键承担，本方法无人用。

**修复**：删除两处；顺手清理 import 里因此空置的名字（如有）。**删除前自查一遍 grep**（防御本清单后新增调用）：

```powershell
grep -rn "version_satisfies_snapshot_tolerance\|as_user" --include="*.py" .
```

## 4. 子项三：skip category 文档补全（ENG-MNT-002）

**证据**：`SkipScenario` docstring（`scenario_runner.py:30`）与 `ExecutionRecord.skip_category` 注释（`execution_record.py:94`）列了 6 类（pool_empty/pool_leased_out/account_missing/db_unavailable/oracle_infra/uncategorized），但 `step_poll` 实际使用第 7 类 `poll_timeout`（`scenario_runner.py:416`）。

**修复**：两处注释补上 `poll_timeout`。顺手检查 `systems/tdm/` 适配包内 `SkipScenario(..., category=...)` 的实际使用是否还有注释外取值（grep `category=`），有则一并补全。

## 5. 质量基线义务（AGENTS.md Boy Scout Rule）

本任务触碰 `engine/versioning.py`、`engine/http_client.py`、`engine/scenario_runner.py`、`engine/execution_record.py`——完成后：

```powershell
ruff check engine/                       # 确认无新增 lint
# vulture 基线刷新（docs/质量基线/ 对应报告重跑更新数字）：
vulture engine/                          # CAT_UPSTREAM 条目在 ENG-T01 后应已消失；本任务后两处死代码条目应消失
```

`docs/质量基线/README.md` 的摘要数字同步刷新（只改与本任务相关的行）。

## 6. 验收标准

1. 三处文档标注落盘（AGENTS.md Never / README / step_python docstring）；
2. 两处死代码删除后：`python -m pytest test_engine -v`、`python -m pytest -k engine_modes -v` 全绿；`python release_check.py` 全 PASS；
3. skip category 注释与实际使用一致（grep `category=` 全仓核对）；
4. vulture/ruff 基线数字刷新且不增。

## 7. 关联文档

- 问题清单 ENG-SEC-001 / ENG-MNT-001 / ENG-MNT-002：`docs/架构升级/测试执行引擎弊端问题清单.md`
- 质量基线协议：`AGENTS.md` §质量基线与顺手修复、`docs/质量基线/README.md`
- 完成后回清单标注「✅ 已修复 → {commit}」
