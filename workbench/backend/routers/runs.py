"""执行控制 API：触发 / 终止 / 状态 / 历史 / WebSocket 实时流

触发前校验 covers 关联（M3 验收：covers 校验未通过禁止触发执行）。
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.runner import run_manager
from services.scenario_store import list_reports, get_report, get_case
from services.covers_gate import check_covers_gate as _check_covers

router = APIRouter(prefix="/api/runs", tags=["runs"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))


class TriggerBody(BaseModel):
    scope: str = "all"       # all / module / scenario / tag / engine_modes
    target: str = ""         # 场景ID / 模块路径 / 标签名
    env: str = "sit"         # 目标环境
    breakpoints: list[str] = []   # 断点场景 ID 列表
    strict_deps: bool = False     # 严格依赖模式（DRIFT/ORPHANED → BLOCKED）
    # 注意：covers 校验不可由客户端跳过（V10 修复）——engine_modes 由服务端按 scope 判定豁免


@router.post("/trigger")
async def api_trigger(body: TriggerBody):
    """触发执行（支持断点）

    covers 校验前置闸：未通过禁止触发（仅 engine_modes 豁免，由服务端判定）。
    """
    # covers 校验前置闸（V10 修复：仅 engine_modes 由服务端豁免，客户端无法绕过；
    # 与 plans 执行入口共用 services.covers_gate）
    if body.scope != "engine_modes":
        covers_errors = _check_covers()
        if covers_errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "covers 校验未通过，禁止触发执行", "errors": covers_errors},
            )

    if body.breakpoints:
        # 有断点 → 分段执行
        scenario_ids = body.target.split(" or ") if body.target else []
        result = await run_manager.trigger_with_breakpoints(
            scenario_ids=scenario_ids,
            breakpoints=body.breakpoints,
            env=body.env,
            strict_deps=body.strict_deps,
        )
    else:
        result = await run_manager.trigger(scope=body.scope, target=body.target, env=body.env,
                                           strict_deps=body.strict_deps)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.post("/resume")
async def api_resume():
    """断点放行"""
    result = await run_manager.resume()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.post("/abort")
async def api_abort():
    """终止当前执行"""
    result = await run_manager.abort()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.get("/status")
def api_status():
    """当前执行状态"""
    return run_manager.get_status()


@router.get("/history")
def api_history(limit: int = 20):
    """历史运行列表"""
    return list_reports(limit=limit)


@router.get("/{run_id}")
def api_get_run(run_id: str):
    """单次运行详情（run.json）"""
    data = get_report(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")
    return data


@router.get("/{run_id}/cases/{case_file:path}")
def api_get_case(run_id: str, case_file: str):
    """单场景详情 JSON"""
    data = get_case(run_id, case_file)
    if data is None:
        raise HTTPException(status_code=404, detail=f"用例 {case_file} 不存在")
    return data


@router.websocket("/stream")
async def ws_stream(ws: WebSocket):
    """WebSocket 实时执行流"""
    await run_manager.subscribe(ws)
    try:
        while True:
            # 保持连接，接收客户端心跳
            await ws.receive_text()
    except WebSocketDisconnect:
        run_manager.unsubscribe(ws)


# covers 闸实现已抽取至 services/covers_gate.py（runs 与 plans 共用）
