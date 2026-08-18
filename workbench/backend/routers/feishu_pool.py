"""feishu_pool.py — 飞书材料池 REST（飞书知识图谱一期 T4/T5）。

端点：
- GET/PUT /watch          watch 配置（feishu_watch.yaml = 显式授权载体）
- POST    /sync           手动「立即同步」（三通道只读拉取落私有区材料池）
- GET     /review-queue   复核队列（当前用户私有区）
- POST    /review/confirm 批量确认（提升共享区 → 图谱派生源）
- POST    /review/reject  批量拒绝（rejected 工作区级留痕防重复建议）

权限：仅操作当前登录用户自己的私有区（specflow_dir 按 contextvar 工号解析）；
RBAC 与 specflow 路由同级（登录即可，角色在依赖注入层控制）。

批次 A 说明：本文件为新建，挂载 main.py 的动作在批次 B 进行
（避免与 GateDock 并行支线冲突）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from services.auth import CurrentUser, get_current_user, resolve_workspace
from services.specflow import feishu_sync_service as sync_svc

router = APIRouter(prefix="/api/feishu-pool", tags=["feishu-pool"],
                   dependencies=[Depends(get_current_user)])


def _sf_base():
    from specstd.workspace import get_context_emp_no, specflow_dir
    return specflow_dir(emp=get_context_emp_no() or "")


def _ws_root():
    from specstd.workspace import get_workspace_root
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=400, detail="工作区未激活")
    return root


class WatchConfig(BaseModel):
    chats: list[dict] = []
    docs: list[dict] = []
    users: list[dict] = []          # 用户监听维度（open_id/name/scopes）
    minutes_days: int = 30
    chat_days: int = 7


class ReviewPairs(BaseModel):
    pairs: list[list[str]] = []


@router.get("/watch")
def get_watch(user: CurrentUser = Depends(get_current_user),
              workspace: str = Depends(resolve_workspace)):
    return sync_svc.load_watch_config(_sf_base())


@router.put("/watch")
def put_watch(cfg: WatchConfig,
              user: CurrentUser = Depends(get_current_user),
              workspace: str = Depends(resolve_workspace)):
    saved = sync_svc.save_watch_config(_sf_base(), cfg.model_dump())
    # T-924 配置驱动启停：保存配置即尝试拉起该用户监听（幂等；失败不阻断保存）
    watcher_state = "skipped"
    try:
        from services.specflow import feishu_watcher as fw

        from specstd.workspace import get_context_emp_no
        reg = fw.get_registry()
        emp = get_context_emp_no() or ""
        if reg is not None and emp:
            watcher_state = "started" if reg.start_user(emp) else "skipped"
    except Exception:
        watcher_state = "failed"
    return {**saved, "watcher": watcher_state}


@router.post("/sync")
def sync_now(user: CurrentUser = Depends(get_current_user),
             workspace: str = Depends(resolve_workspace)):
    """手动立即同步（按 watch 配置三通道拉取；单通道失败记 errors 不中断）。"""
    return sync_svc.sync_all(_sf_base())


@router.get("/review-queue")
def review_queue(user: CurrentUser = Depends(get_current_user),
                 workspace: str = Depends(resolve_workspace)):
    from services.specflow import feishu_review_service as rev_svc
    return {"items": rev_svc.list_queue(_sf_base())}


@router.post("/review/confirm")
def review_confirm(body: ReviewPairs,
                   user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    from services.specflow import feishu_review_service as rev_svc
    pairs = [(p[0], p[1]) for p in body.pairs if len(p) == 2]
    return rev_svc.confirm_suggestions(_sf_base(), _ws_root(), user.emp_no, pairs)


@router.post("/review/reject")
def review_reject(body: ReviewPairs,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    from services.specflow import feishu_review_service as rev_svc
    pairs = [(p[0], p[1]) for p in body.pairs if len(p) == 2]
    return rev_svc.reject_suggestions(_sf_base(), _ws_root(), user.emp_no, pairs)


@router.post("/transcribe")
def transcribe(user: CurrentUser = Depends(get_current_user),
               workspace: str = Depends(resolve_workspace)):
    """存量手动转述（T-920）：扫当前用户材料池全部 pending 图片走 vision 模型。

    未配置 vision 模型（model_configs 无 model_id=vision）→ skipped 不报错。
    """
    from services import model_config
    m = model_config.get_model("vision")
    if not m:
        return {"status": "skipped",
                "reason": "未配置 vision 模型（设置页 model_configs 加 model_id=vision）",
                "done": 0, "failed": 0, "total": 0}
    from agent.llm_client import LLMClient
    from specflow.feishu_pool import captions
    llm = LLMClient(model_id="vision")
    return captions.transcribe_images(_sf_base(), llm_vision=llm)


# ══════════════════════════════════════════════════════════
# T-929：材料池总览页端点（只读 + caption 人工补写）
# ══════════════════════════════════════════════════════════

@router.get("/materials")
def pool_materials(user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    """材料池清单（三通道快照，时间倒序）。纯读。"""
    return {"items": sync_svc.list_pool_materials(_sf_base())}


@router.get("/topics")
def pool_topics(user: CurrentUser = Depends(get_current_user),
                workspace: str = Depends(resolve_workspace)):
    """话题清单（候选=私有区 / 已确认=共享区）。纯读。"""
    return sync_svc.list_pool_topics(_sf_base(), _ws_root())


@router.get("/watcher-status")
def watcher_status(user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    """监听状态（注册表内存快照；未启动 → running=false）。纯读。"""
    from services.specflow import feishu_watcher as fw
    reg = fw.get_registry()
    if reg is None:
        return {"running": False, "count": 0, "watchers": []}
    st = reg.status()
    return {"running": True, **st}


class CaptionUpdate(BaseModel):
    material: str        # 材料 stem（如 fd-tokA）
    placeholder: str     # 图片#N
    caption: str


@router.post("/caption")
def update_caption_ep(body: CaptionUpdate,
                      user: CurrentUser = Depends(get_current_user),
                      workspace: str = Depends(resolve_workspace)):
    """图片 caption 人工补写（复核兜底；by=manual）。"""
    try:
        return sync_svc.update_image_caption(
            _sf_base(), body.material, body.placeholder, body.caption)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


# ══════════════════════════════════════════════════════════
# 选择器数据源（同步设置弹层；全部只读 --as user，失败记 errors 不抛 500）
# ══════════════════════════════════════════════════════════

@router.get("/chats")
def list_chats(user: CurrentUser = Depends(get_current_user),
               workspace: str = Depends(resolve_workspace)):
    """我的群聊列表（群聊选择器数据源；p2p 项前端置灰）。纯读。"""
    return sync_svc.list_my_chats()


@router.get("/users")
def find_users(query: str = "",
               user: CurrentUser = Depends(get_current_user),
               workspace: str = Depends(resolve_workspace)):
    """通讯录用户搜索（query 为空 → 空列表）。纯读。"""
    return sync_svc.search_users(query)


@router.get("/user-docs")
def find_user_docs(open_id: str, query: str = "",
                   user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    """按用户搜文档（应用侧 owner 过滤）。纯读。"""
    return sync_svc.search_user_docs(open_id, query)


@router.get("/docs-search")
def docs_search(query: str = "",
                user: CurrentUser = Depends(get_current_user),
                workspace: str = Depends(resolve_workspace)):
    """按文档名全局搜索（T-941：与按用户检索解耦，无需先选用户）。纯读。"""
    return sync_svc.search_docs(query)


@router.get("/resolve-doc")
def resolve_doc(input: str, user: CurrentUser = Depends(get_current_user),
                workspace: str = Depends(resolve_workspace)):
    """文档链接/token → 文档标识（T-937 粘贴解析：docx 本地/wiki node-get）。纯读。"""
    return sync_svc.resolve_doc_link(input)


@router.get("/material-content")
def material_content(file: str,
                     user: CurrentUser = Depends(get_current_user),
                     workspace: str = Depends(resolve_workspace)):
    """材料原文读取（详情弹层；docs/chats 原文、minutes 可读化+raw、附 imgmap）。纯读。"""
    return sync_svc.read_material_content(_sf_base(), file)


@router.get("/material-image")
def material_image(file: str, ph: str,
                   user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    """图片字节代理（前端 <img> 直连；media_key 下载 + 磁盘缓存）。纯读。"""
    out = sync_svc.fetch_material_image(_sf_base(), file, ph)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error", "图片不存在"))
    return Response(content=out["data"], media_type=out["mime"])
