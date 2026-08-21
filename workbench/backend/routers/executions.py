"""执行台账查询 API：GET /api/executions（场景 × 执行 × 全量结果绑定记录）。

数据源为 services.execution_index（文件真相源 + SQLite 投影 + 文件降级），
响应结构与 MCP 工具 list_executions 一致。
"""
from pathlib import Path

from fastapi import APIRouter, Depends

from services.auth import CurrentUser, get_current_user

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from services import execution_index  # noqa: E402
from specstd.workspace import reports_dir  # noqa: E402

router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("")
async def api_list_executions(scenario_id: str = "", run_id: str = "",
                              verdict: str = "", limit: int = 10,
                              user: CurrentUser = Depends(get_current_user)):
    """查询执行台账（全量含 PASS，最新在前；可按场景/任务号/结果过滤）。"""
    try:
        root = reports_dir()
    except Exception:
        root = SG_ROOT / "reports"
    entries = execution_index.query_executions(root, scenario_id, run_id, verdict, limit)
    return {"ok": True, "count": len(entries), "executions": entries}
