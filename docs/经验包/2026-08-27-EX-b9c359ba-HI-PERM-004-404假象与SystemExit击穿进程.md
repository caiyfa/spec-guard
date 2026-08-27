# HI-PERM-004「404」假象与 SystemExit 击穿运行进程

> 任务号：agent_20260826_142606（真 404）/ EX-dc874ada、EX-b9c359ba（崩溃）/ EX-6cf8ab64（修复后 SKIP）
> 会话：20260826_185503_0cdb0988（人才发展）
> 任务：T-1022（wt/engine-hardening）

## 现象

- HI-PERM-004 草稿试跑，工作台卡片报「失败: Internal Server Error」；点「查看结果」显示的还是 8/26 老版本场景的 404 报告（agent_20260826_142606），用户据此认为「服务路由拼接问题没修好、日志是老版本的」。
- 今早（08-27）两次试跑 EX-dc874ada/EX-b9c359ba 的 output.log 均戛然停在「步骤 python」，run.json 缺失（目录里只有 output.log）。

## 证据链

1. **真 404 已是历史**：agent_20260826_142606 跑的是 v0.5 旧版场景，其 python 步骤用 `http('default').post('/hr-center/api/...')`——`http(account)` 参数是账号不是服务（engine/scenario_runner.py `_python_ns`），base 固定走 default_service（hr-tdm 网关），实拼出 `/femsp/hr-tdm/hr-center/...` 被网关 404。v1.0 已改纯 call 链路 + `service: hr_center`（K-055 路由）。
2. **今早接口已通**：EX-dc874ada/EX-b9c359ba 日志显示 `POST /api/permission/role/emp-and-data-scope-list → 200`，响应体是 hr-center 业务错误 400001「数据权限值类型为部分时，数据权限值不能为空」——searchVo 自带 `dataScopeValueType: PART + dataScopeValues: []` 是服务端不合法的查法（实测可用 curl 用的是空筛条件）。
3. **python 键名写错**：脚本用 `ns.get('members_resp.json', {})` 点号扁平键；call 产出实为嵌套 dict（`ns['名'] → {'status','json','headers'}`），扁平键恒不存在 → records 恒空。同批 HI-PERM-002 用嵌套访问 `ns.get('query_resp')` + `.get('json')`，python 正常跑通。
4. **SystemExit 击穿进程**：脚本兜底 `raise SystemExit('SIT 未配...')`；SystemExit 继承 BaseException，flow python 步骤（scenario_runner.py step_python）与 verify python 断言脚本（_run_verifies）的 `except Exception` 均捕不到 → 异常裸穿 run_scenario → 运行进程死亡 → run.json/cases/索引全缺 → 工作台 500「Internal Server Error」→ UI 回退索引里的老报告。**「404 挡住了 + 日志还是老版本」是崩溃后回退显示的假象，不是真实失败。**

## 根因

三层叠加，各自独立成立：
1. **场景层**：searchVo 携带服务端拒绝的筛选组合（PART+空值）；
2. **场景层**：python 访问 call 产出误用点号扁平键（format_spec §1.13 2.15.0 已明示「平铺 key 与实现相反」，同批 HI-PERM-001 三连败同款认知错误复发）；
3. **引擎层（本次修复主体）**：脚本 raise SystemExit 无防护——except Exception 不覆盖 BaseException，崩溃同时炸掉 K-050「失败必落盘」保证（崩在落盘之前），并诱发 UI 回退老报告误导排障方向。

## 修复

- 引擎（T-1022，wt/engine-hardening）：step_python 与 _run_verifies 断言脚本各补 `except SystemExit` 分支——统一包装为场景编写错误（ScenarioScriptError / trace 原地落盘，CAT_SCENARIO），消息指路「主动跳过请用 raise SkipScenario(...)」；SkipScenario 分支原样放行，SKIP 语义不变。
- 场景（HI-PERM-004.yaml v1.0 修订，specguard-space 工作区草稿）：searchVo 改空筛条件（与实测 curl 一致，size 50）+ python 嵌套访问 + SystemExit 改 SkipScenario。
- format_spec 2.15.1 三同步：§1.13 断言语义补 SystemExit 包装说明。
- 修复后实证：EX-6cf8ab64 接口 200 → python 客户端筛选 → SIT 无 PART 空 codes 成员 → 诚实 SKIP，报告/索引正常落盘，卡片正常显示原因。

## 预防

- python 脚本终止语义只有两种合法形态：正常结束 / `raise SkipScenario('原因')`；绝不用 SystemExit/`exit()`（引擎现会包装为场景错误，不会静默）。
- python 里读 call 产出只用嵌套访问：`resp = ns['名']` 再 `resp['json']`；见到 `ns['xxx.json']` 点号扁平键即为 bug。
- python 步骤里的 `http(account)` 不能做服务路由（参数是账号）；跨服务调用一律用 call 步骤声明 `service:`。
- 「失败提示是老版本日志」类排障：先核对报告目录里该任务号的产物是否齐全——崩溃类失败没有 run.json，UI 展示的是索引里上一份报告，不要据此判断修复无效。
