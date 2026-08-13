"""delta_committer — delta 文档受限提交（git add + commit，不 push）。

与 write_delta_doc 配套的闭环动作：把 changes/{delta_id}/ 起草区变更提交到
工作区 git 仓库。受限语义（与方案 A 同一哲学）：

- 范围受限：仅 `git add changes/{delta_id}/`（含 delta-specs/ 等子目录），
  基线 specs/、归档 archive/ 不在 add 范围；.bak 备份与 FREEZE.yaml 排除
- 门禁前置：该 delta conformance 校验无 ERROR 才允许提交（fail-closed）；
  冻结 delta 拒绝提交（只读契约来源）
- 不 push：提交停留在本地仓库，远端推送始终由人在仓库侧完成
- message 规范：默认自动生成 `feat: delta {代号} 文档更新`；自定义 message
  必须以 {type}: 前缀（feat/fix/docs/refactor/test/chore），防注入且合规
- 审计留痕：commit 动作登记 audit_log

REST（POST /api/spec/changes/{delta}/commit）与 MCP 共用本服务。
"""

import re
import subprocess
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import get_context_emp_no, get_workspace_root  # noqa: E402

from workbench.backend.services.specflow.delta_doc_writer import (  # noqa: E402
    _is_frozen,
    _resolve_delta_dir,
)

# commit message 类型前缀（对齐 AGENTS.md commit 规范）
_MSG_TYPE_RE = re.compile(r"^(feat|fix|docs|refactor|test|chore):\s+\S+")

# git add 排除项（git pathspec exclude 语法，list 参数直接传无需 shell 引号）：
# .bak 备份（write_delta_doc 产物，不入库）+ 冻结凭证
_ADD_EXCLUDE = [":(exclude)*.bak", ":(exclude)FREEZE.yaml"]


def _is_git_repo(root: Path) -> bool:
    """工作区是否为 git 仓库（.git 目录存在）。

    用 .git 存在性而非 source_type：被测系统工作区可能 register 为 local 型
    但目录本身是 git 克隆——提交能力以仓库事实为准。
    """
    return (root / ".git").exists()


