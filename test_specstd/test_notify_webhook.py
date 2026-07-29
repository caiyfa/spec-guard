"""J-2 钉钉/飞书 webhook 测试。

覆盖验收标准：
1. 消息渲染（钉钉 markdown + 飞书卡片，两类事件）
2. 钉钉加签可用
3. webhook 填错不阻塞主流程（失败静默）
4. >3 条漏洞合并一条
5. 钉钉域名通过 SSRF 校验

全部离线：mock httpx.AsyncClient，不触真实 webhook。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from feedback.notify import (
    send_notification,
    send_batch_notifications,
    _render_markdown,
    _render_feishu_card,
    _send_dingtalk,
    _send_feishu,
    validate_webhook_url,
    VULN_BATCH_THRESHOLD,
)


# ══════════════════════════════════════════════════════════
# 验收 1: 消息渲染 — 钉钉 markdown
# ══════════════════════════════════════════════════════════

class TestRenderMarkdown:
    """钉钉 markdown 消息渲染。"""

    def test_vulnerability(self):
        title, text = _render_markdown("vulnerability", {
            "vtype": "MISSING_COVERS",
            "severity": "blocker",
            "summary": "缺少 covers 标签",
            "location": "specs/module1/spec.md",
            "evidence": "场景未关联 FR",
            "suggestion": "添加 covers",
            "detail_url": "http://example.com/detail",
        })
        assert "🔴" in title
        assert "漏洞" in title
        assert "blocker" in text
        assert "MISSING_COVERS" in text
        assert "查看详情" in text

    def test_vulnerability_severity_icons(self):
        for sev, icon in [("blocker", "🔴"), ("major", "🟠"), ("minor", "🟡")]:
            title, _ = _render_markdown("vulnerability", {"severity": sev, "summary": "test"})
            assert icon in title

    def test_plan_failure(self):
        title, text = _render_markdown("plan_failure", {
            "plan_name": "回归计划",
            "scenario_id": "PP-RC-005",
            "error": "断言失败",
            "run_at": "2026-07-29T10:00:00",
            "debug_url": "http://example.com/debug",
        })
        assert "❌" in title
        assert "回归计划" in title
        assert "PP-RC-005" in text
        assert "打开调试" in text

    def test_plan_success(self):
        title, text = _render_markdown("plan_success", {
            "plan_name": "回归计划",
            "scenario_count": 10,
            "run_at": "2026-07-29T10:00:00",
        })
        assert "✅" in title
        assert "10" in text

    def test_unknown_event(self):
        title, text = _render_markdown("custom_event", {"key": "value"})
        assert "custom_event" in title
        assert "value" in text


# ══════════════════════════════════════════════════════════
# 验收 1: 消息渲染 — 飞书卡片
# ══════════════════════════════════════════════════════════

class TestRenderFeishuCard:
    """飞书 interactive 卡片渲染。"""

    def test_vulnerability(self):
        card = _render_feishu_card("vulnerability", {
            "vtype": "MISSING_COVERS",
            "severity": "major",
            "summary": "缺少 covers",
            "location": "spec.md",
            "evidence": "evidence",
            "suggestion": "fix it",
            "detail_url": "http://example.com",
        })
        assert "header" in card
        assert "elements" in card
        assert card["header"]["template"] == "orange"
        assert any("查看详情" in str(e) for e in card["elements"])

    def test_plan_failure(self):
        card = _render_feishu_card("plan_failure", {
            "plan_name": "test",
            "scenario_id": "SC-001",
            "error": "error msg",
            "run_at": "2026-07-29",
            "debug_url": "http://example.com",
        })
        assert card["header"]["template"] == "red"
        assert any("打开调试" in str(e) for e in card["elements"])

    def test_plan_success(self):
        card = _render_feishu_card("plan_success", {
            "plan_name": "test",
            "scenario_count": 5,
            "run_at": "2026-07-29",
        })
        assert card["header"]["template"] == "green"


# ══════════════════════════════════════════════════════════
# 验收 3: webhook 填错不阻塞主流程（失败静默）
# ══════════════════════════════════════════════════════════

class TestFailureSilence:
    """通知失败不抛异常。"""

    def test_disabled_config(self):
        """禁用的配置 → 返回 False，不发请求。"""
        config = {"enabled": False, "channel": "feishu", "webhook_url": "https://x"}
        result = asyncio.run(send_notification(config, "vulnerability", {}))
        assert result is False

    def test_invalid_channel(self):
        """不支持的渠道 → 返回 False。"""
        config = {"enabled": True, "channel": "slack", "webhook_url": "https://x", "id": "c1"}
        result = asyncio.run(send_notification(config, "vulnerability", {}))
        assert result is False

    def test_network_error_silent(self):
        """网络错误 → 返回 False，不抛异常。"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Network error"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            config = {"enabled": True, "channel": "feishu", "webhook_url": "https://x", "id": "c1"}
            result = asyncio.run(send_notification(config, "vulnerability", {}))
            assert result is False

    def test_bad_webhook_url(self):
        """webhook URL 填错 → 返回 False，不抛异常。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"errcode": 1}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("httpx.AsyncClient", return_value=mock_client):
            config = {"enabled": True, "channel": "feishu", "webhook_url": "https://bad.url", "id": "c1"}
            result = asyncio.run(send_notification(config, "vulnerability", {}))
            assert result is False


# ══════════════════════════════════════════════════════════
# 验收 2: 钉钉加签
# ══════════════════════════════════════════════════════════

class TestDingtalkSigning:
    """钉钉加签逻辑。"""

    def test_signing_adds_params(self):
        """配置了 secret 时，URL 添加 timestamp 和 sign 参数。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errcode": 0}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = {
            "enabled": True,
            "channel": "dingtalk",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
            "secret": "SEC123",
            "id": "c1",
        }
        with patch("httpx.AsyncClient", return_value=mock_client):
            asyncio.run(_send_dingtalk(config, "vulnerability", {"severity": "minor", "summary": "test"}))

        # 验证 post 被调用，且 URL 包含 timestamp 和 sign
        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "timestamp=" in url
        assert "sign=" in url

    def test_no_secret_no_signing(self):
        """未配置 secret 时，URL 不变。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errcode": 0}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        original_url = "https://oapi.dingtalk.com/robot/send?access_token=xxx"
        config = {
            "enabled": True,
            "channel": "dingtalk",
            "webhook_url": original_url,
            "secret": "",
            "id": "c1",
        }
        with patch("httpx.AsyncClient", return_value=mock_client):
            asyncio.run(_send_dingtalk(config, "vulnerability", {"severity": "minor", "summary": "test"}))

        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert url == original_url  # 无加签参数


# ══════════════════════════════════════════════════════════
# 验收 4: >3 条漏洞合并一条
# ══════════════════════════════════════════════════════════

class TestBatchMerge:
    """批量通知合并逻辑。"""

    def test_above_threshold_merged(self):
        """>3 条漏洞 → 合并为一条摘要。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 0, "errcode": 0}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        configs = [{"enabled": True, "channel": "feishu", "webhook_url": "https://x", "id": "c1"}]
        payloads = [{"severity": "minor", "summary": f"漏洞{i}"} for i in range(5)]

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(send_batch_notifications(configs, "vulnerability", payloads))

        # 只发一条（合并），返回一个 True
        assert len(results) == 1
        assert results[0] is True
        # post 只被调用一次
        assert mock_client.post.call_count == 1

    def test_below_threshold_individual(self):
        """<=3 条漏洞 → 逐条发送。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errcode": 0}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        configs = [{"enabled": True, "channel": "feishu", "webhook_url": "https://x", "id": "c1"}]
        payloads = [{"severity": "minor", "summary": f"漏洞{i}"} for i in range(3)]

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(send_batch_notifications(configs, "vulnerability", payloads))

        # 3 条逐条发送
        assert len(results) == 3
        assert mock_client.post.call_count == 3

    def test_non_vulnerability_not_merged(self):
        """非漏洞事件不合并（即使 >3 条）。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errcode": 0}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        configs = [{"enabled": True, "channel": "feishu", "webhook_url": "https://x", "id": "c1"}]
        payloads = [{"plan_name": f"计划{i}"} for i in range(5)]

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(send_batch_notifications(configs, "plan_failure", payloads))

        assert len(results) == 5
        assert mock_client.post.call_count == 5


# ══════════════════════════════════════════════════════════
# 验收 5: SSRF 校验支持钉钉域名
# ══════════════════════════════════════════════════════════

class TestWebhookValidation:
    """webhook URL SSRF 校验支持钉钉域名。"""

    def test_dingtalk_accepted(self):
        assert validate_webhook_url("https://oapi.dingtalk.com/robot/send?access_token=xxx") is None

    def test_feishu_accepted(self):
        assert validate_webhook_url("https://open.feishu.cn/open-apis/bot/v2/hook/xxx") is None

    def test_random_domain_rejected(self):
        assert validate_webhook_url("https://evil.example.com/hook") is not None

    def test_http_rejected(self):
        assert validate_webhook_url("http://oapi.dingtalk.com/robot/send") is not None

    def test_ip_rejected(self):
        assert validate_webhook_url("https://192.168.1.1/hook") is not None
