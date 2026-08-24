"""feishu_sync_service.py — 飞书话题材料拉取入库编排（原飞书材料池，T-1003 改名；飞书知识图谱一期 T4）。

三通道只读拉取（docs +fetch / minutes +search+detail / im +chat-messages-list），
产物落私有区材料池（.specflow/{emp}/feishu_pool/）。

纪律：
- 全部只读命令，绝不写飞书资源（S2 背景文档铁律）；
- 单条失败记 errors 不中断（诚实呈现，不静默降级）；
- watch 配置（feishu_watch.yaml）即显式授权载体——只拉取用户配置的群/文档。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from specflow.feishu_pool import pool_store
from specflow.feishu_pool.lark_cli import _run_lark  # noqa: F401  (测试 patch 点)

log = logging.getLogger(__name__)

_IMG_PLACEHOLDER_RE = re.compile(r"\[(图片#\d+)\]")

_DEFAULT_WATCH = {"chats": [], "docs": [], "users": [],
                  "minutes_days": 30, "chat_days": 7,
                  "chat_sync_minutes": 0,
                  # T-1008：事件直写驱动的自动话题分类双阈值（0=各自关闭）
                  "topic_auto_count": 50,       # 单群积累 N 条新消息即触发
                  "topic_auto_minutes": 60}     # 未达条数但距上次分类 M 分钟且有新消息也触发

# 数值型配置键（load/save 双侧归一为非负 int；坏值回退 _DEFAULT_WATCH 默认）
_WATCH_INT_KEYS = ("minutes_days", "chat_days", "chat_sync_minutes",
                   "topic_auto_count", "topic_auto_minutes")


def _clean_watch_ints(cfg: dict) -> dict:
    for k in _WATCH_INT_KEYS:
        try:
            cfg[k] = max(0, int(cfg.get(k, _DEFAULT_WATCH[k])))
        except (TypeError, ValueError):
            cfg[k] = _DEFAULT_WATCH[k]
    return cfg

_USER_SCOPES = {"group_sender", "minutes", "docs"}

# T-990 群类型标签（话题分类的强先验：测试群话题大概率 test 类，T-991 优先级信号之一）
_CHAT_KINDS = {"测试", "产研", "用户", "项目", "运维", "迭代"}


def _clean_users(raw_users) -> list[dict]:
    """users 归一化（设计 §3）：open_id 必填、scopes 合法枚举过滤、
    按 open_id 去重（后写覆盖）；允许空 scopes（保存但无监听动作）。"""
    out: dict[str, dict] = {}
    for u in raw_users or []:
        if not isinstance(u, dict):
            continue
        open_id = str(u.get("open_id", "")).strip()
        if not open_id:
            continue
        scopes = [s for s in (u.get("scopes") or []) if s in _USER_SCOPES]
        out[open_id] = {"open_id": open_id,
                        "name": str(u.get("name", "") or ""),
                        "scopes": scopes}
    return list(out.values())


def _clean_chats(raw_chats) -> list[dict]:
    """chats 归一化（T-990）：chat_id 必填、kind 合枚举过滤（空=未标注）、
    topic_days 归一为非负 int（缺省 7），按 chat_id 去重（后写覆盖）。"""
    out: dict[str, dict] = {}
    for c in raw_chats or []:
        if not isinstance(c, dict):
            continue
        chat_id = str(c.get("chat_id", "")).strip()
        if not chat_id:
            continue
        kind = str(c.get("kind", "") or "")
        try:
            days = max(0, int(c.get("topic_days", 7)))
        except (TypeError, ValueError):
            days = 7
        out[chat_id] = {"chat_id": chat_id,
                        "name": str(c.get("name", "") or ""),
                        "kind": kind if kind in _CHAT_KINDS else "",
                        "topic_days": days}
    return list(out.values())


# ══════════════════════════════════════════════════════════
# watch 配置（显式授权载体）
# ══════════════════════════════════════════════════════════

def _watch_path(specflow_emp_base: Path) -> Path:
    return Path(specflow_emp_base) / "feishu_watch.yaml"


def load_watch_config(specflow_emp_base: Path) -> dict:
    path = _watch_path(specflow_emp_base)
    if not path.is_file():
        return dict(_DEFAULT_WATCH)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return dict(_DEFAULT_WATCH)
    cfg = dict(_DEFAULT_WATCH)
    cfg.update({k: v for k, v in raw.items() if k in _DEFAULT_WATCH})
    cfg["users"] = _clean_users(cfg.get("users"))
    cfg["chats"] = _clean_chats(cfg.get("chats"))
    return _clean_watch_ints(cfg)


def save_watch_config(specflow_emp_base: Path, cfg: dict) -> dict:
    path = _watch_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(_DEFAULT_WATCH)
    clean.update({k: v for k, v in (cfg or {}).items() if k in _DEFAULT_WATCH})
    clean["users"] = _clean_users(clean.get("users"))
    clean["chats"] = _clean_chats(clean.get("chats"))
    clean = _clean_watch_ints(clean)
    path.write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return clean


# ══════════════════════════════════════════════════════════
# 三通道同步
# ══════════════════════════════════════════════════════════

def _imgmap_from_content(content: str, images: list | None) -> dict:
    """imgmap 初始条目（全部 pending；images 字段优先，否则正则扫占位符）。"""
    entries: dict = {}
    for img in images or []:
        ph = str(img.get("placeholder", ""))
        if ph:
            entries[ph] = {"media_key": str(img.get("media_key", "")),
                           "caption": "", "caption_by": "none", "status": "pending"}
    if not entries:
        for m in _IMG_PLACEHOLDER_RE.finditer(content or ""):
            entries.setdefault(m.group(1),
                               {"media_key": "", "caption": "",
                                "caption_by": "none", "status": "pending"})
    return entries


def _pull_perm_meta(token: str, doc_type: str) -> dict:
    """T-949：拉取飞书侧权限元数据（drive +member-list / +permission-get-setting）。

    missing_scope / 任何失败 → {"pulled_at": None, "error": …}（不阻断正文落盘；
    可见性过滤对 perm 缺失保守处理）；成功 → {pulled_at, public, member_users,
    member_chats}。成功返回形状待真实 token 补授权后校准（宽容解析多键名，
    契约见 test_specstd/feishu_cli_contract.py）。
    """
    try:
        members_payload = _run_lark(["drive", "+member-list", "--as", "user",
                                     "--token", token, "--type", doc_type])
        rows = ((members_payload.get("data") or {}).get("members")
                or (members_payload.get("data") or {}).get("items") or [])
        users: list[str] = []
        chats: list[str] = []
        for m in rows:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("member_id") or m.get("id") or "")
            mtype = str(m.get("member_type") or m.get("type") or "user")
            if not mid:
                continue
            (chats if mtype in ("chat", "group") else users).append(mid)
    except ValueError as e:
        return {"pulled_at": None, "public": False, "member_users": [],
                "member_chats": [], "error": str(e)[:300]}
    try:
        setting = _run_lark(["drive", "+permission-get-setting", "--as", "user",
                             "--token", token, "--type", doc_type])
        sd = setting.get("data") or {}
        link = str(sd.get("link_share_entity") or sd.get("link_share") or "")
        public = link in ("tenant_readable", "anyone_readable",
                          "anyone_can_view")
    except ValueError as e:
        # member 成功但 setting 失败：部分权限元数据（保留 members，诚实记错）
        return {"pulled_at": None, "public": False,
                "member_users": users, "member_chats": chats,
                "error": str(e)[:300]}
    return {"pulled_at": datetime.now().isoformat(timespec="seconds"),
            "public": public, "member_users": users, "member_chats": chats}


def sync_doc(specflow_emp_base: Path, doc_token: str, url: str = "",
             meta: dict | None = None) -> dict:
    """文档快照落池（docs +fetch 只读；meta T-940：owner/直链 sidecar；
    T-949：附飞书权限元数据 perm——缺失不阻断，可见性过滤保守处理）。"""
    payload = _run_lark(["docs", "+fetch", "--as", "user",
                         "--doc", doc_token, "--doc-format", "markdown"])
    data = payload.get("data") or {}
    content = str(data.get("content") or data.get("markdown") or "")
    imgmap = _imgmap_from_content(content, data.get("images"))
    meta = dict(meta or {})
    meta.setdefault("perm", _pull_perm_meta(doc_token, "docx"))
    return pool_store.save_doc_snapshot(
        specflow_emp_base, doc_token, content,
        imgmap=imgmap if imgmap else None, source_url=url, meta=meta)


def sync_minutes(specflow_emp_base: Path, days: int = 30,
                 owner_ids: list[str] | None = None) -> list[dict]:
    """妙记快照落池（minutes +search → 逐个 +detail）。

    owner_ids=None → --owner-ids me（现状）；指定时按 open_id 检索（用户监听）。
    """
    if days <= 0:
        return []
    owners = ",".join(owner_ids) if owner_ids else "me"
    found = _run_lark(["minutes", "+search", "--owner-ids", owners,
                       "--page-size", "20"])
    items = (found.get("data") or {}).get("items") or []
    # T-940：单 owner 检索时归属明确（search 返回无结构化 owner_id，
    # 归属由调用方上下文落盘；多 owner/me 不记）
    owner_open_id = owner_ids[0] if owner_ids and len(owner_ids) == 1 else ""
    out = []
    for it in items:
        token = str(it.get("minute_token") or it.get("token") or "")
        if not token:
            continue
        detail = _run_lark(["minutes", "+detail", "--minute-tokens", token,
                            "--summary", "--keyword"])
        # URL：实测 search item 结构为 meta_data.app_link（兼容旧 url 键）
        url = str((it.get("meta_data") or {}).get("app_link")
                  or it.get("url") or "")
        out.append(pool_store.save_minutes_snapshot(
            specflow_emp_base, token, detail.get("data") or {},
            source_url=url,
            meta={"owner_open_id": owner_open_id, "source_url": url,
                  "perm": _pull_perm_meta(token, "minutes")}))
    return out


def sync_chat(specflow_emp_base: Path, chat_id: str, day: str) -> dict:
    """群聊快照落池（T-948 重写：JSONL 事实源 + md 派生视图）。

    按天拉取（--start/--end 圈定当日，end 取 23:59:59 防跨天污染）；
    CLI 契约以实测快照为准（data.messages，见 test_feishu_chat_store._CLI_SNAPSHOT）；
    0 条消息不写文件（消灭 0 字节假成功），返回 messages=0 + file=None。
    """
    from datetime import timedelta

    from specflow.feishu_pool import chat_store
    from specflow.feishu_pool.paths import pool_dirs
    d = datetime.strptime(day, "%Y%m%d")
    payload = _run_lark([
        "im", "+chat-messages-list", "--as", "user",
        "--chat-id", chat_id,
        "--start", d.strftime("%Y-%m-%dT%H:%M:%S"),
        "--end", (d + timedelta(days=1) - timedelta(seconds=1)).strftime(
            "%Y-%m-%dT%H:%M:%S"),
        "--order", "asc", "--page-all", "--page-limit", "40",
        "--page-size", "50"])
    data = payload.get("data") or {}
    msgs = data.get("messages") or data.get("items") or []   # items 兼容观察期
    rows = [chat_store.normalize_pull_message(m) for m in msgs if isinstance(m, dict)]
    cs8 = pool_store.chat_sha8(chat_id)
    if not rows:
        return {"chat_sha8": cs8, "day": day, "messages": 0,
                "added": 0, "updated": 0, "file": None}
    day_file = (pool_dirs(specflow_emp_base)["chats"] / cs8 / f"{day}.jsonl")
    merged = chat_store.merge_chat_jsonl(day_file, rows)
    chat_store.rebuild_views(day_file)
    return {"chat_sha8": cs8, "day": day, "messages": len(rows),
            **merged, "file": f"chats/{cs8}/{day}.md"}


def sync_all(specflow_emp_base: Path, cfg: dict | None = None,
             material_base: Path | None = None,
             chat_id: str = "") -> dict:
    """按 watch 配置全通道同步；单条失败记 errors 不中断。

    T-948：群聊通道按 chat_days 天窗口逐日拉取（历史补拉能力）；
    返回 chats（有消息的 群×天 数）/ chats_empty（当日无消息的天数）/ days_pulled。
    T-949：material_base 非空时三通道快照落共享材料区。
    T-952：chat_id 非空时**单群模式**——只拉该群（docs/minutes 跳过，
    介入工作台「更新本群」入口，秒级反馈不拉全量）。
    """
    from datetime import timedelta

    cfg = cfg if cfg is not None else load_watch_config(specflow_emp_base)
    material_root = Path(material_base) if material_base else specflow_emp_base
    out = {"docs": 0, "minutes": 0, "chats": 0, "chats_empty": 0,
           "days_pulled": 0, "errors": []}
    today = datetime.now()
    chat_days = max(1, int(cfg.get("chat_days") or 1))
    days = [(today - timedelta(days=i)).strftime("%Y%m%d")
            for i in range(chat_days)]
    out["days_pulled"] = len(days)
    if not chat_id:
        for doc in cfg.get("docs") or []:
            try:
                sync_doc(material_root, str(doc.get("token", "")),
                         url=str(doc.get("url", "")),
                         meta={"owner_open_id": str(doc.get("owner_open_id") or ""),
                               "owner_name": str(doc.get("owner_name") or ""),
                               "title": str(doc.get("title") or ""),
                               "source_url": str(doc.get("url") or "")})
                out["docs"] += 1
            except Exception as e:
                out["errors"].append(f"doc {doc.get('token', '?')}: {e}")
        try:
            out["minutes"] = len(sync_minutes(material_root,
                                              int(cfg.get("minutes_days") or 0)))
        except Exception as e:
            out["errors"].append(f"minutes: {e}")
    for chat in cfg.get("chats") or []:
        if chat_id and str(chat.get("chat_id", "")) != chat_id:
            continue                          # T-952：单群模式只拉指定群
        for d in days:
            try:
                r = sync_chat(material_root, str(chat.get("chat_id", "")), d)
                if r.get("messages"):
                    out["chats"] += 1
                else:
                    out["chats_empty"] += 1
            except Exception as e:
                out["errors"].append(f"chat {chat.get('chat_id', '?')}/{d}: {e}")
    # T-945：群聊落池后异步聚类；T-952：自动图片转述（均 daemon 线程，
    # 模型未配置诚实跳过；技术侧多模态处理对用户透明）。
    maybe_cluster_async(specflow_emp_base, material_base=material_root)
    maybe_transcribe_async(specflow_emp_base, material_base=material_root)
    return out


def _cluster_once(emp_base: Path, material_base: Path | None = None,
                  only_chat_ids: set[str] | None = None) -> None:
    """单次聚类（可同步测试）：text 模型未配置→跳过；异常吞掉只记日志。

    T-946：从 watch 配置构造按群窗口——chats[].topic_days（缺省 7：只聚
    近 7 天快照；0=该群关闭）；未入 watch 的历史群回退默认 7 天（过期
    数据不提取，控制 LLM 成本）。
    T-949：窗口读私有 watch（emp_base），快照与话题库读材料区（material_base）。
    T-1008：only_chat_ids 非空时只聚指定群（事件直写双阈值自动触发——
    单群 scoped 重聚，避免全量窗口重复 LLM 调用）；None=全量（同步后默认）。
    """
    try:
        from services import model_config
        m = model_config.get_model("text")
        if not m:
            log.info("话题聚类跳过：未配置 text 模型（设置页 model_configs 加 model_id=text）")
            return
        from agent.llm_client import LLMClient
        from specflow.feishu_pool import topic_cluster as tc
        from specflow.feishu_pool.pool_store import chat_sha8
        chat_windows = {}
        chat_kinds = {}
        for c in (load_watch_config(emp_base).get("chats") or []):
            cid = str(c.get("chat_id", ""))
            if not cid or (only_chat_ids is not None and cid not in only_chat_ids):
                continue
            try:
                chat_windows[chat_sha8(cid)] = int(c.get("topic_days", 7) or 0)
            except (TypeError, ValueError):
                chat_windows[chat_sha8(cid)] = 7
            # T-991：群类型标签随聚类下传（priority 推导信号；多 emp 同群
            # 配置以最后处理的 watch 为准——kind 语义通常一致）
            chat_kinds[chat_sha8(cid)] = str(c.get("kind") or "")
        if only_chat_ids is not None and not chat_windows:
            log.info("话题聚类跳过：指定群不在 watch 配置或均已关闭（topic_days=0 由触发侧过滤）")
            return
        material_root = Path(material_base) if material_base else emp_base
        tc.cluster_chat_snapshots(material_root, LLMClient(model_id="text"),
                                  chat_windows=chat_windows, default_days=7,
                                  chat_kinds=chat_kinds or None)
        # T-992：聚类后触发建边建议入队（死链修复——此前 suggest→enqueue
        # 仅测试调用，生产链路断着；挂聚类尾部使 sync 与 watcher 两路都覆盖）
        _suggest_links_for_pool(emp_base, material_root)
    except Exception as e:
        log.warning("话题聚类失败（不阻断同步）: %s", e)


# T-992：单轮建边建议对象数软上限（控 LLM 成本；超出诚实记日志截断）
_SUGGEST_MAX_TARGETS = 200
# 单对象喂给 LLM 的正文截断（字符）
_SUGGEST_MAX_TEXT = 6000


def _suggest_links_for_pool(emp_base: Path, material_root: Path) -> None:
    """T-992 死链修复：对材料池对象跑 LLM 建边建议并入复核队列（生产接线）。

    对象：话题卡（非 rejected，title+summary）+ docs 快照（fd-*）+ minutes
    快照（fm-*，title+summary 可读化）；逐对象一次 LLM 调用（三重防幻觉在
    link_suggest：幻觉 fr_id 丢弃/evidence 原文子串校验/rejected 不重提）。
    入当前用户私有队列（mine 语义不变，T-991 共享 scope 仅查看侧）。

    拍板②留空后补语义：工作区无 FR 锚点（spec 未落）→ 跳过不硬派生；新 FR
    诞生后下一轮同步自动补挂——enqueue 按 (src,dst) 去重不挡新 dst。
    """
    try:
        from specflow.feishu_pool import link_suggest as ls
        from specflow.feishu_pool import topic_cluster as tc
        from specflow.feishu_pool.paths import pool_dirs
        from specstd.anchors import scan_anchors
        from specstd.workspace import get_workspace_root

        ws_root = get_workspace_root()
        if not ws_root:
            log.info("建边建议跳过：工作区未激活")
            return
        anchors = scan_anchors(ws_root)
        if not anchors:
            log.info("建边建议跳过：工作区无 FR 锚点（spec 未落——话题模块留空，"
                     "待 spec 冻结后下一轮同步自动补挂）")
            return

        pool = pool_dirs(material_root)
        targets: list[tuple[str, str]] = []
        # 话题卡（非 rejected）
        for t in tc._load_candidates(material_root):
            if t.get("status") == "rejected":
                continue
            text = f"{t.get('title', '')}\n{t.get('summary', '')}".strip()
            if text:
                targets.append((str(t.get("id", "")), text))
        # docs 快照（markdown 正文）
        for f in sorted(pool["docs"].glob("fd-*.md")) if pool["docs"].is_dir() else []:
            targets.append((f"fd:{f.stem[3:]}",
                            f.read_text(encoding="utf-8", errors="replace")))
        # minutes 快照（可读化 title+summary；无文本层跳过）
        for f in sorted(pool["minutes"].glob("fm-*.json")) if pool["minutes"].is_dir() else []:
            title, summary = _minutes_title_summary(f)
            text = f"{title}\n{summary}".strip()
            if text:
                targets.append((f"fm:{f.stem[3:]}", text))
        if not targets:
            return
        if len(targets) > _SUGGEST_MAX_TARGETS:
            log.warning("建边建议对象 %d 超软上限 %d，本轮截断（下轮同步继续）",
                        len(targets), _SUGGEST_MAX_TARGETS)
            targets = targets[:_SUGGEST_MAX_TARGETS]

        from agent.llm_client import LLMClient
        from services.specflow import feishu_review_service as rev
        llm = LLMClient(model_id="text")
        suggested_by = str(emp_base.name or "")
        added = 0
        for src_id, text in targets:
            sug = ls.suggest_links_for_material(
                src_id, text[:_SUGGEST_MAX_TEXT], anchors, llm,
                workspace_root=ws_root)
            if sug:
                added += rev.enqueue_suggestions(emp_base, suggested_by, sug)
        log.info("建边建议完成：%d 对象，新入队 %d 条", len(targets), added)
    except Exception as e:
        log.warning("建边建议失败（不阻断同步）: %s", e)


def maybe_cluster_async(emp_base: Path, material_base: Path | None = None,
                        only_chat_ids: set[str] | None = None) -> None:
    """异步触发聚类（daemon 线程，不阻塞 sync 返回；同步完成后话题页稍后可见）。

    T-1008：only_chat_ids 非空时 scoped 单群聚类（事件直写自动触发用）。
    """
    threading.Thread(target=_cluster_once, args=(emp_base, material_base,
                                                 only_chat_ids),
                     daemon=True, name="feishu-topic-cluster").start()


def _transcribe_once(emp_base: Path, material_base: Path | None = None) -> None:
    """T-952：单次图片转述（可同步测试）——vision 模型未配置诚实跳过；
    异常吞掉只记日志（与聚类同模式；技术侧转述对用户透明，无独立维护入口）。"""
    try:
        from services import model_config
        if not model_config.get_model("vision"):
            log.info("图片转述跳过：未配置 vision 模型（设置页 model_configs 加 model_id=vision）")
            return
        from agent.llm_client import LLMClient
        from specflow.feishu_pool import captions
        captions.transcribe_images(
            Path(material_base) if material_base else emp_base,
            llm_vision=LLMClient(model_id="vision"))
    except Exception as e:
        log.warning("图片转述失败（不阻断同步）: %s", e)


def maybe_transcribe_async(emp_base: Path,
                           material_base: Path | None = None) -> None:
    """T-952：异步触发图片转述（daemon 线程；同步后自动，无需用户手动）。"""
    threading.Thread(target=_transcribe_once, args=(emp_base, material_base),
                     daemon=True, name="feishu-img-transcribe").start()


def sync_recent_docs(specflow_emp_base: Path, days: int = 1) -> dict:
    """文档增量轮询（二期 T-922，F4）：drive +search 近 N 天编辑 ∩ watch.docs 授权清单 → 交集落池。

    CLI 事件目录无 docs 域（一期实测缺口）——文档新鲜度由本日级轮询补齐；
    未授权文档绝不落池（授权清单即边界）。
    """
    cfg = load_watch_config(specflow_emp_base)
    authorized = {str(d.get("token", "")) for d in cfg.get("docs") or []}
    out = {"docs": 0, "errors": []}
    if not authorized:
        return out
    found = _run_lark(["drive", "+search", "--as", "user", "--query", "",
                       "--edited-since", f"{days}d", "--doc-types", "docx",
                       "--sort", "edit_time", "--page-size", "20"])
    items = (found.get("data") or {}).get("items") or []
    for it in items:
        token = str(it.get("token") or it.get("obj_token") or "")
        if not token or token not in authorized:
            continue
        try:
            sync_doc(specflow_emp_base, token, url=str(it.get("url") or ""))
            out["docs"] += 1
        except Exception as e:
            out["errors"].append(f"doc {token}: {e}")
    return out


def sync_user_materials(specflow_emp_base: Path,
                        material_base: Path | None = None) -> dict:
    """用户材料轮询（设计 §4.3）：按 users[].scopes 拉指定用户妙记/文档落池。

    单用户/单文档失败记 errors 不中断（诚实呈现）。
    T-1011 波及面修复：watch 配置读私有区（specflow_emp_base），材料落盘走
    material_root（共享材料区；material_base 缺省回退私有区=单用户兼容）。
    """
    cfg = load_watch_config(specflow_emp_base)
    material_root = Path(material_base) if material_base else specflow_emp_base
    out = {"minutes": 0, "docs": 0, "errors": []}
    minutes_days = int(cfg.get("minutes_days") or 0)
    for u in cfg.get("users") or []:
        open_id = str(u.get("open_id", ""))
        scopes = set(u.get("scopes") or [])
        if not open_id:
            continue
        label = str(u.get("name") or "") or open_id
        if "minutes" in scopes:
            try:
                out["minutes"] += len(sync_minutes(
                    material_root, minutes_days, owner_ids=[open_id]))
            except Exception as e:
                out["errors"].append(f"minutes {label}: {e}")
        if "docs" in scopes:
            r = _sync_user_docs(material_root, open_id)
            out["docs"] += r["docs"]
            out["errors"].extend(f"docs {label}: {e}" for e in r["errors"])
    return out


def _sync_user_docs(specflow_emp_base: Path, open_id: str,
                    query: str = "") -> dict:
    """按用户检索文档落池：docs +search（空 query 实测可用）→ 应用侧按
    result_meta.owner_id 过滤（CLI --filter owner_ids 2026-08-17 实测不生效）。

    召回边界：当前用户可见的近期文档 ∩ 该用户产出（诚实呈现，见设计 §4.5）。
    """
    out = {"docs": 0, "errors": []}
    found = _run_lark(["docs", "+search", "--as", "user",
                       "--query", query, "--page-size", "50"])
    results = (found.get("data") or {}).get("results") or []
    for it in results:
        meta = it.get("result_meta") or {}
        if str(meta.get("owner_id", "")) != open_id:
            continue
        token = str(meta.get("token", ""))
        if not token:
            continue
        try:
            sync_doc(specflow_emp_base, token, url=str(meta.get("url") or ""),
                     meta={"owner_open_id": open_id,
                           "owner_name": str(meta.get("owner_name") or ""),
                           "title": str(it.get("title") or ""),
                           "source_url": str(meta.get("url") or "")})
            out["docs"] += 1
        except Exception as e:
            out["errors"].append(f"{token}: {e}")
    return out


# ══════════════════════════════════════════════════════════
# 材料池总览页服务函数（三期 T-929，只读 + caption 人工补写）
# ══════════════════════════════════════════════════════════

def _minutes_title_summary(f: Path) -> tuple[str, str]:
    """妙记快照提取 title/summary（minutes 数组或裸对象兼容；artifacts.summary 优先）。"""
    try:
        data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return "", ""
    entries = data.get("minutes") if isinstance(data, dict) else None
    if not entries and isinstance(data, dict):
        entries = [data]
    for it in entries or []:
        if not isinstance(it, dict):
            continue
        arts = it.get("artifacts") or {}
        return (str(it.get("title") or ""),
                str(arts.get("summary") or it.get("summary") or ""))
    return "", ""


def _md_title_summary(f: Path) -> tuple[str, str]:
    """markdown 快照提取 title（首个 # 行）/ summary（首个非空非标题行）。"""
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", ""
    title, summary = "", ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not title and s.startswith("#"):
            title = s.lstrip("# ").strip()
            continue
        if not summary:
            summary = s
        if title and summary:
            break
    return title, summary


