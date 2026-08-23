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

import re

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


def _material_base():
    """T-949 共享材料区根（{ws}/.specflow/）：chats/docs/minutes 快照与
    话题库/历史所在；watch 配置与话题草案仍走 _sf_base() 私有区。"""
    from specstd.workspace import specflow_dir
    return specflow_dir("")


_POOL_VIEWER_CACHE: dict[str, tuple[float, dict]] = {}
_POOL_VIEWER_TTL = 300.0          # open_id+群列表解析缓存（免每次清单全量拉群）


def _pool_viewer(user: CurrentUser) -> dict:
    """T-949 可见性上下文：当前用户 open_id + 所在群 chat_id 集合。

    解析失败诚实降级（open_id 空 → 仅 chat 类型材料可见）；
    进程内 5min 缓存（auth status + chat-list 两次 CLI 调用摊薄）。
    """
    import time as _time
    emp = str(user.emp_no or "")
    now = _time.time()
    hit = _POOL_VIEWER_CACHE.get(emp)
    if hit and now - hit[0] < _POOL_VIEWER_TTL:
        return hit[1]
    viewer: dict = {"open_id": "", "chats": set()}
    try:
        from mcp_server.tools.lark_auth import do_status
        st = do_status(emp)
        viewer["open_id"] = str(st.get("open_id") or "")
    except Exception:
        pass
    if viewer["open_id"]:
        try:
            r = sync_svc.list_my_chats(emp=emp)
            viewer["chats"] = {str(c.get("chat_id") or "")
                               for c in (r.get("items") or [])}
        except Exception:
            pass
    _POOL_VIEWER_CACHE[emp] = (now, viewer)
    return viewer


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
    chat_sync_minutes: int = 0      # T-952：定时同步间隔（0=关，分钟）


class ReviewPairs(BaseModel):
    pairs: list[list[str]] = []
    scope: str = "mine"     # T-991：mine=私有队列（默认）/ shared=共享队列


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


class SyncRequest(BaseModel):
    chat_id: str = ""                    # T-952：非空时单群模式（只拉该群）


@router.post("/sync")
def sync_now(body: SyncRequest | None = None,
             user: CurrentUser = Depends(get_current_user),
             workspace: str = Depends(resolve_workspace)):
    """手动立即同步（按 watch 配置三通道拉取；单通道失败记 errors 不中断）。

    T-949：快照落共享材料区（多用户复用；watch 仍读私有区——谁配置谁拉）；
    同步前幂等迁移存量私有区数据（migrate_legacy_pool）。
    T-952：body.chat_id 非空时单群模式（只拉该群，秒级反馈——介入工作台
    「更新本群」入口）。
    """
    chat_id = (body.chat_id if body else "") or ""
    sync_svc.migrate_legacy_pool(_sf_base(), material_base=_material_base())
    return sync_svc.sync_all(_sf_base(), material_base=_material_base(),
                             chat_id=chat_id)


@router.get("/review-queue")
def review_queue(scope: str = "mine",
                 user: CurrentUser = Depends(get_current_user),
                 workspace: str = Depends(resolve_workspace)):
    """复核队列（默认 mine=当前用户私有区；T-991 scope=shared 共享材料区
    ——多人协作场景可互相复核建边建议）。"""
    from services.specflow import feishu_review_service as rev_svc
    base = _material_base() if scope == "shared" else _sf_base()
    return {"items": rev_svc.list_queue(base), "scope": scope}


