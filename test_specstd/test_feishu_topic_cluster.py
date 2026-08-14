"""test_feishu_topic_cluster.py — LLM 话题聚类作业单测（飞书知识图谱一期 T6）。

覆盖：
- 群聊快照 → 候选话题（id 规范 tp:{chat_sha8}-{yyyymmdd}-{seq}）
- 增量归并：标题相似 + 同窗 → 沿用旧 id（图谱重建不依赖 LLM 复现）
- LLM 输出非 JSON → 记 error 跳过（诚实呈现不中断）
"""

from unittest.mock import MagicMock

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
    # 候选话题落私有区
    cand = emp / "feishu_pool" / "_candidate_topics.yaml"
    assert cand.is_file()
    saved = yaml.safe_load(cand.read_text(encoding="utf-8"))["topics"]
    assert saved[0]["id"] == t["id"]


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
