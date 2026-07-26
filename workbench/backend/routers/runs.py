"""执行控制 API：触发 / 终止 / 状态 / 历史 / WebSocket 实时流"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.runner import run_manager
from services.scenario_store import list_reports, get_report, get_case

router = APIRouter(prefix="/api/runs", tags=["runs"])


class TriggerBody(BaseModel):
    scope: str = "all"       # all / module / scenario / tag / engine_modes
    target: str = ""         # 场景ID / 模块路径 / 标签名
    env: str = "sit"         # 目标环境
    breakpoints: list[str] = []   # 断点场景 ID 列表
    strict_deps: bool = False     # 严格依赖模式（DRIFT/ORPHANED → BLOCKED）


@router.post("/trigger")
async def api_trigger(body: TriggerBody):
    """触发执行（支持断点）"""
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
