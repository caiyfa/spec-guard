"""feedback.notify — 群聊 webhook 通知（钉钉/飞书，仅出站）。

T-996 二合一：webhook 存储统一到 sg_core.notify_config（SQLite 加密存储），
本模块只保留发送/渲染/SSRF 校验/回执；旧 NotifyRegistry（registry.json）由
migrate_registry_to_configs 一次性迁移后归档。

消息只含 ID/结论/链接——不泄露敏感信息。
"""

import fnmatch
import logging
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

logger = logging.getLogger("specguard.notify")

# 送达回执文件（D2：各触发点消息送达回执落盘）
RECEIPTS_PATH = Path(__file__).resolve().parent / "receipts.jsonl"


def _append_receipt(record: dict):
    """追加一条送达回执到 receipts.jsonl。"""
    record = {"timestamp": datetime.now().isoformat(timespec="seconds"), **record}
    RECEIPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RECEIPTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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


# ════════════════════════════════════════════════════════════
# 用例级通知（T-996：NotifyRegistry 收编，存储走 sg_core.notify_config）
# ════════════════════════════════════════════════════════════

# 用例级事件 → 默认展示图标/模板色
_CASE_EVENT_LABEL = {"fail": "❌ 场景失败", "drift": "🟠 场景漂移", "skip": "⏭️ 场景跳过"}


def case_webhook_count() -> int:
    """订阅了任一用例级事件的启用配置数（runner 零成本早退判断用）。"""
    from sg_core import notify_config
    return sum(len(notify_config.get_configs_by_event(e)) for e in _CASE_EVENT_LABEL)


async def notify_case_event(system: str, scenario_id: str, event: str,
                            verdict: str, conclusion: str, report_link: str = "") -> list[dict]:
    """用例级通知：按 system + scenario_pattern(fnmatch) + event 过滤已启用配置并发送。

    返回每个配置的发送结果；送达回执落盘（含零匹配，便于审计触发点行为）。
    """
    from sg_core import notify_config
    matched = []
    for cfg in notify_config.get_configs_by_event(event):
        if cfg.get("system") and cfg["system"] != system:
            continue
        if not fnmatch.fnmatch(scenario_id, cfg.get("scenario_pattern") or "*"):
            continue
        matched.append(cfg)
    payload = {
        "system": system,
        "scenario_id": scenario_id,
        "event": event,
        "verdict": verdict,
        "conclusion": conclusion[:200],
        "report_link": report_link,
    }
    results = []
    for cfg in matched:
        ok = await send_notification(cfg, event, payload)
        results.append({"webhook_id": cfg["id"], "ok": ok})
    _append_receipt({
        "system": system, "scenario_id": scenario_id, "event": event,
        "verdict": verdict, "matched": len(matched),
        "results": results,
    })
    return results


def migrate_registry_to_configs(sg_root: Path) -> int:
    """旧 NotifyRegistry（feedback/registry.json）一次性迁移进 notify_configs。

    幂等：迁移后 registry.json 改名 .migrated，再次调用无文件直接返回 0。
    非法 URL（SSRF 校验不过）跳过并记录回执。返回迁移条数。
    """
    registry_path = sg_root / "feedback" / "registry.json"
    if not registry_path.is_file():
        return 0
    from sg_core import notify_config
    with open(registry_path, "r", encoding="utf-8") as f:
        webhooks = json.load(f)
    migrated = 0
    for wh in webhooks:
        url = wh.get("url", "")
        err = validate_webhook_url(url)
        if err:
            _append_receipt({"system": wh.get("system", ""), "scenario_id": "",
                             "event": "migrate_skip", "verdict": "",
                             "matched": 0, "results": [],
                             "note": f"registry {wh.get('id')} URL 非法跳过: {err}"})
            continue
        notify_config.create_config({
            "name": f"{wh.get('system', '')}/{wh.get('scenario_pattern', '*')}（registry 迁移）",
            "channel": "feishu",
            "webhook_url": url,
            "events": wh.get("events") or ["fail", "drift", "skip"],
            "enabled": True,
            "system": wh.get("system", ""),
            "scenario_pattern": wh.get("scenario_pattern") or "*",
        }, created_by="t996-migrate")
        migrated += 1
    registry_path.rename(registry_path.with_suffix(".json.migrated"))
    return migrated


# ════════════════════════════════════════════════════════════
# 钉钉/飞书 webhook 实现（J-2）
# ════════════════════════════════════════════════════════════

# 漏洞合并阈值（超过此数量时合并为一条摘要通知）
VULN_BATCH_THRESHOLD = 3


def _log_notify_failure(config_id: str, event: str, error: str):
    """记录通知失败（不抛异常）。"""
    logger.warning("发送失败 config=%s event=%s: %s", config_id, event, error)


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

    if event in _CASE_EVENT_LABEL:
        label = _CASE_EVENT_LABEL[event]
        title = f"{label}：{payload.get('scenario_id', '')}"
        text = (
            f"### {label}\n\n"
            f"- **系统**：{payload.get('system', '-')}\n"
            f"- **场景**：{payload.get('scenario_id', '-')}\n"
            f"- **判定**：{payload.get('verdict', '-')}\n"
            f"- **结论**：{str(payload.get('conclusion', '-'))[:200]}\n\n"
            f"[查看报告]({payload.get('report_link', '')})"
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

    if event in _CASE_EVENT_LABEL:
        label = _CASE_EVENT_LABEL[event]
        return {
            "header": {
                "title": {"tag": "plain_text", "content": f"{label}：{payload.get('scenario_id', '')}"},
                "template": {"fail": "red", "drift": "orange", "skip": "grey"}.get(event, "blue"),
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**系统**：{payload.get('system', '-')}\n**场景**：{payload.get('scenario_id', '-')}\n**判定**：{payload.get('verdict', '-')}"}},
                {"tag": "div", "text": {"tag": "lark_md",
                 "content": f"**结论**：{str(payload.get('conclusion', '-'))[:200]}"}},
                {"tag": "action", "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "查看报告"},
                     "url": payload.get("report_link", ""), "type": "primary"},
                ]},
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
