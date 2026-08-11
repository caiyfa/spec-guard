# 飞书 CLI 集成设计 · T-701/T-702/T-703

> 版本：v1.0 · 2026-08-11 ｜ 状态：设计已确认，待实施
> 关联：总控文档 §4.6（飞书 CLI 集成）、§2.3（S2 背景知识块：topic.yaml 7 种 source 含 feishu_doc/feishu_base/feishu_minutes/feishu_im）
> 依赖：T-602（TOOL_MODULES 单一注册面）✅

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent / LLM                                     │
│  工具调用: lark_auth_* / lark_execute / feishu_* (已有)           │
└──────────┬──────────────────────────────┬──────────────────────────┘
           │  MCP (stdio)                │  REST (HTTP)
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  lark_auth.py        │    │  lark_binding.py         │
│  lark_run.py         │    │  (workbench backend)     │
│  (mcp_server/tools/) │    │  /api/settings/lark/*    │
└──────────┬───────────┘    └──────────┬───────────────┘
           │                           │
           │   共用底层函数              │
           ▼                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  lark_auth._do_login() / _do_status() / _do_logout()            │
│        └─ subprocess: USERPROFILE → {SG_ROOT}/.lark-cli/{emp}/ │
│        └─ per-user lock dict (threading.Lock)                   │
└──────────────────────────────────────────────────────────────────┘
```

### 核心原则

- **不存共享凭据**：每用户独立 app_id/app_secret，存放在各自 USERPROFILE 隔离目录
- **凭据不落日志**：审计脱敏复用 audit_store 的 JSON/query 双形态守护
- **飞书 CLI 路径从环境变量注入**：不硬编码路径
- **server 进程不存用户 token**：仅在服务调用时由用户上下文决定，通过 USERPROFILE 隔离目录实现

---

## 2. T-701：多用户飞书认证服务

### 2.1 MCP 工具

| 工具名 | 用途 | 输出 |
|--------|------|------|
| `lark_auth_status` | 查询当前用户飞书绑定状态 | `{bound: bool, identity: user|bot, identity_name: str, scopes: str[], open_id: str, config_dir: str}` |
| `lark_auth_login` | 两阶段飞书授权 | Phase1: `{phase: "waiting", verification_url: str, device_code: str, qr_image?: str}`; Phase2 (轮询完成后自动执行): `{phase: "completed", identity: user, open_id: str}` |
| `lark_auth_logout` | 解绑（清空隔离目录登录态） | `{ok: bool}` |

### 2.2 用户配置目录隔离

```
{SG_ROOT}/.lark-cli/{emp_no}/    # 每用户隔离目录
  └── config.json                 # lark-cli runtime (自动维护)
  └── token.json                  # 登录态 (自动维护)
```

- 子进程执行前设 `USERPROFILE`（Win）/ `HOME`（Linux）= `{SG_ROOT}/.lark-cli/{emp_no}/`
- 目录由 MCP 工具第一次调用时自动创建（`os.makedirs(exist_ok=True)`）
- `.gitignore` 补充 `.lark-cli/` 行

### 2.3 并发锁

```python
_USER_LOCKS: dict[str, threading.Lock] = {}  # emp_no → Lock
def _user_lock(emp_no: str) -> threading.Lock:
    with _LOCK_CREATE:
        if emp_no not in _USER_LOCKS:
            _USER_LOCKS[emp_no] = threading.Lock()
    return _USER_LOCKS[emp_no]
```

- 每用户一把锁，`lark_auth_login` 独占加锁（防 token 刷新互踩）
- 读操作（`lark_auth_status`）不需要锁

### 2.4 后端 REST 端点（供 T-703 消费）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/settings/lark/status` | 当前用户绑定状态 |
| POST | `/api/settings/lark/login` | 发起授权 |
| POST | `/api/settings/lark/logout` | 解绑 |
| GET | `/api/settings/lark/scopes` | 已授权 scope 清单 |

### 2.5 代码结构

```
mcp_server/tools/lark_auth.py
├── 底层函数
│   ├── _lark_command() → list[str]        # lark-cli 可执行命令前缀
│   ├── _user_lark_dir(emp_no) → Path       # 用户隔离目录路径
│   ├── _inject_userprof(emp_no) → dict     # USERPROFILE 覆盖环境变量
│   ├── _run_lark(emp_no, args, timeout)    # 通用子进程执行
│   ├── _user_lock(emp_no) → Lock           # 每用户并发锁
│   ├── _do_status(emp_no) → dict           # 底层状态查询
│   ├── _do_login(emp_no, scope?) → dict    # 底层登录（MCP + REST 共用）
│   └── _do_logout(emp_no) → dict           # 底层登出
├── MCP 工具定义
│   ├── TOOLS = [lark_auth_status, lark_auth_login, lark_auth_logout]
│   └── async handle(name, arguments)
└── 注册点
    └── 导入即注册（通过 server.py TOOL_MODULES）
```

---

## 3. T-702：通用执行器

### 3.1 MCP 工具

| 工具名 | 用途 | 入参 |
|--------|------|------|
| `lark_execute` | 透传 lark-cli 命令 | `{command: str, args: str[], timeout?: int, confirm_write?: bool}` |

### 3.2 安全层

1. **命令白名单**：仅允许预定义子命令域（calendar/docs/base/minutes/im/vc/task/approval/drive/wiki/sheets/auth/note）
2. **禁止 shell 拼接**：参数以 list 传 `subprocess.run(args=[...])`，无 `shell=True`
3. **写操作保护**：high-risk-write 子命令（如 `auth logout`、`task +create`）自动追加 `--yes`，且需 `confirm_write=true`

### 3.3 执行参数

| 参数 | 默认 | 说明 |
|------|------|------|
| 超时 | 60s | 可通过 `timeout` 入参覆盖 |
| 结果截断 | 50000 字符 | 复用 `_TOOL_RESULT_MAX_CHARS`（与 T-403 统一出口） |
| JSON 解析 | 自动 | `--format json` 注入，失败时返回原始 stdout |
| 权限错误 | 结构化 | 与 feishu_fetch 的 `_permission_block` 同模式 |

### 3.4 审计

- 通过 `audit_store.record_call` 落 `sf_mcp_call_audit` 表
- 脱敏字段：emp_no, command, args_digest, result_summary
- 入参摘要截断（仅前 200 字符），脱敏正则复用已有规则

### 3.5 与 feishu_fetch 的关系

```
feishu_fetch (高階, 語義化)           lark_execute (低階, 通用)
  feishu_calendar_agenda               lark_execute("calendar +agenda ...")
  feishu_meeting_notes                 lark_execute("vc +detail ...")
  feishu_doc_read                      lark_execute("docs +fetch ...")
  feishu_base_query                    lark_execute("base +record-list ...")

高階工具 = 已知返回格式 + 面试场景语义 + 结构化错误处理
低階工具 = 通用通道 + 能力探索 + feishu_fetch 未封装的命令
```

---

## 4. T-703：Workbench 绑定页

### 4.1 菜单 & 路由

- **菜单位置**：「工作区」分组新增「绑定飞书」，全角色可见
- **前端路由**：`/lark-binding`
- **后端注册**：`main.py` include_router `lark_binding.router`

### 4.2 页面布局

```
┌─────────────────────────────────────────────┐
│  🐦 绑定飞书账号                                │
├─────────────────────────────────────────────┤
│  [状态卡片]                                    │
│  ┌──────────────────────────────────────┐   │
│  │  🔵 已绑定 / ⚪ 未绑定                  │   │
│  │  身份: bot/openId: ou_xxx / user/... │   │
│  │  token 过期: 2026-08-12 00:00        │   │
│  │  授权 scope: N 项                     │   │
│  │  [解绑]                              │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  [scope 清单（已绑定时展开）]                    │
│  ┌──────────────────────────────────────┐   │
│  │  📋 已授权权限                        │   │
│  │  ✅ docs:* · 飞书云文档读写             │   │
│  │  ✅ base:* · 多维表格读写              │   │
│  │  ✅ minutes:* · 妙记读写              │   │
│  │  ... (来自 auth status 实时查询)       │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  [未绑定时的引导流程]                           │
│  ┌──────────────────────────────────────┐   │
│  │  ① 点击「绑定飞书」按钮                   │   │
│  │  ② 扫描二维码 / 打开链接完成飞书授权       │   │
│  │  ③ 授权完成后此页面自动刷新                │   │
│  │                                              │
│  │  [🔗 绑定飞书] 按钮 → 弹出二维码模态框        │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  [调用审计（admin 可见） — 可选区块]             │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### 4.3 状态管理

| 状态 | 前端展示 |
|------|---------|
| `unbound` | 引导绑定流程 + 绑定按钮 |
| `pending` | 二维码模态框（轮询完成） |
| `bound` | 身份卡片 + scope 清单 + 解绑按钮 |
| `error` | 错误提示 + 重试引导 |

### 4.4 后端端点

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | `/api/settings/lark/status` | 全角色 | 绑定状态（bound/identity/scopes/config_dir） |
| POST | `/api/settings/lark/login` | 全角色 | 发起授权 -> 返回 verification_url + device_code |
| POST | `/api/settings/lark/logout` | 全角色 | 解绑（清空隔离目录登录态） |
| GET | `/api/settings/lark/scopes` | 全角色 | 已授权 scope 详细清单 |

---

## 5. 文件变更清单

| 文件 | 操作 | 归属 |
|------|------|------|
| `mcp_server/tools/lark_auth.py` | 新建 | T-701 |
| `mcp_server/tools/lark_run.py` | 新建 | T-702 |
| `workbench/backend/routers/lark_binding.py` | 新建 | T-703 |
| `workbench/frontend/src/pages/LarkBinding.tsx` | 新建 | T-703 |
| `mcp_server/server.py` | 修改：TOOL_MODULES 注册 lark_auth + lark_run | T-701/T-702 |
| `workbench/backend/main.py` | 修改：include_router lark_binding | T-703 |
| `workbench/frontend/src/App.tsx` | 修改：菜单 + 路由 | T-703 |
| `workbench/frontend/src/api.ts` | 修改：larkApi 类型+方法 | T-703 |
| `.gitignore` | 修改：补充 `.lark-cli/` | T-701 |
| `agent/purposes/requirement_interview.md` | 修改：白名单加 lark_execute | T-702 |
| `test_specstd/test_mcp_server.py` | 修改：工具数断言 | T-701/T-702 |
| `docs/远期设计/SpecGuard-总控文档.md` | 修改：§5/§6 注册 | 协议 |

---

## 6. 验收清单

### T-701 多用户认证服务
- [ ] `lark_auth_status` 返回正确的用户身份（unbound/bound + identity）
- [ ] `lark_auth_login` 两阶段：Phase1 返回 verification_url → Phase2 完成授权
- [ ] `lark_auth_logout` 成功清空隔离目录登录态
- [ ] 每用户隔离目录 `{SG_ROOT}/.lark-cli/{emp_no}/` 生效（子进程 USERPROFILE）
- [ ] 并发锁：同一用户两线程同时 login 不互踩
- [ ] 未绑定用户明确提示引导授权
- [ ] `.gitignore` 已补充 `.lark-cli/`

### T-702 通用执行器
- [ ] `lark_execute` 透传命令成功执行并返回结构化结果
- [ ] 命令白名单校验：非法命令返回确定性错误
- [ ] 无 shell 拼接验证（传 list 不走 shell）
- [ ] 写操作 `confirm_write=true` 检查
- [ ] 超时 60s 截断 + 结果 50K 截断
- [ ] 权限错误结构化返回（复用 _permission_block 模式）
- [ ] 审计落库（sf_mcp_call_audit）

### T-703 绑定页
- [ ] 未绑定状态：引导绑定流程 + 绑定按钮
- [ ] 绑定中：二维码模态框（轮询）
- [ ] 已绑定：身份卡片 + scope 清单 + 解绑
- [ ] 解绑后状态同步刷新
- [ ] 前端 build 通过