def _read_meta_sidecar(f: Path) -> dict:
    """读材料 meta sidecar（{stem}.meta.json；缺失/损坏返回空 dict 诚实降级）。"""
    mp = f.with_suffix(".meta.json")
    if not mp.is_file():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def migrate_legacy_pool(specflow_emp_base: Path,
                        material_base: Path | None = None) -> dict:
    """T-949 存量迁移：私有区三通道快照/话题库/历史 → 共享材料区（幂等可重跑）。

    - chats/docs/minutes：逐文件 move（目标已存在则跳过——共享版本优先；
      docs/minutes 的 .meta.json/.imgmap.json sidecar 随正文一同迁移）。
      T-1011 波及面修复补 docs/minutes——T-949 版只迁 chats，而
      specflow_dir 解析根因（验收钉案）致 docs/minutes 同样落私有区；
    - 话题库：私有 _topics.yaml/_candidate_topics.yaml 存在且共享无 → move；
      共享已有 → 按 id 合并（冲突共享优先）后删私有文件；
    - 历史：整行去重 append 合并后删私有文件。
    返回 {chats_files, docs_files, topic_store}。watch 配置/草案不迁（设计 D2：留私有）。
    """
    import shutil

    mroot = Path(material_base) if material_base else specflow_emp_base
    out = {"chats_files": 0, "docs_files": 0, "topic_store": False}
    if mroot == Path(specflow_emp_base):
        return out                                  # 同区无需迁移
    src_pool = Path(specflow_emp_base) / "feishu_pool"
    dst_pool = mroot / "feishu_pool"
    if not src_pool.is_dir():
        return out
    # ① 三通道快照（chats/docs/minutes 同语义：共享优先，sidecar 随附）
    for sub, key in (("chats", "chats_files"), ("docs", "docs_files"),
                     ("minutes", "docs_files")):
        src_dir = src_pool / sub
        if not src_dir.is_dir():
            continue
        for f in sorted(src_dir.rglob("*")):
            if not f.is_file():
                continue
            dst = dst_pool / sub / f.relative_to(src_dir)
            if dst.is_file():
                f.unlink()                           # 共享版本优先，丢弃私有副本
                out[key] += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dst))
            out[key] += 1
    # ② 话题库（_topics.yaml 优先，回退旧 _candidate_topics.yaml）
    from specflow.feishu_pool import topic_cluster as tc
    src_store = next((p for p in (src_pool / "_topics.yaml",
                                  src_pool / "_candidate_topics.yaml")
                      if p.is_file()), None)
    if src_store is not None:
        dst_store = dst_pool / "_topics.yaml"
        if not dst_store.is_file():
            dst_store.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_store), str(dst_store))
            out["topic_store"] = True
        else:
            # 合并：共享已有 → 私有卡按 id 并入（冲突共享优先）
            merged = {t.get("id"): t for t in tc._load_candidates(mroot)}
            for t in tc._load_candidates(specflow_emp_base):
                merged.setdefault(t.get("id"), t)
            tc._save_candidates(mroot, list(merged.values()))
            src_store.unlink()
            out["topic_store"] = True
    # ③ 历史（整行去重 append）
    src_hist = src_pool / "_topic_history.jsonl"
    if src_hist.is_file():
        dst_hist = dst_pool / "_topic_history.jsonl"
        existing = (dst_hist.read_text(encoding="utf-8", errors="replace")
                    .splitlines() if dst_hist.is_file() else [])
        have = set(existing)
        adds = [ln for ln in src_hist.read_text(
            encoding="utf-8", errors="replace").splitlines()
            if ln.strip() and ln not in have]
        if adds:
            dst_hist.parent.mkdir(parents=True, exist_ok=True)
            with open(dst_hist, "a", encoding="utf-8") as fh:
                for ln in adds:
                    fh.write(ln + "\n")
        src_hist.unlink()
    return out


