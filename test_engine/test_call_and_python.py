"""引擎离线单测：call Apifox 参数体系（headers/cookies/body_type）+ python 原语。"""

import os
import sys
from types import SimpleNamespace

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.execution_record import ExecutionRecord  # noqa: E402
from engine.scenario_runner import step_call, step_python, SkipScenario, ScenarioScriptError  # noqa: E402


# ══════════════════════════════════════════════════════════
# 假 HTTP 客户端（记录请求参数）
# ══════════════════════════════════════════════════════════

class _FakeResp:
    status_code = 200
    headers = {"X-Api-Version": "1.0.0(abcdefg)"}

    def json(self):
        return {"ok": True}


class _FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **kw):
        self.calls.append({"method": method, "path": path, **kw})
        return _FakeResp()


def _rctx(client):
    return SimpleNamespace(http_client=lambda account, service='tdm': client, db=None, dbs={})


# ══════════════════════════════════════════════════════════
# step_call：Apifox 参数体系
# ══════════════════════════════════════════════════════════

def test_call_headers_cookies_passthrough():
    client = _FakeClient()
    record = ExecutionRecord(scenario_id="T")
    step_call({"method": "GET", "path": "/api/x",
               "headers": {"X-Trace": "{{tid}}"}, "cookies": {"sid": "abc"},
               "save": "r"}, _rctx(client), {"tid": "t-123"}, record)
    call = client.calls[0]
    assert call["headers"] == {"X-Trace": "t-123"}
    assert call["cookies"] == {"sid": "abc"}


def test_call_default_json_body():
    client = _FakeClient()
    record = ExecutionRecord(scenario_id="T")
    step_call({"method": "POST", "path": "/api/x", "json": {"a": 1}, "save": "r"},
              _rctx(client), {}, record)
    assert client.calls[0]["json_body"] == {"a": 1}
    assert client.calls[0]["data"] is None


def test_call_urlencoded():
    client = _FakeClient()
    record = ExecutionRecord(scenario_id="T")
    step_call({"method": "POST", "path": "/api/x", "body_type": "urlencoded",
               "urlencoded": {"user": "zhang"}, "save": "r"}, _rctx(client), {}, record)
    call = client.calls[0]
    assert call["data"] == {"user": "zhang"}
    assert call["json_body"] is None
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_call_raw_with_content_type():
    client = _FakeClient()
    record = ExecutionRecord(scenario_id="T")
    step_call({"method": "POST", "path": "/api/x", "body_type": "raw",
               "raw": "<xml>hi</xml>", "content_type": "application/xml", "save": "r"},
              _rctx(client), {}, record)
    call = client.calls[0]
    assert call["data"] == "<xml>hi</xml>"
    assert call["headers"]["Content-Type"] == "application/xml"


def test_call_form_with_file(tmp_path):
    f = tmp_path / "up.txt"
    f.write_text("hello", encoding="utf-8")
    client = _FakeClient()
    record = ExecutionRecord(scenario_id="T")
    step_call({"method": "POST", "path": "/api/x", "body_type": "form",
               "form": {"biz": "import", "attachment": f"@{f}"}, "save": "r"},
              _rctx(client), {}, record)
    call = client.calls[0]
    assert call["data"] == {"biz": "import"}
    assert call["files"]["attachment"][0] == "up.txt"


def test_call_binary(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\x00\x01\x02")
    client = _FakeClient()
    record = ExecutionRecord(scenario_id="T")
    step_call({"method": "POST", "path": "/api/x", "body_type": "binary",
               "file": str(f), "save": "r"}, _rctx(client), {}, record)
    call = client.calls[0]
    assert call["headers"]["Content-Type"] == "application/octet-stream"
    assert hasattr(call["data"], "read")


def test_call_invalid_body_type_rejected():
    record = ExecutionRecord(scenario_id="T")
    with pytest.raises(ValueError, match="body_type 非法"):
        step_call({"method": "POST", "path": "/x", "body_type": "graphql"},
                  _rctx(_FakeClient()), {}, record)


# ══════════════════════════════════════════════════════════
# python 原语
# ══════════════════════════════════════════════════════════

def test_python_step_output_and_save():
    record = ExecutionRecord(scenario_id="T")
    ns = {"rows": [{"s": 1}, {"s": None}, {"s": 3}]}
    out = step_python({"script": "output = [r for r in ns['rows'] if r['s'] is None]",
                       "save": "null_rows"},
                      _rctx(None), ns, record)
    assert out == [{"s": None}]
    assert record.steps[-1].type == "python"


def test_python_step_ns_write_through():
    record = ExecutionRecord(scenario_id="T")
    ns = {}
    step_python({"script": "ns['x'] = 41 + 1\nsave('y', ns['x'] * 2)"},
                _rctx(None), ns, record)
    assert ns["x"] == 42 and ns["y"] == 84


def test_python_step_print_captured():
    record = ExecutionRecord(scenario_id="T")
    step_python({"script": "print('hello specguard')"}, _rctx(None), {}, record)
    assert "hello specguard" in record.steps[-1].note


def test_python_step_fn_helpers():
    record = ExecutionRecord(scenario_id="T")
    ns = {}
    step_python({"script": "ns['d'] = fn.date()\nns['u'] = fn.uuid_short()"},
                _rctx(None), ns, record)
    assert len(ns["d"]) == 8 and len(ns["u"]) == 8


def test_python_step_skip_scenario():
    record = ExecutionRecord(scenario_id="T")
    with pytest.raises(SkipScenario):
        step_python({"script": "raise SkipScenario('无候选', category='pool_empty')"},
                    _rctx(None), {}, record)


def test_python_step_error_propagates():
    record = ExecutionRecord(scenario_id="T")
    # ENG-T01：python 步骤脚本异常经包装为 ScenarioScriptError（归 CAT_SCENARIO），不再裸抛 KeyError
    with pytest.raises(ScenarioScriptError):
        step_python({"script": "ns['missing']"}, _rctx(None), {}, record)


def test_python_step_missing_script_rejected():
    record = ExecutionRecord(scenario_id="T")
    with pytest.raises(ValueError, match="缺少 script"):
        step_python({}, _rctx(None), {}, record)
