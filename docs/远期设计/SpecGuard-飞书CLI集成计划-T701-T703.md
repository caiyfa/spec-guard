# 飞书 CLI 集成 Implementation Plan

> **For agentic workers:** Inline execution — implement tasks sequentially with verification checkpoints.
>
> **Goal:** 实现 SpecGuard 飞书 CLI 集成支线（T-701/T-702/T-703），使每用户可通过独立 feishu 账号绑定并在 Agent 对话/workbench UI 中使用 lark-cli 能力。
>
> **Architecture:** MCP 工具层封装认证与执行（lark_auth.py / lark_run.py），REST 路由供前端绑定页消费（lark_binding.py），共用底层 subprocess + USERPROFILE 隔离函数。遵循 T-602 TOOL_MODULES 单一注册面。
>
> **Tech Stack:** Python 3.14 / MCP stdio / FastAPI / React 19 + TS

---

## File Structure

### 新建文件

| 文件 | 职责 |
|------|------|
| `mcp_server/tools/lark_auth.py` | T-701：MCP 认证工具（status/login/logout）+ 底层函数（_do_status/_do_login/_do_logout/_run_lark/_user_lock），MCP handler 和 REST 共用 |
| `mcp_server/tools/lark_run.py` | T-702：MCP 通用执行器（lark_execute），命令白名单 + 写操作保护 + 审计 |
| `workbench/backend/routers/lark_binding.py` | T-703：REST 端点（status/login/logout/scopes），调 lark_auth 底层函数 |
| `workbench/frontend/src/pages/LarkBinding.tsx` | T-703：绑定页 UI（状态卡片/scope 清单/绑定引导/二维码模态框） |

### 修改文件

| 文件 | 变更 |
|------|------|
| `mcp_server/server.py` | TOOL_MODULES 注册 lark_auth + lark_run |
| `workbench/backend/main.py` | include_router lark_binding |
| `workbench/frontend/src/api.ts` | 新增 larkApi 类型+方法 |
| `workbench/frontend/src/App.tsx` | 菜单「绑定飞书」+ 路由 /lark-binding |
| `.gitignore` | 补充 `.lark-cli/` |
| `agent/purposes/requirement_interview.md` | 白名单加 lark_execute |
| `agent/purposes/test_workbench.md` | 白名单加 lark_* 工具 |
| `test_specstd/test_mcp_server.py` | 工具数断言更新 |
| `docs/远期设计/SpecGuard-总控文档.md` | §5 会话注册 + §6 文件登记 |

---

### Task 1: T-701 多用户飞书认证服务（lark_auth.py）

**负责文件**
- 新建: `mcp_server/tools/lark_auth.py`
- 修改: `mcp_server/server.py`（TOOL_MODULES 注册）
- 修改: `.gitignore`
- 修改: `test_specstd/test_mcp_server.py`

#### 1.1 创建 lark_auth.py — 底层函数 + MCP 工具

- [ ] **Step 1.1：创建 lark_auth.py 底层基础设施**

`mcp_server/tools/lark_auth.py` 的框架：

