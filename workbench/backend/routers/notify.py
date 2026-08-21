"""通知配置 API：CRUD + 测试发送。

端点：
- GET    /api/notify/configs           — 列出全部通知配置
- POST   /api/notify/configs           — 创建通知配置
- PUT    /api/notify/configs/{id}      — 更新通知配置
- DELETE /api/notify/configs/{id}      — 删除通知配置
- POST   /api/notify/configs/{id}/test — 发送测试消息（J-2 实现 webhook 后生效）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role
from services import notify_config

router = APIRouter(prefix="/api/notify", tags=["notify"])


class NotifyConfigBody(BaseModel):
    name: str = ""
    channel: str = "feishu"  # dingtalk / feishu
    webhook_url: str = ""
    secret: str = ""
    mention_mobiles: str = ""
    events: list[str] = ["plan_failure", "vulnerability"]
    enabled: bool = True


class TestSendBody(BaseModel):
    event: str = "plan_failure"


@router.get("/configs")
def list_configs(user=Depends(require_role("admin", "tester"))):
    """列出全部通知配置（webhook_url/secret 脱敏）。"""
    return {"configs": notify_config.list_configs()}


@router.post("/configs")
def create_config(body: NotifyConfigBody, user=Depends(require_role("admin"))):
    """创建通知配置。webhook_url/secret 加密存储。"""
    try:
        return notify_config.create_config(body.model_dump(), created_by=user.emp_no)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/configs/{cid}")
def update_config(cid: str, body: NotifyConfigBody, user=Depends(require_role("admin"))):
    """更新通知配置。"""
    try:
        result = notify_config.update_config(cid, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"通知配置不存在: {cid}")
    return result


@router.delete("/configs/{cid}")
def delete_config(cid: str, user=Depends(require_role("admin"))):
    """删除通知配置。"""
    if not notify_config.delete_config(cid):
        raise HTTPException(status_code=404, detail=f"通知配置不存在: {cid}")
    return {"ok": True}


@router.post("/configs/{cid}/test")
async def test_send(cid: str, body: TestSendBody = None, user=Depends(require_role("admin", "tester"))):
    """发送测试消息。

    调用 send_notification 真实发送到配置的群聊。
    """
    config = notify_config.get_config(cid)
    if config is None:
        raise HTTPException(status_code=404, detail=f"通知配置不存在: {cid}")

    event = body.event if body else "plan_failure"
    test_payload = {
        "plan_name": "（测试计划）",
        "scenario_id": "TEST-001",
        "error": "这是一条测试消息，验证通知配置是否正常工作。",
        "run_at": "2026-07-29T00:00:00",
    }

    # J-2：调用真实 send_notification
    from pathlib import Path
    sg_root = Path(__file__).resolve().parent.parent.parent.parent
    from feedback.notify import send_notification
    ok = await send_notification(config, event, test_payload)

    return {
        "ok": ok,
        "config": {
            "id": config["id"],
            "name": config["name"],
            "channel": config["channel"],
            "events": config["events"],
            "enabled": config["enabled"],
        },
        "message": "发送成功" if ok else "发送失败（请检查 webhook URL 或网络连通性）",
    }
