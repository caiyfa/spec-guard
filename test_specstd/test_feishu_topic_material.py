"""test_feishu_topic_material.py — 话题↔材料关联预筛单测（T-1014）。

零外部依赖（纯函数）：预筛条件逐条证真/证伪 + materials_by_topic 派生。
时间口径：mtime/window 均按本地时区构造，测试用 datetime(...).timestamp()
动态求值，任何时区下稳定。
"""

from datetime import datetime

from specflow.feishu_pool import topic_material as tm


def _topic(**over):
    t = {"id": "tp:aaaaaa-20260807-01", "title": "断档分析报告排查",
         "summary": "s", "keywords": ["断档", "邮箱"], "category": "requirement",
         "status": "draft",
         "window": ["2026-08-07T14:00", "2026-08-07T15:00"]}
    t.update(over)
    return t


def _mat(**over):
    m = {"id": "fm:abc", "type": "feishu_minutes", "title": "周会",
         "summary": "s", "keywords": ["断档", "排期"], "file": "minutes/fm-abc.json",
         "mtime": datetime(2026, 8, 7, 16, 0).timestamp()}
    m.update(over)
    return m


def test_hit_by_minutes_keyword_intersection():
    out = tm.suggest_topic_materials([_topic()], [_mat()], done=set())
    assert [(s["src"], s["dst"]) for s in out] == [("tp:aaaaaa-20260807-01", "fm:abc")]
    assert any("断档" in r for r in out[0]["reasons"])


def test_hit_by_doc_text_contains():
    """文档无结构化关键词：话题关键词在材料 title+summary 文本包含即命中。"""
    m = _mat(id="fd:tokA", type="feishu_doc", title="数据口径说明",
             keywords=[], summary="本文说明断档统计口径")
    out = tm.suggest_topic_materials([_topic()], [m], done=set())
    assert len(out) == 1 and out[0]["dst"] == "fd:tokA"


def test_hit_by_title_similarity_without_keywords():
    t = _topic(keywords=[], title="断档分析报告排查")
    m = _mat(keywords=[], title="断档分析报告排查纪要")
    out = tm.suggest_topic_materials([t], [m], done=set())
    assert len(out) == 1 and any("标题相似" in r for r in out[0]["reasons"])


def test_excluded_when_far_in_time():
    m = _mat(mtime=datetime(2026, 9, 20, 10, 0).timestamp())   # 窗口外 44 天
    assert tm.suggest_topic_materials([_topic()], [m], done=set()) == []


def test_time_missing_window_passes():
    """window 缺失诚实放行（时间不把门，语义条件兜底）。"""
    t = _topic(window=[])
    out = tm.suggest_topic_materials([t], [_mat()], done=set())
    assert len(out) == 1


def test_excluded_chat_category_and_rejected():
    assert tm.suggest_topic_materials(
        [_topic(category="chat")], [_mat()], done=set()) == []
    assert tm.suggest_topic_materials(
        [_topic(status="rejected")], [_mat()], done=set()) == []


def test_excluded_chat_type_material():
    """群聊快照不进推荐（话题已 message_ids 直连群聊原文）。"""
    m = _mat(id="chat:aaaaaa/20260807", type="chat", keywords=[])
    assert tm.suggest_topic_materials([_topic()], [m], done=set()) == []


def test_done_pair_not_recommended():
    done = {("tp:aaaaaa-20260807-01", "fm:abc")}
    assert tm.suggest_topic_materials([_topic()], [_mat()], done=done) == []


def test_score_sorted_desc():
    t = _topic()
    m1 = _mat(id="fm:low", title="无关标题", keywords=["断档"])
    m2 = _mat(id="fm:high", title="断档分析报告排查", keywords=["断档"])
    out = tm.suggest_topic_materials([t], [m1, m2], done=set())
    assert [s["dst"] for s in out] == ["fm:high", "fm:low"]


def test_materials_by_topic_only_confirmed_references():
    links = [
        {"src": "tp:a", "dst": "fm:x", "edge": "references", "status": "confirmed"},
        {"src": "tp:a", "dst": "fm:y", "edge": "references", "status": "rejected"},
        {"src": "tp:a", "dst": "FR-001", "edge": "mentions", "status": "confirmed"},
        {"src": "tp:a", "dst": "fm:ghost", "edge": "references", "status": "confirmed"},
    ]
    idx = {"fm:x": {"id": "fm:x", "type": "feishu_minutes", "title": "纪要X",
                    "file": "minutes/fm-x.json"}}
    out = tm.materials_by_topic(links, idx)
    assert [m["id"] for m in out["tp:a"]] == ["fm:x"]   # rejected/mentions/断链均剔除
