"""工作区管理 + Spec 文档中心 API。

端点：
  GET    /api/workspace/list            列出工作区
  POST   /api/workspace/register-local  注册本地工作区
  POST   /api/workspace/register-git    注册 git 工作区
  POST   /api/workspace/activate        激活工作区
  DELETE /api/workspace/{name}          注销工作区
  POST   /api/workspace/conformance     合规校验
  POST   /api/workspace/pull            拉取更新
  GET    /api/workspace/spec-files      Spec 文件列表
  GET    /api/workspace/read-file       读取文件
  GET    /api/workspace/active          获取当前激活工作区
"""

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.workspace import (
    list_workspaces, get_workspace, get_active_workspace,
    register_local, register_git, set_active, unregister,
    pull, run_conformance, safe_resolve,
)
from services.auth import (  # noqa: E402
    CurrentUser, get_current_user, require_role, resolve_workspace,
)
from services import user_store  # noqa: E402


# ══════════════════════════════════════════════════════════
# 请求模型
# ══════════════════════════════════════════════════════════

class RegisterLocalBody(BaseModel):
    name: str
    path: str
    system: str = "tdm"
    activate: bool = True
    # 注意：不接受 run_conformance 客户端参数——接入即门禁，合规校验由服务端强制执行（V2 修复）


class RegisterGitBody(BaseModel):
    name: str
    url: str
    system: str = "tdm"
    branch: str = "main"
    activate: bool = True
    # 同上：合规校验不可被客户端跳过（V2 修复）


class ActivateBody(BaseModel):
    name: str


class ConformanceBody(BaseModel):
    name: str = ""


class PullBody(BaseModel):
    name: str


# ══════════════════════════════════════════════════════════
# 工作区管理
# ══════════════════════════════════════════════════════════

@router.get("/list")
def api_list_workspaces(user: CurrentUser = Depends(get_current_user)):
    """列出工作区：admin 见全部；其他角色仅见已授权的。"""
    workspaces = list_workspaces()
    if not user.is_admin:
        granted = {g["workspace_name"] for g in user_store.list_grants(emp_no=user.emp_no)}
        workspaces = [w for w in workspaces if w.name in granted]
    db_user = user_store.get_user(user.emp_no) or {}
    return {
        "workspaces": [w.to_dict() for w in workspaces],
        "active": get_active_workspace().name if get_active_workspace() else "",
        "my_default": db_user.get("default_workspace", ""),
    }


@router.get("/active")
def api_get_active():
    """获取当前激活的工作区。"""
    ws = get_active_workspace()
    if not ws:
        return {"active": None}
    return {"active": ws.to_dict()}


@router.post("/register-local")
def api_register_local(body: RegisterLocalBody,
                       admin: CurrentUser = Depends(require_role("admin"))):
    """注册本地文件夹工作区（合规校验强制执行，任一 ERROR 拒绝接入）。"""
    result = register_local(body.name, body.path, body.system,
                            activate=body.activate, run_conformance=True)
    if result.get("ok"):
        user_store.audit(admin.emp_no, "register_workspace", body.name, "local")
    return result


@router.post("/register-git")
def api_register_git(body: RegisterGitBody,
                     admin: CurrentUser = Depends(require_role("admin"))):
    """注册 git 工作区（克隆仓库，合规校验强制执行）。"""
    result = register_git(body.name, body.url, body.system, body.branch,
                          activate=body.activate, run_conformance=True)
    if result.get("ok"):
        user_store.audit(admin.emp_no, "register_workspace", body.name, "git")
    return result


@router.post("/activate", dependencies=[Depends(require_role("admin"))])
def api_activate(body: ActivateBody):
    """【遗留·仅 admin】设置全局激活工作区（MCP stdio POC 模式用；
    多用户 Web 模式用个人默认工作区 + X-SG-Workspace header，不走此接口）。"""
    if not set_active(body.name):
        raise HTTPException(status_code=404, detail=f"工作区不存在: {body.name}")
    return {"ok": True, "active": body.name}


@router.delete("/{name}")
def api_unregister(name: str, admin: CurrentUser = Depends(require_role("admin"))):
    """注销工作区。"""
    if not unregister(name):
        raise HTTPException(status_code=404, detail=f"工作区不存在: {name}")
    user_store.audit(admin.emp_no, "unregister_workspace", name)
    return {"ok": True}


@router.post("/conformance", dependencies=[Depends(require_role("admin"))])
def api_conformance(body: ConformanceBody):
    """执行合规校验。"""
    report = run_conformance(body.name or None)
    return report.to_dict()


@router.post("/pull", dependencies=[Depends(require_role("admin"))])
def api_pull(body: PullBody):
    """拉取 git 工作区更新，记录 pulled_at 时间戳（供 H-2 路由信号）。"""
    result = pull(body.name)
    # H-5: 返回 pulled_at（供前端展示和路由信号确认）
    if result.get("ok"):
        info = get_workspace(body.name)
        if info:
            result["pulled_at"] = info.pulled_at
    return result


# ══════════════════════════════════════════════════════════
# H-5: 漏洞管理（闭环衔接）
# ══════════════════════════════════════════════════════════