def migrate_all_private_pools(sf_shared_root: Path,
                              material_base: Path | None = None) -> dict:
    """T-1011 波及面修复：枚举 .specflow 下全部 emp 私有区，逐个迁移材料池到
    共享区（复用 migrate_legacy_pool 幂等语义，可重跑）。

    背景：specflow_dir("") 在 emp 请求上下文下恒解析私有区（T-1011 验收打回
    根因），T-949 以来全部同步产出实际落在各 emp 私有池；解析修复后须把存量
    归拢共享区，否则话题页/召回读到空库。
    sf_shared_root = 共享 .specflow 根（枚举其一级子目录中的 emp 私有区）。
    返回 {emps, chats_files, topic_store}。
    """
    root = Path(sf_shared_root)
    out = {"emps": 0, "chats_files": 0, "docs_files": 0, "topic_store": 0}
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "feishu_pool").is_dir():
            continue
        r = migrate_legacy_pool(d, material_base=material_base)
        moved = r["chats_files"] or r["docs_files"] or r["topic_store"]
        out["emps"] += int(bool(moved))   # 只计有实际迁移的（空目录不算，保幂等零增量）
        out["chats_files"] += r["chats_files"]
        out["docs_files"] += r["docs_files"]
        out["topic_store"] += int(bool(r["topic_store"]))
    return out


