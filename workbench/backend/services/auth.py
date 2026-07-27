"""认证与 RBAC 依赖注入（M6 基座）。

模式（环境变量 SG_AUTH_MODE）：
- uac（生产默认）：Bearer token → UAC check/authentication 验证（TTL 5min 缓存）
- mock（开发/测试）：本地 mock-login 签发 `mock-{emp_no}` token，不调 UAC

UAC 对接（集团 Authing 方案2，仅需配置地址）：
- 登录跳转：{UAC}/api/authing/login?redirectURL={回跳地址}
- 验证：GET {UAC}/api/authing/check/authentication?serialize=false&accessToken={token}
- 用户资料：GET {UAC}/api/user/current/get（Authorization: Bearer {token}）
- 登出：{UAC}/logout
注：UAC 返回结构以首日 SIT 实测为准，解析逻辑集中在 _uac_validate/_uac_user_info 两处。

依赖：
- get_current_user: 全部 /api 路由挂载（health/auth 端点除外）
- require_role(*roles): 角色门禁
- resolve_workspace: 解析请求工作区（X-SG-Workspace header > 用户默认 > 403；非 admin 校验授权）
"""

from __future__ import annotations

import contextvars
import os
import re
import time
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, Request, WebSocket

from services import user_store

# 请求级用户身份上下文（M7：draft 作者归属等下游场景使用；
# asyncio.to_thread / threadpool 复制 context，下游线程可读）
_CTX_EMP_NO: contextvars.ContextVar[str] = contextvars.ContextVar("sg_emp_no", default="")


def current_emp_no() -> str:
    """当前请求的操作人工号（未认证/无上下文时为空串）。"""
    return _CTX_EMP_NO.get()

SG_AUTH_MODE = os.environ.get("SG_AUTH_MODE", "uac")  # uac / mock
SG_UAC_BASE = os.environ.get(
    "SG_UAC_BASE", "http://sit-ha.fehorizon.com/femsp/uac").rstrip("/")

# token 验证缓存：{token: (emp_no, name, exp_ts)}
_TOKEN_CACHE: dict[str, tuple[str, str, float]] = {}
CACHE_TTL_SECONDS = 300


@dataclass
class CurrentUser:
    emp_no: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def uac_login_url(redirect_url: str) -> str:
    return f"{SG_UAC_BASE}/api/authing/login?redirectURL={redirect_url}"


def uac_logout_url() -> str:
    return f"{SG_UAC_BASE}/logout"


# ══════════════════════════════════════════════════════════
# token 验证
# ══════════════════════════════════════════════════════════

def _uac_validate(token: str) -> tuple[str, str]:
    """调 UAC 验证 token，返回 (emp_no, name)。失败抛 HTTPException(401)。

    响应结构容错解析（SIT 实读后若偏差仅改此函数）：
    预期 {"statusCode": 200, "data": {...}} 或直接的 200 + 用户 JSON。
    """
    try:
        resp = httpx.get(
            f"{SG_UAC_BASE}/api/authing/check/authentication",
            params={"serialize": "false", "accessToken": token},
            timeout=5.0,
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"UAC 验证服务不可达: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="token 已失效，请重新登录")
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=401, detail="UAC 验证响应异常")
    # 容错：信封或非信封结构都尝试取身份字段
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    ok = data.get("statusCode", 200) in (200, "200") or body
    if not ok:
        raise HTTPException(status_code=401, detail="token 已失效，请重新登录")
    emp_no = str(body.get("empNo") or body.get("emp_no") or body.get("account")
                 or body.get("username") or body.get("sub") or "")
    name = str(body.get("name") or body.get("empName") or body.get("nickname") or "")
    if not emp_no:
        raise HTTPException(status_code=401, detail="UAC 响应缺少用户标识")
    return emp_no, name


