"""T-1020 F2：draft 工具活动流水 + reset 会话收窄 + overwrite 模式测试。

事故场景回放（20260825_151821_3178914e）钉案：
- Agent 被 OVERWRITE_DENIED 逼向 reset 全清（用户 v0.3 修复版被误删）
- 修复：write mode=overwrite 给重写正道；reset 只清本会话产物且删前留档
"""
import asyncio
import json

import pytest

from mcp_server.tools import draft_writer
from specstd.workspace import drafts_dir, register_local, unregister
from test_specstd.helpers import create_valid_workspace


def _call(module, name, arguments):
    return asyncio.run(module.handle(name, arguments))


@pytest.fixture
def workspace(tmp_path):
    ws_path = create_valid_workspace(tmp_path / "ws")
    register_local("t1020-ws", str(ws_path), "tdm", activate=True)
    yield "t1020-ws"
    unregister("t1020-ws")


@pytest.fixture
def db(tmp_path, monkeypatch):
    """activity 流水落临时库（复用 user_store 连接）。"""
    import sg_core.user_store as core_us
    p = tmp_path / "t1020-f2.db"
    core_us.init_db(p)
    monkeypatch.setattr(core_us, "DB_PATH", p)
    return p


@pytest.fixture
def sess(db, workspace):
    """注入会话上下文（模拟 agent runtime 的 contextvar 注入）。"""
    from sg_core import session_context as sc
    tok = sc.set_session_id("SESS-F2")
    yield "SESS-F2"
    sc.reset_session_id(tok)


class TestOverwriteMode:
    def test_overwrite_rewrites_with_backup(self, sess):
        _call(draft_writer, "write_draft",
              {"filename": "OW-1.yaml", "content": "id: V1\n"})
        result = _call(draft_writer, "write_draft",
                       {"filename": "OW-1.yaml", "content": "id: V2\n",
                        "mode": "overwrite"})
        data = json.loads(result[0].text)
        assert data["ok"] is True and data["action"] == "overwrite"
        assert (drafts_dir() / "OW-1.yaml").read_text(encoding="utf-8") == "id: V2\n"
        assert (drafts_dir() / "OW-1.yaml.bak").read_text(encoding="utf-8") == "id: V1\n"
        (drafts_dir() / "OW-1.yaml").unlink(missing_ok=True)
        (drafts_dir() / "OW-1.yaml.bak").unlink(missing_ok=True)

    def test_overwrite_nonexistent_acts_as_create(self, sess):
        """overwrite 目标不存在 = 直接新建（不报错）。"""
        result = _call(draft_writer, "write_draft",
                       {"filename": "OW-NEW.yaml", "content": "id: NEW\n",
                        "mode": "overwrite"})
        data = json.loads(result[0].text)
        assert data["ok"] is True and data["action"] == "overwrite"
        assert (drafts_dir() / "OW-NEW.yaml").exists()
        (drafts_dir() / "OW-NEW.yaml").unlink(missing_ok=True)

    def test_create_still_denies_existing(self, sess):
        """create 防呆保留：禁覆盖不因 overwrite 存在而放松。"""
        _call(draft_writer, "write_draft",
              {"filename": "OW-D.yaml", "content": "id: X\n"})
        result = _call(draft_writer, "write_draft",
                       {"filename": "OW-D.yaml", "content": "id: Y\n"})
        assert "OVERWRITE_DENIED" in result[0].text
        (drafts_dir() / "OW-D.yaml").unlink(missing_ok=True)