@router.post("/review/confirm")
def review_confirm(body: ReviewPairs,
                   user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    from services.specflow import feishu_review_service as rev_svc
    pairs = [(p[0], p[1]) for p in body.pairs if len(p) == 2]
    base = _material_base() if body.scope == "shared" else _sf_base()
    return rev_svc.confirm_suggestions(base, _ws_root(), user.emp_no, pairs)


@router.post("/review/reject")
def review_reject(body: ReviewPairs,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    from services.specflow import feishu_review_service as rev_svc
    pairs = [(p[0], p[1]) for p in body.pairs if len(p) == 2]
    base = _material_base() if body.scope == "shared" else _sf_base()
    return rev_svc.reject_suggestions(base, _ws_root(), user.emp_no, pairs)


@router.post("/transcribe")
def transcribe(user: CurrentUser = Depends(get_current_user),
               workspace: str = Depends(resolve_workspace)):
    """存量手动转述（T-920）：扫材料区全部 pending 图片走 vision 模型。

    未配置 vision 模型（model_configs 无 model_id=vision）→ skipped 不报错。
    T-949：imgmap 随材料落共享区。
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
    return captions.transcribe_images(_material_base(), llm_vision=llm)


# ══════════════════════════════════════════════════════════
# T-929：材料池总览页端点（只读 + caption 人工补写）
# ══════════════════════════════════════════════════════════

@router.get("/materials")
def pool_materials(user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    """材料池清单（三通道快照，时间倒序；T-949 材料在共享区 + 按当前用户
    的飞书权限可见性过滤）。纯读。"""
    return {"items": sync_svc.list_pool_materials(
        _material_base(), viewer=_pool_viewer(user))}


@router.get("/topics")
def pool_topics(user: CurrentUser = Depends(get_current_user),
                workspace: str = Depends(resolve_workspace)):
    """话题清单（卡片=共享材料区状态制 / 已确认=共享区 facts）。纯读。"""
    return sync_svc.list_pool_topics(_material_base(), _ws_root())


# ══════════════════════════════════════════════════════════
# T-947：话题人工介入工作流端点（登录即可）
# ══════════════════════════════════════════════════════════

class DraftRequest(BaseModel):
    chat_sha8: str
    day: str = ""                       # 单日（兼容）或窗口首日
    days: list[str] = []                # T-951c：多日窗口（非空优先于 day）


class CommitRequest(BaseModel):
    chat_sha8: str
    day: str
    days: list[str] = []                # T-951c：多日窗口（提交时清理窗口内各日旧卡）
    picked: list[dict] = []


class CardUpdate(BaseModel):
    id: str
    title: str = ""
    summary: str = ""
    keywords: list[str] = []          # T-948：空列表=不改；传入即覆盖
    category: str = ""                # T-991：空=不改（chat|routine|requirement|test|solution）
    priority: str = ""                # T-991：空=不改（high|normal|low）
    base_rev: int | None = None       # T-948 乐观锁：与卡片 rev 不符 → 409
    message_ids: list[str] | None = None  # T-1001：None/缺省=不改；传入即整体重关联（须非空）
    window: list[str] = []            # T-1001：随重关联更新 [start,end]（空=不改）
    days: list[str] = []              # T-1001：随重关联更新跨日窗口（空=不改）


class RegenRequest(BaseModel):
    id: str


class TopicIdRequest(BaseModel):
    id: str


# T-993 D4/D5：跨群关联——确认/忽略写 relates_to 边；精筛结果进程内缓存
class RelateRequest(BaseModel):
    a: str
    b: str
    confirmed: bool = True     # false = 忽略（rejected 留痕防重复推荐）


_XREFINE_CACHE: dict[str, tuple[float, list[dict]]] = {}   # {ws: (ts, 精筛结果)}
_XREFINE_TTL = 300.0          # 5 分钟（设计 D5：推荐不是事实，不落盘）


@router.get("/topics/drafts")
def list_topic_drafts(user: CurrentUser = Depends(get_current_user),
                      workspace: str = Depends(resolve_workspace)):
    """全部话题草案（人工介入工作区）。纯读。"""
    from specflow.feishu_pool import topic_cluster as tc
    return {"items": tc.list_drafts(_sf_base())}


@router.post("/topics/draft")
def draft_topics(body: DraftRequest,
                 user: CurrentUser = Depends(get_current_user),
                 workspace: str = Depends(resolve_workspace)):
    """对单群单日/多日窗口重新 AI 分段，写 _topic_drafts.yaml（不动话题库）。"""
    from services import model_config

    from agent.llm_client import LLMClient
    from specflow.feishu_pool import topic_cluster as tc

    if not model_config.get_model("text"):
        raise HTTPException(
            status_code=400,
            detail="未配置 text 模型（设置页 model_configs 加 model_id=text）")
    days = body.days or ([body.day] if body.day else [])
    if not days:
        raise HTTPException(status_code=400, detail="day 或 days 至少传一个")
    # T-991：watch 反查该群类型标签（priority 推导信号；当前用户 watch 视角）
    chat_kind = ""
    try:
        from specflow.feishu_pool.pool_store import chat_sha8 as _sha8
        for c in (sync_svc.load_watch_config(_sf_base()).get("chats") or []):
            cid = str(c.get("chat_id") or "")
            if cid and _sha8(cid) == body.chat_sha8:
                chat_kind = str(c.get("kind") or "")
                break
    except Exception:
        pass
    try:
        out = tc.draft_chat_segments(
            _sf_base(), LLMClient(model_id="text"), body.chat_sha8, days,
            material_base=_material_base(), chat_kind=chat_kind)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return {"items": out}


@router.post("/topics/commit")
def commit_topics(body: CommitRequest,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    """勾选段提交为话题卡（窗口内各日旧卡标 rejected 留痕；新卡带 author/agent_origin）。"""
    from specflow.feishu_pool import topic_cluster as tc
    author = {"emp": user.emp_no, "name": getattr(user, "name", "") or ""}
    out = tc.commit_drafts(_sf_base(), body.chat_sha8, body.day, body.picked,
                           author=author, material_base=_material_base(),
                           days=body.days or None)
    return {"items": out}


@router.put("/topics/card")
def update_topic_card(body: CardUpdate,
                      user: CurrentUser = Depends(get_current_user),
                      workspace: str = Depends(resolve_workspace)):
    """单卡编辑 title/summary/keywords/category/priority（T-948 R7 + T-991）
    + 手动重关联原文 message_ids/window/days（T-1001 F4）；
    乐观锁冲突 → 409 带最新卡片；非法枚举/空关联 → 400）。"""
    from specflow.feishu_pool import topic_cluster as tc
    editor = {"emp": user.emp_no, "name": getattr(user, "name", "") or ""}
    try:
        return tc.edit_candidate(
            _sf_base(), body.id, title=body.title, summary=body.summary,
            keywords=body.keywords or None, base_rev=body.base_rev,
            editor=editor, material_base=_material_base(),
            category=body.category, priority=body.priority,
            message_ids=body.message_ids,
            window=body.window or None, days=body.days or None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except tc.RevConflict as e:
        raise HTTPException(
            status_code=409,
            detail={"message": "卡片已被他人编辑，请刷新后重试",
                    "topic": e.topic}) from None


@router.get("/topics/history")
def topic_history(topic_id: str,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    """单卡编辑历史（倒序，最新在前；多用户协作留痕）。纯读。"""
    from specflow.feishu_pool import topic_cluster as tc
    return {"items": tc.list_history(_sf_base(), topic_id,
                                     material_base=_material_base())}


@router.post("/topics/regen")
def regen_topic_card(body: RegenRequest,
                     user: CurrentUser = Depends(get_current_user),
                     workspace: str = Depends(resolve_workspace)):
    """单卡重新生成（id 不变；agent_origin 换新版本、旧版进历史）。"""
    from services import model_config

    from agent.llm_client import LLMClient
    from specflow.feishu_pool import topic_cluster as tc

    if not model_config.get_model("text"):
        raise HTTPException(
            status_code=400,
            detail="未配置 text 模型（设置页 model_configs 加 model_id=text）")
    editor = {"emp": user.emp_no, "name": getattr(user, "name", "") or ""}
    try:
        return tc.regen_candidate(
            _sf_base(), LLMClient(model_id="text"), body.id, editor=editor,
            material_base=_material_base())
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.post("/topics/confirm")
def confirm_topic(body: TopicIdRequest,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    """确认话题（状态翻转 draft→confirmed + 历史留痕 + 提升图谱事实源）。"""
    return _set_status(body.id, "confirmed", user)


@router.post("/topics/reject")
def reject_topic(body: TopicIdRequest,
                 user: CurrentUser = Depends(get_current_user),
                 workspace: str = Depends(resolve_workspace)):
    """拒绝话题（状态翻转 →rejected + 历史留痕）。"""
    return _set_status(body.id, "rejected", user)


def _set_status(topic_id: str, status: str, user: CurrentUser) -> dict:
    from specflow.feishu_pool import topic_cluster as tc
    editor = {"emp": user.emp_no, "name": getattr(user, "name", "") or ""}
    try:
        t = tc.set_topic_status(_sf_base(), topic_id, status, editor=editor,
                                material_base=_material_base())
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    # T-949：图谱事实源联动（confirmed 提升 / rejected 移除，保持一致）
    from specflow.feishu_pool import facts
    if status == "confirmed":
        facts.upsert_topic(_ws_root(), t)
    elif status == "rejected":
        facts.remove_topic(_ws_root(), topic_id)
    return t


# ══════════════════════════════════════════════════════════
# T-993：跨群话题关联（设计 D2/D4/D5——relates_to 边，只推荐不合并）
# ══════════════════════════════════════════════════════════

@router.post("/topics/relate")
def relate_topics(body: RelateRequest,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    """人工确认/忽略跨群关联：写 material_links.yaml 的 relates_to 边
    （confirmed=关联生效进图谱 / rejected=忽略留痕防重复推荐）。"""
    from specflow.feishu_pool import facts
    from specflow.feishu_pool import topic_cluster as tc
    known = {str(t.get("id")) for t in tc._load_candidates(_material_base())}
    for tid in (body.a, body.b):
        if tid not in known:
            raise HTTPException(status_code=404, detail=f"话题不存在: {tid}")
    a, b = sorted((body.a, body.b))            # 键规范化（与预筛一致）
    facts.append_link(_ws_root(), src=a, dst=b, edge="relates",
                      confidence=1.0 if body.confirmed else 0.0,
                      evidence="", confirmed_by=str(user.emp_no or ""),
                      status="confirmed" if body.confirmed else "rejected")
    _XREFINE_CACHE.pop(workspace, None)        # 状态变了，精筛缓存失效
    return {"a": a, "b": b,
            "status": "confirmed" if body.confirmed else "rejected"}


@router.get("/topics/relations")
def topic_relations(user: CurrentUser = Depends(get_current_user),
                    workspace: str = Depends(resolve_workspace)):
    """全部已确认跨群关联边（前端「N 群」徽标与关联抽屉数据源）。纯读。"""
    from specflow.feishu_pool import facts
    items = [l for l in facts.load_links(_ws_root())
             if l.get("edge") == "relates" and l.get("status") == "confirmed"]
    return {"items": items}


@router.post("/topics/cross-refine")
def cross_refine(user: CurrentUser = Depends(get_current_user),
                 workspace: str = Depends(resolve_workspace)):
    """LLM 精筛跨群候选（设计 D5：按需触发，进程内 5min 缓存不落盘；
    text 模型未配置 → 诚实返回预筛原样并标注 unrefined）。"""
    import time as _time
    hit = _XREFINE_CACHE.get(workspace)
    if hit and _time.time() - hit[0] < _XREFINE_TTL:
        return {"items": hit[1], "cached": True}
    from specflow.feishu_pool import facts
    out = sync_svc.list_pool_topics(_material_base(), _ws_root())
    candidates = out.get("cross_suggestions") or []
    cards = ([t for t in out.get("candidates", [])
              if t.get("status") != "rejected"]
             + out.get("confirmed", []))
    by_id = {str(t.get("id")): t for t in cards}
    unrefined = False
    try:
        from services import model_config
        if model_config.get_model("text"):
            from agent.llm_client import LLMClient
            from specflow.feishu_pool import cross_chat as xc
            candidates = xc.refine_with_llm(candidates, by_id,
                                            LLMClient(model_id="text"))
        else:
            unrefined = True
    except Exception:
        unrefined = True                       # LLM 不可达：诚实降级
    payload = {"items": candidates, "cached": False, "unrefined": unrefined}
    _XREFINE_CACHE[workspace] = (_time.time(), candidates)
    return payload


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


class AuthLoginBody(BaseModel):
    scope: str = ""      # 缺省 --domain all 全域（T-942：一次授权补齐）


class AuthCompleteBody(BaseModel):
    device_code: str = ""


# ── T-942：飞书授权闭环（登录即可，无菜单门槛）──
# 注：settings 路径的 lark_binding 端点被「系统设置」菜单 RBAC 拦截且未挂载，
# 材料池场景（普通用户）不可达——授权端点直接挂在 feishu-pool 前缀下。
# 底层复用 mcp_server.tools.lark_auth（两阶段 device flow + segno 二维码）。


@router.get("/auth/status")
def feishu_auth_status(user: CurrentUser = Depends(get_current_user),
                        workspace: str = Depends(resolve_workspace)):
    """当前用户飞书绑定状态（未绑定→弹层内引导授权）。"""
    from mcp_server.tools.lark_auth import do_status
    try:
        return do_status(user.emp_no)
    except Exception as e:   # noqa: BLE001 状态查询失败不阻断授权入口
        return {"bound": False, "identity": "", "identity_name": "",
                "open_id": "", "scopes": [], "error": str(e)[:200]}


@router.post("/auth/login")
def feishu_auth_login(body: AuthLoginBody,
                      user: CurrentUser = Depends(get_current_user),
                      workspace: str = Depends(resolve_workspace)):
    """发起飞书两阶段授权（返回 verification_url + 二维码 + device_code）。"""
    from mcp_server.tools.lark_auth import do_login
    return do_login(user.emp_no, body.scope)


@router.post("/auth/complete")
def feishu_auth_complete(body: AuthCompleteBody,
                         user: CurrentUser = Depends(get_current_user),
                         workspace: str = Depends(resolve_workspace)):
    """device flow 收尾：用户扫码后以 device_code 完成授权。"""
    from mcp_server.tools.lark_auth import do_login_complete
    return do_login_complete(user.emp_no, body.device_code)


@router.post("/caption")
def update_caption_ep(body: CaptionUpdate,
                      user: CurrentUser = Depends(get_current_user),
                      workspace: str = Depends(resolve_workspace)):
    """图片 caption 人工补写（复核兑底；by=manual）。T-949：imgmap 随材料在共享区。"""
    try:
        return sync_svc.update_image_caption(
            _material_base(), body.material, body.placeholder, body.caption)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


# ══════════════════════════════════════════════════════════
# 选择器数据源（同步设置弹层；全部只读 --as user，失败记 errors 不抛 500）
# ══════════════════════════════════════════════════════════

@router.get("/chats")
def list_chats(limit: int = 0,
               user: CurrentUser = Depends(get_current_user),
               workspace: str = Depends(resolve_workspace)):
    """我的群聊列表（group only；limit>0 快速预览最近活跃 N 群）。纯读。"""
    return sync_svc.list_my_chats(limit=limit)


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
    """材料原文读取（详情弹层；docs/chats 原文、minutes 可读化+raw、附 imgmap）。纯读。

    T-949：材料在共享材料区。
    """
    return sync_svc.read_material_content(_material_base(), file)


@router.get("/chat-messages")
def chat_messages(sha8: str, day: str,
                  user: CurrentUser = Depends(get_current_user),
                  workspace: str = Depends(resolve_workspace)):
    """群聊消息 JSONL 事实源（T-948：前端精确高亮/时间轴渲染用）。纯读。

    路径校验复用 _safe_material_path 白名单（仅允许 chats/{sha8}/{day}.jsonl 形状）。
    T-949：事实源在共享材料区。
    """
    from specflow.feishu_pool import chat_store
    rel = f"chats/{sha8}/{day}.jsonl"
    p = sync_svc._safe_material_path(_material_base(), rel)
    if p is None or not p.is_file():
        raise HTTPException(status_code=404, detail=f"消息快照不存在: {rel}")
    return {"items": chat_store.load_chat_jsonl(p), "file": rel}


@router.get("/chat-file")
def chat_file(message_id: str, file_key: str, name: str = "attachment",
              user: CurrentUser = Depends(get_current_user),
              workspace: str = Depends(resolve_workspace)):
    """T-955：聊天附件文件下载（消息附件可打开）。

    纯读；磁盘缓存同附件只下载一次；Content-Disposition 附件下载流。
    """
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", message_id or "") \
            or not re.fullmatch(r"[A-Za-z0-9_\-]+", file_key or ""):
        raise HTTPException(status_code=400, detail="非法 message_id/file_key")
    out = sync_svc.fetch_chat_file(_material_base(), message_id, file_key,
                                    file_name=name,
                                    emp=str(user.emp_no or ""))
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error", "附件不存在"))
    safe_name = re.sub(r"[^\w.\u4e00-\u9fff()\[\]-]", "_", out.get("file_name") or "attachment")
    return Response(
        content=out["data"], media_type="application/octet-stream",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{safe_name}"})


@router.get("/material-image")
def material_image(file: str, ph: str,
                   user: CurrentUser = Depends(get_current_user),
                   workspace: str = Depends(resolve_workspace)):
    """图片字节代理（前端 <img> 直连；media_key 下载 + 磁盘缓存）。纯读。

    T-949：imgmap 随材料在共享材料区。
    """
    out = sync_svc.fetch_material_image(_material_base(), file, ph,
                                         emp=str(user.emp_no or ""))
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error", "图片不存在"))
    return Response(content=out["data"], media_type=out["mime"])


@router.get("/chat-image")
def chat_image(message_id: str, media_key: str,
               user: CurrentUser = Depends(get_current_user),
               workspace: str = Depends(resolve_workspace)):
    """T-952/955b：聊天图片按 (message_id, media_key) 直取（时间轴富渲染）。

    纯读；磁盘缓存同图只下载一次。参数形状校验（纵深防御）。
    """
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", message_id or "") \
            or not re.fullmatch(r"[A-Za-z0-9_\-]+", media_key or ""):
        raise HTTPException(status_code=400, detail="非法 message_id/media_key")
    out = sync_svc.fetch_image_by_key(_material_base(), message_id, media_key,
                                       emp=str(user.emp_no or ""))
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error", "图片不存在"))
    return Response(content=out["data"], media_type=out["mime"])
