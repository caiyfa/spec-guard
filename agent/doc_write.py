"""doc_write 事件构建器（S0.6 · 更新足迹）。

runtime 在「写型文档工具」调用成功后调用 build_doc_write()，产出 WS 事件
doc_write 的 payload（tool/ref/path/turn/摘要/verdict/意义标注），前端
「📝 更新与产物」页签据此汇聚「agent 更新了哪些文档的哪些内容」。

边界纪律（对齐 doc_read 设计 §4.5）：
- 只覆盖 WRITE_TOOLS 写型工具；读型/查询型工具不上更新足迹。
- 失败结果不产生足迹（写失败不是「更新依据」）。
- 纯函数零 I/O：path/verdict 均从工具返回 JSON 解析（写型工具结果自带
  path/validation/backup/gate 等确定性字段），不做文件系统探测。
- excerpt 预算宁少勿多（≤_EXCERPT_MAX_CHARS，对齐 doc_read 口径）。
"""

from __future__ import annotations

import json

from agent.doc_read import _EXCERPT_MAX_CHARS, _is_error_result


# 写型工具足迹 hunk note 的关键参数键（doc_read 的 _note 键集面向读型工具，不共用）
_WRITE_NOTE_KEYS = ("filename", "delta_id", "scenario_id", "module", "path")


def _write_note(tool: str, args: dict) -> str:
    parts = [f"{k}={args[k]}" for k in _WRITE_NOTE_KEYS if args.get(k) not in (None, "")]
    return f"{tool}({', '.join(parts)})" if parts else f"{tool}()"


# 写型工具清单（产物更新足迹覆盖面：草稿/delta 起草区/信息包/入库/回滚）
WRITE_TOOLS = frozenset({
    "write_draft",
    "write_delta_doc",
    "commit_delta_changes",
    "add_to_info_pack",
    "promote_draft",
    "promote_drafts",
    "undo_draft",
})

# 校验失败原因提取上限与单条 message 截断（事件体积控制，防 WS 载荷膨胀）
_FINDINGS_MAX = 20
_FINDING_MSG_MAX = 200


def _parse_result_json(result: str) -> dict:
    """解析工具返回 JSON（写型工具统一 JSON 形态）；非 JSON 返回空 dict。"""
    try:
        payload = json.loads(result)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _excerpt_of_content(arguments: dict, result: str) -> str:
    """更新足迹摘要优先取「写入内容」头部（更新了什么的最直接证据）；
    无 content 的工具（commit/入库等）回退结果文本头部。"""
    content = arguments.get("content")
    if isinstance(content, str) and content:
        return content[:_EXCERPT_MAX_CHARS]
    return result[:_EXCERPT_MAX_CHARS]


def _gate_verdict(payload: dict) -> str | None:
    """promote 发布门禁 verdict：skipped → SKIP；ok → PASS；失败 → REJECT。"""
    gate = payload.get("gate")
    if not isinstance(gate, dict):
        return None
    if gate.get("skipped"):
        return "SKIP"
    return "PASS" if gate.get("ok") else "REJECT"


def _extract_findings(payload: dict) -> list[dict]:
    """从校验结果提取失败原因（write_delta_doc validation.findings）。

    失败原因与 verdict 同源（工具返回 JSON），纯解析零 I/O；
    PASS/SKIP 或无 findings 时为空列表。message 截断防事件膨胀。
    """
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        return []
    findings = validation.get("findings") or []
    out = []
    for f in findings[: _FINDINGS_MAX]:
        if not isinstance(f, dict):
            continue
        level = str(f.get("level", "") or "")
        rule = str(f.get("rule", "") or "")
        message = str(f.get("message", "") or "")
        if not (level or rule or message):
            continue
        out.append({"level": level, "rule": rule, "message": message[: _FINDING_MSG_MAX]})
    return out


def _write_hunk(title: str, excerpt: str, note: str) -> dict:
    """写入足迹默认单 hunk：写入内容头部行区间（打开文件时定位更新区）。"""
    return {
        "title": title,
        "start": 1,
        "end": max(1, excerpt.count("\n") + 1),
        "note": note,
    }


