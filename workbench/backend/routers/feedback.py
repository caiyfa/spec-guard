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

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role

# 反哺闭环整体对 tester+ 开放（viewer 无此菜单，后端同样拦截）
router = APIRouter(
    prefix="/api/feedback", tags=["feedback"],
    dependencies=[Depends(require_role("admin", "tester"))],
)

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

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


# ══════════════════════════════════════════════════════════
# M09 归因台账（T-063）：SPQ 建档/流转/查询/信息包装配
# ══════════════════════════════════════════════════════════

class CreateSpqBody(BaseModel):
    title: str
    run_id: str = ""
    scenario_id: str = ""
    fr_refs: list[str] = []
    suggestion_kind: str = ""      # Agent 建议（仅存档，不生效）
    decided_kind: str              # 人定性（生效值：product_defect/spec_question/environment）
    comment: str = ""


class SpqTransitionBody(BaseModel):
    status: str
    note: str = ""


class SyncInfoPackBody(BaseModel):
    iv_id: str                     # 目标面试 IV（如 IV-007）


@router.get("/spq")
def list_spq(status: str = "", fr: str = ""):
    """归因台账查询（含挂链字段；可按状态/FR 过滤）。"""
    ledger = _get_ledger()
    entries = ledger.list_entries(status or None)
    if fr:
        entries = [e for e in entries if fr in (e.get("fr_refs") or [])]
    return {"entries": entries}


@router.post("/spq")
def create_spq(body: CreateSpqBody):
    """人定性建档 SPQ（T-063）：留痕 decided_by/decided_at（当前用户）；

    suggestion_kind 仅存档（Agent 建议永不自动转 decided，铁律 1）；
    缺 run_id/fr_refs → linkage_warnings（挂链完整性，不阻断建档）。
    建档后自动尝试装配进匹配面试信息包（T-064 loop-back）。
    """
    from services import attribution_service
    from services.auth import current_emp_no
    ledger = _get_ledger()
    try:
        entry = attribution_service.create_spq(
            ledger, title=body.title, run_id=body.run_id,
            scenario_id=body.scenario_id, fr_refs=body.fr_refs,
            suggestion_kind=body.suggestion_kind,
            decided_kind=body.decided_kind, decided_by=current_emp_no(),
            comment=body.comment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # T-064：自动装配钩子（按 FR 相关性匹配进行中面试；无匹配静默）
    try:
        _auto_sync_info_pack(entry, body.fr_refs)
    except Exception:
        pass
    return entry


def _auto_sync_info_pack(entry: dict, fr_refs: list):
    """自动装配：按 fr_refs 与面试 baseline_refs 相关性匹配进行中面试 IV，注入 spq_feedback.yaml。

    fr_refs 为空时退化为第一个进行中面试（兼容无挂链建档）。
    """
    from specstd.workspace import specflow_dir
    from specstd.workspace import get_workspace_root
    ws = get_workspace_root()
    if not ws:
        return
    base = specflow_dir()
    iv_dir = base / "interviews"
    if not iv_dir.is_dir():
        return
    # 进行中的面试（iv 生命周期 interviewing/p0_cleared），读 topic.yaml 判定状态与 FR 集合
    from specflow.interview.topic import Topic
    want = set(fr_refs or [])
    matched, best = None, -1
    for d in sorted(iv_dir.iterdir()):
        if not d.is_dir():
            continue
        topic_path = d / "topic.yaml"
        if not topic_path.is_file():
            continue
        try:
            topic = Topic.from_yaml(topic_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if topic.status not in ("interviewing", "p0_cleared"):
            continue
        topic_frs = {r.fr for r in topic.baseline_refs}
        score = len(want & topic_frs) if want else 0
        if score > best:
            best = score
            matched = d.name
            if want and score == len(want):
                break  # 全命中即最优
    if not matched:
        return
    from services import attribution_service
    attribution_service.sync_spq_to_info_pack(
        entry["spq_id"], matched, pack_dir=base, ledger=_get_ledger())


@router.patch("/spq/{spq_id}")
def patch_spq(spq_id: str, body: SpqTransitionBody):
    """状态流转（非法迁移 → 409）。"""
    from services import attribution_service
    ledger = _get_ledger()
    try:
        return attribution_service.transition_spq(ledger, spq_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"台账条目不存在: {spq_id}")


@router.post("/spq/{spq_id}/sync-info-pack")
def sync_spq_info_pack(spq_id: str, body: SyncInfoPackBody):
    """手动补偿：装配指定 SPQ 进指定面试信息包（幂等）。"""
    from services import attribution_service
    from specstd.workspace import specflow_dir
    ledger = _get_ledger()
    try:
        result = attribution_service.sync_spq_to_info_pack(
            spq_id, body.iv_id, pack_dir=specflow_dir(), ledger=ledger)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"台账条目不存在: {spq_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"装配失败: {e}")
    return result


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
    return {"webhooks": reg.list_webhooks()}


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
