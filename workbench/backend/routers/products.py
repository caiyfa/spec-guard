"""产出反查 API（T-1000 F3）：产物 → 会话/工号/时间/FR 的反查接口。

端点：
  GET /api/products/by-session/{sid}  某会话产出了什么
  GET /api/products/mine              我的产出（本人查本人，非 admin 可用）
  GET /api/products/trace             产物溯源（这草稿/场景是哪次会话产的）
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user
from sg_core import product_index

router = APIRouter(prefix="/api/products", tags=["products"],
                   dependencies=[Depends(get_current_user)])


@router.get("/by-session/{sid}")
def api_by_session(sid: str, user: CurrentUser = Depends(get_current_user)):
    """某会话的产出清单（登录可查——会话产物是工作区共享过程产物）。"""
    return {"products": product_index.by_session(sid), "session_id": sid}


@router.get("/mine")
def api_mine(emp: str = "", type: str = "", from_: str = "", limit: int = 100,
             user: CurrentUser = Depends(get_current_user)):
    """我的产出。本人查本人非 admin 可用；查他人须 admin（越权 403）。"""
    target = emp or user.emp_no
    if target != user.emp_no and not user.is_admin:
        raise HTTPException(status_code=403, detail=f"无权查看他人产出: {target}")
    return {"products": product_index.by_emp(target, product_type=type,
                                             date_from=from_, limit=limit),
            "emp_no": target}


@router.get("/trace")
def api_trace(path: str, user: CurrentUser = Depends(get_current_user)):
    """产物溯源：按产物路径反查全部产出记录（会话/工号/时间线）。"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少 path 参数")
    return {"records": product_index.trace(path), "path": path}
