"""Spec 校验 API：delta 列表 / spec 校验 / testcase 校验 / 报告读取 / delta 文档写入"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role, resolve_workspace
from services.spec_validator import (
    list_deltas, get_current_delta, run_spec_validation,
    read_validation_report, validate_test_cases,
)
from services.specflow.delta_committer import commit_delta_changes, push_delta
from services.specflow import rebase_resolver
from services import git_config

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


@router.post("/push")
def api_push_delta(
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """推送当前分支未推送提交到远端（git push）。

    分支级操作（不依赖 delta_id）：推送 @{u}..HEAD 全部本地提交。
    使用用户配置的 git token（加密存储的 HTTPS PAT）注入认证。
    """
    token = git_config.get_decrypted_token(user.emp_no)
    result = push_delta(
        workspace=workspace, delta_id="",
        token=token, emp_no=user.emp_no,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "推送被拒绝"))
    return result


# ══════════════════════════════════════════════════════════
# rebase 中断界面化恢复（检测 → 冲突展示 → 三选解决 → 完成/放弃）
# ══════════════════════════════════════════════════════════

@router.get("/rebase/status")
def api_rebase_status(
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """rebase 中断状态 + 冲突文件列表（含每文件冲突段数）。"""
    return rebase_resolver.get_rebase_status(workspace)


@router.get("/rebase/conflict")
def api_rebase_conflict(
    path: str,
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """读取冲突文件的冲突段（ours/theirs 分段展示）。"""
    result = rebase_resolver.get_conflict_detail(workspace, path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "读取失败"))
    return result


class RebaseResolveBody(BaseModel):
    path: str
    resolution: str            # ours / theirs / smart / custom
    merged_content: str = ""   # resolution=custom 时的合并内容


@router.post("/rebase/resolve")
def api_rebase_resolve(
    body: RebaseResolveBody,
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """解决单个文件冲突（ours/theirs/smart/custom）并 git add。"""
    result = rebase_resolver.resolve_conflict(
        workspace=workspace, path=body.path, resolution=body.resolution,
        merged_content=body.merged_content, emp_no=user.emp_no,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "解决失败"))
    return result


@router.post("/rebase/abort")
def api_rebase_abort(
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """放弃 rebase（git rebase --abort）：回到 rebase 前状态。"""
    result = rebase_resolver.abort_rebase(workspace, emp_no=user.emp_no)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
    return result


@router.post("/rebase/continue")
def api_rebase_continue(
    user=Depends(require_role("admin", "product")),
    workspace: str = Depends(resolve_workspace),
):
    """完成 rebase（git rebase --continue）：前置校验无未解决冲突。"""
    result = rebase_resolver.continue_rebase(workspace, emp_no=user.emp_no)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
    return result
