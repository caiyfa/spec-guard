"""chat_store.py — 群聊消息 JSONL 事实源（T-948 存储层核心）。

设计（docs/upgrade-plans/2026-08-19-T948-话题存储重构与协作加工-设计文档.md §2.1/§2.2）：
- chats/{sha8}/{yyyymmdd}.jsonl 是唯一事实源（每行一条消息，保 message_id）；
  {yyyymmdd}.md 与 .imgmap.json 是从 JSONL 派生的视图，可随时重建。
- 幂等合并：按 message_id 去重（同 id 覆盖——更新/撤回状态刷新）；
  拉取通道用飞书 message_id，事件通道无 id 用 "evt:{event_id}" 前缀键，
  下一次按天全量拉取时 evt 条目被同消息的 pull 版本吸收。
- 契约纪律：字段形状以 2026-08-19 对 lark-cli 1.0.85 实测快照为准
  （test_specstd/test_feishu_chat_store.py._CLI_SNAPSHOT）——data.messages 数组、
  create_time "YYYY-MM-DD HH:MM" 字符串、sender 嵌套对象、image_key 在
  content "[Image: {key}]" 内。禁止按代码期望造字段。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

_IMAGE_KEY_RE = re.compile(r"\[Image:\s*(.+?)\]")
_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")

# T-952 实测契约：post 内嵌图引用 ![Image](key)；file 自描述 <file key name/>
_POST_IMG_RE = re.compile(r"!\[Image\]\((.+?)\)")
_FILE_TAG_RE = re.compile(r'<file\s+key="([^"]*)"\s+name="([^"]*)"\s*/>')

# T-1016 实测契约（2026-08-26，feishu_cli_contract.MERGE_FORWARD_MESSAGE）：
# merge_forward content 为 <forwarded_messages> 包裹文本，内层每条消息
# "[ISOts+08:00] 发送人:" 头行 + 缩进内容行；内嵌图两种占位混排
# （![Image](key) 与 [Image: key]）。
_FWD_ANY_IMG_RE = re.compile(r"!\[Image\]\((.+?)\)|\[Image:\s*(.+?)\]")
_FWD_MSG_HEAD_RE = re.compile(r"^\[([^\]]+)\]\s+([^:：]+)[:：]\s*$")
_P_TAG_RE = re.compile(r"</?p>")

# T-1028 实测（2026-08-27）：文档分享的现场事实形态 = text 消息内纯 URL
# （fehorizon.feishu.cn 的 docx/sheets，带 query+fragment 变体）；产品域族
# 收编 feishu.cn/larksuite.com 两家官方域。kind 取路径段原词（docx/sheets/
# base/wiki/minutes/file），消费方（T-1029）按 token 匹配快照。
_FEISHU_LINK_RE = re.compile(
    r"https?://(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"(?:feishu\.cn|larksuite\.com)"
    r"/(docx|doc|sheets|base|wiki|minutes|file)/([A-Za-z0-9]+)"
    # 尾段零宽可空（*）：裸链接后紧跟空白时，+ 会把 token 末位回借给尾段
    r"[^\s<>\"'）)】」，。；：！？]*")
_TRAILING_PUNCT = ".,;:!?)》、，。；：！？」』）】"


def extract_feishu_links(content) -> list[dict]:
    """消息 content 内飞书产品链接确定性提取 → [{kind, token, url}]。

    零幻觉、可离线测试；与 msg_type 解耦——text/post/merge_forward 及将来
    钉案的卡片类 content 通吃。同 URL 去重（保序）；尾部中英文标点不吞。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in _FEISHU_LINK_RE.finditer(str(content or "")):
        url = m.group(0).rstrip(_TRAILING_PUNCT)
        if url in seen:
            continue
        seen.add(url)
        out.append({"kind": m.group(1), "token": m.group(2), "url": url})
    return out


