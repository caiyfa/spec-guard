"""test_cross_chat.py — 跨群话题关联推荐单测（T-993 F1，设计 D1-D3）。

覆盖：
- 预筛条件矩阵：跨群命中/同群排除/分类不同排除/闲聊排除/时间过远排除/
  rejected 排除/语义不沾排除
- 键规范化（pair_key 小 id 在前）与 score 排序
- related_map：连通分量入口（A-B、B-C → A 含 C）
- LLM 精筛：verdict 落注/单对失败保留/整体异常降级
全部离线。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specflow.feishu_pool import cross_chat as xc  # noqa: E402


def _card(tid, sha, title, *, category="requirement", keywords=(), day="2026-08-07",
          status="confirmed"):
    return {"id": tid, "chat_sha8": sha, "title": title, "summary": "s",
            "category": category, "keywords": list(keywords), "status": status,
            "window": [f"{day}T14:00", f"{day}T15:00"]}


def test_prefilter_hits_cross_chat_pair():
    """同分类跨群 + 标题相似 + 时间近 → 命中，键规范化小 id 在前。"""
    topics = [
        _card("tp:bbb-20260807-01", "bbbbbb", "导出权限过滤方案"),
        _card("tp:aaa-20260807-01", "aaaaaa", "导出权限过滤讨论"),
    ]
    out = xc.suggest_cross_chat_relations(topics, rejected=set())
    assert len(out) == 1
    c = out[0]
    assert (c["src"], c["dst"]) == ("tp:aaa-20260807-01", "tp:bbb-20260807-01")
    assert c["score"] > 0 and any("标题相似" in r for r in c["reasons"])


def test_prefilter_keywords_intersection():
    """标题不似但关键词交集 → 命中且理由含关键词。"""
    topics = [
        _card("tp:aaa-20260807-01", "aaaaaa", "口径对齐", keywords=["绩效阈值"]),
        _card("tp:bbb-20260807-02", "bbbbbb", "指标讨论", keywords=["绩效阈值", "SIT"]),
    ]
    out = xc.suggest_cross_chat_relations(topics, rejected=set())
    assert len(out) == 1
    assert any("关键词交集" in r for r in out[0]["reasons"])


def test_prefilter_exclusions():
    """同群/分类不同/闲聊/时间过远/rejected/语义不沾 → 全排除。"""
    base = dict(day="2026-08-07")
    cases = [
        # 同群
        ([_card("tp:aaa-01", "aaaaaa", "导出权限过滤方案"),
          _card("tp:aaa-02", "aaaaaa", "导出权限过滤讨论")], set()),
        # 分类不同
        ([_card("tp:aaa-01", "aaaaaa", "导出权限过滤方案", category="requirement"),
          _card("tp:bbb-01", "bbbbbb", "导出权限过滤讨论", category="test")], set()),
        # 闲聊
        ([_card("tp:aaa-01", "aaaaaa", "午饭吃什么好", category="chat"),
          _card("tp:bbb-01", "bbbbbb", "午饭吃什么呀", category="chat")], set()),
        # 时间过远（>7 天）
        ([_card("tp:aaa-01", "aaaaaa", "导出权限过滤方案"),
          _card("tp:bbb-01", "bbbbbb", "导出权限过滤讨论", day="2026-08-20")], set()),
        # rejected 对
        ([_card("tp:aaa-01", "aaaaaa", "导出权限过滤方案"),
          _card("tp:bbb-01", "bbbbbb", "导出权限过滤讨论")],
         {("tp:aaa-01", "tp:bbb-01")}),
        # 语义不沾（标题不似 + 无关键词交集；注：中文常用字会使字级相似度
        # 虚高，预筛宽容 + LLM 精筛/人判断把关是设计分层，此处取零共享对）
        ([_card("tp:aaa-01", "aaaaaa", "集群扩容"),
          _card("tp:bbb-01", "bbbbbb", "生日会")], set()),
    ]
    for topics, rejected in cases:
        assert xc.suggest_cross_chat_relations(topics, rejected=rejected) == [], \
            f"应被排除: {[t['id'] for t in topics]}"


def test_prefilter_rejected_key_order_insensitive():
    """rejected 键与卡顺序无关（规范化键生效）。"""
    topics = [
        _card("tp:zzz-01", "zzzzzz", "导出权限过滤方案"),
        _card("tp:aaa-01", "aaaaaa", "导出权限过滤讨论"),
    ]
    out = xc.suggest_cross_chat_relations(topics, rejected=set())
    assert len(out) == 1
    assert (out[0]["src"], out[0]["dst"]) == ("tp:aaa-01", "tp:zzz-01")
    # 反向键也能挡住
    assert xc.suggest_cross_chat_relations(
        topics, rejected={("tp:zzz-01", "tp:aaa-01")}) == []


def test_related_map_connected_component():
    """confirmed 边 → 双向邻接表（A-B、B-C → A 的关联含 C）。"""
    rel = [{"src": "tp:a", "dst": "tp:b"}, {"src": "tp:b", "dst": "tp:c"},
           {"src": "tp:a", "dst": "FR-012"}]        # 非 tp 端防御性忽略
    m = xc.related_map(rel)
    assert set(m["tp:a"]) == {"tp:b"}
    assert set(m["tp:b"]) == {"tp:a", "tp:c"}
    assert set(m["tp:c"]) == {"tp:b"}


def test_refine_with_llm_verdicts():
    """精筛 verdict 落注；单对坏 JSON 保留该对；异常整体降级。"""
    cands = [{"src": "tp:a", "dst": "tp:b", "score": 0.7, "reasons": []},
             {"src": "tp:c", "dst": "tp:d", "score": 0.6, "reasons": []}]
    by_id = {"tp:a": {"title": "t", "summary": "s", "keywords": [], "category": "test"},
             "tp:b": {"title": "t2", "summary": "s", "keywords": [], "category": "test"},
             "tp:c": {"title": "t3", "summary": "s", "keywords": [], "category": "test"},
             "tp:d": {"title": "t4", "summary": "s", "keywords": [], "category": "test"}}
    llm = MagicMock()
    llm.chat.side_effect = [
        {"content": json.dumps({"same": True, "confidence": 0.9, "reason": "同一缺陷"})},
        {"content": "not-json"},
    ]
    out = xc.refine_with_llm(cands, by_id, llm)
    assert out[0]["refined"] is True and out[0]["llm_same"] is True
    assert out[0]["llm_confidence"] == 0.9 and out[0]["llm_reason"] == "同一缺陷"
    assert out[1]["refined"] is False        # 单对失败保留原候选

    # 整体异常（chat 抛错到外层）→ 全部降级
    llm2 = MagicMock()
    llm2.chat.side_effect = RuntimeError("LLM 不可达")
    cands2 = [{"src": "tp:a", "dst": "tp:b", "score": 0.7, "reasons": []}]
    out2 = xc.refine_with_llm(cands2, by_id, llm2)
    assert out2[0]["refined"] is False
