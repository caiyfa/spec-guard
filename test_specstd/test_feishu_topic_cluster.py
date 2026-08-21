"""test_feishu_topic_cluster.py — LLM 话题聚类作业单测（飞书知识图谱一期 T6）。

覆盖：
- 群聊快照 → 候选话题（id 规范 tp:{chat_sha8}-{yyyymmdd}-{seq}）
- 增量归并：标题相似 + 同窗 → 沿用旧 id（图谱重建不依赖 LLM 复现）
- LLM 输出非 JSON → 记 error 跳过（诚实呈现不中断）
- T-946：时效窗口（过期快照不聚）+ 按群配置（chat_windows 覆盖/关闭）
"""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
import yaml

from specflow.feishu_pool import topic_cluster as tc


def _make_emp(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    chat_dir = emp / "feishu_pool" / "chats" / "3f9a2c"
    chat_dir.mkdir(parents=True)
    (chat_dir / "20260807.md").write_text(
        "[14:00] 张三: 导出要按平台过滤吗\n"
        "[14:01] 李四: 按 corpCode+groupLevel\n"
        "[15:00] 张三: 中午吃什么\n", encoding="utf-8")
    return emp


def _llm_returning(payload: str):
    llm = MagicMock()
    llm.chat.return_value = {"content": payload}
    return llm


_OK_PAYLOAD = ('{"topics": [{"title": "导出权限过滤",'
               ' "summary": "按 corpCode 过滤",'
               ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')


def test_cluster_window_filters_expired_days(tmp_path):
    """T-946：时效窗口——default_days=7 时，8 天前的快照过期不聚，今日正常。"""
    emp = _make_emp(tmp_path)
    chat_dir = emp / "feishu_pool" / "chats" / "3f9a2c"
    today = date.today().strftime("%Y%m%d")
    old = (date.today() - timedelta(days=8)).strftime("%Y%m%d")
    (chat_dir / f"{today}.md").write_text("[14:00] 张三: 今日话题\n", encoding="utf-8")
    (chat_dir / f"{old}.md").write_text("[14:00] 张三: 过期话题\n", encoding="utf-8")
    llm = _llm_returning(_OK_PAYLOAD)
    tc.cluster_chat_snapshots(emp, llm, default_days=7)
    # LLM 只被窗口内文件调用（今日/7 天内；8 天前 old 与旧 20260807 被过滤）。
    # call 形状：chat([messages]) → c[0][0] 是 messages 列表，首条 dict 取 content。
    prompts = [c[0][0][0]["content"] for c in llm.chat.call_args_list]
    assert any(today in p for p in prompts)
    assert not any(old in p for p in prompts)
    assert not any("20260807" in p for p in prompts)


def test_cluster_chat_disabled_via_windows(tmp_path):
    """T-946：按群配置——chat_windows[sha]=0 关闭该群话题生成。"""
    emp = _make_emp(tmp_path)
    llm = _llm_returning(_OK_PAYLOAD)
    tc.cluster_chat_snapshots(emp, llm, days=["20260807"],
                              chat_windows={"3f9a2c": 0}, default_days=7)
    llm.chat.assert_not_called()      # 该群关闭 → 零 LLM 调用


def test_cluster_per_chat_window_overrides_default(tmp_path):
    """T-946：per-chat 窗口覆盖 default——群 A 窗口 30 含 10 天前文件，群 B 默认 7 不含。"""
    emp = tmp_path / ".specflow" / "u1"
    for sha, in (("aaaaaa",), ("bbbbbb",)):
        d = emp / "feishu_pool" / "chats" / sha
        d.mkdir(parents=True)
        old10 = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
        (d / f"{old10}.md").write_text("[14:00] 张三: 十天前\n", encoding="utf-8")
    llm = _llm_returning(_OK_PAYLOAD)
    tc.cluster_chat_snapshots(emp, llm,
                              chat_windows={"aaaaaa": 30, "bbbbbb": 7},
                              default_days=7)
    # 群 aaaaaa（窗口 30 含 10 天前）被聚类；群 bbbbbb（窗口 7）10 天前过期被过滤
    assert llm.chat.call_count == 1


def test_cluster_produces_candidate_topics(tmp_path):
    emp = _make_emp(tmp_path)
    llm = _llm_returning(
        '{"topics": [{"title": "导出权限过滤",'
        ' "summary": "按 corpCode+groupLevel 过滤",'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
    assert len(out) == 1
    t = out[0]
    assert t["id"].startswith("tp:3f9a2c-20260807-")
    assert t["message_count"] == 2 and t["chat_sha8"] == "3f9a2c"
    # T-948：话题卡落状态制单文件 _topics.yaml（带 v2 字段）
    cand = emp / "feishu_pool" / "_topics.yaml"
    assert cand.is_file()
    saved = yaml.safe_load(cand.read_text(encoding="utf-8"))["topics"]
    assert saved[0]["id"] == t["id"]
    assert saved[0]["status"] == "draft" and saved[0]["rev"] == 1
    assert "agent_origin" in saved[0]


def test_incremental_merge_reuses_id(tmp_path):
    emp = _make_emp(tmp_path)
    llm = _llm_returning(
        '{"topics": [{"title": "导出权限过滤",'
        ' "summary": "按 corpCode 过滤",'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')
    first = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
    # 第二次聚类：标题略变（相似）、同窗同日 → 沿用旧 id
    llm2 = _llm_returning(
        '{"topics": [{"title": "导出权限过滤讨论",'
        ' "summary": "修订：按 corpCode+groupLevel 过滤",'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')
    second = tc.cluster_chat_snapshots(emp, llm2, days=["20260807"])
    assert second[0]["id"] == first[0]["id"]
    assert second[0]["summary"].startswith("修订")


def test_new_topic_gets_next_seq(tmp_path):
    emp = _make_emp(tmp_path)
    llm = _llm_returning(
        '{"topics": ['
        '{"title": "导出权限过滤", "summary": "s1",'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2},'
        '{"title": "午饭话题", "summary": "s2",'
        ' "msg_range": ["[15:00]", "[15:00]"], "participants_count": 1}]}')
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
    ids = [t["id"] for t in out]
    assert ids[0].endswith("-01") and ids[1].endswith("-02")


def test_llm_bad_json_skipped_with_error(tmp_path):
    emp = _make_emp(tmp_path)
    llm = _llm_returning("这不是JSON")
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
    assert out == []
    errors = tc.last_errors()
    assert errors and "20260807" in errors[0]


# ══════════════════════════════════════════════════════════
# T-926：话题演进链（continues）
# ══════════════════════════════════════════════════════════

def _make_emp_with_old_topic(tmp_path):
    """两日快照 + 昨日已有话题 tp:3f9a2c-20260807-01。"""
    emp = tmp_path / ".specflow" / "u1"
    chat_dir = emp / "feishu_pool" / "chats" / "3f9a2c"
    chat_dir.mkdir(parents=True)
    (chat_dir / "20260807.md").write_text(
        "[14:00] 张三: 导出要按平台过滤吗\n", encoding="utf-8")
    (chat_dir / "20260808.md").write_text(
        "[10:00] 李四: 接着昨天，权限过滤还要考虑 groupLevel\n", encoding="utf-8")
    cand = emp / "feishu_pool" / "_candidate_topics.yaml"
    cand.write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 导出权限过滤\n"
        "    summary: 按 corpCode 过滤\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
    return emp


def test_continues_linked_when_llm_judges(tmp_path):
    emp = _make_emp_with_old_topic(tmp_path)
    llm = _llm_returning(
        '{"topics": [{"title": "导出权限过滤补充", "continues": "tp:3f9a2c-20260807-01",'
        ' "summary": "还要考虑 groupLevel",'
        ' "msg_range": ["[10:00]", "[10:00]"], "participants_count": 1}]}')
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260808"])
    assert out[0].get("continues") == "tp:3f9a2c-20260807-01"


def test_continues_hallucination_dropped(tmp_path):
    emp = _make_emp_with_old_topic(tmp_path)
    llm = _llm_returning(
        '{"topics": [{"title": "导出权限过滤补充", "continues": "tp:ghost-不存在",'
        ' "summary": "还要考虑 groupLevel",'
        ' "msg_range": ["[10:00]", "[10:00]"], "participants_count": 1}]}')
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260808"])
    assert "continues" not in out[0]              # 幻觉 id 丢弃，话题本体保留
    assert out[0]["title"] == "导出权限过滤补充"


# ══════════════════════════════════════════════════════════
# T-947：话题人工介入工作流（草案 / 提交 / 编辑 / 重生成）
# ══════════════════════════════════════════════════════════

def _make_emp_for_draft(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    chat_dir = emp / "feishu_pool" / "chats" / "3f9a2c"
    chat_dir.mkdir(parents=True)
    (chat_dir / "20260807.md").write_text(
        "[14:00] 张三: 导出要按平台过滤吗\n"
        "[14:01] 李四: 按 corpCode+groupLevel\n"
        "[15:00] 张三: 中午吃什么\n", encoding="utf-8")
    return emp


def test_draft_writes_drafts_not_candidates(tmp_path):
    emp = _make_emp_for_draft(tmp_path)
    llm = _llm_returning(_OK_PAYLOAD)
    out = tc.draft_chat_segments(emp, llm, "3f9a2c", ["20260807"])
    assert len(out) == 1
    drafts_path = emp / "feishu_pool" / "_topic_drafts.yaml"
    cand_path = emp / "feishu_pool" / "_candidate_topics.yaml"
    assert drafts_path.is_file()
    assert not cand_path.exists()                 # 候选文件未被改动


def test_draft_overwrites_same_day(tmp_path):
    emp = _make_emp_for_draft(tmp_path)
    tc.draft_chat_segments(emp, _llm_returning(_OK_PAYLOAD), "3f9a2c", ["20260807"])
    payload2 = ('{"topics": [{"title": "权限过滤", "summary": "s1",'
                ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2},'
                ' {"title": "午饭", "summary": "s2",'
                ' "msg_range": ["[15:00]", "[15:00]"], "participants_count": 1}]}')
    out = tc.draft_chat_segments(emp, _llm_returning(payload2), "3f9a2c", ["20260807"])
    assert len(out) == 2
    drafts = yaml.safe_load(
        (emp / "feishu_pool" / "_topic_drafts.yaml").read_text(encoding="utf-8"))
    assert len(drafts["drafts"]["3f9a2c/20260807"]) == 2


def test_commit_picked_replaces_day_candidates(tmp_path):
    """T-947 建立（T-948 语义演进）：旧该日卡片不再物理删除，标 rejected 留痕。"""
    emp = _make_emp_for_draft(tmp_path)
    cand_path = emp / "feishu_pool" / "_topics.yaml"
    cand_path.write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 旧话题A\n"
        "    summary: 旧摘要A\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n"
        "  - id: tp:3f9a2c-20260807-02\n    title: 旧话题B\n"
        "    summary: 旧摘要B\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T15:00', '2026-08-07T15:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n"
        "  - id: tp:3f9a2c-20260808-01\n    title: 他日话题\n"
        "    summary: 保留\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-08T10:00', '2026-08-08T10:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260808.md\n", encoding="utf-8")
    picked = [
        {"title": "导出权限过滤", "summary": "新摘要A",
         "window": ["2026-08-07T14:00", "2026-08-07T14:01"],
         "message_count": 2, "participants_count": 2,
         "source": "chats/3f9a2c/20260807.md"},
        {"title": "午饭去哪吃", "summary": "新摘要B",
         "window": ["2026-08-07T15:00", "2026-08-07T15:00"],
         "message_count": 1, "participants_count": 1,
         "source": "chats/3f9a2c/20260807.md"},
    ]
    out = tc.commit_drafts(emp, "3f9a2c", "20260807", picked)
    assert len(out) == 2
    ids = [t["id"] for t in out]
    assert all(i.startswith("tp:3f9a2c-20260807-") for i in ids)
    saved = yaml.safe_load(cand_path.read_text(encoding="utf-8"))["topics"]
    assert len(saved) == 5                        # 2 新 + 2 旧（rejected 留痕） + 1 他日
    by_id = {t["id"]: t for t in saved}
    assert by_id["tp:3f9a2c-20260807-01"]["status"] == "rejected"   # 旧卡标记
    assert by_id["tp:3f9a2c-20260807-02"]["status"] == "rejected"
    assert by_id["tp:3f9a2c-20260808-01"]["status"] == "draft"      # 他日不动
    new_titles = {t["title"] for t in out}
    assert {"导出权限过滤", "午饭去哪吃"} <= new_titles


def test_edit_candidate_partial(tmp_path):
    emp = _make_emp_for_draft(tmp_path)
    cand_path = emp / "feishu_pool" / "_candidate_topics.yaml"
    cand_path.write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 原标题\n"
        "    summary: 原摘要\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
    t = tc.edit_candidate(emp, "tp:3f9a2c-20260807-01", "", "新摘要")
    assert t["title"] == "原标题" and t["summary"] == "新摘要"
    with pytest.raises(KeyError):
        tc.edit_candidate(emp, "tp:not-exist", "x", "y")


def test_regen_candidate_keeps_id(tmp_path):
    emp = _make_emp_for_draft(tmp_path)
    cand_path = emp / "feishu_pool" / "_candidate_topics.yaml"
    cand_path.write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 旧标题\n"
        "    summary: 旧摘要\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:01']\n"
        "    message_count: 2\n    participants_count: 2\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
    llm = _llm_returning(
        '{"topics": [{"title": "新标题", "summary": "新摘要",'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')
    t = tc.regen_candidate(emp, llm, "tp:3f9a2c-20260807-01")
    assert t["id"] == "tp:3f9a2c-20260807-01"
    assert t["title"] == "新标题" and t["summary"] == "新摘要"


# ══════════════════════════════════════════════════════════
# T-948：话题 schema v2（状态制 + keywords + author/rev + agent_origin + 历史）
# ══════════════════════════════════════════════════════════

_EDITOR = {"emp": "90000001", "name": "王测试"}


def _read_topics(emp):
    return yaml.safe_load(
        (emp / "feishu_pool" / "_topics.yaml").read_text(encoding="utf-8"))["topics"]


def test_commit_drafts_status_regime(tmp_path):
    """commit 后新卡片带 status/author/rev/agent_origin；旧该日卡片 rejected 留痕。"""
    emp = _make_emp_for_draft(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 旧话题A\n"
        "    summary: s\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n    status: draft\n    rev: 1\n",
        encoding="utf-8")
    picked = [{"title": "新话题", "summary": "新摘要",
               "keywords": ["导出", "权限"],
               "window": ["2026-08-07T14:00", "2026-08-07T14:01"],
               "message_count": 2, "participants_count": 2,
               "source": "chats/3f9a2c/20260807.md",
               "agent_origin": {"title": "新话题", "summary": "新摘要",
                                "keywords": ["导出"]}}]
    out = tc.commit_drafts(emp, "3f9a2c", "20260807", picked, author=_EDITOR)
    assert out[0]["status"] == "draft"
    assert out[0]["author"] == _EDITOR
    assert out[0]["rev"] == 1
    assert out[0]["keywords"] == ["导出", "权限"]
    assert out[0]["agent_origin"]["keywords"] == ["导出"]   # agent 原稿随卡片落
    saved = _read_topics(emp)
    old = next(t for t in saved if t["id"] == "tp:3f9a2c-20260807-01")
    assert old["status"] == "rejected"                      # 旧卡不删除，标记留痕


def test_edit_candidate_keywords_rev_history(tmp_path):
    """编辑 title+keywords（带 base_rev/editor）→ rev+1、last_edited_*、历史落 from/to。"""
    import json as _json
    emp = _make_emp_for_draft(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 原标题\n    summary: 原摘要\n"
        "    keywords: [权限]\n    chat_sha8: 3f9a2c\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n    status: draft\n    rev: 1\n",
        encoding="utf-8")
    t = tc.edit_candidate(emp, "tp:3f9a2c-20260807-01",
                          title="新标题", keywords=["导出", "权限"],
                          base_rev=1, editor=_EDITOR)
    assert t["rev"] == 2
    assert t["last_edited_by"] == _EDITOR
    assert t["keywords"] == ["导出", "权限"]
    hist = tc.list_history(emp, "tp:3f9a2c-20260807-01")
    assert hist[0]["action"] == "edit" and hist[0]["editor"] == _EDITOR
    assert hist[0]["changes"]["title"]["from"] == "原标题"
    assert hist[0]["changes"]["keywords"]["to"] == ["导出", "权限"]


def test_edit_candidate_rev_conflict(tmp_path):
    """base_rev 过期 → RevConflict（卡片未变、历史无记录）。"""
    emp = _make_emp_for_draft(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 原标题\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    rev: 5\n    status: draft\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
    with pytest.raises(tc.RevConflict) as ei:
        tc.edit_candidate(emp, "tp:3f9a2c-20260807-01", title="抢写",
                          base_rev=1, editor=_EDITOR)
    assert ei.value.topic["rev"] == 5                 # 409 载荷：最新卡片
    assert _read_topics(emp)[0]["title"] == "原标题"   # 未被覆盖
    assert tc.list_history(emp, "tp:3f9a2c-20260807-01") == []


def test_set_topic_status_and_history(tmp_path):
    """confirm/reject 状态翻转 + 历史留痕（editor 身份）。"""
    emp = _make_emp_for_draft(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: t\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    rev: 1\n    status: draft\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
    t = tc.set_topic_status(emp, "tp:3f9a2c-20260807-01", "confirmed",
                            editor=_EDITOR)
    assert t["status"] == "confirmed"
    hist = tc.list_history(emp, "tp:3f9a2c-20260807-01")
    assert hist[0]["action"] == "confirm" and hist[0]["editor"] == _EDITOR


def test_legacy_candidate_file_migration(tmp_path):
    """旧 _candidate_topics.yaml → 读取自动映射 status=draft，保存落新路径。"""
    emp = _make_emp_for_draft(tmp_path)
    (emp / "feishu_pool" / "_candidate_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 存量\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    window: ['2026-08-07T14:00', '2026-08-07T14:00']\n"
        "    message_count: 1\n    participants_count: 1\n"
        "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
    tc.set_topic_status(emp, "tp:3f9a2c-20260807-01", "confirmed",
                        editor=_EDITOR)
    assert (emp / "feishu_pool" / "_topics.yaml").is_file()   # 迁移落新路径
    assert _read_topics(emp)[0]["status"] == "confirmed"
    assert _read_topics(emp)[0]["title"] == "存量"


def test_regen_updates_agent_origin_and_history(tmp_path):
    """regen：agent_origin 换新版本（含 model/generated_at/prompt_version），旧版本进历史。"""
    emp = _make_emp_for_draft(tmp_path)
    (emp / "feishu_pool" / "_topics.yaml").write_text(
        "version: 1\ntopics:\n"
        "  - id: tp:3f9a2c-20260807-01\n    title: 用户改过的标题\n    summary: s\n"
        "    chat_sha8: 3f9a2c\n    rev: 3\n    status: draft\n"
        "    window: ['2026-08-07T14:00', '2026-08-07T14:01']\n"
        "    message_count: 2\n    participants_count: 2\n"
        "    source: chats/3f9a2c/20260807.md\n"
        "    agent_origin:\n      title: AI原标题\n      summary: AI原摘要\n"
        "      keywords: []\n      model: m1\n      generated_at: '2026-08-18T09:00:00'\n"
        "      prompt_version: pv1\n", encoding="utf-8")
    llm = _llm_returning(
        '{"topics": [{"title": "AI新标题", "summary": "AI新摘要",'
        ' "keywords": ["新词"], "msg_range": ["[14:00]", "[14:01]"],'
        ' "participants_count": 2}]}')
    t = tc.regen_candidate(emp, llm, "tp:3f9a2c-20260807-01", editor=_EDITOR)
    assert t["title"] == "AI新标题"
    assert t["agent_origin"]["title"] == "AI新标题"          # origin 跟新版本走
    assert t["agent_origin"]["prompt_version"].startswith("pv")
    assert t["rev"] == 4                                       # regen 也推进 rev
    hist = tc.list_history(emp, "tp:3f9a2c-20260807-01")
    regen_rec = next(h for h in hist if h["action"] == "regen")
    assert regen_rec["changes"]["agent_origin"]["from"]["title"] == "AI原标题"
    assert regen_rec["changes"]["agent_origin"]["to"]["title"] == "AI新标题"


# ══════════════════════════════════════════════════════════
# T-948 pv2：msg_lines → message_ids 精确锚定（JSONL 事实源优先，md 回退）
# ══════════════════════════════════════════════════════════

def _make_emp_with_jsonl(tmp_path):
    """造 JSONL 事实源（含派生 md）：3 条消息，行号→id 映射确定。"""
    from specflow.feishu_pool import chat_store as cs
    emp = tmp_path / ".specflow" / "u1"
    day_file = emp / "feishu_pool" / "chats" / "3f9a2c" / "20260807.jsonl"
    rows = []
    for i, (mid, hhmm, sender, text) in enumerate([
            ("om_a", "14:00", "张三", "导出要按平台过滤吗"),
            ("om_b", "14:01", "李四", "按 corpCode+groupLevel"),
            ("om_c", "15:00", "张三", "中午吃什么")], start=1):
        rows.append({"message_id": mid, "position": str(i),
                     "sender_id": f"ou_{i}", "sender_name": sender,
                     "ts": f"2026-08-07T{hhmm}:00", "msg_type": "text",
                     "content": text, "image_key": "", "reply_to": "",
                     "mentions": [], "origin": "pull"})
    cs.merge_chat_jsonl(day_file, rows)
    cs.rebuild_views(day_file)
    return emp


def test_cluster_msg_lines_to_message_ids(tmp_path):
    """LLM 输出行号列表 → 卡片 message_ids 精确锚定（同分钟并行话题可区分）。"""
    emp = _make_emp_with_jsonl(tmp_path)
    llm = _llm_returning(
        '{"topics": [{"title": "导出权限过滤", "summary": "s",'
        ' "keywords": ["导出"], "msg_lines": [1, 2],'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
    assert out[0]["message_ids"] == ["om_a", "om_b"]
    assert out[0]["message_count"] == 2            # len(message_ids) 精确计数
    assert out[0]["keywords"] == ["导出"]


def test_cluster_md_only_fallback(tmp_path):
    """无 JSONL（存量 md）→ msg_lines 失效但不炸；message_count 回退时间窗。"""
    emp = _make_emp_for_draft(tmp_path)            # 只有 20260807.md
    llm = _llm_returning(
        '{"topics": [{"title": "导出权限过滤", "summary": "s",'
        ' "keywords": [], "msg_lines": [1, 2],'
        ' "msg_range": ["[14:00]", "[14:01]"], "participants_count": 2}]}')
    out = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
    assert "message_ids" not in out[0] or not out[0]["message_ids"]
    assert out[0]["message_count"] == 2            # window 兜底计数


def test_draft_segments_message_ids(tmp_path):
    """draft 分段同样带 message_ids（勾选提交后卡片精确高亮数据齐备）。"""
    emp = _make_emp_with_jsonl(tmp_path)
    llm = _llm_returning(
        '{"topics": [{"title": "午饭", "summary": "s",'
        ' "keywords": ["食堂"], "msg_lines": [3],'
        ' "msg_range": ["[15:00]", "[15:00]"], "participants_count": 1}]}')
    out = tc.draft_chat_segments(emp, llm, "3f9a2c", ["20260807"])
    assert out[0]["message_ids"] == ["om_c"]


# ══════════════════════════════════════════════════════════
# T-991：schema v3（category 五分类 + priority 信号推导）
# ══════════════════════════════════════════════════════════

class TestSchemaV3:
    def test_derive_priority_unit(self):
        """信号推导：闲聊恒 low；阈值映射；LLM hint 微调；群类型加分。"""
        # 闲聊无视一切信号
        assert tc.derive_priority("chat", 99, 9, chat_kind="测试",
                                  llm_hint="high") == "low"
        # 全信号拉满 → high（1+1+0.5+0.5+0.5=3.5）
        assert tc.derive_priority("requirement", 30, 5, chat_kind="测试",
                                  llm_hint="high") == "high"
        # 中档（0.5+0.5=1）→ normal
        assert tc.derive_priority("routine", 10, 3) == "normal"
        # 无信号 → low
        assert tc.derive_priority("routine", 5, 2) == "low"
        # LLM low 微调下压（1-0.5=0.5）→ low
        assert tc.derive_priority("routine", 10, 3, llm_hint="low") == "low"

    def test_cluster_category_priority_and_chat_kept(self, tmp_path):
        """聚类产出带 category/priority；闲聊保留（拍板③：分类不丢弃）恒 low。"""
        emp = _make_emp(tmp_path)
        llm = _llm_returning(
            '{"topics": [{'
            ' "title": "导出权限过滤", "summary": "按 corpCode 过滤",'
            ' "category": "requirement", "priority_hint": "high",'
            ' "participants_count": 6, "msg_range": ["[14:00]", "[14:01]"]}, {'
            ' "title": "午饭吃啥", "summary": "闲聊", "category": "chat",'
            ' "participants_count": 9, "msg_range": ["[15:00]", "[15:00]"]}]}')
        out = tc.cluster_chat_snapshots(
            emp, llm, days=["20260807"], chat_kinds={"3f9a2c": "测试"})
        by_title = {t["title"]: t for t in out}
        req = by_title["导出权限过滤"]
        assert req["category"] == "requirement"
        # pc6=1 + kind测试=0.5 + requirement=0.5 + hint high=0.5 → 2.5 high
        assert req["priority"] == "high"
        assert req["agent_origin"]["category"] == "requirement"
        chat = by_title["午饭吃啥"]
        assert chat["category"] == "chat" and chat["priority"] == "low"

    def test_cluster_invalid_category_falls_back(self, tmp_path):
        """LLM 输出非法分类 → 保守归 routine（不抛错不丢卡）。"""
        emp = _make_emp(tmp_path)
        llm = _llm_returning(
            '{"topics": [{"title": "奇怪分类", "summary": "s",'
            ' "category": "不存在的类", "participants_count": 1,'
            ' "msg_range": ["[14:00]", "[14:01]"]}]}')
        out = tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
        assert out[0]["category"] == "routine"

    def test_cluster_revision_preserves_edited_priority(self, tmp_path):
        """聚类修订沿用旧卡 priority（初值语义——人工改过不被重算覆盖）。"""
        emp = _make_emp(tmp_path)
        payload = ('{"topics": [{"title": "导出权限过滤", "summary": "s",'
                   ' "category": "requirement", "priority_hint": "high",'
                   ' "participants_count": 6,'
                   ' "msg_range": ["[14:00]", "[14:01]"]}]}')
        tc.cluster_chat_snapshots(emp, _llm_returning(payload), days=["20260807"])
        tid = tc._load_candidates(emp)[0]["id"]
        # 人工降级
        tc.edit_candidate(emp, tid, priority="low", editor={"emp": "u1", "name": "一"})
        # 重新聚类（同标题相似 → 归并修订）
        out = tc.cluster_chat_snapshots(emp, _llm_returning(payload),
                                        days=["20260807"])
        assert out[0]["id"] == tid
        assert out[0]["priority"] == "low"

    def test_normalize_legacy_cards_default_v3(self, tmp_path):
        """存量卡（无 category/priority）加载补默认 routine/normal；非法值归默认。"""
        emp = _make_emp(tmp_path)
        topics_yaml = emp / "feishu_pool" / "_topics.yaml"
        topics_yaml.write_text(
            "version: 1\ntopics:\n"
            "  - id: tp:3f9a2c-20260807-01\n    title: 旧卡\n    chat_sha8: 3f9a2c\n"
            "    window: ['2026-08-07T14:00', '2026-08-07T14:01']\n"
            "  - id: tp:3f9a2c-20260807-02\n    title: 脏卡\n    chat_sha8: 3f9a2c\n"
            "    category: bogus\n    priority: super\n"
            "    window: ['2026-08-07T15:00', '2026-08-07T15:00']\n",
            encoding="utf-8")
        cards = {t["title"]: t for t in tc._load_candidates(emp)}
        assert cards["旧卡"]["category"] == "routine"
        assert cards["旧卡"]["priority"] == "normal"
        assert cards["脏卡"]["category"] == "routine"
        assert cards["脏卡"]["priority"] == "normal"

    def test_edit_candidate_category_priority(self, tmp_path):
        """edit_candidate 支持两字段：合法改 + changes 留痕；非法枚举 ValueError。"""
        emp = _make_emp(tmp_path)
        llm = _llm_returning(_OK_PAYLOAD)
        tc.cluster_chat_snapshots(emp, llm, days=["20260807"])
        tid = tc._load_candidates(emp)[0]["id"]
        t = tc.edit_candidate(emp, tid, category="test", priority="high",
                              editor={"emp": "u1", "name": "一"})
        assert t["category"] == "test" and t["priority"] == "high"
        assert t["rev"] == 2
        with pytest.raises(ValueError):
            tc.edit_candidate(emp, tid, category="bogus")
        with pytest.raises(ValueError):
            tc.edit_candidate(emp, tid, priority="super")

    def test_draft_segments_carry_v3_fields(self, tmp_path):
        """人工分段草案带 category/priority（chat_kind 参与推导）。"""
        emp = _make_emp(tmp_path)
        llm = _llm_returning(
            '{"topics": [{"title": "方案讨论", "summary": "分库分表",'
            ' "category": "solution", "priority_hint": "normal",'
            ' "msg_lines": [1, 2], "participants_count": 3}]}')
        segs = tc.draft_chat_segments(emp, llm, "3f9a2c", ["20260807"],
                                      chat_kind="产研")
        # mc2=0 + pc3=0.5 + 产研0.5 + solution0.5 = 1.5 → normal
        assert segs[0]["category"] == "solution"
        assert segs[0]["priority"] == "normal"

    def test_regen_updates_category_and_priority(self, tmp_path):
        """regen 更新分类并按新信号重推导优先级。"""
        emp = _make_emp(tmp_path)
        tc.cluster_chat_snapshots(emp, _llm_returning(_OK_PAYLOAD),
                                  days=["20260807"])
        tid = tc._load_candidates(emp)[0]["id"]
        regen_payload = ('{"topics": [{"title": "导出权限细化", "summary": "s2",'
                         ' "category": "test", "priority_hint": "high",'
                         ' "msg_range": ["[14:00]", "[14:01]"],'
                         ' "participants_count": 5}]}')
        t = tc.regen_candidate(emp, _llm_returning(regen_payload), tid)
        assert t["category"] == "test"
        # mc2=0 + pc5=1 + test0.5 + high0.5 = 2 → high
        assert t["priority"] == "high"
