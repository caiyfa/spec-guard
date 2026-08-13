"""设置 API：多模型管理 + 连通性探测。

端点：
- GET  /api/settings/models           — 列出全部模型配置
- POST /api/settings/models           — 创建模型配置
- PUT  /api/settings/models/{id}      — 更新模型配置
- DELETE /api/settings/models/{id}    — 删除模型配置
- POST /api/settings/models/{id}/default — 设为默认
- POST /api/settings/models/{id}/probe   — 探测连通性
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role
from services import llm_config, model_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ProbeBody(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 30


# ══════════════════════════════════════════════════════════
# 多模型管理
# ══════════════════════════════════════════════════════════

class ModelBody(BaseModel):
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: str = "120"
    temperature: str = "0.7"
    max_context_tokens: str = ""
    max_output_tokens: str = ""
    thinking_enabled: str = "false"
    reasoning_effort: str = ""


@router.get("/models")
def list_models(user=Depends(require_role("admin", "tester"))):
    """列出全部模型配置。"""
    return {"models": model_config.list_models()}


@router.post("/models")
def create_model(body: ModelBody, user=Depends(require_role("admin"))):
    """创建模型配置。"""
    return model_config.create_model(body.model_dump())


@router.put("/models/{mid}")
def update_model(mid: str, body: ModelBody, user=Depends(require_role("admin"))):
    """更新模型配置。"""
    result = model_config.update_model(mid, body.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail=f"模型不存在: {mid}")
    return result


@router.delete("/models/{mid}")
def delete_model(mid: str, user=Depends(require_role("admin"))):
    """删除模型配置（不允许删除默认模型，除非是唯一模型）。"""
    if not model_config.delete_model(mid):
        raise HTTPException(status_code=409, detail="不允许删除默认模型（请先设置其他模型为默认）")
    return {"ok": True}


@router.post("/models/{mid}/default")
def set_default_model(mid: str, user=Depends(require_role("admin"))):
    """设为默认模型。"""
    result = model_config.set_default(mid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"模型不存在: {mid}")
    return result


class ModelProbeBody(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 30


@router.post("/models/{mid}/probe")
def probe_model(mid: str, body: ModelProbeBody = None, user=Depends(require_role("admin", "tester"))):
    """探测指定模型的连通性。

    优先使用请求体中的表单值（允许保存前测试），回退到数据库存储值。
    """
    m = model_config.get_model(mid)
    if m is None:
        raise HTTPException(status_code=404, detail=f"模型不存在: {mid}")
    # 表单值优先，回退到 DB 值（脱敏值含 *** 视为未填，回退 DB 真实 key）
    base_url = (body.base_url if body and body.base_url else m["base_url"])
    api_key = (body.api_key if body and body.api_key and "***" not in body.api_key else m["api_key"])
    model_name = (body.model if body and body.model else m["model"])
    timeout = (body.timeout if body and body.timeout else 30)
    return llm_config.probe_connectivity(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        timeout=timeout,
    )


class AuditBaselineBody(BaseModel):
    auto_update: bool


@router.get("/audit-baseline")
def get_audit_baseline(user=Depends(require_role("admin", "tester"))):
    """获取「审计完成自动更新 spec 签名基线」开关状态（K-007，默认手动）。"""
    from services import settings_store
    return {"auto_update": settings_store.audit_auto_update_baseline()}


@router.post("/audit-baseline")
def set_audit_baseline(body: AuditBaselineBody, user=Depends(require_role("admin"))):
    """设置「审计完成自动更新 spec 签名基线」开关（K-007，默认手动）。

    开启后，Agent 写审计报告成功时自动更新基线；关闭（默认）需手动调
    POST /api/workspace/mark-audited 更新基线。
    """
    from services import settings_store
    settings_store.set_bool(settings_store.KEY_AUDIT_AUTO_UPDATE_BASELINE, body.auto_update)
    return {"ok": True, "auto_update": body.auto_update}


class RunTimeoutBody(BaseModel):
    timeout_sec: int  # 秒；0 = 禁用看门狗


@router.get("/run-timeout")
def get_run_timeout(user=Depends(require_role("admin", "tester"))):
    """T-204：执行看门狗超时配置（秒，0=禁用；缺省回退环境变量 SG_RUN_TIMEOUT）。"""
    from services import settings_store
    raw = settings_store.get_setting("run_timeout_sec", "")
    if not raw:
        import os
        raw = os.environ.get("SG_RUN_TIMEOUT", "")
    try:
        val = int(float(raw or 0))
    except ValueError:
        val = 0
    return {"timeout_sec": val, "source": "settings" if settings_store.get_setting("run_timeout_sec", "") else "env"}


@router.post("/run-timeout")
def set_run_timeout(body: RunTimeoutBody, user=Depends(require_role("admin"))):
    """T-204：设置执行看门狗超时（0=禁用）。对后续触发的执行生效（无需重启）。"""
    from services import settings_store
    if body.timeout_sec < 0:
        raise HTTPException(status_code=400, detail="timeout_sec 必须 ≥ 0（0=禁用）")
    settings_store.set_setting("run_timeout_sec", str(body.timeout_sec))
    return {"ok": True, "timeout_sec": body.timeout_sec}