def material_visible(item: dict, viewer_open_id: str,
                     viewer_chats: set[str]) -> bool:
    """T-949 材料可见性判定（跟随飞书侧权限，设计 §2.6）。

    规则：chat 快照全员可见（拉取者必在群内，办公转述语义）→
    owner 本人可见 → perm 有效时（public ∨ 用户被授权 ∨ 所在群被授权）可见 →
    perm 缺失（missing_scope/拉取失败）对非 owner 保守不可见（推用户补授权）。
    viewer_open_id 为空（未绑定飞书）：只剩 chat 类型可见。
    """
    if str(item.get("type") or "") == "chat":
        return True
    if viewer_open_id and str(item.get("owner_open_id") or "") == viewer_open_id:
        return True
    perm = item.get("perm") or {}
    if not perm.get("pulled_at"):
        return False
    if perm.get("public"):
        return True
    if viewer_open_id and viewer_open_id in (perm.get("member_users") or []):
        return True
    if viewer_chats and (set(perm.get("member_chats") or []) & set(viewer_chats)):
        return True
    return False


def list_pool_materials(specflow_emp_base: Path,
                        viewer: dict | None = None) -> list[dict]:
    """材料池清单（三通道快照：id/类型/标题/摘要/文件/sha/大小/mtime，时间倒序）。

    title/summary 是人可读层（T-930 可读性补强）：minutes 取 title+artifacts.summary、
    docs 取首个 markdown 标题+首段、chats 取 watch 群名+首行消息。
    T-940：附 source_url/owner_open_id/owner_name（meta sidecar；按监听用户筛选
    与飞书原文直链；存量无 meta 降级空串）。
    T-949：附 perm 摘要；viewer（{"open_id", "chats"}）非空时按飞书权限过滤，
    None 不过滤（向后兼容/管理员视图）。
    """
    from specflow.feishu_pool.paths import pool_dirs
    pool = pool_dirs(specflow_emp_base)
    chat_names: dict[str, str] = {}
    try:
        from specflow.feishu_pool.pool_store import chat_sha8
        for c in load_watch_config(specflow_emp_base).get("chats") or []:
            name = str(c.get("name") or "")
            if name:
                chat_names[chat_sha8(str(c.get("chat_id", "")))] = name
    except Exception:
        pass
    items: list[dict] = []
    for sub, prefix, ntype, ext in (("docs", "fd-", "feishu_doc", ".md"),
                                    ("minutes", "fm-", "feishu_minutes", ".json")):
        d = pool[sub]
        if not d.is_dir():
            continue
        for f in sorted(d.glob(f"{prefix}*{ext}")):
            if f.name.endswith(".meta.json"):      # sidecar 不是材料
                continue
            content = f.read_text(encoding="utf-8", errors="replace")
            if ntype == "feishu_doc":
                title, summary = _md_title_summary(f)
            else:
                title, summary = _minutes_title_summary(f)
            m = _read_meta_sidecar(f)
            items.append({
                "id": f"{prefix[:-1]}:{f.stem[len(prefix):]}",
                "type": ntype, "file": f"{sub}/{f.name}",   # 带目录前缀（T-939：material-content 白名单/前端 imgmap 推导依赖）
                "title": title, "summary": summary[:80],
                "sha": pool_store.sha12(content),
                "size": f.stat().st_size, "mtime": f.stat().st_mtime,
                "source_url": str(m.get("source_url") or ""),
                "owner_open_id": str(m.get("owner_open_id") or ""),
                "owner_name": str(m.get("owner_name") or ""),
                "perm": m.get("perm") or {},          # T-949：权限元数据摘要
            })
    chats_root = pool["chats"]
    if chats_root.is_dir():
        for f in sorted(chats_root.rglob("*.md")):
            title, summary = _md_title_summary(f)
            if not title:
                title = chat_names.get(f.parent.name, "")
            items.append({
                "id": f"chat:{f.parent.name}/{f.stem}", "type": "chat",
                "file": f"chats/{f.parent.name}/{f.name}",
                "title": title or f.stem, "summary": summary[:80],
                "sha": pool_store.sha12(f.read_text(encoding="utf-8",
                                                    errors="replace")),
                "size": f.stat().st_size, "mtime": f.stat().st_mtime,
                "source_url": "", "owner_open_id": "", "owner_name": "",
            })
    if viewer is not None:
        items = [i for i in items
                 if material_visible(i, str(viewer.get("open_id") or ""),
                                     set(viewer.get("chats") or []))]
    items.sort(key=lambda i: -i["mtime"])
    return items


