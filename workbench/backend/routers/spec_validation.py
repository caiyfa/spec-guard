"""Spec 校验 API：delta 列表 / spec 校验 / testcase 校验 / 报告读取 / delta 文档写入"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role, resolve_workspace
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
    """运行 spec 合规校验（specstd.conformance 原生实现）"""
    delta = body.delta or get_current_delta()
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


class DeltaDocBody(BaseModel):
    filename: str
    content: str


class DeltaCommitBody(BaseModel):
    message: str = ""


@router.put("/changes/{delta_id}")
def api_write_delta_doc(
    delta_id: str,
    body: DeltaDocBody,
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """写入 delta 文档（方案 A：产品/管理员可写 changes/{delta}/ 下文件）。

    写前 .bak 备份 + 审计留痕 + 写后自动 conformance 校验；不代提交 git。
    冻结 delta（FREEZE.yaml 凭证存在）拒绝写入；基线/归档/草稿不可达。
    """
    from services.specflow.delta_doc_writer import write_delta_doc
    result = write_delta_doc(
        workspace=workspace, delta_id=delta_id,
        filename=body.filename, content=body.content,
        emp_no=user.emp_no,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=403, detail=result.get("error", "写入被拒绝"))
    return result


@router.post("/changes/{delta_id}/commit")
def api_commit_delta_changes(
    delta_id: str,
    body: DeltaCommitBody,
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """受限提交 changes/{delta}/ 起草区变更（git add + commit，不 push）。

    前置门禁：该 delta conformance 无 ERROR、未冻结；message 须 {type}: 前缀。
    提交停留在本地仓库，远端推送由人在 spec 仓库侧完成。
    """
    from services.specflow.delta_committer import commit_delta_changes
    result = commit_delta_changes(
        workspace=workspace, delta_id=delta_id,
        message=body.message, emp_no=user.emp_no,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=403, detail=result.get("error", "提交被拒绝"))
    return result
