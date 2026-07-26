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

from fastapi import APIRouter, HTTPException
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
def api_list_workspaces():
    """列出全部已注册工作区。"""
    workspaces = list_workspaces()
    return {
        "workspaces": [w.to_dict() for w in workspaces],
        "active": get_active_workspace().name if get_active_workspace() else "",
    }


@router.get("/active")
def api_get_active():
    """获取当前激活的工作区。"""
    ws = get_active_workspace()
    if not ws:
        return {"active": None}
    return {"active": ws.to_dict()}


@router.post("/register-local")
def api_register_local(body: RegisterLocalBody):
    """注册本地文件夹工作区（合规校验强制执行，任一 ERROR 拒绝接入）。"""
    result = register_local(body.name, body.path, body.system,
                            activate=body.activate, run_conformance=True)
    return result


@router.post("/register-git")
def api_register_git(body: RegisterGitBody):
    """注册 git 工作区（克隆仓库，合规校验强制执行）。"""
    result = register_git(body.name, body.url, body.system, body.branch,
                          activate=body.activate, run_conformance=True)
    return result


@router.post("/activate")
def api_activate(body: ActivateBody):
    """激活工作区。"""
    if not set_active(body.name):
        raise HTTPException(status_code=404, detail=f"工作区不存在: {body.name}")
    return {"ok": True, "active": body.name}


@router.delete("/{name}")
def api_unregister(name: str):
    """注销工作区。"""
    if not unregister(name):
        raise HTTPException(status_code=404, detail=f"工作区不存在: {name}")
    return {"ok": True}


@router.post("/conformance")
def api_conformance(body: ConformanceBody):
    """执行合规校验。"""
    report = run_conformance(body.name or None)
    return report.to_dict()


@router.post("/pull")
def api_pull(body: PullBody):
    """拉取 git 工作区更新。"""
    result = pull(body.name)
    return result


# ══════════════════════════════════════════════════════════
# Spec 文档中心
# ══════════════════════════════════════════════════════════

@router.get("/spec-files")
def api_spec_files(subdir: str = ""):
    """列出当前激活工作区的 spec 文件树（含 delta 标记）。"""
    ws = get_active_workspace()
    if not ws:
        raise HTTPException(status_code=400, detail="无激活的工作区")

    # V3 修复：subdir 必须解析在工作区根之内（防路径穿越枚举任意目录）
    if subdir:
        root = safe_resolve(subdir)
        if root is None:
            raise HTTPException(status_code=403, detail=f"OUT_OF_SCOPE: 路径越界: {subdir}")
    else:
        root = ws.root
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {subdir}")

    import json
    files = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(ws.root)).replace("\\", "/")
            is_delta = "changes" in f.parts
            files.append({"path": rel, "is_delta": is_delta, "size": f.stat().st_size})

    return {"files": files, "workspace": ws.name}


@router.get("/read-file")
def api_read_file(path: str):
    """读取当前激活工作区的文件。"""
    resolved = safe_resolve(path)
    if resolved is None:
        raise HTTPException(status_code=403, detail=f"OUT_OF_SCOPE: 路径越界或工作区未激活: {path}")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")

    content = resolved.read_text(encoding="utf-8")
    return {"path": path, "content": content}
