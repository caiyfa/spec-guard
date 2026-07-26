"""feedback.notify — 飞书通知（webhook 注册表 + 掩码存储 + 仅出站）。

消息只含 ID/结论/链接——不泄露敏感信息。
webhook URL 掩码存储（如 a3f***）。
"""

import fnmatch
import ipaddress
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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
        "SG_NOTIFY_ALLOWED_HOSTS", "open.feishu.cn,*.feishu.cn"
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

    def list(self) -> list[dict]:
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
