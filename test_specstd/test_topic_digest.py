"""test_topic_digest.py — T-1011 飞书话题通用召回单测。

覆盖：
- select_digest_cards 时效分级（近3天非闲聊全量含 draft / 4-7天仅 high /
  更旧排除 / rejected、chat 排除 / 日期不可解析保守按最新）
- build_digest 摘要块（空态诚实 / 行格式 / cap）
- match_topic_cards 关键词命中（keywords 2分 / 标题 1分 / cap / 分级集合内）
- topic 合并工具四动作（list/search/read/messages 原文口子 + 未知 id + 无工作区）
- resolve_tools meta 域常驻并集（收窄用途可见 topic；不收窄用途语义不变）
- build_system_prompt 注入「飞书话题」块
"""

import asyncio
import json
from datetime import date, timedelta

import yaml

from specflow.feishu_pool import topic_digest as td

TODAY = date(2026, 8, 24)


def _card(tid, days_ago, priority="normal", category="requirement",
          status="draft", keywords=None, title="话题", summary="结论"):
    day = (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {
        "id": tid, "title": f"{title}{tid}", "summary": summary,
        "keywords": keywords or [], "category": category,
        "priority": priority, "status": status, "rev": 1,
        "chat_sha8": "ab12cd34", "window": [f"{day}T10:00", f"{day}T11:00"],
        "message_count": 12, "participants_count": 3,
        "source": f"chats/ab12cd34/{day.replace('-', '')}.md",
        "message_ids": ["m1", "m2"],
    }


def _write_pool(root, cards, messages=None):
    pool = root / "feishu_pool"
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "_topics.yaml").write_text(
        yaml.safe_dump({"version": 1, "topics": cards}, allow_unicode=True),
        encoding="utf-8")
    if messages is not None:
        cdir = pool / "chats" / "ab12cd34"
        cdir.mkdir(parents=True, exist_ok=True)
        day = (TODAY).strftime("%Y%m%d")
        with open(cdir / f"{day}.jsonl", "w", encoding="utf-8") as fh:
            for m in messages:
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        (cdir / f"{day}.md").write_text("# 产研对齐群\n", encoding="utf-8")
    return root


# ══════════════════════════════════════════════════════════
# select_digest_cards 时效分级
# ══════════════════════════════════════════════════════════

class TestSelectDigestCards:
    def test_recent_3d_all_non_chat_including_draft(self):
        cards = [_card("tp-1", 0, priority="low", status="draft"),
                 _card("tp-2", 3, priority="normal", status="confirmed")]
        ids = [c["id"] for c in td.select_digest_cards(cards, today=TODAY)]
        assert ids == ["tp-1", "tp-2"]

    def test_4_to_7d_only_high(self):
        cards = [_card("tp-high", 5, priority="high"),
                 _card("tp-normal", 5, priority="normal"),
                 _card("tp-low", 7, priority="low")]
        ids = [c["id"] for c in td.select_digest_cards(cards, today=TODAY)]
        assert ids == ["tp-high"]

    def test_older_than_7d_excluded(self):
        cards = [_card("tp-old", 8, priority="high")]
        assert td.select_digest_cards(cards, today=TODAY) == []

    def test_chat_and_rejected_always_excluded(self):
        cards = [_card("tp-chat", 0, priority="high", category="chat"),
                 _card("tp-rej", 0, priority="high", status="rejected")]
        assert td.select_digest_cards(cards, today=TODAY) == []

    def test_unparseable_date_treated_as_newest(self):
        c = _card("tp-nodate", 0)
        c["window"] = []
        ids = [x["id"] for x in td.select_digest_cards([c], today=TODAY)]
        assert ids == ["tp-nodate"]

    def test_sort_new_first_then_priority(self):
        cards = [_card("tp-oldhigh", 2, priority="high"),
                 _card("tp-newlow", 0, priority="low"),
                 _card("tp-sameday-high", 2, priority="normal",
                       title="同日")]
        picked = td.select_digest_cards(cards, today=TODAY)
        assert [c["id"] for c in picked] == ["tp-newlow", "tp-oldhigh",
                                             "tp-sameday-high"]


# ══════════════════════════════════════════════════════════
# build_digest / load_topic_cards
# ══════════════════════════════════════════════════════════

