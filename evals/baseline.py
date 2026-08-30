"""evals.baseline — Phase 0 基线仪表盘聚合器（T-1042）。

定位（《docs/SpecGuard-Agent评测体系-现状基线.md》§十五.5 + 知识库
《2026-08-26-2037 评估架构体系设计》Phase 0）：聚合**已落盘**的三类信号，
产出七指标基线报告——零新埋点、纯读、离线可跑。

数据源（全部只读，路径可注入，默认主库布局）：
  - 会话 JSONL   agent/sessions/**/{sid}.jsonl
                  （session_meta / system·user·assistant·tool / metrics / todo_list）
  - 逐轮 metrics  agent/sessions/**/{sid}_metrics.jsonl
                  （timestamp/model/prompt_tokens/completion_tokens/total_tokens/…）
  - 工具审计      workbench.db::sf_mcp_call_audit
                  （tool_name/side_effect/verdict(ok|denied-*|warn)/created_at）

七指标（§十五.5）：
  1. tool_call_success_rate   工具调用成功率（会话 tool 行结果前缀判定，与 harness 同源）
  2. denied_whitelist_rate    越权拒绝率（sf_mcp_call_audit verdict=denied-whitelist 占比）
  3. fuse_rate                熔断率（会话含 [FUSE] system 行的占比）
  4. gate3_pass_rate          三闸通过率（audit_log 三闸事件口径，无数据诚实报 None）
  5. validate_first_pass_rate validate 一次通过率（每会话首次 validate 即 PASS 占比）
  6. correction_trigger_rate  纠正触发率（user 消息命中纠正关键词的会话占比）
  7. avg_tokens_per_task      每任务 token（metrics total_tokens 均值 + 分位）

诚实性原则：任一指标无足够数据时给 None 并注明 reason，不造假数字（T-964 教训）。
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ── 与 harness.py 同源的工具结果错误前缀（单一事实，复制保持判定一致）──
_RESULT_ERROR_PREFIXES = (
    "错误：",
    "[越权拒绝]",
    "未知工具:",
    "工具执行异常:",
    "[SIDE_EFFECT_VIOLATION]",
    "[拒绝]",
)

# 纠正关键词（经验飞轮 T-510 口径）：用户说「不对/错了/应该是…」即纠正
_CORRECTION_KEYWORDS = ("不对", "错了", "应该是", "不应", "你搞错", "重新", "不是这样")

# validate 工具名（合并工具 action 参数化后的调用名候选）
_VALIDATE_TOOL_NAMES = ("validate", "spec_validate")


@dataclass
class SessionScan:
    """单个会话 JSONL 的扫描结果（轨迹类信号）。"""
    session_id: str
    path: str
    purpose: str = ""
    workspace: str = ""
    emp_no: str = ""
    n_user: int = 0
    n_assistant: int = 0
    n_tool_calls: int = 0
    n_tool_ok: int = 0
    n_tool_fail: int = 0
    fused: bool = False
    had_correction: bool = False
    validate_calls: int = 0
    validate_first_pass: bool | None = None  # 有 validate 调用才有意义
    validate_pass: int = 0
    validate_fail: int = 0
    total_tokens: int = 0
    model: str = ""
    tools_used: list = field(default_factory=list)


def _tool_result_ok(result: str) -> bool:
    return not str(result).startswith(_RESULT_ERROR_PREFIXES)


def _validate_verdict(content: str) -> str | None:
    """从 validate 工具结果文本里提取 verdict（PASS/REJECT/ERROR）。

    validate 结果可能是 JSON（{"verdict": "PASS", ...}）或含 verdict 字样的文本。
    提取不到返回 None（不计入一次通过率，避免误判）。
    """
    text = str(content).strip()
    # JSON 形态
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            v = obj.get("verdict") or (obj.get("summary") or {}).get("verdict")
            if isinstance(v, str):
                return v.upper()
        except (json.JSONDecodeError, AttributeError):
            pass
    # 文本形态：找 verdict 关键词
    upper = text.upper()
    for tag in ("PASS", "REJECT", "ERROR", "FAIL"):
        if f'"VERDICT": "{tag}"' in upper or f"VERDICT={tag}" in upper or f"VERDICT: {tag}" in upper:
            return tag
    return None


def scan_session(path: str | Path) -> SessionScan | None:
    """扫描单个会话 JSONL，提取 Phase 0 轨迹信号。解析失败返回 None（跳过不炸）。"""
    path = Path(path)
    try:
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not rows:
        return None

    scan = SessionScan(session_id=path.stem, path=str(path))
    # smoke 隔离区（T-1041）：路径任一段为 smoke 即测试/验收产物，不计生产基线
    if "smoke" in path.parts:
        scan.purpose = "__smoke__"
    # tool_call_id → tool_name（assistant 声明），用于把 tool 结果行归到具体工具
    call_id_to_tool: dict[str, str] = {}
    validate_results: list[str | None] = []

    for o in rows:
        rtype = o.get("_type") or o.get("role")
        if rtype == "session_meta":
            # smoke 标记优先（路径权威），不被 meta 覆盖
            if scan.purpose != "__smoke__":
                p = o.get("purpose", "") or ""
                # purpose 空 = T-010 体系（2026-08-10）落地前的历史会话，如实标注
                scan.purpose = p if p else "legacy(no-purpose)"
            scan.workspace = o.get("workspace", "") or scan.workspace
            scan.emp_no = o.get("emp_no", "") or scan.emp_no
        elif rtype == "user":
            scan.n_user += 1
            content = str(o.get("content", ""))
            if any(kw in content for kw in _CORRECTION_KEYWORDS):
                scan.had_correction = True
        elif rtype == "assistant":
            scan.n_assistant += 1
            for tc in (o.get("tool_calls") or []):
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                scan.n_tool_calls += 1
                call_id_to_tool[tc.get("id", "")] = name
                scan.tools_used.append(name)
                if name in _VALIDATE_TOOL_NAMES:
                    scan.validate_calls += 1
        elif rtype == "tool":
            result = str(o.get("content", ""))
            ok = _tool_result_ok(result)
            if ok:
                scan.n_tool_ok += 1
            else:
                scan.n_tool_fail += 1
            tool_name = call_id_to_tool.get(o.get("tool_call_id", ""), "")
            if tool_name in _VALIDATE_TOOL_NAMES:
                validate_results.append(_validate_verdict(result))
        elif rtype == "system":
            content = str(o.get("content", ""))
            if "[FUSE]" in content:
                scan.fused = True
        elif rtype == "metrics":
            # 会话级汇总 metrics 行（save 时写入，最后一行最新）
            scan.total_tokens = int(o.get("total_tokens", 0) or 0)
            scan.model = o.get("model", "") or scan.model

    # validate 一次通过率：第一次 validate 的结果
    if validate_results:
        first = validate_results[0]
        scan.validate_first_pass = (first == "PASS") if first is not None else None
        scan.validate_pass = sum(1 for v in validate_results if v == "PASS")
        scan.validate_fail = sum(1 for v in validate_results if v in ("REJECT", "ERROR", "FAIL"))
    return scan


def scan_metrics_files(sessions_root: str | Path) -> dict:
    """聚合逐轮 metrics 文件：每任务 token（均值/分位）、模型分布、缓存命中。"""
    pattern = str(Path(sessions_root) / "**" / "*_metrics.jsonl")
    files = glob.glob(pattern, recursive=True)
    totals: list[int] = []
    cache_hits = 0
    cache_misses = 0
    models: dict[str, int] = {}
    for f in files:
        try:
            for ln in Path(f).read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                o = json.loads(ln)
                tt = int(o.get("total_tokens", 0) or 0)
                if tt > 0:
                    totals.append(tt)
                cache_hits += int(o.get("cache_hits", 0) or 0)
                cache_misses += int(o.get("cache_misses", 0) or 0)
                m = o.get("model", "") or "unknown"
                models[m] = models.get(m, 0) + 1
        except (OSError, json.JSONDecodeError):
            continue
    totals.sort()

    def _pct(p: float) -> int | None:
        if not totals:
            return None
        idx = min(len(totals) - 1, max(0, round(p * (len(totals) - 1))))
        return totals[idx]

    return {
        "files": len(files),
        "turns_with_tokens": len(totals),
        "avg_total_tokens": round(sum(totals) / len(totals), 1) if totals else None,
        "p50_total_tokens": _pct(0.50),
        "p95_total_tokens": _pct(0.95),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate": round(cache_hits / (cache_hits + cache_misses), 4)
        if (cache_hits + cache_misses) else None,
        "models": models,
    }


def scan_audit(db_path: str | Path) -> dict:
    """聚合 sf_mcp_call_audit：verdict 分布（越权拒绝率）、按工具/用途分桶。"""
    if not Path(db_path).exists():
        return {"available": False, "reason": f"workbench.db 不存在: {db_path}"}
    try:
        c = sqlite3.connect(str(db_path))
        verdicts = dict(c.execute(
            "SELECT verdict, COUNT(*) FROM sf_mcp_call_audit GROUP BY verdict").fetchall())
        by_tool = dict(c.execute(
            "SELECT tool_name, COUNT(*) FROM sf_mcp_call_audit "
            "GROUP BY tool_name ORDER BY COUNT(*) DESC LIMIT 15").fetchall())
        denied_by_tool = dict(c.execute(
            "SELECT tool_name, COUNT(*) FROM sf_mcp_call_audit "
            "WHERE verdict='denied-whitelist' GROUP BY tool_name "
            "ORDER BY COUNT(*) DESC LIMIT 10").fetchall())
        total = sum(verdicts.values())
        c.close()
    except sqlite3.Error as e:
        return {"available": False, "reason": f"审计库读取失败: {e}"}
    denied = verdicts.get("denied-whitelist", 0)
    return {
        "available": True,
        "total_calls": total,
        "verdicts": verdicts,
        "denied_whitelist": denied,
        "denied_whitelist_rate": round(denied / total, 4) if total else None,
        "top_tools": by_tool,
        "denied_by_tool": denied_by_tool,
    }


def scan_gate3(db_path: str | Path) -> dict:
    """三闸通过率：audit_log 里三闸相关事件的通过/拒绝分布。

    三闸事件在 audit_log.action 里的命名需按真实落库口径匹配（gate/promote/三闸）。
    无匹配数据时诚实报 available=False，不造假数字。
    """
    if not Path(db_path).exists():
        return {"available": False, "reason": f"workbench.db 不存在: {db_path}"}
    try:
        c = sqlite3.connect(str(db_path))
        rows = c.execute(
            "SELECT action, COUNT(*) FROM audit_log "
            "WHERE action LIKE '%gate%' OR action LIKE '%promote%' OR action LIKE '%三闸%' "
            "GROUP BY action").fetchall()
        c.close()
    except sqlite3.Error as e:
        return {"available": False, "reason": f"audit_log 读取失败: {e}"}
    if not rows:
        return {"available": False, "reason": "audit_log 无三闸/promote 相关事件"}
    return {"available": True, "actions": dict(rows)}


def build_baseline_report(sessions_root: str | Path, db_path: str | Path,
                          limit: int | None = None) -> dict:
    """Phase 0 主入口：扫描全部数据源，产出七指标基线报告（dict，可 JSON 序列化）。"""
    pattern = str(Path(sessions_root) / "**" / "*.jsonl")
    session_files = [f for f in glob.glob(pattern, recursive=True)
                     if "_metrics" not in f and "_truncated" not in f.replace("\\", "/")]
    if limit:
        session_files = session_files[:limit]

    scans: list[SessionScan] = []
    for f in session_files:
        s = scan_session(f)
        if s is not None:
            scans.append(s)

    # smoke 隔离区（T-1041）与生产会话分离：生产基线只统计 prod，smoke 单列
    prod = [s for s in scans if s.purpose != "__smoke__"]
    smoke = [s for s in scans if s.purpose == "__smoke__"]

    n = len(prod)
    # 1. 工具调用成功率
    total_calls = sum(s.n_tool_calls for s in prod)
    total_ok = sum(s.n_tool_ok for s in prod)
    total_fail = sum(s.n_tool_fail for s in prod)
    tool_success = round(total_ok / (total_ok + total_fail), 4) if (total_ok + total_fail) else None
    # 3. 熔断率
    n_fused = sum(1 for s in prod if s.fused)
    # 5. validate 一次通过率（仅统计有 validate 调用的会话）
    with_validate = [s for s in prod if s.validate_calls > 0]
    n_val_first_pass = sum(1 for s in with_validate if s.validate_first_pass is True)
    n_val_scored = sum(1 for s in with_validate if s.validate_first_pass is not None)
    # 6. 纠正触发率
    n_correction = sum(1 for s in prod if s.had_correction)
    # 7. 每任务 token（会话级汇总行）
    tokens = sorted(s.total_tokens for s in prod if s.total_tokens > 0)

    metrics_agg = scan_metrics_files(sessions_root)
    audit_agg = scan_audit(db_path)
    gate3_agg = scan_gate3(db_path)

    # purpose 分布（生产会话）
    purposes: dict[str, int] = {}
    for s in prod:
        p = s.purpose or "unknown"
        purposes[p] = purposes.get(p, 0) + 1

    return {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "data_sources": {
            "sessions_root": str(sessions_root),
            "db_path": str(db_path),
            "session_files": len(session_files),
            "sessions_scanned": len(scans),
            "production_sessions": n,
            "smoke_sessions_excluded": len(smoke),
        },
        "indicators": {
            "1_tool_call_success_rate": {
                "value": tool_success,
                "detail": {"ok": total_ok, "fail": total_fail, "declared_calls": total_calls},
            },
            "2_denied_whitelist_rate": {
                "value": audit_agg.get("denied_whitelist_rate"),
                "detail": audit_agg.get("verdicts") if audit_agg.get("available") else audit_agg,
            },
            "3_fuse_rate": {
                "value": round(n_fused / n, 4) if n else None,
                "detail": {"fused_sessions": n_fused, "total_sessions": n},
            },
            "4_gate3_pass_rate": {
                "value": None,
                "detail": gate3_agg,
                "note": "三闸事件口径待确认后细化；当前仅列出匹配到的 audit_log action 分布",
            },
            "5_validate_first_pass_rate": {
                "value": round(n_val_first_pass / n_val_scored, 4) if n_val_scored else None,
                "detail": {
                    "sessions_with_validate": len(with_validate),
                    "scorable": n_val_scored,
                    "first_pass": n_val_first_pass,
                    "note": "仅统计能提取到 verdict 的会话；结果非 JSON 或无 verdict 字样的不计入",
                },
            },
            "6_correction_trigger_rate": {
                "value": round(n_correction / n, 4) if n else None,
                "detail": {"corrected_sessions": n_correction, "total_sessions": n,
                           "keywords": list(_CORRECTION_KEYWORDS)},
            },
            "7_avg_tokens_per_task": {
                "value": round(sum(tokens) / len(tokens), 1) if tokens else None,
                "detail": {
                    "sessions_with_tokens": len(tokens),
                    "p50": tokens[len(tokens) // 2] if tokens else None,
                    "p95": tokens[min(len(tokens) - 1, round(0.95 * (len(tokens) - 1)))] if tokens else None,
                    "per_turn_metrics": metrics_agg,
                },
            },
        },
        "distributions": {
            "purposes": purposes,
            "workspaces": _count_by(prod, "workspace"),
        },
        "audit_top_tools": audit_agg.get("top_tools", {}),
        "audit_denied_by_tool": audit_agg.get("denied_by_tool", {}),
    }


def _count_by(scans: list[SessionScan], attr: str) -> dict:
    out: dict[str, int] = {}
    for s in scans:
        v = getattr(s, attr, "") or "unknown"
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def render_markdown(report: dict) -> str:
    """把基线报告 dict 渲染成 Markdown（仪表盘人读面）。"""
    ind = report["indicators"]
    src = report["data_sources"]

    def fmt(v):
        return f"{v:.2%}" if isinstance(v, float) and v is not None else ("—" if v is None else str(v))

    def fmtnum(v):
        return "—" if v is None else (f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))

    lines = [
        "# SpecGuard Agent Phase 0 基线仪表盘",
        "",
        f"> 生成时间：{report['generated_at']}　|　数据源：`{src['sessions_root']}`",
        f"> 会话文件 {src['session_files']} 个，成功扫描 {src['sessions_scanned']} 个；"
        f"**生产会话 {src['production_sessions']} 个**（已排除 smoke 隔离区 {src['smoke_sessions_excluded']} 个）；"
        f"审计库 `{src['db_path']}`",
        "",
        "## 七指标基线（§十五.5，仅生产会话口径）",
        "",
        "| # | 指标 | 数值 | 备注 |",
        "|---|------|------|------|",
    ]
    rows = [
        ("1", "工具调用成功率", fmt(ind["1_tool_call_success_rate"]["value"]),
         f"ok={ind['1_tool_call_success_rate']['detail']['ok']} fail={ind['1_tool_call_success_rate']['detail']['fail']}"),
        ("2", "越权拒绝率（denied-whitelist）", fmt(ind["2_denied_whitelist_rate"]["value"]),
         json.dumps(ind["2_denied_whitelist_rate"]["detail"], ensure_ascii=False)),
        ("3", "熔断率", fmt(ind["3_fuse_rate"]["value"]),
         f"熔断会话 {ind['3_fuse_rate']['detail']['fused_sessions']}/{ind['3_fuse_rate']['detail']['total_sessions']}"),
        ("4", "三闸通过率", fmt(ind["4_gate3_pass_rate"]["value"]),
         str(ind["4_gate3_pass_rate"].get("note", ""))[:60]),
        ("5", "validate 一次通过率", fmt(ind["5_validate_first_pass_rate"]["value"]),
         f"可评分会话 {ind['5_validate_first_pass_rate']['detail']['scorable']}（含 validate 共 {ind['5_validate_first_pass_rate']['detail']['sessions_with_validate']}）"),
        ("6", "纠正触发率", fmt(ind["6_correction_trigger_rate"]["value"]),
         f"纠正会话 {ind['6_correction_trigger_rate']['detail']['corrected_sessions']}/{ind['6_correction_trigger_rate']['detail']['total_sessions']}"),
        ("7", "每任务 token（均值）", fmtnum(ind["7_avg_tokens_per_task"]["value"]),
         f"p50={fmtnum(ind['7_avg_tokens_per_task']['detail']['p50'])} p95={fmtnum(ind['7_avg_tokens_per_task']['detail']['p95'])}"),
    ]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | **{r[2]}** | {r[3]} |")

    dist = report["distributions"]
    lines += [
        "",
        "## 分布",
        "",
        f"- **purpose 分布**：{json.dumps(dist['purposes'], ensure_ascii=False)}",
        "  - `legacy(no-purpose)` = purpose 体系（T-010，2026-08-10）落地前的历史会话，非解析失败",
        f"- **workspace 分布**：{json.dumps(dist['workspaces'], ensure_ascii=False)}",
        f"- **审计 TOP 工具**：{json.dumps(report['audit_top_tools'], ensure_ascii=False)}",
        "  - ⚠ 审计库混有测试/探针数据（`nonexistent_*`/`switch_mode` 等非生产工具名），解读时需剔除",
        f"- **越权拒绝 TOP 工具**：{json.dumps(report['audit_denied_by_tool'], ensure_ascii=False)}",
        "",
        "> 指标 4（三闸通过率）当前为占位——三闸事件在 audit_log 的真实 action 口径确认后再细化；",
        "> 指标 5 仅统计能提取 verdict 的会话，结果非 JSON 的 validate 调用不计入（诚实不计，不造假）。",
    ]
    return "\n".join(lines)