def _topic_modules(workspace_root: Path) -> dict[str, list[str]]:
    """T-992：话题模块派生——已确认 mentions 边 → FR 锚点 module。

    拍板②：不做自由文本字段（FR→模块目录已存在且被 covers 门禁维护，第二
    套词表必然漂移）；关联不到 FR 的话题（闲聊/日常沟通/spec 未落）模块留空，
    语义自洽。响应时派生不落库，mentions 边确认后下一请求自动可见。
    """
    try:
        from specflow.feishu_pool import facts
        from specstd.anchors import scan_anchors
        anchors = scan_anchors(workspace_root)
        mods: dict[str, set[str]] = {}
        for l in facts.load_links(workspace_root):
            if l.get("status") != "confirmed" or l.get("edge") != "mentions":
                continue
            src = str(l.get("src", ""))
            if not src.startswith("tp:"):
                continue
            info = anchors.get(str(l.get("dst", "")))
            mod = (getattr(info, "module", "") or "") if info else ""
            if mod:
                mods.setdefault(src, set()).add(mod)
        return {k: sorted(v) for k, v in mods.items()}
    except Exception:
        return {}


def list_pool_topics(specflow_emp_base: Path, workspace_root: Path) -> dict:
    """话题清单：卡片（私有区 _topics.yaml 状态制，T-948 含全部状态）
    + 已确认（共享区；T-949 合并为单一存储后此区分退役）。
    T-992：每卡附 modules（FR 锚点派生，拍板②——关联不到留空）。
    T-993 D5：附 cross_suggestions（确定性预筛零 LLM——跨群候选关联，
    rejected 对不重复推荐；LLM 精筛由 /topics/cross-refine 按需触发）。"""
    from specflow.feishu_pool import cross_chat as xc
    from specflow.feishu_pool import facts
    from specflow.feishu_pool import topic_cluster as tc
    candidates = tc._load_candidates(specflow_emp_base)   # 含旧文件迁移+字段归一化
    confirmed = facts.load_topics(workspace_root)
    mods = _topic_modules(workspace_root)
    for t in candidates:
        t["modules"] = mods.get(str(t.get("id")), [])
    for t in confirmed:
        t["modules"] = mods.get(str(t.get("id")), [])
    # 已处理对（confirmed 已关联 / rejected 已忽略）均不再重复推荐
    done_pairs = {xc.pair_key(str(l.get("src", "")), str(l.get("dst", "")))
                  for l in facts.load_links(workspace_root)
                  if l.get("edge") == "relates"}
    pool_cards = [t for t in candidates if t.get("status") != "rejected"] + confirmed
    suggestions = xc.suggest_cross_chat_relations(pool_cards, done_pairs)
    return {"candidates": candidates, "confirmed": confirmed,
            "cross_suggestions": suggestions}


