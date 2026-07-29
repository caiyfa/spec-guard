"""audit — Spec 审计工具（H-1）。

工具：
  write_audit_report: 写入 Spec 审计报告到 .specguard/audit/ 目录
  report_vulnerability: 登记漏洞到反馈台账（SPQ ledger）+ 触发群聊通知
"""

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

# Backend services 路径（notify_config 等）
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 台账文件路径（T-2 切换点：未来迁移到 .specguard/ledger.json）
LEDGER_PATH = SG_ROOT / "feedback" / "ledger.json"

# 文件名安全字符：允许字母数字下划线连字符和中日韩文字
_SAFE_CHAR_RE = re.compile(r"[^A-Za-z0-9_\-\u4e00-\u9fff]")


def _sanitize_filename(text: str, max_len: int = 60) -> str:
    """将标题转为安全文件名（保留中文，替换特殊字符为下划线）。"""
    safe = _SAFE_CHAR_RE.sub("_", text).strip("_")
    if not safe:
        safe = "audit_report"
    return safe[:max_len]


TOOLS = [
    Tool(
        name="write_audit_report",
        description="写入 Spec 审计报告到工作区 .specguard/audit/ 目录。"
                    "审计完成后调用此工具输出完整报告（Markdown 格式）。",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "报告标题"},
                "content": {"type": "string", "description": "报告正文（Markdown）"},
                "vulnerability_count": {"type": "integer", "description": "发现的漏洞数量"},
            },
            "required": ["title", "content"],
        },
    ),
    Tool(
        name="report_vulnerability",
        description="登记一条漏洞到反馈台账（SPQ ledger），并触发群聊通知。"
                    "每发现一条漏洞时调用此工具。",
        inputSchema={
            "type": "object",
            "properties": {
                "vtype": {
                    "type": "string",
                    "enum": ["logic_defect", "spec_impl_mismatch", "missing_info", "behavior_deviation"],
                    "description": "漏洞类型",
                },
                "severity": {
                    "type": "string",
                    "enum": ["blocker", "major", "minor"],
                    "description": "严重度",
                },
                "location": {"type": "string", "description": "FR ID 或文件路径"},
                "evidence": {"type": "string", "description": "证据（spec 原文 / 接口返回）"},
                "suggestion": {"type": "string", "description": "建议修正"},
                "summary": {"type": "string", "description": "一句话描述"},
            },
            "required": ["vtype", "severity", "location", "summary"],
        },
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_audit_report":
        return _handle_write_audit_report(arguments)
    elif name == "report_vulnerability":
        return await _handle_report_vulnerability(arguments)
    return []


# ══════════════════════════════════════════════════════════
# write_audit_report
# ══════════════════════════════════════════════════════════

def _handle_write_audit_report(arguments: dict) -> list[TextContent]:
    """写入审计报告到 .specguard/audit/ 目录。"""
    title = arguments.get("title", "").strip()
    content = arguments.get("content", "")
    vuln_count = arguments.get("vulnerability_count", 0)

    if not title:
        return [TextContent(type="text", text="错误：缺少 title 参数")]
    if not content:
        return [TextContent(type="text", text="错误：缺少 content 参数")]

    # 获取审计报告目录（F-1-1 specguard_dir，已 ✅ 用真实路径）
    try:
        from specstd.workspace import specguard_dir
        audit_dir = specguard_dir() / "audit"
    except RuntimeError:
        return [TextContent(type="text", text="错误：无激活工作区，请先激活工作区再写审计报告")]
    except Exception as e:
        return [TextContent(type="text", text=f"错误：获取工作区目录失败: {e}")]

    audit_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名：{timestamp}_{sanitized_title}.md
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = _sanitize_filename(title)
    filename = f"{timestamp}_{safe_title}.md"
    report_path = audit_dir / filename

    # 构建完整报告内容
    header = (
        f"# {title}\n\n"
        f"> 审计时间：{datetime.now().isoformat(timespec='seconds')}\n"
        f"> 漏洞数量：{vuln_count}\n\n"
        f"---\n\n"
    )
    full_content = header + content

    try:
        report_path.write_text(full_content, encoding="utf-8")
    except Exception as e:
        return [TextContent(type="text", text=f"错误：写入报告失败: {e}")]

    # K-007: 若开启「审计完成自动更新基线」，审计报告成功后更新 spec 签名基线
    baseline_updated = False
    try:
        from services import settings_store, spec_baseline
        if settings_store.audit_auto_update_baseline():
            baseline_updated = spec_baseline.update_baseline()
    except Exception:
        pass  # 基线更新失败不阻塞审计报告

    return [TextContent(type="text", text=json.dumps({
        "ok": True,
        "path": str(report_path),
        "filename": filename,
        "vulnerability_count": vuln_count,
        "baseline_updated": baseline_updated,
    }, ensure_ascii=False, indent=2))]


# ══════════════════════════════════════════════════════════
# report_vulnerability
# ══════════════════════════════════════════════════════════

async def _handle_report_vulnerability(arguments: dict) -> list[TextContent]:
    """登记漏洞到台账 + 触发通知（best-effort）。"""
    vtype = arguments.get("vtype", "")
    severity = arguments.get("severity", "")
    location = arguments.get("location", "")
    summary = arguments.get("summary", "")
    evidence = arguments.get("evidence", "")
    suggestion = arguments.get("suggestion", "")

    # 参数校验
    if not vtype:
        return [TextContent(type="text", text="错误：缺少 vtype 参数")]
    if not severity:
        return [TextContent(type="text", text="错误：缺少 severity 参数")]
    if not location:
        return [TextContent(type="text", text="错误：缺少 location 参数")]
    if not summary:
        return [TextContent(type="text", text="错误：缺少 summary 参数")]

    # 写入台账
    try:
        from feedback.ledger import FeedbackLedger
        ledger = FeedbackLedger(LEDGER_PATH)
        entry = ledger.create_vulnerability(
            vtype=vtype,
            severity=severity,
            location=location,
            summary=summary,
            evidence=evidence,
            suggestion=suggestion,
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"错误：参数校验失败: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"错误：写入台账失败: {e}")]

    spq_id = entry["spq_id"]

    # 触发通知（best-effort，失败不阻塞台账记录）
    # J-2 已 ✅，使用真实 send_notification
    notify_status = "skipped"
    notify_error = ""
    try:
        from feedback.notify import send_batch_notifications
        from services.notify_config import get_configs_by_event

        configs = get_configs_by_event("vulnerability")
        if configs:
            payload = {
                "spq_id": spq_id,
                "vtype": vtype,
                "severity": severity,
                "location": location,
                "summary": summary,
                "evidence": evidence[:200] if evidence else "",
                "suggestion": suggestion[:200] if suggestion else "",
                "detail_url": f"/feedback?highlight={spq_id}",
            }
            results = await send_batch_notifications(configs, "vulnerability", [payload])
            if all(results):
                notify_status = "sent"
            elif any(results):
                notify_status = "partial"
            else:
                notify_status = "failed"
                notify_error = "全部通知发送失败"
        else:
            notify_status = "no_config"
    except Exception as e:
        # 通知失败不影响台账记录
        notify_status = "error"
        notify_error = str(e)

    result = {
        "ok": True,
        "spq_id": spq_id,
        "status": "pending",
        "notification": notify_status,
    }
    if notify_error:
        result["notify_error"] = notify_error

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
