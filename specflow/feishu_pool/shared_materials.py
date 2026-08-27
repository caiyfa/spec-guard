"""shared_materials.py — 话题共享材料事实层（T-1029，T-1027 设计 D3/D4）。

职责切分（与 T-1015 references 判断边双轨并存，事实≠判断）：
- 事实推导（确定性零 LLM）：从话题关联的消息行提取「群里客观分享过」的
  飞书产品链接 → [{kind, token, url, message_id}]，随 message_ids 而来、
  可重算，落卡字段 shared_materials；
- 快照联接（纯读派生）：resolve 把事实映射到池内 fd-*/fm-* 快照并附标题，
  响应时派生不落库（同 modules/materials 口径）——消除回填时序问题。

D4 补拉（拍板①：即时单条补拉+失败诚实降级）的服务入口在 workbench
feishu_sync_service.fetch_topic_materials；GET 链路保持纯读纪律。
"""

from __future__ import annotations

from pathlib import Path

# 快照通道支持的材料类型（docs 通道只吃文档/文件类；sheets/base/wiki 无
# 离线快照通道——如实标注不可同步，前端灰显）
FETCHABLE_KINDS = ("docx", "doc", "minutes")


def derive_from_rows(rows) -> list[dict]:
    """消息行集 → 共享材料事实列表（去重保序；按 (url) 幂等）。

    行来自 chat_store.load_chat_jsonl 的 JSONL 事实源；已撤回行 content
    为「[已撤回]」天然无链接命中。facts 不含快照信息（那是 resolve 的活）。
    """
    from specflow.feishu_pool import chat_store as cs
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows or []:
        mid = str((r or {}).get("message_id") or "")
        for link in cs.extract_feishu_links(str((r or {}).get("content") or "")):
            if link["url"] in seen:
                continue
            seen.add(link["url"])
            out.append({"kind": str(link.get("kind") or ""),
                        "token": str(link.get("token") or ""),
                        "url": str(link.get("url") or ""),
                        "message_id": mid})
    return out


def index_message_rows(specflow_emp_base: Path, chat_sha8: str,
                       days=None) -> dict[str, dict]:
    """群×日范围（缺省=全目录）内 message_id → 消息行索引（仅 JSONL 事实源）。

    md-only 存量天不入索引——无行可推导时由调用方守卫（edit/regen 保持
    旧值不动），诚实不虚构。
    """
    from specflow.feishu_pool.paths import pool_dirs
    chats_root = pool_dirs(specflow_emp_base)["chats"] / chat_sha8
    if not chats_root.is_dir():
        return {}
    day_files = ([chats_root / f"{d}.jsonl" for d in sorted(set(days or []))]
                 if days else sorted(chats_root.glob("*.jsonl")))
    idx: dict[str, dict] = {}
    from specflow.feishu_pool import chat_store as cs
    for f in day_files:
        for r in cs.load_chat_jsonl(f):
            mid = str(r.get("message_id") or "")
            if mid:
                idx[mid] = r
    return idx


def attach_to_card(card: dict, rows_by_mid: dict[str, dict]) -> list[dict]:
    """按卡片的 message_ids 推导并写入 card["shared_materials"]（返回所挂清单）。

    关联 id 全部不在行索引里（md-only 存量卡）→ 不改写旧值（诚实守卫：
    手头没有数据就不覆盖既有推导）。空关联写 []（明确清空语义）。
    """
    ids = [str(m) for m in (card.get("message_ids") or [])]
    if not ids:
        card["shared_materials"] = []
        return []
    rows = [rows_by_mid[i] for i in ids if i in rows_by_mid]
    facts = derive_from_rows(rows)
    if not rows and "shared_materials" in card:
        return list(card["shared_materials"])       # 无数据不改写旧值
    card["shared_materials"] = facts
    return facts


# docx/doc/file 落 docs 目录（fd-{token}）；minutes 落 minutes 目录（fm-{token}）
_SNAPSHOT_SUBDIR = {"docx": "docs", "doc": "docs", "file": "docs",
                    "minutes": "minutes"}


def resolve(facts, specflow_emp_base: Path) -> list[dict]:
    """纯读联接：事实 → 附 snapshot_ref/title/in_pool/fetchable 的展示副本。

    快照存在性按 fd-{token}.md / fm-{token}.json 文件判定；标题取同名
    meta sidecar 的 title 字段（缺失留空——诚实不猜）。不改传入结构。
    """
    from specflow.feishu_pool.paths import pool_dirs
    pool = pool_dirs(specflow_emp_base)
    out: list[dict] = []
    for f in facts or []:
        kind = str(f.get("kind") or "")
        token = str(f.get("token") or "")
        ref = ""
        title = ""
        subdir = _SNAPSHOT_SUBDIR.get(kind)
        if subdir and token:
            stem = ("fd-" if subdir == "docs" else "fm-") + token
            marker = pool[subdir] / (f"{stem}.md" if subdir == "docs"
                                     else f"{stem}.json")
            if marker.is_file():
                ref = stem
                meta = pool[subdir] / f"{stem}.meta.json"
                if meta.is_file():
                    try:
                        import json
                        title = str((json.loads(
                            meta.read_text(encoding="utf-8")) or {}).get(
                            "title") or "")
                    except Exception:
                        title = ""
        out.append({"kind": kind, "token": token, "url": str(f.get("url") or ""),
                    "message_id": str(f.get("message_id") or ""),
                    "snapshot_ref": ref, "title": title,
                    "in_pool": bool(ref),
                    "fetchable": kind in FETCHABLE_KINDS})
    return out