def update_image_caption(specflow_emp_base: Path, material_stem: str,
                         placeholder: str, caption: str) -> dict:
    """图片 caption 人工补写（复核兜底环节；by=manual）。"""
    from specflow.feishu_pool import captions as cap_mod
    from specflow.feishu_pool.paths import pool_dirs
    pool = pool_dirs(specflow_emp_base)
    for sub in ("docs", "chats", "minutes"):
        cand = pool[sub]
        if not cand.is_dir():
            continue
        for f in cand.rglob(f"{material_stem}.imgmap.json"):
            return cap_mod.update_caption(f, placeholder, caption, by="manual")
    raise KeyError(f"材料 imgmap 不存在: {material_stem}")


# ══════════════════════════════════════════════════════════
# T-939：材料原文读取 + 图片字节代理（详情弹层）
# ══════════════════════════════════════════════════════════

# 材料相对路径白名单：docs|minutes|chats 前缀 + md|json|jsonl 扩展（防私有区外泄；
# T-948 增 jsonl：chats 消息事实源，/chat-messages 端点复用本校验）
_MATERIAL_FILE_RE = re.compile(
    r"^(docs|minutes|chats)/[A-Za-z0-9_\-./]+\.(md|json|jsonl)$")

_IMG_MIME = ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
             (b"GIF8", "image/gif"))


def _safe_material_path(specflow_emp_base: Path, rel_file: str) -> Path | None:
    """材料相对路径安全解析（白名单前缀 + resolve 防穿越；非法返回 None）。"""
    rel = (rel_file or "").strip()
    if not _MATERIAL_FILE_RE.fullmatch(rel):
        return None
    base = (specflow_emp_base / "feishu_pool").resolve()
    p = (base / rel).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        return None
    return p


def read_material_content(specflow_emp_base: Path, rel_file: str) -> dict:
    """材料原文读取（详情弹层数据源；纯读私有区）。

    - docs/chats → 原文文本（markdown）
    - minutes → 可读化文本（title/summary）+ raw JSON（前端折叠展示）
    - docs 附带 imgmap 条目列表（前端 [图片#N] 内嵌图与描述编辑共用）
    """
    p = _safe_material_path(specflow_emp_base, rel_file)
    if p is None:
        return {"ok": False, "error": f"非法材料路径: {rel_file}"}
    if not p.is_file():
        return {"ok": False, "error": f"材料不存在: {rel_file}"}
    out: dict = {"ok": True, "file": rel_file, "images": []}
    if rel_file.startswith("minutes/"):
        out["type"] = "feishu_minutes"
        out["raw"] = p.read_text(encoding="utf-8", errors="replace")
        title, summary = _minutes_title_summary(p)
        out["content"] = (f"# {title}\n\n{summary}" if title or summary
                          else out["raw"])
    else:
        out["type"] = "chat" if rel_file.startswith("chats/") else "feishu_doc"
        out["content"] = p.read_text(encoding="utf-8", errors="replace")
    if rel_file.startswith("docs/") or rel_file.startswith("chats/"):
        # T-952：chats 同样附 imgmap（时间轴富渲染的 key→caption 映射；
        # post 内嵌图与 image 消息均在 imgmap——T-952a 起统一序号池）
        imgmap_path = p.with_suffix(".imgmap.json")
        if imgmap_path.is_file():
            try:
                m = json.loads(imgmap_path.read_text(encoding="utf-8"))
                out["images"] = [
                    {"placeholder": k, **(v if isinstance(v, dict) else {})}
                    for k, v in m.items()]
            except Exception:
                out["images"] = []
    return out


def _download_image(media_key: str, emp: str = "") -> bytes:
    """下载图片字节（复用 captions 同源链路：docs +media-download）。"""
    from specflow.feishu_pool.captions import _download_image as _dl
    return _dl(media_key, emp=emp)


def fetch_image_by_key(material_base: Path, message_id: str,
                    media_key: str, emp: str = "") -> dict:
    """T-952/955b：聊天图片按 (message_id, media_key) 直取（时间轴富渲染用）。

    im +messages-resources-download --type image（实测 2026-08-19：返回
    data.saved_path 落盘产物；旧实现走 docs +media-download --media-key 为
    臆断契约——该 flag 不存在，聊天图从未下载成功过）。
    下载→读回→删临时文件；磁盘缓存 {材料区}/feishu_pool/_imgcache/{sha16}.bin。
    emp 非空时按该用户飞书身份下载（T-956 多用户身份隔离一致性）。
    """
    if not message_id or not media_key:
        return {"ok": False, "error": "message_id/media_key 为空"}
    cache_dir = Path(material_base) / "feishu_pool" / "_imgcache"
    cache = cache_dir / f"{hashlib.sha256(media_key.encode('utf-8')).hexdigest()[:16]}.bin"
    if cache.is_file():
        data = cache.read_bytes()
        return {"ok": True, "data": data, "mime": _sniff_mime(data)}
    seed = f"{message_id}|{media_key}"
    tmp_name = (f"tmp-dl-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
                ".bin")
    try:
        _run_lark(["im", "+messages-resources-download", "--as", "user",
                   "--message-id", message_id, "--file-key", media_key,
                   "--type", "image", "--output", tmp_name],
                  timeout=120, emp=emp)
        tmp = Path(tmp_name)
        if not tmp.is_file():
            return {"ok": False, "error": "下载产物未找到（CLI 输出路径异常）"}
        data = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
    except ValueError as e:
        Path(tmp_name).unlink(missing_ok=True)
        return {"ok": False, "error": f"图片下载失败: {e}"}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return {"ok": True, "data": data, "mime": _sniff_mime(data)}


