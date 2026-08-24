"""topic_material.py — 话题↔材料（文档/妙记）关联推荐（T-1014，仿 T-993 D5）。

确定性预筛（零 LLM，纯读）+ 人工确认写 references 边（material_links.yaml）。
只推荐不自动挂边；群聊快照不在推荐范围（话题已通过 message_ids/window
直连群聊原文，重复建边无意义）。

预筛条件（全满足才入选）：
- 话题非 rejected 且 category != chat（闲聊不关联材料）
- 材料类型限 feishu_doc / feishu_minutes
- 时间接近：材料 mtime 与话题 window 重叠或间距 ≤7 天（window 缺失放行——
  诚实不拦，靠语义条件把关，同 cross_chat._windows_close 口径）
- 语义沾边：标题相似 ≥0.4（SequenceMatcher）或关键词命中 ≥1
  （妙记带 artifacts.keywords 直接求交；文档无关键词，用话题 keywords
  在材料 title+summary 文本中的包含命中）
- (tp, mat) 未被 confirmed/rejected（references 有向边，键不归一化）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher

_TITLE_SIM = 0.4
_WINDOW_DAYS = 7


def _parse_ts(v) -> datetime | None:
    s = str(v or "")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _mtime_near_window(mtime: float, window: list) -> bool:
    """材料 mtime（秒级时间戳）与话题 window（ISO 起止）间距 ≤7 天。"""
    if not window:
        return True                     # 窗口缺失不拦（诚实放行）
    t0 = _parse_ts(window[0])
    t1 = _parse_ts(window[-1] if len(window) > 1 else None) or t0
    if t0 is None or not mtime:
        return True
    mt = datetime.fromtimestamp(float(mtime))
    return t0 - timedelta(days=_WINDOW_DAYS) <= mt \
        <= (t1 or t0) + timedelta(days=_WINDOW_DAYS)


def _keyword_hits(topic: dict, material: dict) -> list[str]:
    """关键词命中清单：妙记求交集；文档看话题关键词在材料文本中的包含。"""
    kws = [str(k) for k in (topic.get("keywords") or []) if str(k)]
    if not kws:
        return []
    m_kws = {str(k) for k in (material.get("keywords") or []) if str(k)}
    if m_kws:                           # 妙记：结构化关键词求交
        return sorted(k for k in kws if k in m_kws)
    text = f"{material.get('title') or ''}\n{material.get('summary') or ''}"
    return [k for k in kws if k in text]


def suggest_topic_materials(topics: list[dict], materials: list[dict],
                            done: set[tuple[str, str]]) -> list[dict]:
    """确定性预筛：话题 × 文档/妙记 → 候选关联（纯读零 LLM）。

    Args:
        topics: 话题卡列表（候选 + 已确认，调用方组装）
        materials: 材料清单（list_pool_materials 条目；chat 类型函数内过滤）
        done: 已处理 (tp_id, material_id) 对（confirmed/rejected 均不再推荐）

    Returns:
        [{src, dst, score, reasons}]，按 score 降序；
        score = 标题相似度 + 0.2 × 关键词命中数（上限 1.0）
    """
    cards = [t for t in (topics or [])
             if isinstance(t, dict) and t.get("id")
             and str(t.get("status") or "") != "rejected"
             and str(t.get("category") or "routine") != "chat"]
    mats = [m for m in (materials or [])
            if isinstance(m, dict)
            and m.get("type") in ("feishu_doc", "feishu_minutes") and m.get("id")]
    done = done or set()
    out: list[dict] = []
    for t in cards:
        for m in mats:
            key = (str(t["id"]), str(m["id"]))
            if key in done:
                continue
            if not _mtime_near_window(float(m.get("mtime") or 0),
                                      t.get("window") or []):
                continue
            title_sim = SequenceMatcher(
                None, str(t.get("title", "")),
                str(m.get("title", ""))).ratio()
            hits = _keyword_hits(t, m)
            if title_sim < _TITLE_SIM and not hits:
                continue
            reasons = []
            if title_sim >= _TITLE_SIM:
                reasons.append(f"标题相似 {title_sim:.2f}")
            if hits:
                reasons.append(f"关键词命中 {hits}")
            score = min(1.0, title_sim + 0.2 * len(hits))
            out.append({"src": key[0], "dst": key[1],
                        "score": round(score, 2), "reasons": reasons})
    out.sort(key=lambda c: (-c["score"], c["src"], c["dst"]))
    return out


def materials_by_topic(links: list[dict],
                       mat_index: dict[str, dict]) -> dict[str, list[dict]]:
    """confirmed references 边 → {tp_id: [{id,type,title,file}]}（话题卡挂材料区）。

    断链诚实跳过（材料已删/未同步的 dst 不出渣数据）；同话题下按材料 id 排序。
    """
    out: dict[str, list[dict]] = {}
    for l in links or []:
        if str(l.get("edge") or "") != "references" \
                or l.get("status") != "confirmed":
            continue
        src, dst = str(l.get("src", "")), str(l.get("dst", ""))
        if not src.startswith("tp:"):
            continue
        m = mat_index.get(dst)
        if m is None:
            continue
        out.setdefault(src, []).append({
            "id": m["id"], "type": m["type"],
            "title": str(m.get("title") or m["id"]),
            "file": str(m.get("file") or ""),
        })
    for v in out.values():
        v.sort(key=lambda x: x["id"])
    return out
