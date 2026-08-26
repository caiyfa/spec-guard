"""T-1020 F1：产物活动流水（product_activity）测试。

设计要点（总控人拍板）：
- 每次写动作一条流水：session_id/emp_no/workspace 自动取 contextvar（工具层零传参），
  显式参数覆盖（测试/非 agent 路径用）
- version_no 按 (workspace, product_path) 全局递增——「文件第几版」事实源
- content 全文快照留档：reset 误删后可从 DB 恢复（v0.3 事故根治）
- 动作词表：create/patch/overwrite/undo/promote/promote_batch/discard/reset_delete
"""
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """user_store 指向临时库（product_activity 共用其连接与 DB_PATH）。"""
    p = tmp_path / "t1020.db"
    import sg_core.user_store as core_us
    core_us.init_db(p)
    monkeypatch.setattr(core_us, "DB_PATH", p)
    return p


@pytest.fixture
def ctx(monkeypatch):
    """注入 agent 会话上下文（session/emp/workspace 三 contextvar）——工具层视角。"""
    import sg_core.emp_context as ec
    import specstd.workspace as wsm
    from sg_core import session_context as sc

    t1 = sc.set_session_id("SESS-1")
    t2 = ec._CTX_EMP_NO.set("u1")
    t3 = wsm._CTX_WORKSPACE.set("ws1")
    yield {"session_id": "SESS-1", "emp_no": "u1", "workspace": "ws1"}
    sc.reset_session_id(t1)
    ec._CTX_EMP_NO.reset(t2)
    wsm._CTX_WORKSPACE.reset(t3)


class TestRecordAndContext:
    def test_context_auto_fill(self, db, ctx):
        """工具层零传参：session/emp/workspace 全部从 contextvar 自动取。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", content="v1")
        rows = pa.by_session("SESS-1")
        assert len(rows) == 1
        r = rows[0]
        assert r["emp_no"] == "u1" and r["workspace"] == "ws1"
        assert r["version_no"] == 1 and r["content"] == "v1"

    def test_explicit_args_override(self, db, ctx):
        """显式参数覆盖上下文（非 agent 路径/测试用）。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create",
                           session_id="SESS-X", emp_no="u9", workspace="wsX")
        r = pa.by_session("SESS-X")[0]
        assert r["emp_no"] == "u9" and r["workspace"] == "wsX"

    def test_no_context_empty_honest(self, db, monkeypatch):
        """无上下文（MCP stdio/纯 API）：字段诚实留空，流水照记。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", workspace="ws1")
        r = pa.by_session("")[0]
        assert r["session_id"] == "" and r["emp_no"] == ""

    def test_empty_path_noop(self, db):
        from sg_core import product_activity as pa
        pa.record_activity("", "create")
        assert pa.by_session("") == []


class TestVersionChain:
    def test_version_no_increments_per_path(self, db, ctx):
        """同 path 版本递增；不同 path 独立计数。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", content="v1")
        pa.record_activity("drafts/A.yaml", "patch", content="v2")
        pa.record_activity("drafts/A.yaml", "overwrite", content="v3")
        pa.record_activity("drafts/B.yaml", "create", content="b1")
        chain = pa.version_chain("ws1", "drafts/A.yaml")
        assert [r["version_no"] for r in chain] == [1, 2, 3]
        assert [r["action"] for r in chain] == ["create", "patch", "overwrite"]
        assert pa.version_chain("ws1", "drafts/B.yaml")[0]["version_no"] == 1

    def test_version_isolated_by_workspace(self, db, ctx):
        """版本计数按 workspace 隔离（多工作区不串号）。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", workspace="ws1")
        pa.record_activity("drafts/A.yaml", "create", workspace="ws2")
        assert pa.version_chain("ws1", "drafts/A.yaml")[0]["version_no"] == 1
        assert pa.version_chain("ws2", "drafts/A.yaml")[0]["version_no"] == 1

    def test_current_version_returns_latest_with_content(self, db, ctx):
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", content="v1")
        pa.record_activity("drafts/A.yaml", "overwrite", content="v2")
        cur = pa.current_version("ws1", "drafts/A.yaml")
        assert cur["version_no"] == 2 and cur["content"] == "v2"

    def test_current_version_missing_returns_none(self, db):
        from sg_core import product_activity as pa
        assert pa.current_version("ws-none", "drafts/A.yaml") is None


class TestSessionScope:
    def test_session_drafts_query(self, db, ctx):
        """reset 会话收窄的数据依赖：某会话写过的草稿文件集。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create")   # SESS-1
        pa.record_activity("drafts/B.yaml", "create")   # SESS-1
        pa.record_activity("drafts/C.yaml", "create", session_id="SESS-2")
        files = pa.session_draft_files("SESS-1")
        assert files == {"drafts/A.yaml", "drafts/B.yaml"}

    def test_latest_by_workspace(self, db, ctx):
        """面板 DB 化数据源：工作区每份产物最新状态+版本数+来源会话。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", content="v1")
        pa.record_activity("drafts/A.yaml", "overwrite", content="v2",
                           session_id="SESS-2")
        pa.record_activity("drafts/B.yaml", "create")
        latest = {r["product_path"]: r for r in pa.latest_by_workspace("ws1")}
        assert set(latest) == {"drafts/A.yaml", "drafts/B.yaml"}
        a = latest["drafts/A.yaml"]
        assert a["version_no"] == 2 and a["session_id"] == "SESS-2"
        assert a["versions"] == 2

    def test_reset_delete_keeps_snapshot(self, db, ctx):
        """reset 留档：删前内容快照进流水（恢复事实源）。"""
        from sg_core import product_activity as pa
        pa.record_activity("drafts/A.yaml", "create", content="v0.3-precious")
        pa.record_activity("drafts/A.yaml", "reset_delete", content="v0.3-precious")
        cur = pa.current_version("ws1", "drafts/A.yaml")
        assert cur["action"] == "reset_delete"
        assert cur["content"] == "v0.3-precious"