def render_row_body(row: dict, img_slot=None) -> str:
    """单条消息行 → 可读正文（T-1028 D1「渲染保真降级制」三处口径共享实现）。

    此前的口径漂移（日级 md 保真 vs _load_window_source/compose 只留纯 text）
    即本函数要消灭的问题：任何类型至少一行人类可读——已知类型专属渲染；
    system/video_chat 按实测形状打标；未知类型（未来卡片类）降级为
    「[{type}消息] + 空白折叠截断摘要」，不再是纯占位。

    Args:
        row: JSONL 消息行
        img_slot: 图片占位回调 str(image_key)->str（日级视图传注入 imgmap 的
            闭包以分配序号）；None 时图片渲染为不可转述的静态 "[图片]"
    Returns:
        正文文本（不含时间戳/发言人前缀）
    """

    def _slot(key: str) -> str:
        return img_slot(key) if img_slot else "[图片]"

    mtype = str(row.get("msg_type") or "")
    content = str(row.get("content") or "")
    if mtype == "image":
        return _slot(str(row.get("image_key") or ""))
    if mtype == "post":
        # 文本主体 + 内嵌图逐一占位（内嵌图引用从文本中替换为占位符）
        text = content
        for key in (row.get("image_keys") or []):
            text = text.replace(f"![Image]({key})", _slot(key))
        return text or "[空 post]"
    if mtype == "file":
        fname = str(row.get("file_name") or "")
        return f"[文件] {fname}" if fname else "[文件]"
    if mtype == "merge_forward":
        # 单行内联展开（line_ids 一对一约束不破）——内层「发送人: 内容」
        # 拍平串联；内嵌图占位按出现顺序入 imgmap
        subs = parse_forwarded_messages(content)
        if not subs:
            return "[合并转发]"
        parts = []
        for s in subs:
            t = _FWD_ANY_IMG_RE.sub(
                lambda m: _slot((m.group(1) or m.group(2)).strip()),
                str(s.get("text") or ""))
            parts.append(f"{s.get('sender') or '?'}: {t}".rstrip())
        return "[合并转发] " + "；".join(parts)
    if mtype == "text":
        return content
    if mtype == "system":                    # 实测：会议开始/邀请入群等通知
        return f"[系统] {content.strip()}" if content.strip() else "[系统消息]"
    if mtype == "video_chat":                # 实测：视频通话开始（[Video call]）
        return "[视频通话]" + (f" {content.strip()}" if content.strip() else "")
    snippet = re.sub(r"\s+", " ", content).strip()
    return f"[{mtype}消息]" + (f" {snippet[:80]}" if snippet else "")


def extract_image_keys_from_post(content: str) -> list[str]:
    """post 消息 content 内嵌图引用提取（markdown 化 ![Image](key)，可多张）。"""
    return [m.group(1).strip() for m in _POST_IMG_RE.finditer(content or "")]