class TestBuildDigest:
    def test_empty_when_no_topics_file(self, tmp_path):
        assert td.build_digest(material_root=tmp_path, today=TODAY) == ""

    def test_lines_format_and_status_visible(self, tmp_path):
        _write_pool(tmp_path, [_card("tp-1", 1, priority="high",
                                     status="draft")])
        out = td.build_digest(material_root=tmp_path, today=TODAY)
        assert "- tp-1 | 08-23 | high | draft |" in out

    def test_cap_with_overflow_hint(self, tmp_path):
        cards = [_card(f"tp-{i:03d}", 0) for i in range(5)]
        _write_pool(tmp_path, cards)
        out = td.build_digest(material_root=tmp_path, today=TODAY, cap=3)
        assert out.count("- tp-") == 3
        assert "另有 2 条" in out

    def test_no_workspace_returns_empty(self, monkeypatch):
        monkeypatch.setattr(td, "_material_root", lambda: None)
        assert td.build_digest(today=TODAY) == ""


# ══════════════════════════════════════════════════════════
# match_topic_cards 关键词命中
# ══════════════════════════════════════════════════════════

class TestMatchTopicCards:
    def test_keyword_hit_scores_and_caps(self, tmp_path):
        cards = [_card("tp-1", 0, keywords=["九宫格", "盘点"]),
                 _card("tp-2", 0, keywords=["九宫格"]),
                 _card("tp-3", 0, keywords=["调休"])]
        _write_pool(tmp_path, cards)
        hits = td.match_topic_cards("九宫格落位口径再确认一下",
                                    material_root=tmp_path, today=TODAY)
        assert [c["id"] for c in hits] == ["tp-1", "tp-2"]

    def test_title_hit(self, tmp_path):
        c = _card("tp-t", 0, title="绩效校准会结论")
        c["title"] = "绩效校准会结论"  # _card 会拼 tid 后缀，还原自然标题
        _write_pool(tmp_path, [c])
        hits = td.match_topic_cards("绩效校准会结论同步了吗",
                                    material_root=tmp_path, today=TODAY)
        assert [x["id"] for x in hits] == ["tp-t"]

    def test_miss_and_chat_excluded(self, tmp_path):
        cards = [_card("tp-c", 0, category="chat", keywords=["九宫格"])]
        _write_pool(tmp_path, cards)
        assert td.match_topic_cards("九宫格", material_root=tmp_path,
                                    today=TODAY) == []
        assert td.match_topic_cards("完全无关的词", material_root=tmp_path,
                                    today=TODAY) == []


# ══════════════════════════════════════════════════════════
# topic 合并工具（meta 域常驻）
# ══════════════════════════════════════════════════════════

def _run_tool(name, args):
    from mcp_server.tools import topic_query
    return asyncio.run(topic_query.handle(name, args))


class TestTopicTool:
    def _pool(self, tmp_path):
        msgs = [
            {"message_id": "m1", "ts": f"{TODAY} 10:00", "sender_name": "张三",
             "msg_type": "text", "content": "九宫格按绩效+潜力两轴"},
            {"message_id": "m2", "ts": f"{TODAY} 10:01", "sender_name": "李四",
             "msg_type": "text", "content": "同意，先跑一批看分布"},
            {"message_id": "m3", "ts": f"{TODAY} 10:02", "sender_name": "王五",
             "msg_type": "text", "content": "无关消息"},
        ]
        return _write_pool(tmp_path, [_card("tp-1", 0, priority="high")], msgs)

    def test_list_default_grading(self, tmp_path, monkeypatch):
        root = self._pool(tmp_path)
        from mcp_server.tools import topic_query
        monkeypatch.setattr(topic_query, "_root", lambda: root)
        out = json.loads(_run_tool("topic", {"action": "list"})[0].text)
        assert out["ok"] and out["count"] == 1
        assert out["topics"][0].startswith("- tp-1 |")

    def test_search_and_read(self, tmp_path, monkeypatch):
        root = self._pool(tmp_path)
        from mcp_server.tools import topic_query
        monkeypatch.setattr(topic_query, "_root", lambda: root)
        out = json.loads(_run_tool("topic", {"action": "search",
                                             "keyword": "话题tp-1"})[0].text)
        assert out["ok"] and out["count"] == 1
        out = json.loads(_run_tool("topic", {"action": "read",
                                             "id": "tp-1"})[0].text)
        assert out["ok"] and out["topic"]["id"] == "tp-1"
        assert out["chat_name"] == "产研对齐群"
        assert "messages" in out["origin_hint"]

    def test_messages_replay_filtered_by_ids(self, tmp_path, monkeypatch):
        root = self._pool(tmp_path)
        from mcp_server.tools import topic_query
        monkeypatch.setattr(topic_query, "_root", lambda: root)
        out = json.loads(_run_tool("topic", {"action": "messages",
                                             "id": "tp-1"})[0].text)
        assert out["ok"]
        assert "九宫格按绩效+潜力两轴" in out["messages"]
        assert "无关消息" not in out["messages"]  # m3 不在 message_ids

    def test_unknown_id_and_no_workspace(self, tmp_path, monkeypatch):
        root = self._pool(tmp_path)
        from mcp_server.tools import topic_query
        monkeypatch.setattr(topic_query, "_root", lambda: root)
        out = json.loads(_run_tool("topic", {"action": "read",
                                             "id": "tp-none"})[0].text)
        assert not out["ok"] and "不存在" in out["error"]
        monkeypatch.setattr(topic_query, "_root", lambda: None)
        out = json.loads(_run_tool("topic", {"action": "list"})[0].text)
        assert not out["ok"] and "工作区" in out["error"]

    def test_domain_meta_and_pure_read(self):
        from mcp_server.tools.tool_meta import get_meta, resolve_side_effect
        meta = get_meta("topic")
        assert meta.domain == "meta"
        assert resolve_side_effect("topic", "list") == "none"
        assert set(meta.actions) == {"list", "search", "read", "messages"}


