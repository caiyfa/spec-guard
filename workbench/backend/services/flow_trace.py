"""services.flow_trace — 会话路径重放服务（T-1042 实时跑偏检测）。

对话进行中扫描当前进展：会话 JSONL 每轮增量落盘（agent/runtime 每轮 save），
本服务把已落盘行喂给 evals.flowpath 的路径重放，得到「golden flow 基线 vs
实际走径」的当前态——前端右侧 🧭 路径 面板轮询本结果即可实时展示跑偏。

依赖方向纪律：workbench → evals 函数级懒加载（evals 上游是 agent/mcp_server，
模块级引入会把评测依赖钉进工作台组合根）；evals 不可用时诚实降级
（available=false + reason），不炸对话主链路。
"""

from __future__ import annotations

from datetime import datetime


def build_flow_trace(rows: list, session_id: str = "") -> dict:
    """会话行（JSONL 已解析）→ 路径重放结构。纯读、无副作用。"""
    try:
        from evals.baseline import scan_rows
        from evals.flowpath import render_flow_mermaid, trace_scan
    except Exception as e:  # 评测依赖缺失/版本不齐 → 诚实降级，不影响对话
        return {"available": False, "reason": f"evals 模块加载失败: {e}"}

    scan = scan_rows(rows, session_id=session_id)
    if scan is None:
        return {"available": False, "reason": "会话无有效行（空会话或未落盘）"}
    try:
        trace = trace_scan(scan)
    except Exception as e:  # 路径重放自身异常 → 降级不炸
        return {"available": False, "reason": f"路径重放执行失败: {e}"}

    return {
        "available": True,
        "session_id": trace.session_id,
        "flow_id": trace.flow_id,
        "flow_title": trace.flow_title,
        "flow_source": trace.flow_source,
        "is_generate": trace.is_generate,
        "n_tool_calls": trace.n_tool_calls,
        "total_tokens": trace.total_tokens,
        "purpose": trace.purpose,
        "workspace": trace.workspace,
        "stages": [
            {"key": s.key, "label": s.label, "required": s.required, "status": s.status,
             "first_step": s.first_step, "times": s.times, "tools": s.tools, "note": s.note}
            for s in trace.stages
        ],
        "deviations": list(trace.deviations),
        "extras": list(trace.extras),
        "n_missing": trace.n_missing,
        "n_out_of_order": trace.n_out_of_order,
        "mermaid": render_flow_mermaid(trace),  # 图形视图（前端 MermaidBlock 主题跟随渲染）
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
