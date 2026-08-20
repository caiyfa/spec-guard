"""llm_client SSE 流式（K-012）+ runtime 未知工具提示 测试。

- 流式：httpx MockTransport 构造 SSE 响应，验证 delta 回调序列 / tool_calls 组装 / usage / 回退
- 未知工具：模式白名单剔除旧工具后返回自我纠正提示（而非干巴巴「未知工具」打断流程）

DB 隔离：monkeypatch _load_db_config 返回 {}（K-001 教训：避免读真实 workbench.db）。
"""

import json
import sys
from pathlib import Path

import httpx
import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.llm_client import LLMClient
from agent.runtime import AgentRuntime


def _make_client(handler, monkeypatch) -> LLMClient:
    """构造注入 MockTransport 的客户端（隔离 DB 配置读取）。"""
    monkeypatch.setattr(LLMClient, "_load_db_config", staticmethod(lambda model_id="": {}))
    c = LLMClient(base_url="http://llm.test", api_key="k", model="m", timeout=5)
    c._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    return c


MESSAGES = [{"role": "user", "content": "hi"}]


def _sse(*chunks: str) -> str:
    """把若干 data 载荷拼成 SSE 文本。"""
    return "".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n"


class TestStream:
    def test_content_deltas_in_order(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["stream"] is True
            assert body["stream_options"] == {"include_usage": True}
            return httpx.Response(200, text=_sse(
                '{"choices":[{"delta":{"content":"你"}}]}',
                '{"choices":[{"delta":{"content":"好"}}]}',
                '{"choices":[{"delta":{"content":"！"}}]}',
                '{"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
            ), headers={"Content-Type": "text/event-stream"})

        deltas = []
        msg, usage = _make_client(handler, monkeypatch).chat(
            MESSAGES, on_delta=deltas.append)
        assert deltas == ["你", "好", "！"]
        assert msg["content"] == "你好！"
        assert "tool_calls" not in msg
        assert usage["total_tokens"] == 5

    def test_tool_calls_accumulated_across_chunks(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_sse(
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"val"}}]}}]}',
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"idate","arguments":"{\\"a\\""}}]}}]}',
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":1}"}}]}}]}',
                '{"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_2","function":{"name":"write_draft","arguments":"{}"}}]}}]}',
                '{"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}',
            ))

        msg, _ = _make_client(handler, monkeypatch).chat(MESSAGES, on_delta=lambda t: None)
        tcs = msg["tool_calls"]
        assert [tc["id"] for tc in tcs] == ["call_1", "call_2"]
        assert tcs[0]["function"] == {"name": "validate", "arguments": '{"a":1}'}
        assert tcs[1]["function"]["name"] == "write_draft"
        assert msg["content"] == ""

    def test_missing_usage_tolerated(self, monkeypatch):
        """网关不支持 include_usage 时 usage 为空 dict，不报错。"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_sse('{"choices":[{"delta":{"content":"ok"}}]}'))

        msg, usage = _make_client(handler, monkeypatch).chat(MESSAGES, on_delta=lambda t: None)
        assert msg["content"] == "ok"
        assert usage == {}

    def test_stream_refused_falls_back_to_nonstream(self, monkeypatch):
        """流式建连失败（未产出 delta）→ 自动回退非流式，结果完整。"""
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body.get("stream"):
                return httpx.Response(400, text="stream not supported")
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": "完整回复"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })

        deltas = []
        msg, usage = _make_client(handler, monkeypatch).chat(
            MESSAGES, on_delta=deltas.append)
        assert deltas == []  # 流式未产出任何 delta
        assert msg["content"] == "完整回复"
        assert usage["total_tokens"] == 2

    def test_midstream_failure_falls_back(self, monkeypatch):
        """流式产出部分 delta 后中断 → 回退非流式取完整结果（前端以最终消息为准）。"""
        def broken_gen():
            yield b'data: {"choices":[{"delta":{"content":"\xe9\x83\xa8"}}]}\n\n'
            raise httpx.ReadError("connection reset")

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body.get("stream"):
                return httpx.Response(200, content=broken_gen())
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": "部分回复（完整）"}}],
                "usage": {},
            })

        deltas = []
        msg, _ = _make_client(handler, monkeypatch).chat(MESSAGES, on_delta=deltas.append)
        assert deltas == ["部"]  # 已产出的部分 delta 如实回调过
        assert msg["content"] == "部分回复（完整）"  # 最终以非流式完整结果为准


class TestBuildBodyStrip:
    """K-013：_build_body 清洗非标准字段（reasoning_content / references）。"""

    def test_strips_references_and_reasoning(self, monkeypatch):
        monkeypatch.setattr(LLMClient, "_load_db_config", staticmethod(lambda model_id="": {}))
        c = LLMClient(base_url="http://llm.test", api_key="k", model="m", timeout=5)
        body = c._build_body([
            {"role": "user", "content": "hi",
             "references": [{"type": "file", "path": "a.md", "sha": "x"}]},
            {"role": "assistant", "content": "ok", "reasoning_content": "思考"},
        ], None, 0.7)
        assert "references" not in body["messages"][0]
        assert "reasoning_content" not in body["messages"][1]
        assert body["messages"][0]["content"] == "hi"


class TestUnknownToolHint:
    """K-023：全量工具常驻后，只有「真未知」（LLM 编造）的工具名才触发纠正提示。"""

    def _runtime(self, mode: str) -> AgentRuntime:
        class _MockLLM:
            is_mock = True
            max_context_tokens = 0
        return AgentRuntime(_MockLLM(), mode_name=mode)

    def test_all_tools_available_any_mode(self):
        """K-023 核心：任何模式都可直接调用 validate 等工具——不再有「模式未挂载」。"""
        rt = self._runtime("audit")
        result = rt._execute_tool({"function": {"name": "validate", "arguments": "{\"content\": \"id: X\\nflow: []\\nverify: []\"}"}})
        assert "未知工具" not in result
        assert "当前模式" not in result

    def test_truly_unknown_tool(self):
        """完全不存在的工具 → 「未知工具」+ 可用清单（自愈路径保留）。"""
        rt = self._runtime("audit")
        result = rt._execute_tool({"function": {"name": "nonexistent_xyz", "arguments": "{}"}})
        assert "未知工具: nonexistent_xyz" in result
        assert "可用工具" in result


# ══════════════════════════════════════════════════════════
# T-951a：MiniMax-M3 接入兜底（<think> 标签剥离）
# ══════════════════════════════════════════════════════════
# 背景：MiniMax-M3 OpenAI 兼容接口 thinking 默认开启，content 混入
# <think>…</think>；下游 _parse_llm_json/captions 直接解析会炸。
# 剥离在 LLMClient 出口做（对所有模型通用无侵入——正常内容不含该标签）。

def test_strip_think_tags_full():
    """完整 think 块剥离（含多行思考内容）。"""
    from agent.llm_client import _strip_think_tags
    content = "<think>用户要求聚类，我先分析消息\n再考虑分组</think>{\"topics\": []}"
    assert _strip_think_tags(content) == "{\"topics\": []}"


def test_strip_think_tags_none_and_plain():
    """无标签内容原样返回（空串/普通文本/含尖括号但不匹配）。"""
    from agent.llm_client import _strip_think_tags
    assert _strip_think_tags("") == ""
    assert _strip_think_tags("普通回复") == "普通回复"
    assert _strip_think_tags("<div>不是思考</div>") == "<div>不是思考</div>"


def test_strip_think_tags_leading_whitespace():
    """剥离后清理首尾空白（M3 常见：think 块后换行再正文）。"""
    from agent.llm_client import _strip_think_tags
    assert _strip_think_tags("<think>x</think>\n\n  正文  ") == "正文"