```python
"""lark_auth.py — T-701：多用户飞书 CLI 认证服务。

MCP 工具：
  lark_auth_status: 查询当前用户飞书绑定状态
  lark_auth_login:  两阶段飞书授权（返回 verification_url → device-code 完成）
  lark_auth_logout: 解绑（清空隔离目录登录态）

REST 共用函数（供 lark_binding.py 调用）：
  do_status(emp_no) / do_login(emp_no) / do_logout(emp_no)

安全红线：
- 每用户独立 USERPROFILE 隔离目录 {SG_ROOT}/.lark-cli/{emp_no}/
- 凭据不落日志/argv（审计脱敏复用 audit_store 规则）
- 飞书 CLI 路径从 shutil.which 发现，不硬编码
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent

# ── 用户隔离目录 ──
_LARK_DIR = SG_ROOT / ".lark-cli"
_LOCK_CREATE = threading.Lock()
_USER_LOCKS: dict[str, threading.Lock] = {}
_LARK_TIMEOUT = 90  # login 两阶段放宽


def _lark_command() -> list[str]:
    if sys.platform == "win32":
        full = shutil.which("lark-cli") or "lark-cli"
        return ["cmd", "/c", full]
    return ["lark-cli"]


def _user_lark_dir(emp_no: str) -> Path:
    d = _LARK_DIR / emp_no
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inject_userprof(emp_no: str) -> dict:
    env = os.environ.copy()
    lark_dir = str(_user_lark_dir(emp_no))
    if sys.platform == "win32":
        env["USERPROFILE"] = lark_dir
    else:
        env["HOME"] = lark_dir
    return env


def _user_lock(emp_no: str) -> threading.Lock:
    with _LOCK_CREATE:
        if emp_no not in _USER_LOCKS:
            _USER_LOCKS[emp_no] = threading.Lock()
    return _USER_LOCKS[emp_no]


def _run_lark(emp_no: str, args: list[str], timeout: int = _LARK_TIMEOUT) -> dict:
    cmd = _lark_command() + args + ["--format", "json"]
    env = _inject_userprof(emp_no)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", check=False, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError(f"lark-cli 调用超时（>{timeout}s）: {' '.join(args[:3])}")
    except OSError as e:
        raise ValueError(f"lark-cli 不可用: {e}")
    text = (proc.stdout or "") + (proc.stderr or "")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"lark-cli 输出非 JSON（rc={proc.returncode}）: {text[:300]}")
    if not payload.get("ok"):
        raise ValueError(f"lark-cli 调用失败: {text[:300]}")
    return payload


# ── 底层认证函数（REST + MCP 共用）──

def do_status(emp_no: str) -> dict:
    """查询绑定状态。"""
    lark_dir = _user_lark_dir(emp_no)
    # 无目录/无 token.json 标记为 unbound
    token_file = lark_dir / ".lark-cli" / "token.json"
    # 注意：USERPROFILE 重定向后 lark-cli 的 token 路径可能在 lark_dir 下
    if not any(lark_dir.rglob("token.json")):
        return {"bound": False, "identity": "", "scopes": [], "identity_name": "", "open_id": "", "config_dir": str(lark_dir)}
    try:
        payload = _run_lark(emp_no, ["auth", "status"])
        data = payload.get("data") or payload
        bot_info = data.get("bot") or {}
        user_info = data.get("user") or {}
        scopes = data.get("scopes", [])
        # 优先 user 身份
        if user_info:
            identity = "user"
            identity_name = user_info.get("name", user_info.get("open_id", ""))
            open_id = user_info.get("open_id", "")
        elif bot_info:
            identity = "bot"
            identity_name = bot_info.get("name", bot_info.get("open_id", ""))
            open_id = bot_info.get("open_id", "")
        else:
            identity = ""
            identity_name = ""
            open_id = ""
        return {
            "bound": True,
            "identity": identity,
            "identity_name": identity_name,
            "open_id": open_id,
            "scopes": scopes if isinstance(scopes, list) else [],
            "config_dir": str(lark_dir),
        }
    except ValueError as e:
        # auth status 失败（如未登录）→ unbound
        return {"bound": False, "identity": "", "scopes": [], "identity_name": "", "open_id": "", "config_dir": str(lark_dir), "error": str(e)}


def do_login(emp_no: str, scope: str = "") -> dict:
    """两阶段登录：Phase1 返回 verification_url。

    Returns:
        {"phase": "waiting", "verification_url": str, "device_code": str}
        或 {"phase": "completed", "identity": str, "open_id": str}
    """
    with _user_lock(emp_no):
        args = ["auth", "login", "--no-wait"]
        if scope:
            args += ["--scope", scope]
        try:
            payload = _run_lark(emp_no, args)
        except ValueError as e:
            return {"phase": "error", "error": str(e)}
        data = payload.get("data") or payload
        verification_url = data.get("verification_url", data.get("url", ""))
        device_code = data.get("device_code", "")
        if not verification_url:
            # 可能已经登录成功（首次调用已授权）
            status = do_status(emp_no)
            if status.get("bound"):
                return {
                    "phase": "completed",
                    "identity": status.get("identity", ""),
                    "open_id": status.get("open_id", ""),
                    "identity_name": status.get("identity_name", ""),
                }
            return {"phase": "error", "error": "返回无 verification_url"}
        return {
            "phase": "waiting",
            "verification_url": verification_url,
            "device_code": device_code,
        }


def do_logout(emp_no: str) -> dict:
    """解绑。"""
    with _user_lock(emp_no):
        try:
            _run_lark(emp_no, ["auth", "logout", "--yes"])
        except ValueError:
            pass  # 未登录状态也算成功
        return {"ok": True}


# ── MCP 工具定义 ──

lark_auth_status_tool = Tool(
    name="lark_auth_status",
    description="查询当前用户飞书 CLI 绑定状态（bound/unbound、身份类型、scope 列表）。"
                "Agent 对话中用于判断飞书工具是否可用。",
    inputSchema={
        "type": "object",
        "properties": {},
    },
)

lark_auth_login_tool = Tool(
    name="lark_auth_login",
    description="发起飞书 CLI 两阶段授权。Phase1 返回 verification_url（用户需打开该链接完成授权），"
                "Phase2 自动完成（轮询检测）。未授权 scope 时给出引导。",
    inputSchema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "可选：指定授权 scope 范围（默认与当前 app 一致）",
            },
        },
    },
)

lark_auth_logout_tool = Tool(
    name="lark_auth_logout",
    description="解绑当前用户飞书 CLI 账号（清空隔离目录登录态）。解绑后需重新授权。",
    inputSchema={
        "type": "object",
        "properties": {},
    },
)

TOOLS = [lark_auth_status_tool, lark_auth_login_tool, lark_auth_logout_tool]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    from services.auth import current_emp_no
    emp_no = current_emp_no()
    if not emp_no:
        return [TextContent(type="text", text="错误: 未获取到当前用户身份（emp_no 为空）")]
    try:
        if name == "lark_auth_status":
            result = do_status(emp_no)
        elif name == "lark_auth_login":
            result = do_login(emp_no, arguments.get("scope", ""))
        elif name == "lark_auth_logout":
            result = do_logout(emp_no)
        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]
```

