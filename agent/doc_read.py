"""doc_read 事件构建器（S0.5 · T-511 依据透明 · 阅读足迹）。

runtime 在「读型文档工具」调用完成后调用 build_doc_read()，产出 WS 事件
doc_read 的 payload（path/tool/turn/摘要/大小/hunks/意义标注），前端 📖 阅读
页签据此汇聚「agent 读过哪些文档的哪些章节」。

边界纪律（《知识体系设计》§4.5）：
- 只覆盖 READ_DOC_TOOLS 五个读型文档工具；写型/查询型工具不上足迹。
- excerpt 预算宁少勿多（≤_EXCERPT_MAX_CHARS，远小于 T-403 的 50000 口径）。
- 错误结果不产生足迹（工具失败不是「阅读依据」）。
- 纯函数零 I/O：路径是否真实可读由前端打开时校验（read-file 失败前端回退
  memo 页签展示 excerpt）。
"""

from __future__ import annotations

import json
import os
import re

# 设计 §4.5 边界纪律：只对这五个读型文档工具上足迹
READ_DOC_TOOLS = frozenset({
    "read_spec",
    "read_scenario",
    "read_run_report",
    "read_run_log",
    "read_info_pack",
})

_EXCERPT_MAX_CHARS = 2000

# 工具失败结果的统一前缀（runtime/MCP 各 handler 约定俗成）
_ERROR_PREFIXES = ("错误：", "工具执行异常", "未知工具", "OUT_OF_SCOPE")

# T-512 章节提取标头（spec_reader/scenario_tools 章节分支首行，真实文件行区间）
_SECTION_HEADER_RE = re.compile(r"^--- .+ · (.+) · 行(\d+)-(\d+) ---$")


def _is_error_result(result: str) -> bool:
    text = result.lstrip()
    if text.startswith(_ERROR_PREFIXES):
        return True
    # JSON 形态失败（read_run_log/read_run_report 的 {"ok": false, ...}）
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return False
        if isinstance(payload, dict) and payload.get("ok") is False:
            return True
    return False


def _excerpt_of(result: str) -> str:
    return result[:_EXCERPT_MAX_CHARS]


def _note(tool: str, arguments: dict) -> str:
    """意义标注的结构化来源①：工具名+关键参数，如 read_spec(anchor=FR-009)。"""
    keys = ("path", "anchor", "section", "id", "part", "run_id", "tail", "scenario_id")
    parts = [f"{k}={arguments[k]}" for k in keys if arguments.get(k) not in (None, "")]
    return f"{tool}({', '.join(parts)})" if parts else f"{tool}()"


def _head_hunk(title: str, excerpt: str, note: str) -> dict:
    """V1 默认单 hunk：全文/头部摘录（行区间 = 摘录覆盖的头部行）。"""
    return {
        "title": title,
        "start": 1,
        "end": max(1, excerpt.count("\n") + 1),
        "note": note,
    }


def _section_hunk(result: str, note: str) -> dict | None:
    """T-512：工具章节分支首行标头（--- path · title · 行N-M ---）→ 真实行区间 hunk。"""
    first = result.split("\n", 1)[0]
    m = _SECTION_HEADER_RE.match(first)
    if not m:
        return None
    return {"title": m.group(1), "start": int(m.group(2)), "end": int(m.group(3)),
            "note": note}


def build_doc_read(tool: str, arguments: dict, result: str,
                   turn: int, thinking: str = "") -> dict | None:
    """构建 doc_read 事件 payload；工具不上足迹或结果失败时返回 None。

    返回字段：
      tool/ref/turn — 工具名、原始定位参数、轮次
      path          — 可经 read-file 打开的工作区相对路径；打不开则为 None
                      （前端回退 memo 内容页签展示 excerpt）
      size/excerpt  — 结果大小与头部摘录
      label         — 意义标注①：工具名+关键参数的人类可读映射
      thinking      — 意义标注②：本轮 K-024 思考文本（runtime 捎带）
      hunks         — 使用位置列表（V1 单 hunk；T-512 章节参数接入后多 hunk）
    """
    if tool not in READ_DOC_TOOLS or _is_error_result(result):
        return None

    args = arguments or {}
    excerpt = _excerpt_of(result)
    note = _note(tool, args)
    path = None
    hunks: list[dict] = []

    if tool == "read_spec":
        ref = str(args.get("path", "") or "")
        anchor = str(args.get("anchor", "") or "")
        section = str(args.get("section", "") or "")
        if ref.startswith("sg://"):
            path = None  # 仓库根路径 read-file 不可达，前端走 memo 兜底
        else:
            path = ref or None
        if anchor:
            label = f"引用需求条目 {anchor}"
        elif section:
            label = f"定位章节 {section}"
        else:
            label = f"查阅 {os.path.basename(ref)}" if ref else "查阅 spec"
        # T-512：章节分支标头 → 真实行区间 hunk；全文读取 → V1 头部 hunk
        hunks = [_section_hunk(result, note) or _head_hunk("全文（头部摘录）", excerpt, note)]

    elif tool == "read_scenario":
        ref = str(args.get("id", "") or "")
        part = str(args.get("part", "") or "")
        label = f"查看场景 {ref}" + (f"（{part} 段）" if part else "")
        path = None  # scenarios/ 在仓库根，read-file 只覆盖工作区根
        hunks = [_section_hunk(result, note) or _head_hunk("场景 YAML（头部摘录）", excerpt, note)]

    elif tool == "read_run_report":
        ref = str(args.get("run_id", "") or "")
        label = f"查看执行报告 {ref}"
        # 工具返回是聚合 JSON（非 run.json 原文），行区间无法映射真实文件 →
        # 一律 memo 展示；有失败场景时摘录优先给「失败断言段」（设计 §4.5：报告类展示失败断言段）
        path = None
        failed = None
        try:
            payload = json.loads(result)
            if isinstance(payload, dict) and payload.get("failed_cases"):
                failed = payload["failed_cases"]
        except (ValueError, TypeError):
            pass
        if failed:
            excerpt = ("失败断言段：\n" + json.dumps(
                failed, ensure_ascii=False, indent=2))[:_EXCERPT_MAX_CHARS]
            hunks = [_head_hunk(f"失败断言段（{len(failed)} 场景）", excerpt, note)]
        else:
            hunks = [_head_hunk("报告摘要", excerpt, note)]

    elif tool == "read_run_log":
        ref = str(args.get("run_id", "") or "")
        label = f"查看执行日志 {ref}"
        path = f".specguard/reports/{ref}/output.log" if ref else None
        # tail 区间：结果 JSON 带 total_lines/returned_lines，可确定性换算行号
        try:
            payload = json.loads(result)
            total = int(payload.get("total_lines", 0))
            returned = int(payload.get("returned_lines", 0))
        except (ValueError, TypeError):
            total = returned = 0
        if total > 0 and returned > 0:
            hunks = [{
                "title": f"尾部 {returned} 行",
                "start": max(1, total - returned + 1),
                "end": total,
                "note": note,
            }]
        else:
            hunks = [_head_hunk("日志摘录", excerpt, note)]

    elif tool == "read_info_pack":
        ref = str(args.get("scenario_id", "") or "")
        label = f"查阅信息包 {ref}"
        path = None  # 多文件拼接文本，无单一可开路径
        hunks = [_head_hunk("信息包拼接（头部摘录）", excerpt, note)]

    else:  # pragma: no cover - READ_DOC_TOOLS 守卫已拦截
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
        "hunks": hunks,
    }