class TestActivityFlow:
    def test_write_versions_recorded(self, sess):
        """create→patch→overwrite 版本链 1,2,3，session 归属正确。"""
        from sg_core import product_activity as pa
        _call(draft_writer, "write_draft",
              {"filename": "ACT-1.yaml", "content": "v1"})
        _call(draft_writer, "write_draft",
              {"filename": "ACT-1.yaml", "content": "+v2", "mode": "patch"})
        _call(draft_writer, "write_draft",
              {"filename": "ACT-1.yaml", "content": "v3", "mode": "overwrite"})
        chain = pa.version_chain("t1020-ws", "drafts/ACT-1.yaml")
        assert [r["version_no"] for r in chain] == [1, 2, 3]
        assert [r["action"] for r in chain] == ["create", "patch", "overwrite"]
        assert all(r["session_id"] == "SESS-F2" for r in chain)
        assert chain[-1]["content"] == "v3"
        (drafts_dir() / "ACT-1.yaml").unlink(missing_ok=True)
        (drafts_dir() / "ACT-1.yaml.bak").unlink(missing_ok=True)

    def test_undo_recorded(self, sess):
        from sg_core import product_activity as pa
        _call(draft_writer, "write_draft",
              {"filename": "ACT-U.yaml", "content": "v1"})
        _call(draft_writer, "write_draft",
              {"filename": "ACT-U.yaml", "content": "v2", "mode": "overwrite"})
        _call(draft_writer, "undo_draft", {"filename": "ACT-U.yaml"})
        chain = pa.version_chain("t1020-ws", "drafts/ACT-U.yaml")
        assert chain[-1]["action"] == "undo"
        assert chain[-1]["content"] == "v1"  # 恢复后内容
        (drafts_dir() / "ACT-U.yaml").unlink(missing_ok=True)
        (drafts_dir() / "ACT-U.yaml.bak").unlink(missing_ok=True)


class TestResetSessionScope:
    def test_reset_without_session_rejected(self, db, workspace):
        """无会话上下文 → 拒绝（不给他「无会话=全清」后门）。"""
        result = _call(draft_writer, "reset_draft_area", {})
        data = json.loads(result[0].text)
        assert data["ok"] is False
        assert "会话" in data["error"]

    def test_reset_only_current_session_files(self, db, workspace):
        """会话 A 写两份 + 手工放一份 → reset(A) 只清 A 的两份，手工的留存。"""
        from sg_core import product_activity as pa
        from sg_core import session_context as sc

        tok = sc.set_session_id("SESS-A")
        try:
            _call(draft_writer, "write_draft",
                  {"filename": "RS-A1.yaml", "content": "a1"})
            _call(draft_writer, "write_draft",
                  {"filename": "RS-A2.yaml", "content": "a2"})
        finally:
            sc.reset_session_id(tok)

        # 用户手工放置（非任何会话产物）——v0.3 修复版场景钉案
        (drafts_dir() / "RS-MANUAL.yaml").write_text("precious-v0.3", encoding="utf-8")

        tok = sc.set_session_id("SESS-A")
        try:
            result = _call(draft_writer, "reset_draft_area", {})
        finally:
            sc.reset_session_id(tok)
        data = json.loads(result[0].text)

        assert data["ok"] is True
        assert data["yaml_deleted"] == 2
        assert not (drafts_dir() / "RS-A1.yaml").exists()
        assert not (drafts_dir() / "RS-A2.yaml").exists()
        # 手工草稿不受影响（事故根治点）
        assert (drafts_dir() / "RS-MANUAL.yaml").exists()
        assert "RS-MANUAL.yaml" in data["skipped"]

        # 删前内容留档：可从流水恢复
        chain = pa.version_chain("t1020-ws", "drafts/RS-A1.yaml")
        assert chain[-1]["action"] == "reset_delete"
        assert chain[-1]["content"] == "a1"
        (drafts_dir() / "RS-MANUAL.yaml").unlink(missing_ok=True)

    def test_reset_other_session_files_untouched(self, db, workspace):
        """会话 A 写的文件在会话 B 的 reset 下不动。"""
        from sg_core import session_context as sc

        tok = sc.set_session_id("SESS-A")
        try:
            _call(draft_writer, "write_draft",
                  {"filename": "RS-XA.yaml", "content": "from-a"})
        finally:
            sc.reset_session_id(tok)

        tok = sc.set_session_id("SESS-B")
        try:
            result = _call(draft_writer, "reset_draft_area", {})
        finally:
            sc.reset_session_id(tok)
        data = json.loads(result[0].text)

        assert data["ok"] is True
        assert data["yaml_deleted"] == 0
        assert (drafts_dir() / "RS-XA.yaml").exists()
        assert "RS-XA.yaml" in data["skipped"]
        (drafts_dir() / "RS-XA.yaml").unlink(missing_ok=True)