- [ ] **Step 1.2：注册到 server.py TOOL_MODULES**

在 `mcp_server/server.py` 的 import 节加：
```python
from mcp_server.tools import lark_auth
from mcp_server.tools import lark_run  # T-702 也提前导入
```

在 `build_tool_modules()` 的 mods 列表追加：
```python
lark_auth,
lark_run,
```

- [ ] **Step 1.3：更新 .gitignore**

追加一行 `.lark-cli/` 到 `d:\work\tdm-code\specguard\.gitignore`

- [ ] **Step 1.4：更新 test_mcp_server 工具数断言**

在 `test_specstd/test_mcp_server.py` 中找到工具数断言（当前 `TOOL_COUNT = 61` 等），+4（lark_auth 3 + lark_run 1 = 增加 4）。

```python
# 搜索：TOOL_COUNT = 61（或当前值）→ 改为 65
# 搜索工具名称集合 → 追加 "lark_auth_status", "lark_auth_login", "lark_auth_logout", "lark_execute"
```

---

### Task 2: T-702 通用执行器（lark_run.py）

**负责文件**
- 新建: `mcp_server/tools/lark_run.py`

- [ ] **Step 2.1：创建 lark_run.py**

```python
"""lark_run.py — T-702：飞书 CLI 通用执行器。

MCP 工具：
  lark_execute: 透传 lark-cli 命令（白名单校验 + 写操作保护 + 审计）

安全设计：
- 命令白名单：仅允许预定义子命令域
- 禁止 shell 拼接：参数以 list 传 subprocess.run，无 shell=True
- 写操作自动追加 --yes 且需 confirm_write=true
- 审计落库：通过 audit_store.record_call
"""

from __future__ import annotations

import json
import sys

from mcp.types import Tool, TextContent

# 复用 lark_auth 的底层
from mcp_server.tools.lark_auth import _run_lark, _lark_command

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

# ══════════════════════════════════════════════════════════
# 安全层
# ══════════════════════════════════════════════════════════

# 允许的子命令域白名单
_ALLOWED_COMMANDS = frozenset({
    "calendar", "docs", "base", "minutes", "im", "vc",
    "task", "approval", "drive", "wiki", "sheets", "auth", "note",
})

# 写操作子命令关键词（需 --yes + confirm_write=true）
_HIGH_RISK_WRITE = frozenset({
    "+create", "+update", "+delete", "logout", "register",
    "+add", "+remove", "+set",
})

_LARK_TIMEOUT = 60  # 通用执行器默认 60s
_TOOL_RESULT_MAX_CHARS = 50000  # 与 T-403 统一截断

# ══════════════════════════════════════════════════════════
# MCP 工具定义
# ══════════════════════════════════════════════════════════

lark_execute_tool = Tool(
    name="lark_execute",
    description="飞书 CLI 通用命令执行器。透传 lark-cli 子命令（calendar/docs/base/minutes/im/vc/"
                "task/approval/drive/wiki/sheets/auth/note）。写操作需设置 confirm_write=true，"
                "自动追加 --yes。结果自动 JSON 解析，失败返回原始 stdout。",
    inputSchema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "lark-cli 子命令（如 calendar +agenda、docs +fetch）",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "命令参数列表（每个参数独立元素，禁止 shell 拼接）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 60，可选 10-300）",
            },
            "confirm_write": {
                "type": "boolean",
                "description": "写操作确认（命令含 high-risk-write 子命令时必须为 true）",
            },
        },
        "required": ["command"],
    },
)

TOOLS = [lark_execute_tool]


def _check_write_permission(command: str, confirm_write: bool) -> None:
    """检查写操作权限。"""
    for keyword in _HIGH_RISK_WRITE:
        if keyword in command.split():
            if not confirm_write:
                raise ValueError(
                    f"命令 '{command}' 包含写操作关键词 '{keyword}'，"
                    f"请设置 confirm_write=true 确认后执行")
            break


async def handle(name: str, arguments: dict) -> list[TextContent]:
    from services.auth import current_emp_no
    emp_no = current_emp_no()
    if not emp_no:
        return [TextContent(type="text", text="错误: 未获取到当前用户身份")]
    if name != "lark_execute":
        return [TextContent(type="text", text=f"未知工具: {name}")]

    command = str(arguments.get("command", "")).strip()
    if not command:
        return [TextContent(type="text", text="错误: command 必填")]

    # 白名单校验
    cmd_parts = command.split()
    if not cmd_parts or cmd_parts[0] not in _ALLOWED_COMMANDS:
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "error": f"命令域 '{cmd_parts[0] if cmd_parts else ''}' 不在白名单中。"
                     f"允许的域: {', '.join(sorted(_ALLOWED_COMMANDS))}",
        }, ensure_ascii=False))]

    # 写操作确认
    confirm_write = bool(arguments.get("confirm_write", False))
    try:
        _check_write_permission(command, confirm_write)
    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))]

    # 构造完整 args
    raw_args = arguments.get("args", [])
    if not isinstance(raw_args, list):
        return [TextContent(type="text", text="错误: args 必须是字符串数组")]
    full_args = command.split() + [str(a) for a in raw_args]

    # 写操作自动追加 --yes
    for keyword in _HIGH_RISK_WRITE:
        if keyword in full_args and "--yes" not in full_args:
            full_args.append("--yes")
            break

    timeout = int(arguments.get("timeout", _LARK_TIMEOUT))
    timeout = max(10, min(timeout, 300))

    try:
        payload = _run_lark(emp_no, full_args, timeout=timeout)
    except ValueError as e:
        text = str(e)
        if any(h in text.lower() for h in ("无权限", "权限不足", "forbidden", "denied")):
            return [TextContent(type="text", text=json.dumps({
                "ok": False,
                "status": "permission_denied",
                "hint": "无权限操作此资源，请检查飞书 scope 授权",
                "error": text[:500],
            }, ensure_ascii=False))]
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": text[:500]}, ensure_ascii=False))]

    # 结果截断
    result_str = json.dumps(payload, ensure_ascii=False, default=str)
    if len(result_str) > _TOOL_RESULT_MAX_CHARS:
        result_str = result_str[:_TOOL_RESULT_MAX_CHARS] + f"\n...（截断，原始 {len(result_str)} 字符）"

    return [TextContent(type="text", text=result_str)]
```

