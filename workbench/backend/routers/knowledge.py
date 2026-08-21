"""知识维护页 API（T-509 一页三区：词条 / 环境叙事 / 经验审核队列）。

端点：
  GET    /api/knowledge/glossary            读词典（词条 + 断链校验发现）
  PUT    /api/knowledge/glossary            保存词条（保存即 conformance 校验）
  GET    /api/knowledge/env                 环境叙事文件列表
  GET    /api/knowledge/env/{env}           读单个环境叙事（凭据红线预检）
  PUT    /api/knowledge/env/{env}           保存环境叙事（凭据红线拒绝）
  GET    /api/knowledge/experience          经验审核队列列表

纪律：写操作 RBAC（admin/tester）+ 审计留痕；词条/叙事按工作区/系统隔离。
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role, get_current_user
from services import user_store
from services import knowledge_service as ks

router = APIRouter(
    prefix="/api/knowledge", tags=["knowledge"],
    dependencies=[Depends(require_role("admin", "tester"))],
)

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class GlossaryBody(BaseModel):
    text: str


class EnvBody(BaseModel):
    text: str


class RateBody(BaseModel):
    rating: str  # up / down


def _emp(user) -> str:
    """取当前用户工号（审计留痕用）。"""
    return getattr(user, "emp_no", "") or getattr(user, "username", "") or ""


# ══════════════════════════════════════════════════════════
# 词条（L1 语义词典）
# ══════════════════════════════════════════════════════════

@router.get("/glossary")
async def get_glossary(user=Depends(get_current_user)):
    """读当前工作区词典：词条列表 + 断链校验发现（保存即校验的读侧）。"""
    try:
        return ks.load_glossary()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/glossary")
async def put_glossary(body: GlossaryBody, user=Depends(get_current_user)):
    """保存词条全文；保存即 conformance 校验（断链标红）；审计留痕。"""
    try:
        return ks.save_glossary(body.text, emp=_emp(user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════════════════
# 环境叙事（L2）
# ══════════════════════════════════════════════════════════

@router.get("/env")
async def list_env(user=Depends(get_current_user)):
    """列出当前系统的环境叙事文件（env.{env}.md）。"""
    try:
        return {"narratives": ks.list_env_narratives()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/env/{env}")
async def get_env(env: str, user=Depends(get_current_user)):
    """读单个环境叙事（含凭据红线预检发现）。"""
    try:
        return ks.load_env_narrative(env)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="环境叙事不存在")


@router.put("/env/{env}")
async def put_env(env: str, body: EnvBody, user=Depends(get_current_user)):
    """保存环境叙事；凭据红线：含凭据直接拒绝；审计留痕。"""
    try:
        return ks.save_env_narrative(env, body.text, emp=_emp(user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════════════════
# 经验审核队列（L3，T-510 落行后消费）
# ══════════════════════════════════════════════════════════

@router.get("/experience")
async def list_experience(user=Depends(get_current_user)):
    """经验库队列列表（{ws}/.specguard/experience/*.md）。"""
    try:
        return {"items": ks.list_experience_queue()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experience/{token}/rate")
async def rate_experience(token: str, body: RateBody, user=Depends(get_current_user)):
    """T-510：经验 👍/👎 反馈（rating ∈ up/down）；审计留痕。"""
    try:
        from services import experience_store
        from specstd.workspace import get_workspace_root
        root = get_workspace_root()
        if root is None:
            raise HTTPException(status_code=400, detail="无激活工作区")
        ok = experience_store.rate_experience(root, token, body.rating)
        if not ok:
            raise HTTPException(status_code=404, detail=f"经验条目不存在或 rating 非法: {token}")
        try:
            user_store.audit(_emp(user), "knowledge_rate", f"experience/{token}",
                             detail=f"rating={body.rating}")
        except Exception:
            pass
        return {"ok": True, "rating": body.rating}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
