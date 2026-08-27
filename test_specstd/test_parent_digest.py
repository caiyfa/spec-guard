"""T-1032 父会话脉络感知：session_digest 纯函数 / parent 工具门卫 / 路由触发链。

方案②（run 完成→摘要落盘）与方案③（辅助会话限界读取工具）的离线回归面：
- 摘要生命周期：写入→幂等跳过→内容增长过期重写→LLM 失败诚实降级骨架；
- parent 工具：仅 kind=aux 可用、锁死本链接父会话、summary/recent 两动作、
  缺摘要时指路 recent；不收任何会话 ID 参数（横向越权面为零）；
- 快照提示行只在工具白名单含 aux 域时出现（存量辅助会话 M5 不回流语义）。
"""
import asyncio
import json
from pathlib import Path

import pytest

# ══════════════════════════════════════════════════════════
# sg_core.session_digest 纯函数层
# ══════════════════════════════════════════════════════════

def _sample_msgs() -> list[dict]:
    return [
        {"role": "user", "content": "<parent_context>x</parent_context>"
                                    "帮我生成 HI-PERM-002 权限场景"},
        {"role": "assistant", "content": "先查注册表", "tool_calls": [
            {"function": {"name": "query_registry",
                          "arguments": json.dumps({"keyword": "history"})}}]},
        {"role": "tool", "tool_call_id": "t1",
         "content": '{"tools": ["select_emp"]}'},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_draft",
                          "arguments": json.dumps(
                              {"filename": "HI-PERM-002.yaml", "content": "doc: x"})}}]},
        {"role": "assistant", "content": "草稿 v1 已落盘，等待试跑验证。"},
    ]


class TestTranscriptAndSkeleton:
    def test_injected_blocks_stripped_from_transcript(self):
        from sg_core.session_digest import render_transcript
        t = render_transcript([{"role": "user",
                                "content": "<knowledge_refs>叙事</knowledge_refs>真实提问"}])
        assert "知识" not in t or "叙事" not in t
        assert "真实提问" in t

    def test_tool_calls_rendered_as_lines(self):
        from sg_core.session_digest import render_transcript
        t = render_transcript(_sample_msgs())
        assert "write_draft(filename=HI-PERM-002.yaml)" in t
        assert "[用户] 帮我生成 HI-PERM-002 权限场景" in t

    def test_skeleton_marks_mode_and_lists_markers(self):
        from sg_core.session_digest import skeleton_digest
        s = skeleton_digest("P1", _sample_msgs())
        assert "骨架模式" in s          # 诚实标注：LLM 不可用的确定性兜底
        assert "HI-PERM-002.yaml" in s


class TestRefreshDigestLifecycle:
    def test_write_skip_grow_llm_and_failure_fallback(self, tmp_path):
        from sg_core import session_digest as sd
        d = str(tmp_path)

        r1 = sd.refresh_digest(d, "P1", _sample_msgs())
        assert r1["action"] == "written" and r1["mode"] == "skeleton"
        md, mj = sd.paths_for(d, "P1")
        assert "骨架模式" in md.read_text(encoding="utf-8")

        # 幂等：未变化跳过（不重复烧 token）
        assert sd.refresh_digest(d, "P1", _sample_msgs())["action"] == "skipped"

        # 增长 → 过期重写；带 LLM 通道且转录够长（≥200 字符门槛）→ mode=llm
        grown = _sample_msgs() + [{"role": "assistant",
                                   "content": "试跑 PASS：total=55 与 DB COUNT 一致。"
                                              + "补充证据链与归因说明。" * 12}]
        r3 = sd.refresh_digest(d, "P1", grown,
                               llm_call=lambda sys_, usr: f"## 当前主题\n{usr[-20:]}")
        assert r3["action"] == "written" and r3["mode"] == "llm"
        assert "当前主题" in md.read_text(encoding="utf-8")

        # LLM 抛错 → 诚实降级骨架，绝不把原文冒充 LLM 摘要
        def boom(sys_, usr):
            raise RuntimeError("model down")
        # 同内容会被幂等跳过（防重复烧 token），故 force 强制重生成验证降级路径
        r4 = sd.refresh_digest(d, "P1", grown, llm_call=boom, force=True)
        assert r4["mode"] == "skeleton"
        assert "骨架模式" in md.read_text(encoding="utf-8")

    def test_short_session_cleans_artifacts(self, tmp_path):
        from sg_core import session_digest as sd
        d = str(tmp_path)
        sd.refresh_digest(d, "P2", [{"role": "user", "content": "只有一条"}])
        md, mj = sd.paths_for(d, "P2")
        assert not md.exists() and not mj.exists()

    def test_recent_window_bounded_and_newest_last(self, tmp_path):
        from sg_core.session_digest import render_recent_window
        many = [{"role": "user", "content": f"问题{i}"} for i in range(30)]
        out = render_recent_window(many, max_messages=5)
        assert "问题29" in out and "问题10" not in out      # 保最新
        big = [{"role": "user", "content": "x" * 3000} for _ in range(50)]
        out2 = render_recent_window(big, max_messages=14, max_chars=5000)
        assert len(out2) <= 5200


