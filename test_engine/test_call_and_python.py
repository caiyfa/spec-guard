"""引擎离线单测：call Apifox 参数体系（headers/cookies/body_type）+ python 原语。"""

import os
from types import SimpleNamespace

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    # ENG-T03：binary 改传 bytes（流式句柄有 fd 泄漏与 401 重试空 body 问题）
    assert call["data"] == b"\x00\x01\x02"


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


# ══════════════════════════════════════════════════════════
# T-1018：脚本异常消息增强（NameError/KeyError 附 ns 可用键与访问范式）
# ══════════════════════════════════════════════════════════

def test_python_step_name_error_lists_ns_keys():
    """把 save 变量当脚本全局名（NameError）→ 错误消息附 ns 可用键清单。

    2026-08-26 HI-PERM-001 三连败实证：Agent 在脚本里写裸 roles_resp（或 {{}} 模板）
    报 NameError 后只能靠猜；消息直接给出可用键与正确范式可一轮自愈。
    """
    record = ExecutionRecord(scenario_id="T")
    ns = {"roles_resp": {"status": 200, "json": {}, "headers": {}}}
    with pytest.raises(ScenarioScriptError) as ei:
        step_python({"script": "data = roles_resp['json']"}, _rctx(None), ns, record)
    msg = str(ei.value)
    assert "ns 当前可用键" in msg and "roles_resp" in msg
    assert "ns['名']" in msg


def test_python_step_key_error_lists_ns_keys():
    """ns 键名写错（KeyError）→ 同样附可用键清单。"""
    record = ExecutionRecord(scenario_id="T")
    with pytest.raises(ScenarioScriptError) as ei:
        step_python({"script": "x = ns['roels_resp']"}, _rctx(None),
                    {"roles_resp": 1}, record)
    assert "ns 当前可用键" in str(ei.value) and "roles_resp" in str(ei.value)


def test_python_step_other_error_no_ns_hint():
    """非 NameError/KeyError 不附 ns 清单（保持原消息形态，防噪音）。"""
    record = ExecutionRecord(scenario_id="T")
    with pytest.raises(ScenarioScriptError) as ei:
        step_python({"script": "x = 1 / 0"}, _rctx(None), {"k": 1}, record)
    assert "ns 当前可用键" not in str(ei.value)


def test_python_step_system_exit_wrapped():
    """脚本 raise SystemExit(...) → 包装为 ScenarioScriptError，不得裸穿击穿 runner。

    2026-08-27 HI-PERM-004 实证（EX-dc874ada/EX-b9c359ba）：SystemExit 继承
    BaseException，except Exception 捕不到，裸放行直接崩掉运行进程——run.json
    空文件、工作台 Internal Server Error、UI 回退显示老报告。主动跳过的正道是
    SkipScenario（独立分支原样放行），SystemExit 一律按场景编写错误包装并指路。
    """
    record = ExecutionRecord(scenario_id="T")
    with pytest.raises(ScenarioScriptError) as ei:
        step_python({"script": "raise SystemExit('SIT 未配 corp 维度 PART 空 codes 成员')"},
                    _rctx(None), {}, record)
    msg = str(ei.value)
    assert "SystemExit" in msg
    assert "SkipScenario" in msg