def _git_run(args: list, cwd: Path, timeout: int = 30) -> tuple[int, str]:
    """执行 git 命令（cwd=root，UTF-8 解码防中文乱码）。返回 (returncode, 合并输出)。"""
    try:
        proc = subprocess.run(
            args, cwd=str(cwd),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "git 命令超时"
    except FileNotFoundError:
        return -1, "git 命令不可用，请确认已安装 Git"
    except Exception as e:
        return -1, f"git 命令异常: {e}"


def _delta_validation_errors(root: Path, delta_id: str) -> list:
    """该 delta conformance 校验的 ERROR findings（空 = 可提交）。"""
    try:
        from specstd.conformance import check_conformance
        report = check_conformance(root, root.name)
        return [
            f.to_dict() for f in report.findings
            if f.level == "ERROR" and (delta_id in f.path or delta_id in str(f.detail))
        ]
    except Exception:
        return [{"rule": "?", "message": "conformance 校验执行异常"}]


def _audit(emp: str, action: str, target: str, detail: str = ""):
    """审计留痕（无用户上下文时跳过——MCP stdio 无 emp）。"""
    if not emp:
        return
    try:
        from services import user_store
        user_store.audit(emp, action, target, detail)
    except Exception:
        pass


def commit_delta_changes(workspace: str = "", delta_id: str = "",
                         message: str = "", emp_no: str = "") -> dict:
    """受限提交 changes/{delta_id}/ 起草区变更（git add + commit，不 push）。

    emp_no 非空时读取用户配置的 git 身份覆盖提交者（-c user.name/email），
    不修改仓库级 git config。

    Args:
        workspace: 工作区名（空 = 当前激活）
        delta_id: delta 代号（如 0817）
        message: commit message（空 = 自动生成；自定义须以 {type}: 前缀）
        emp_no: 操作人工号（空 = 取请求上下文，再空 = 跳过审计与身份覆盖）

    Returns:
        {"ok": bool, "error"?: str, "commit"?: str, "files"?: list[str],
         "message": str, "note": str}
    """
    emp = emp_no or get_context_emp_no() or ""

    if not delta_id:
        return {"ok": False, "error": "缺少 delta_id 参数"}

    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用（未激活或不存在）"}

    delta_dir = _resolve_delta_dir(root, delta_id)
    if delta_dir is None:
        return {"ok": False, "error": f"delta {delta_id!r} 不存在或代号非法"}

    if not _is_git_repo(root):
        return {"ok": False, "error": f"工作区 {root.name!r} 不是 git 仓库，无法提交"}

    if _is_frozen(root, delta_id, emp):
        return {"ok": False, "error": f"delta {delta_id!r} 已冻结（只读契约来源）——拒绝提交"}

    # 门禁：conformance 该 delta 无 ERROR（fail-closed）
    errors = _delta_validation_errors(root, delta_id)
    if errors:
        return {"ok": False, "error": "conformance 校验未通过，拒绝提交",
                "validation_errors": errors[:10]}

    # message 校验：自定义须合规前缀；空则自动生成
    if message and not _MSG_TYPE_RE.match(message):
        return {"ok": False, "error": "commit message 必须以 {type}: 前缀开头"
                "（feat/fix/docs/refactor/test/chore），且不能为空描述"}
    msg = message or f"feat: delta {delta_id} 文档更新（SpecGuard 受限提交）"

    # git status 预检：delta 目录内是否有变更（无变更不提交）
    code, out = _git_run(
        ["git", "status", "--porcelain", "--", f"changes/{delta_id}/"], root)
    if code != 0:
        return {"ok": False, "error": f"git status 失败: {out[:300]}"}
    changed_lines = [ln for ln in out.splitlines() if ln.strip()]
    if not changed_lines:
        return {"ok": False, "error": f"changes/{delta_id}/ 下无变更可提交"}

    # git add（路径限定 delta 目录 + 排除 .bak/FREEZE.yaml）
    code, out = _git_run(
        ["git", "add", "--", f"changes/{delta_id}/"] + _ADD_EXCLUDE, root)
    if code != 0:
        return {"ok": False, "error": f"git add 失败: {out[:300]}"}

    # 再次确认 add 后暂存区有内容（排除项可能清空 add 结果）
    code, staged = _git_run(
        ["git", "diff", "--cached", "--name-only", "--", f"changes/{delta_id}/"], root)
    if code != 0 or not staged.strip():
        return {"ok": False, "error": "暂存区无 changes/{delta_id}/ 内容"
                "（全部变更可能都是 .bak/排除项）"}

    # 读取用户 git 身份覆盖，不修改仓库级 config
    identity_args = []
    if emp:
        try:
            from services import git_config as _gc
            cfg = _gc.get_git_config(emp)
            if cfg.get("name"):
                identity_args.extend(["-c", f"user.name={cfg['name']}"])
            if cfg.get("email"):
                identity_args.extend(["-c", f"user.email={cfg['email']}"])
        except Exception:
            pass

    # commit（带身份覆盖）
    commit_cmd = ["git"] + identity_args + ["commit", "-m", msg]
    code, out = _git_run(commit_cmd, root)
    if code != 0:
        return {"ok": False, "error": f"git commit 失败: {out[:300]}"}

    files = [ln.strip() for ln in staged.splitlines() if ln.strip()]
    _audit(emp, "commit_delta_changes", f"changes/{delta_id}/",
           detail=f"files={len(files)} message={msg}")

    note = "已本地提交"
    has_push_token = False
    if emp:
        try:
            from services import git_config as _gc
            cfg = _gc.get_git_config(emp)
            has_push_token = cfg.get("has_token", False)
        except Exception:
            pass
    if has_push_token:
        note += "，可推送远端（🚀）"
    else:
        note += "，未 push——远端推送请在 spec 仓库侧手动执行"

    return {
        "ok": True,
        "commit": out,
        "files": files,
        "message": msg,
        "note": note,
        "can_push": has_push_token,
    }


def push_delta(workspace: str = "", delta_id: str = "",
               token: str = "", emp_no: str = "") -> dict:
    """推送当前分支未推送提交到远端（git push）。

    分支级操作（不依赖 delta_id）：推送 @{u}..HEAD 之间的全部本地提交。
    使用 HTTPS PAT token 注入认证（git credential.helper 临时注入，不修改
    remote URL 与 credential 配置）。前置 pull --rebase --autostash 防冲突。

    Args:
        workspace: 工作区名（空 = 当前激活）
        delta_id: 可选，仅用于审计记录（不传不校验）
        token: HTTPS Personal Access Token（git_config 解码后传入）
        emp_no: 操作人工号（审计）

    Returns:
        {"ok": bool, "error"?: str, "output"?: str, "note": str,
         "ahead"?: int, "commits"?: list}
    """
    emp = emp_no or get_context_emp_no() or ""

    if not token:
        return {"ok": False, "error": "未配置 git token——请在系统设置＞Git 配置中设置 HTTPS PAT"}

    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用（未激活或不存在）"}

    if not _is_git_repo(root):
        return {"ok": False, "error": f"工作区 {root.name!r} 不是 git 仓库，无法推送"}

    # 获取远端 URL 判断协议
    code, remote_url = _git_run(["git", "remote", "get-url", "origin"], root)
    if code != 0:
        return {"ok": False, "error": f"获取远端地址失败: {remote_url[:200]}"}
    url_stripped = remote_url.strip()
    if url_stripped.startswith("git@") or url_stripped.startswith("ssh://"):
        return {"ok": False, "error": "远端为 SSH 协议，不支持 PAT token。请改用 HTTPS remote 或配置 SSH key"}

    # 检查未推送提交（@{u}..HEAD）
    code, unpushed_log = _git_run(
        ["git", "log", "--oneline", "@{u}..HEAD"], root)
    if code != 0:
        # 无上游分支或首次推送
        unpushed_log = ""
    unpushed_lines = [ln for ln in unpushed_log.splitlines() if ln.strip()]
    if not unpushed_lines:
        return {"ok": False, "error": "当前分支无未推送提交（全部已同步远端）", "ahead": 0}

    # git pull --rebase 先拉远端变更防冲突
    code, out = _git_run(["git", "pull", "--rebase", "--autostash"], root, timeout=60)
    if code != 0:
        return {"ok": False, "error": f"git pull --rebase 失败，请先手动解决冲突: {out[:300]}"}

    # git push：用 credential.helper 临时注入 token（不修改 remote URL / credential 配置）
    helper_script = f"!f() {{ echo username=token; echo password={token}; }}; f"
    code, out = _git_run(
        ["git", "-c", f"credential.helper={helper_script}", "push"], root, timeout=60)
    if code != 0:
        return {"ok": False, "error": f"git push 失败: {out[:500]}"}

    _audit(emp, "push_delta", f"changes/{delta_id}/" if delta_id else "branch",
           detail=f"ahead={len(unpushed_lines)} remote: {url_stripped}")

    return {
        "ok": True,
        "output": out,
        "note": f"已推送 {len(unpushed_lines)} 个提交到远端",
        "ahead": len(unpushed_lines),
        "commits": unpushed_lines,
    }
