"""执行控制 API：触发 / 终止 / 状态 / 历史 / WebSocket 实时流

触发前校验 covers 关联（M3 验收：covers 校验未通过禁止触发执行）。
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.auth import (
    CurrentUser, get_current_user, get_current_user_ws, optional_workspace, require_role,
)
from services import user_store
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
    prep_only: bool = False           # K-046 轻量执行：只跑上游环境准备
    skip_upstream_verify: bool = False  # K-046 轻量执行：上游只跑 flow 不断言
    # 注意：covers 校验不可由客户端跳过（V10 修复）——engine_modes 由服务端按 scope 判定豁免


@router.post("/trigger")
async def api_trigger(body: TriggerBody,
                      user: CurrentUser = Depends(require_role("admin", "tester")),
                      workspace: str = Depends(optional_workspace)):
    """触发执行（支持断点 + 多用户 FIFO 队列）

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
            emp_no=user.emp_no,
            workspace=workspace,
        )
    else:
        result = await run_manager.trigger(scope=body.scope, target=body.target, env=body.env,
                                           strict_deps=body.strict_deps,
                                           emp_no=user.emp_no, workspace=workspace,
                                           prep_only=body.prep_only,
                                           skip_upstream_verify=body.skip_upstream_verify)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


def _check_run_owner(user: CurrentUser):
    """M8：resume/abort 仅触发人本人或 admin 可操作。"""
    owner = run_manager.current_emp_no
    if owner and owner != user.emp_no and not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"当前执行由 {owner} 触发，仅本人或管理员可操作")


@router.post("/resume")
async def api_resume(user: CurrentUser = Depends(require_role("admin", "tester"))):
    """断点放行（仅触发人本人或 admin）"""
    _check_run_owner(user)
    result = await run_manager.resume()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.post("/abort")
async def api_abort(user: CurrentUser = Depends(require_role("admin", "tester"))):
    """终止当前执行（仅触发人本人或 admin）"""
    _check_run_owner(user)
    result = await run_manager.abort()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.delete("/queue/{item_id}")
def api_cancel_queued(item_id: int, user: CurrentUser = Depends(get_current_user)):
    """取消排队项（本人或 admin；M8）。"""
    row = user_store.get_run_queue_item(item_id)
    if not row or row["status"] != "queued":
        raise HTTPException(status_code=404, detail="排队项不存在或已开始执行")
    if row["emp_no"] != user.emp_no and not user.is_admin:
        raise HTTPException(status_code=403, detail="仅本人或管理员可取消排队")
    user_store.update_run_queue(item_id, "cancelled", finished=True)
    user_store.audit(user.emp_no, "cancel_queued", str(item_id))
    return {"ok": True}


@router.get("/status", dependencies=[Depends(get_current_user)])
def api_status():
    """当前执行状态"""
    return run_manager.get_status()


@router.get("/history", dependencies=[Depends(get_current_user)])
def api_history(limit: int = 20):
    """历史运行列表"""
    return list_reports(limit=limit)


@router.get("/{run_id}", dependencies=[Depends(get_current_user)])
def api_get_run(run_id: str):
    """单次运行详情（run.json）"""
    data = get_report(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")
    return data


@router.get("/{run_id}/cases/{case_file:path}", dependencies=[Depends(get_current_user)])
def api_get_case(run_id: str, case_file: str):
    """单场景详情 JSON"""
    data = get_case(run_id, case_file)
    if data is None:
        raise HTTPException(status_code=404, detail=f"用例 {case_file} 不存在")
    return data


@router.websocket("/stream")
async def ws_stream(ws: WebSocket, _user: CurrentUser = Depends(get_current_user_ws)):
    """WebSocket 实时执行流（WS 专用认证依赖；token 经 query 参数传入）"""
    await run_manager.subscribe(ws)
    try:
        while True:
            # 保持连接，接收客户端心跳
            await ws.receive_text()
    except WebSocketDisconnect:
        run_manager.unsubscribe(ws)


# covers 闸实现已抽取至 services/covers_gate.py（runs 与 plans 共用）
