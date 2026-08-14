"""菜单守卫中间件：按 API path 匹配菜单授权（前后端双控的后端侧）。

- 只处理 http scope；WebSocket 不拦（页面访问由前端路由守卫控制）
- 白名单：/api/health、/api/auth/*、/api/menus/me（登录必需通道）
- 绑定表：API 前缀 → menu_key（API 是代码定义的，归属关系代码声明；菜单树本身动态）
- 匹配两级：前两段精确优先（agent/audit → menu-audit），再第一段；未绑定放行
- 菜单不存在 / visible=0 / 无授权 → 403
- token 缺失或解析失败 → 透传（认证职责在路由层 get_current_user，避免双重 401 语义差异）
- 保底：is_system 菜单对 admin 恒通过（rbac_store.user_has_menu 内实现）
"""
from __future__ import annotations

import json

from services import rbac_store, user_store
from services.auth import _validate_token

# 第一段前缀 → menu_key（实测 32 个 router prefix 核对结果）
API_MENU_BINDINGS: dict[str, str] = {
    "scenarios": "menu-plans",
    "plans": "menu-plans",
    "runs": "menu-run",
    "executions": "menu-run",
    "schedules": "menu-schedules",
    "history": "menu-history",
    "attribution": "menu-attribution",
    "reference": "menu-plans",
    "spec": "menu-spec",
    "specflow": "menu-spec",
    "drafts": "menu-drafts",
    "agent": "menu-agent",
    "workspace": "menu-workspace",
    "knowledge": "menu-knowledge",
    "feedback": "menu-feedback",
    "notify": "menu-notify",
    "settings": "menu-settings",
    "users": "menu-users",
    "menus": "menu-menu-manage",
    "roles": "menu-menu-manage",
    "graph": "menu-graph",
    "lineage": "menu-lineage",
    "lifecycle": "menu-lifecycle",
    "coverage": "menu-coverage",
    "zentao": "menu-zentao",
    "materials": "menu-materials",
    "scores": "menu-scores",
    "quality": "menu-quality",
    # feishu-pool / data-fab 无对应菜单，暂放行（设计文档注明待核对）
}

# 前两段精确前缀（优先于第一段）
API_MENU_BINDINGS_EXACT: dict[str, str] = {
    "agent/audit": "menu-audit",  # 实测 audit.py 前缀 /api/agent/audit
    "spec/push": "menu-agent",    # push 仅 AgentChat 页调用（specApi.pushBranch），归属 agent 而非合规校验
}

WHITELIST_PREFIXES = ("health", "auth")
WHITELIST_PATHS = ("/api/menus/me",)


def menu_key_for_path(path: str) -> str | None:
    """两级匹配：前两段精确优先，再第一段；未绑定返回 None。"""
    parts = path.strip("/").split("/")
    if not parts or parts[0] != "api" or len(parts) < 2:
        return None
    two = "/".join(parts[1:3])
    if two in API_MENU_BINDINGS_EXACT:
        return API_MENU_BINDINGS_EXACT[two]
    return API_MENU_BINDINGS.get(parts[1])


def _is_whitelisted(path: str) -> bool:
    if path in WHITELIST_PATHS:
        return True
    parts = path.strip("/").split("/")
    return len(parts) >= 2 and parts[1] in WHITELIST_PREFIXES


def _extract_bearer_token(scope) -> str:
    """从 ASGI scope headers 提取 Bearer token（ASGI 规范 header 名小写，
    auth._extract_token 期望 "Authorization" 大写键，此处内联提取避免大小写歧义）。"""
    for k, v in (scope.get("headers") or []):
        if k.decode("latin-1").lower() == "authorization":
            val = v.decode("latin-1")
            if val.startswith("Bearer "):
                return val[7:].strip()
            return ""
    return ""


class MenuGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if not path.startswith("/api/") or _is_whitelisted(path):
            await self.app(scope, receive, send)
            return
        menu_key = menu_key_for_path(path)
        if not menu_key:
            await self.app(scope, receive, send)
            return
        menu = rbac_store.get_menu(menu_key)
        if not menu or not menu["visible"]:
            await self._deny(send, menu_key)
            return
        # 认证：失败透传（路由层负责 401）
        token = _extract_bearer_token(scope)
        if not token:
            await self.app(scope, receive, send)
            return
        try:
            emp_no, _ = _validate_token(token)
        except Exception:
            await self.app(scope, receive, send)
            return
        user = user_store.get_user(emp_no) or {}
        roles = user.get("roles") or []
        if not rbac_store.user_has_menu(roles, menu_key):
            await self._deny(send, menu_key)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send, menu_key: str = ""):
        """403 响应：明确缺失的菜单授权（label + key + 开通路径），避免空泛提示。"""
        if menu_key:
            menu = rbac_store.get_menu(menu_key)
            label = menu["label"] if menu else menu_key
            detail = (f"无权限: 需要「{label}」（{menu_key}）菜单授权，"
                      f"请联系管理员在「菜单管理 → 角色授权」中开通")
        else:
            detail = "无权限访问，请联系管理员开通"
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
