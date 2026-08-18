"""feishu_sync_service.py — 飞书材料池拉取入库编排（飞书知识图谱一期 T4）。

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
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from specflow.feishu_pool import pool_store
from specflow.feishu_pool.lark_cli import _run_lark  # noqa: F401  (测试 patch 点)

_IMG_PLACEHOLDER_RE = re.compile(r"\[(图片#\d+)\]")

_DEFAULT_WATCH = {"chats": [], "docs": [], "users": [],
                  "minutes_days": 30, "chat_days": 7}

_USER_SCOPES = {"group_sender", "minutes", "docs"}


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
    return cfg


def save_watch_config(specflow_emp_base: Path, cfg: dict) -> dict:
    path = _watch_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(_DEFAULT_WATCH)
    clean.update({k: v for k, v in (cfg or {}).items() if k in _DEFAULT_WATCH})
    clean["users"] = _clean_users(clean.get("users"))
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


def sync_doc(specflow_emp_base: Path, doc_token: str, url: str = "") -> dict:
    """文档快照落池（docs +fetch 只读）。"""
    payload = _run_lark(["docs", "+fetch", "--as", "user",
                         "--doc", doc_token, "--doc-format", "markdown"])
    data = payload.get("data") or {}
    content = str(data.get("content") or data.get("markdown") or "")
    imgmap = _imgmap_from_content(content, data.get("images"))
    return pool_store.save_doc_snapshot(
        specflow_emp_base, doc_token, content,
        imgmap=imgmap if imgmap else None, source_url=url)


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
    out = []
    for it in items:
        token = str(it.get("minute_token") or it.get("token") or "")
        if not token:
            continue
        detail = _run_lark(["minutes", "+detail", "--minute-tokens", token,
                            "--summary", "--keyword"])
        out.append(pool_store.save_minutes_snapshot(
            specflow_emp_base, token, detail.get("data") or {},
            source_url=str(it.get("url") or "")))
    return out


def _render_chat_lines(items: list) -> str:
    """消息列表 → [HH:MM] 发送人: 内容 行格式（图片消息留 [图片#N] 占位）。"""
    lines = []
    img_seq = 0
    for it in items:
        ms = int(it.get("create_time_ms") or it.get("create_time") or 0)
        hhmm = datetime.fromtimestamp(ms / 1000).strftime("%H:%M") if ms else "??:??"
        sender = str(it.get("sender_name") or it.get("sender") or "?")
        msg_type = str(it.get("msg_type") or "text")
        if msg_type == "text":
            body = str(it.get("text") or it.get("content") or "")
        elif msg_type == "image":
            img_seq += 1
            body = f"[图片#{img_seq}]"
        else:
            body = f"[{msg_type}消息]"
        lines.append(f"[{hhmm}] {sender}: {body}")
    return "\n".join(lines) + ("\n" if lines else "")


def sync_chat(specflow_emp_base: Path, chat_id: str, day: str) -> dict:
    """群聊快照落池（im +chat-messages-list 只读，按天归档）。"""
    payload = _run_lark(["im", "+chat-messages-list", "--as", "user",
                         "--chat-id", chat_id, "--page-size", "50"])
    items = (payload.get("data") or {}).get("items") or []
    markdown = _render_chat_lines(items)
    return pool_store.save_chat_snapshot(specflow_emp_base, chat_id, day, markdown)


def sync_all(specflow_emp_base: Path, cfg: dict | None = None) -> dict:
    """按 watch 配置全通道同步；单条失败记 errors 不中断。"""
    cfg = cfg if cfg is not None else load_watch_config(specflow_emp_base)
    out = {"docs": 0, "minutes": 0, "chats": 0, "errors": []}
    for doc in cfg.get("docs") or []:
        try:
            sync_doc(specflow_emp_base, str(doc.get("token", "")),
                     url=str(doc.get("url", "")))
            out["docs"] += 1
        except Exception as e:
            out["errors"].append(f"doc {doc.get('token', '?')}: {e}")
    try:
        out["minutes"] = len(sync_minutes(specflow_emp_base,
                                          int(cfg.get("minutes_days") or 0)))
    except Exception as e:
        out["errors"].append(f"minutes: {e}")
    today = datetime.now().strftime("%Y%m%d")
    for chat in cfg.get("chats") or []:
        try:
            sync_chat(specflow_emp_base, str(chat.get("chat_id", "")), today)
            out["chats"] += 1
        except Exception as e:
            out["errors"].append(f"chat {chat.get('chat_id', '?')}: {e}")
    return out


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


def sync_user_materials(specflow_emp_base: Path) -> dict:
    """用户材料轮询（设计 §4.3）：按 users[].scopes 拉指定用户妙记/文档落池。

    单用户/单文档失败记 errors 不中断（诚实呈现）。
    """
    cfg = load_watch_config(specflow_emp_base)
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
                    specflow_emp_base, minutes_days, owner_ids=[open_id]))
            except Exception as e:
                out["errors"].append(f"minutes {label}: {e}")
        if "docs" in scopes:
            r = _sync_user_docs(specflow_emp_base, open_id)
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
            sync_doc(specflow_emp_base, token, url=str(meta.get("url") or ""))
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