# ══════════════════════════════════════════════════════════
# parent 工具：门卫 + 两动作
# ══════════════════════════════════════════════════════════

@pytest.fixture
def parent_setup(tmp_path):
    """tmp 会话目录 + 父会话已落盘消息链；返回 (sessions_dir, parent_sid)。"""
    from agent.session import SessionManager
    sm = SessionManager(tmp_path, workspace="w1")
    pid = sm.create(emp_no="e", workspace="w1")
    sm.save(pid, _sample_msgs(), emp_no="e", workspace="w1")
    return str(sm.sessions_dir), pid


def _call(action, scope):
    from mcp_server.tools import parent_tool
    from sg_core.session_context import reset_runtime_scope, set_runtime_scope
    tok = set_runtime_scope(scope)
    try:
        return asyncio.run(parent_tool.handle("parent", {"action": action}))
    finally:
        reset_runtime_scope(tok)


def _text(result) -> str:
    return result[0].text


def test_parent_requires_session_context(parent_setup):
    result = _call("summary", {})
    payload = json.loads(_text(result))
    assert payload["ok"] is False and "无会话上下文" in payload["error"]
    # MCP stdio 场景（scope=None）同口径拒绝
    assert "无会话上下文" in _text(_call("summary", None)) or \
           json.loads(_text(_call("summary", None)))["ok"] is False


def test_parent_rejects_non_aux_sessions(parent_setup):
    sessions_dir, _pid = parent_setup
    result = _call("summary", {"sid": "MAIN1", "kind": "", "purpose": "test_workbench",
                               "parent_sid": "", "title": "", "sessions_dir": sessions_dir})
    payload = json.loads(_text(result))
    assert payload["ok"] is False and "不是辅助会话" in payload["error"]


def test_parent_summary_returns_digest_with_freshness(parent_setup):
    from sg_core import session_digest as sd
    sessions_dir, pid = parent_setup
    sd.refresh_digest(sessions_dir, pid, _sample_msgs())
    result = _call("summary", {"sid": "AUX1", "kind": "aux", "purpose": "sql_assistant",
                               "parent_sid": pid, "title": "",
                               "sessions_dir": sessions_dir})
    text = _text(result)
    assert "[父会话 " + pid + "]" in text
    assert "新鲜度" in text
    assert "脉络摘要" in text or "骨架" in text


def test_parent_summary_missing_digest_points_to_recent(parent_setup):
    sessions_dir, pid = parent_setup
    result = _call("summary", {"sid": "AUX1", "kind": "aux", "purpose": "sql_assistant",
                               "parent_sid": pid, "title": "",
                               "sessions_dir": sessions_dir})
    payload = json.loads(_text(result))
    assert payload["ok"] is False
    assert "action=recent" in payload["error"]   # 指路，不给死胡同


def test_parent_recent_reads_window(parent_setup):
    sessions_dir, pid = parent_setup
    result = _call("recent", {"sid": "AUX1", "kind": "aux", "purpose": "sql_assistant",
                              "parent_sid": pid, "title": "",
                              "sessions_dir": sessions_dir})
    text = _text(result)
    assert "草稿 v1 已落盘" in text       # 最新回复可见
    assert "write_draft" in text          # 工具调用要点可见

    # 父会话不可读降级
    result2 = _call("recent", {"sid": "AUX1", "kind": "aux", "purpose": "sql_assistant",
                               "parent_sid": "NOPE1234", "title": "",
                               "sessions_dir": sessions_dir})
    payload = json.loads(_text(result2))
    assert payload["ok"] is False and "不存在或不可读" in payload["error"]

    # 未知 action 拒绝
    result3 = _call("delete_all", {"sid": "AUX1", "kind": "aux",
                                   "parent_sid": pid, "sessions_dir": sessions_dir})
    assert "未知 action" in _text(result3)