def _map_tool(tool: str, args: dict, payload: dict,
              excerpt: str, note: str) -> tuple:
    """分工具映射 (ref, path, label, verdict, hunks)；未知工具返回 (None, ...)。"""
    if tool == "write_draft":
        filename = str(args.get("filename", "") or "")
        action = payload.get("action", "create")
        label = f"写入草稿 {filename}" if action == "create" else f"追加草稿 {filename}（patch）"
        return (filename, payload.get("path"), label, None,
                [_write_hunk("写入内容（头部摘录）", excerpt, note)])

    if tool == "write_delta_doc":
        delta_id = str(args.get("delta_id", "") or "")
        filename = str(args.get("filename", "") or "")
        validation = payload.get("validation")
        verdict = validation.get("verdict") if isinstance(validation, dict) else None
        label = f"更新 {filename}（delta {delta_id}）"
        return (f"{delta_id}/{filename}", payload.get("path"), label, verdict,
                [_write_hunk("写入内容（头部摘录）", excerpt, note)])

    if tool == "commit_delta_changes":
        delta_id = str(args.get("delta_id", "") or "")
        files = payload.get("files") or []
        label = f"提交 delta {delta_id} 变更" + (f"（{len(files)} 文件）" if files else "")
        return (delta_id, None, label, "PASS" if payload.get("ok") else None,
                [_write_hunk("提交摘要", excerpt, note)])

    if tool == "add_to_info_pack":
        scenario_id = str(args.get("scenario_id", "") or "")
        added = str(payload.get("added_file", "") or "")
        label = f"信息包补充 {added}" + (f"（{scenario_id}）" if scenario_id else "")
        return (scenario_id, None, label, None,
                [_write_hunk("信息包变更摘要", excerpt, note)])

    if tool == "promote_draft":
        filename = str(args.get("filename", "") or "")
        target = str(payload.get("target", "") or "")
        label = f"入库草稿 {filename}" + (f" → {target}" if target else "")
        return (filename, payload.get("target"), label, _gate_verdict(payload),
                [_write_hunk("入库摘要", excerpt, note)])

    if tool == "promote_drafts":
        promoted = payload.get("promoted") or []
        label = f"批量入库 {len(promoted)} 份草稿"
        return ("batch", None, label, _gate_verdict(payload),
                [_write_hunk("批量入库摘要", excerpt, note)])

    if tool == "undo_draft":
        filename = str(args.get("filename", "") or "")
        label = f"撤销草稿 {filename}（.bak 恢复）"
        return (filename, payload.get("path"), label, None,
                [_write_hunk("撤销后内容（头部摘录）", excerpt, note)])

    return (None, None, "", None, [])  # pragma: no cover - WRITE_TOOLS 守卫已拦截


def build_doc_write(tool: str, arguments: dict, result: str,
                    turn: int, thinking: str = "") -> dict | None:
    """构建 doc_write 事件 payload；工具不上足迹或结果失败时返回 None。

    返回字段：
      tool/ref/turn — 工具名、原始定位参数、轮次
      path          — 可经 read-file 打开的工作区相对路径；打不开则为 None
                      （前端回退 memo 内容页签展示 excerpt）
      size/excerpt  — 结果大小与写入内容头部摘录
      label         — 意义标注①：工具名+关键参数的人类可读映射
      thinking      — 意义标注②：本轮 K-024 思考文本（runtime 捎带）
      verdict       — 确定性校验结果（write_delta_doc conformance /
                      promote 发布门禁）：PASS/REJECT/SKIP/ERROR，无则 None
      findings      — 校验失败原因列表（[{level, rule, message}]，与 verdict 同源；
                      PASS/SKIP 时为空——Agent 据此定位修复）
      hunks         — 更新位置列表（V1 单 hunk：写入内容头部行区间）
    """
    if tool not in WRITE_TOOLS or _is_error_result(result):
        return None

    args = arguments or {}
    payload = _parse_result_json(result)
    excerpt = _excerpt_of_content(args, result)
    note = _write_note(tool, args)
    ref, path, label, verdict, hunks = _map_tool(tool, args, payload, excerpt, note)
    if ref is None:  # pragma: no cover
        return None

    return {
        "tool": tool,
        "ref": ref,
        "path": path,
        "turn": turn,
        "size": len(result),
        "excerpt": excerpt,
        "label": label,
        "thinking": (thinking or "").strip(),
        "verdict": verdict,
        "findings": _extract_findings(payload),
        "hunks": hunks,
    }
