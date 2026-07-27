"""认证 API（M6）：当前用户 / 登录配置 / mock 登录 / 登出。

端点：
  GET  /api/auth/config       认证配置（auth_mode + UAC 登录/登出地址，前端跳转用）
  GET  /api/auth/me           当前登录用户信息
  POST /api/auth/mock-login   mock 模式登录（仅 SG_AUTH_MODE=mock）
  POST /api/auth/logout       登出（审计；UAC 登出由前端跳转完成）
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.auth import (
    SG_AUTH_MODE, SG_UAC_BASE, CurrentUser,
    get_current_user, issue_mock_token, uac_login_url, uac_logout_url,
)
from services import user_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def auth_config():
    """前端登录页配置（无需登录）。"""
    return {
        "auth_mode": SG_AUTH_MODE,
        "uac_base": SG_UAC_BASE,
        "uac_logout_url": uac_logout_url(),
        # redirectURL 由前端按当前地址拼接
    }


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    """当前登录用户信息。"""
    db_user = user_store.get_user(user.emp_no) or {}
    return {
        "emp_no": user.emp_no,
        "name": user.name,
        "role": user.role,
        "default_workspace": db_user.get("default_workspace", ""),
        "auth_mode": SG_AUTH_MODE,
    }


class MockLoginBody(BaseModel):
    emp_no: str
    name: str = ""


@router.post("/mock-login")
def mock_login(body: MockLoginBody):
    """mock 模式登录（开发/测试降级通道；生产 SG_AUTH_MODE=uac 时返回 403）。"""
    if not body.emp_no.strip():
        return {"ok": False, "error": "emp_no 不能为空"}
    token = issue_mock_token(body.emp_no.strip(), body.name.strip())
    user_store.audit(body.emp_no.strip(), "login", "", "mock")
    user = user_store.get_user(body.emp_no.strip())
    return {"ok": True, "token": token, "user": user}


@router.post("/logout")
def logout(user: CurrentUser = Depends(get_current_user)):
    """登出（审计；前端负责清 token 并跳 UAC 登出页）。"""
    user_store.audit(user.emp_no, "logout")
    return {"ok": True, "uac_logout_url": uac_logout_url()}
