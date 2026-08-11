"""覆盖缺口与场景生成 API（M07，T-060/T-061）。

端点：
  GET  /api/coverage/gaps                     三态缺口聚合（🔴 无覆盖 / 🟡 草稿待审 / 🟢 已覆盖）
  GET  /api/coverage/backlink/{fr_id}         FR 反向链接（只读派生）
  POST /api/coverage/next-batch               「生成下一批」批量草稿（只产草稿不产计划，铁律 6）

RBAC：gaps/backlink 只读（tester+）；next-batch 写（tester+）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role

router = APIRouter(prefix="/api/coverage", tags=["coverage"])


class NextBatchBody(BaseModel):
    module: str = ""               # 缺口模块（可空）
    frs: list[str]                 # 圈定 FR 集合（人确认后传入）
    source_delta: str = ""         # 来源 delta（挂链，如 extend-void-scope）


@router.get("/gaps", dependencies=[Depends(require_role("admin", "tester", "product"))])
def coverage_gaps(module: str = ""):
    """三态缺口聚合（M07 §4.1 结构：lanes / suggested_order / fingerprint）。"""
    from services import coverage_gaps as cg
    try:
        return cg.compute_coverage(module=module)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"覆盖聚合失败: {e}")


@router.get("/backlink/{fr_id}", dependencies=[Depends(require_role("admin", "tester", "product"))])
def coverage_backlink(fr_id: str):
    """FR 反向链接：场景 / 草稿 / 最近 run / deltas（只读派生，不落库不回写）。"""
    from services import coverage_gaps as cg
    return cg.backlink(fr_id)


@router.post("/next-batch", dependencies=[Depends(require_role("admin", "tester"))])
def coverage_next_batch(body: NextBatchBody):
    """「生成下一批」：按圈定 FR 集合批量产草稿骨架。

    全程确定性编排；产物全部走三闸通道；**不产生任何计划**（铁律 6）。
    flow/verify 由 Agent（generate-scenario skill）后续填充。
    """
    from services.auth import current_emp_no
    from services import coverage_gaps as cg, user_store

    if not body.frs:
        raise HTTPException(status_code=400, detail="frs 不能为空")
    try:
        result = cg.build_next_batch(frs=body.frs, source_delta=body.source_delta)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量生成失败: {e}")
    try:
        user_store.audit(current_emp_no(), "coverage_next_batch",
                         f"圈定 {len(body.frs)} FR → 产出 {len(result['produced'])} 草稿"
                         f"（delta={body.source_delta or '-'}）")
    except Exception:
        pass
    return result
