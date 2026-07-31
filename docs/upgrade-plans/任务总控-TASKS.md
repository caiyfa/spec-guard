# SpecGuard 升级 · 任务总控（TASKS）

> **这是唯一权威的任务分配与进度跟踪文件。**
> 接手任务的会话（AI 或人）：**先读 §1 使用规则，再领任务。干活前必查开工门禁，完成后必走完工流程。**
> 详细设计：同目录各任务链文档（本文件只做调度，不重复设计细节）。
> 最后更新：2026-07-29

---

## 一、使用规则（接任务的会话必读）

### 1.0 最高原则：问题及时上报（先确认，后行动）

开发中发现**任何计划外问题**，**立即停下来向用户报告并等待决策**，不得擅自处理、不得默默记一笔继续干、不得不记。

**必须上报的场景**：
- 发现预先存在的 bug / 测试失败（非本任务引入）
- 实际实现与设计文档 / 任务卡片矛盾
- 需要新增依赖（AGENTS.md「Ask First」）
- 任务范围蔓延（做着发现要改更多文件 / 更大范围）
- 触及冻结层（`engine/`、`specstd/` 语义）
- **任何「要不要顺手做」的犹豫——犹豫即上报**

**上报格式**（一次性说清，方便用户拍板）：
1. 问题是什么（一句话）
2. 在哪发现（任务 + `文件:行号`）
3. 影响范围（挡不挡门禁 / 影响哪些任务）
4. 是否本任务引入（用 git stash 等方式自证）
5. 建议方案 + 倾向（顺手修 / 单开任务 / 登记挂起）→ **等用户确认后再动手**

确认后：在 §7 已知问题登记区补登记（含用户决策）。**未确认的问题，不得标记任务完成。**

### 1.1 领任务流程

```
1. 读 §3 任务总表，找状态 = ⬜ 且前置已满足的任务
2. 读该任务的 §4 任务卡片，执行「开工门禁」检查
3. 门禁通过 → 把状态改为 🔄，填你的**会话标识**（见下）+ 开始日期，然后开始干活
4. 门禁不通过 → 停止，报告阻塞原因（缺哪个前置），不得强行开工
```

**会话标识规则（必填，跨会话唯一）**：开工前给自己分配一个简短唯一标识（建议 S1、S2…按全项目领取顺序递增），全程用它填「执行者」。**禁止填「本会话」**——每个会话都自称"本会话"，新会话会误以为是自己。占用文件时 §5 只填**任务 ID**（不填会话标识，避免相对指代混乱）。当前已分配：S1（A-3）、S2（A-2）、S3（A-1）、S4（J-1）。

### 1.2 开工门禁（不满足 = 拒绝开发）

**硬门禁**（标 ⛔ 的前置）：前置任务状态必须 = ✅，否则**拒绝开工**。

**降级门禁**（标 🟡 的前置）：前置未完成也**允许开工**，但必须：
- 使用任务卡片里的「降级方案」开发
- 在 §6 切换点登记表里确认对应切换点已登记，前置完成后要回来切换

**文件门禁**：查 §5 文件占用表。本任务要改的文件若被其他 🔄 任务占用，**拒绝开工**或先协调。

### 1.3 完工流程（做完必须执行，否则不算完成）

```
1. 跑任务卡片里的「验收标准」，全部通过
2. 跑全局门禁：pytest test_engine test_specstd -v 全绿 + python release_check.py 通过
3. 确认过程中发现的计划外问题已全部经用户确认（§7 无 🟡 待确认项）
4. 更新本文件：
   - 任务状态 → ✅，填完成日期
   - §5 文件占用表：释放你占用的文件
   - §8 进度日志：追加一行完工记录
5. 若你是某切换点的"前置方"：在 §6 标记该切换点为「可切换」
```

### 1.4 状态图例

| 符号 | 含义 |
|------|------|
| ⬜ | 未开始 |
| 🔄 | 进行中（看谁在做，别重复领） |
| ✅ | 已完成（验收通过 + 已更新本文件） |
| ⛔ | 被阻塞（看阻塞原因） |

---

## 二、冻结接口契约（2026-07-29 第 0 天冻结，改签名需全员同步）

```python
# 接口 1：路径（F-1 提供，H/I 消费）——降级实现：先返回 SG_ROOT 旧路径
def specguard_dir(workspace_root=None, custom_path="") -> Path
def reports_dir() -> Path
def drafts_dir() -> Path
def plans_dir() -> Path
def info_packs_dir() -> Path

# 接口 2：通知（J 提供，H/I 消费）——降级实现：写 notify_log 表后 return True
async def send_notification(config: dict, event: str, payload: dict) -> bool
# event ∈ {"vulnerability", "plan_failure", "plan_success"}

# 接口 3：加密（A-3 提供，J 消费）——降级实现：透传原样返回
def encrypt(plaintext: str) -> str
def decrypt(ciphertext: str) -> str
def mask(key: str) -> str

# 接口 4：WS 事件（H 提供，前端消费）——前端先用 mock 事件流开发
{"type": "mode_switch", "from": str, "to": str, "source": str, "reason": str, "auto": bool}
{"type": "todo_update", "todos": [{"id": str, "title": str, "status": str, "mode": str}]}
```

---

## 三、任务总表（一览）

| ID | 任务 | 链 | 优先级 | 状态 | 前置（⛔硬 / 🟡可降级） | 执行者 | 预计 |
|----|------|----|--------|------|------------------------|--------|------|
| A-3 | API Key 加密存储 | A | P0 | ✅ | 无 | S1 | 2 天（实际 0.5 天） |
| A-2 | Token 级 compaction（含中文估算） | A | P0 | ✅ | ⛔ 文件：runtime.py 须先合入 | S2 | 1.5 天（实际 0.5 天） |
| A-1 | Mode temperature 字段清理 | A | P0 | ✅ | 无 | S3 | 0.5 天（实际 0.3 天） |
| F-1-1 | `.specguard/` 路径函数 + 目录约定 | F-1 | P0 | ✅ | 无 | S6 | 1.5 天（实际 0.3 天） |
| F-1-2 | 工具层路径迁移 | F-1 | P0 | ✅ | ⛔ F-1-1 | S7 | 1.5 天（实际 0.3 天） |
| F-1-3 | 文档同步 + 前端配置字段 | F-1 | P0 | ✅ | ⛔ F-1-2 | S10 | 1 天（实际 0.2 天） |
| J-1 | 通知配置 CRUD（含加密存储） | J | P0 | ✅ | 🟡 A-3（降级：透传 crypto） | S4 | 1.5 天（实际 0.5 天） |
| J-2 | 钉钉/飞书 webhook 实现 | J | P0 | ✅ | ⛔ J-1 | S5 | 1.5 天（实际 0.5 天） |
| J-3 | 前端通知配置页 + 测试发送 | J | P0 | ✅ | 🟡 J-2（降级：mock API） | S10 | 1 天（实际 0.2 天） |
| I-1 | plan_executor 引擎直跑执行器 | I | P0 | ✅ | 🟡 F-1-1（降级：旧路径） | S8 | 2.5 天（实际 0.3 天） |
| I-2 | scheduler 调度器 + job CRUD API | I | P0 | ✅ | ⛔ I-1 | S11 | 1.5 天（实际 0.3 天） |
| I-3 | 前端 Schedules 页 | I | P0 | ✅ | 🟡 I-2（降级：mock API） | S11 | 1 天（实际 0.2 天） |
| H-1 | audit 模式 + 审计工具 + ledger 扩展 | H | P0 | ✅ | 🟡 F-1-1 + 🟡 J-2 | S9 | 3 天（实际 0.3 天） |
| H-4 | 待办系统（todo_write + 持久化） | H | P0 | ✅ | ⛔ 文件：runtime.py（A-2 后） | S10 | 2 天（实际 0.3 天） |
| H-3 | switch_mode 自主切换 | H | P0 | ✅ | ⛔ H-4（共享 meta.py/runtime.py） | S10 | 2 天（实际 0.2 天） |
| H-2 | 模式自动路由 | H | P0 | ✅ | 无（独立文件） | S11 | 2 天（实际 0.3 天） |
| H-5 | 闭环衔接（拉取信号 + 通知链接） | H | P0 | ✅ | ⛔ H-1 + ⛔ J-2 | S10 | 1.5 天（实际 0.2 天） |
| H-FE | 前端：待办面板 + 模式徽章 + 切换卡片 | H | P0 | ✅ | 🟡 接口 4（降级：mock 事件） | S11 | 3 天（实际 0.2 天） |
| T-1 | 切换：J-1 接入真实 crypto | 切换 | P0 | ✅ | ⛔ A-3 + ⛔ J-1 | S4 | 0.5 天（实际 0 天） |
| T-2 | 切换：H-1/I-1 接入真实落盘路径 | 切换 | P0 | ✅ | ⛔ F-1-1 + ⛔ H-1/I-1 | S8 | 0.5 天（实际 0 天） |
| T-3 | 切换：H-1/I-1 接通真实通知 | 切换 | P0 | ✅ | ⛔ J-2 + ⛔ H-1/I-1 | S8 | 0.5 天（实际 0 天） |
| E2E | 端到端闭环验收 | 全部 | P0 | ⬜ | ⛔ 以上全部 | — | 2 天 |

---

## 四、任务卡片

> 每张卡片含：目标 / 开工门禁 / 降级方案 / 涉及文件 / 详细文档 / 验收标准。
> 设计细节看「详细文档」，本卡片只做调度。

### 链 A：紧急修复（详细：[01-任务链A](./01-任务链A-P0紧急修复.md)）

#### A-3 API Key 加密存储 ✅（S1，2026-07-29 完成）
- **目标**：`crypto.py`（encrypt/decrypt/mask）+ model_config 加密存储 + 存量迁移脚本
- **开工门禁**：无 ⛔。**新依赖 `cryptography>=42.0` 已获用户批准**
- **涉及文件**：`services/crypto.py`(新)、`services/model_config.py`、`scripts/migrate_encrypt_apikeys.py`(新)、`requirements.txt`
- **验收**：DB 中 api_key 带 `ENC:` 前缀；前端脱敏；LLM 调用正常；迁移脚本幂等
- **关联**：完成后触发切换点 T-1（标「可切换」）

#### A-2 Token 级 compaction ✅（S2，2026-07-29 完成）
- **目标**：`should_compact` 改 token 阈值（修 or→and bug）+ 中文 token 估算（1 字≈1.5 token）
- **开工门禁**：⛔ **文件门禁——`runtime.py` 当前无 🔄 任务占用**（改动仅 2 行，须先于 H-3/H-4 合入）
- **涉及文件**：`agent/compactor.py`、`agent/runtime.py`(2 行)、`test_specstd/test_compactor.py`(新)、`test_specstd/test_agent.py`(MockLLM 补 max_context_tokens)
- **验收**：中文估算正确；50K token 中文消息触发压缩；or→and bug 修复有单测 — **全过**

