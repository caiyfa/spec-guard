# SpecGuard 多角色服务访问流转与规模化升级设计

> 版本：v1.0 · 2026-08-11 ｜ 配套总控：`SpecGuard-总控文档.md` §4.7（T-801~T-806）
> 依据：代码实证（runner.py / user_store.py / scheduler.py / auth.py / main.py / purposes/*）+ 规模评估结论
> 定位：① 当前各角色（产品/研发/测试/admin/viewer）如何访问 SpecGuard 各服务的流转图；② 后期 100+ 人规模时的升级方案详细设计，任务已注入总控 §4.7，开发时机见 §四。

---

## 一、背景与结论摘要

SpecGuard 当前目标团队规模约 35 人（产品 5+ 研发 20+ 测试 10+），后期若反响好可能扩展到 100+ 各角色人员。评估结论：

| 规模 | 结论 |
|------|------|
| **35 人（现状目标）** | **架构完全支持，零改动**。设计注释明确「几十用户量级无压力」（user_store.py WAL + 短事务 + 单 worker）。 |
| **100+ 人「访问」** | 支持。HTTP/静态/SSO/文件系统均无压力（单进程 async 可挂数百连接）。 |
| **100+ 人「使用核心能力（执行测试）」** | **存在 4 个阻塞点**，最大的是「单一执行槽」（RunManager 全局单例），其次为全局 WebSocket 广播、SQLite 单文件单写、调度忙时跳过。 |

升级任务编号 T-801~T-806（总控 §4.7），开发时机按「规模信号触发制」编排，不是一次性大改造。

---

## 二、当前各角色服务访问流转图

### 2.1 总体架构（部署形态）

```
                    ┌─────────────────────────────────────────────┐
                    │            Windows 服务器（单机单进程）         │
                    │                                             │
 浏览器(工作台) ─────▶│  uvicorn :9100（workers=1 硬约束）           │
   HTTP+WS          │   ├─ auth（UAC SSO 会话 + RBAC 多角色）        │
                    │   ├─ routers ×26（scenarios/runs/plans/     │
 外部 AI 宿主 ──────▶│  │   agent/specflow_*/zentao/graph/...）     │
 (Qoder 等, MCP     │   ├─ services（runner/plan_executor/        │
  stdio 挂载)        │  │   scheduler/各 store）                   │
                    │   ├─ 静态前端 dist（SPA 兜底）                │
 命令行 ───────────▶│   └─ 进程内 APScheduler（定时任务）           │
 python -m agent.cli│                                             │
                    │   RunManager 单例（1 个执行槽）               │
                    │      └─ spawn pytest 子进程（引擎执行）        │
                    └──────┬──────────────┬──────────────┬───────┘
                           │              │              │
                    ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼──────┐
                    │ SQLite     │ │ 文件系统     │ │ 外部依赖     │
                    │ workbench  │ │ specstd/    │ │ UAC SSO/    │
                    │ .db(WAL)   │ │ workspaces  │ │ LLM API/    │
                    │ 用户/授权/  │ │ .specguard/ │ │ SIT 网关+   │
                    │ 审计/队列/  │ │ 产物/报告/   │ │ MySQL/飞书/  │
                    │ 台账/图谱   │ │ 草稿(私有区) │ │ 禅道        │
                    └────────────┘ └─────────────┘ └─────────────┘
```

- **给人用**：浏览器访问 `http://服务器:9100`，UAC SSO 登录后进工作台（API + 前端同端口）
- **给 AI 用**：外部宿主（Qoder/Claude Code 等）挂载 `mcp_server`（stdio 协议，随宿主进程走，不进网站体系）
- **执行**：工作台触发 → RunManager 单例 → `python -m pytest` 子进程（同一时刻全系统仅 1 个）

### 2.2 角色 × 服务访问矩阵（代码实证）

