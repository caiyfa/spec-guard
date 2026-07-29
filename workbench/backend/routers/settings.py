"""设置 API：大模型配置读写 + 多模型管理 + 连通性探测。

端点：
- GET  /api/settings/llm-config       — 读取当前生效配置（向后兼容，返回默认模型）
- POST /api/settings/llm-config       — 保存配置（向后兼容）
- POST /api/settings/llm-config/probe — 探测 LLM 连通性
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


class LLMConfigBody(BaseModel):
    # 连接参数
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: str = "120"
    temperature: str = "0.7"
    # 模型能力限制
    max_context_tokens: str = ""
    max_output_tokens: str = ""
    # 思考/推理选项
    thinking_enabled: str = "false"
    reasoning_effort: str = ""


class ProbeBody(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 30


@router.get("/llm-config")
def get_llm_config(user=Depends(require_role("admin", "tester"))):
    """读取当前 LLM 配置（DB 值 + 环境变量状态 + 最终生效值）。"""
    db_configs = llm_config.get_all()
    resolved = llm_config.resolve_config()
    env_flags = llm_config.is_env_controlled()
    return {
        "config": resolved,
        "db_config": db_configs,
        "env_controlled": env_flags,
    }


@router.post("/llm-config")
def save_llm_config(body: LLMConfigBody, user=Depends(require_role("admin"))):
    """保存 LLM 配置到 DB（即时生效，LLMClient 下次请求自动加载）。

    保存前自动探测连通性，结果随响应返回。
    """
    # 自动探测连通性（使用提交值或回退到环境变量）
    resolved_base_url = body.base_url or os.environ.get("SG_LLM_BASE_URL", "")
    resolved_api_key = body.api_key or os.environ.get("SG_LLM_API_KEY", "")
    resolved_model = body.model or os.environ.get("SG_LLM_MODEL", "gpt-4o")

    probe_result = None
    if resolved_base_url and resolved_api_key:
        probe_result = llm_config.probe_connectivity(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model=resolved_model,
            timeout=15,
        )

    configs = {
        "base_url": body.base_url,
        "api_key": body.api_key,
        "model": body.model,
        "timeout": body.timeout,
        "temperature": body.temperature,
        "max_context_tokens": body.max_context_tokens,
        "max_output_tokens": body.max_output_tokens,
        "thinking_enabled": body.thinking_enabled,
        "reasoning_effort": body.reasoning_effort,
    }
    saved = llm_config.save(configs)
    resolved = llm_config.resolve_config()
    return {
        "ok": True,
        "config": resolved,
        "db_config": saved,
        "probe": probe_result,
    }


@router.post("/llm-config/probe")
def probe_llm(body: ProbeBody, user=Depends(require_role("admin", "tester"))):
    """探测 LLM 连通性：发一条简短消息验证配置是否可用。"""
    result = llm_config.probe_connectivity(
        base_url=body.base_url,
        api_key=body.api_key,
        model=body.model,
        timeout=body.timeout,
    )
    return result


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
    # 表单值优先，回退到 DB 值
    base_url = (body.base_url if body and body.base_url else m["base_url"])
    api_key = (body.api_key if body and body.api_key else m["api_key"])
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
