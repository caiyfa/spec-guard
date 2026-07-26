"""执行控制 API：触发 / 终止 / 状态 / 历史 / WebSocket 实时流

触发前校验 covers 关联（M3 验收：covers 校验未通过禁止触发执行）。
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.runner import run_manager
from services.scenario_store import list_reports, get_report, get_case

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
    skip_covers_check: bool = False  # 跳过 covers 校验（engine_modes 用）


@router.post("/trigger")
async def api_trigger(body: TriggerBody):
    """触发执行（支持断点）

    covers 校验前置闸：未通过禁止触发（skip_covers_check=True 可跳过）。
    """
    # covers 校验前置闸
    if not body.skip_covers_check and body.scope != "engine_modes":
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


def _check_covers() -> list[dict]:
    """检查全部场景的 covers 是否可解析为有效 FR ID。

    返回 covers 错误列表（空列表表示全部通过）。
    """
    try:
        from specstd.workspace import get_active_workspace
        from specstd.anchors import scan_anchors, resolve_covers
        from specstd.conformance import check_covers

        ws = get_active_workspace()
        if not ws:
            return []  # 无激活工作区时不阻止执行

        anchors = scan_anchors(ws.root)
        if not anchors:
            return []  # 无锚点时不阻止（可能是新工作区未导入 spec）

        scenarios_root = SG_ROOT / "scenarios"
        findings = check_covers(anchors, scenarios_root)
        errors = [f.to_dict() for f in findings if f.level == "ERROR"]
        return errors
    except Exception:
        return []  # 校验异常时不阻止执行（容错）