---

### Task 3: T-703 REST 后端端点（lark_binding.py）

**负责文件**
- 新建: `workbench/backend/routers/lark_binding.py`
- 修改: `workbench/backend/main.py`

- [ ] **Step 3.1：创建 lark_binding.py**

```python
"""lark_binding.py — T-703：飞书绑定 REST 端点。

供前端 LarkBinding 页面消费，底层认证逻辑复用 lark_auth 的 do_status/do_login/do_logout。

端点：
  GET    /api/settings/lark/status     — 绑定状态
  POST   /api/settings/lark/login      — 发起授权
  POST   /api/settings/lark/logout     — 解绑
  GET    /api/settings/lark/scopes     — scope 清单
"""

from fastapi import APIRouter, Depends
from services.auth import get_current_user, CurrentUser
from mcp_server.tools.lark_auth import do_status, do_login, do_logout

router = APIRouter(prefix="/api/settings/lark", tags=["lark"])


@router.get("/status")
def lark_status(user: CurrentUser = Depends(get_current_user)):
    result = do_status(user.emp_no)
    return result


@router.post("/login")
def lark_login(scope: str = "", user: CurrentUser = Depends(get_current_user)):
    result = do_login(user.emp_no, scope)
    return result


@router.post("/logout")
def lark_logout(user: CurrentUser = Depends(get_current_user)):
    result = do_logout(user.emp_no)
    return result


@router.get("/scopes")
def lark_scopes(user: CurrentUser = Depends(get_current_user)):
    """返回已授权的 scope 详细清单（从 auth status 解析）。"""
    status = do_status(user.emp_no)
    return {"scopes": status.get("scopes", []), "bound": status.get("bound", False)}
```