def parse_file_tag(content: str) -> tuple[str, str]:
    """file 消息 content 自描述标签解析 → (file_key, file_name)。"""
    m = _FILE_TAG_RE.search(content or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else ("", "")


def extract_image_keys_from_forward(content: str) -> list[str]:
    """merge_forward content 内嵌图 key 提取（两种占位混排，按文本出现顺序）。"""
    return [(m.group(1) or m.group(2)).strip()
            for m in _FWD_ANY_IMG_RE.finditer(content or "")]


def parse_forwarded_messages(content: str) -> list[dict]:
    """merge_forward content → 内层消息列表 [{ts, sender, text}]（图片占位保留在
    text，由渲染层替换为图/占位符；<p> 段落标签剥离）。

    非 <forwarded_messages> 包裹内容返回 []（调用方兜底原文展示）。
    """
    body = str(content or "")
    if "<forwarded_messages>" not in body:
        return []
    body = body.replace("<forwarded_messages>", "").replace(
        "</forwarded_messages>", "")
    subs: list[dict] = []
    for line in body.splitlines():
        head = _FWD_MSG_HEAD_RE.match(line) if not line.startswith((" ", "\t"))             else None
        if head:
            subs.append({"ts": head.group(1).strip(),
                         "sender": head.group(2).strip(), "lines": []})
        elif subs:
            subs[-1]["lines"].append(line.strip())
    return [{"ts": s["ts"], "sender": s["sender"],
             "text": _P_TAG_RE.sub(
                 "", " ".join(ln for ln in s["lines"] if ln)).strip()}
            for s in subs]


def extract_image_key(msg: dict) -> str:
    """image 消息 content 内提取 image_key（"[Image: {key}]"，Q5 实测）。"""
    if str(msg.get("msg_type") or "") != "image":
        return ""
    m = _IMAGE_KEY_RE.search(str(msg.get("content") or ""))
    return m.group(1).strip() if m else ""


def _ts_from_pull(raw: str) -> str:
    """CLI create_time "YYYY-MM-DD HH:MM[:SS]" → ISO 本地时间（补秒）。"""
    s = str(raw or "").strip()
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


def _ts_from_ms(ms) -> str:
    """事件毫秒时间戳 → ISO 本地时间（0/非法 → 空串，调用方兜底）。"""
    try:
        v = int(ms or 0)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    return datetime.fromtimestamp(v / 1000).isoformat(timespec="seconds")


def normalize_pull_message(raw: dict) -> dict:
    """拉取通道 CLI 消息（data.messages 元素）→ JSONL 行。

    T-952：post/file 的真实内容就在 content（实测契约）——post 为 markdown 化
    文本（内嵌图提取 image_keys，可多张）；file 为 <file key name/> 自描述标签
    （解析 file_name/file_key）；content 原样保留供前端富渲染。
    """
    sender = raw.get("sender") or {}
    deleted = bool(raw.get("deleted"))
    msg_type = str(raw.get("msg_type") or "text")
    content = str(raw.get("content") or "")
    image_keys: list[str] = []
    file_key = file_name = ""
    if not deleted:
        if msg_type == "post":
            image_keys = extract_image_keys_from_post(content)
        elif msg_type == "merge_forward":
            # T-1016：内嵌图提取（外层 message_id 配对下载依据），content 原样保留
            image_keys = extract_image_keys_from_forward(content)
        elif msg_type == "file":
            file_key, file_name = parse_file_tag(content)
    row = {
        "message_id": str(raw.get("message_id") or ""),
        "position": str(raw.get("message_position") or ""),
        "sender_id": str(sender.get("id") or ""),
        "sender_name": str(sender.get("name") or ""),
        "ts": _ts_from_pull(raw.get("create_time")),
        "msg_type": msg_type,
        "content": "[已撤回]" if deleted else content,
        "image_key": "" if deleted else extract_image_key(raw),
        "reply_to": str(raw.get("reply_to") or ""),
        "mentions": raw.get("mentions") or [],
        "origin": "pull",
    }
    if image_keys:
        row["image_keys"] = image_keys
    if file_key or file_name:
        row["file_key"] = file_key
        row["file_name"] = file_name
    return row


def normalize_event_message(ev: dict) -> dict:
    """事件通道消息（watcher im.message.receive_v1）→ JSONL 行。

    无 message_id → "evt:{event_id}" 幂等键（与拉取键天然不冲突）；
    position 空，排序回退 (ts, sender_id)。
    """
    event_id = str(ev.get("event_id") or "")
    if not event_id:
        # 无 event_id 的极端事件：内容指纹兜底键（保证幂等键非空）
        seed = "|".join([str(ev.get("chat_id") or ""), str(ev.get("create_time") or ""),
                         str(ev.get("sender_id") or ""), str(ev.get("content") or "")])
        import hashlib
        event_id = "h_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    msg_type = str(ev.get("message_type") or "text")
    content = str(ev.get("content") or "")
    if msg_type == "image":
        # 事件通道 content 为原始 JSON 串或 image_key，尽力提取；失败留占位
        key = _IMAGE_KEY_RE.search(content)
        content = key.group(0) if key else "[图片]"
    return {
        "message_id": f"evt:{event_id}",
        "position": "",
        "sender_id": str(ev.get("sender_id") or ""),
        "sender_name": str(ev.get("sender_name") or ""),
        "ts": _ts_from_ms(ev.get("create_time")) or datetime.now().isoformat(
            timespec="seconds"),
        "msg_type": msg_type,
        "content": content,
        "image_key": (_IMAGE_KEY_RE.search(content).group(1).strip()
                      if msg_type == "image" and _IMAGE_KEY_RE.search(content) else ""),
        "reply_to": "",
        "mentions": [],
        "origin": "event",
    }


# ══════════════════════════════════════════════════════════
# JSONL 幂等合并（事实源唯一写入口）
# ══════════════════════════════════════════════════════════

def _sort_key(r: dict):
    p = str(r.get("position") or "")
    return (int(p) if p.isdigit() else float("inf"),
            str(r.get("ts") or ""), str(r.get("sender_id") or ""))


def load_chat_jsonl(day_file: Path) -> list[dict]:
    """读 JSONL（缺失/损坏行跳过；缺失文件返回空 list）。"""
    f = Path(day_file)
    if not f.is_file():
        return []
    out: list[dict] = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("message_id"):
            out.append(row)
    return out


def merge_chat_jsonl(day_file: Path, incoming: list[dict]) -> dict:
    """按 message_id 幂等合并：新键追加、同键覆盖（更新/撤回刷新）。

    合并后按 (position→ts→sender_id) 排序全量重写（临时文件 + 原子替换，
    进程内并发安全的前提是调用方串行化——sync_all/直写都在锁内调用）。
    """
    f = Path(day_file)
    current = {r["message_id"]: r for r in load_chat_jsonl(f)}
    added = updated = 0
    for row in incoming or []:
        mid = str((row or {}).get("message_id") or "")
        if not mid:
            continue
        if mid in current:
            if current[mid] != row:
                current[mid] = row
                updated += 1
        else:
            current[mid] = row
            added += 1
    rows = sorted(current.values(), key=_sort_key)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(f.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, f)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"added": added, "updated": updated}


