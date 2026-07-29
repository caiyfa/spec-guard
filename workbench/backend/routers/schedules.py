"""定时任务调度 API。

端点：
  GET    /api/schedules             列出定时任务（支持工作区过滤）
  POST   /api/schedules             创建定时任务
  GET    /api/schedules/{id}        获取单个任务
  PUT    /api/schedules/{id}        更新任务
  DELETE /api/schedules/{id}        删除任务
  POST   /api/schedules/{id}/run    手动触发一次执行
  GET    /api/schedules/plans/list  列出可用计划（供下拉选择）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import CurrentUser, get_current_user, require_role, resolve_workspace

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

from services import scheduler as sched_service


# ══════════════════════════════════════════════════════════
# 请求模型
# ══════════════════════════════════════════════════════════

class CreateJobBody(BaseModel):
    name: str
    plan_id: str
    cron: str
    notify_config_id: str = ""
    enabled: bool = True


class UpdateJobBody(BaseModel):
    name: str = ""
    plan_id: str = ""
    cron: str = ""
    notify_config_id: str = ""
    enabled: bool | None = None


# ══════════════════════════════════════════════════════════
# 端点
# ══════════════════════════════════════════════════════════

@router.get("")
def list_jobs(ws_name: str = Depends(resolve_workspace),
              user: CurrentUser = Depends(get_current_user)):
    """列出定时任务（按工作区隔离）。"""
    jobs = sched_service.list_jobs(workspace=ws_name)
    return {"jobs": jobs}


@router.post("", dependencies=[Depends(require_role("admin"))])
def create_job(body: CreateJobBody,
               user: CurrentUser = Depends(get_current_user),
               ws_name: str = Depends(resolve_workspace)):
    """创建定时任务（仅 admin）。"""
    try:
        job = sched_service.create_job(
            name=body.name,
            plan_id=body.plan_id,
            workspace=ws_name,
            cron=body.cron,
            notify_config_id=body.notify_config_id,
            created_by=user.emp_no,
            enabled=body.enabled,
        )
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/plans/list")
def list_plans(ws_name: str = Depends(resolve_workspace),
               user: CurrentUser = Depends(get_current_user)):
    """列出可用计划（供下拉选择）。"""
    from services import plan_store
    plans = plan_store.list_plans()
    return {"plans": [{"id": p["id"], "name": p["name"],
                        "scenario_count": p.get("scenario_count", 0)} for p in plans]}


@router.get("/{job_id}")
def get_job(job_id: str,
            ws_name: str = Depends(resolve_workspace),
            user: CurrentUser = Depends(get_current_user)):
    """获取单个定时任务。"""
    job = sched_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["workspace"] != ws_name:
        raise HTTPException(status_code=403, detail="任务不属于当前工作区")
    return job


@router.put("/{job_id}", dependencies=[Depends(require_role("admin"))])
def update_job(job_id: str, body: UpdateJobBody,
               ws_name: str = Depends(resolve_workspace)):
    """更新定时任务（仅 admin）。"""
    existing = sched_service.get_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="任务不存在")
    if existing["workspace"] != ws_name:
        raise HTTPException(status_code=403, detail="任务不属于当前工作区")

    try:
        job = sched_service.update_job(
            job_id=job_id,
            name=body.name,
            plan_id=body.plan_id,
            cron=body.cron,
            notify_config_id=body.notify_config_id,
            enabled=body.enabled,
        )
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{job_id}", dependencies=[Depends(require_role("admin"))])
def delete_job(job_id: str,
               ws_name: str = Depends(resolve_workspace)):
    """删除定时任务（仅 admin）。"""
    existing = sched_service.get_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="任务不存在")
    if existing["workspace"] != ws_name:
        raise HTTPException(status_code=403, detail="任务不属于当前工作区")

    if not sched_service.delete_job(job_id):
        raise HTTPException(status_code=500, detail="删除失败")
    return {"ok": True}


@router.post("/{job_id}/run")
async def trigger_job(job_id: str,
                      user: CurrentUser = Depends(require_role("admin", "tester")),
                      ws_name: str = Depends(resolve_workspace)):
    """手动触发一次执行（立即运行）。"""
    existing = sched_service.get_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="任务不存在")
    if existing["workspace"] != ws_name:
        raise HTTPException(status_code=403, detail="任务不属于当前工作区")

    result = await sched_service.trigger_job_now(job_id)
    return result
