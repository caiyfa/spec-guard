"""菜单守卫中间件：按 API path 匹配菜单授权（前后端双控的后端侧）。

- 只处理 http scope；WebSocket 不拦（页面访问由前端路由守卫控制）
- 白名单：/api/health、/api/auth/*、/api/menus/me（登录必需通道）
- 绑定表：API 前缀 → menu_key（API 是代码定义的，归属关系代码声明；菜单树本身动态）
- 匹配两级：前两段精确优先（agent/audit → menu-audit），再第一段；未绑定放行
- 绑定值支持元组：共享前缀归属多个菜单页（如 /api/runs 同时服务测试执行与执行中心），任一授权即放行
- 菜单不存在 / visible=0 / 无授权 → 403
- token 缺失或解析失败 → 透传（认证职责在路由层 get_current_user，避免双重 401 语义差异）
- 保底：is_system 菜单对 admin 恒通过（rbac_store.user_has_menu 内实现）
"""
from __future__ import annotations

import json

from services import rbac_store, user_store
from services.auth import _validate_token

# 第一段前缀 → menu_key（T-996 菜单收缩后对齐；值为元组时任一授权即放行）
API_MENU_BINDINGS: dict[str, str | tuple[str, ...]] = {
    "scenarios": "menu-plans",
    "plans": "menu-plans",
    "runs": ("menu-run", "menu-history"),
    "executions": "menu-history",
    "schedules": "menu-history",
    "reference": ("menu-plans", "menu-system-config", "menu-settings"),  # T-1010：env-config 收编
    "spec": "menu-agent",
    "specflow": ("menu-agent", "menu-drafts"),
    "drafts": "menu-drafts",
    "agent": "menu-agent",
    "workspace": ("menu-agent", "menu-system-config"),  # T-1010：workspace 收编（menu-agent 公开保底顶栏全站可用）
    "knowledge": "menu-agent",
    "feedback": "menu-feedback",
    "notify": "menu-feedback",
    "settings": "menu-settings",
    "users": "menu-users",
    "menus": "menu-menu-manage",
    "roles": "menu-menu-manage",
    "graph": "menu-graph",
    "lineage": "menu-graph",
    "lifecycle": "menu-lifecycle",
    "coverage": "menu-lifecycle",
    "zentao": "menu-agent",
    "quality": "menu-dashboard",
    "systems": "menu-system-config",  # T-1010：系统包管理收编系统配置
    "feishu-pool": "menu-feishu-pool",
    "products": "menu-activity",
    "scenario-quality": "menu-scenario-quality",  # T-1035：场景库质量看板
    # data-fab 无前端消费方，保持未绑定放行（存量行为）
}

# 前两段精确前缀（优先于第一段）
API_MENU_BINDINGS_EXACT: dict[str, str] = {
    "agent/audit": "menu-audit",      # 实测 audit.py 前缀 /api/agent/audit
    "users/audit-log": "menu-audit",  # 管理操作审计并入审计日志页（双审计统一）
    "spec/push": "menu-agent",        # push 仅 AgentChat 页调用（specApi.pushBranch），归属 agent 而非合规校验
}

WHITELIST_PREFIXES = ("health", "auth")
WHITELIST_PATHS = ("/api/menus/me",)


def menu_keys_for_path(path: str) -> tuple[str, ...]:
    """两级匹配：前两段精确优先，再第一段；未绑定返回空元组。绑定值始终归一为元组。"""
    parts = path.strip("/").split("/")
    if not parts or parts[0] != "api" or len(parts) < 2:
        return ()
    two = "/".join(parts[1:3])
    bound = API_MENU_BINDINGS_EXACT.get(two) or API_MENU_BINDINGS.get(parts[1])
    if not bound:
        return ()
    return (bound,) if isinstance(bound, str) else bound


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
        menu_keys = menu_keys_for_path(path)
        if not menu_keys:
            await self.app(scope, receive, send)
            return
        # 候选键：存在且可见；全部缺失/隐藏 → 403
        candidates = [k for k in menu_keys
                      if (m := rbac_store.get_menu(k)) and m["visible"]]
        if not candidates:
            await self._deny(send, menu_keys[0])
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
        if not any(rbac_store.user_has_menu(roles, k) for k in candidates):
            await self._deny(send, candidates[0])
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
