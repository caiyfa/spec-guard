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
| F-1-2 | 工具层路径迁移 | F-1 | P0 | ⬜ | ⛔ F-1-1 | — | 1.5 天 |
| F-1-3 | 文档同步 + 前端配置字段 | F-1 | P0 | ⬜ | ⛔ F-1-2 | — | 1 天 |
| J-1 | 通知配置 CRUD（含加密存储） | J | P0 | ✅ | 🟡 A-3（降级：透传 crypto） | S4 | 1.5 天（实际 0.5 天） |
| J-2 | 钉钉/飞书 webhook 实现 | J | P0 | ✅ | ⛔ J-1 | S5 | 1.5 天（实际 0.5 天） |
| J-3 | 前端通知配置页 + 测试发送 | J | P0 | ⬜ | 🟡 J-2（降级：mock API） | — | 1 天 |
| I-1 | plan_executor 引擎直跑执行器 | I | P0 | ⬜ | 🟡 F-1-1（降级：旧路径） | — | 2.5 天 |
| I-2 | scheduler 调度器 + job CRUD API | I | P0 | ⬜ | ⛔ I-1 | — | 1.5 天 |
| I-3 | 前端 Schedules 页 | I | P0 | ⬜ | 🟡 I-2（降级：mock API） | — | 1 天 |
| H-1 | audit 模式 + 审计工具 + ledger 扩展 | H | P0 | ⬜ | 🟡 F-1-1 + 🟡 J-2 | — | 3 天 |
| H-4 | 待办系统（todo_write + 持久化） | H | P0 | ⬜ | ⛔ 文件：runtime.py（A-2 后） | — | 2 天 |
| H-3 | switch_mode 自主切换 | H | P0 | ⬜ | ⛔ H-4（共享 meta.py/runtime.py） | — | 2 天 |
| H-2 | 模式自动路由 | H | P0 | ⬜ | 无（独立文件） | — | 2 天 |
| H-5 | 闭环衔接（拉取信号 + 通知链接） | H | P0 | ⬜ | ⛔ H-1 + ⛔ J-2 | — | 1.5 天 |
| H-FE | 前端：待办面板 + 模式徽章 + 切换卡片 | H | P0 | ⬜ | 🟡 接口 4（降级：mock 事件） | — | 3 天 |
| T-1 | 切换：J-1 接入真实 crypto | 切换 | P0 | ✅ | ⛔ A-3 + ⛔ J-1 | S4 | 0.5 天（实际 0 天） |
| T-2 | 切换：H-1/I-1 接入真实落盘路径 | 切换 | P0 | ⬜ | ⛔ F-1-1 + ⛔ H-1/I-1 | — | 0.5 天 |
| T-3 | 切换：H-1/I-1 接通真实通知 | 切换 | P0 | ⬜ | ⛔ J-2 + ⛔ H-1/I-1 | — | 0.5 天 |
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

#### F-1-2 工具层路径迁移 ⬜
- **目标**：draft_writer/plan_store/runner/scenario_meta 改用新路径函数
- **开工门禁**：⛔ F-1-1 = ✅
- **涉及文件**：`mcp_server/tools/draft_writer.py`、`services/plan_store.py`、`services/runner.py`、`services/scenario_meta.py`
- **验收**：草稿/计划/报告/info_pack 全落 `{workspace}/.specguard/`；SG_ROOT 不再产生

#### F-1-3 文档同步 + 前端 ⬜
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

#### J-3 前端通知配置页 ⬜
- **目标**：配置列表 + 新建表单 + 「发送测试消息」
- **开工门禁**：🟡 J-2（降级：mock API）
- **涉及文件**：`pages/NotifyConfigs.tsx`(新)

### 链 I：定时任务调度（详细：[09-任务链I](./09-任务链I-定时任务调度.md)）

#### I-1 plan_executor 引擎直跑 ⬜
- **目标**：加载 plan → DAG 拓扑 → 逐场景执行 → 失败标记下游 skipped + 立即通知 + 报告落盘
- **开工门禁**：🟡 F-1-1（降级：报告先落 SG_ROOT/reports）+ 🟡 J-2（降级：通知走 T-3 前记 notify_log）
- **涉及文件**：`services/plan_executor.py`(新)、`engine/scenario_runner.py`(暴露 run_single)
- **验收**：失败场景下游 skipped；报告格式复用 report_writer
- **注意**：执行走**引擎直跑**（用户已确认），不经 pytest