@router.get("/vulnerabilities")
def api_list_vulnerabilities(status: str = "",
                             user: CurrentUser = Depends(require_role("admin", "tester"))):
    """列出漏洞台账条目（可按状态过滤）+ 统计摘要。"""
    from feedback.ledger import FeedbackLedger
    ledger = FeedbackLedger(SG_ROOT / "feedback" / "ledger.json")
    vulns = ledger.list_vulnerabilities(status or None)
    summary = ledger.get_vulnerability_summary()
    return {"vulnerabilities": vulns, "summary": summary}


class CloseVulnerabilityBody(BaseModel):
    note: str = ""


@router.post("/vulnerabilities/{spq_id}/close")
def api_close_vulnerability(spq_id: str, body: CloseVulnerabilityBody,
                            user: CurrentUser = Depends(require_role("admin", "tester"))):
    """关闭漏洞（Agent 重新审计后已修正的漏洞）。"""
    from feedback.ledger import FeedbackLedger
    ledger = FeedbackLedger(SG_ROOT / "feedback" / "ledger.json")
    try:
        return ledger.close_vulnerability(spq_id, body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"漏洞不存在: {spq_id}")


class CloseByLocationBody(BaseModel):
    location: str


@router.post("/vulnerabilities/close-by-location")
def api_close_by_location(body: CloseByLocationBody,
                          user: CurrentUser = Depends(require_role("admin", "tester"))):
    """按位置批量关闭漏洞（Agent 重新审计后某 FR 的漏洞已全部修正）。"""
    from feedback.ledger import FeedbackLedger
    ledger = FeedbackLedger(SG_ROOT / "feedback" / "ledger.json")
    closed = ledger.close_vulnerabilities_by_location(body.location)
    return {"closed_count": len(closed), "closed": closed}


# ══════════════════════════════════════════════════════════
# Spec 文档中心
# ══════════════════════════════════════════════════════════

@router.get("/spec-files")
def api_spec_files(subdir: str = "", ws_name: str = Depends(resolve_workspace)):
    """列出请求工作区的 spec 文件树（含 delta 标记；授权校验由 resolve_workspace 完成）。"""
    ws = get_workspace(ws_name)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区未注册: {ws_name}")

    # V3 修复：subdir 必须解析在工作区根之内（防路径穿越枚举任意目录）
    if subdir:
        root = safe_resolve(subdir, ws_name)
        if root is None:
            raise HTTPException(status_code=403, detail=f"OUT_OF_SCOPE: 路径越界: {subdir}")
    else:
        root = ws.root
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {subdir}")

    files = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(ws.root)).replace("\\", "/")
            is_delta = "changes" in f.parts
            files.append({"path": rel, "is_delta": is_delta, "size": f.stat().st_size})

    return {"files": files, "workspace": ws.name}


@router.get("/read-file")
def api_read_file(path: str, ws_name: str = Depends(resolve_workspace)):
    """读取请求工作区的文件（授权校验由 resolve_workspace 完成）。"""
    resolved = safe_resolve(path, ws_name)
    if resolved is None:
        raise HTTPException(status_code=403, detail=f"OUT_OF_SCOPE: 路径越界或工作区不存在: {path}")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")

    content = resolved.read_text(encoding="utf-8")
    return {"path": path, "content": content}


@router.get("/search")
def api_search_files(q: str = "", ws_name: str = Depends(resolve_workspace)):
    """在工作区文件中搜索内容（返回匹配文件路径 + 上下文片段）。

    限制：只搜索文本文件（md/yaml/yml/json/txt/html/csv），单文件上限 512KB。
    """
    if not q or len(q) < 2:
        return {"results": [], "query": q}
    ws = get_workspace(ws_name)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区未注册: {ws_name}")

    TEXT_EXTS = {".md", ".markdown", ".yaml", ".yml", ".json", ".txt", ".html", ".htm", ".csv"}
    MAX_FILE_SIZE = 512 * 1024  # 512KB
    results = []
    q_lower = q.lower()

    for f in sorted(ws.root.rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in TEXT_EXTS:
            continue
        if f.stat().st_size > MAX_FILE_SIZE:
            continue
        rel = str(f.relative_to(ws.root)).replace("\\", "/")
        # 文件名匹配也算结果
        name_match = q_lower in rel.lower()
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if name_match:
            # 文件名匹配，取前 200 字符作为预览
            preview = content[:200].replace("\n", " ")
            results.append({"path": rel, "match_type": "filename", "preview": preview, "size": f.stat().st_size})
            continue
        # 内容搜索：找第一个匹配行的上下文
        for i, line in enumerate(content.splitlines()):
            if q_lower in line.lower():
                start = max(0, i - 1)
                end = min(len(content.splitlines()), i + 2)
                context = "\n".join(content.splitlines()[start:end])
                results.append({
                    "path": rel, "match_type": "content", "line": i + 1,
                    "preview": context[:300], "size": f.stat().st_size,
                })
                break  # 每个文件只取第一个匹配
        if len(results) >= 50:
            break  # 限制结果数量

    return {"results": results, "query": q}
