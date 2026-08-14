"""pool_store.py — 材料快照落盘/读取（飞书知识图谱一期）。

纪律：
- 原文快照「拉取时刻冻结」，sha256-12 可复算；imgmap 与原文分离（替身文本可回填
  而不污染原文指纹）。
- 全部落私有区（.specflow/{emp}/feishu_pool/）；提升共享区走 review 服务，不在此层。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from specflow.feishu_pool.paths import pool_dirs


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def chat_sha8(chat_id: str) -> str:
    """群 id 脱敏（sha 截断 8 位；原始 chat_id 只出现在私有区配置中）。"""
    return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:8]


def save_doc_snapshot(specflow_emp_base: Path, doc_token: str, markdown: str,
                      imgmap: dict | None = None, source_url: str = "") -> dict:
    """文档快照落盘（fd-{token}.md + 可选 fd-{token}.imgmap.json）。"""
    d = pool_dirs(specflow_emp_base)["docs"]
    d.mkdir(parents=True, exist_ok=True)
    stem = f"fd-{doc_token}"
    (d / f"{stem}.md").write_text(markdown, encoding="utf-8")
    if imgmap is not None:
        (d / f"{stem}.imgmap.json").write_text(
            json.dumps(imgmap, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"node_id": f"fd:{doc_token}", "sha": sha12(markdown),
            "source_url": source_url, "file": f"docs/{stem}.md"}


def save_minutes_snapshot(specflow_emp_base: Path, minute_token: str,
                          detail_json: dict, source_url: str = "") -> dict:
    """妙记快照落盘（fm-{token}.json）。"""
    d = pool_dirs(specflow_emp_base)["minutes"]
    d.mkdir(parents=True, exist_ok=True)
    stem = f"fm-{minute_token}"
    raw = json.dumps(detail_json, ensure_ascii=False, indent=2)
    (d / f"{stem}.json").write_text(raw, encoding="utf-8")
    return {"node_id": f"fm:{minute_token}", "sha": sha12(raw),
            "source_url": source_url, "file": f"minutes/{stem}.json"}


def save_chat_snapshot(specflow_emp_base: Path, chat_id: str, day: str,
                       markdown: str) -> dict:
    """群聊快照落盘（chats/{chat_sha8}/{yyyymmdd}.md）。"""
    cs8 = chat_sha8(chat_id)
    d = pool_dirs(specflow_emp_base)["chats"] / cs8
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{day}.md").write_text(markdown, encoding="utf-8")
    return {"chat_sha8": cs8, "day": day, "sha": sha12(markdown),
            "file": f"chats/{cs8}/{day}.md"}


def load_imgmap(specflow_emp_base: Path, stem_file: Path) -> dict:
    """读取材料配套 imgmap（缺失返回空 dict）。"""
    imgmap_path = Path(stem_file).with_suffix(".imgmap.json")
    if not imgmap_path.is_file():
        return {}
    try:
        return json.loads(imgmap_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════
# 事件直写原语（三期 T-925，F6）
# ══════════════════════════════════════════════════════════

import time as _time

_SEEN_EVENTS_TTL = 7 * 86400   # event_id 去重表 TTL（7 天滚动）


def append_chat_lines(specflow_emp_base: Path, chat_id: str, day: str,
                      lines: list[str]) -> Path:
    """群聊快照追加写（事件直写主路径；与 sync_chat 覆盖写互补）。"""
    cs8 = chat_sha8(chat_id)
    d = pool_dirs(specflow_emp_base)["chats"] / cs8
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}.md"
    with open(f, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line.rstrip("\n") + "\n")
    return f


def _seen_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / "_seen_events.json"


def mark_event_seen(specflow_emp_base: Path, event_id: str) -> bool:
    """event_id 去重：首次见 → 登记返回 True；已见 → False（重复事件不双写）。"""
    path = _seen_path(specflow_emp_base)
    seen: dict = {}
    if path.is_file():
        try:
            seen = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            seen = {}
    now = _time.time()
    # TTL 滚动清理
    seen = {k: v for k, v in seen.items()
            if isinstance(v, (int, float)) and now - v < _SEEN_EVENTS_TTL}
    if event_id in seen:
        return False
    seen[event_id] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return True


def _senders_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / "_senders.json"


def _resolve_sender(open_id: str) -> str:
    """lark-cli 通讯录解析 open_id → 显示名（失败返回空串，调用方兜底）。"""
    from specflow.feishu_pool.lark_cli import _run_lark
    try:
        payload = _run_lark(["contact", "+get-user", "--user-id", open_id,
                             "--as", "user"])
        data = payload.get("data") or {}
        return str(data.get("name") or data.get("nickname") or "")
    except Exception:
        return ""


def sender_display(specflow_emp_base: Path, open_id: str) -> str:
    """open_id → 显示名（_senders.json 缓存；解析失败回退尾 6 位）。"""
    path = _senders_path(specflow_emp_base)
    cache: dict = {}
    if path.is_file():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    if open_id in cache:
        return cache[open_id]
    name = _resolve_sender(open_id)
    if not name:
        name = f"…{open_id[-6:]}"
    cache[open_id] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return name
