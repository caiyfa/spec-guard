"""agent_skills.py — Skill 注册表查询 REST API（T-080）。

前缀 /api/agent/skills，全角色可读。
"""

from fastapi import APIRouter, Depends, HTTPException
from services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/agent", tags=["agent"],
                   dependencies=[Depends(get_current_user)])


@router.get("/skills")
def list_skills(
    user: CurrentUser = Depends(get_current_user),
):
    """技能清单：name/version/description/author/depends_tools/source。"""
    from agent.skill_loader import list_skills_metadata
    return {"skills": list_skills_metadata()}


@router.get("/skills/{name}")
def get_skill(
    name: str,
    user: CurrentUser = Depends(get_current_user),
):
    """单技能元数据详情。"""
    from agent.skill_loader import get_skill_metadata
    meta = get_skill_metadata(name)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"技能不存在: {name}")
    return {"skill": meta}