"""test_topic_shared_materials.py — T-1029 话题共享材料事实层测试。

覆盖：derive/attach 纯函数守卫 + cluster/draft/compose/regen/edit 五路
推导与重算守卫 + resolve 快照联接（纯读）+ 服务层补拉钩子（D4 逐链接
诚实降级）。契约纪律同 test_feishu_chat_store。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from specflow.feishu_pool import chat_store as cs
from specflow.feishu_pool import shared_materials as sm
from specflow.feishu_pool import topic_cluster as tc

_SHA = "3f9a2c11"


def _row(mid: str, content: str, pos: str, ts="2026-08-19T14:00:00",
         msg_type: str = "text", name: str = "张三") -> dict:
    return {"message_id": mid, "position": pos, "sender_id": "ou_1",
            "sender_name": name, "ts": ts, "msg_type": msg_type,
            "content": content, "image_key": "", "reply_to": "",
            "mentions": [], "origin": "pull"}


def _llm(topics_json: str) -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = {"content": topics_json}
    return llm


_LINK = "https://fehorizon.feishu.cn/docx/CtM6dlgsroTTcBxB73wc6RSRnhd"
_SHEET = "https://fehorizon.feishu.cn/sheets/MchesjK2nhtfKsthZyvcHa7Xne1"

_ROWS = [
    _row("om_a", "口径确认下 P0 范围", "1", ts="2026-08-19T14:00:00"),
    _row("om_b", f"文档在这 {_LINK} 先看", "2", ts="2026-08-19T14:01:00"),
    _row("om_c", f"数据表 {_SHEET} 自取", "3", ts="2026-08-19T14:02:00"),
]

_TOPICS_JSON = ('{"topics": [{"title": "范围确认", "summary": "对齐P0", '
                '"msg_lines": [2, 3], '
                '"msg_range": ["[14:01]", "[14:02]"], '
                '"participants_count": 1}]}')


# ══════════════════════════════════════════════════════════
# 纯函数层：derive / attach 守卫
# ══════════════════════════════════════════════════════════

def test_derive_from_rows_dedup_and_kinds():
    rows = [_row("om_a", f"先看 {_LINK} 大家", "1"),
            _row("om_b", f"表格 {_SHEET}，还有重复 {_LINK}", "2"),
            _row("om_c", "[已撤回]", "3"),
            _row("om_d", "Meeting has started.", "4",
                 msg_type="system")]
    facts = sm.derive_from_rows(rows)
    assert [(f["kind"], f["token"], f["message_id"]) for f in facts] == [
        ("docx", "CtM6dlgsroTTcBxB73wc6RSRnhd", "om_a"),
        ("sheets", "MchesjK2nhtfKsthZyvcHa7Xne1", "om_b")]


def test_attach_guards():
    card: dict = {"message_ids": ["om_x"]}
    assert sm.attach_to_card(card, {}) == []          # 有 id 无行 → 空（明确清空）
    legacy = {"message_ids": ["om_x"], "shared_materials": [{"kind": "docx"}]}
    sm.attach_to_card(legacy, {})                     # 全部 id 不可见 → 不动旧值
    assert legacy["shared_materials"] == [{"kind": "docx"}]


# ══════════════════════════════════════════════════════════
# 集成层：四路生成路径 attach
# ══════════════════════════════════════════════════════════

def _pool_with_rows(tmp_path: Path, rows: list[dict], day="20260819") -> Path:
    """共享区材料池：JSONL 事实源 + md 派生视图（cluster 以 md 文件为枚举基准）。"""
    shared = tmp_path / ".specflow"
    day_file = (shared / "feishu_pool" / "chats" / _SHA / f"{day}.jsonl")
    cs.merge_chat_jsonl(day_file, rows)
    cs.rebuild_views(day_file)
    return shared


def test_cluster_path_attaches(tmp_path):
    """cluster：话题卡的 shared_materials 来自其 message_ids 的确定性推导。"""
    shared = _pool_with_rows(tmp_path, _ROWS)
    out = tc.cluster_chat_snapshots(shared, _llm(_TOPICS_JSON),
                                    days=["20260819"])
    card = next(t for t in out if t.get("message_ids") == ["om_b", "om_c"])
    assert [(f["kind"], f["token"]) for f in card["shared_materials"]] == [
        ("docx", "CtM6dlgsroTTcBxB73wc6RSRnhd"),
        ("sheets", "MchesjK2nhtfKsthZyvcHa7Xne1")]


def test_draft_and_compose_paths_attach(tmp_path):
    """draft（草案段）与 compose（勾选归纳）同源推导。"""
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    _pool_with_rows(tmp_path, _ROWS)
    segs = tc.draft_chat_segments(emp, _llm(_TOPICS_JSON), _SHA,
                                  ["20260819"], material_base=shared)
    assert len(segs[0]["shared_materials"]) == 2
    seg = tc.compose_topic_from_messages(
        emp, None, _SHA, ["om_a", "om_c"], ["20260819"],
        title="t", summary="s", keywords=["关键"],
        material_base=shared)
    assert [(f["kind"], f["message_id"]) for f in seg["shared_materials"]] \
        == [("sheets", "om_c")]


def test_edit_recompute_with_guard(tmp_path):
    """edit 换关联 → 重算；换到行不可见的 id 集 → 旧值保留。"""
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    _pool_with_rows(tmp_path, _ROWS)
    produced = tc.commit_drafts(emp, _SHA, "20260819", [{
        "title": "t", "summary": "s", "keywords": [],
        "window": ["2026-08-19T14:00", "2026-08-19T14:02"],
        "message_ids": ["om_a"], "days": ["20260819"],
        "message_count": 1, "participants_count": 1,
        "source": f"chats/{_SHA}/20260819.md"}],
        author={"emp": "u1", "name": "甲"}, material_base=shared)
    tid = produced[0]["id"]
    t = tc.edit_candidate(emp, tid, message_ids=["om_c", "om_b"],
                          base_rev=1, material_base=shared)
    assert [(f["kind"], f["token"]) for f in t["shared_materials"]] == [
        ("sheets", "MchesjK2nhtfKsthZyvcHa7Xne1"),
        ("docx", "CtM6dlgsroTTcBxB73wc6RSRnhd")]   # 按 ids 序逐行推导
    hist = tc.list_history(emp, tid, material_base=shared)[0]
    assert "shared_materials" in hist["changes"]     # 变更留痕
    # 重关联到索引中完全不存在的 id → 字段保持旧值（诚实守卫）
    rev = t["rev"]
    before = list(t["shared_materials"])
    t2 = tc.edit_candidate(emp, tid, message_ids=["om_ghost"],
                           base_rev=rev, material_base=shared)
    assert t2["shared_materials"] == before


def test_regen_recompute_only_with_row_visible_window(tmp_path):
    """regen：跨日卡走窗口源（line_ts 可见）→ 按新 msg_lines 重算；
    md-only 存量卡（无 JSONL）→ 不触碰旧值。"""
    emp = tmp_path / ".specflow" / "u1"
    shared = tmp_path / ".specflow"
    _pool_with_rows(tmp_path, _ROWS)
    produced = tc.commit_drafts(emp, _SHA, "20260819", [{
        "title": "t", "summary": "s", "keywords": [],
        "window": ["2026-08-19T14:00", "2026-08-19T14:02"],
        "message_ids": ["om_a"], "days": ["20260819"],
        "message_count": 1, "participants_count": 1,
        "source": f"chats/{_SHA}/20260819.md"}],
        author={"emp": "u1", "name": "甲"}, material_base=shared)
    regen_json = '{"topics": [{"title": "t2", "summary": "s2", ' \
                 '"category": "requirement", "msg_lines": [3], ' \
                 '"msg_range": ["[14:02]", "[14:02]"], ' \
                 '"participants_count": 1}]}'
    t = tc.regen_candidate(emp, _llm(regen_json), produced[0]["id"],
                           material_base=shared)
    assert [f["token"] for f in t["shared_materials"]] == [
        "MchesjK2nhtfKsthZyvcHa7Xne1"]
    # md-only 回退路径：删掉 JSONL 后 regen 不应清空/改写字段
    (shared / "feishu_pool" / "chats" / _SHA / "20260819.jsonl").unlink()
    legacy = dict(t, days=["20260820"])              # 无该日 JSONL → fallback md
    tc._save_candidates(shared, [legacy])
    t2 = tc.regen_candidate(emp, _llm(regen_json), legacy["id"],
                            material_base=shared)
    assert t2["shared_materials"] == t["shared_materials"]


# ══════════════════════════════════════════════════════════
# resolve 快照联接（纯读派生）
# ══════════════════════════════════════════════════════════

def test_resolve_links_snapshots_readonly(tmp_path):
    base = tmp_path / ".specflow" / "u1"
    docs = base / "feishu_pool" / "docs"
    mins = base / "feishu_pool" / "minutes"
    docs.mkdir(parents=True)
    mins.mkdir(parents=True)
    tok_doc = "CtM6dlgsroTTcBxB73wc6RSRnhd"
    tok_min = "obcnxyz987654321abcd"
    (docs / f"fd-{tok_doc}.md").write_text("# x", encoding="utf-8")
    (docs / f"fd-{tok_doc}.meta.json").write_text(
        '{"title": "盘点方案"}', encoding="utf-8")
    (mins / f"fm-{tok_min}.json").write_text("{}", encoding="utf-8")
    facts = [{"kind": "docx", "token": tok_doc, "url": "https://x/" + tok_doc,
              "message_id": "om_a"},
             {"kind": "minutes", "token": tok_min, "url": "", "message_id": ""},
             {"kind": "sheets", "token": "McheAAAA", "url": "",
              "message_id": ""}]
    out = sm.resolve(facts, base)
    doc, minute, sheet = out
    assert doc["in_pool"] and doc["snapshot_ref"] == f"fd-{tok_doc}"
    assert doc["title"] == "盘点方案" and doc["fetchable"]
    assert minute["in_pool"] and minute["title"] == ""
    assert not sheet["in_pool"] and not sheet["fetchable"]   # 无通道如实标注
    # 纯读：不改入参
    assert "in_pool" not in facts[0]


# ══════════════════════════════════════════════════════════
# 服务层：list 联接 + D4 补拉（逐链接诚实降级）
# ══════════════════════════════════════════════════════════

def _commit_card(base: Path) -> str:
    produced = tc.commit_drafts(base, _SHA, "20260819", [{
        "title": "t", "summary": "s", "keywords": [],
        "window": ["2026-08-19T14:00", "2026-08-19T14:02"],
        "message_ids": ["om_b", "om_c"], "days": ["20260819"],
        "message_count": 2, "participants_count": 1,
        "shared_materials": sm.derive_from_rows([_ROWS[1], _ROWS[2]]),
        "source": f"chats/{_SHA}/20260819.md"}],
        author={"emp": "u1", "name": "甲"})
    return produced[0]["id"]


def test_fetch_topic_materials_honest_degrade(tmp_path, monkeypatch):
    """D4 补拉：docs 命中落池、二次调用幂等跳过、sheets 无通道如实 skip、
    单链接失败不中断（errors 逐条返回）。"""
    from workbench.backend.services.specflow import feishu_sync_service as svc
    shared = tmp_path / ".specflow"
    _pool_with_rows(tmp_path, _ROWS)
    tid = _commit_card(shared)

    def _fake_lark(args, timeout=90):
        if "+fetch" in args:
            return {"data": {"content": "# 盘点方案正文"}}
        raise AssertionError(f"意外 lark 调用: {args}")

    monkeypatch.setattr(svc, "_run_lark", _fake_lark)
    monkeypatch.setattr(svc, "_pull_perm_meta", lambda *_a, **_k: {})
    out = svc.fetch_topic_materials(shared, tid)
    assert any(f["kind"] == "docx" for f in out["fetched"])
    assert any(s["kind"] == "sheets" for s in out["skipped"])
    fd = (shared / "feishu_pool" / "docs" / "fd-CtM6dlgsroTTcBxB73wc6RSRnhd.md")
    assert fd.is_file()
    # 幂等：再次调用全部已在池内 → fetched 空
    out2 = svc.fetch_topic_materials(shared, tid)
    assert out2["fetched"] == [] and out2["errors"] == []
    # 失败降级：删除快照后让 fetch 抛错 → errors 记录且 sheets skip 不受影响
    fd.unlink()

    def _boom(args, timeout=90):
        raise RuntimeError("权限不足")

    monkeypatch.setattr(svc, "_run_lark", _boom)
    out3 = svc.fetch_topic_materials(shared, tid)
    assert len(out3["errors"]) == 1
    assert "权限不足" in out3["errors"][0]["error"]
    with pytest.raises(KeyError):
        svc.fetch_topic_materials(shared, "tp:none")


def test_list_pool_topics_resolves_shared(tmp_path):
    """GET 口径联接：卡片事实附 snapshot_ref/title/in_pool（响应时派生）。
    sheets 无快照通道 → 即便重名文件也不认（in_pool/fetchable 双 False）。"""
    from workbench.backend.services.specflow import feishu_sync_service as svc
    shared = tmp_path / ".specflow"
    _pool_with_rows(tmp_path, _ROWS)
    tid = _commit_card(shared)
    docs = shared / "feishu_pool" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    tok_doc = "CtM6dlgsroTTcBxB73wc6RSRnhd"
    (docs / f"fd-{tok_doc}.md").write_text("# 盘点方案", encoding="utf-8")
    (docs / f"fd-{tok_doc}.meta.json").write_text(
        '{"title": "盘点方案"}', encoding="utf-8")
    resp = svc.list_pool_topics(shared, shared)
    card = next(t for t in resp["candidates"] if t["id"] == tid)
    by_kind = {f["kind"]: f for f in card["shared_materials"]}
    assert by_kind["docx"]["in_pool"]
    assert by_kind["docx"]["snapshot_ref"] == f"fd-{tok_doc}"
    assert by_kind["docx"]["title"] == "盘点方案"
    # sheets：无通道，永远灰显「不可同步」
    assert not by_kind["sheets"]["in_pool"]
    assert not by_kind["sheets"]["fetchable"]