def test_parent_tool_whitelist_domain_scoping():
    """aux 域只对声明它的 purpose 生效——主会话工具面零污染。"""
    from agent.runtime import resolve_tools
    aux = resolve_tools([], ["tester"], purpose_domains=["run", "spec", "scenario", "draft", "aux"])
    main = resolve_tools([], ["tester"],
                         purpose_domains=["spec", "scenario", "run", "draft",
                                          "knowledge", "quality", "meta"])
    assert any(t.name == "parent" for t in aux)
    assert all(t.name != "parent" for t in main)


# ══════════════════════════════════════════════════════════
# 路由侧：后台刷新助手 + 快照提示行
# ══════════════════════════════════════════════════════════

def test_refresh_bg_helper_writes_skeleton(tmp_path):
    from agent.session import SessionManager
    from test_specstd.routers_shim import _refresh_parent_digest_bg
    sm = SessionManager(tmp_path, workspace="w1")
    pid = sm.create(emp_no="e", workspace="w1")
    sm.save(pid, _sample_msgs(), emp_no="e", workspace="w1")
    report = _refresh_parent_digest_bg(sm, pid, None)     # llm=None → 骨架
    assert report is not None and report.get("action") == "written"
    md, _mj = sm.sessions_dir / f"{pid}_digest.md", None
    assert Path(md).is_file()


def test_snapshot_digest_hint_line_gated_by_whitelist_flag(tmp_path):
    from agent.session import SessionManager
    from sg_core import session_digest as sd
    from test_specstd.routers_shim import _parent_snapshot
    sm = SessionManager(tmp_path, workspace="w1")
    pid = sm.create(emp_no="e", workspace="w1")
    sm.save(pid, _sample_msgs(), emp_no="e", workspace="w1")
    sd.refresh_digest(str(sm.sessions_dir), pid, _sample_msgs())

    block_on, _fp1 = _parent_snapshot(sm, pid, "", include_digest_hint=True)
    assert "parent 工具读取" in block_on and "action=summary" in block_on

    block_off, _fp2 = _parent_snapshot(sm, pid, "", include_digest_hint=False)
    assert "parent 工具读取" not in block_off


def test_refresh_bg_passes_callable_llm_wrapper(monkeypatch, tmp_path):
    """验收缺陷 C 钉子：_refresh_parent_digest_bg 必须把 _llm 包装闭包（可调用）
    交给 refresh_digest——曾误传 LLMClient 实例本身，refresh_digest 以
    llm_call(system,user) 调用即抛 'LLMClient' object is not callable，
    每轮摘要全量静默降骨架。"""
    from types import SimpleNamespace
    from workbench.backend.routers import agent as rag

    captured = {}

    class FakeLLM:
        is_mock = False

        def chat(self, prompt, tools=None):
            assert prompt[0]["role"] == "system" and prompt[1]["role"] == "user"
            return {"content": "# LLM 脉络摘要"}, {"total_tokens": 1}

    def fake_refresh(sessions_dir, sid, msgs, llm_call=None, force=False):
        captured["llm_call"] = llm_call
        assert callable(llm_call), "llm_call 必须是可调用包装，而非客户端实例"
        assert llm_call("s", "u") == "# LLM 脉络摘要"
        return {"action": "written", "mode": "llm"}

    monkeypatch.setattr("sg_core.session_digest.refresh_digest", fake_refresh)
    sm = SimpleNamespace(sessions_dir=str(tmp_path),
                         load=lambda _sid: [{"role": "user", "content": "hi"},
                                            {"role": "assistant", "content": "yo"}])

    report = rag._refresh_parent_digest_bg(sm, "sidX", FakeLLM())
    assert report == {"action": "written", "mode": "llm"}
    assert callable(captured["llm_call"])


def test_refresh_bg_mock_llm_falls_back_to_skeleton_path(monkeypatch, tmp_path):
    """mock/未配置模型时 llm_call 为 None——骨架兜底通道不受缺陷 C 修复影响。"""
    from types import SimpleNamespace
    from workbench.backend.routers import agent as rag

    captured = {}

    class MockLLM:
        is_mock = True

        def chat(self, prompt, tools=None):  # pragma: no cover - 不应被走到
            raise AssertionError("mock 模型不应参与摘要生成")

    def fake_refresh(sessions_dir, sid, msgs, llm_call=None, force=False):
        captured["llm_call"] = llm_call
        return {"action": "written", "mode": "skeleton"}

    monkeypatch.setattr("sg_core.session_digest.refresh_digest", fake_refresh)
    sm = SimpleNamespace(sessions_dir=str(tmp_path),
                         load=lambda _sid: [{"role": "user", "content": "hi"}])
    report = rag._refresh_parent_digest_bg(sm, "sidX", MockLLM())
    assert report["mode"] == "skeleton"
    assert captured["llm_call"] is None
