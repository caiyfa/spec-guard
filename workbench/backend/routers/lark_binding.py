"""lark_binding.py — T-703：飞书绑定 REST 端点。

供前端 LarkBinding 页面消费，底层认证逻辑复用 lark_auth 的 do_status/do_login/do_logout。

端点：
  GET    /api/settings/lark/status     — 绑定状态（bound/identity/scopes）
  POST   /api/settings/lark/login      — 发起授权（返回 verification_url）
  POST   /api/settings/lark/logout     — 解绑
  GET    /api/settings/lark/scopes     — 已授权 scope 详细清单
"""

from fastapi import APIRouter, Depends
from services.auth import get_current_user, CurrentUser
from mcp_server.tools.lark_auth import do_status, do_login, do_logout

router = APIRouter(prefix="/api/settings/lark", tags=["lark"])


@router.get("/status")
def lark_status(user: CurrentUser = Depends(get_current_user)):
    """当前用户飞书绑定状态。"""
    result = do_status(user.emp_no)
    return result


@router.post("/login")
def lark_login(scope: str = "", user: CurrentUser = Depends(get_current_user)):
    """发起飞书两阶段授权。"""
    result = do_login(user.emp_no, scope)
    return result


@router.post("/logout")
def lark_logout(user: CurrentUser = Depends(get_current_user)):
    """解绑飞书账号。"""
    result = do_logout(user.emp_no)
    return result


@router.get("/scopes")
def lark_scopes(user: CurrentUser = Depends(get_current_user)):
    """已授权 scope 清单。"""
    status = do_status(user.emp_no)
    return {"scopes": status.get("scopes", []), "bound": status.get("bound", False)}