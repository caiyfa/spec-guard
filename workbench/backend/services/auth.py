"""认证与 RBAC 依赖注入（M6 基座）。

模式（环境变量 SG_AUTH_MODE）：
- uac（生产默认）：Bearer token → UAC check/authentication 验证（TTL 5min 缓存）
- mock（开发/测试）：本地 mock-login 签发 `mock-{emp_no}` token，不调 UAC

UAC 对接（集团 Authing 方案2，仅需配置地址）：
- 登录跳转（SSO）：{UACSSO}/login?app_id={APP_ID}&protocol=oidc&redirect_uri={回跳地址}
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
from urllib.parse import unquote

import httpx
from fastapi import Depends, HTTPException, Request, WebSocket

from services import user_store

# 请求级用户身份上下文（M7：draft 作者归属等下游场景使用；
# asyncio.to_thread / threadpool 复制 context，下游线程可读）
# T-975：contextvar 定义下沉 sg_core.emp_context（mcp_server/agent 工具的作者归属
# 与 FastAPI 会话共享同一实例）；auth 内保留原名 re-export。
from sg_core.emp_context import _CTX_EMP_NO  # noqa: F401（auth 内 set/get 继续用）


def current_emp_no() -> str:
    """当前请求的操作人工号（未认证/无上下文时为空串）。"""
    return _CTX_EMP_NO.get()

SG_AUTH_MODE = os.environ.get("SG_AUTH_MODE", "uac")  # uac / mock
SG_UAC_BASE = os.environ.get(
    "SG_UAC_BASE", "http://sit-ha.fehorizon.com/femsp/uac").rstrip("/")
# Authing SSO（登录页跳转）
SG_UAC_SSO_BASE = os.environ.get(
    "SG_UAC_SSO_BASE", "http://sso.sit-authing.fehorizon.com").rstrip("/")
SG_UAC_APP_ID = os.environ.get(
    "SG_UAC_APP_ID", "650d55be5fb1d2cc66d9a550")

# token 验证缓存：{token: (emp_no, name, exp_ts)}
_TOKEN_CACHE: dict[str, tuple[str, str, float]] = {}
CACHE_TTL_SECONDS = 300
# L3：缓存条数阈值——超过后写入前惰性清理过期条目（防多用户长跑内存无限增长）
_MAX_TOKEN_CACHE = 5000


@dataclass
class CurrentUser:
    emp_no: str
    name: str
    role: str          # 主角色（兼容存量单值语义）
    roles: list = None  # 全量角色集（v1.8 多角色：一人可多用途）

    def __post_init__(self):
        if not self.roles:
            self.roles = [self.role] if self.role else []

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


def uac_login_url(redirect_url: str) -> str:
    """Authing SSO 登录 URL（OIDC 协议）。"""
    return f"{SG_UAC_SSO_BASE}/login?app_id={SG_UAC_APP_ID}&protocol=oidc&redirect_uri={redirect_url}"


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
    """验证 token → (emp_no, name)。带 5min TTL 缓存。

    自动识别 token 类型：
    - mock- 前缀 → mock token，本地解析工号查 SQLite
    - 其他 → UAC token，调 UAC API 验证
    """
    cached = _TOKEN_CACHE.get(token)
    if cached and cached[2] > time.time():
        return cached[0], cached[1]

    if token.startswith("mock-"):
        # mock token 形式：mock-{emp_no}
        # 仅 SG_AUTH_MODE=mock 时接受 mock token（生产环境拒绝，准入由 /mock-login 端点+前端确定）
        if os.environ.get("SG_AUTH_MODE", "uac") != "mock":
            raise HTTPException(status_code=401, detail="mock token 仅允许开发环境（SG_AUTH_MODE=mock）")
        if len(token) <= 5:
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

    # L3：写入前惰性清理（超阈值时才扫一次，过期条目逐出）
    if len(_TOKEN_CACHE) >= _MAX_TOKEN_CACHE:
        _now_ts = time.time()
        stale = [k for k, v in _TOKEN_CACHE.items() if v[2] <= _now_ts]
        for k in stale:
            del _TOKEN_CACHE[k]
    _TOKEN_CACHE[token] = (result[0], result[1], time.time() + CACHE_TTL_SECONDS)
    return result


def issue_mock_token(emp_no: str, name: str = "") -> str:
    """mock 模式登录签发 token（mock/UAC 模式均可使用）。"""
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
    # T-014：注入 specstd 用户上下文——产物写读点据此定位私有区（.specguard/{emp}/）
    try:
        from specstd.workspace import set_context_emp_no as _sg_set_emp
        _sg_set_emp(user["emp_no"])
    except Exception:
        pass
    return CurrentUser(emp_no=user["emp_no"], name=user["name"],
                       role=user.get("role", "viewer"), roles=user.get("roles") or None)


async def get_current_user(request: Request) -> CurrentUser:
    """认证依赖（HTTP 路由）。"""
    return _authenticate(request.headers, request.query_params)


async def get_current_user_ws(websocket: WebSocket) -> CurrentUser:
    """认证依赖（WebSocket 路由；握手期拒绝会关闭连接）。"""
    return _authenticate(websocket.headers, websocket.query_params)


def require_role(*roles: str):
    """角色门禁依赖工厂（HTTP）：require_role("admin") / require_role("admin", "tester")。

    v1.8 多角色语义：用户角色集合与所需角色交集非空即通过（包含任一）。
    """
    required = set(roles)
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not (set(user.roles) & required):
            raise HTTPException(status_code=403, detail=f"需要 {'/'.join(roles)} 角色")
        return user
    return checker


def require_role_ws(*roles: str):
    """角色门禁依赖工厂（WebSocket）。v1.8：用户角色集与所需角色交集非空即通过。"""
    required = set(roles)
    async def checker(user: CurrentUser = Depends(get_current_user_ws)) -> CurrentUser:
        if not (set(user.roles) & required):
            raise HTTPException(status_code=403, detail=f"需要 {'/'.join(roles)} 角色")
        return user
    return checker


async def optional_workspace(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> str:
    """非强制工作区解析：header > 用户默认 > 空串（不 403，执行触发等场景用）。"""
    name = unquote(request.headers.get("X-SG-Workspace", "")).strip()
    if not name:
        db_user = user_store.get_user(user.emp_no) or {}
        name = (db_user.get("default_workspace") or "").strip()
    return name


async def resolve_workspace(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> str:
    """解析请求工作区：X-SG-Workspace header（前端 encodeURIComponent 编码，此处 unquote 还原）
    > 用户默认工作区 > 403。

    非 admin 用户必须已被授权该工作区（workspace_grants）。
    """
    name = unquote(request.headers.get("X-SG-Workspace", "")).strip()
    if not name:
        db_user = user_store.get_user(user.emp_no) or {}
        name = (db_user.get("default_workspace") or "").strip()
    if not name:
        raise HTTPException(status_code=403, detail="请先选择工作区（顶部工作区选择器）")
    if not user.is_admin and not user_store.has_grant(user.emp_no, name):
        raise HTTPException(status_code=403, detail=f"未授权工作区: {name}")
    return name
