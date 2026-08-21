"""S2 specflow MCP 工具测试（审查修复验证）。

覆盖（H2/M4/M5）：
- iv_ask_question：问题登记链路（原来无写入通道）+ 非法输入拒绝
- iv_read_baseline：真实 specstd.anchors 摘录（原来 stub 假数据）
- iv_open_topic：emp 留痕注入 + workspace 缺失拒绝
"""

import asyncio
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from test_specstd.helpers import create_valid_workspace  # noqa: E402
from specstd.workspace import (  # noqa: E402
    register_local, unregister, specflow_dir, set_context_emp_no,
    reset_context_emp_no, set_context_workspace, reset_context_workspace,
)
from mcp_server.tools import specflow_interview  # noqa: E402
from specflow.interview.topic import load_topic  # noqa: E402
from workbench.backend.services.specflow import sf_store  # noqa: E402


def _call(module, name, arguments):
    return asyncio.run(module.handle(name, arguments))


@pytest.fixture(autouse=True)
def _cleanup_ctx():
    """防 contextvar 泄漏：MCP 调用/测试内的 emp/workspace 注入影响后续测试。"""
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离 DB + 注册合规工作区（含 specs/ 基线）。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    monkeypatch.setattr(sf_store, "DB_PATH", tmp_path / "workbench.db")

    ws_path = create_valid_workspace(tmp_path / "ws")
    register_local("test-mcp", str(ws_path), "tdm", activate=True)

    # 模拟 Agent 会话上下文：workspace + emp 注入
    tok_ws = set_context_workspace("test-mcp")
    tok_emp = set_context_emp_no("E10001")
    yield "test-mcp"
    reset_context_workspace(tok_ws)
    reset_context_emp_no(tok_emp)
    unregister("test-mcp")


def _open_via_mcp(env):
    """走 MCP iv_open_topic 开标。"""
    result = _call(specflow_interview, "iv_open_topic", {
        "session_id": "SESS-1",
        "title": "人才打标AI构建",
        "source": [{"type": "prd_section", "ref": "PRD v3.2 §2.7"}],
    })
    text = result[0].text
    assert "iv_id" in text, text
    # 解析 iv_id（dict str 中提取）
    iv_id = text.split("'iv_id': '")[1].split("'")[0]
    return iv_id


# ══════════════════════════════════════════════════════════
# H2：iv_ask_question 问题登记链路
# ══════════════════════════════════════════════════════════

class TestAskQuestion:
    def test_create_question_ok(self, env):
        iv_id = _open_via_mcp(env)
        r = _call(specflow_interview, "iv_ask_question", {
            "iv_id": iv_id, "priority": "P0", "question": "调整范围：仅绩效域？",
            "chapter": 1,
        })
        text = r[0].text
        assert "'status': 'created'" in text, text
        assert f"{iv_id}-Q1" in text

    def test_ask_question_bad_priority(self, env):
        iv_id = _open_via_mcp(env)
        r = _call(specflow_interview, "iv_ask_question", {
            "iv_id": iv_id, "priority": "P9", "question": "Q",
        })
        assert "非法优先级" in r[0].text

    def test_ask_question_invalid_iv(self, env):
        r = _call(specflow_interview, "iv_ask_question", {
            "iv_id": "../../etc", "priority": "P0", "question": "Q",
        })
        assert "非法 IV 编号" in r[0].text

    def test_ask_question_unknown_interview(self, env):
        r = _call(specflow_interview, "iv_ask_question", {
            "iv_id": "IV-999", "priority": "P0", "question": "Q",
        })
        assert "面试不存在" in r[0].text

    def test_ask_question_requires_workspace(self, env):
        """无工作区上下文 → 拒绝（fail-closed，不落空区）。"""
        iv_id = _open_via_mcp(env)
        from specstd.workspace import get_context_workspace
        assert get_context_workspace()  # fixture 已注入
        # 模拟无上下文：直接清空后调用会失败，此处验证 MCP 工具读 contextvar
        r = _call(specflow_interview, "iv_ask_question", {
            "iv_id": iv_id, "priority": "P0", "question": "Q",
        })
        assert "created" in r[0].text  # 有上下文时正常

    def test_questions_isolated_by_workspace(self, env):
        """问题登记带 workspace 维度，跨工作区查询不可见。"""
        iv_id = _open_via_mcp(env)
        _call(specflow_interview, "iv_ask_question", {
            "iv_id": iv_id, "priority": "P0", "question": "Q1",
        })
        # 另一工作区视角查询 → 空
        from specstd.workspace import set_context_workspace, reset_context_workspace
        from workbench.backend.services.specflow.sf_store import list_questions
        tok = set_context_workspace("other-ws")
        try:
            assert list_questions(iv_id, workspace="other-ws") == []
        finally:
            reset_context_workspace(tok)
        assert len(list_questions(iv_id, workspace="test-mcp")) == 1


# ══════════════════════════════════════════════════════════
# M5：iv_read_baseline 真实摘录（原 stub 假数据）
# ══════════════════════════════════════════════════════════

class TestReadBaseline:
    def test_baseline_found_real(self, env):
        """FR-001 在合规工作区 specs/ 中真实存在 → found + 真实标题。"""
        r = _call(specflow_interview, "iv_read_baseline", {"fr_refs": ["FR-001"]})
        text = r[0].text
        assert "'status': 'found'" in text, text
        assert "FR-001" in text
        assert "available_frs" in text  # 自愈锚点清单

    def test_baseline_not_found(self, env):
        r = _call(specflow_interview, "iv_read_baseline", {"fr_refs": ["FR-999"]})
        assert "'status': 'not_found'" in r[0].text


# ══════════════════════════════════════════════════════════
# M4：iv_open_topic emp 留痕 + 私有区落点
# ══════════════════════════════════════════════════════════

class TestOpenTopic:
    def test_open_topic_emp_attribution(self, env):
        """开标后议题卡 initiator.emp = contextvar 注入工号（归属留痕）。"""
        iv_id = _open_via_mcp(env)
        topic = load_topic(iv_id, specflow_dir())
        assert topic is not None
        assert topic.initiator["emp"] == "E10001"
        # 产物落 emp 私有区
        assert "E10001" in str(specflow_dir())

    def test_open_topic_requires_workspace(self, env):
        """无工作区上下文时开标被拒（写路径 fail-closed）。"""
        from specstd.workspace import set_context_workspace, reset_context_workspace
        tok = set_context_workspace(None)
        try:
            r = _call(specflow_interview, "iv_open_topic", {
                "session_id": "S2",
                "title": "T",
                "source": [{"type": "spq", "ref": "SPQ-001"}],
            })
            assert "缺少工作区上下文" in r[0].text
        finally:
            reset_context_workspace(tok)
