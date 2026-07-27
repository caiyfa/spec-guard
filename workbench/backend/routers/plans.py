"""测试计划 API：CRUD + 按计划执行 + 计划历史"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import CurrentUser, optional_workspace, require_role
from services.plan_store import (
    list_plans, get_plan, save_plan, delete_plan,
    resolve_scenarios, list_plan_history, import_from_delta,
    import_preview, import_confirm,
    get_plan_working_copy, save_plan_working_copy, list_plan_working_copies,
)
from services.runner import run_manager
from services.covers_gate import check_covers_gate

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("")
def api_list_plans():
    """计划列表"""
    return list_plans()


@router.get("/{plan_id}")
def api_get_plan(plan_id: str):
    """计划详情（含解析后的场景列表）"""
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"计划 {plan_id} 不存在")
    return plan


class PlanBody(BaseModel):
    name: str = ""
    description: str = ""
    env: str = "sit"
    filter: dict = {}
    tags: list = []


@router.put("/{plan_id}", dependencies=[Depends(require_role("admin", "tester"))])
def api_save_plan(plan_id: str, body: PlanBody):
    """创建/更新计划"""
    return save_plan(plan_id, body.model_dump())


@router.delete("/{plan_id}", dependencies=[Depends(require_role("admin", "tester"))])
def api_delete_plan(plan_id: str):
    """删除计划"""
    if not delete_plan(plan_id):
        raise HTTPException(status_code=404, detail=f"计划 {plan_id} 不存在")
    return {"ok": True}


@router.post("/{plan_id}/run")
async def api_run_plan(plan_id: str,
                       user: CurrentUser = Depends(require_role("admin", "tester")),
                       workspace: str = Depends(optional_workspace)):
    """按计划执行（支持断点 + 多用户 FIFO 队列）

    与 runs/trigger 同一 covers 前置闸（计划驱动是主执行路径，不能成为闸口漏洞）。
    """
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"计划 {plan_id} 不存在")

    covers_errors = check_covers_gate()
    if covers_errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "covers 校验未通过，禁止触发执行", "errors": covers_errors},
        )

    scenario_ids = resolve_scenarios(plan)
    if not scenario_ids:
        raise HTTPException(status_code=400, detail="计划过滤条件未匹配到任何场景")

    breakpoints = plan.get("breakpoints") or []
    strict_deps = bool(plan.get("strict_deps"))
    if breakpoints:
        result = await run_manager.trigger_with_breakpoints(
            scenario_ids=scenario_ids,
            breakpoints=breakpoints,
            env=plan.get("env", "sit"),
            plan_id=plan_id,
            strict_deps=strict_deps,
            emp_no=user.emp_no,
            workspace=workspace,
        )
    else:
        target = " or ".join(scenario_ids)
        result = await run_manager.trigger(
            scope="scenario", target=target, env=plan.get("env", "sit"),
            plan_id=plan_id, strict_deps=strict_deps,
            emp_no=user.emp_no, workspace=workspace,
        )
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return {**result, "scenario_count": len(scenario_ids)}


class ImportConfirmBody(BaseModel):
    selected_files: list[str] = []


@router.get("/import-preview/{delta_code}")
def api_import_preview(delta_code: str):
    """导入预览：展示 delta 文件清单 + 格式校验 + 分类"""
    result = import_preview(delta_code)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/import-confirm/{delta_code}", dependencies=[Depends(require_role("admin", "tester"))])
def api_import_confirm(delta_code: str, body: ImportConfirmBody):
    """确认导入：创建工作副本 + 生成计划"""
    result = import_confirm(delta_code, body.selected_files)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/import/{delta_code}", dependencies=[Depends(require_role("admin", "tester"))])
def api_import_plan(delta_code: str):
    """从 spec delta 导入生成测试计划"""
    result = import_from_delta(delta_code)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/{plan_id}/working-copies")
def api_list_working_copies(plan_id: str):
    """列出计划的工作副本"""
    return list_plan_working_copies(plan_id)


@router.get("/{plan_id}/working-copies/{filename}")
def api_get_working_copy(plan_id: str, filename: str):
    """读取工作副本内容"""
    content = get_plan_working_copy(plan_id, filename)
    if content is None:
        raise HTTPException(status_code=404, detail=f"副本不存在: {filename}")
    return {"filename": filename, "content": content}


class WorkingCopyBody(BaseModel):
    content: str


@router.put("/{plan_id}/working-copies/{filename}", dependencies=[Depends(require_role("admin", "tester"))])
def api_save_working_copy(plan_id: str, filename: str, body: WorkingCopyBody):
    """保存工作副本（不影响源文件）"""
    if not save_plan_working_copy(plan_id, filename, body.content):
        raise HTTPException(status_code=404, detail=f"副本目录不存在")
    return {"ok": True}


@router.get("/{plan_id}/history")
def api_plan_history(plan_id: str, limit: int = 20):
    """计划的历史执行记录"""
    return list_plan_history(plan_id, limit=limit)
