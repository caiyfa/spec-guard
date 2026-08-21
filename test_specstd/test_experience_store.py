"""experience_store 测试（T-510 经验飞轮）。

覆盖：
- run 终局落行（failed 场景 → 经验草稿 .md + _meta.json 登记，幂等）
- 用户纠正关键词检测（corrected）
- recency×hit_count 检索（≤2KB 封顶、命中计数）
- 👍/👎 反馈 API（rating 落盘）
- 物理隔离（经验按工作区 .specguard/experience/ 隔离）
"""

import json
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from services import experience_store as es  # noqa: E402


def _mk_run(tmp_path: Path, run_id: str = "EX-test001") -> Path:
    """构造一个含 FAIL 场景的 run.json + cases 目录。"""
    run_dir = tmp_path / run_id
    (run_dir / "cases").mkdir(parents=True)
    (run_dir / "cases" / "PP-RC-005.json").write_text(json.dumps({
        "id": "PP-RC-005", "verdict": "FAIL",
        "failure": {"message": "断言差异: 期望 3 行实际 2 行", "category": "assert"},
        "steps": [{"tool": "read_spec"}],
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_id, "env": "sit",
        "cases": [
            {"id": "PP-RC-005", "verdict": "FAIL", "title": "切片模式查询",
             "file": "cases/PP-RC-005.json"},
            {"id": "IS-PREP-002", "verdict": "PASS", "title": "数据准备",
             "file": "cases/IS-PREP-002.json"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    """工作区根（含 .specguard/ 目录）。"""
    root = tmp_path / "tdm"
    (root / ".specguard").mkdir(parents=True)
    return root


# ══════════════════════════════════════════════════════════
# run 终局落行
# ══════════════════════════════════════════════════════════

class TestRunAppend:
    def test_append_failed_scenario(self, tmp_path, ws):
        """run 终局：FAIL 场景落经验草稿（PASS 不落），_meta.json 登记。"""
        root = _mk_run(tmp_path)
        n = es.append_experience(root, "EX-test001", ws)
        assert n == 1  # 仅 FAIL 场景
        exp_dir = ws / ".specguard" / "experience"
        files = list(exp_dir.glob("*.md"))
        assert len(files) == 1
        md = files[0].read_text(encoding="utf-8")
        assert "PP-RC-005" in md
        assert "断言差异" in md  # 现象段带失败消息
        meta = json.loads((exp_dir / "_meta.json").read_text(encoding="utf-8"))
        token = files[0].stem
        assert meta[token]["run_id"] == "EX-test001"
        assert meta[token]["verdict"] == "FAIL"
        assert meta[token]["hit_count"] == 0

    def test_append_idempotent(self, tmp_path, ws):
        """幂等：同一 run_id 重复调用不重复落行。"""
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        n2 = es.append_experience(root, "EX-test001", ws)
        assert n2 == 0
        exp_dir = ws / ".specguard" / "experience"
        assert len(list(exp_dir.glob("*.md"))) == 1

    def test_no_run_json_returns_zero(self, tmp_path, ws):
        assert es.append_experience(tmp_path, "EX-none", ws) == 0


# ══════════════════════════════════════════════════════════
# 用户纠正关键词检测
# ══════════════════════════════════════════════════════════

class TestCorrectionDetect:
    def test_correction_keywords(self):
        assert es.detect_correction("不对，这个结论错了") is True
        assert es.detect_correction("应该是 3 行才对") is True
        assert es.detect_correction("帮我看看为什么失败") is False
        assert es.detect_correction("") is False

    def test_record_corrected(self, tmp_path, ws):
        """纠正落行：corrected 状态写入 meta（run 成功后用户纠正也留痕）。"""
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        token = list((ws / ".specguard" / "experience").glob("*.md"))[0].stem
        es.mark_corrected(ws, token)
        meta = json.loads((ws / ".specguard" / "experience" / "_meta.json").read_text(encoding="utf-8"))
        assert meta[token]["corrected"] is True


# ══════════════════════════════════════════════════════════
# 检索（recency×hit_count，≤2KB 封顶）
# ══════════════════════════════════════════════════════════

class TestSearch:
    def test_search_and_hit_count(self, tmp_path, ws):
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        # 命中检索 → hit_count 递增
        results = es.search_experiences(ws, "PP-RC-005")
        assert len(results) == 1
        token = results[0]["token"]
        assert results[0]["hit_count"] == 1
        # 再次检索 → 2（recency×hit_count 排序信号）
        results2 = es.search_experiences(ws, "PP-RC-005")
        assert results2[0]["hit_count"] == 2

    def test_search_budget_cap(self, tmp_path, ws):
        """≤2KB 封顶：注入文本总长不超 2KB。"""
        for i in range(5):
            run_dir = _mk_run(tmp_path, f"EX-test{i:03d}")
            es.append_experience(run_dir, f"EX-test{i:03d}", ws)
        results = es.search_experiences(ws, "断言", limit=2000)
        total = sum(len(r["text"]) for r in results)
        assert total <= 2000

    def test_search_empty(self, ws):
        assert es.search_experiences(ws, "x") == []


# ══════════════════════════════════════════════════════════
# 👍/👎 反馈 + 物理隔离
# ══════════════════════════════════════════════════════════

class TestRating:
    def test_rate_up_down(self, tmp_path, ws):
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        token = list((ws / ".specguard" / "experience").glob("*.md"))[0].stem
        assert es.rate_experience(ws, token, "up") is True
        meta = json.loads((ws / ".specguard" / "experience" / "_meta.json").read_text(encoding="utf-8"))
        assert meta[token]["rating"] == "up"

    def test_rate_invalid(self, tmp_path, ws):
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        token = list((ws / ".specguard" / "experience").glob("*.md"))[0].stem
        assert es.rate_experience(ws, token, "sideways") is False

    def test_physical_isolation(self, tmp_path):
        """经验按工作区隔离：ws_a 落行不影响 ws_b。"""
        root = _mk_run(tmp_path)
        ws_a = tmp_path / "a"; (ws_a / ".specguard").mkdir(parents=True)
        ws_b = tmp_path / "b"; (ws_b / ".specguard").mkdir(parents=True)
        es.append_experience(root, "EX-test001", ws_a)
        assert len(es.search_experiences(ws_a, "PP-RC-005")) == 1
        assert es.search_experiences(ws_b, "PP-RC-005") == []

    def test_draft_text_has_five_sections(self, tmp_path, ws):
        """落行草稿为五段式（提炼为经验包的前置形态）。"""
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        md = list((ws / ".specguard" / "experience").glob("*.md"))[0].read_text(encoding="utf-8")
        for sec in ("现象", "证据链", "根因", "修复", "预防"):
            assert sec in md


# ══════════════════════════════════════════════════════════
# runtime 集成（纠正检测 → 经验检索注入）
# ══════════════════════════════════════════════════════════

class TestRuntimeExperience:
    def test_correction_triggers_experience_refs(self, tmp_path, ws):
        """用户纠正关键词 → <experience_refs> 注入（≤2KB 封顶由 search 保证）。"""
        from agent.runtime import AgentRuntime
        from unittest.mock import MagicMock, patch
        # 预置经验库
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)

        llm = MagicMock()
        llm.is_mock = True
        llm.chat.return_value = ({"role": "assistant", "content": "好的", "tool_calls": None}, {})
        llm.max_context_tokens = 128000
        runtime = AgentRuntime(llm)
        # 拦截工作区解析（指向测试 ws）
        with patch("specstd.workspace.get_workspace_root", return_value=ws):
            messages = runtime.run("sys", "不对，PP-RC-005 这个结论错了，应该是 3 行")
        joined = "\n".join(str(m.get("content", "")) for m in messages)
        assert "<experience_refs>" in joined
        assert "PP-RC-005" in joined  # 经验 token 注入

    def test_no_correction_no_experience_refs(self, tmp_path, ws):
        """无纠正关键词 → 不注入经验（防噪音）。"""
        from agent.runtime import AgentRuntime
        from unittest.mock import MagicMock, patch
        root = _mk_run(tmp_path)
        es.append_experience(root, "EX-test001", ws)
        llm = MagicMock()
        llm.is_mock = True
        llm.chat.return_value = ({"role": "assistant", "content": "好的", "tool_calls": None}, {})
        llm.max_context_tokens = 128000
        runtime = AgentRuntime(llm)
        with patch("specstd.workspace.get_workspace_root", return_value=ws):
            messages = runtime.run("sys", "你好")
        joined = "\n".join(str(m.get("content", "")) for m in messages)
        assert "<experience_refs>" not in joined