# ══════════════════════════════════════════════════════════
# md / imgmap 派生视图
# ══════════════════════════════════════════════════════════

def render_md_from_jsonl(day_file: Path) -> tuple[str, dict, list[str]]:
    """JSONL → (md 文本, imgmap, 行号→message_id 对齐表)。

    md 行格式 "[HH:MM] 发送人: 内容"（与聚类 _PROMPT 约定一致）；
    逐行正文统一走 render_row_body（T-1028 三处口径共享渲染）；
    line_ids 与 md 消息行一一对应（聚类 msg_lines → message_id 换算依据）。
    """
    rows = sorted(load_chat_jsonl(day_file), key=_sort_key)
    lines: list[str] = []
    line_ids: list[str] = []
    imgmap: dict = {}

    def _img(ph_key: str) -> str:
        ph = f"[图片#{len(imgmap) + 1}]"
        imgmap[ph] = {"media_key": ph_key, "caption": "",
                      "caption_by": "none", "status": "pending"}
        return ph

    for r in rows:
        hhmm = str(r.get("ts") or "")[11:16] or "??:??"
        sender = str(r.get("sender_name") or r.get("sender_id") or "?")
        body = render_row_body(r, img_slot=_img)
        lines.append(f"[{hhmm}] {sender}: {body}")
        line_ids.append(str(r.get("message_id") or ""))
    md = "\n".join(lines) + ("\n" if lines else "")
    return md, imgmap, line_ids


def rebuild_views(day_file: Path) -> Path | None:
    """重建派生视图（同目录 {day}.md + {day}.imgmap.json）；无 JSONL 返回 None。

    imgmap 与既有 docs 通道同构（captions._iter_pending / material-image 代理
    / caption 人工补写全部直接复用）；无图片时不写 imgmap 文件。
    """
    f = Path(day_file)
    if not f.is_file():
        return None
    md, imgmap, _ = render_md_from_jsonl(f)
    md_file = f.with_suffix(".md")
    md_file.write_text(md, encoding="utf-8")
    imgmap_file = f.with_suffix(".imgmap.json")
    if imgmap:
        imgmap_file.write_text(
            json.dumps(imgmap, ensure_ascii=False, indent=2), encoding="utf-8")
    elif imgmap_file.is_file():
        imgmap_file.unlink()      # 图片全部消失（撤回）时清理残留视图
    return md_file
