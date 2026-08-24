"""topic_digest — 飞书话题的 agent 召回层（T-1011，通用能力非单用途专属）。

话题库读共享材料区（{ws}/.specflow/feishu_pool/_topics.yaml，T-949 后
群聊快照与话题库均为工作区公共资产）。三条消费通道共用同一过滤口径：
- A 摘要注入：build_digest() → system prompt「飞书话题」块（存在性）
- B topic 工具：list/search 复用 select_digest_cards 过滤与排序（按需取细节）
- C 关键词命中：match_topic_cards(user_message) → 命中卡注入该轮消息

时效分级（总控人 2026-08-24 拍板）：
- 近 3 天：全部非闲聊话题（含 draft——用户确认概率低，不等人工确认）
- 近 4~7 天：仅 priority=high
- 更旧 / rejected / category=chat：不进摘要与命中（工具 list 仍可全量查）
"""

from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path

RECENT_DAYS = 3          # 近 N 天全量（非闲聊）
HIGH_PRIORITY_DAYS = 7   # 近 N 天 high 优先级
DIGEST_CAP = 60          # 摘要行数上限（防爆 token）
MATCH_CAP = 3            # 关键词命中注入上限
_CACHE_TTL = 30.0        # 与 skill_loader 同口径的热加载缓存

_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}

# {(root_str, mtime): (ts, cards)}——mtime 变化即失效，TTL 兜底防 stat 抖动
_cache: dict[tuple[str, float], tuple[float, list[dict]]] = {}


def _material_root() -> Path | None:
    """共享材料区根（无激活工作区 → None，诚实降级为空摘要）。"""
    try:
        from specstd.workspace import specflow_dir
        return specflow_dir("")
    except Exception:
        return None


def load_topic_cards(material_root: Path) -> list[dict]:
    """读话题库并归一化（复用 topic_cluster 的 T-948/T-991 字段归一）。"""
    from specflow.feishu_pool import topic_cluster as tc
    key = (str(material_root), 0.0)
    try:
        mtime = (material_root / "feishu_pool" / "_topics.yaml").stat().st_mtime
        key = (str(material_root), mtime)
    except OSError:
        pass
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    cards = tc._load_candidates(material_root)
    _cache.clear()
    _cache[key] = (time.monotonic(), cards)
    return cards


def card_day(card: dict) -> date | None:
    """话题日期：window[0]（ISO '2026-08-07T14:00' 或 yyyymmdd）→ date。"""
    win = card.get("window") or []
    raw = str(win[0]) if win else ""
    digits = "".join(ch for ch in raw[:10] if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def select_digest_cards(cards: list[dict], today: date | None = None,
                        recent_days: int = RECENT_DAYS,
                        high_days: int = HIGH_PRIORITY_DAYS) -> list[dict]:
    """时效分级过滤 + 排序（新→旧，同级 high 优先、消息量次之）。

    规则：rejected 与闲聊（chat）永不进摘要；近 recent_days 天全量；
    recent_days~high_days 天仅 high；更旧不注入。日期不可解析的卡保守
    按最新处理（宁可多注入一条，不漏用户刚聊的话题）。
    """
    today = today or date.today()
    picked: list[tuple[int, dict]] = []
    for c in cards:
        if c.get("status") == "rejected" or c.get("category") == "chat":
            continue
        d = card_day(c)
        age = (today - d).days if d else 0
        if age > high_days:
            continue
        if age > recent_days and c.get("priority") != "high":
            continue
        picked.append((age, c))
    picked.sort(key=lambda t: (
        t[0],
        _PRIORITY_RANK.get(str(t[1].get("priority")), 1),
        -int(t[1].get("message_count") or 0)))
    return [c for _, c in picked]


def digest_line(c: dict) -> str:
    """单行摘要：id | 日期 | 优先级 | 状态 | 标题 | 结论摘要。"""
    d = card_day(c)
    day = d.strftime("%m-%d") if d else "????"
    return (f"- {c.get('id')} | {day} | {c.get('priority')} | {c.get('status')} | "
            f"{c.get('title')} | {str(c.get('summary', ''))[:80]}")


def build_digest(material_root: Path | None = None, today: date | None = None,
                 cap: int = DIGEST_CAP) -> str:
    """system prompt 注入用摘要块；无工作区/无话题返回空串（不注水）。"""
    root = material_root or _material_root()
    if root is None:
        return ""
    cards = select_digest_cards(load_topic_cards(root), today=today)
    if not cards:
        return ""
    lines = [digest_line(c) for c in cards[:cap]]
    more = len(cards) - cap
    if more > 0:
        lines.append(f"- …（另有 {more} 条，用 topic(action=list) 查看）")
    return "\n".join(lines)


def match_topic_cards(text: str, material_root: Path | None = None,
                      today: date | None = None, cap: int = MATCH_CAP) -> list[dict]:
    """用户消息关键词命中（确定性子串匹配，仿 match_skills_hint）。

    只在摘要 eligibility 集合内匹配（同等时效分级），命中计分：keywords
    每个 2 分、标题 1 分；按分排序取前 cap 条。
    """
    if not text:
        return []
    root = material_root or _material_root()
    if root is None:
        return []
    low = text.lower()
    scored: list[tuple[int, dict]] = []
    for c in select_digest_cards(load_topic_cards(root), today=today):
        score = sum(2 for kw in (c.get("keywords") or [])
                    if kw and str(kw).lower() in low)
        title = str(c.get("title") or "")
        if title and len(title) >= 4 and title.lower() in low:
            score += 1
        if score:
            scored.append((score, c))
    scored.sort(key=lambda t: -t[0])
    return [c for _, c in scored[:cap]]
