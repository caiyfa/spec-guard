"""Spec 校验 API：delta 列表 / spec 校验 / testcase 校验 / 报告读取"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.spec_validator import (
    list_deltas, get_current_delta, run_spec_validation,
    read_validation_report, validate_test_cases,
)

router = APIRouter(prefix="/api/spec", tags=["spec-validation"])


@router.get("/deltas")
def api_list_deltas():
    """列出全部可用的 delta"""
    return {
        "current": get_current_delta(),
        "deltas": list_deltas(),
    }


class ValidateBody(BaseModel):
    delta: str = ""
    mode: str = "create"   # create / pre / post


@router.post("/validate")
def api_validate_spec(body: ValidateBody):
    """运行 spec 校验（verify_delta_merge.py）"""
    delta = body.delta or get_current_delta()
    if not delta:
        raise HTTPException(status_code=400, detail="未指定 delta 且 .current-delta 为空")
    return run_spec_validation(delta, body.mode)


@router.get("/report")
def api_read_report(path: str = ""):
    """读取校验报告 MD 内容"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少 path 参数")
    content = read_validation_report(path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {path}")
    return {"path": path, "content": content}


@router.get("/validate-testcases")
def api_validate_testcases():
    """校验全部测试 YAML 的格式合规性"""
    return validate_test_cases()