def _sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"                          # 缺省 png（与既有代理一致）


def fetch_chat_file(material_base: Path, message_id: str,
                    file_key: str, file_name: str = "",
                    emp: str = "") -> dict:
    """T-955：聊天附件文件下载（消息附件可打开）。

    im +messages-resources-download 按 message_id+file_key 拉（CLI 落 cwd
    临时名 → 读回字节 → 删临时文件）；磁盘缓存 {材料区}/feishu_pool/_imgcache/
    {sha16}.bin（同图/同附件只下载一次）。返回 {ok, data(bytes), file_name}。
    emp 非空时按该用户飞书身份下载（T-956 多用户身份隔离一致性）。
    """
    if not message_id or not file_key:
        return {"ok": False, "error": "message_id/file_key 为空"}
    cache_dir = Path(material_base) / "feishu_pool" / "_imgcache"
    seed = f"{message_id}|{file_key}"
    cache = cache_dir / f"{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}.bin"
    if cache.is_file():
        return {"ok": True, "data": cache.read_bytes(),
                "file_name": file_name or "attachment"}
    tmp_name = (f"tmp-dl-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
                ".bin")
    try:
        _run_lark(["im", "+messages-resources-download", "--as", "user",
                   "--message-id", message_id, "--file-key", file_key,
                   "--type", "file", "--output", tmp_name],
                  timeout=180, emp=emp)
        tmp = Path(tmp_name)
        if not tmp.is_file():
            return {"ok": False, "error": "下载产物未找到（CLI 输出路径异常）"}
        data = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
    except ValueError as e:
        Path(tmp_name).unlink(missing_ok=True)
        return {"ok": False, "error": f"附件下载失败: {e}"}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return {"ok": True, "data": data, "file_name": file_name or "attachment"}


def fetch_material_image(specflow_emp_base: Path, imgmap_file: str,
                         placeholder: str, emp: str = "") -> dict:
    """图片字节代理（前端 <img src> 直连）：imgmap 条目 media_key →

    下载 → 磁盘缓存（_imgcache/{sha16}.bin，同图只下载一次）→
    {ok, data(bytes), mime（魔数推断，缺省 png）}。纯读 + 材料目录内缓存。
    emp 非空时按该用户飞书身份下载（T-956 多用户身份隔离一致性）。
    """
    p = _safe_material_path(specflow_emp_base, imgmap_file)
    if p is None or not p.is_file():
        return {"ok": False, "error": f"imgmap 不存在: {imgmap_file}"}
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
        entry = m.get(placeholder) or {}
    except Exception:
        return {"ok": False, "error": f"imgmap 解析失败: {imgmap_file}"}
    if not isinstance(entry, dict):
        return {"ok": False, "error": f"imgmap 条目非法: {placeholder}"}
    media_key = str(entry.get("media_key", "") or "")
    if not media_key:
        return {"ok": False,
                "error": f"{placeholder} 无 media_key（占位符扫描产物，无法取图）"}
    cache = (p.parent / "_imgcache"
             / f"{hashlib.sha256(media_key.encode('utf-8')).hexdigest()[:16]}.bin")
    if cache.is_file():
        data = cache.read_bytes()
    else:
        try:
            data = _download_image(media_key, emp=emp)
        except Exception as e:
            return {"ok": False, "error": f"图片下载失败: {e}"}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    mime = next((v for magic, v in _IMG_MIME if data.startswith(magic)),
                "image/png")
    return {"ok": True, "data": data, "mime": mime}


# ══════════════════════════════════════════════════════════
# 选择器数据源（同步设置弹层；全部只读 --as user）
# ══════════════════════════════════════════════════════════

# T-937/T-938：list_my_chats 缓存（key=工号；条目 = (过期时间戳, 结果)）。
# stale-while-revalidate：有缓存立即返回（过期返旧值 + stale 标记 + 后台刷新），
# 配合 watcher chats_warmup_job（interval 5min）预热——弹层打开秒出，不等 CLI。
_chats_cache: dict[str, tuple[float, dict]] = {}
_CHATS_CACHE_TTL = 60.0
_chats_refreshing: set[str] = set()


def _now() -> float:
    return time.time()


def _chats_cache_key() -> str:
    from specstd.workspace import get_context_emp_no
    return get_context_emp_no() or ""


def _friendly_lark_error(e: Exception) -> str:
    """CLI 错误人话化（T-941/T-942）：授权类错误 → 纯人话一句
    （不拼技术原文——弹层黄横幅已给授权入口，原文噪音用户实锄不需要；
    排查走后端日志）。其余错误原样透传。"""
    msg = str(e)
    if "missing_scope" in msg or "missing required scope" in msg:
        return "飞书授权缺少权限——请点击弹层顶部「重新授权」补全后重试"
    if "认证未就绪" in msg or "not logged in" in msg:
        return "飞书账号未绑定——请点击弹层顶部「绑定飞书」完成授权"
    return msg


def _fetch_my_chats(key: str) -> dict:
    """全量拉取并写缓存（key 即 emp，透传 _run_lark 身份隔离）。失败不缓存。

    实测定案（2026-08-18，CLI 1.0.85）：①--types 不接受逗号多值
    （报 invalid_argument "p2p group"）——单值 group；②响应字段为
    data.chats（非 items）；③T-944：单聊本期不支持不显示——只拉
    group（顺带全量耗时减半）。p2p 兼容字段保留（旧缓存/防御解析）。"""
    out: dict = {"items": [], "errors": []}
    try:
        payload = _run_lark(["im", "+chat-list", "--as", "user",
                             "--types", "group", "--sort", "active_time",
                             "--page-all"], emp=key)
    except Exception as e:
        out["errors"].append(_friendly_lark_error(e))
        return out
    data = payload.get("data") or {}
    for it in (data.get("chats") or data.get("items") or []):
        chat_id = str(it.get("chat_id", ""))
        if not chat_id:
            continue
        out["items"].append({
            "chat_id": chat_id,
            "name": str(it.get("name", "") or ""),
            "chat_mode": str(it.get("chat_mode", "group") or "group"),
            "peer_open_id": str(it.get("p2p_target_id", "") or ""),
        })
    if not out["errors"]:
        _chats_cache[key] = (_now() + _CHATS_CACHE_TTL, out)
    return out


def _fetch_my_chats_quick(key: str, limit: int) -> dict:
    """快速预览（T-944）：单页 --page-size N（按活跃排序=最近活跃群），
    无 page-all 不翻页——秒出；不读/写缓存（预览不污染全量缓存）。"""
    out: dict = {"items": [], "errors": []}
    try:
        payload = _run_lark(["im", "+chat-list", "--as", "user",
                             "--types", "group", "--sort", "active_time",
                             "--page-size", str(limit)], emp=key)
    except Exception as e:
        out["errors"].append(_friendly_lark_error(e))
        return out
    data = payload.get("data") or {}
    for it in (data.get("chats") or data.get("items") or []):
        chat_id = str(it.get("chat_id", ""))
        if not chat_id:
            continue
        out["items"].append({
            "chat_id": chat_id,
            "name": str(it.get("name", "") or ""),
            "chat_mode": "group",
            "peer_open_id": str(it.get("p2p_target_id", "") or ""),
        })
    return out


