"""T-314 执行日志信息密度单测：调用锚点带响应摘要/耗时，断言结果进日志。

背景：EX-a78498c3 执行日志只有一行「POST /api/system/tags → 500 | trace=...」，
请求/响应体/断言详情全在 run.json——日志与报告「对不上」。增强后引擎执行轨迹
（调用摘要、断言结果）实时进 stdout（-s 流入执行日志）。
"""

import os
import sys
import time
from types import SimpleNamespace

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from engine.http_client import HttpClient  # noqa: E402
from engine import scenario_runner as sr  # noqa: E402


def _fake_resp(status=500, body=None, trace="trace-abc"):
    """伪 requests.Response（json()/headers 可用的最小形态）。"""
    headers = {"X-Trace-Id": trace} if trace else {}
    return SimpleNamespace(status_code=status, headers=headers,
                           json=lambda: body, text=str(body))


def _http(monkeypatch, resp):
    client = HttpClient("http://gw", token_provider=None)
    monkeypatch.setattr(client.session, "request",
                        lambda *a, **k: resp)
    return client


class TestHttpAnchorDensity:
    """调用锚点：method/path → 状态 | 耗时 | 响应体摘要 | trace。"""

    def test_anchor_includes_body_and_elapsed(self, monkeypatch, capsys):
        body = {"status": "500", "message": "系统异常", "data": "系统异常"}
        client = _http(monkeypatch, _fake_resp(500, body))
        started = time.monotonic()
        client.request("POST", "/api/system/tags", raise_on_error=False)
        elapsed = int((time.monotonic() - started) * 1000)
        out = capsys.readouterr().out
        assert "POST /api/system/tags → 500" in out
        assert "系统异常" in out, f"响应体摘要应进日志: {out}"
        assert "trace-abc" in out, f"trace 应保留: {out}"
        # 耗时应与真实耗时同数量级（≥0 且不超过 10 倍实际耗时）
        import re
        m = re.search(r"\| (\d+)ms", out)
        assert m, f"日志应含耗时: {out}"
        assert 0 <= int(m.group(1)) <= max(1, elapsed * 10)

    def test_anchor_escapes_brackets(self, monkeypatch, capsys):
        """响应体含数组时摘要转圆括号——防 runner._parse_line 把 [XX-XXX] 误判为场景 ID。"""
        body = {"items": ["IS-PREP-001", "TL-RC-014"]}
        client = _http(monkeypatch, _fake_resp(200, body))
        client.request("GET", "/api/x", raise_on_error=False)
        out = capsys.readouterr().out
        excerpt = out.split("body=", 1)[1].split(" | trace=", 1)[0]
        assert "[" not in excerpt, f"body 摘要不应含方括号: {excerpt}"
        assert "(\"IS-PREP-001\"" in excerpt, f"数组应转圆括号: {excerpt}"

    def test_anchor_without_trace(self, monkeypatch, capsys):
        client = _http(monkeypatch, _fake_resp(200, {"ok": True}, trace=""))
        client.request("GET", "/api/x", raise_on_error=False)
        out = capsys.readouterr().out
        assert "trace=" not in out


class TestAssertionLogFormat:
    """断言结果日志行格式（纯函数，_run_verifies 逐条调用）。"""

    def _trace(self, passed, expr="errResp.status == 400", message=""):
        return SimpleNamespace(passed=passed, expr=expr, message=message)

    def test_fail_format(self):
        line = sr.format_assertion_log(self._trace(False, message="实际状态 500 ≠ 预期 400"))
        assert line.startswith("[SpecGuard] 断言 errResp.status == 400 → ❌FAIL")
        assert "实际状态 500 ≠ 预期 400" in line

    def test_pass_format(self):
        line = sr.format_assertion_log(self._trace(True))
        assert "✅PASS" in line
        assert "❌" not in line