| 角色 | 登录入口 | 工作台页签（REST 能力） | AgentChat 用途（工具白名单） | 关键写操作 | 只读操作 |
|------|---------|----------------------|---------------------------|-----------|---------|
| **admin** | 浏览器 SSO | 全部页签 + 用户/授权管理 + MCP 审计查询 | 双用途（需求面试 + 测试工作台），全量工具 | 一切（含他人执行 abort/resume、角色授权） | 一切 |
| **tester**（测试） | 浏览器 SSO | 测试侧全部：执行控制/DAG/计划/草稿/历史/归因/数据制造/覆盖缺口/图谱/血缘 | 测试工作台（`test_workbench`，全量测试工具 29+） | 执行触发/断点/abort（仅本人或 admin）、草稿写入与 promote 三闸、数据制造、归因确认、提 BUG | 报告/台账/图谱/血缘/需求侧只读（草稿查看、覆盖缺口） |
| **product**（产品） | 浏览器 SSO | 需求侧页签：材料包/评分冻结/禅道集成/覆盖缺口 + 草稿只读 | 需求面试（`requirement_interview`，specflow 工具集 22 工具，测试侧写工具不可见） | 材料候选确认/入包、评分 QA 确认、冻结闸①、禅道建故事/提 BUG、决策台账落锤 | 基线/决策台账/报告/图谱 |
| **dev**（研发） | 浏览器 SSO | 基础读面（报告/图谱/血缘/历史） | 需求面试用途可见（roles 含 dev，可参与需求面试会话） | 无（当前）；S8 后经 MCP 消费 dev-context-pack（规划中） | 冻结 spec/报告/图谱 |
| **viewer** | 浏览器 SSO | 基础读面（列表/报告/图谱/血缘） | 无（Agent 工具空集，fail-closed） | 无 | 全部读面 |

> 依据：`user_store.py` VALID_ROLES = (admin/tester/viewer/product)；`purposes/requirement_interview.md` roles=[admin,product,dev]、`test_workbench.md` roles=[admin,tester]；RBAC 矩阵（T-011 备注：admin/tester 全量、product 只读集、viewer 空集）；REST 层 `require_role` 分布（drafts/coverage GET 含 product；runs/feedback/data_fab 仅 admin/tester；zentao/specflow 决策写仅 product）。

### 2.3 关键流转路径

**路径 1：测试执行（tester/admin）**
浏览器 → UAC SSO → `POST /api/runs/trigger`（require_role admin/tester）→ RunManager 单例 → 忙则 FIFO 入队（SQLite run_queue 持久化）→ spawn pytest 子进程（SG_RUN_ID=EX-xxxx 报告目录隔离）→ 逐行输出经 WebSocket 广播**给所有订阅者** → 收尾写失败索引/执行台账/推送通知（webhook）。

**路径 2：需求面试（product/dev/admin）**
浏览器 → AgentChat（purpose=requirement_interview，白名单 22 工具）→ runtime 经 MCP 工具层 → specflow store（SQLite sf_* 表）+ 文件系统（.specflow/{emp}/ 私有区）→ 评分/冻结经 REST（product 闸门）→ 冻结产物进基线（S5 三闸）。

**路径 3：AI 宿主消费（外部 Agent）**
宿主进程 → mcp_server（stdio）→ 工具分发（三层交集白名单：注册表 ∩ purpose ∩ RBAC）→ specstd 工作区 contextvar 透传 → 读 spec/场景/报告/台账，写草稿（落私有区，走三闸）。

---

## 三、规模化升级详细设计（T-801~T-806）

> 阻塞点证据链（代码位置）：① 单执行槽 `runner.py:877-878 run_manager = RunManager()` 模块级单例；② 全局广播 `runner.py:199-207 broadcast` 遍历全部 subscribers 无过滤；③ SQLite 单文件 `user_store.py:22-40`（user/audit/run_queue/draft_gates/scheduler/sf_*/audit_store 全写 workbench.db）；④ 调度忙时跳过 `scheduler.py:166-181`（is_running → skipped_busy 不入队）。

### T-801 WebSocket 订阅隔离（广播过滤）

**现状**：`RunManager.subscribers` 为全局列表，`broadcast` 逐条 `send_json` 发给**所有**订阅者——A 用户执行时，所有打开执行流页面的用户收到 A 的全部输出；无 run_id / workspace 过滤。

**问题（规模信号）**：100+ 在线时，单次执行每行输出 × 全部连接 = 消息放大 100 倍（CPU/IO 热点）；同时信息串台（B/C/D 用户看到 A 的任务流）。

**设计**：
- 订阅协议扩展：WS 首帧 auth 消息携带 `{run_id? | scope: "all"|"mine"}`（后端默认降级为当前行为，兼容旧前端）
- `subscribe(ws, filter)` 记录过滤条件；`broadcast(run_id, msg)` 只发给 `filter.run_id == run_id 或 scope == "all"` 的订阅者
- 执行流页按 run_id 订阅；全局状态页（status/queue）订阅系统级事件（started/finished/queued），不再收逐行 output

