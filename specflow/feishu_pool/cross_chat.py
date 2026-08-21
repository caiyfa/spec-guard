"""cross_chat.py — 跨群话题关联推荐（T-993，设计 D3 两段式）。

确定性预筛（零 LLM，纯读）+ LLM 精筛（可选，异常诚实降级）。
铁律（D1）：只推荐不自动合并——关联是人确认的 relates 边（存
material_links.yaml），单群卡与 tp id 方案零改动；聚合由视图层连通分量表达。

预筛条件（全满足才入选，设计 D3）：
- 两卡 chat_sha8 不同（跨群）
- category 相同且非 chat（闲聊跨群关联无意义）
- 时间窗重叠或间距 ≤7 天（window 起点比较）
- 标题相似 ≥0.5 或 keywords 交集 ≥1
- (src, dst) 未被 rejected（防重复推荐；键规范化小 id 在前）
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

_TITLE_SIM = 0.5
_WINDOW_DAYS = 7

_REFINE_PROMPT = """你是话题关联判断助手。给定两张来自不同群聊的话题卡，判断它们
是否为同一主题的跨群讨论（同一需求/缺陷/方案在不同群的各自讨论）。

话题卡 A（id={a_id}）：标题「{a_title}」；摘要：{a_summary}；关键词：{a_keywords}；分类：{a_category}
话题卡 B（id={b_id}）：标题「{b_title}」；摘要：{b_summary}；关键词：{b_keywords}；分类：{b_category}

要求：不为仅主题相近但讨论对象不同的卡建立关联，宁缺毋滥。
严格输出 JSON：{{"same": true/false, "confidence": 0~1, "reason": "≤30字判断依据"}}
不要输出任何其他内容。"""


def pair_key(a: str, b: str) -> tuple[str, str]:
    """关联对规范化键（小 id 在前——与 facts 存储方向一致，防 (A,B)/(B,A) 重复）。"""
    return (a, b) if a <= b else (b, a)


def _parse_ts(v) -> datetime | None:
    s = str(v or "")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _windows_close(win_a: list, win_b: list) -> bool:
    """时间窗重叠或间距 ≤7 天（window[0]/[1] 为 ISO 起点/终点）。"""
    a0 = _parse_ts(win_a[0] if win_a else None)
    a1 = _parse_ts(win_a[-1] if len(win_a) > 1 else None) or a0
    b0 = _parse_ts(win_b[0] if win_b else None)
    b1 = _parse_ts(win_b[-1] if len(win_b) > 1 else None) or b0
    if a0 is None or b0 is None:
        return True            # 时间缺失不拦（诚实放行，靠语义条件把关）
    return a0 <= (b1 or b0) + timedelta(days=_WINDOW_DAYS) \
        and b0 <= (a1 or a0) + timedelta(days=_WINDOW_DAYS)


def suggest_cross_chat_relations(topics: list[dict],
                                 rejected: set[tuple[str, str]]) -> list[dict]:
    """确定性预筛：跨群卡两两配对 → 候选关联（纯读零 LLM）。

    Args:
        topics: 话题卡列表（调用方负责滤除 rejected 状态卡）
        rejected: 已处理的关联对集合（pair_key 规范化键——confirmed 已关联
            或 rejected 已忽略，均不再重复推荐）

    Returns:
        [{src, dst, score, reasons}]，按 score 降序；
        score = 标题相似度 + 0.2 × keywords 交集数（上限 1.0）
    """
    cards = [t for t in (topics or [])
             if isinstance(t, dict) and t.get("id") and t.get("chat_sha8")]
    norm_rejected = {pair_key(a, b) for (a, b) in (rejected or set())}
    out: list[dict] = []
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]
            if a["chat_sha8"] == b["chat_sha8"]:
                continue                      # 同群不跨
            ca = str(a.get("category") or "routine")
            cb = str(b.get("category") or "routine")
            if ca != cb or ca == "chat":
                continue                      # 分类不同/闲聊不关联
            if not _windows_close(a.get("window") or [], b.get("window") or []):
                continue                      # 时间相距过远
            key = pair_key(str(a["id"]), str(b["id"]))
            if key in norm_rejected:
                continue                      # 已忽略不再推荐（键双向归一）
            title_sim = SequenceMatcher(
                None, str(a.get("title", "")), str(b.get("title", ""))).ratio()
            kw_a = {str(k) for k in (a.get("keywords") or []) if str(k)}
            kw_b = {str(k) for k in (b.get("keywords") or []) if str(k)}
            kw_common = kw_a & kw_b
            if title_sim < _TITLE_SIM and not kw_common:
                continue                      # 语义都不沾边
            reasons = []
            if title_sim >= _TITLE_SIM:
                reasons.append(f"标题相似 {title_sim:.2f}")
            if kw_common:
                reasons.append(f"关键词交集 {sorted(kw_common)}")
            reasons.append(f"同分类 {ca}")
            score = min(1.0, title_sim + 0.2 * len(kw_common))
            out.append({"src": key[0], "dst": key[1], "score": round(score, 2),
                        "reasons": reasons})
    out.sort(key=lambda c: (-c["score"], c["src"], c["dst"]))
    return out


def related_map(relations: list[dict]) -> dict[str, list[str]]:
    """confirmed relates 边 → {topic_id: [关联的对方 id]}（视图层连通分量入口）。"""
    out: dict[str, list[str]] = {}
    for r in relations or []:
        src, dst = str(r.get("src", "")), str(r.get("dst", ""))
        if not src.startswith("tp:") or not dst.startswith("tp:"):
            continue
        out.setdefault(src, []).append(dst)
        out.setdefault(dst, []).append(src)
    return out


def refine_with_llm(candidates: list[dict], topics_by_id: dict, llm) -> list[dict]:
    """LLM 精筛（可选）：逐候选对判"是否同一主题"，附 confidence/reason。

    单对失败跳过保留原候选（refined=False）；整体异常（LLM 不可达等）
    诚实降级——全部原样返回（前端展示"未经模型复核"）。
    """
    if not candidates:
        return []

    def _content(resp) -> str:
        # LLMClient.chat 返回 (message, usage) tuple；测试 mock 返回 dict——两者兼容
        if isinstance(resp, tuple):
            resp = resp[0] if resp else {}
        return str((resp or {}).get("content", ""))

    try:
        for c in candidates:
            try:
                a = topics_by_id.get(c["src"]) or {}
                b = topics_by_id.get(c["dst"]) or {}
                raw = _content(llm.chat([{"role": "user", "content": _REFINE_PROMPT.format(
                    a_id=c["src"], a_title=a.get("title", ""),
                    a_summary=a.get("summary", ""),
                    a_keywords="、".join(a.get("keywords") or []),
                    a_category=a.get("category", ""),
                    b_id=c["dst"], b_title=b.get("title", ""),
                    b_summary=b.get("summary", ""),
                    b_keywords="、".join(b.get("keywords") or []),
                    b_category=b.get("category", ""))}])).strip()
                m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
                if m:
                    raw = m.group(1).strip()
                verdict = json.loads(raw)
                c["refined"] = True
                c["llm_same"] = bool(verdict.get("same"))
                c["llm_confidence"] = round(float(verdict.get("confidence") or 0), 2)
                c["llm_reason"] = str(verdict.get("reason") or "")[:60]
            except Exception:
                c["refined"] = False          # 单对失败：保留原候选不阻断
        return candidates
    except Exception:
        for c in candidates:
            c.setdefault("refined", False)
        return candidates