- [ ] **Step 3.2：注册到 main.py**

在 `workbench/backend/main.py` 的 import 节加：
```python
from routers import lark_binding
```

在 `app.include_router` 区域加：
```python
app.include_router(lark_binding.router, dependencies=[Depends(get_current_user)])
```

---

### Task 4: T-703 前端绑定页（LarkBinding.tsx + 菜单/路由/API）

**负责文件**
- 新建: `workbench/frontend/src/pages/LarkBinding.tsx`
- 修改: `workbench/frontend/src/api.ts`
- 修改: `workbench/frontend/src/App.tsx`

- [ ] **Step 4.1：api.ts 添加 larkApi**

在 `d:\work\tdm-code\specguard\workbench\frontend\src\api.ts` 末尾追加：

```typescript
// ── T-703：飞书 CLI 绑定 ──
export interface LarkStatus {
  bound: boolean;
  identity: string;
  identity_name: string;
  open_id: string;
  scopes: string[];
  config_dir: string;
  error?: string;
}

export interface LarkLoginResult {
  phase: 'waiting' | 'completed' | 'error';
  verification_url?: string;
  device_code?: string;
  identity?: string;
  open_id?: string;
  identity_name?: string;
  error?: string;
}

export interface LarkScopes {
  scopes: string[];
  bound: boolean;
}

export const larkApi = {
  status: () => request<LarkStatus>('/settings/lark/status'),
  login: (scope = '') => request<LarkLoginResult>('/settings/lark/login', {
    method: 'POST',
    body: JSON.stringify({ scope }),
  }),
  logout: () => request<{ ok: boolean }>('/settings/lark/logout', { method: 'POST' }),
  scopes: () => request<LarkScopes>('/settings/lark/scopes'),
};
```

