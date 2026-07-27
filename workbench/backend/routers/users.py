"""用户与工作区授权管理 API（M6/M7）。

端点：
  GET    /api/users                          用户列表（admin）
  PUT    /api/users/{emp_no}/role            改角色（admin）
  GET    /api/users/grants                   授权列表（admin 全量 / 普通用户仅自己）
  POST   /api/users/{emp_no}/grants          授权工作区（admin）
  DELETE /api/users/{emp_no}/grants/{ws}     撤销授权（admin）
  PUT    /api/users/me/default-workspace     设个人默认工作区（登录即可，限授权范围）
  GET    /api/users/audit-log                审计日志（admin）
"""

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/users", tags=["users"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from services.auth import CurrentUser, get_current_user, require_role  # noqa: E402
from services import user_store  # noqa: E402
from specstd.workspace import get_workspace  # noqa: E402


@router.get("")
def list_all_users(admin: CurrentUser = Depends(require_role("admin"))):
    return {"users": user_store.list_users()}


class RoleBody(BaseModel):
    role: str  # admin / tester / viewer


@router.put("/{emp_no}/role")
def change_role(emp_no: str, body: RoleBody,
                admin: CurrentUser = Depends(require_role("admin"))):
    try:
        ok = user_store.set_role(emp_no, body.role, admin.emp_no)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"用户不存在: {emp_no}（需其先登录一次）")
    return {"ok": True}


@router.get("/grants")
def list_grants(user: CurrentUser = Depends(get_current_user)):
    """授权列表：admin 见全量，其他角色仅见自己的。"""
    if user.is_admin:
        return {"grants": user_store.list_grants()}
    return {"grants": user_store.list_grants(emp_no=user.emp_no)}


class GrantBody(BaseModel):
    workspace_name: str


@router.post("/{emp_no}/grants")
def grant(emp_no: str, body: GrantBody,
          admin: CurrentUser = Depends(require_role("admin"))):
    if not get_workspace(body.workspace_name):
        raise HTTPException(status_code=404, detail=f"工作区未注册: {body.workspace_name}")
    if not user_store.get_user(emp_no):
        raise HTTPException(status_code=404, detail=f"用户不存在: {emp_no}（需其先登录一次）")
    user_store.grant_workspace(body.workspace_name, emp_no, admin.emp_no)
    return {"ok": True}


@router.delete("/{emp_no}/grants/{workspace_name}")
def revoke(emp_no: str, workspace_name: str,
           admin: CurrentUser = Depends(require_role("admin"))):
    if not user_store.revoke_workspace(workspace_name, emp_no, admin.emp_no):
        raise HTTPException(status_code=404, detail="授权记录不存在")
    return {"ok": True}


class DefaultWsBody(BaseModel):
    workspace_name: str


@router.put("/me/default-workspace")
def set_default_workspace(body: DefaultWsBody,
                          user: CurrentUser = Depends(get_current_user)):
    """设个人默认工作区（限自己授权范围内的，admin 不限）。"""
    name = body.workspace_name.strip()
    if name and not get_workspace(name):
        raise HTTPException(status_code=404, detail=f"工作区未注册: {name}")
    if name and not user.is_admin and not user_store.has_grant(user.emp_no, name):
        raise HTTPException(status_code=403, detail=f"未授权工作区: {name}")
    user_store.set_default_workspace(user.emp_no, name)
    return {"ok": True, "default_workspace": name}


@router.get("/audit-log")
def audit_log(limit: int = 100, admin: CurrentUser = Depends(require_role("admin"))):
    return {"entries": user_store.list_audit(limit)}