# ══════════════════════════════════════════════════════════
# resolve_tools meta 域常驻并集
# ══════════════════════════════════════════════════════════

class TestResolveToolsMetaDomain:
    def test_narrowed_purpose_still_sees_topic(self):
        from agent.runtime import resolve_tools
        tools = resolve_tools([], ["admin"], purpose_domains=["spec"])
        names = {t.name for t in tools}
        assert "topic" in names
        assert "gate_dock_status" in names  # meta 域存量成员同样常驻

    def test_unnarrowed_purpose_semantics_unchanged(self):
        from agent.runtime import resolve_tools
        tools = resolve_tools([], ["admin"])
        names = {t.name for t in tools}
        assert "topic" in names and "scenario" in names  # admin 全量不收窄

    def test_product_role_sees_topic_pure_read(self):
        from agent.runtime import resolve_tools
        tools = resolve_tools([], ["product"], purpose_domains=["specflow"])
        assert "topic" in {t.name for t in tools}

    def test_purpose_tool_count_budget_intact(self):
        """meta 并集不挤领域名额：requirement_interview 领域工具仍 15 + meta。"""
        from agent.runtime import resolve_tools
        tools = resolve_tools(
            ["spec", "validate", "query_registry", "info_pack"],
            ["admin"],
            purpose_domains=["specflow", "feishu", "run", "draft", "knowledge"])
        names = {t.name for t in tools}
        assert "topic" in names
        assert "spec" in names  # 域外显式补充不受影响


# ══════════════════════════════════════════════════════════
# build_system_prompt 注入
# ══════════════════════════════════════════════════════════

class TestPromptInjection:
    def test_digest_block_injected(self, monkeypatch):
        monkeypatch.setattr(td, "build_digest",
                            lambda **kw: "- tp-1 | 08-24 | high | draft | 九宫格 | 结论")
        from agent.runtime import build_system_prompt
        prompt = build_system_prompt(format_spec_text="fmt", agents_md="rules")
        assert "## 飞书话题" in prompt
        assert "- tp-1 | 08-24 | high | draft | 九宫格 | 结论" in prompt

    def test_empty_digest_honest_placeholder(self, monkeypatch):
        monkeypatch.setattr(td, "build_digest", lambda **kw: "")
        from agent.runtime import build_system_prompt
        prompt = build_system_prompt(format_spec_text="fmt", agents_md="rules")
        assert "（近期无非闲聊话题，或话题库尚未聚类）" in prompt

    def test_digest_failure_never_breaks_prompt(self, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("yaml broken")
        monkeypatch.setattr(td, "build_digest", _boom)
        from agent.runtime import build_system_prompt
        prompt = build_system_prompt(format_spec_text="fmt", agents_md="rules")
        assert "话题摘要加载失败" in prompt
