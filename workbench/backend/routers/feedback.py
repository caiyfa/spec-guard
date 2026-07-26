"""反哺闭环 API：台账管理 + 飞书通知配置 + 事件推送。

端点：
  GET    /api/feedback/ledger           列出台账条目
  POST   /api/feedback/ledger            创建台账条目
  POST   /api/feedback/ledger/{spq_id}/transition  状态流转
  GET    /api/feedback/notify            列出 webhook 配置
  POST   /api/feedback/notify            注册 webhook
  DELETE /api/feedback/notify/{wid}       注销 webhook
  POST   /api/feedback/notify/send       发送通知
"""

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from feedback.ledger import FeedbackLedger
from feedback.notify import NotifyRegistry

FEEDBACK_DIR = SG_ROOT / "feedback"
LEDGER_PATH = FEEDBACK_DIR / "ledger.json"
REGISTRY_PATH = FEEDBACK_DIR / "registry.json"


def _get_ledger():
    return FeedbackLedger(LEDGER_PATH)


def _get_registry():
    return NotifyRegistry(REGISTRY_PATH)


# ══════════════════════════════════════════════════════════
# 台账管理
# ══════════════════════════════════════════════════════════

class CreateLedgerBody(BaseModel):
    title: str
    source: str = "loop_b"
    scenario_id: str = ""
    detail: str = ""


class TransitionBody(BaseModel):
    status: str  # pending / in_progress / closed


@router.get("/ledger")
def list_ledger(status: str = ""):
    """列出台账条目（可按状态过滤）。"""
    ledger = _get_ledger()
    return {"entries": ledger.list_entries(status or None)}


@router.post("/ledger")
def create_ledger(body: CreateLedgerBody):
    """创建台账条目。"""
    ledger = _get_ledger()
    try:
        entry = ledger.create(body.title, body.source, body.scenario_id, body.detail)
        return entry
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ledger/{spq_id}/transition")
def transition_ledger(spq_id: str, body: TransitionBody):
    """状态流转。"""
    ledger = _get_ledger()
    try:
        return ledger.transition(spq_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"台账条目不存在: {spq_id}")


# ══════════════════════════════════════════════════════════
# 通知配置
# ══════════════════════════════════════════════════════════

class RegisterWebhookBody(BaseModel):
    system: str
    scenario_pattern: str
    url: str
    events: list[str] = ["fail", "drift", "skip"]


class SendNotifyBody(BaseModel):
    system: str
    scenario_id: str
    event: str
    verdict: str
    conclusion: str
    report_link: str = ""


@router.get("/notify")
def list_webhooks():
    """列出 webhook 配置（掩码 URL）。"""
    reg = _get_registry()
    return {"webhooks": reg.list()}


@router.post("/notify")
def register_webhook(body: RegisterWebhookBody):
    """注册 webhook（URL 须过 SSRF 校验）。"""
    reg = _get_registry()
    try:
        entry = reg.register(body.system, body.scenario_pattern, body.url, body.events)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 返回时掩码 URL
    entry.pop("url", None)
    return entry


@router.delete("/notify/{webhook_id}")
def unregister_webhook(webhook_id: str):
    """注销 webhook。"""
    reg = _get_registry()
    if not reg.unregister(webhook_id):
        raise HTTPException(status_code=404, detail=f"webhook 不存在: {webhook_id}")
    return {"ok": True}


@router.post("/notify/send")
def send_notification(body: SendNotifyBody):
    """发送通知（仅出站，消息只含 ID/结论/链接）。"""
    reg = _get_registry()
    results = reg.send_notification(
        body.system, body.scenario_id, body.event,
        body.verdict, body.conclusion, body.report_link,
    )
    return {"results": results, "sent": len(results)}


@router.get("/receipts")
def list_receipts(limit: int = 50):
    """送达回执记录（receipts.jsonl 尾部，最新的在前）。"""
    receipts_path = FEEDBACK_DIR / "receipts.jsonl"
    if not receipts_path.is_file():
        return {"receipts": []}
    import json
    lines = receipts_path.read_text(encoding="utf-8").splitlines()
    receipts = []
    for line in reversed(lines[-limit:]):
        line = line.strip()
        if line:
            try:
                receipts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"receipts": receipts}