def _refresh_chats_async(key: str) -> None:
    """过期缓存的后台刷新（daemon 线程；在选去重——同 key 并发只跑一个）。"""
    if key in _chats_refreshing:
        return
    _chats_refreshing.add(key)

    def _run():
        try:
            _fetch_my_chats(key)
        except Exception:
            pass                      # _fetch 内部已记 errors，这里只防线程外泄
        finally:
            _chats_refreshing.discard(key)

    threading.Thread(target=_run, daemon=True,
                     name=f"feishu-chats-refresh-{key}").start()


def list_my_chats(emp: str = "", limit: int = 0) -> dict:
    """我的群聊列表（group only，T-944 单聊不显示）。

    limit>0：快速预览路径（单页最近活跃 N 群，秒出，不碰缓存）——
    供弹层首屏先行渲染，全量随后台预热/二次全量调用补齐。
    limit=0：stale-while-revalidate（有缓存立即返，过期返旧值+后台刷新）。"""
    if limit and limit > 0:
        key = (emp or "").strip() or _chats_cache_key()
        return _fetch_my_chats_quick(key, limit)
    key = (emp or "").strip() or _chats_cache_key()
    hit = _chats_cache.get(key)
    if hit:
        if hit[0] <= _now():
            _refresh_chats_async(key)
            return {**hit[1], "stale": True}
        return hit[1]
    return _fetch_my_chats(key)


def search_users(query: str) -> dict:
    """通讯录用户搜索：contact +search-user --has-chatted。
    query 为空 → 空列表（不调 CLI，避免无关键词扫全量）。"""
    out = {"items": [], "errors": []}
    query = (query or "").strip()
    if not query:
        return out
    try:
        payload = _run_lark(["contact", "+search-user", "--as", "user",
                             "--query", query, "--has-chatted"])
    except Exception as e:
        out["errors"].append(_friendly_lark_error(e))
        return out
    data = payload.get("data") or {}
    for it in (data.get("users") or data.get("items") or []):
        open_id = str(it.get("open_id", ""))
        if not open_id:
            continue
        out["items"].append({
            "open_id": open_id,
            "name": str(it.get("name") or it.get("localized_name") or ""),
            "email": str(it.get("enterprise_email") or it.get("email") or ""),
            "department": str(it.get("department") or ""),
        })
    return out


def _parse_doc_results(payload: dict) -> list[dict]:
    """docs +search 结果解析（em 高亮剥离 + owner 标注；共用解析）。"""
    parsed: list[dict] = []
    for it in (payload.get("data") or {}).get("results") or []:
        meta = it.get("result_meta") or {}
        token = str(meta.get("token", ""))
        if not token:
            continue
        title = str(it.get("title_highlighted") or it.get("title") or "")
        parsed.append({
            "token": token,
            "title": title.replace("<em>", "").replace("</em>", ""),
            "url": str(meta.get("url") or ""),
            "doc_type": str(meta.get("doc_types") or ""),
            "owner_id": str(meta.get("owner_id") or ""),
            "owner_name": str(meta.get("owner_name") or ""),
        })
    return parsed


def search_docs(query: str) -> dict:
    """按文档名全局搜索（T-941：与按用户检索解耦——无需先选用户，
    直接搜名字；结果带产出人标注供勾选）。纯读。"""
    out: dict = {"items": [], "errors": []}
    query = (query or "").strip()
    if not query:
        return out
    try:
        payload = _run_lark(["docs", "+search", "--as", "user",
                             "--query", query, "--page-size", "50"])
    except Exception as e:
        out["errors"].append(_friendly_lark_error(e))
        return out
    out["items"] = _parse_doc_results(payload)
    return out


def search_user_docs(open_id: str, query: str = "") -> dict:
    """按用户搜文档：docs +search → 应用侧按 owner_id 过滤
    （CLI --filter owner_ids 2026-08-17 实测不生效——对照实验定案）。
    召回边界：当前用户可见文档 ∩ 该用户产出（诚实呈现）。"""
    out: dict = {"items": [], "errors": []}
    open_id = (open_id or "").strip()
    if not open_id:
        out["errors"].append("open_id 必填")
        return out
    try:
        payload = _run_lark(["docs", "+search", "--as", "user",
                             "--query", query or "", "--page-size", "50"])
    except Exception as e:
        out["errors"].append(_friendly_lark_error(e))
        return out
    out["items"] = [d for d in _parse_doc_results(payload)
                    if d["owner_id"] == open_id]
    return out


# 飞书云文档链接（host 含 feishu；typ=docx|wiki；token 末段捕获）
_DOC_LINK_RE = r"https?://[A-Za-z0-9.-]*feishu[A-Za-z0-9.-]*/{typ}/([A-Za-z0-9]+)"


def resolve_doc_link(input_str: str) -> dict:
    """链接/token → 文档标识（T-937 粘贴解析；纯读）。

    分流定案（2026-08-18 实测）：
    - /docx/<tok> URL → 本地解析零 CLI（路径末段即 obj_token；title 缺省，
      落池后材料池可读层 _md_title_summary 自然补标题）
    - /wiki/<tok> URL → wiki +node-get（node_token ≠ obj_token 必须经 CLI；
      返回 obj_token/title/owner；非 wiki 的普通云文档 404 故 docx 不走此通道）
    - 裸 token → 本地透传（兼容旧习惯，零 CLI）
    - minutes/base/sheets 等其他链接 → 明确错误（watch docs 仅云文档）
    """
    raw = (input_str or "").strip()
    if not raw:
        return {"ok": False, "error": "输入为空：粘贴云文档链接（/docx/ 或 /wiki/）或裸 token"}
    url_clean = raw.split("?")[0].split("#")[0].rstrip("/")
    m = re.search(_DOC_LINK_RE.format(typ="docx"), raw)
    if m:
        return {"ok": True, "items": [
            {"token": m.group(1), "url": url_clean, "doc_type": "docx"}]}
    m = re.search(_DOC_LINK_RE.format(typ="wiki"), raw)
    if m:
        try:
            payload = _run_lark(["wiki", "+node-get", "--as", "user",
                                 "--node-token", raw])
        except Exception as e:
            return {"ok": False, "error": str(e)}
        data = payload.get("data") or {}
        token = str(data.get("obj_token", "")).strip()
        if not token:
            return {"ok": False, "error": f"node-get 未返回 obj_token: {payload}"}
        return {"ok": True, "items": [{
            "token": token,
            "title": str(data.get("title", "") or ""),
            "url": url_clean,
            "doc_type": str(data.get("obj_type", "") or ""),
            "owner_open_id": str(data.get("owner", "") or ""),
        }]}
    # 非 URL：裸 token 透传（单段字母数字）
    if "://" not in raw and re.fullmatch(r"[A-Za-z0-9]+", raw):
        return {"ok": True, "items": [{"token": raw}]}
    return {"ok": False,
            "error": "无法识别：监听文档仅支持飞书云文档（/docx/ 或 /wiki/）链接或裸 token"}