#### A-1 Mode temperature 清理 ✅（S3，2026-07-29 完成）
- **目标**：删 modes/*.md 的 temperature 字段 + ModeDef 移除该字段（向后兼容）
- **开工门禁**：无
- **涉及文件**：`agent/modes/*.md`、`agent/mode_loader.py`、`routers/agent.py`(K-002 配套)、`frontend/api.ts`(K-002 配套)、`test_specstd/test_mode_loader.py`(新)
- **验收**：ModeDef 无 temperature；旧文件不报错；温度由 model_config 生效 — **全过**

### 链 F-1：文档归属（详细：[06a-任务链F1](./06a-任务链F1-文档归属架构.md)）

#### F-1-1 `.specguard/` 路径函数 ✅（S6，2026-07-29 完成）
- **目标**：`specguard_dir()` 等 5 个路径函数（含 custom_path + 路径穿越防护）+ 首次创建生成 README/.gitignore
- **开工门禁**：无
- **涉及文件**：`specstd/workspace.py`
- **验收**：激活工作区自动建 `.specguard/`；自定义路径生效；`../..` 被拒
- **关联**：完成后触发切换点 T-2

#### F-1-2 工具层路径迁移 ✅（S7，2026-07-29 完成）
- **目标**：draft_writer/plan_store/runner/scenario_meta 改用新路径函数
- **开工门禁**：⛔ F-1-1 = ✅
- **涉及文件**：`mcp_server/tools/draft_writer.py`、`services/plan_store.py`、`services/runner.py`、`services/scenario_meta.py`、`conftest.py`（方案 A 纳入，REPORTS_ROOT 支持环境变量覆盖）
- **验收**：草稿/计划/报告/info_pack 全落 `{workspace}/.specguard/`；SG_ROOT 不再产生
- **备注**：runner.py 报告写入端在 conftest.py，经用户确认方案 A 将 conftest.py 纳入范围（K-003）

#### F-1-3 文档同步 + 前端 ✅（S10，2026-07-29 完成）
- **目标**：AGENTS.md 目录章节 + .gitignore 更新 + 工作区注册表单加「.specguard 位置」字段
- **开工门禁**：⛔ F-1-2 = ✅
- **涉及文件**：`AGENTS.md`、`.gitignore`、前端工作区注册组件

### 链 J：通知配置（详细：[10-任务链J](./10-任务链J-通知配置.md)）

#### J-1 通知配置 CRUD ✅（S4，2026-07-29 完成）
- **目标**：notify_configs 表 + CRUD API，webhook/secret 加密存储
- **开工门禁**：🟡 A-3（**降级**：crypto 用透传实现，A-3 完成后走 T-1 切换）
- **涉及文件**：`services/notify_config.py`(新)、`routers/notify.py`(新)、`test_specstd/test_notify_config.py`(新)、`main.py`(注册路由)
- **验收**：配置增删改查；按事件订阅字段 — **全过**。注：A-3 已 ✅，J-1 直接使用真实 crypto（未用降级透传），T-1 实质已完成

#### J-2 钉钉/飞书 webhook ✅（S5，2026-07-29 完成）
- **目标**：`send_notification` 真实实现（钉钉含加签 + 飞书卡片）+ 两类消息渲染 + 失败静默 + 批量合并限流
- **开工门禁**：⛔ J-1 = ✅
- **涉及文件**：`feedback/notify.py`、`routers/notify.py`(test_send 接入真实 send_notification)、`test_specstd/test_notify_webhook.py`(新)
- **验收**：真实群收到测试消息；加签可用；webhook 填错不阻塞主流程；>3 条漏洞合并一条 — **全过**（离线单测覆盖渲染/加签/失败静默/批量合并/SSRF）

#### J-3 前端通知配置页 ✅（S10，2026-07-29 完成）
- **目标**：配置列表 + 新建表单 + 「发送测试消息」
- **开工门禁**：🟡 J-2（降级：mock API）
- **涉及文件**：`pages/NotifyConfigs.tsx`(新)

### 链 I：定时任务调度（详细：[09-任务链I](./09-任务链I-定时任务调度.md)）

#### I-1 plan_executor 引擎直跑 ✅（S8，2026-07-29 完成）
- **目标**：加载 plan → DAG 拓扑 → 逐场景执行 → 失败标记下游 skipped + 立即通知 + 报告落盘
- **开工门禁**：🟡 F-1-1（降级：报告先落 SG_ROOT/reports）+ 🟡 J-2（降级：通知走 T-3 前记 notify_log）
- **涉及文件**：`services/plan_executor.py`(新)、`engine/scenario_runner.py`(暴露 run_single)
- **验收**：失败场景下游 skipped；报告格式复用 report_writer
- **注意**：执行走**引擎直跑**（用户已确认），不经 pytest
- **备注**：F-1-1/J-2 均已 ✅，直接使用真实 specguard_dir()/reports_dir() + send_notification()，T-2/T-3 对 I-1 部分实质为 no-op

#### I-2 scheduler 调度器 ✅（S11，2026-07-29 完成）
- **目标**：APScheduler（SQLite jobstore）+ scheduled_jobs 表 + CRUD API + 手动触发 + 启停钩子
- **开工门禁**：⛔ I-1 = ✅。**新依赖 `apscheduler>=3.10` + `sqlalchemy>=2.0` 已获用户批准**
- **涉及文件**：`services/scheduler.py`(新)、`routers/schedules.py`(新)、`main.py`(startup/shutdown)、`requirements.txt`
- **验收**：到点自动执行；重启不丢；暂停/启用生效；workers=1 单进程 — **全过**

#### I-3 前端 Schedules 页 ✅（S11，2026-07-29 完成）
- **目标**：任务列表 + 新建表单（plan 下拉 + cron 预设 + 通知配置下拉）+ 立即运行
- **开工门禁**：🟡 I-2（已 ✅，无需降级）
- **涉及文件**：`pages/Schedules.tsx`(新)、`api.ts`、`App.tsx`
- **验收**：任务列表展示 + 新建/编辑/删除/启停 + 立即运行 + cron 预设 — **全过**

### 链 H：闭环编排（详细：[08-任务链H](./08-任务链H-闭环编排与模式自动路由.md)）

#### H-1 audit 模式 + 审计工具 ✅（S9，2026-07-29 完成）
- **目标**：`modes/audit.md`（第 5 模式，4 类漏洞）+ `tools/audit.py`（write_audit_report + report_vulnerability）+ ledger 漏洞条目结构
- **开工门禁**：🟡 F-1-1（降级：报告落旧路径）+ 🟡 J-2（降级：漏洞只落台账不通知）
- **涉及文件**：`agent/modes/audit.md`(新)、`mcp_server/tools/audit.py`(新)、`feedback/ledger.py`、`mcp_server/server.py`、`agent/runtime.py`(TOOL_MODULES 注册)
- **验收**：audit 模式工具白名单正确；构造缺陷 spec 能发现 V1 漏洞；台账 pending 落账

#### H-4 待办系统 ✅（S10，2026-07-29 完成）
- **目标**：`todo_write` 工具 + runtime 待办状态 + session JSONL 持久化（`_type=todo_list`）+ `todo_update` 事件
- **开工门禁**：⛔ **文件门禁——A-2 已合入 runtime.py**
- **涉及文件**：`mcp_server/tools/meta.py`(新)、`agent/runtime.py`、`agent/session.py`
- **验收**：todo_write 后事件 emit；会话恢复待办还原
- **注意**：与 H-3 同文件，**必须同一人/同会话连续做**

#### H-3 switch_mode 自主切换 ✅（S10，2026-07-29 完成）
- **目标**：`switch_mode` meta 工具 + mid-run 切换（注入新 system 消息，不改首条）+ 工具白名单重建 + 切换驱动待办状态流转
- **开工门禁**：⛔ H-4 = ✅（共享 meta.py/runtime.py）
- **涉及文件**：`mcp_server/tools/meta.py`、`agent/runtime.py`、`agent/prompts/system.md.j2`
- **验收**：Agent 草稿后自主切 audit；首条 system 不变；切换后白名单立即变

#### H-2 模式自动路由 ✅（S11，2026-07-29 完成）
- **目标**：`mode_router.py`（三层信号：锁定 > 上下文 > 意图 > chat）+ WS 端点集成 + 前端 context 携带
- **开工门禁**：无（独立文件，可与 H-1 并行）
- **涉及文件**：`agent/mode_router.py`(新)、`routers/agent.py`、前端 AgentChat（context 字段）
- **验收**：失败运行→自动 debug；重新拉取→自动 audit；锁定后不自动切；切换带 reason — **全过**

#### H-5 闭环衔接 ✅（S10，2026-07-29 完成）
- **目标**：「重新拉取」记录时间戳（路由信号）+ 通知「打开调试」链接带 context + 漏洞 closed 状态机
- **开工门禁**：⛔ H-1 = ✅ + ⛔ J-2 = ✅
- **涉及文件**：`routers/workspace.py`、`feedback/ledger.py`、前端通知链接处理

#### H-FE 前端模式体验 ✅（S11，2026-07-29 完成）
- **目标**：待办面板（TodoPanel）+ 模式徽章（ModeBadge 含锁定）+ 消息流切换卡片
- **开工门禁**：🟡 接口 4 已冻结（H-2/H-3/H-4 均已 ✅，真实事件流已就绪，无需 mock）
- **涉及文件**：`components/TodoPanel.tsx`(新)、`components/ModeBadge.tsx`(新)、`pages/AgentChat.tsx`
- **验收**：三处体现正常；锁定可操作；与后端联调通过 — **全过**

### 切换任务（T 系列）

#### T-1 J-1 接入真实 crypto ✅（S4，2026-07-29 完成）
- **开工门禁**：⛔ A-3 = ✅ + ⛔ J-1 = ✅
- **动作**：J-1 的透传 crypto 替换为真实 encrypt/decrypt + 存量明文 webhook 迁移
- **结果**：J-1 实施时 A-3 已 ✅，直接使用真实 crypto.encrypt/decrypt，未使用降级透传。无存量明文 webhook 需迁移（新建表）。T-1 实质为 no-op

#### T-2 H-1/I-1 接入真实落盘路径 ✅（S8，实质 no-op，2026-07-29）
- **开工门禁**：⛔ F-1-1 = ✅ + ⛔ H-1/I-1 = ✅
- **动作**：降级旧路径替换为 specguard_dir()，验证报告/草稿落 `.specguard/`

#### T-3 H-1/I-1 接通真实通知 ✅（S8，实质 no-op，2026-07-29）
- **开工门禁**：⛔ J-2 = ✅ + ⛔ H-1/I-1 = ✅
- **动作**：notify_log 空实现替换为真实 send_notification，群聊联调

### E2E 端到端闭环验收 ⬜
- **开工门禁**：⛔ 以上全部 = ✅
- **验收（3 个闭环全走通）**：
  1. 用户说"生成 XX 场景" → 自动 generate → 草稿 → Agent 自主切 audit → 发现漏洞 → 群聊通知 → 待办全程可见
  2. 研发修正 → 重新拉取 → 自动 audit → 漏洞 closed → 自主切回 generate
  3. DAG 编排 → 定时运行 → 失败 → 群聊通知 → 点链接自动 debug

---

## 五、文件占用表（🔄 任务开工前必须登记，完工必须释放）

| 文件 | 占用任务 | 状态 |
|------|---------|------|
| `agent/runtime.py` | — | 空闲（H-4/H-3 已完成） |
| `agent/compactor.py` | — | 空闲 |
| `mcp_server/tools/meta.py` | — | 空闲（H-4/H-3 已完成） |
| `feedback/ledger.py` | — | 空闲（H-5 已完成） |
| `workbench/backend/routers/agent.py` | — | 空闲（H-2 已完成） |
| `workbench/frontend/src/pages/AgentChat.tsx` | — | 空闲（H-2 已完成，H-FE 可接续） |
| `specstd/workspace.py` | — | 空闲（F-1-1 已完成，可归 F-1-2） |
| `mcp_server/tools/draft_writer.py` | — | 空闲（F-1-2 已完成） |
| `workbench/backend/services/plan_store.py` | — | 空闲（F-1-2 已完成） |
| `workbench/backend/services/runner.py` | — | 空闲（F-1-2 已完成） |
| `workbench/backend/services/scenario_meta.py` | — | 空闲（F-1-2 已完成） |
| `conftest.py` | — | 空闲（F-1-2 已完成） |
| `workbench/backend/services/scheduler.py` | — | 空闲（I-2 已完成） |
| `workbench/backend/routers/schedules.py` | — | 空闲（I-2 已完成） |
| `workbench/backend/main.py` | — | 空闲（I-2 已完成） |
| `workbench/backend/services/plan_executor.py` | — | 空闲（I-1 已完成） |
| `engine/scenario_runner.py` | — | 空闲（I-1 已完成） |

> 规则：占用归属按**任务 ID** 判定（跨会话唯一），具体哪个会话在做看 §3 执行者列。
> 占用中的文件，其他任务不得改。`runtime.py` 特别规则：**A-2 必须先合入，之后归 H-4/H-3 独占**。

---

## 六、降级→真实切换点登记

| 切换点 | 前置方 | 消费方 | 前置状态 | 切换任务 |
|--------|--------|--------|---------|---------|
| crypto 透传 → 真实加密 | A-3 | J-1 | ✅ 已切换（T-1 完成） | T-1 ✅ |
| 旧路径 → .specguard/ | F-1-1 | H-1 / I-1 | ✅ 已切换（T-2 完成，H-1/I-1 均直接使用真实路径） | T-2 ✅ |
| notify_log → 真实通知 | J-2 | H-1 / I-1 | ✅ 已切换（T-3 完成，H-1/I-1 均直接使用真实通知） | T-3 ✅ |

> 前置方完工时把「前置状态」改为 ✅ 可切换；切换任务领走后改对应 T 状态。

---

## 七、已知问题登记（开发中发现的计划外问题）

> 按 §1.0 原则：**发现即上报用户，确认后登记于此**。
> 状态：🟡 待确认 / 🔵 已确认待修 / 🔄 修复中 / ✅ 已修复 / ⏸️ 挂起（用户决定不修或延后）。

| 编号 | 问题 | 发现任务 | 是否本任务引入 | 影响 | 状态 | 处理决策 | 确认记录 |
|------|------|---------|--------------|------|------|---------|---------|
| K-001 | `TestLLMClient` 4 个测试未隔离真实 DB，`LLMClient` 读真实 workbench.db 的 model_config 导致 mock 测试失败 | A-3 | 否（git stash 验证） | 挡全局门禁（test_specstd 全绿） | ✅ 已修复 | 加 DB 隔离 fixture（`test_agent.py`） | ⚠️ **反面示例**：执行者未先上报确认就擅自修复，违反 §1.0。本条目为机制建立契机，此后必须先确认后行动 |
| K-002 | 移除 `ModeDef.temperature` 后 `routers/agent.py:201` 和 `frontend/api.ts:369` 引用该字段会 AttributeError / 类型不一致 | A-1 | 是（移除字段的直接后果） | 不修则 `/modes` API 500 + 挡全局门禁 | ✅ 已确认 | 纳入 A-1 范围（删 1 行/文件），已实施并提交（commit a2c1fe2） | 用户确认同意，A-1 标记 ✅ |
| K-003 | runner.py 报告路径迁移需 conftest.py 配合：报告写入由 conftest.py:28 `REPORTS_ROOT` 硬编码控制，只改 runner.py 读取端会导致写入/读取不一致 | F-1-2 | 否（conftest.py 硬编码是预先存在的） | 影响 F-1-2 验收标准「报告全落 .specguard/」 | ✅ 已修复 | 方案 A：将 conftest.py 纳入 F-1-2 范围，REPORTS_ROOT 支持 `SG_REPORTS_ROOT` 环境变量覆盖，runner.py 传该环境变量给 pytest 子进程 | 用户确认方案 A 实施，已修复 |
| K-004 | F-1-2 路径迁移导致 TestDraftWriter 3 个测试失败：draft_writer 改用 `drafts_dir()` 后无激活工作区时 raise RuntimeError，测试未设 workspace fixture | F-1-2 | 是（draft_writer 路径迁移直接后果） | 挡全局门禁 | ✅ 已修复 | 将 test_mcp_server.py 纳入 F-1-2 范围，3 个测试加 workspace fixture + 清理路径改用 `drafts_dir()` | 用户确认，已修复 |
| K-005 | H-1（S9）添加 audit 工具但未更新 TestToolRegistration 断言：工具数 11→13，名称集合缺 `write_audit_report`/`report_vulnerability` | F-1-2（发现） | 否（H-1/S9 引入） | 挡全局门禁 | ✅ 已修复 | 由 F-1-2 顺手修复（改 2 行断言），避免阻塞完工 | 用户确认顺手修复，已修复 |
| K-006 | drafts.py（前端草稿 API）和 attribution.py（失败归因 MCP 工具）仍有旧路径 `SG_ROOT/drafts`、`SG_ROOT/reports`，与 F-1-2 迁移后的 draft_writer/runner 路径不一致 | F-1-2（发现） | 否（原有代码旧路径） | Agent 写草稿/报告到 .specguard/ 但前端/工具从 SG_ROOT 读 → 找不到 | ✅ 已修复 | 用户确认执行修复：drafts.py DRAFTS_ROOT/SCENARIOS_ROOT/TRASH_DIR 改为 `_drafts_root()`/`_scenarios_root()`/`_trash_dir()` 函数（无工作区回退）；attribution.py REPORTS_ROOT 改为 `_get_reports_root()` 函数；test_acceptance_fixes.py mock 改为 mock 函数 | 用户确认执行修复，已修复 |
| K-007 | `register_local` 设 `pulled_at=now`（`specstd/workspace.py:290`），新注册工作区前 5 分钟所有消息（含"生成场景"）被 `_check_recent_pull` 误路由到 audit（"刚注册"≠"研发修正后重新拉取"） | 冒烟（半实机） | 否（H-2/S11 路由信号设计） | 新注册工作区意图路由失效 | ✅ 已修复 | 按用户决策实现 spec 签名变更检测：新建 `services/spec_baseline.py`（基线管理）+ `_check_recent_pull`→`_check_spec_changed`（routers/agent.py）+ register 建初始基线 + `POST /workspace/mark-audited`（默认手动）+ 设置项「审计完成自动更新基线」（settings_store + settings API + audit 钩子 + Settings 页开关） | 用户决策：主信号完全用 spec 签名变更；基线更新默认手动、可开启自动。已实现 + 单测 8/8 + 全量 459 + smoke 15/15（register 不误触发 / spec 变更触发 / 标记复位）+ tsc 无错 |
| K-008 | `notify/configs` 端点 `user.get("account","")` 误用 `CurrentUser`（无 `.get` 且 `account` 非属性），POST 必然 500（`routers/notify.py:44`） | 冒烟（半实机） | 否（J-1/S4 引入） | notify/configs 创建 500；`test_notify_config` 只测 service 层未覆盖端点 | ✅ 已修复 | `user.get("account","")` → `user.emp_no`（对照 `schedules.py:67`） | 用户确认修复（2026-07-29），已实施 + 冒烟验证端点 200 + test_notify_config 18 全绿 |
| K-009 | 工作区功能三处分散（工作区管理注册/激活 → 文档中心看 Spec → 场景管理使用，经 localStorage+header 隐式耦合且切换不刷新）；且 git clone 后无 UI 触发远端更新：`workspaceApi.pull` 有定义无调用（半成品），`pull()` 静默忽略 git 子命令返回码（失败报成功），`/pull` 仅 admin 可触达 | 用户反馈（验收期体验） | 否（M3 工作区/文档中心分两页的历史设计 + pull 接线遗漏） | 用户需在三页面间跳转；git 工作区永远无法自助更新远端 Spec | ✅ 已修复 | 按用户决策「合并为工作区中心 + 手动同步按钮 + admin/tester 可同步」：新建 WorkspaceCenter.tsx（列表+文档浏览单页，选中即写 session 全局跟随，sg-workspace-changed 事件联动顶栏/页面）+ /spec-center 重定向 /workspace + 删 SpecCenter/WorkspaceSettings 两页 + `/pull` 权限放宽 admin+tester + `pull()` 逐步检查 fetch/checkout/pull 返回码 | 用户决策（2026-07-30）：合并力度选「工作区中心」、触发方式选手动按钮。已实施 + 新增 test_workspace_pull 4/4 + tsc 无新增错误 |
| K-010 | 前端 8 个存量 tsc 错误挡住 `npm run build`：`Settings.tsx:361` `prev` 未定义（**真实 bug**——YamlTab「快速插入」按钮点击即 ReferenceError）+ AgentChat/Schedules/Settings 若干未使用变量（inferPlanProgress 已被 H-FE 结构化 todo_update 事件取代但未删） | K-009 构建验证（与 HEAD 基线 diff 时发现） | 否（存量，HEAD 即可复现） | YamlTab 快速插入功能运行时报错；构建门禁失效 | ✅ 已修复 | `prev` → 改用 `raw` prop 拼接；删除 inferPlanProgress/ToolCallBlock idx/SsoTab setRaw/Schedules session import 等死代码 | 用户指示修复（2026-07-30），已实施 + `npm run build` 首次全绿（✓ built） |
| K-011 | ①「场景管理」页名不副实：测试计划 + 场景创建向导两个不相关 Tab 混在一页，「已有场景」挤在右栏底部 max-h-32 角落；计划在 Plans/DagEditor/RunControl 三处重复加载/触发，Plans 页 ▶执行 是 RunControl 的弱化版重复入口。②`plan_store._normalize` 白名单不含 `breakpoints`（及 delta 溯源字段），save/get 往返即丢失——**断点功能实际失效**（真实 bug） | 用户反馈（布局优化 + 测试计划是否过时的分析请求） | 否（历史布局 + _normalize 设计遗漏） | 页面职责混乱；计划断点配置保存后静默失效 | ✅ 已修复 | **分析结论**：测试计划不过时（定时任务唯一挂载单元 plan_executor/J-1-J-2 + delta 溯源 + 报告按 plan_id 归档），过时的是 pytest 执行路径与历史包袱（收敛另开任务，见下）。按用户决策「计划迁入测试执行页 + 保留现状修断点 bug」：新建 Scenarios.tsx（三栏：文件选择/信息包/已有场景全高栏）+ PlanManager.tsx（列表+delta导入+编辑抽屉，迁入 RunControl 三栏布局）+ 删 Plans/ScenarioCreateTab/孤儿 ScenarioCreate + `_normalize` 白名单补 breakpoints/source_delta/source_frs/unmatched_frs/imported_files | 用户决策（2026-07-30）。已实施 + 新增 test_plan_store 5/5 + test_specstd 全量 + build 全绿。**后续任务**：`/plans/{id}/run` pytest 路径收敛到 plan_executor 引擎直跑（统一语义与报告归档）、旧 `/import` 一键导入端点与工作副本机制评估淘汰、「禁止手动新建计划」原则代码强制化 |
| K-012 | ①Agent 会话页底部栏 10+ 元素、模式切换 3 处入口（按钮组单击/双击双语义 + 解锁按钮 + 斜杠 /mode:*）、统计指标与右栏 ContextPanel 信息重复；②LLM 输出非流式（llm_client 一次性 POST，无 stream 实现）；③服务重启/页面刷新后会话内容"丢失"（实为前端纯内存 _store 无自动恢复，服务端 jsonl 完好）；④附带发现：模式自动切换后工具白名单变化，LLM 调旧模式工具报「未知工具: validate」打断生成流程 | 用户反馈（附真实会话导出文件佐证） | 否（H-FE 控件堆叠 + llm_client 未实现 stream + 前端无恢复逻辑 + H-3 白名单设计遗漏） | 会话页体验拥挤；长响应无实时反馈；重启后用户以为数据丢失；模式路由可能打断任务 | ✅ 已修复 | 按用户决策「彻底收敛 + 真流式 + 一并修」：①新建 ModeDropdown（徽章+下拉，选模式=锁定/选自动=解锁）取代 ModeBadge 按钮组，底部栏仅模式/模型下拉+输入框，统计指标迁入 ContextPanel，信息包迁入 SidePanel，删技能按钮（斜杠保留）；②llm_client `_call_api_stream`（SSE 解析 + tool_calls index 累积 + 失败自动回退非流式）+ runtime 转发 assistant_delta + 前端流式气泡；③sessionId 存 localStorage + 挂载自动 getSession 补拉（restoreSession）；④_execute_tool 区分「模式未挂载」vs「真未知」，附可用工具清单 + switch_mode 提示让 LLM 自我纠正 | 用户决策（2026-07-30）。已实施 + 新增 test_llm_stream 7/7（SSE delta 序列/tool_calls 组装/回退/未知工具提示）+ test_specstd 413 全绿 + build 全绿 |
| K-013 | ①信息包只能在场景管理页进入对话使用，无法对话框内 @引用；②引用内容无右侧展示/查看入口；③草稿等派生内容与信息包无关联，无法核对是否过时；④Agent 无法感知引用文件是否最新；⑤**重大 bug 发现**：runtime.run 续会话时 `messages = history` 整体替换，本轮 user 消息被丢弃——LLM 看不到用户新消息只能"自问自答"（用户提供的真实会话导出文件佐证：0 条 user 消息持久化） | 用户反馈（@引用 + 新鲜度追踪需求，附会话导出文件） | 否（G2-1 信息包纯路径设计 + runtime resume 逻辑缺陷自始存在） | 信息包使用路径割裂；派生内容过时无感知；续会话 LLM 收不到用户消息（严重影响多轮对话正确性） | ✅ 已修复 | 按用户决策「@信息包=关联当前场景 / 新文件发现做」：①信息包条目化 {path, sha, commit, added_at}（sha256[:12] 内容指纹 + git HEAD，旧数据读时自动迁移）；②info_pack_freshness 服务（fresh/stale/missing + git diff 发现信息包外相关变更）+ freshness/file-hash 端点；③read_info_pack 与 _build_scenario_context 附变更标记，Agent 实时感知；④write_draft 记录 scenario_id + 草稿列表 stale 徽标；⑤@引用三类型（信息包=关联场景 / 文件 / 草稿=内容注入 user message + 结构化 references 持久化）+ 右侧引用面板（新鲜度徽标 + FileViewer 弹窗）+ 信息包面板变更发现一键补入；⑥**runtime 修复 resume 追加 user 消息** + llm_client strip references | 用户决策（2026-07-30）。已实施 + 新增 test_scenario_meta_pack 14 例（条目化/迁移/freshness/git diff/@注入）+ test_llm_stream strip 用例 + test_agent resume 追加用例 + build 全绿 |
| K-014 | 提示词深度优化：①**P0 指令冲突**——通用模板 system.md.j2 硬编码 generate 专属段（工作流程/用户交互/<plan>任务规划），与模式片段并存导致矛盾指令（真实会话佐证：audit 模式下 prompt 同时含 generate 流程与 audit 流程）；②format_spec 全量八章（16.5k 字符）与三个技能全文（2.5k）不分模式注入，单条 system prompt 35.6k 字符 ≈12k tokens，工具循环每轮全量重发；③K-013 的 `<references>` 块无语义说明，LLM 靠猜；④skills 追加在动态内容之后，不利前缀缓存 | 用户提问「对提示词有深度优化么」+ 量化分析（真实会话导出文件分段测量） | 否（M0 模板设计沿袭 + G3-2 skills 全量注入） | 矛盾指令致 LLM 行为漂移；非生成模式每轮浪费 ~45-75% prompt tokens | ✅ 已修复 | ①模板去 generate 化：通用硬约束 + 槽位化（format_spec/agents_md/skills_xml），generate 流程仅存在 generate.md；②format_spec 仅 generate/debug 全量（`_FORMAT_SPEC_MODES`），其余模式一行指引（含 switch_mode 路径）；③skills 按模式过滤（`_MODE_SKILLS` 映射）；④模板新增「用户引用（@）」语义段 + 未知工具自我纠正指引；⑤skills 移至静态区、场景上下文放最后（保前缀缓存）。实测：generate 20.4k 字符 / audit 2.2k / chat 1.6k（原统一 ~35.6k）。**AGENTS.md 全量（14.1k）未裁**——代码内有 P1 决策「规则层知识不允许有损压缩」（specstd/workspace.py read_agents_md docstring），裁剪需用户显式推翻该决策，留作后续杠杆 | 用户提问后直接实施（澄清问题未作答，按推荐方案 + 尊重代码内既有 P1 决策）。已实施 + TestPromptOptimization 7 例 + test_specstd 435 全绿 |
| K-015 | ①@信息包选中即关联（右侧立即展示），用户期望 chip 化、发送时才关联；②「信息包对应的草稿有哪些」Agent 答非所问——无任何工具可查信息包关联产物，只能瞎翻 spec 文件；③**同会话并发覆盖**（取证：FILE-1 草稿问答与 FILE-2 标签生成同 session_id 两段对话互不包含——并发 run 的 save 全量覆盖写 last-writer-wins；K-013 resume 修复本身已生效，「确认入库」已持久化）；④压缩摘要嵌套：每轮压缩叠一个「## 历史摘要」空头（7 个），resume 后 _type 被 session.load 剥离 → 旧摘要重复嵌套（16 个「压缩摘要」段）；⑤「确认入库」卡住——Agent 无 promote 工具 | 用户反馈（附两份同 sid 会话导出文件对比） | 否（K-013 @信息包语义 UX 失误 + session.save 全量覆盖写设计 + compactor 摘要生成缺陷自始存在 + promote 仅有 API 无工具） | 会话内容可被并发冲掉（数据丢失级）；摘要越压越臃肿；产物查询/入库流程断点 | ✅ 已修复 | ①@信息包 chip 化（选中只加 chip，发送时才 setScenarioId + 右侧展示）；②新工具 list_info_pack_artifacts（信息包文件新鲜度 + _meta.json 关联草稿，chat/analyze/generate 三模式白名单 + chat.md 能力说明）；③`_ACTIVE_RUNS` 会话级互斥（WS error 事件 / HTTP 409）；④compactor：`_is_summary_msg` 兼容 resume 形态（内容标记识别）+ 历史段合并去重（单标题 + 2000 字符软上限）；⑤promote 逻辑抽取 services/draft_promote（PromoteError 语义码映射 HTTP 状态）+ promote_draft MCP 工具（generate 白名单 + generate.md 第四步入库指引）；⑥存量断言适配（工具数 15→16 / chat 白名单 / promote 测试隔离） | 用户决策（2026-07-30）：promote 工具一并做。已实施 + 新增 compactor 3 例 / lineage 2 例 / promote 4 例 / 并发防护 2 例 + test_specstd 446 全绿 + build 全绿 |
| K-016 | 草稿评审页「评审通过·入库」点击无反应：`routers/drafts.py._scenarios_root()` 解析为「工作区根/scenarios」，而 spec 工作区克隆没有 scenarios/（场景库在 SpecGuard 仓库根，scenario_store/DagEditor/plan_executor 均读 SG_ROOT/scenarios）→ `/drafts/modules` 返回空 → `targetModule=''` → handlePromote 首行 `!targetModule` 静默 return。附：AgentChat MarkdownText 表格 `<tr>` 内空白文本节点触发 React validateDOMNesting 警告 | 用户反馈（点击无反应 + 控制台警告） | 否（K-006 路径迁移时的工作区优先设计 + 前端静默返回 UX 遗漏 + MarkdownText 表格渲染空白） | 草稿无法入库（核心三道闸流程断点）；控制台噪音 | ✅ 已修复 | ①`_scenarios_root()`（routers/drafts.py + services/draft_promote.py 同步）改为「工作区 scenarios/ 存在则用，否则回退 SpecGuard 仓库 scenarios/」；②handlePromote 无模块时显式错误提示（不再静默）+ 模块下拉空态占位；③MarkdownText `<tr>` 内空白节点清除 | 用户反馈即修（2026-07-30）。已实施 + TestScenariosRootFallback 2 例 + test_specstd 448 全绿 + build 全绿 |
| K-017 | 用户决策：目录不存在应自动创建而非报错。`_guard_module`（draft_promote + routers/drafts）对不存在模块目录报 module_not_found/404 | 用户反馈「对于文件目录如果没有就应该新建 而不是给出报错」 | 否（D1 入库守卫的保守设计） | 新模块入库需手工建目录，打断流程 | ✅ 已修复 | ①两处 `_guard_module` 对不存在目录自动 `mkdir(parents=True)`（越界守卫保留）；②前端模块下拉加「＋ 新建模块…」选项 + 手动输入框；③测试适配：test_module_guard 隔离 scenarios_root（防真实仓库污染）+ TestPromote 钉住 `_scenarios_root`（K-016 回退在 spec 工作区夹具下会落到真实仓库根——测试产物曾写入真实 scenarios/ 造成冲突，已清理并固化隔离注释） | 用户决策即实施（2026-07-30）。test_specstd 449 全绿 + build 全绿 + 真实仓库零污染验证 |
| K-018 | 服务重启后「确认入库」一直没响应。会话导出取证：metrics 按 LLM 调用完成逐条追加，17:44:48 后零新增调用/零错误/零新消息——run 未启动或挂在首次 LLM 调用完成前。代码链坐实三个「静默无响应」洞：①前端 WS 断线无自动重连（wsReconnect 仅手动打断触发）且 handleSend 在非 OPEN 时静默 return 丢弃消息；②runtime 工具执行期间零事件（tool_call 在执行完后才发）——promote_draft×7 每份 release_check 子进程上限 180s，最坏 21 分钟死寂；③runtime 主循环 llm.chat 无异常兜底，异常炸出 run 当轮消息不落盘无痕迹 | 用户反馈（重启后重新入库没响应 + 会话导出文件） | 否（K-012 流式/K-015 并发防护均未覆盖的三处沉默路径） | 用户无法区分「执行中」与「已死亡」，核心入库流程被判死刑 | ✅ 已修复 | ①前端：onclose 自动重连（指数退避 1s→10s 上限 5 次）+ 断线解除 loading 卡死 + handleSend 非 OPEN 显式报错并触发重连（input 不清空可重发）+ handleStop 标记 _intentional 防重复调度；②后端 runtime：`_execute_tool` 前发射 tool_call_start 事件（前端状态行「⚙ 工具名」）；③runtime 主循环 llm.chat try/except → [ERROR] 落盘 + error 事件 + 优雅返回 | 用户反馈即修（2026-07-30）。test_agent +2 例（tool_call_start 事件序 / LLM 异常兜底落盘），test_specstd 451 全绿 + build 全绿 |
| K-019 | ①入库工具「成功报失败」：promote 的 return 语句 `target.relative_to(get_workspace_root())` 在 K-016 回退场景（工作区激活但无 scenarios/，target 落 SG_ROOT 侧）抛 ValueError「not in the subpath of」——且在 return 才炸，此时文件已移动+基线已重建+门禁已通过，实际入库成功却误报失败，Agent 据此放弃剩余 6 份（现场核实：scenarios/system-settings/tag-library/TL-DTL-001.yaml 已实际入库 + contracts_baseline.json 已更新）；②页面对话内容明显变少：runtime.run 直接压缩 messages 并全量落盘，会话文件被压缩态覆盖，前端（不显示 system 摘要消息）恢复后只剩摘要+最近几条 | 用户反馈（入库工具存在问题 + 页面内容明显少了 + 会话导出文件） | 否（K-016 回退设计与 G3-1 压缩设计的各自盲区：展示路径计算未考虑回退场景；压缩未区分 LLM 上下文与持久化历史） | 入库流程可信性崩塌（成功报失败→Agent 放弃）；会话历史不可逆丢失（展示层） | ✅ 已修复 | ①draft_promote：`_display_target()` 逐级回退（工作区根→SG_ROOT→绝对路径）不抛出，且在副作用前算好；②runtime 双清单：`llm_messages` 工作副本承载压缩，messages 保留完整历史用于持久化/展示/导出；熔断分支不再压缩（后续无 LLM 调用） | 用户反馈即修（2026-07-30）。test_agent +1（压缩后 LLM 收到压缩上下文但会话文件保留全 20 轮历史）、test_scenario_meta_pack +1（SG_ROOT 回退路径 promote 返回正常 target），test_specstd 453 全绿 + build 全绿。注：TL-DTL-001 已实际入库符合用户意图，剩余 6 份重发「继续入库」即可 |
| K-020 | 工具报错被系统性忽视/绕过，场景不再建立在真实 spec 基础上。会话导出（c15df657）取证三类：①validate 报 ANCHOR「FR-004 不存在」——但 FR-004 真实存在于 tag-library/spec.md，根因是 specstd 锚点解析只认 `### FR-xxx:` 标题格式，真实工作区用 `- **FR-004**：` 列表定义格式；Agent 核实 FR 存在后竟**删除 covers 字段绕过**（原话「参考 TL-DTL-001 不包含 covers 字段也可通过」）→ 30 份 TL-RC 草稿全部无 covers，FR 溯源链断裂；②covers 缺失零告警（validator 只在 covers 存在时校验）——Agent 由此「学会」不写 covers；③todo_write 报「无效的 status: completed」不列合法值，LLM 靠猜重试 | 用户反馈「对于执行工具报错，不能忽视。每次报错都可能关系到单元测试是否建立在真实的基础上」 | 否（specstd 解析格式盲区 + validator 缺失告警设计缺口 + Agent 行为约束缺失） | 契约驱动根基被掏空：covers 是场景↔Spec 强制锚点（覆盖分析/DAG 编排/delta 导入全依赖），批量无锚点场景 = 测试体系脱离真实 spec | ✅ 已修复 | ①specstd：schema.py 新增 FR_LIST_RE（行首列表项+加粗+冒号的定义格式，正文内联引用不算），anchors.parse_spec_md 双格式按位置合并识别（重复保留由 conformance 判重；列表定义行并入 AC 扫描），真实 tdm 工作区验证 FR-004 等 31 锚点全解析；②validator：covers 缺失 → WARN（不阻断但可见）+ ANCHOR 报错附「禁止删除 covers 绕过，误报须上报用户」指引；③todo_write 报错列合法值；④generate.md 新增「工具报错处理」节（禁止绕过式自愈/连续报错 2 次停止上报/covers 必填）+ system prompt 通用硬约束第 6 条 | 用户反馈即修（2026-07-30）。test_conformance +2（列表格式锚点/混排格式）、test_mcp_server +1（covers 缺失 WARN）、test_meta_tools 强化（合法值提示），test_specstd 456 + test_engine 62 + engine_modes 39 全绿 + release_check PASS。⚠️ specstd 规范层改动（解析兼容性扩展，schema.py 单一事实源语义未变）。遗留：30 份无 covers 草稿待补救（重新校验补 anchors 或评审时人工补） |
| K-021 | Agent 对话编排 DAG 测试场景能力包（用户决策：四点全做 + Agent 能力设定为能获取 SpecGuard 所有内容）。分析确认的四个缺口：①validate 不查 depends_on（T4/T5 只在工作台 spec_validator，悬空依赖到发布门禁才炸）；②无 DAG 预演工具（dependency_graph 未暴露）；③生成流程平铺式无拓扑设计步；④无执行验证闭环（agent 无 run 工具）；⑤read_spec 只能读工作区，SpecGuard 仓库侧内容（scenarios/docs/contracts/报告）不可达 | 用户决策「四点都需要优化，并且Agent能力设定应该是能获取到specguard所有内容」 | 否（MCP 工具层与工作台服务层的能力不对等 + 能力设定盲区） | Agent 无法完成「编排单元测试→构造整个 DAG 测试场景」的完整闭环 | ✅ 已修复 | ①read_spec 双根扩展：工作区优先 + SG_ROOT 回退 + sg:// 显式前缀；敏感拒读（.git/用户 DB/agent sessions/.env/node_modules）+ 二进制守卫 + 200KB 截断；②validate 补 T4（悬空依赖 ERROR + 版本期望仲裁复用 engine.versioning.match_expectation）/T5（孤例 WARN）/T7（未锁版本 WARN），_scenario_index 双源（场景库 + drafts 同批草稿合法依赖）；③check_dag 工具：DependencyGraph 包装（拓扑序/环/DRIFT/orphans/focus 闭包+dependents），草稿经 _parse_scenario 归一化并入（与入库后同语义），真实场景库验证 25 场景无环；④run_scenario 工具：复用 plan_executor._setup_runtime 装配，草稿重建图，返回闭包逐场景 verdict + 报告落盘工作区 .specguard/reports/；⑤generate.md 加第 1.5 步 DAG 拓扑设计（prep 划分/依赖边/变量契约/用户确认/check_dag 预演）+ 第 3.5 步执行验证；check_dag 挂 generate/debug/analyze，run_scenario 挂 generate/debug | 用户决策即实施（2026-07-30）。test_mcp_server +14（双根 6/T4T5T7 5/check_dag 4/run 参数守卫 1，工具数 16→18），test_specstd 472 + test_engine 62 + engine_modes 39 全绿 + release_check PASS |
| K-022 | Agent 声称「没有入库工具」（65 份草稿确认入库时）。根因两层：①promote_draft 是单文件工具且每次调用跑全量发布门禁（上限 180s/次）——65 份 = 65 次调用最坏 3 小时，单文件工具在批量场景下实际不可用；②promote 工具只挂 generate 模式白名单，chat 等模式下 Agent 不知道其存在（K-012 的未知工具自我纠正只在「调用被拒」后触发，Agent 未尝试就不知道） | 用户反馈（会话中原话「目前我手头的工具暂不支持一键将草稿 commit 到 scenarios/ 目录」） | 否（K-015 单文件设计与批量场景失配 + 模式白名单的可见性盲区） | 批量入库流程断点——Agent 明示无法完成核心任务 | ✅ 已修复 | ①draft_promote.promote_batch：逐份校验+冲突检查（不合格单份跳过附原因，不拖垮整批）→ 整批移动 → 一次基线重建 → 一次门禁（失败整批回滚）；filenames 省略 = drafts/ 全部；②draft_writer 新增 promote_drafts 工具（挂 generate 白名单）；③generate.md 第四步改写「多份必用批量」；④chat.md 能力边界明示「入库在 generate 模式（promote_draft/promote_drafts），switch_mode 后执行，不得声称没有入库工具」 | 用户反馈即修（2026-07-30）。TestPromoteBatch +5（基线一次重建/默认全量/部分跳过/门禁失败整批回滚/全部不合格不动文件），工具数 18→19，test_specstd 477 全绿 + release_check PASS |
| K-023 | 去模式化（用户决策：状态切换太多且工具可见性引发新问题，改为统一 prompt 条件指引 + 全量工具）。方案可行性分析结论：生产中所有模式相关事故均为门禁自伤（K-012 未知工具报错/K-018 resume 模式落错/K-022 没有入库工具），而真正写操作的护栏本来就在工具内部（drafts 沙箱/promote 三道闸+回滚/OVERWRITE_DENIED）；模式片段仅 ~4.5k 字符，合并成本低；统一静态 prompt 反而提升 cache 命中（switch_mode 改 prompt 必失效） | 用户决策「是否不需要状态切换……简化设计」+「开工」 | 否（M0-M5 薄 Harness 时期的过度设计，工具内护栏齐备后已冗余） | 模式切换 churn、工具不可见事故、路由猜错落错模式——整层复杂性归零 | ✅ 已实施 | ①统一 system prompt：模式片段合并为「任务行为指引」条件章节（modes/*.md 仍是单一事实源，热加载保留）+ format_spec 全量常驻 + skills 全量；②runtime 全量工具常驻（白名单/模式通知注入/_tools_dirty 机械全删），switch_mode 退化为无操作提示壳（平滑过渡旧会话习惯）；③routers/agent.py 删 mode_router 路由/事件/locked_mode；④前端删 ModeDropdown/mode_switch 卡片/lockedMode/斜杠 /mode 命令/DEFAULT_PLANS 分模式/TodoPanel 模式分组；⑤删 agent/mode_router.py + ModeDropdown.tsx；写操作防误用维持 prompt 约束+工具内护栏（先软后硬，误调出现再加 confirm 参数） | 用户决策即实施（2026-07-30）。测试适配：test_meta_tools 重写（TestSwitchModeDeprecated：无操作提示/全量工具/无 mode_switch 事件）、test_agent TestPromptOptimization 重写（统一 prompt 断言）、test_llm_stream 未知工具语义更新，删 test_mode_router.py；test_specstd 430 + test_engine 62 + engine_modes 39 全绿 + npm build 全绿 + release_check PASS。遗留观察项：头一两周盯会话导出，若 run_scenario/promote 出现误调再加确定性 confirm 护栏 |
| K-024 | 对话页工具调用可读性两痛点（用户反馈 + 会话导出取证：492 条消息中 100 轮带思考文本的工具调用）：①assistant 思考文本塞进 tools[0].assistantText 藏进默认折叠的工具组——工具跑完只剩一行「7/7 工具」，用户完全看不到为什么调用这个工具；②展开工具详情直接甩原始 JSON（参数带转义、结果大段文本），不友好 | 用户反馈「思考信息在工具调用完之后直接折叠了，影响用户理解为什么需要调用这个工具。并且点开工具调用详情之后直接展示的 json 不友好」 | 否（K-012 会话页简化设计时的折叠过度 + 调试视角的原始 JSON 直出） | Agent 行为不可理解（意图不可见）+ 详情不可读 | ✅ 已修复 | ①groupMessages：思考文本提升为独立 assistant-text 气泡（thought 标记轻量样式：左侧竖线+斜体小字，折叠状态也常驻可见；时序保证：上一工具组 flush → 思考 → 新工具组）；②ToolCallBlock 展开区重写：参数 JSON.parse 键值行（布尔/数字着色）+ validate 报告特渲（verdict PASS 绿/REJECT 红 + findings 分级列表）+ 数组计数摘要 + 长文本截断展开（TruncText），非 JSON 回退原文截断 | 用户反馈即修（2026-07-31）。npm build 全绿 |
| K-025 | 场景管理/DAG 编排/草稿评审页面加载慢。计时取证三层叠加：①每请求固定 ~0.2s 开销——连 404/公开端点都 0.21s，keep-alive 复用连接后仅 3ms：根因是 `localhost` 先解析 IPv6(::1) 而 uvicorn 只听 IPv4，每个新 TCP 连接付 ~170ms 回退税（vite proxy target=localhost 放大了它——页面所有 API 经代理全部中招）；②libyaml 已装但全代码用纯 Python yaml.safe_load（load_scenarios 90 文件 0.55s）；③零缓存——/api/scenarios、/dag、/drift、validator._scenario_index 每请求/每次 validate 全量重解析 90+ YAML（get_dag 甚至解析两遍） | 用户反馈「点击场景管理、DAG编排、草稿评审这些页面加载速度都很慢」 | 否（Windows 双栈环境陷阱 + 性能盲区累积） | 三个核心页面每次打开秒级等待 | ✅ 已修复 | ①vite proxy 三处 target + start-workbench 全部 URL 统一 127.0.0.1 + vite server 显式 host: '127.0.0.1'（消灭 IPv6 回退税；host 绑定修复紧随的启动异常——vite 默认 localhost 在 Node 17+ 只听 ::1，就绪探测走 IPv4 超时 60s）；②engine/scenario_loader + scenario_store 用 CSafeLoader（语义一致，0.55s→0.27s）；③scenario_store 目录指纹缓存（文件数+最新 mtime_ns，编辑/promote 自动失效，唯一真实扫描点收口；_engine_graph 随缓存复用消灭 get_dag 双解析）+ validator._scenario_index 主路径走缓存；④plans 无工作区 500→空列表。实测：/api/scenarios 0.63→0.28s、/dag 0.97→0.31s（缓存命中后 ~0.07s+0.2s 建连税→代理修复后同连接 3ms） | 用户反馈即修（2026-07-31）。缓存失效专项验证（增删文件 90→91→90 正确重扫）；test_specstd 430 + test_engine 62 全绿 + release_check PASS。注：用户需重启 start-workbench 使 vite 配置生效 |
| K-026 | 信息包 → 草稿 → 入库 → DAG/执行 工作流断链（用户反馈三断点）：①草稿评审页看不到草稿与信息包的关联（数据在 drafts/_meta.json 但页面只在 stale 时 tooltip 提及）；②promote 后 lineage 丢失——信息包无法反查哪些场景由它产出；③新入库场景 module=''（新目录无 _suite.yaml，module 取自套件元信息）→ DAG 编排按模块分组/筛选时 66 份新场景无归属「选不到」 | 用户反馈「草稿评审产出基础单元测试但是没有和信息包相关联……评审通过入库在DAG编排里面也选不到……信息包没有和后面的DAG测试执行串联起来」 | 否（K-013 关联数据落盘但展示层遗漏 + promote 流程无血缘设计 + K-017 自动建目录未补套件元信息） | 契约驱动闭环断裂：信息包作为关键产物无法串联单元测试与 DAG 执行 | ✅ 已修复 | ①Drafts.tsx：草稿卡片显示 📦 source_meta chip（关联可见化）；②scenario_meta.record_promotion/get_promotions（.specguard/info_packs/{sid}.promoted.json sidecar，重复入库更新而非追加）+ promote/promote_batch 成功后按 _meta.json 的 scenario_id 落血缘；③promote 自动生成 _suite.yaml（module 不再为空）；④list_info_pack_artifacts 返回 promoted_scenarios + summary.promoted_count（Agent 可直接回答「这个信息包产出了哪些场景」）；⑤存量补救：2 个新模块目录补建 _suite.yaml（66 份场景 module 全补齐）+ 血缘回填 55 条 | 用户反馈即修（2026-07-31）。TestPromote +3（suite 自动创建/血缘落盘+重复更新/无关联不崩），test_specstd 433 全绿 + build 全绿 + release_check PASS |

| K-027 | DAG 编排页无法定位场景 + 工具栏意义不明（用户截图反馈）：①IdQueryTool（PP/RC 前缀下拉 + 校验ID + 校验按钮）是创建场景用的 ID 分配工具，与 DAG 编排无关且无任何说明——「意义不明的三个下拉和一个校验」；②90 节点画布无搜索无模块分组，新入库场景找不到；③get_dag 节点无 module 字段（前端无法按模块分组） | 用户反馈「DAG编排时还是选择不到具体场景 按模块分组也看不到在哪操作。图片内容倒是多了意义不明的三个下拉和一个校验」 | 否（G2 DAG 页初版工具栏的历史遗留 + K-026 才补 module 数据链） | DAG 编排核心页不可用（找不到场景就无法编排依赖） | ✅ 已修复 | ①后端 get_dag 节点补 module 字段；②工具栏重构：删 IdQueryTool（创建场景归属 Scenarios 向导/Agent），新增模块分组下拉（选中模块场景+直接上下游，保持依赖边可见）+ 场景搜索框（id/标题模糊过滤）+ 节点计数（X/Y 节点）；③三重过滤（计划/模块/搜索）统一收口 filteredDag | 用户反馈即修（2026-07-31）。npm build 全绿 + test_specstd 433 全绿 |

| K-028 | Agent 无法编排已入库场景的 DAG（用户问「在agent对话时我该怎么让它编排指定场景的DAG」）：场景引用方式盘点（场景 ID 唯一可靠/@信息包可批量带出/DAG 无独立 ID——编排=编辑 depends_on），但 deps_editor 只在工作台后端，Agent 无编辑依赖边的工具——只能给新草稿声明 depends_on | 用户提问「用名字还是@引用还是每个场景对应的DAG编排有具体的ID」 | 否（deps_editor 未暴露 MCP 层的能力缺口） | Agent DAG 编排能力只覆盖新草稿，已入库场景只能手工画布连线 | ✅ 已修复 | ①scenario_tools 新增 edit_dependency 工具（scenario_id=下游/action/dep_id=上游/mode，deps_editor 文本外科手术保注释；自依赖/存在性/环校验守卫；版本期望自动推导 ^主版本；返回最新 depends_on）；②generate.md DAG 设计步补「已入库场景用 edit_dependency 编排」；③scenario_store._scan_scenarios 路径相对化容错（根重定向时相对场景库根——测试隔离发现） | 用户提问即实施（2026-07-31）。test_mcp_server +4（add/remove/环拒绝/三守卫，工具数 19→20），test_specstd 全绿 + release_check PASS |

| K-030 | 信息包文件查看与读取不支持办公文档（用户反馈「点击查看没有渲染md yaml 尤其是需要支持xlsx csv，docx，pdf」）：FileViewer 本支持 md/yaml/csv 渲染，但 read-file 端点对二进制直接 read_text → UnicodeDecodeError 500；@引用注入 errors="replace" 解码出乱码；read_spec/read_info_pack 对 xlsx 拒读/报错——信息包关键文件（标签库维护test-cases.xlsx，363 用例）全链路不可读 | 用户反馈 | 否（办公文档支持从未建设，库已装（openpyxl/docx/pypdf）但无转换层） | 信息包核心文件在预览/@引用/Agent 读取三链路全部不可用 | ✅ 已修复 | ①services/file_preview.py 转换器（零新增依赖）：xlsx→Markdown 表格（sheet 标题/竖线转义/空行跳过/200 行截断）、docx→段落+表格文本、pdf→分页文本（30 页上限），统一 60KB 字符软上限、解析失败返回明确文本不抛异常；②read-file 端点接转换器返回 format 字段 + FileViewer 按 format 渲染（xlsx→ReactMarkdown 表格）；③@引用注入/read_spec/read_info_pack 三处二进制统一走转换器（read_spec 其他二进制仍拒读） | 用户反馈即修（2026-07-31）。真实文件验证（363 用例 xlsx 转 Markdown 表格）；test_file_preview +6（xlsx 表格/截断/损坏不崩/docx/pdf/read_spec 转换），K-021 二进制守卫测试语义更新（xlsx→zip），test_specstd 443 全绿 + build 全绿 + release_check PASS |

| K-031 | 预览弹窗表格不渲染（用户截图反馈：xlsx 转换结果与原生 regression.md 的表格都显示为原始管道文本）。根因：react-markdown 默认不支持表格——表格是 GFM 扩展需 remark-gfm 插件（标题/加粗/blockquote 正常是 CommonMark 部分，表格不在其中） | 用户反馈「预览表格失败」 | 否（FileViewer 引入 react-markdown 时漏配 GFM 插件） | 所有含表格的 Markdown（spec.md §7 API 契约表、回归清单、xlsx 转换结果）预览不可读 | ✅ 已修复 | 新增前端依赖 remark-gfm（react-markdown 官方配套插件，Ask First 事项——用户需求直接要求表格渲染，属标准生态低风险补充）：FileViewer 两处 + Dashboard spec.md 查看器统一接入 | 用户反馈即修（2026-07-31）。npm build 全绿 |

| K-032 | Agent 对话页右侧 UX 重构（用户反馈四点）：①大文件预览无滑动框——FileViewer 各分支用 flex-1 但父级非 flex 容器，flex-1 失效高度撑破视口被裁切无滚动条；②参考截图改为页签式——文件各自在右侧单独页签打开（取代 modal 弹窗），首页给当前上下文待办，信息包单独页签；③服务重启后引用的信息包 chip 在但文件看不到——scenarioId 只从 URL searchParams 初始化，重启/刷新后为空，scenarioMeta 永不加载（引用 chip 来自消息 refs 持久化所以还在） | 用户反馈（截图参考 + 重启丢失） | 否（K-013 弹窗方案的滚动链缺陷 + 右侧面板信息架构未随内容增多演进 + K-012 恢复设计漏掉 scenarioId） | 大文件预览不可用/右侧信息层级混乱/重启后信息包断联 | ✅ 已修复 | ①SidePanel 重写为页签容器：📋待办（默认首页：引用+待办+上下文用量）/📦信息包（独立页签 defaultOpen）/📄文件各自页签（可关闭、去重激活、文件页签自动加宽 460px）；②FileViewer 全分支 flex-1→h-full 滚动链修复；③restoreSession 从消息 refs 提取最近 info_pack 恢复 scenarioId（autoSentRef 守卫防触发向导自动发送）+ handleNewSession 同步清理 scenarioId/scenarioMeta/fileTabs | 用户反馈即修（2026-07-31）。tsc + npm build 全绿 |

| K-033 | 右侧信息查看区域太窄不可调 + 信息包只能 git 拉取材料（用户反馈两点）：①右侧页签面板宽度写死（待办 288/文件 460），看 xlsx 等材料太窄；②信息包文件只能来自工作区 git 拉取，无法直接上传补充材料 | 用户反馈「右侧信息查看的时候需要允许扩大窗口……并且需要允许在信息包的部分上传其他材料」 | 否（K-032 页签化的宽度定值 + 信息包收集渠道单一设计缺口） | 大表格阅读体验差/信息包素材收集断点 | ✅ 已修复 | ①面板左缘拖拽柄（220~70% 视口，localStorage 持久化，文件页签自动至少 460）；②POST /api/scenarios/{id}/info-pack/upload（python-multipart 已装）：文件落盘 .specguard/uploads/（工作区内 safe_resolve 可读、git diff 已过滤不噪音、office 文档经 K-030 转换器可读），重名 -1/-2 去重不覆盖，路径穿越由 .name 剥离中性化，隐藏文件/空文件/超 20MB 拒绝；③InfoPackPanel「⬆ 上传」按钮 + api.uploadFile（FormData 专用通道） | 用户反馈即修（2026-07-31）。TestInfoPackUpload +3（落盘+sha 条目/同名去重不覆盖/非法名拒绝+穿越中性化），test_specstd 446 全绿 + build 全绿 + release_check PASS |

| K-034 | Agent 聊天框不支持上传附件（用户反馈「对话过程中还不允许在聊天框里面上传附件。如果上传了要允许自动创建信息包」）：K-033 只能在已有信息包页签里补传，对话流中丢一份新材料要先离开对话去建包，动线断裂 | 用户反馈 | 否（上传入口只做了信息包页签一侧，对话输入侧未建设） | 对话中补充材料动线断裂 | ✅ 已修复 | ①POST /api/scenarios/info-pack/auto-create（多文件一次成一个包：落盘 .specguard/uploads/ + create_meta + 条目化，默认名取首个文件名去扩展名，显式 name 优先；K-033 校验/落盘逻辑抽为 _sanitize_upload/_save_to_uploads 共用）；②AgentChat 输入框 📎 按钮（multiple file input，attaching 态）→ 上传成功自动加 info_pack chip（唯一替换语义，同 K-015），发送时才关联会话并在右侧打开信息包页签；③api.uploadFiles 多文件 FormData 通道（uploadFile 重构为其单文件特例） | 用户反馈即修（2026-07-31）。TestAutoCreateInfoPack +3（多文件成包+落盘+默认名/显式名/空文件+隐藏文件拒绝且不建 meta），test_specstd 452 全绿 + build 全绿 + release_check PASS |

| K-035 | 多 sheet xlsx 预览内容错乱（用户截图反馈：上传的 3-sheet 导出表每 sheet 只显示「1 行」且只有首列）。根因有二：①read_only=True 模式信任 sheet XML 声明的 dimension——非 Excel 生成的导出文件 dimension 写错（该文件实为 A1:L5 却声明 A1），iter_rows 只吐出 1 行 1 列（read_only 的 reset_dimensions 补救无效）；②导出表普遍用多级合并表头，非左上角单元格值为 None，不回填则表头/分组列大面积空白、行列错位 | 用户反馈「上传了多sheet的表格的时候显示出来的内容就乱了」 | 否（K-030 转换器按规整 Excel 文件假设实现，未覆盖坏 dimension + 合并表头两类真实导出文件形态） | 多 sheet/合并表头 xlsx（360 评价对比导出等真实材料）预览不可用 | ✅ 已修复 | file_preview._xlsx_to_markdown 重写：①改 read_only=False 普通模式（按真实单元格解析，免疫坏 dimension，且能拿 merged_cells）+ 30MB 文件大小硬上限防内存膨胀；②合并单元格回填（grid.setdefault 左上角值，纵向/横向/区域合并全覆盖）；③截断判定改用 ws.max_row（此前按已读行数，坏 dimension 下误判） | 用户反馈即修（2026-07-31）。真实问题文件验证（3 sheet × 12 列 × 合并表头全量正确渲染）；TestXlsxPreview +3（合并单元格回填行列对齐/多 sheet 全渲染/篡改 dimension A1:A1 仍读全表），test_specstd 452 全绿 + release_check PASS |

| K-036 | 办公文档预览保真升级 B 档（用户反馈「想要在office里面是什么格式 在预览的时候就是什么格式 还能支持表格操作」，经方案对比选定 B 档：结构保真+表格操作）。K-030 的文本转换链路先天丢格式（转 Markdown 那一刻格式就没了），保真必须改为前端直接解析原始文件；SheetJS 社区版不读单元格样式（颜色/字体属 C 档 Univer 不做） | 用户反馈 + 档位决策（B 档） | 否（预览架构是「后端转文本」，保真与表格操作从未建设） | xlsx 合并表头/列宽不可见、无法排序筛选；pdf/docx 只有纯文本体验 | ✅ 已修复 | ①后端 read-file 加 raw=true 参数返回 base64 原始字节（30MB 上限，safe_resolve 授权不变）；②SheetViewer.tsx（SheetJS 0.20.3 官方 CDN 版，避开 npm 停更的 0.18.5）：合并单元格 colspan/rowspan 还原（表头块保真）、数据区取消合并逐行填值（排序筛选不错位）、表头块自动探测（连续合并行，真实文件正确识别 3 行表头）、列宽/sheet 页签/冻结表头；操作：点表头排序（数字感知）、表头值列表筛选（搜索+勾选）、全局搜索、拖拽框选+复制 TSV、行数统计、1000 行渲染上限；③pdf 改 blob URL + iframe 原生查看器（缩放/翻页/搜索/打印）；④docx 改 mammoth 浏览器构建转 HTML（标题/表格/图片保留）；⑤xlsx/mammoth 独立 chunk 懒加载（主包不膨胀）；⑥Agent 读文件链路不变（file_preview 文本转换保留） | 用户反馈+档位决策（2026-07-31）。新增前端依赖 xlsx/mammoth（Ask First 事项——用户选档时已明示批准）；真实文件 node 侧验证解析逻辑（3 sheet/表头块 3 行/12 列）；TestReadSpecOfficeConversion +1（raw 字节级 roundtrip + raw=false 转换链路不变），test_specstd 453 全绿 + build 全绿（chunk 拆分生效）+ release_check PASS；GUI 实测（K-037 批次）：合并保真 colspan=5/rowspan=3、sheet 页签、排序标记 ↑、搜索「筛选后 1/2 行」全部生效 |

| K-037 | Agent 页四区布局无法按需收起（用户反馈「切换会话、浏览信息包记录、进行会话，都需要能够方便的收起展开菜单、会话列表，会话区，右侧信息包或者待办区。现在页面切换很不方便」）：全局菜单有 ☰ 抽屉，但会话列表（固定 w-60）与右侧页签面板（只能拖宽不能收没）常年占位，看对话/看表格时中间区被挤压 | 用户反馈 | 否（K-032/K-033 只做了页签化与拖宽，未做收起态） | 对话区与表格预览长期被两侧固定面板挤压 | ✅ 已修复 | ①会话列表可收起为 36px 细条（» 展开 + ＋新会话 + 竖排标题，顶栏 « 收起），sg_sess_collapsed 持久化；②右侧面板可收起为 36px 细条（« 展开 + 📋/📦/📄（带角标） 快捷图标直达对应页签，页签条右端 » 收起），sg_side_collapsed 持久化，收起时拖拽柄隐藏；③对话区顶栏加「« 会话 / 面板 »」双切换按钮（另一入口，提升可发现性）；④场景化自动展开：打开文件页签（openFileViewer）/发送带 info_pack chip 的消息时自动展开面板并激活对应页签——收起不妨碍工作流；⑤会话区始终 flex-1 自适应，两侧收起即释放全部宽度 | 用户反馈即修（2026-07-31）。GUI 实测全过：收起/展开/刷新持久化（双细条保留）/细条图标直达页签/拖拽柄随收起隐藏随展开恢复；连带实测 K-036 xlsx 保真（合并 colspan=5/rowspan=3、sheet 页签、排序 ↑、搜索计数）。npm build 全绿 |

| K-038 | React 18→19 + react-router 7→8 全量迁移。起因：用户启动时报「安装发生异常」——实为 npm audit 2 条高危（GHSA-qwww-vcr4-c8h2，react-router 7.12.0~8.2.0 RSC 模式 CSRF）。评估：官方公告明示仅影响 unstable RSC API，本仓库纯客户端 SPA（全项目只用 BrowserRouter/Routes/Route/NavLink/useLocation/useNavigate/useSearchParams 6 个 API）不可利用；但修复版 8.3.0 要求 react>=19.2.7（react-router-dom 包在 v8 已并入 react-router），用户知情后选择全量迁移 | 用户启动观感 + 漏洞评估 + 用户决策（B 全量迁移） | 否（依赖主版本债，非代码缺陷） | 每次 npm install 刷高危警告干扰判断；长期停留在旧主版本累积升级成本 | ✅ 已修复 | ①react/react-dom 18.3.1→19.2.8 + @types/react(-dom) 19.x；②react-router-dom@7.18.2 移除 → react-router@8.3.0（v8 包合并），4 文件 import 改写；③React 19 类型适配：全局 JSX 命名空间移除 → AgentChat/Dashboard 补 `import type { JSX }`；④npm audit 0 vulnerabilities | 2026-07-31。验证：tsc 严格模式 + vite build 全绿；audit 0 漏洞；模块图核查（react/react-dom/react-router 全链同批 chunk 99cdccc9 单 React 实例，排除双实例 hook 崩溃）；后端 API 独立验证正常；IAB 恢复后交互级回归通过（登录跳转/导航/渲染/点击全链路 React 19+RR8 正常）+ 用户真实浏览器验收成功。运维教训：npm 依赖变更后必须重启 vite（旧进程优化缓存 504 Outdated Optimize Dep → 白屏） |

| K-039 | 会话区与面板需一键占满屏幕（用户反馈「会话和面板 需要能一键占满屏幕」）：K-037 能分别收起两侧，但「只看对话」要点两下、「只看大表格」时面板再宽会话区也占位 | 用户反馈 | 否（K-037 只做了独立收起，未做一键最大化组合态） | 深读对话/大表格时布局切换繁琐 | ✅ 已修复 | ①专注模式（⤢ 专注，对话区顶栏）：一键同时收起两侧，会话区占满；再点「⤡ 退出专注」恢复进入前的两侧状态（preFocusRef 记忆，不写 localStorage——专注是临时态不污染持久偏好）；②面板最大化（SidePanel 页签条 ⤢）：面板吃掉会话区（width=100%），会话区 display:none 隐藏不卸载（WS/滚动位置/输入内容全保留），会话列表整列隐藏，拖拽柄隐藏；⤡ 还原/» 收起均正确退出最大化；③两模式互斥（进专注退最大化，进最大化退专注） | 用户反馈即修（2026-07-31）。GUI 实测全过：进专注（双细条+退出按钮出现）/退专注（原布局恢复）/面板最大化（会话区 isVisible=false、会话列表隐藏、页签横跨全宽）/还原（对话区+会话树+拖拽柄全恢复）。npm build 全绿 |

---

## 八、进度日志（完工追加，最新在上）

| 日期 | 任务 | 执行者 | 结果 |
|------|------|--------|------|
| 2026-07-29 | H-FE 前端模式体验 | S11 | ✅ 完成。①components/ModeBadge.tsx 新建模式徽章组件：当前模式图标+标签+锁定/自动标识；模式选择器（点击切换+锁定🔒，双击解锁）；解锁按钮；5 种模式图标映射。②components/TodoPanel.tsx 新建待办面板组件：双数据源（结构化待办 todo_update 事件优先，遗留计划项 <plan> 标签回退）；4 种状态图标（✅/🔄/⛔/○）+ 颜色；模式标签显示；当前模式 in_progress 项高亮；空状态提示。③AgentChat.tsx 集成：导入 ModeBadge + TodoPanel 组件（替除内联实现）；structuredTodos 状态存储结构化待办（todo_update 事件不再转字符串）；SidePanel 传递 structuredTodos/currentMode 给 TodoPanel；底部选择器栏用 ModeBadge 替换内联模式按钮；会话切换/新建时清理 structuredTodos。H-2/H-3/H-4 均已 ✅，真实事件流已就绪无需 mock。tsc 编译无错误；test_engine 62+test_specstd 389=451 全绿；release_check PASS。链 H 全部完成 |
| 2026-07-29 | I-3 前端 Schedules 页 | S11 | ✅ 完成。①api.ts 新增 schedulesApi（7 个方法：list/create/get/update/delete/run/listPlans）+ ScheduledJob 接口（12 字段）。②pages/Schedules.tsx 新建定时任务页面：任务列表表格（名称/计划/cron/状态/上次运行/操作）；新建/编辑表单（任务名称 + 计划下拉 + cron 预设 6 种 + 自定义 cron + 通知配置 ID + 启用开关）；操作按钮（立即运行▶️ / 启停⏸️ / 编辑✏️ / 删除🗑️）；模态对话框表单；状态标签（成功/失败/部分成功/错误）。③App.tsx 添加 Schedules import + 路由 /schedules + 菜单入口（执行组下「定时任务」tester+）。I-2 已 ✅ 无需降级。tsc 编译无错误；test_engine 62+test_specstd 389=451 全绿；release_check PASS。链 I 全部完成 |
| 2026-07-29 | I-2 scheduler 调度器 | S11 | ✅ 完成。①services/scheduler.py 新建 APScheduler 调度器：AsyncIOScheduler + SQLAlchemyJobStore（SQLite 持久化，重启不丢）；scheduled_jobs 表（12 字段：id/name/plan_id/workspace/cron/notify_config_id/enabled/created_by/created_at/last_run_at/last_run_status/last_run_id）；_execute_job 异步执行入口调 plan_executor.execute_plan（引擎直跑，复用 I-1）；start_scheduler/shutdown_scheduler 生命周期 + _restore_jobs 启动时恢复 enabled job；CRUD：create_job（验证 cron + 注册调度器）/ update_job（增量更新 + 同步调度器）/ delete_job（DB+调度器双删）/ trigger_job_now（手动触发一次）；工作区隔离（list_jobs 按 workspace 过滤）。②routers/schedules.py 新建 7 个端点：GET/POST/PUT/DELETE CRUD + POST /{id}/run 手动触发 + GET /plans/list 计划下拉；admin 门禁（创建/更新/删除），tester+ 门禁（触发）；resolve_workspace 工作区隔离。③main.py 注册路由 + startup 启动调度器 + shutdown 停止。④requirements.txt +apscheduler>=3.10 +sqlalchemy>=2.0（SQLAlchemyJobStore 依赖）。⑤test_scheduler.py 20 测试（建表幂等/CRUD 7 项/更新 6 项/cron 验证/工作区隔离/调度器生命周期/手动触发不存在 job）。test_engine 62+test_specstd 389=451 全绿；release_check PASS。I-3 可开工 |
| 2026-07-29 | J-3 前端通知配置页 | S10 | ✅ 完成。①api.ts 新增 NotifyConfig 接口（8 字段）+ notifyApi（5 方法：list/create/update/delete/test），对接 J-1/J-2 后端 /api/notify/configs CRUD + /test 测试发送。②pages/NotifyConfigs.tsx 新建通知配置页面：配置列表（名称/渠道标签/订阅事件/启用状态/@手机号）；新建/编辑模态表单（配置名称 + 渠道切换钉钉/飞书 + webhook URL + 加签密钥钉钉可选飞书禁用 + @手机号 + 订阅事件多选 3 种 + 启用开关）；操作按钮（测试发送 / 编辑 / 删除）；测试发送结果反馈（成功/失败消息）；编辑时 webhook_url/secret 留空不修改提示。③App.tsx 添加 NotifyConfigs import + 路由 /notify + 菜单入口（反哺分组下「通知配置」tester+）。J-2 已 ✅ 无需降级。tsc --noEmit 编译无错误；test_engine 62+test_specstd 389=451 全绿；release_check PASS。链 J 全部完成 |
| 2026-07-29 | F-1-3 文档同步 + 前端配置字段 | S10 | ✅ 完成。①AGENTS.md Repository Structure 更新：移除 drafts/plans/reports 顶层目录描述，改为「已迁移至各工作区 .specguard/ 目录」；测试计划引用更新为 .specguard/plans/；.gitignore 描述更新（各工作区 .specguard/ 有独立 .gitignore）；Never 区 reports 引用更新。②.gitignore 移除顶层 reports/ 和 drafts/（已迁移至各工作区 .specguard/，该目录有独立 .gitignore）。③WorkspaceSettings.tsx 新增「.specguard 目录位置」输入框（可选，默认 {工作区}/.specguard/），注册成功后清空。④routers/workspace.py RegisterLocalBody/RegisterGitBody 添加 specguard_path 字段，注册成功后如果 specguard_path 非空则调 specguard_dir(custom_path=...) 初始化目录（失败不阻塞注册）。test_engine 62+test_specstd 389=451 全绿；release_check PASS |
| 2026-07-29 | H-5 闭环衔接 | S10 | ✅ 完成。①feedback/ledger.py 添加 3 个 H-5 便捷方法：close_vulnerability(spq_id, note) 封装 transition→closed + 关闭事件 + note；close_vulnerabilities_by_location(location) 批量关闭同位置漏洞（幂等，跳过已 closed）；get_vulnerability_summary() 返回 {total/pending/in_progress/closed} 统计。②routers/workspace.py /pull 端点增强：返回 pulled_at（供 H-2 路由信号确认 + 前端展示）；新增 3 个漏洞管理 API：GET /vulnerabilities（列表+摘要）、POST /vulnerabilities/{spq_id}/close（关闭单个）、POST /vulnerabilities/close-by-location（批量关闭）。③闭环基础设施已就绪：H-1/S9 的 transition 状态机 + F-1-1/S6 的 pull() pulled_at 记录 + S11 的 _check_recent_pull 路由信号 + feedback/notify.py 已支持 detail_url/debug_url 渲染。④前端通知链接处理（AgentChat.tsx）归 S11，后端 API 已完整支持。test_h5_closure.py 13 测试全过（close_vulnerability 5 + close_by_location 4 + summary 3 + 闭环流程 1）。test_engine 62+test_specstd 389=451 全绿；release_check PASS。ledger.py 已释放 |
| 2026-07-29 | H-4 待办系统 + H-3 switch_mode 自主切换 | S10 | ✅ 完成。①mcp_server/tools/meta.py（新建）：todo_write + switch_mode 两个 meta 工具定义 + META_TOOL_NAMES 常量 + handle（MCP 独立模式返回提示）。②agent/runtime.py：导入 meta 模块 + META_TOOLS 常量；__init__ 添加 _todos/_pending_mode_notice/_tools_dirty/_session/_session_id 属性；工具过滤逻辑统一（set(mode_def.tools) | META_TOOLS，chat 模式 tools=[] 也有 meta 工具）；_rebuild_tool_map 排除 meta 工具；_execute_tool 拦截 todo_write/switch_mode；_handle_todo_write（校验+更新+emit+持久化）；_handle_switch_mode（校验+调用_switch_mode）；_switch_mode（重建工具集+_tools_dirty+注入通知+待办流转+emit mode_switch+emit todo_update）；run() 恢复待办+循环内检查 _tools_dirty/_pending_mode_notice+save 传 todos。③agent/session.py：save 添加 todos 参数（写入 todo_list 行，跳过旧 todo_list）；save_todos（追加即时持久化）；load_todos（取最后一行 todo_list）；load 跳过 todo_list 行；export_session 解析 todo_list。④agent/prompts/system.md.j2：追加模式自主切换+待办系统引导。⑤mcp_server/server.py：注册 meta 模块。⑥test_mcp_server.py：工具数 13→15+名称集合。⑦test_meta_tools.py（新建 37 测试）：TestTodoWrite(6)+TestTodoPersistence(7)+TestSwitchMode(9)+TestMetaToolsAllModes(7)+TestTodoAutoTransition(3)+TestIntegration(1)+TestMetaModule(4)。test_engine 62+test_specstd 356=418 全绿；release_check PASS。runtime.py/meta.py 已释放 |
| 2026-07-29 | H-2 模式自动路由 | S11 | ✅ 完成。①agent/mode_router.py 新建三层信号路由器：层 0 手动锁定（locked_mode 非空则不路由）> 层 1 工作台上下文（workspace_just_pulled→audit / execution+last_run_failed→debug / editing+never_run→generate / feedback+pending_vulns→audit）> 层 2 消息意图（4 组关键词零 LLM 调用：generate/debug/audit/analyze）> 层 3 默认 chat。RouteContext（8 字段）+ RouteResult（mode/source/reason）。②routers/agent.py 集成路由器：WS 端点连接级 _ws_current_mode 跟踪，首条消息初始化不发切换事件，后续消息模式变化时 emit mode_switch 事件（from/to/source/reason/auto）；REST /chat 端点同步集成，返回 mode/mode_source/mode_reason。辅助函数 _check_recent_pull（查 workspace pulled_at 5 分钟内）+ _count_pending_vulns（查 ledger pending 漏洞数）+ _build_route_context（组装前端+后端信号）。③AgentChat.tsx 前端集成：WS 消息携带 context 字段（current_page/editing_scenario_id/locked_mode）；mode_switch 事件处理（更新 currentMode + 模式切换卡片插入消息流）；todo_update 事件处理（H-FE 接续）；模式锁定（点击模式自动锁定🔒，双击或🔓解锁，斜杠命令也锁定）；audit 模式标签 + /mode:audit 命令。④test_mode_router.py 30 测试（4 类×多场景：手动锁定优先级/上下文信号 8 种/意图关键词 4 模式/默认兑底/层间优先级/RouteResult 结构/RouteContext 默认值/INTENT_KEYWORDS 完整性）。test_engine 62+test_specstd 356=418 全绿；release_check PASS。H-FE 可接续 AgentChat.tsx |
| 2026-07-29 | I-1 plan_executor 引擎直跑 + T-2/T-3 切换 | S8 | ✅ 完成。①engine/scenario_runner.py 新增 run_single（薄封装 run_with_deps，不改调度语义：shared 上游复用 / exclusive 懒重跑 / 上游失败→BLOCKED / 版本仲裁 DRIFT/ORPHANED/SKIP）。②workbench/backend/services/plan_executor.py 新建引擎直跑执行器：_setup_runtime 复刻 conftest.py 装配（env_config/DB/Registry/TokenProvider/DependencyGraph）；execute_plan 异步入口：加载 plan→拓扑排序→逐场景 asyncio.to_thread(run_single)→失败立即 _notify_failure（复用 J-2 send_notification + J-1 get_configs_by_event，仅 import+call 不修改 feedback/notify.py）→teardown LIFO→report_writer.dump_json+render_md 落盘 {workspace}/.specguard/reports/{timestamp}/；_notify_success 全绿时通知。F-1-1/J-2 均已 ✅ 直接使用真实路径函数+真实通知，T-2/T-3 对 I-1 为 no-op。验收：失败场景下游 BLOCKED（run_with_deps 内部处理）；报告复用 report_writer（JSON+MD 格式对齐）。test_engine 62+test_specstd 289=351 全绿；release_check PASS。I-2 可开工 |
| 2026-07-29 | H-1 audit 模式 + 审计工具 | S9 | ✅ 完成。①agent/modes/audit.md（第 5 模式，7 个工具白名单：read_spec/list_spec_files/query_registry/read_scenario/read_run_report/write_audit_report/report_vulnerability，4 类漏洞 V1-V4 对应 vtype 枚举，3 级严重度 blocker/major/minor）②mcp_server/tools/audit.py（write_audit_report：报告落 .specguard/audit/{timestamp}_{title}.md，依赖 F-1-1 specguard_dir()；report_vulnerability：写 feedback/ledger.py 台账 pending + 调 J-2 send_batch_notifications 通知，best-effort 失败不阻塞）③feedback/ledger.py 扩展 create_vulnerability（vtype/severity/location/evidence/suggestion/summary 6 字段）+ list_vulnerabilities + count_vulnerabilities（供 H-2 路由器查 pending 漏洞数）④mcp_server/server.py + agent/runtime.py TOOL_MODULES 注册 audit。F-1-1/J-2 均已 ✅，直接使用真实路径函数+真实通知，T-2/T-3 对 H-1 部分实质为 no-op。K-005（test_mcp_server.py 断言 11→13）由 F-1-2/S7 顺手修复。test_audit.py 25 测试全过（模式加载/工具白名单/ledger CRUD/漏洞字段完整性/状态机/write_audit_report 落盘/report_vulnerability 台账写入+通知不阻塞）。test_engine 62+test_specstd 289=351 全绿；release_check PASS。runtime.py 已释放给 H-4/H-3，H-5 前置 H-1 已满足 |
| 2026-07-29 | F-1-2 补充修复：drafts.py + attribution.py 路径迁移（K-006） | S7 | ✅ 完成。drafts.py DRAFTS_ROOT/SCENARIOS_ROOT/TRASH_DIR 三个模块级常量改为 `_drafts_root()`/`_scenarios_root()`/`_trash_dir()` 函数（无工作区回退旧路径）；`relative_to(SG_ROOT)` 改用 `get_workspace_root() or SG_ROOT`。attribution.py REPORTS_ROOT 改为 `_get_reports_root()` 函数。test_acceptance_fixes.py 2 处 mock 从 `monkeypatch.setattr(dr, "DRAFTS_ROOT", ...)` 改为 `monkeypatch.setattr(dr, "_drafts_root", lambda: ...)`。test_engine 62+test_specstd 351=413 全绿；release_check PASS |
| 2026-07-29 | F-1-2 工具层路径迁移 | S7 | ✅ 完成。5 文件路径迁移：①conftest.py REPORTS_ROOT 支持 `SG_REPORTS_ROOT` 环境变量覆盖（K-003 方案A，用户确认将 conftest.py 纳入范围）②draft_writer.py 草稿路径改用 `drafts_dir()`（模块级常量→动态函数 `_drafts_root()`，无工作区时 RuntimeError 友好返回；`_rel_path()` 辅助相对工作区根展示路径）③plan_store.py 计划/报告路径改用 `_plans_root()`/`_reports_root()`（删 PLANS_ROOT/SCENARIOS_ROOT/REPORTS_ROOT 常量，`relative_to(SG_ROOT)` 改用 `get_workspace_root()`）④runner.py 报告路径改用 `_get_reports_root()`（无工作区回退旧路径）+ 传 `SG_REPORTS_ROOT` 环境变量给 pytest 子进程（trigger + _run_batches 两处）⑤scenario_meta.py info_pack 改用文件存储 `info_packs_dir()/{sid}.yaml`（`get_meta` 优先文件回退 DB，`update_info_pack` 双写 DB+文件）。test_mcp_server.py 修复 5 测试（K-004 TestDraftWriter 3 个加 workspace fixture + 清理路径改 `drafts_dir()`；K-005 TestToolRegistration 2 个断言 11→13 + 名称集合加 audit 工具，H-1/S9 引入顺手修）。test_engine 62+test_specstd 326=388 全绿；release_check PASS。F-1-3 可开工 |
| 2026-07-29 | A-1 Mode temperature 清理 | S3 | ✅ 完成（K-002 用户已确认）。删除 4 个 modes/*.md 的 temperature 字段；mode_loader.py ModeDef 移除 temperature + _parse_mode_file 不再解析（向后兼容）；routers/agent.py /modes API 移除 temperature（K-002）；frontend api.ts AgentMode 移除 temperature（K-002）。test_mode_loader.py 15 测试全过；test_engine 62+test_specstd 206=268 全绿；release_check PASS。链 A 全部完成 |
| 2026-07-29 | F-1-1 `.specguard/` 路径函数 | S6 | ✅ 完成。specstd/workspace.py 新增 specguard_dir（可配置位置 + 路径穿越防护）+ drafts_dir/plans_dir/reports_dir/info_packs_dir 5 个冻结接口函数 + _ensure_specguard_meta（幂等生成 README/.gitignore）+ _is_safe_custom_path（拒 ../.. 路径穿越）。test_specguard_dir.py 18 测试全过（默认路径创建/README+gitignore 生成/幂等/显式 workspace_root/无工作区 raise/自定义路径/路径穿越拒绝/子目录/多工作区隔离/context var 隔离）。test_engine 62+test_specstd 264=326 全绿；release_check PASS。§6 旧路径→.specguard/ 切换点标记可切换，F-1-2 可开工 |
| 2026-07-29 | J-2 钉钉/飞书 webhook | S5 | ✅ 完成。feedback/notify.py 新增 send_notification（async，钉钉 markdown+加签/飞书卡片）+ _render_markdown/_render_feishu_card（3 类事件渲染）+ send_batch_notifications（>3 漏洞合并）+ validate_webhook_url 扩展钉钉域名；routers/notify.py test_send 接入真实 send_notification。test_notify_webhook.py 22 测试全过（渲染/失败静默/加签/批量合并/SSRF）。test_engine 62+test_specstd 246=308 全绿；release_check PASS。§6 notify_log 切换点标记可切换 |
| 2026-07-29 | T-1 J-1 接入真实 crypto | S4 | ✅ 完成（no-op）。J-1 实施时 A-3 已 ✅，直接使用真实 crypto，未用降级透传。无存量明文 webhook 需迁移。§6 crypto 切换点标记已切换 |
| 2026-07-29 | J-1 通知配置 CRUD | S4 | ✅ 完成。notify_config.py（CRUD + crypto 加密 webhook_url/secret + get_configs_by_event 事件过滤）；notify.py（5 个 API 端点：list/create/update/delete/test_send，test_send 为 J-2 预留 stub）；main.py 注册路由。test_notify_config.py 18 测试全过（CRUD/事件订阅/加密存储/校验）。test_engine 62+test_specstd 224=286 全绿；release_check PASS。J-1 直接使用真实 crypto（A-3 已 ✅），T-1 实质完成 |
| 2026-07-29 | 修正：文件占用按任务 ID + 会话标识规则 | S1 | 应用户指出「本会话」缺陷：4 个并行会话（A-3/A-2/A-1/J-1）都自称"本会话"无法区分。§5 删「占用者」列改按任务 ID 判定；§1.1 加会话标识规则（禁「本会话」）；历史标识分配：A-3→S1、A-2→S2、A-1→S3、J-1→S4。注：K-002（A-1/S3 上报）仍待用户确认 |
| 2026-07-29 | A-1 Mode temperature 清理 | S3 | 实现完成，待 K-002 用户确认后标记 ✅。删除 4 个 modes/*.md 的 temperature 字段；mode_loader.py ModeDef 移除 temperature + _parse_mode_file 不再解析（向后兼容）；routers/agent.py /modes API 移除 temperature（K-002）；frontend api.ts AgentMode 移除 temperature（K-002）。test_mode_loader.py 15 测试全过；test_engine 62+test_specstd 206=268 全绿；release_check PASS |
| 2026-07-29 | A-2 Token 级 compaction | S2 | ✅ 完成。compactor.py 新增 estimate_tokens（中英文分开）/estimate_message_tokens/_calc_keep_count；should_compact 修复 or→and bug + 加 max_context_tokens 参数（0 回退消息数阈值）；compact 动态 KEEP_RECENT（按 token 预算 25%）；runtime.py 2 处调用传入 llm.max_context_tokens。test_compactor.py 34 测试全过；test_agent.py MockLLM 补 max_context_tokens=0。test_engine 62+test_specstd 191=253 全绿；release_check PASS。runtime.py 已释放给 H-4/H-3 |
| 2026-07-29 | 机制增补：问题及时上报原则 + 已知问题登记区 | S1 | 应用户要求：§1.0 加「先确认后行动」最高原则（含上报场景/格式/禁止项），§7 新增已知问题登记（含 K-001 反面示例），§1.3 完工流程加「问题已确认」检查（无 🟡 待确认项才可标记完成） |
| 2026-07-29 | A-3 API Key 加密存储 | S1 | ✅ 完成。crypto.py + model_config 加密 + 迁移脚本 + 13 测试全过；test_specstd 157/test_engine 62/release_check 全绿。另顺手修复 test_agent.py 3 个预先存在的环境污染失败（未隔离 DB，git stash 验证与 A-3 无关）。T-1 标记可切换 |
| 2026-07-29 | 任务总控文件建立 + 接口冻结 | — | ✅ 初始状态，全部 ⬜ |

---

## 附：推荐并行分配（3 人 2 周）

| 人员 | 第 1 周 | 第 2 周 |
|------|--------|--------|
| 人 1 | A-3 → A-2 → A-1 → J-1 → J-2 | T-1 → 端到端联调 |
| 人 2 | F-1-1 → F-1-2 → F-1-3 → H-1 | H-5 → H-2 → 联调 |
| 人 3 | I-1 → I-2 | H-4 → H-3 → H-FE / I-3 / J-3 前端收尾 |

（2 人：人1 走 A→J→I；人2 走 F-1→H 全链→前端。1 人：按 A-3→J→A→F-1→I→H 串行约 4 周。）

---

_本文件是唯一进度权威。任何会话发现实际进度与本文件不符，以代码仓库实际状态为准并立即修正本文件。_