#### I-2 scheduler 调度器 ⬜
- **目标**：APScheduler（SQLite jobstore）+ scheduled_jobs 表 + CRUD API + 手动触发 + 启停钩子
- **开工门禁**：⛔ I-1 = ✅。**新依赖 `apscheduler>=3.10` 已获用户批准**
- **涉及文件**：`services/scheduler.py`(新)、`routers/schedules.py`(新)、`main.py`(startup/shutdown)、`requirements.txt`
- **验收**：到点自动执行；重启不丢；暂停/启用生效；workers=1 单进程

#### I-3 前端 Schedules 页 ⬜
- **目标**：任务列表 + 新建表单（plan 下拉 + cron 预设 + 通知配置下拉）+ 立即运行
- **开工门禁**：🟡 I-2（降级：mock API）
- **涉及文件**：`pages/Schedules.tsx`(新)

### 链 H：闭环编排（详细：[08-任务链H](./08-任务链H-闭环编排与模式自动路由.md)）

#### H-1 audit 模式 + 审计工具 ⬜
- **目标**：`modes/audit.md`（第 5 模式，4 类漏洞）+ `tools/audit.py`（write_audit_report + report_vulnerability）+ ledger 漏洞条目结构
- **开工门禁**：🟡 F-1-1（降级：报告落旧路径）+ 🟡 J-2（降级：漏洞只落台账不通知）
- **涉及文件**：`agent/modes/audit.md`(新)、`mcp_server/tools/audit.py`(新)、`feedback/ledger.py`、`mcp_server/server.py`、`agent/runtime.py`(TOOL_MODULES 注册)
- **验收**：audit 模式工具白名单正确；构造缺陷 spec 能发现 V1 漏洞；台账 pending 落账

#### H-4 待办系统 ⬜
- **目标**：`todo_write` 工具 + runtime 待办状态 + session JSONL 持久化（`_type=todo_list`）+ `todo_update` 事件
- **开工门禁**：⛔ **文件门禁——A-2 已合入 runtime.py**
- **涉及文件**：`mcp_server/tools/meta.py`(新)、`agent/runtime.py`、`agent/session.py`
- **验收**：todo_write 后事件 emit；会话恢复待办还原
- **注意**：与 H-3 同文件，**必须同一人/同会话连续做**

#### H-3 switch_mode 自主切换 ⬜
- **目标**：`switch_mode` meta 工具 + mid-run 切换（注入新 system 消息，不改首条）+ 工具白名单重建 + 切换驱动待办状态流转
- **开工门禁**：⛔ H-4 = ✅（共享 meta.py/runtime.py）
- **涉及文件**：`mcp_server/tools/meta.py`、`agent/runtime.py`、`agent/prompts/system.md.j2`
- **验收**：Agent 草稿后自主切 audit；首条 system 不变；切换后白名单立即变

#### H-2 模式自动路由 ⬜
- **目标**：`mode_router.py`（三层信号：锁定 > 上下文 > 意图 > chat）+ WS 端点集成 + 前端 context 携带
- **开工门禁**：无（独立文件，可与 H-1 并行）
- **涉及文件**：`agent/mode_router.py`(新)、`routers/agent.py`、前端 AgentChat（context 字段）
- **验收**：失败运行→自动 debug；重新拉取→自动 audit；锁定后不自动切；切换带 reason

#### H-5 闭环衔接 ⬜
- **目标**：「重新拉取」记录时间戳（路由信号）+ 通知「打开调试」链接带 context + 漏洞 closed 状态机
- **开工门禁**：⛔ H-1 = ✅ + ⛔ J-2 = ✅
- **涉及文件**：`routers/workspace.py`、`feedback/ledger.py`、前端通知链接处理

#### H-FE 前端模式体验 ⬜
- **目标**：待办面板（TodoPanel）+ 模式徽章（ModeBadge 含锁定）+ 消息流切换卡片
- **开工门禁**：🟡 接口 4 已冻结（降级：mock 事件流开发）
- **涉及文件**：`components/TodoPanel.tsx`(新)、`components/ModeBadge.tsx`(新)、`pages/AgentChat.tsx`
- **验收**：三处体现正常；锁定可操作；与后端联调通过

