"""场景库质量看板 API（T-1035）。

端点：
  GET /api/scenario-quality/overview   全局统计 + 套件聚合 + 能力矩阵 + 场景明细（一次返回）

只读看板：三源确定性派生（场景 YAML × spec 锚点 × 断言证据），无落库无写操作。
RBAC：只读（admin/tester/product，对齐 coverage）。
"""

from fastapi import APIRouter, Depends, HTTPException
from services.auth import require_role

router = APIRouter(prefix="/api/scenario-quality", tags=["scenario-quality"])


@router.get("/overview", dependencies=[Depends(require_role("admin", "tester", "product"))])
def quality_overview(refresh: bool = False):
    """场景库质量全景（30s 缓存；refresh=1 强制重扫——单点刷新入口）。"""
    from services import scenario_quality as sq
    try:
        return sq.collect_quality(refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"场景库质量扫描失败: {e}") from e
