"""feedback.notify — 飞书通知（webhook 注册表 + 掩码存储 + 仅出站）。

消息只含 ID/结论/链接——不泄露敏感信息。
webhook URL 掩码存储（如 a3f***）。
"""

import fnmatch
import hashlib
import hmac
import ipaddress
import json
import os
import time
import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, quote_plus

import httpx


def validate_webhook_url(url: str) -> str | None:
    """校验 webhook URL（V14 修复：SSRF 限制）。

    - 仅允许 https 协议（飞书 webhook 为 https）
    - 禁止 IP 字面量与 localhost
    - 主机名须命中白名单（环境变量 SG_NOTIFY_ALLOWED_HOSTS，逗号分隔，
      默认 open.feishu.cn,*.feishu.cn）
    返回错误消息；合法时返回 None。
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "URL 解析失败"
    if parsed.scheme != "https":
        return f"仅允许 https 协议: {parsed.scheme or '(无协议)' }"
    host = (parsed.hostname or "").lower()
    if not host:
        return "缺少主机名"
    if host in ("localhost",) or host.endswith(".local"):
        return f"禁止本机地址: {host}"
    try:
        ipaddress.ip_address(host)
        return f"禁止 IP 字面量地址: {host}"
    except ValueError:
        pass  # 非 IP，为主机名，继续白名单校验
    allowed = os.environ.get(
        "SG_NOTIFY_ALLOWED_HOSTS", "open.feishu.cn,*.feishu.cn,oapi.dingtalk.com"
    ).split(",")
    if not any(fnmatch.fnmatch(host, pat.strip().lower()) for pat in allowed if pat.strip()):
        return f"主机名不在白名单（SG_NOTIFY_ALLOWED_HOSTS）: {host}"
    return None


def mask_url(url: str) -> str:
    """掩码 URL（保留协议+域名，路径部分只显示前 4 字符 + ***）。"""
    if "://" in url:
        proto, rest = url.split("://", 1)
        if "/" in rest:
            domain, path = rest.split("/", 1)
            masked = path[:4] + "***" if len(path) > 4 else path + "***"
            return f"{proto}://{domain}/{masked}"
        return f"{proto}://{rest[:4]}***"
    return url[:8] + "***"


class NotifyRegistry:
    """飞书 webhook 注册表。"""

    def __init__(self, registry_path: Path, receipts_path: Path | None = None):
        self.path = registry_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 回执记录文件（D2 修复：各触发点消息送达回执落盘）
        self.receipts_path = receipts_path or (self.path.parent / "receipts.jsonl")
        self._webhooks = self._load()

    def _append_receipt(self, record: dict):
        """追加一条送达回执到 receipts.jsonl。"""
        record = {"timestamp": datetime.now().isoformat(timespec="seconds"), **record}
        with open(self.receipts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._webhooks, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    def register(self, system: str, scenario_pattern: str, url: str,
                 events: list[str] = None) -> dict:
        """注册 webhook。URL 须通过 SSRF 校验（V14），非法时抛 ValueError。"""
        url_err = validate_webhook_url(url)
        if url_err:
            raise ValueError(f"webhook URL 非法: {url_err}")
        entry = {
            "id": f"wh-{len(self._webhooks) + 1:03d}",
            "system": system,
            "scenario_pattern": scenario_pattern,
            "url": url,
            "masked_url": mask_url(url),
            "events": events or ["fail", "drift", "skip"],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._webhooks.append(entry)
        self._save()
        return entry

    def list_webhooks(self) -> list[dict]:
        """列出全部 webhook（显示掩码 URL，不暴露完整 URL）。"""
        return [{k: v for k, v in w.items() if k != "url"} for w in self._webhooks]

    def unregister(self, webhook_id: str) -> bool:
        """注销 webhook。"""
        before = len(self._webhooks)
        self._webhooks = [w for w in self._webhooks if w["id"] != webhook_id]
        if len(self._webhooks) < before:
            self._save()
            return True
        return False

    def find_matches(self, system: str, scenario_id: str, event: str) -> list[dict]:
        """查找匹配的 webhook（系统 + 场景 pattern + 事件类型）。"""
        matches = []
        for wh in self._webhooks:
            if wh["system"] != system:
                continue
            if not fnmatch.fnmatch(scenario_id, wh["scenario_pattern"]):
                continue
            if event not in wh.get("events", []):
                continue
            matches.append(wh)
        return matches

    def send_notification(self, system: str, scenario_id: str, event: str,
                           verdict: str, conclusion: str, report_link: str = "") -> list[dict]:
        """发送通知（仅出站，消息只含 ID/结论/链接）。

        返回每个 webhook 的发送结果。
        """
        matches = self.find_matches(system, scenario_id, event)
        results = []

        message = {
            "scenario_id": scenario_id,
            "event": event,
            "verdict": verdict,
            "conclusion": conclusion[:200],
            "report_link": report_link,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        for wh in matches:
            try:
                resp = httpx.post(wh["url"], json={
                    "msg_type": "text",
                    "content": {"text": json.dumps(message, ensure_ascii=False)},
                }, timeout=10)
                results.append({
                    "webhook_id": wh["id"],
                    "status_code": resp.status_code,
                    "ok": resp.status_code == 200,
                })
            except Exception as e:
                results.append({
                    "webhook_id": wh["id"],
                    "error": str(e),
                    "ok": False,
                })

        # D2 修复：送达回执落盘（含未匹配到 webhook 的情况，便于审计触发点行为）
        self._append_receipt({
            "system": system, "scenario_id": scenario_id, "event": event,
            "verdict": verdict, "matched": len(matches),
            "results": [{"webhook_id": r["webhook_id"], "ok": r["ok"]} for r in results],
        })
        return results


# ════════════════════════════════════════════════════════════
# 钉钉/飞书 webhook 实现（J-2）
# ════════════════════════════════════════════════════════════

# 漏洞合并阈值（超过此数量时合并为一条摘要通知）
VULN_BATCH_THRESHOLD = 3


def _log_notify_failure(config_id: str, event: str, error: str):
    """记录通知失败到 stderr（不抛异常）。"""
    import sys
    print(f"[notify] 发送失败 config={config_id} event={event}: {error}", file=sys.stderr)


async def send_notification(config: dict, event: str, payload: dict) -> bool:
    """按配置发送通知。失败静默记录，不抛异常（通知不能阻塞主流程）。

    Args:
        config: 通知配置（含 channel, webhook_url, secret, mention_mobiles, enabled）
        event: 事件类型（vulnerability / plan_failure / plan_success）
        payload: 事件数据

    Returns:
        True 发送成功，False 发送失败或配置禁用
    """
    if not config.get("enabled", True):
        return False
    try:
        if config["channel"] == "dingtalk":
            return await _send_dingtalk(config, event, payload)
        elif config["channel"] == "feishu":
            return await _send_feishu(config, event, payload)
        else:
            _log_notify_failure(config.get("id", ""), event, f"不支持的渠道: {config.get('channel')}")
            return False
    except Exception as e:
        _log_notify_failure(config.get("id", ""), event, str(e))
        return False


async def _send_dingtalk(config: dict, event: str, payload: dict) -> bool:
    """钉钉自定义机器人（markdown 消息 + 可选加签）。"""
    url = config["webhook_url"]
    # 加签（如果配置了 secret）
    if config.get("secret"):
        ts = str(round(time.time() * 1000))
        sign_str = f"{ts}\n{config['secret']}"
        sign = quote_plus(base64.b64encode(
            hmac.new(config["secret"].encode(), sign_str.encode(),
                     hashlib.sha256).digest()))
        url = f"{url}&timestamp={ts}&sign={sign}"

    md_title, md_text = _render_markdown(event, payload)
    body = {
        "msgtype": "markdown",
        "markdown": {"title": md_title, "text": md_text},
    }
    # @ 人
    if config.get("mention_mobiles"):
        body["at"] = {
            "atMobiles": [m.strip() for m in config["mention_mobiles"].split(",") if m.strip()],
            "isAtAll": False,
        }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=body)
        return resp.status_code == 200 and resp.json().get("errcode") == 0


async def _send_feishu(config: dict, event: str, payload: dict) -> bool:
    """飞书自定义机器人（interactive 卡片）。"""
    card = _render_feishu_card(event, payload)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(config["webhook_url"],
                                 json={"msg_type": "interactive", "card": card})
        return resp.status_code == 200 and resp.json().get("code") == 0


def _render_markdown(event: str, payload: dict) -> tuple[str, str]:
    """渲染钉钉 markdown 消息。返回 (title, text)。"""
    if event == "vulnerability":
        sev = payload.get("severity", "minor")
        sev_icon = {"blocker": "🔴", "major": "🟠", "minor": "🟡"}.get(sev, "🟡")
        title = f"{sev_icon} Spec 漏洞：{payload.get('summary', '')}"
        text = (
            f"### {sev_icon} SpecGuard 发现 Spec 漏洞\n\n"
            f"- **类型**：{payload.get('vtype', '-')}\n"
            f"- **严重度**：{sev}\n"
            f"- **位置**：{payload.get('location', '-')}\n"
            f"- **证据**：{str(payload.get('evidence', '-'))[:200]}\n"
            f"- **建议**：{str(payload.get('suggestion', '-'))[:200]}\n\n"
            f"[查看详情]({payload.get('detail_url', '')})"
        )
        return title, text

    if event == "plan_failure":
        title = f"❌ 定时任务失败：{payload.get('plan_name', '')}"
        text = (
            f"### ❌ SpecGuard 定时任务执行失败\n\n"
            f"- **计划**：{payload.get('plan_name', '-')}\n"
            f"- **失败场景**：{payload.get('scenario_id', '-')}\n"
            f"- **错误**：{str(payload.get('error', '-'))[:300]}\n"
            f"- **时间**：{payload.get('run_at', '-')}\n\n"
            f"[打开调试]({payload.get('debug_url', '')})"
        )
        return title, text

    if event == "plan_success":
        title = f"✅ 定时任务成功：{payload.get('plan_name', '')}"
        text = (
            f"### ✅ SpecGuard 定时任务执行成功\n\n"
            f"- **计划**：{payload.get('plan_name', '-')}\n"
            f"- **场景数**：{payload.get('scenario_count', '-')}\n"
            f"- **时间**：{payload.get('run_at', '-')}\n"
        )
        return title, text

    # 未知事件：通用格式
    title = f"SpecGuard 通知：{event}"
    text = f"### SpecGuard 通知\n\n事件: {event}\n\n```json\n{json.dumps(payload, ensure_ascii=False)[:500]}\n```"
    return title, text


def _render_feishu_card(event: str, payload: dict) -> dict:
    """渲染飞书 interactive 卡片。"""
    if event == "vulnerability":
        sev = payload.get("severity", "minor")
        sev_emoji = {"blocker": "🔴", "major": "🟠", "minor": "🟡"}.get(sev, "🟡")
        return {
            "header": {
                "title": {"tag": "plain_text", "content": f"{sev_emoji} Spec 漏洞：{payload.get('summary', '')}"},
                "template": {"blocker": "red", "major": "orange", "minor": "yellow"}.get(sev, "yellow"),
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**类型**：{payload.get('vtype', '-')}\n**严重度**：{sev}\n**位置**：{payload.get('location', '-')}"}},
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**证据**：{str(payload.get('evidence', '-'))[:200]}"}},
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**建议**：{str(payload.get('suggestion', '-'))[:200]}"}},
                {"tag": "action", "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "查看详情"},
                     "url": payload.get("detail_url", ""), "type": "primary"},
                ]},
            ],
        }

    if event == "plan_failure":
        return {
            "header": {
                "title": {"tag": "plain_text", "content": f"❌ 定时任务失败：{payload.get('plan_name', '')}"},
                "template": "red",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**计划**：{payload.get('plan_name', '-')}\n**失败场景**：{payload.get('scenario_id', '-')}"}},
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**错误**：{str(payload.get('error', '-'))[:300]}"}},
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**时间**：{payload.get('run_at', '-')}"}},
                {"tag": "action", "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "打开调试"},
                     "url": payload.get("debug_url", ""), "type": "danger"},
                ]},
            ],
        }

    if event == "plan_success":
        return {
            "header": {
                "title": {"tag": "plain_text", "content": f"✅ 定时任务成功：{payload.get('plan_name', '')}"},
                "template": "green",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**计划**：{payload.get('plan_name', '-')}\n**场景数**：{payload.get('scenario_count', '-')}\n**时间**：{payload.get('run_at', '-')}"}},
            ],
        }

    # 未知事件
    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"SpecGuard 通知：{event}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md",
             "content": f"事件: {event}\n```json\n{json.dumps(payload, ensure_ascii=False)[:500]}\n```"}},
        ],
    }


async def send_batch_notifications(
    configs: list[dict],
    event: str,
    payloads: list[dict],
) -> list[bool]:
    """批量发送通知（漏洞合并：>3 条合并为一条摘要）。

    Args:
        configs: 通知配置列表
        event: 事件类型
        payloads: 事件数据列表

    Returns:
        每个配置的发送结果
    """
    results = []
    for config in configs:
        if event == "vulnerability" and len(payloads) > VULN_BATCH_THRESHOLD:
            # 合并为一条摘要
            summary_payload = {
                "vtype": "批量",
                "severity": payloads[0].get("severity", "minor"),
                "summary": f"发现 {len(payloads)} 个 Spec 漏洞",
                "location": f"{len(payloads)} 处",
                "evidence": "; ".join(p.get("summary", "") for p in payloads[:5]),
                "suggestion": "请查看详情链接",
                "detail_url": payloads[0].get("detail_url", ""),
            }
            results.append(await send_notification(config, event, summary_payload))
        else:
            # 逐条发送
            for payload in payloads:
                results.append(await send_notification(config, event, payload))
    return results