**改造点**：`services/runner.py`（subscribe/broadcast 签名）、`routers/runs.py`（WS 首帧解析）、前端 `useRunStream`（订阅参数）。
**验收**：A 执行时 B 订阅 A 的 run 才收到 output；C 未订阅只收 status/queued 事件；单次执行广播量 = 订阅该 run 的连接数（可打点验证）。
**开发时机**：**35 人起步即可认领**（低风险、独立、无依赖），或在线 WS 连接数 > 30 时优先。

### T-805 服务守护与自动拉起

**现状**：`serve-prod.ps1` 手工启动单进程 uvicorn，无守护、无崩溃自愈；进程挂 = 全员不可用（run_queue 有持久化，重启后 `fail_stale_running` 可恢复，但没有自动拉起机制）。

**问题**：生产环境 35 人稳定使用后，单点进程的可用性风险成为第一位问题（比并发更现实）。

**设计**：
- Windows 服务化（NSSM 或计划任务 + Watchdog 脚本）：崩溃/退出码非零自动重启，重启间隔退避防循环
- 启动自检已有（`/api/health` 就绪确认）→ 守护脚本复用同一探活逻辑
- 重启后队列恢复验证纳入启动流程（`fail_stale_running` 已在 startup 执行，补一条 WARN 日志标注恢复的队列项数）

**改造点**：新增 `scripts/watchdog.ps1`（或 NSSM 配置文档）、`serve-prod.ps1` 可选 `-Install` 模式。
**验收**：kill 后端进程后 60s 内自动恢复；`/api/health` 恢复；重启后 running 队列项被标 failed 并记录日志。
**开发时机**：**35 人起步即可认领**（成本低、收益高、不依赖任何其他升级任务）。

### T-802 执行槽池化（RunManager → RunPool）【架构级 · 需评审】

**现状**：`run_manager` 模块级单例，`is_running` 时新触发进 FIFO 队列。长任务（全量回归 30-60min）期间**所有人**排队；队列只有 position 无 ETA、无优先级。

**问题（触发信号）**：100+ 团队执行频率大幅上升，单执行槽成为吞吐天花板——不是崩溃问题，是「测试执行」核心动作的效率退化。

**设计**：
- `RunManager` 改造为 `RunPool`：N 个并发槽（N 可配，默认 2），每个槽一个执行实例（run_id/process/subscribers 独立，现有 EX- 随机 ID 与报告目录已天然隔离）
- **互斥维度从「全局」收窄到「(workspace, env)」**：同一工作区 + 同一环境不并发（调度器注释已指出「并发打同一 SIT 环境会互相干扰数据」——这是业务约束，不是全局约束；不同工作区/不同环境可并行）
- 队列增强：ETA 预估（按历史平均执行时长）+ 优先级（manual > 定时 > 批量）
- `run_queue` 状态机已具备（queued/running/finished），槽位变化仅新增 `slot` 列
- 依赖 T-801：多 run 并行时广播必须按 run 隔离

**改造点**：`services/runner.py`（单例→池，广播签名随 T-801）、`user_store.py`（run_queue 加 slot 列）、`routers/runs.py`（状态查询聚合）、前端 RunControl（多 run 并排/队列 ETA 展示）、`scheduler.py`（互斥判断改槽位维度）。
**验收**：并发 2 个不同 (workspace,env) 执行互不干扰；同 (workspace,env) 仍互斥；队列有 ETA 与优先级；abort/超时/断点语义在池化下不回归（复用 T-111/T-112/T-118 测试）。
**开发时机**：**触发制**——排队成为常态（连续一周队列长度 > 3 或等待 > 15 分钟）时启动；属架构级改造（触及 runner 调度语义），开工前须按冻结层评审流程评审。

### T-803 调度忙时排队（替代跳过）

**现状**：`scheduler.py:166-181` 定时任务触发时若 `run_manager.is_running` 直接跳过记 `skipped_busy`——不排队。执行槽被手动任务长期占用时，计划任务可能永远轮不上。

**设计**：
- 忙时入队而非跳过：`scheduled_jobs` 触发时向 run_queue 投递（带 `priority=定时` 标记），T-802 的多槽 + 优先级自然消化
- 保留 skipped_busy 统计（趋势可见：调度被挤占比是「执行槽不足」的观测指标）
- 错峰窗口（可选）：定时任务声明允许窗口（如 22:00-06:00），窗口内排队执行

