"""T-1027 F2：草稿面板人工编辑的对话感知测试。

钉案（20260827_094125_f955645e 会话复盘）：
- 用户在面板改草稿后，对话必须能感知编辑并拿到确定性校验结论
- run 进行中不能 append 会话 JSONL（runtime 轮末全量覆写会丢行）→ pending 文件
- WS 开跑前 drain 排空，<panel_edits> 前缀并入本轮 user 消息（幂等读后即删）
- REST 人工编辑进 user_edit 版本链（此前只挂 MCP 写路径，版本叙事失真）
"""
import json

import pytest
from services.panel_edit_feedback import (
    PENDING_SUFFIX,
    build_edit_note,
    drain_panel_edits,
    inject_edit_note,
)

from specstd.workspace import register_local, unregister
from test_specstd.helpers import create_valid_workspace


@pytest.fixture
def workspace(tmp_path):
    ws_path = create_valid_workspace(tmp_path / "ws")
    register_local("t1027-ws", str(ws_path), "tdm", activate=True)
    yield "t1027-ws"
    unregister("t1027-ws")


@pytest.fixture
def db(tmp_path, monkeypatch):
    """活动流水落临时库（复用 user_store 连接）。"""
    import sg_core.user_store as core_us
    p = tmp_path / "t1027.db"
    core_us.init_db(p)
    monkeypatch.setattr(core_us, "DB_PATH", p)
    return p


OLD_YAML = "id: X-001\ntitle: 旧标题\nflow:\n  - step: call\nverify:\n  - eq: status"
NEW_YAML = ("id: X-001\ntitle: 新标题\nflow:\n  - step: call\n"
            "verify:\n  - eq: status\n  - db_eq: count")


class TestBuildEditNote:
    def test_diff_stat_and_sections(self):
        note = build_edit_note("X.yaml", OLD_YAML, NEW_YAML, None)
        assert "[面板编辑]" in note and "X.yaml" in note
        assert "+2/-1" in note            # 改 title(±1) + 追加 db_eq 行(+1)
        assert "title" in note or "verify" in note  # 涉及区块点名

    def test_validation_summary_pass(self):
        report = {"verdict": "PASS", "summary": {"error": 0, "warn": 2}, "findings": []}
        note = build_edit_note("X.yaml", OLD_YAML, NEW_YAML, report)
        assert "PASS" in note and "error 0 / warn 2" in note

    def test_error_findings_listed_capped(self):
        report = {"verdict": "FAIL", "summary": {"error": 5, "warn": 0},
                  "findings": [{"level": "ERROR", "rule": f"R{i}", "message": f"错{i}"} for i in range(5)]}
        note = build_edit_note("X.yaml", OLD_YAML, NEW_YAML, report)
        assert "FAIL" in note and "[R0] 错0" in note
        assert "[R3]" not in note         # 只摘录前 3 条
        assert "ERROR" in note            # 有 ERROR 时提示关注修复

    def test_truncated_to_cap(self):
        big_new = NEW_YAML + "\n# " + "x" * 5000
        note = build_edit_note("X.yaml", OLD_YAML, big_new, None)
        assert len(note) <= 1200


class TestInjectEditNote:
    @pytest.fixture
    def sess(self, tmp_path):
        from agent.session import SessionManager
        sm = SessionManager(tmp_path / "sessions", workspace="t1027-wsx")
        sid = sm.create(emp_no="90024166")
        return sm, sid

    def test_appended_system_row_visible_to_llm_hidden_in_ui(self, tmp_path, sess):
        sm, sid = sess
        r = inject_edit_note(tmp_path / "sessions", "t1027-wsx", sid,
                             "[面板编辑] 用户修改了 X.yaml", busy=False)
        assert r["mode"] == "appended"
        rows = sm.load(sid)
        hits = [m for m in rows if m.get("role") == "system" and "[面板编辑]" in m.get("content", "")]
        assert len(hits) == 1   # LLM 每轮历史可见；前端 groupMessages 跳过 system 不渲染

    def test_unknown_session_not_found(self, tmp_path):
        r = inject_edit_note(tmp_path / "sessions", "", "NOPE-sid", "n", busy=False)
        assert r["mode"] == "session_not_found"

    def test_busy_goes_pending_then_drained_once(self, tmp_path, sess):
        sm, sid = sess
        base = tmp_path / "sessions"
        r = inject_edit_note(base, "t1027-wsx", sid, "note-one", busy=True)
        assert r["mode"] == "pending"
        inject_edit_note(base, "t1027-wsx", sid, "note-two", busy=True)
        pend = base / "t1027-wsx" / f"{sid}{PENDING_SUFFIX}"
        assert pend.is_file()
        # 会话 JSONL 未被动过（run 进行中不可写）
        assert all("[面板编辑]" not in json.dumps(m, ensure_ascii=False)
                   for m in sm.load(sid))

        block = drain_panel_edits(base, "t1027-wsx", sid)
        assert block.startswith("<panel_edits>") and "note-one" in block and "note-two" in block
        assert not pend.exists()          # 读后即删——同一批只并入一次
        assert drain_panel_edits(base, "t1027-wsx", sid) == ""

    def test_drain_no_pending_empty(self, tmp_path):
        assert drain_panel_edits(tmp_path / "sessions", "ws", "any") == ""


class TestUserEditVersionChain:
    def test_rest_style_record_uses_explicit_context(self, db):
        """REST 保存显式传参会话/工号/工作区（无 contextvar 依赖），版本链可查。"""
        from sg_core import product_activity as pa
        row = pa.record_activity("drafts/HI-PERM-002.yaml", "user_edit",
                                 session_id="20260827_094125_f955645e",
                                 emp_no="90024166", workspace="tdm",
                                 content=NEW_YAML)
        assert row["version_no"] >= 1
        chain = pa.version_chain("tdm", "drafts/HI-PERM-002.yaml")
        assert chain[-1]["action"] == "user_edit"
        assert chain[-1]["sha"] == row["sha"]

    def test_second_edit_bumps_version(self, db):
        from sg_core import product_activity as pa
        pa.record_activity("drafts/B.yaml", "create", session_id="S1",
                           emp_no="E", workspace="w", content="v1")
        row = pa.record_activity("drafts/B.yaml", "user_edit", session_id="S1",
                                 emp_no="E", workspace="w", content="v2")
        assert row["version_no"] == 2
