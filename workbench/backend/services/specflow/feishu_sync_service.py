"""feishu_sync_service.py — 飞书材料池拉取入库编排（飞书知识图谱一期 T4）。

三通道只读拉取（docs +fetch / minutes +search+detail / im +chat-messages-list），
产物落私有区材料池（.specflow/{emp}/feishu_pool/）。

纪律：
- 全部只读命令，绝不写飞书资源（S2 背景文档铁律）；
- 单条失败记 errors 不中断（诚实呈现，不静默降级）；
- watch 配置（feishu_watch.yaml）即显式授权载体——只拉取用户配置的群/文档。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

from specflow.feishu_pool.lark_cli import _run_lark  # noqa: F401  (测试 patch 点)
from specflow.feishu_pool import pool_store

_IMG_PLACEHOLDER_RE = re.compile(r"\[(图片#\d+)\]")

_DEFAULT_WATCH = {"chats": [], "docs": [], "minutes_days": 30, "chat_days": 7}


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
    return cfg


def save_watch_config(specflow_emp_base: Path, cfg: dict) -> dict:
    path = _watch_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(_DEFAULT_WATCH)
    clean.update({k: v for k, v in (cfg or {}).items() if k in _DEFAULT_WATCH})
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


def sync_minutes(specflow_emp_base: Path, days: int = 30) -> list[dict]:
    """妙记快照落池（minutes +search --owner-ids me → 逐个 +detail）。"""
    if days <= 0:
        return []
    found = _run_lark(["minutes", "+search", "--owner-ids", "me",
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


# ══════════════════════════════════════════════════════════
# 材料池总览页服务函数（三期 T-929，只读 + caption 人工补写）
# ══════════════════════════════════════════════════════════

def list_pool_materials(specflow_emp_base: Path) -> list[dict]:
    """材料池清单（三通道快照：id/类型/文件/sha/大小/mtime，时间倒序）。"""
    from specflow.feishu_pool.paths import pool_dirs
    pool = pool_dirs(specflow_emp_base)
    items: list[dict] = []
    for sub, prefix, ntype, ext in (("docs", "fd-", "feishu_doc", ".md"),
                                    ("minutes", "fm-", "feishu_minutes", ".json")):
        d = pool[sub]
        if not d.is_dir():
            continue
        for f in sorted(d.glob(f"{prefix}*{ext}")):
            items.append({
                "id": f"{prefix[:-1]}:{f.stem[len(prefix):]}",
                "type": ntype, "file": f.name,
                "sha": pool_store.sha12(f.read_text(encoding="utf-8",
                                                    errors="replace")),
                "size": f.stat().st_size, "mtime": f.stat().st_mtime,
            })
    chats_root = pool["chats"]
    if chats_root.is_dir():
        for f in sorted(chats_root.rglob("*.md")):
            items.append({
                "id": f"chat:{f.parent.name}/{f.stem}", "type": "chat",
                "file": f"{f.parent.name}/{f.name}",
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
