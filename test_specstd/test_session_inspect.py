"""agent.inspect 开发期会话排查测试（T-321）。

背景：开发 SpecGuard 时按 sessionId 排查 Agent 对话问题——jsonl 里 system prompt
巨大、tool 调用与错误散布消息链，直接翻文件低效；export 又要用户操作。
inspect 脚本输出结构化排查视图：错误汇总优先 + 工具调用链 + 截断消息链。
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent import inspect  # noqa: E402


def _write_session(root: Path, emp: str, sid: str, workspace: str = "tdm",
                   lines: list = None, metrics: dict = None):
    """构造会话 jsonl（meta + 消息行 + 可选 metrics）。"""
    if workspace:
        d = root / emp / workspace
    else:
        d = root / emp
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.jsonl").write_text("\n".join(
        [json.dumps({"_type": "session_meta", "session_id": sid,
                     "emp_no": emp, "workspace": workspace,
                     "created_at": "2026-08-03T10:00:00"}, ensure_ascii=False)]
        + [json.dumps(x, ensure_ascii=False) for x in (lines or [])]
    ) + "\n", encoding="utf-8")
    if metrics:
        (d / f"{sid}_metrics.jsonl").write_text(
            json.dumps(metrics, ensure_ascii=False) + "\n", encoding="utf-8")


class TestFindSessionFile:
    def test_workspace_subdir(self, tmp_path):
        _write_session(tmp_path, "90024166", "SID001", workspace="tdm")
        p = inspect.find_session_file(tmp_path, "SID001", workspace="tdm")
        assert p is not None and p.name == "SID001.jsonl"

    def test_legacy_root_dir(self, tmp_path):
        """旧格式：无工作区子目录。"""
        _write_session(tmp_path, "90024166", "SID002", workspace="")
        p = inspect.find_session_file(tmp_path, "SID002")
        assert p is not None

    def test_not_found(self, tmp_path):
        assert inspect.find_session_file(tmp_path, "NOPE") is None


class TestSummarize:
    def _msgs(self):
        return [
            {"role": "system", "content": "你是 SpecGuard 助手。" * 50},  # 长 prompt
            {"role": "user", "content": "生成 TL-RC-066 场景"},
            {"role": "assistant", "content": "好的，我来生成。",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "write_draft",
                                          "arguments": '{"filename": "TL-RC-066.yaml"}'}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true, "path": "drafts/TL-RC-066.yaml"}'},
            {"role": "assistant", "content": "已生成草稿。"},
        ]

    def test_system_prompt_only_length(self):
        s = inspect.summarize_messages(self._msgs())
        first = s["turns"][0]
        assert first["role"] == "system" and first["kind"] == "prompt"
        assert "length" in first and "content" not in first, "prompt 不刷屏"

    def test_tool_calls_extracted(self):
        s = inspect.summarize_messages(self._msgs())
        assert s["tool_calls"] == [{"tool": "write_draft",
                                    "arguments": '{"filename": "TL-RC-066.yaml"}'}]

    def test_content_truncated(self):
        long = {"role": "user", "content": "长" * 1000}
        s = inspect.summarize_messages([long], truncate_chars=100)
        assert len(s["turns"][0]["content"]) <= 100 + 30  # 截断 + 尾注

    def test_errors_collected_and_flagged(self):
        msgs = [
            {"role": "system", "content": "[ERROR] LLM 调用失败: timeout"},
            {"role": "tool", "tool_call_id": "c1", "content": "工具执行异常: KeyError"},
        ]
        s = inspect.summarize_messages(msgs)
        assert len(s["errors"]) == 2, s["errors"]
        assert "timeout" in s["errors"][0] and "KeyError" in s["errors"][1]
        assert s["turns"][0]["error"] is True
        assert s["turns"][1]["error"] is True

    def test_clean_session_no_errors(self):
        s = inspect.summarize_messages(self._msgs())
        assert s["errors"] == []


class TestLoadSession:
    def test_full_load_with_metrics(self, tmp_path):
        _write_session(tmp_path, "90024166", "SID003", workspace="tdm",
                       lines=[{"role": "user", "content": "hi"}],
                       metrics={"_type": "metrics", "calls": 1, "total_tokens": 123})
        data = inspect.load_session(tmp_path, "SID003", workspace="tdm")
        assert data is not None
        assert data["meta"]["emp_no"] == "90024166"
        assert len(data["messages"]) == 1
        assert data["metrics"]["total_tokens"] == 123

    def test_missing_session(self, tmp_path):
        assert inspect.load_session(tmp_path, "NOPE") is None
