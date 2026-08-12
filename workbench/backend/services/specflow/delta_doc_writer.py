"""delta_doc_writer — delta 文档写通道（方案 A）。

产品/管理员可写工作区 changes/{delta}/ 下文件（proposal.md / delta-spec.md /
delta.manifest.yaml / api-delta.yaml / delta-specs/ 等 delta 起草区文档），
写前 .bak 备份 + 审计留痕 + 写后自动 conformance 校验；**不代提交 git**
（落盘后由产品自行 commit，git 门禁不被绕过）。

只读红线（与 S8 open/ 只读面一致）：
- 冻结 delta（FREEZE.yaml 凭证存在）不可写——冻结产物是开放面唯一契约来源
- 基线 specs/、归档 archive/、私有草稿 drafts/ 一律不可达（路径守卫）

REST 与 MCP 共用本服务（与 draft_promote 同一模式）。
"""

import re
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import (  # noqa: E402
    get_context_emp_no,
    get_workspace_root,
    specflow_dir,
)

# delta 代号安全模式（防路径穿越：仅字母数字点横线）
_DELTA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# 禁止写入的文件（冻结凭证/备份文件本身）
_FORBIDDEN_NAMES = {"FREEZE.yaml", "FREEZE.yml"}


def _resolve_delta_dir(root: Path, delta_id: str) -> Path | None:
    """解析 changes/{delta_id} 目录（存在性 + 净化）。"""
    if not delta_id or not _DELTA_ID_RE.match(delta_id):
        return None
    d = (root / "changes" / delta_id).resolve()
    try:
        d.relative_to((root / "changes").resolve())
    except ValueError:
        return None
    return d if d.is_dir() else None


def _is_frozen(root: Path, delta_id: str, emp: str = "") -> bool:
    """冻结检查：spec 仓库 changes/ 侧或 .specflow 冻结凭证任一处存在即冻结。

    S5 freeze_gate 把 FREEZE.yaml 凭证落在 .specflow/{emp}/changes/{delta_id}/；
    工作区 changes/{delta_id}/FREEZE.yaml 为手工标记的等价物——任一存在即只读。
    """
    ws_mark = root / "changes" / delta_id / "FREEZE.yaml"
    if ws_mark.is_file():
        return True
    try:
        sf_mark = specflow_dir(emp) / "changes" / delta_id / "FREEZE.yaml"
        if sf_mark.is_file():
            return True
    except Exception:
        pass
    return False


def _guard_filename(delta_dir: Path, filename: str) -> Path | None:
    """文件名守卫：resolve 后必须位于 delta 目录内；禁止绝对路径/.. 越界。

    允许相对子路径（如 delta-specs/exp-tag.md）；禁止写入冻结凭证/备份本身。
    """
    if not filename or "\x00" in filename:
        return None
    if Path(filename).is_absolute():
        return None
    target = (delta_dir / filename).resolve()
    try:
        target.relative_to(delta_dir.resolve())
    except ValueError:
        return None
    if target.name in _FORBIDDEN_NAMES or target.name.endswith(".bak"):
        return None
    return target


def _run_delta_validation(root: Path, delta_id: str) -> dict:
    """写后 conformance 校验（复用 specstd 原生校验器，过滤该 delta findings）。"""
    try:
        from specstd.conformance import check_conformance
        report = check_conformance(root, root.name)
        findings = [
            f.to_dict() for f in report.findings
            if delta_id in f.path or delta_id in str(f.detail)
        ]
        return {
            "verdict": "PASS" if not [f for f in findings if f.get("level") == "ERROR"] else "REJECT",
            "findings": findings,
        }
    except Exception as e:
        return {"verdict": "ERROR", "findings": [], "error": str(e)}


def _audit(emp: str, action: str, target: str, detail: str = ""):
    """审计留痕（无用户上下文时跳过——MCP stdio 无 emp）。"""
    if not emp:
        return
    try:
        from services import user_store
        user_store.audit(emp, action, target, detail)
    except Exception:
        pass


def write_delta_doc(workspace: str = "", delta_id: str = "",
                    filename: str = "", content: str = "",
                    emp_no: str = "") -> dict:
    """写入 delta 文档（changes/{delta_id}/ 限定）。

    Args:
        workspace: 工作区名（空 = 当前激活）
        delta_id: delta 代号（如 0817）
        filename: delta 目录内相对路径（如 delta-spec.md / delta-specs/exp-tag.md）
        content: 文件全文
        emp_no: 操作人工号（空 = 取请求上下文，再空 = 跳过审计）

    Returns:
        {"ok": bool, "error": str?, "path": str, "backup": bool,
         "size": int, "validation": {verdict, findings}}
    """
    emp = emp_no or get_context_emp_no() or ""

    if not delta_id or not filename:
        return {"ok": False, "error": "缺少 delta_id 或 filename 参数"}
    if content is None:
        return {"ok": False, "error": "缺少 content 参数"}

    root = get_workspace_root(workspace)
    if root is None:
        return {"ok": False, "error": "工作区不可用（未激活或不存在）"}

    delta_dir = _resolve_delta_dir(root, delta_id)
    if delta_dir is None:
        return {"ok": False, "error": f"delta {delta_id!r} 不存在或代号非法"}

    if _is_frozen(root, delta_id, emp):
        return {"ok": False, "error": f"delta {delta_id!r} 已冻结（只读冻结态）——"
                "冻结产物是开放面唯一契约来源，如需修改请走新 delta 或人工解冻"}

    target = _guard_filename(delta_dir, filename)
    if target is None:
        return {"ok": False, "error": f"路径越界或非法: {filename!r}（仅允许 changes/{delta_id}/ 内文件）"}

    # 写前备份（对齐 draft_writer .bak 惯例）
    backed = False
    if target.is_file():
        try:
            target.with_name(target.name + ".bak").write_text(
                target.read_text(encoding="utf-8"), encoding="utf-8")
            backed = True
        except OSError as e:
            return {"ok": False, "error": f"备份失败，未写入: {e}"}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"写入失败: {e}"}

    _audit(emp, "write_delta_doc",
           f"changes/{delta_id}/{filename}",
           detail=f"size={len(content)} backup={backed}")

    validation = _run_delta_validation(root, delta_id)

    return {
        "ok": True,
        "path": f"changes/{delta_id}/{filename}",
        "backup": backed,
        "size": len(content),
        "validation": validation,
        "note": "已落盘但未代提交 git——请在工作区 spec 仓库自行 commit（git 门禁不被绕过）",
    }
