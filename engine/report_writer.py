"""报告写出：JSON 结构化落盘（可视化数据源）+ MD 四段式渲染。

JSON 先行：一切执行记录先落 JSON，MD 只是 JSON 的一种渲染视图。
"""

import json
import os

from engine.execution_record import VERDICT_PASS, VERDICT_FAIL, VERDICT_SKIP, VERDICT_BLOCKED

SCHEMA_VERSION = "1.0"

_VERDICT_CN = {VERDICT_PASS: "通过", VERDICT_FAIL: "失败",
               VERDICT_SKIP: "跳过", VERDICT_BLOCKED: "阻塞"}


# ══════════════════════════════════════════════════════════
# JSON 落盘
# ══════════════════════════════════════════════════════════

def dump_json(records, run_dir, meta):
    """meta: {run_id, env, system, started_at}"""
    os.makedirs(os.path.join(run_dir, "cases"), exist_ok=True)

    stats = {VERDICT_PASS: 0, VERDICT_FAIL: 0, VERDICT_SKIP: 0, VERDICT_BLOCKED: 0}
    cases_index = []
    for r in records:
        stats[r.verdict] = stats.get(r.verdict, 0) + 1
        d = r.to_dict()
        # 索引中的相对路径统一用正斜杠（Web 端消费 run.json 时跨平台一致）；
        # exclusive 依赖会产生同场景多实例，文件名用实例号区分避免覆盖
        suffix = ""
        if r.upstream_of:
            suffix = "_upstream" if r.instance_no <= 1 else f"_inst{r.instance_no}"
        elif r.instance_no > 1:
            suffix = f"_inst{r.instance_no}"
        case_name = f"{r.scenario_id}{suffix}.json"
        with open(os.path.join(run_dir, "cases", case_name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        cases_index.append({
            "id": r.scenario_id, "title": r.title, "verdict": r.verdict,
            "duration_ms": r.duration_ms, "covers": r.covers,
            "upstream_of": r.upstream_of, "instance_no": r.instance_no,
            "dep_mode": r.dep_mode, "file": f"cases/{case_name}",
            "skip_category": r.skip_category,
            "warning_count": r.warning_count,
        })

    run_doc = {
        "schema_version": SCHEMA_VERSION,
        "run_id": meta["run_id"],
        "env": meta.get("env"),
        "system": meta.get("system"),
        "started_at": meta.get("started_at"),
        "finished_at": meta.get("finished_at"),
        "stats": {"pass": stats.get(VERDICT_PASS, 0), "fail": stats.get(VERDICT_FAIL, 0),
                  "skip": stats.get(VERDICT_SKIP, 0), "blocked": stats.get(VERDICT_BLOCKED, 0),
                  "total": len(records),
                  "warnings": sum(r.warning_count for r in records)},
        "leases": meta.get("leases", {}),   # 租约快照：{resource_type: {key: holder}}
        "cases": cases_index,
    }
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(run_doc, f, ensure_ascii=False, indent=2, default=str)
    return run_doc


# ══════════════════════════════════════════════════════════
# MD 四段式渲染（原始内容 / 执行过程 / 结果 / 情况分析）
# ══════════════════════════════════════════════════════════

def _fmt_val(v, limit=200):
    s = json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else str(v)
    return s if len(s) <= limit else s[:limit] + f"…(共{len(s)}字符)"


def _render_case_md(r):
    """r: ExecutionRecord.to_dict() 后的 dict"""
    lines = []
    verdict = r["verdict"]
    lines.append(f"## {r['scenario_id']} {r['title']} [{verdict}]")
    lines.append("")

    # ── 原始内容 ──
    lines.append("### 原始内容")
    doc = r.get("doc") or {}
    if doc:
        for k in ("given", "when", "then"):
            if doc.get(k):
                lines.append(f"- **{k}**: {doc[k]}")
        if r.get("covers"):
            lines.append(f"- **覆盖 FR**: {', '.join(r['covers'])}")
    given = r.get("given") or {}
    if given.get("depends_on"):
        lines.append(f"- **依赖链**: {' → '.join(given['depends_on'])} → 本场景")
    if given.get("emp_pool"):
        lines.append(f"- **工号池**: {given['emp_pool']}")
    if given.get("account"):
        lines.append(f"- **使用账号**: {given['account']}")
    lines.append("")

    # ── 执行过程 ──
    lines.append("### 执行过程")
    if not r.get("steps") and not r.get("oracle_traces") and not r.get("db_traces"):
        lines.append("- （未执行）")
    for i, s in enumerate(r.get("steps", []), 1):
        req = s.get("request") or {}
        desc = s.get("note") or f"{req.get('method', '')} {req.get('path', '')}"
        params = f" params={_fmt_val(req['params'], 120)}" if req.get("params") else ""
        who = f"[{req['as']}] " if req.get("as") else ""
        status = f" → {s['response_status']}" if s.get("response_status") is not None else ""
        trace = f" | trace={s['trace_id']}" if s.get('trace_id') else ""
        lines.append(f"{i}. **{s['type']}** {who}{desc}{params}{status}{trace}（{s.get('duration_ms', 0)}ms）")
    for t in r.get("oracle_traces", []):
        lines.append(f"- 权限预言: {_fmt_val(t, 300)}")
    for t in r.get("db_traces", []):
        lines.append(f"- DB 校对: {_fmt_val(t, 300)}")
    lines.append("")

    # ── 结果 ──
    lines.append("### 结果")
    if r.get("assertions"):
        lines.append("| # | 断言 | 实际 | 预期 | 结论 |")
        lines.append("|---|------|------|------|------|")
        for i, a in enumerate(r["assertions"], 1):
            mark = "✓" if a["passed"] else "✗"
            lines.append(f"| {i} | {a['expr']} | {_fmt_val(a.get('actual'), 60)} "
                         f"| {_fmt_val(a.get('expected'), 60)} | {mark} |")
    else:
        lines.append("- （无断言记录）")
    lines.append("")

    # ── 情况分析 ──
    lines.append("### 情况分析")
    lines.extend(_render_analysis(r))
    lines.append("")
    return lines


def _render_analysis(r):
    if r["verdict"] == VERDICT_PASS:
        out = ["- 结论：通过"]
        warn_count = r.get("warning_count") or 0
        if warn_count:
            out.append(f"- ⚠️ WARN：{warn_count} 条宽松差异（PASS 带警告，趋势突增是回归前兆）")
        ctx = []
        if (r.get("given") or {}).get("emp_pool"):
            ctx.append(r["given"]["emp_pool"])
        ctx.append(f"执行步骤 {len(r.get('steps', []))} 个，断言 {len(r.get('assertions', []))} 条全部通过")
        out.append(f"- 数据上下文：{'；'.join(ctx)}")
        return out
    if r["verdict"] in (VERDICT_SKIP, VERDICT_BLOCKED):
        cat = r.get("skip_category") or "uncategorized"
        cat_note = f"（归类: {cat}）" if cat != "uncategorized" else ""
        return [f"- 结论：{_VERDICT_CN.get(r['verdict'], r['verdict'])}{cat_note}", f"- 原因：{r.get('skip_reason') or '未说明'}"]
    # FAIL
    f = r.get("failure") or {}
    out = [f"- 失败归类：`{f.get('category', 'unknown')}`", f"- 原因：{f.get('message', '')}"]
    evidence = f.get("evidence")
    if evidence:
        out.append("- 证据：")
        for ev in (evidence if isinstance(evidence, list) else [evidence]):
            if isinstance(ev, dict):
                out.append(f"  - {ev.get('expr', '')}: 实际 {_fmt_val(ev.get('actual'), 80)}，"
                           f"预期 {_fmt_val(ev.get('expected'), 80)}。{ev.get('message', '')}")
            else:
                out.append(f"  - {_fmt_val(ev, 120)}")
    return out


def render_md(records, run_dir, meta):
    """渲染四段式 report.md"""
    stats = {"pass": 0, "fail": 0, "skip": 0, "blocked": 0}
    for r in records:
        key = {VERDICT_PASS: "pass", VERDICT_FAIL: "fail",
               VERDICT_SKIP: "skip", VERDICT_BLOCKED: "blocked"}[r.verdict]
        stats[key] += 1

    module = meta.get("module") or ""
    title_module = module

    lines = [
        f"# SpecGuard 测试报告 {('— ' + title_module) if title_module else ''}",
        "",
        f"> run_id: `{meta['run_id']}` | 环境: {meta.get('env')} | 系统: {meta.get('system')} "
        f"| 开始时间: {meta.get('started_at')}",
        f"> 总览：**{stats['pass']} 通过 / {stats['fail']} 失败 / {stats['skip']} 跳过 / {stats['blocked']} 阻塞**"
        f"（共 {len(records)} 条记录，含上游准备）",
        "",
        "## 结果总览",
        "",
        "| 场景 | 标题 | 结果 | 耗时 | 覆盖 FR | 备注 |",
        "|------|------|------|------|---------|------|",
    ]
    for r in records:
        note = ""
        if r.upstream_of:
            note = f"上游（{r.upstream_of}）"
        elif r.verdict in (VERDICT_SKIP, VERDICT_BLOCKED):
            note = r.skip_reason[:40]
        elif r.verdict == VERDICT_FAIL and r.failure:
            note = r.failure.get("category", "")[:40]
        lines.append(f"| {r.scenario_id} | {r.title} | {r.verdict} | {r.duration_ms}ms "
                     f"| {', '.join(r.covers)} | {note} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in records:
        lines.extend(_render_case_md(r.to_dict()))
        lines.append("---")
        lines.append("")

    report_path = os.path.join(run_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path