- [ ] **Step 4.2：创建 LarkBinding.tsx**

```tsx
/** LarkBinding — T-703：绑定飞书页签
 *
 * 状态管理：
 *   unbound → 引导绑定流程 + 绑定按钮
 *   pending → 二维码模态框（轮询）
 *   bound   → 身份卡片 + scope 清单 + 解绑
 *   error   → 错误提示 + 重试
 */
import { useEffect, useState, useCallback } from 'react';
import { larkApi } from '../api';
import type { LarkStatus, LarkLoginResult } from '../api';

type BindState = 'loading' | 'unbound' | 'pending' | 'bound' | 'error';

export default function LarkBinding() {
  const [state, setState] = useState<BindState>('loading');
  const [status, setStatus] = useState<LarkStatus | null>(null);
  const [loginResult, setLoginResult] = useState<LarkLoginResult | null>(null);
  const [error, setError] = useState('');

  const loadStatus = useCallback(async () => {
    try {
      const s = await larkApi.status();
      setStatus(s);
      setState(s.bound ? 'bound' : 'unbound');
    } catch (e: any) {
      setError(String(e.message || e));
      setState('error');
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleLogin = async () => {
    try {
      const r = await larkApi.login();
      setLoginResult(r);
      if (r.phase === 'waiting') {
        setState('pending');
        // 打开 verification_url
        if (r.verification_url) {
          window.open(r.verification_url, '_blank');
        }
        // 轮询检测授权完成
        const poll = setInterval(async () => {
          try {
            const s = await larkApi.status();
            if (s.bound) {
              clearInterval(poll);
              setStatus(s);
              setState('bound');
            }
          } catch { /* 忽略轮询错误 */ }
        }, 3000);
        // 3 分钟后停止轮询
        setTimeout(() => clearInterval(poll), 180000);
      } else if (r.phase === 'completed') {
        setState('bound');
        await loadStatus();
      } else {
        setError(r.error || '授权失败');
        setState('error');
      }
    } catch (e: any) {
      setError(String(e.message || e));
      setState('error');
    }
  };

  const handleLogout = async () => {
    try {
      await larkApi.logout();
      setStatus(null);
      setLoginResult(null);
      setState('unbound');
    } catch (e: any) {
      setError(String(e.message || e));
    }
  };

  if (state === 'loading') {
    return (
      <div className="p-6 text-gray-500 text-sm">加载飞书绑定状态...</div>
    );
  }

  return (
    <div className="h-full flex flex-col p-6 max-w-2xl">
      <div className="flex items-center gap-2 mb-6">
        <span className="text-xl">🐦</span>
        <h2 className="text-lg font-semibold">绑定飞书账号</h2>
      </div>

      {/* 状态卡片 */}
      <div className="bg-surface-2 border border-border rounded-lg p-4 mb-4">
        {state === 'bound' && status && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="font-medium">已绑定</span>
              <span className="text-xs text-gray-500 ml-auto">
                配置目录: {status.config_dir}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-gray-500">身份</span>
                <span className="ml-2">{status.identity} / {status.identity_name}</span>
              </div>
              <div>
                <span className="text-gray-500">OpenID</span>
                <span className="ml-2 text-xs font-mono">{status.open_id}</span>
              </div>
              <div>
                <span className="text-gray-500">授权 scope</span>
                <span className="ml-2">{status.scopes?.length || 0} 项</span>
              </div>
            </div>
            <button onClick={handleLogout}
              className="mt-4 px-3 py-1.5 text-xs bg-red-900/30 text-red-400 rounded hover:bg-red-900/50 transition-colors">
              解绑
            </button>
          </div>
        )}

        {state === 'unbound' && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-gray-500" />
              <span className="font-medium">未绑定</span>
            </div>
            <p className="text-sm text-gray-400 mb-4">
              绑定飞书账号后，可在 Agent 对话中使用飞书 CLI 能力（文档/多维表格/妙记/聊天/日程等）。
            </p>
            <div className="space-y-2 text-sm text-gray-400 mb-4">
              <p>① 点击下方「绑定飞书」按钮</p>
              <p>② 在弹出的飞书授权页面完成授权</p>
              <p>③ 授权完成后页面自动刷新</p>
            </div>
            <button onClick={handleLogin}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">
              🔗 绑定飞书
            </button>
          </div>
        )}

        {state === 'pending' && loginResult?.verification_url && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
              <span className="font-medium">等待授权完成...</span>
            </div>
            <p className="text-sm text-gray-400 mb-3">
              请在弹出的页面中完成飞书授权。页面将自动检测授权状态。
            </p>
            <div className="bg-surface-1 rounded p-3 mb-3 text-xs break-all">
              <p className="text-gray-500 mb-1">授权 URL:</p>
              <a href={loginResult.verification_url} target="_blank"
                className="text-blue-400 hover:underline">
                {loginResult.verification_url}
              </a>
            </div>
            <p className="text-xs text-gray-600">
              若页面未自动打开，请手动复制上方链接在浏览器中打开。
            </p>
          </div>
        )}

        {state === 'error' && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="font-medium text-red-400">出错</span>
            </div>
            <p className="text-sm text-red-400 mb-3">{error}</p>
            <button onClick={loadStatus}
              className="px-3 py-1.5 text-xs bg-surface-1 rounded hover:bg-surface-3 transition-colors">
              重试
            </button>
          </div>
        )}
      </div>

      {/* Scope 清单（已绑定时展开） */}
      {state === 'bound' && status?.scopes && status.scopes.length > 0 && (
        <div className="bg-surface-2 border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-2">📋 已授权权限</h3>
          <div className="space-y-1">
            {status.scopes.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-gray-400">
                <span className="text-green-500">✅</span>
                <span className="font-mono">{s}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4.3：App.tsx 菜单 + 路由**

在 `d:\work\tdm-code\specguard\workbench\frontend\src\App.tsx` 中：

import 区加：`import LarkBinding from './pages/LarkBinding';`

在「工作区」菜单组的 items 尾部添加：
```typescript
{ to: '/lark-binding', label: '绑定飞书', roles: ALL },
```

在 Routes 区加：
```tsx
<Route path="/lark-binding" element={<LarkBinding />} />
```

---

### Task 5: Purpose 白名单 & 总控文档登记

- [ ] **Step 5.1：requirement_interview.md 白名单加 lark_execute**

在 `agent/purposes/requirement_interview.md` 中找到 tools 白名单列表，追加：
```yaml
  - lark_execute
