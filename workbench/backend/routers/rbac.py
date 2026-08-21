"""菜单 / 角色 / 授权管理 API（RBAC）。

端点全部经 MenuGuardMiddleware 绑定 menu-menu-manage（除 /api/menus/me 白名单，
该端点登录即可，供侧边栏渲染）。
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["rbac"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from services import rbac_store  # noqa: E402
from services.auth import CurrentUser, get_current_user  # noqa: E402


# ── 菜单 ──

@router.get("/menus/me")
def my_menus(user: CurrentUser = Depends(get_current_user)):
    """当前用户可见菜单树（侧边栏渲染；白名单放行，认证由本依赖完成）。"""
    return {"groups": rbac_store.menus_for_user(user.roles)}


@router.get("/menus")
def list_menus(user: CurrentUser = Depends(get_current_user)):
    return {"menus": rbac_store.list_menus()}


class MenuBody(BaseModel):
    menu_key: str = ""
    label: str
    icon: str = ""
    path: str = ""
    parent_key: str = ""
    sort: int = 0
    visible: bool = True


@router.post("/menus")
def create_menu(body: MenuBody, user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.create_menu(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.put("/menus/{menu_key}")
def update_menu(menu_key: str, body: MenuBody,
                user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.update_menu(menu_key, body.model_dump(exclude={"menu_key"}))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.delete("/menus/{menu_key}")
def delete_menu(menu_key: str, user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.delete_menu(menu_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# ── 角色 ──

class RoleBody(BaseModel):
    role_key: str = ""
    label: str
    sort: int = 0


@router.get("/roles")
def list_roles(user: CurrentUser = Depends(get_current_user)):
    return {"roles": rbac_store.list_roles()}


@router.post("/roles")
def create_role(body: RoleBody, user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.create_role(body.role_key, body.label, body.sort)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.put("/roles/{role_key}")
def update_role(role_key: str, body: RoleBody,
                user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.update_role(role_key, {"label": body.label, "sort": body.sort})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.delete("/roles/{role_key}")
def delete_role(role_key: str, user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.delete_role(role_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


class RoleMenusBody(BaseModel):
    menu_keys: list[str]


@router.get("/roles/{role_key}/menus")
def get_role_menus(role_key: str, user: CurrentUser = Depends(get_current_user)):
    """查询角色已授权菜单（角色授权页加载用）。"""
    return {"menu_keys": rbac_store.list_role_menus(role_key)}


@router.put("/roles/{role_key}/menus")
def set_role_menus(role_key: str, body: RoleMenusBody,
                   user: CurrentUser = Depends(get_current_user)):
    try:
        rbac_store.set_role_menus(role_key, body.menu_keys)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