**改造点**：`services/scheduler.py`、`user_store.py`（队列 priority 字段，若 T-802 已加则复用）。
**验收**：定时任务在手动执行期间入队并最终执行；`skipped_busy` 记录与「入队补跑」两条路径都有日志。
**开发时机**：**挂 T-802 后**；触发：出现定时任务 skipped_busy 反馈（用户可感知的「计划没跑」）。

### T-804 SQLite 写路径演进

**现状**：user/audit/run_queue/draft_gates/scheduled_jobs/sf_*/audit_store 全部写同一 `workbench.db`（WAL + timeout=10s + 每操作短连接）；单次执行收尾会写失败索引 + 执行台账 + 队列状态 + 通知等多张表。

**问题（触发信号）**：100 用户高频操作（登录审计/触发/入库）时写放大，峰值可能出现 `database is locked`（10s 超时）。

**设计（先观测后动刀，三步渐进）**：
1. **观测**：写 TPS 与锁等待打点（SQLite `busy_timeout` 命中计数），量化真实压力——不预设结论
2. **低风险优化**：审计类写（audit_log / sf_mcp_call_audit）改批量/异步落盘（攒批 100ms 或 50 条一写）；高频读走进程内缓存（角色/配置已有部分缓存）
3. **必要时升级**：高频表拆独立 SQLite 文件（按写频率分库）或迁 PostgreSQL（需多 worker 或 HA 时一并评估）

**改造点**：新增 `services/db_metrics.py`（观测）、`audit_store.py`/`user_store.py`（批量写）、必要时存储层拆分。
**验收**：观测期产出一周写 TPS/锁等待报告；优化后峰值写延迟 < 100ms、无 database is locked。
**开发时机**：**触发制**——出现 `database is locked` 或写延迟 > 100ms 时；100+ 峰值前先做观测（低成本可提前）。

### T-806 状态外迁与多机横向扩展【储备】

**现状**：workers=1 硬约束（RunManager 全局单例 + SQLite + 进程内调度器），单机单进程。

**设计**（触发后评估，非默认路径）：
- 执行状态迁出进程：RunManager → Redis 或独立执行进程（HTTP/gRPC），uvicorn 才可多 worker/多机
- SQLite → PostgreSQL（随 T-804 阶段 3 一并）
- 调度器独立进程化（避免多实例重复触发）
- 部署形态：Nginx 反代 + 多 worker + 共享存储（报告/工作区克隆走 NAS/对象存储）

**验收**（触发后定义）：多 worker 下执行队列不重复消费；状态一致；滚动发布零停机。
**开发时机**：**储备，触发制**——100+ 且 T-802/T-804 后仍不足（或出现多团队隔离/HA 硬需求）时启动，**先行评估报告再立项**。

---

## 四、开发时机总表（触发信号 = 何时开发）

| 任务 | 内容 | 依赖 | 规模信号（什么时候开发） | 优先级 |
|------|------|------|------------------------|--------|
| **T-801** | WebSocket 订阅隔离 | — | **35 人起步即可做**（无风险独立）；在线 WS 连接 > 30 时优先 | P1 |
| **T-805** | 服务守护与自动拉起 | — | **35 人起步即可做**（生产正式使用即做，第一位可用性保障） | P2 |
| **T-802** | 执行槽池化 | T-801 | **排队成为常态**：连续一周队列长度 > 3 或等待 > 15 分钟；架构级需评审 | P0 |
| **T-803** | 调度忙时排队 | T-802 | T-802 之后；出现「定时任务没跑」（skipped_busy 用户反馈） | P1 |
| **T-804** | SQLite 写路径演进 | —（观测可提前） | **写锁告警**：database is locked 或写延迟 > 100ms；100+ 峰值前先做观测 | P1 |
| **T-806** | 状态外迁/多机（储备） | T-802/T-804 | **100+ 仍不足**或出现 HA/多团队隔离硬需求；先评估报告再立项 | 储备 |

**决策原则**：
1. **不提前做架构级改造**——T-802 之前的广播隔离（T-801）与守护（T-805）已覆盖 35→100 人过渡期 80% 的可用性问题
2. **信号驱动**——每个触发信号都可观测（队列长度/等待时间/写锁/调度跳过率），由总控人按信号宣布认领，不靠拍脑袋
3. **先观测后动刀**——T-804 的观测期与 T-801 无冲突，可提前布点