```

同理 test_workbench.md 也加（全场景可用的 lark_auth_* 和 lark_execute）。

- [ ] **Step 5.2：总控文档 §5 会话注册**

追加一行到 §5 会话注册表：
```
| sess-lark-dev | 飞书 CLI 集成施工 | T-701/T-702/T-703 | 2026-08-11 | T-701→T-702→T-703 顺序施工，与 S8 主线并行 |
```

- [ ] **Step 5.3：总控文档 §6 文件登记**

在 §6 文件变更登记表追加各行。

- [ ] **Step 5.4：§4.6 状态更新**

将 §4.6 T-701/T-702/T-703 的状态从「未认领」改为「进行中」，会话ID从空白改为 `sess-lark-dev`。

---

### Task 6: 验证 & 提交

- [ ] **Step 6.1：pytest test_specstd 验证**

```bash
cd d:\work\tdm-code\specguard
python -m pytest test_specstd -v -k "mcp_server" 2>&1 | tail -30
```

确认工具数断言通过。

- [ ] **Step 6.2：前端 build 验证**

```bash
cd d:\work\tdm-code\specguard\workbench\frontend
npm run build 2>&1
```

确认 tsc + vite 构建通过。

- [ ] **Step 6.3：总控文档指纹更新**

按 §1 协议更新 §6 登记行的修改后 hash。

- [ ] **Step 6.4：git commit**

```bash
cd d:\work\tdm-code\specguard
git add -A
git commit -m "feat: T-701/T-702/T-703 飞书CLI集成——多用户认证/通用执行器/绑定页"
```