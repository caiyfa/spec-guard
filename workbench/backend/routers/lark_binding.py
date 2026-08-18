"""lark_binding.py — T-703：飞书绑定 REST 端点。

供前端 LarkBinding 页面消费，底层认证逻辑复用 lark_auth 的 do_status/do_login/do_logout。

端点：
  GET    /api/settings/lark/status     — 绑定状态（bound/identity/scopes）
  POST   /api/settings/lark/login      — 发起授权（返回 verification_url）
  POST   /api/settings/lark/logout     — 解绑
  GET    /api/settings/lark/scopes     — 已授权 scope 详细清单
"""

from fastapi import APIRouter, Body, Depends
from services.auth import CurrentUser, get_current_user

from mcp_server.tools.lark_auth import do_login, do_login_complete, do_logout, do_status

router = APIRouter(prefix="/api/settings/lark", tags=["lark"])


@router.get("/status")
def lark_status(user: CurrentUser = Depends(get_current_user)):
    """当前用户飞书绑定状态。

    T-942 补丁：do_status 内部仅兑 ValueError，OSError 等会 500 致前端
    authStatus=null、授权块全分支不渲染（用户实锄按钮消失）——此处全量
    兑底返回 bound=False（前端永远拿到 200，授权入口恒在）。
    """
    try:
        return do_status(user.emp_no)
    except Exception as e:   # noqa: BLE001 状态查询失败不阻断授权入口
        return {"bound": False, "identity": "", "identity_name": "",
                "open_id": "", "scopes": [], "error": str(e)[:200]}


@router.post("/login")
def lark_login(scope: str = "", user: CurrentUser = Depends(get_current_user)):
    """发起飞书两阶段授权。"""
    result = do_login(user.emp_no, scope)
    return result


@router.post("/complete")
def lark_complete(payload: dict = Body(...), user: CurrentUser = Depends(get_current_user)):
    """device flow 收尾：用户扫码后用 device_code 完成授权。"""
    device_code = (payload or {}).get("device_code", "")
    result = do_login_complete(user.emp_no, device_code)
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
