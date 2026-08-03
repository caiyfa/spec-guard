"""lifecycle 路由 — 单元测试生命周期监控（K-xxx）。

聚合台账投影层（ledger_store）回答：
1. 全部测试当前状态（草稿待评审/更新中/已入库/已废弃）+ 执行摘要
2. 单条测试的完整生命周期时间线（草稿→入库→执行→失败→修复闭环）
"""

from fastapi import APIRouter, HTTPException

from services import lifecycle

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


@router.get("/scenarios")
def api_lifecycle_list():
    """全部测试的生命周期行（状态 + 执行摘要 + 闭环统计）。"""
    try:
        return lifecycle.list_lifecycle()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生命周期聚合失败: {e}")


@router.get("/scenarios/{scenario_id}")
def api_lifecycle_detail(scenario_id: str):
    """单条测试：时间线 + 执行历史。"""
    try:
        detail = lifecycle.scenario_detail(scenario_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生命周期查询失败: {e}")
    if not detail.get("timeline") and not detail.get("runs") and not detail.get("status"):
        raise HTTPException(status_code=404, detail=f"场景不存在或台账为空: {scenario_id}")
    return detail