def list_pool_materials(specflow_emp_base: Path) -> list[dict]:
    """材料池清单（三通道快照：id/类型/标题/摘要/文件/sha/大小/mtime，时间倒序）。

    title/summary 是人可读层（T-930 可读性补强）：minutes 取 title+artifacts.summary、
    docs 取首个 markdown 标题+首段、chats 取 watch 群名+首行消息。
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
            content = f.read_text(encoding="utf-8", errors="replace")
            if ntype == "feishu_doc":
                title, summary = _md_title_summary(f)
            else:
                title, summary = _minutes_title_summary(f)
            items.append({
                "id": f"{prefix[:-1]}:{f.stem[len(prefix):]}",
                "type": ntype, "file": f.name,
                "title": title, "summary": summary[:80],
                "sha": pool_store.sha12(content),
                "size": f.stat().st_size, "mtime": f.stat().st_mtime,
            })
    chats_root = pool["chats"]
    if chats_root.is_dir():
        for f in sorted(chats_root.rglob("*.md")):
            title, summary = _md_title_summary(f)
            if not title:
                title = chat_names.get(f.parent.name, "")
            items.append({
                "id": f"chat:{f.parent.name}/{f.stem}", "type": "chat",
                "file": f"{f.parent.name}/{f.name}",
                "title": title or f.stem, "summary": summary[:80],
                "sha": pool_store.sha12(f.read_text(encoding="utf-8",
                                                    errors="replace")),
                "size": f.stat().st_size, "mtime": f.stat().st_mtime,
            })
    items.sort(key=lambda i: -i["mtime"])
    return items


def list_pool_topics(specflow_emp_base: Path, workspace_root: Path) -> dict:
    """话题清单：候选（私有区）+ 已确认（共享区）。"""
    import yaml

    from specflow.feishu_pool import facts
    from specflow.feishu_pool.paths import pool_dirs
    cand_path = pool_dirs(specflow_emp_base)["root"] / "_candidate_topics.yaml"
    candidates: list[dict] = []
    if cand_path.is_file():
        try:
            raw = yaml.safe_load(cand_path.read_text(encoding="utf-8")) or {}
            candidates = [t for t in (raw.get("topics") or [])
                          if isinstance(t, dict)]
        except Exception:
            candidates = []
    return {"candidates": candidates,
            "confirmed": facts.load_topics(workspace_root)}


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

# 材料相对路径白名单：docs|minutes|chats 前缀 + md|json 扩展（防私有区外泄）
_MATERIAL_FILE_RE = re.compile(
    r"^(docs|minutes|chats)/[A-Za-z0-9_\-./]+\.(md|json)$")

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
    if rel_file.startswith("docs/"):
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


def _download_image(media_key: str) -> bytes:
    """下载图片字节（复用 captions 同源链路：docs +media-download）。"""
    from specflow.feishu_pool.captions import _download_image as _dl
    return _dl(media_key)


def fetch_material_image(specflow_emp_base: Path, imgmap_file: str,
                         placeholder: str) -> dict:
    """图片字节代理（前端 <img src> 直连）：imgmap 条目 media_key →

    下载 → 磁盘缓存（_imgcache/{sha16}.bin，同图只下载一次）→
    {ok, data(bytes), mime（魔数推断，缺省 png）}。纯读 + 材料目录内缓存。
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
            data = _download_image(media_key)
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


def _fetch_my_chats(key: str) -> dict:
    """同步拉取并写缓存（key 即 emp，透传 _run_lark 身份隔离）。失败不缓存。"""
    out = {"items": [], "errors": []}
    try:
        payload = _run_lark(["im", "+chat-list", "--as", "user",
                             "--types", "p2p,group", "--sort", "active_time",
                             "--page-all"], emp=key)
    except Exception as e:
        out["errors"].append(str(e))
        return out
    items = (payload.get("data") or {}).get("items") or []
    for it in items:
        out["items"].append({
            "chat_id": str(it.get("chat_id", "")),
            "name": str(it.get("name", "") or ""),
            "chat_mode": str(it.get("chat_mode", "group") or "group"),
            "peer_open_id": str(it.get("p2p_target_id", "") or ""),
        })
    if not out["errors"]:
        _chats_cache[key] = (_now() + _CHATS_CACHE_TTL, out)
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


def list_my_chats(emp: str = "") -> dict:
    """我的群聊列表：im +chat-list --as user --types p2p,group。
    p2p 项附带 peer_open_id（前端置灰——本期不做私聊监听，设计 D2）。

    T-937：同工号 TTL 内存缓存；失败结果不缓存（重试即时生效）。
    T-938：① emp 显式参数（预热 job 传入；缺省 contextvar）；②身份隔离
    （emp 透传 _run_lark 的 USERPROFILE 注入，多用户各见其群）；
    ③ stale-while-revalidate——有缓存立即返回，过期返旧值（stale=True）
    并后台刷新，绝不现场等 CLI。"""
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
        out["errors"].append(str(e))
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


def search_user_docs(open_id: str, query: str = "") -> dict:
    """按用户搜文档：docs +search → 应用侧按 owner_id 过滤
    （CLI --filter owner_ids 2026-08-17 实测不生效——对照实验定案）。
    召回边界：当前用户可见文档 ∩ 该用户产出（诚实呈现）。"""
    out = {"items": [], "errors": []}
    open_id = (open_id or "").strip()
    if not open_id:
        out["errors"].append("open_id 必填")
        return out
    try:
        payload = _run_lark(["docs", "+search", "--as", "user",
                             "--query", query or "", "--page-size", "50"])
    except Exception as e:
        out["errors"].append(str(e))
        return out
    results = (payload.get("data") or {}).get("results") or []
    for it in results:
        meta = it.get("result_meta") or {}
        if str(meta.get("owner_id", "")) != open_id:
            continue
        token = str(meta.get("token", ""))
        if not token:
            continue
        title = str(it.get("title_highlighted") or it.get("title") or "")
        title = title.replace("<em>", "").replace("</em>", "")
        out["items"].append({
            "token": token,
            "title": title,
            "url": str(meta.get("url") or ""),
            "doc_type": str(meta.get("doc_types") or ""),
            "owner_id": open_id,
            "owner_name": str(meta.get("owner_name") or ""),
        })
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