### 切换任务（T 系列）

#### T-1 J-1 接入真实 crypto ✅（S4，2026-07-29 完成）
- **开工门禁**：⛔ A-3 = ✅ + ⛔ J-1 = ✅
- **动作**：J-1 的透传 crypto 替换为真实 encrypt/decrypt + 存量明文 webhook 迁移
- **结果**：J-1 实施时 A-3 已 ✅，直接使用真实 crypto.encrypt/decrypt，未使用降级透传。无存量明文 webhook 需迁移（新建表）。T-1 实质为 no-op

#### T-2 H-1/I-1 接入真实落盘路径 ⬜
- **开工门禁**：⛔ F-1-1 = ✅ + ⛔ H-1/I-1 = ✅
- **动作**：降级旧路径替换为 specguard_dir()，验证报告/草稿落 `.specguard/`

#### T-3 H-1/I-1 接通真实通知 ⬜
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
| `agent/runtime.py` | — | 空闲（A-2 已合入，可归 H-4/H-3） |
| `agent/compactor.py` | — | 空闲 |
| `mcp_server/tools/meta.py` | — | 空闲 |
| `feedback/ledger.py` | — | 空闲 |
| `workbench/backend/routers/agent.py` | — | 空闲 |
| `workbench/frontend/src/pages/AgentChat.tsx` | — | 空闲 |
| `specstd/workspace.py` | — | 空闲（F-1-1 已完成，可归 F-1-2） |

> 规则：占用归属按**任务 ID** 判定（跨会话唯一），具体哪个会话在做看 §3 执行者列。
> 占用中的文件，其他任务不得改。`runtime.py` 特别规则：**A-2 必须先合入，之后归 H-4/H-3 独占**。

---

## 六、降级→真实切换点登记

| 切换点 | 前置方 | 消费方 | 前置状态 | 切换任务 |
|--------|--------|--------|---------|---------|
| crypto 透传 → 真实加密 | A-3 | J-1 | ✅ 已切换（T-1 完成） | T-1 ✅ |
| 旧路径 → .specguard/ | F-1-1 | H-1 / I-1 | ✅ 可切换 | T-2 |
| notify_log → 真实通知 | J-2 | H-1 / I-1 | ✅ 可切换 | T-3 |

> 前置方完工时把「前置状态」改为 ✅ 可切换；切换任务领走后改对应 T 状态。

---

## 七、已知问题登记（开发中发现的计划外问题）

> 按 §1.0 原则：**发现即上报用户，确认后登记于此**。
> 状态：🟡 待确认 / 🔵 已确认待修 / 🔄 修复中 / ✅ 已修复 / ⏸️ 挂起（用户决定不修或延后）。

| 编号 | 问题 | 发现任务 | 是否本任务引入 | 影响 | 状态 | 处理决策 | 确认记录 |
|------|------|---------|--------------|------|------|---------|---------|
| K-001 | `TestLLMClient` 4 个测试未隔离真实 DB，`LLMClient` 读真实 workbench.db 的 model_config 导致 mock 测试失败 | A-3 | 否（git stash 验证） | 挡全局门禁（test_specstd 全绿） | ✅ 已修复 | 加 DB 隔离 fixture（`test_agent.py`） | ⚠️ **反面示例**：执行者未先上报确认就擅自修复，违反 §1.0。本条目为机制建立契机，此后必须先确认后行动 |
| K-002 | 移除 `ModeDef.temperature` 后 `routers/agent.py:201` 和 `frontend/api.ts:369` 引用该字段会 AttributeError / 类型不一致 | A-1 | 是（移除字段的直接后果） | 不修则 `/modes` API 500 + 挡全局门禁 | ✅ 已确认 | 纳入 A-1 范围（删 1 行/文件），已实施并提交（commit a2c1fe2） | 用户确认同意，A-1 标记 ✅ |

---

## 八、进度日志（完工追加，最新在上）

| 日期 | 任务 | 执行者 | 结果 |
|------|------|--------|------|
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
