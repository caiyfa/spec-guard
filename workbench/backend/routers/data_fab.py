"""数据制造 API（M08 §5.1，T-062）。

端点：
  POST /api/data-fab/fabricate   数据制造 Agent 编排入口（产物一律草稿态过三闸）

RBAC：tester+（数据制造是测试侧写操作）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role

router = APIRouter(prefix="/api/data-fab", tags=["data-fab"])


class FabricateBody(BaseModel):
    frs: list[str]                 # 目标 FR 锚点（缺口圈定）
    source_delta: str = ""         # 来源 delta（挂链）
    target: str = "IS-PREP"        # 产物前缀（默认数据准备实例）


@router.post("/fabricate", dependencies=[Depends(require_role("admin", "tester"))])
def fabricate(body: FabricateBody):
    """数据制造编排：复用判定 → 生成 IS-PREP 草稿（含 data_contract）→ 数据校验器。

    产物一律草稿态（write_draft 自动登记三闸 + gate2 自动校验），promote 必须三闸全过。
    """
    from services.auth import current_emp_no
    from services import data_fabrication, user_store

    if not body.frs:
        raise HTTPException(status_code=400, detail="frs 不能为空")
    try:
        result = data_fabrication.fabricate(
            frs=body.frs, source_delta=body.source_delta, target=body.target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据制造失败: {e}")
    try:
        user_store.audit(current_emp_no(), "data_fabricate",
                         f"{len(body.frs)} FR → 产出 {len(result['drafts'])} 草稿"
                         f"（delta={body.source_delta or '-'}）")
    except Exception:
        pass
    return result
