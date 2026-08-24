"""probe 连通性回归防护（T-999b 改名事故教训）。

事故回放：T-999b 批量重命名 _connect→db_connect 误伤 probe_connectivity
（定义被改成 probedb_connectivity、路由调用方未同步），probe 接口静默 500。
本文件三层钉死：① 函数名存在性 ② URL 拼接归一（/v1 后缀不重复拼）
③ 路由 → 函数端到端（防再次静默失配）。
"""

import httpx
import pytest
from routers import settings as settings_router

from sg_core import llm_config, model_config


class _FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"model": "MiniMax-M3"}
        self.text = "" if status_code == 200 else "boom"

    def json(self):
        return self._payload


def _capture_post(monkeypatch, captured: dict, resp: _FakeResp | None = None):
    """打桩 httpx.post，捕获实际请求 URL/headers/body。"""

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return resp or _FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)


def test_probe_function_exists():
    """T-999b 回归：路由调用的函数名必须存在于 llm_config 模块。"""
    assert callable(getattr(llm_config, "probe_connectivity", None))


def test_probe_url_plain_base(monkeypatch):
    """base_url 不含 /v1：拼出 {base}/v1/chat/completions。"""
    captured: dict = {}
    _capture_post(monkeypatch, captured)

    result = llm_config.probe_connectivity("https://api.minimaxi.com", "k", "MiniMax-M3")

    assert captured["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert result["ok"] is True


def test_probe_url_v1_suffix_not_doubled(monkeypatch):
    """base_url 已含 /v1（官方文档/SDK 风格填法）：不得拼成 /v1/v1/...。"""
    captured: dict = {}
    _capture_post(monkeypatch, captured)

    result = llm_config.probe_connectivity("https://api.minimaxi.com/v1", "k", "MiniMax-M3")

    assert captured["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert result["ok"] is True


def test_probe_url_v1_trailing_slash(monkeypatch):
    """base_url 末尾带斜杠的 /v1 变体同样归一。"""
    captured: dict = {}
    _capture_post(monkeypatch, captured)

    llm_config.probe_connectivity("https://api.minimaxi.com/v1/", "k", "MiniMax-M3")

    assert captured["url"] == "https://api.minimaxi.com/v1/chat/completions"


def test_probe_route_end_to_end(monkeypatch):
    """路由 → llm_config.probe_connectivity 全链路（防函数名再次静默失配）。"""
    monkeypatch.setattr(
        model_config,
        "get_model",
        lambda mid: {"base_url": "https://api.minimaxi.com", "api_key": "db-key", "model": "MiniMax-M3"},
    )
    captured: dict = {}
    _capture_post(monkeypatch, captured)

    body = settings_router.ModelProbeBody(base_url="https://api.minimaxi.com/v1", api_key="form-key", model="MiniMax-M3")
    result = settings_router.probe_model("model-004", body, user=None)

    assert result["ok"] is True
    assert captured["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer form-key"


def test_probe_route_falls_back_to_db_values(monkeypatch):
    """表单缺省时回退 DB 存储值（脱敏 *** key 视为未填）。"""
    monkeypatch.setattr(
        model_config,
        "get_model",
        lambda mid: {"base_url": "https://api.minimaxi.com", "api_key": "db-key", "model": "MiniMax-M3"},
    )
    captured: dict = {}
    _capture_post(monkeypatch, captured)

    body = settings_router.ModelProbeBody(base_url="", api_key="sk-***", model="")
    result = settings_router.probe_model("model-004", body, user=None)

    assert result["ok"] is True
    assert captured["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer db-key"


def test_probe_failure_message(monkeypatch):
    """非 200 诚实回报 HTTP 状态与响应摘要。"""
    _capture_post(monkeypatch, {}, _FakeResp(status_code=401))

    result = llm_config.probe_connectivity("https://api.minimaxi.com", "bad-key", "MiniMax-M3")

    assert result["ok"] is False
    assert "401" in result["message"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