def _uac_user_info(token: str) -> dict:
    """调 UAC /api/user/current/get 获取用户资料（计划 §一：首个请求时调用）。

    返回 {emp_no, name}（字段缺失时尽力而为，返回空 dict 不阻断登录）。
    """
    try:
        resp = httpx.get(
            f"{SG_UAC_BASE}/api/user/current/get",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        body = data.get("data") if isinstance(data.get("data"), dict) else data
        if not isinstance(body, dict):
            return {}
        emp_no = str(body.get("empNo") or body.get("emp_no") or body.get("account")
                     or body.get("username") or "")
        name = str(body.get("name") or body.get("empName") or body.get("nickname") or "")
        return {"emp_no": emp_no, "name": name}
    except Exception:
        return {}


def _validate_token(token: str) -> tuple[str, str]:
    """验证 token → (emp_no, name)。带 5min TTL 缓存。"""
    cached = _TOKEN_CACHE.get(token)
    if cached and cached[2] > time.time():
        return cached[0], cached[1]

    if SG_AUTH_MODE == "mock":
        # mock token 形式：mock-{emp_no}
        if not token.startswith("mock-") or len(token) <= 5:
            raise HTTPException(status_code=401, detail="mock token 非法")
        emp_no = token[5:]
        user = user_store.get_user(emp_no)
        name = user["name"] if user else emp_no
        result = (emp_no, name)
    else:
        result = _uac_validate(token)
        # 计划 §一：验证通过后调 /api/user/current/get 取更完整用户资料（姓名等）
        info = _uac_user_info(token)
        if info.get("name"):
            result = (result[0], info["name"])
        # 登录留痕（仅新鲜验证时记录，缓存命中不重复记）
        try:
            user_store.audit(result[0], "login", "", "uac")
        except Exception:
            pass

    _TOKEN_CACHE[token] = (result[0], result[1], time.time() + CACHE_TTL_SECONDS)
    return result


def issue_mock_token(emp_no: str, name: str = "") -> str:
    """mock 模式登录签发 token（仅 SG_AUTH_MODE=mock 可用）。"""
    if SG_AUTH_MODE != "mock":
        raise HTTPException(status_code=403, detail="非 mock 模式，请走 UAC 登录")
    # 工号将编进 token 放入 HTTP Authorization header（仅支持 ASCII），
    # 中文/空格/特殊字符必须在此拦截——否则签发成功但后续请求必然构造失败
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", emp_no or ""):
        raise HTTPException(status_code=400,
                            detail="工号仅支持字母、数字、下划线、连字符（1-64 位）")
    user_store.upsert_user(emp_no, name or emp_no)
    return f"mock-{emp_no}"


# ══════════════════════════════════════════════════════════
# FastAPI 依赖
# ══════════════════════════════════════════════════════════

def _extract_token(headers, query_params) -> str:
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    # WebSocket 等无法设 header 的场景允许 query 参数
    return query_params.get("token", "")


def _authenticate(headers, query_params) -> CurrentUser:
    """认证核心：解析 token → 验证 → upsert 用户 → CurrentUser（HTTP/WS 共用）。"""
    token = _extract_token(headers, query_params)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    emp_no, name = _validate_token(token)
    user = user_store.upsert_user(emp_no, name)
    _CTX_EMP_NO.set(user["emp_no"])
    return CurrentUser(emp_no=user["emp_no"], name=user["name"], role=user["role"])


async def get_current_user(request: Request) -> CurrentUser:
    """认证依赖（HTTP 路由）。"""
    return _authenticate(request.headers, request.query_params)


async def get_current_user_ws(websocket: WebSocket) -> CurrentUser:
    """认证依赖（WebSocket 路由；握手期拒绝会关闭连接）。"""
    return _authenticate(websocket.headers, websocket.query_params)


def require_role(*roles: str):
    """角色门禁依赖工厂（HTTP）：require_role("admin") / require_role("admin", "tester")。"""
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"需要 {'/'.join(roles)} 角色")
        return user
    return checker


def require_role_ws(*roles: str):
    """角色门禁依赖工厂（WebSocket）。"""
    async def checker(user: CurrentUser = Depends(get_current_user_ws)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"需要 {'/'.join(roles)} 角色")
        return user
    return checker


async def optional_workspace(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> str:
    """非强制工作区解析：header > 用户默认 > 空串（不 403，执行触发等场景用）。"""
    name = request.headers.get("X-SG-Workspace", "").strip()
    if not name:
        db_user = user_store.get_user(user.emp_no) or {}
        name = (db_user.get("default_workspace") or "").strip()
    return name


async def resolve_workspace(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> str:
    """解析请求工作区：X-SG-Workspace header > 用户默认工作区 > 403。

    非 admin 用户必须已被授权该工作区（workspace_grants）。
    """
    name = request.headers.get("X-SG-Workspace", "").strip()
    if not name:
        db_user = user_store.get_user(user.emp_no) or {}
        name = (db_user.get("default_workspace") or "").strip()
    if not name:
        raise HTTPException(status_code=403, detail="请先选择工作区（顶部工作区选择器）")
    if not user.is_admin and not user_store.has_grant(user.emp_no, name):
        raise HTTPException(status_code=403, detail=f"未授权工作区: {name}")
    return name
