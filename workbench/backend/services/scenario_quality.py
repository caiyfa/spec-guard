"""scenario_quality — 测试用例管理页数据装配（T-1035）。

只读派生，三源确定性聚合（无落库，重扫重建同一结果）：
  场景 YAML（engine.scenario_loader.load_scenarios，含 _suite.yaml 套件元信息；
    行载荷附 doc 语义摘要 + flow/verify 一行式人话描述，明细展开即见用例内容）
× spec FR 锚点（specstd.anchors.scan_anchors，covers 逐条解析有效性+标题；
    无工作区锚点时诚实跳过 invalid 判定并置 anchors_available=False）
× 断言证据（sg_core.test_dimensions.extract_evidence，深度评级输入）

评级与问题标记在后端确定性计算，前端只渲染——规则口径唯一事实源在本文件。

评级规则：
  deep      深断言——证据含 oracle/db_proof/python，或 flow 含 db_query 步骤
  shallow   浅断言——证据不出 {http_ok, json_field}（仅成功状态+字段存在性）且 verify ≤3 条
  no-verify 无断言——verify 为空（探针/半成品）
  medium    其他（有实质字段断言，但无持久层/脚本证据）

问题标记（一个场景可命中多个）：
  missing-covers  doc.covers 为空（FR 追溯断裂）
  invalid-covers  covers 中有 spec 锚点表查不到的 FR
  shallow         浅断言（评级 shallow）
  no-verify       无断言（评级 no-verify）
  probe           探针——verify 为空且 flow 含 python 步骤（调试残留特征）
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from services.scenario_store import scenarios_root

_DEEP_EVIDENCE = {"oracle", "db_proof", "python"}

GRADE_DEEP = "deep"
GRADE_MEDIUM = "medium"
GRADE_SHALLOW = "shallow"
GRADE_NO_VERIFY = "no-verify"
GRADES = (GRADE_DEEP, GRADE_MEDIUM, GRADE_SHALLOW, GRADE_NO_VERIFY)

ISSUE_MISSING_COVERS = "missing-covers"
ISSUE_INVALID_COVERS = "invalid-covers"
ISSUE_SHALLOW = "shallow"
ISSUE_NO_VERIFY = "no-verify"
ISSUE_PROBE = "probe"

_CACHE_TTL = 30.0
_cache: dict = {"key": None, "ts": 0.0, "payload": None}


def invalidate_cache():
    _cache.update(key=None, ts=0.0, payload=None)


def _load_anchors() -> dict:
    """当前工作区 FR 锚点（与 coverage_gaps 同口径；无工作区/扫描失败诚实为空）。"""
    try:
        from specstd.anchors import scan_anchors
        from specstd.workspace import get_workspace_root
        ws = get_workspace_root()
        if not ws:
            return {}
        return scan_anchors(ws)
    except Exception:
        return {}


def _step_stats(flow: list) -> tuple[dict, dict]:
    """步骤类型计数 + tool 使用计数（含未走 tool 信封的遗留直写形式）。"""
    steps: dict[str, int] = {}
    tools: dict[str, int] = {}
    known = {"call", "db_query", "poll", "tool", "python", "random", "set_var"}
    for step in flow or []:
        if not isinstance(step, dict) or not step:
            continue
        kind = next(iter(step))
        steps[kind] = steps.get(kind, 0) + 1
        if kind == "tool":
            use = (step.get("tool") or {}).get("use")
            if use:
                tools[str(use)] = tools.get(str(use), 0) + 1
        elif kind not in known:
            tools[kind] = tools.get(kind, 0) + 1
    return steps, tools


def _oracles_used(verify: list) -> dict:
    """verify 中 oracle 断言器使用计数（值形态：字符串 或 {name, params}）。"""
    oracles: dict[str, int] = {}
    for item in verify or []:
        if not isinstance(item, dict) or "oracle" not in item:
            continue
        raw = item["oracle"]
        name = raw if isinstance(raw, str) else (raw or {}).get("name", "")
        if name:
            oracles[str(name)] = oracles.get(str(name), 0) + 1
    return oracles


def _clip(text: str, limit: int = 60) -> str:
    """单行截断（明细一行式展示用）。"""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _step_line(step: dict) -> str:
    """flow 步骤一行式人话描述（确定性，不做语义推断）。"""
    kind = next(iter(step))
    body = step.get(kind) or {}
    if kind == "call":
        method = str(body.get("method", "GET")).upper()
        line = f"调用 {method} {body.get('path', '')}"
        if body.get("as"):
            line += f"（账号 {body['as']}）"
    elif kind == "db_query":
        line = f"DB 查询 {_clip(body.get('sql', ''), 48)}"
    elif kind == "poll":
        call = body.get("call") or {}
        line = f"轮询 {call.get('method', 'GET')} {call.get('path', '')}（直至条件满足或超时）"
    elif kind == "tool":
        line = f"工具 {body.get('use', '')}"
        if body.get("with"):
            line += f"（参数 {_clip(body['with'], 40)}）"
    elif kind == "python":
        line = f"Python 脚本 {_clip(body.get('script') or body.get('file') or '', 48)}"
    elif kind == "random":
        line = f"随机数据 {_clip(body.get('type', ''), 24)}"
    elif kind == "set_var":
        line = f"注入变量 {', '.join(k for k in body if k != 'save')}" if isinstance(body, dict) else "注入变量"
    else:
        line = f"工具 {kind}（遗留直写形式）"
    if isinstance(body, dict) and body.get("save"):
        line += f" → 存 {body['save']}"
    return line


def _verify_line(item: dict) -> str:
    """verify 断言一行式人话描述（确定性，不做语义推断）。"""
    of = ""
    if "status" in item:
        s = item["status"] or {}
        of = s.get("of", "")
        line = f"HTTP 状态 = {s.get('eq', '?')}"
    elif "json" in item:
        j = item["json"] or {}
        of = j.get("of", "")
        ops = [f"{op} {_clip(j[op], 24)}" for op in j if op not in ("path", "of")]
        line = f"响应字段 {j.get('path', '')} {'，'.join(ops)}"
    elif "oracle" in item:
        raw = item["oracle"]
        name = raw if isinstance(raw, str) else (raw or {}).get("name", "")
        line = f"DB 校对断言器 {name}"
        if isinstance(raw, dict) and raw.get("params"):
            line += f"（参数 {_clip(raw['params'], 40)}）"
    elif "python" in item:
        line = "Python 断言脚本"
    else:
        line = _clip(item, 48)
    if of:
        line += f"（断言对象 {of}）"
    return line


def _doc_summary(doc: dict) -> dict:
    """doc 层业务语义（given/when/then 原文摘录）。"""
    return {k: str(doc.get(k, "") or "") for k in ("given", "when", "then")}


def _covers_detail(covers: list, anchors: dict) -> list:
    """covers 逐条解析：有效 → 附锚点标题/模块；失效 → 标记（前端展示「锚点表查不到」）。"""
    detail = []
    for c in covers:
        info = anchors.get(c)
        detail.append({
            "fr": c,
            "valid": bool(info),
            "title": str(getattr(info, "title", "") or "") if info else "",
            "module": str(getattr(info, "module", "") or "") if info else "",
        })
    return detail


def _grade(evidence: set, verify_count: int, has_db_query: bool) -> str:
    """断言深度评级（规则见模块 docstring，改动需同步前端口径提示）。"""
    if verify_count == 0:
        return GRADE_NO_VERIFY
    if evidence & _DEEP_EVIDENCE or has_db_query:
        return GRADE_DEEP
    if evidence <= {"http_ok", "json_field"} and verify_count <= 3:
        return GRADE_SHALLOW
    return GRADE_MEDIUM


def collect_quality(refresh: bool = False) -> dict:
    """质量全景（30s 缓存；工作区/场景库切换自动换键，refresh=True 强制重扫）。"""
    root = scenarios_root()
    try:
        from specstd.workspace import get_workspace_root
        ws_key = str(get_workspace_root() or "")
    except Exception:
        ws_key = ""
    key = f"{root}|{ws_key}"
    now = time.time()
    if (not refresh and _cache["payload"] is not None
            and _cache["key"] == key and now - _cache["ts"] < _CACHE_TTL):
        return _cache["payload"]
    payload = _build(root)
    _cache.update(key=key, ts=now, payload=payload)
    return payload


def _build(root: Path) -> dict:
    from engine.scenario_loader import load_scenarios
    from sg_core.test_dimensions import extract_evidence

    anchors = _load_anchors()
    scenarios = load_scenarios(str(root))  # ScenarioLoadError 由 router 转 500 诚实报错

    rows: list[dict] = []
    suite_agg: dict[str, dict] = {}
    matrix_steps: dict[str, int] = {}
    matrix_tools: dict[str, int] = {}
    matrix_oracles: dict[str, int] = {}
    matrix_depends = {"shared": 0, "exclusive": 0}
    covered_frs: set[str] = set()

    for sc in scenarios:
        evidence = extract_evidence({"flow": sc.flow, "verify": sc.verify})
        steps, tools = _step_stats(sc.flow)
        oracles = _oracles_used(sc.verify)
        verify_count = len(sc.verify or [])
        grade = _grade(evidence, verify_count, steps.get("db_query", 0) > 0)

        covers = [str(c) for c in (sc.covers or [])]
        invalid = [c for c in covers if anchors and c not in anchors]
        covered_frs.update(c for c in covers if c in anchors)

        issues: list[str] = []
        if not covers:
            issues.append(ISSUE_MISSING_COVERS)
        if invalid:
            issues.append(ISSUE_INVALID_COVERS)
        if grade == GRADE_SHALLOW:
            issues.append(ISSUE_SHALLOW)
        if grade == GRADE_NO_VERIFY:
            issues.append(ISSUE_NO_VERIFY)
            if steps.get("python"):
                issues.append(ISSUE_PROBE)

        try:
            suite_key = str(Path(sc.path).parent.relative_to(root))
            rel_path = str(Path(sc.path).relative_to(root))
        except ValueError:
            suite_key = Path(sc.path).parent.name
            rel_path = sc.path

        suite = suite_agg.setdefault(suite_key, {
            "key": suite_key,
            "feature": sc.suite.get("feature", "") if sc.suite else "",
            "module": sc.module or "",
            "spec_ref": sc.suite.get("spec_ref", "") if sc.suite else "",
            "spec_version": str(sc.suite.get("spec_version", "") or "") if sc.suite else "",
            "scenarios": 0,
            "covers_tagged": 0,
            "grades": dict.fromkeys(GRADES, 0),
            "scenarios_with_issues": 0,
        })
        suite["scenarios"] += 1
        if covers:
            suite["covers_tagged"] += 1
        suite["grades"][grade] += 1
        if issues:
            suite["scenarios_with_issues"] += 1

        for k, v in steps.items():
            matrix_steps[k] = matrix_steps.get(k, 0) + v
        for k, v in tools.items():
            matrix_tools[k] = matrix_tools.get(k, 0) + v
        for k, v in oracles.items():
            matrix_oracles[k] = matrix_oracles.get(k, 0) + v
        for d in sc.depends_on:
            if d.get("mode") in matrix_depends:
                matrix_depends[d["mode"]] += 1

        rows.append({
            "id": sc.id,
            "title": sc.title,
            "suite": suite_key,
            "module": sc.module or "",
            "path": rel_path,
            "covers": covers,
            "covers_detail": _covers_detail(covers, anchors),
            "invalid_covers": invalid,
            "dimensions": list(sc.dimensions or []),
            "priority": sc.priority,
            "tags": list(sc.tags or []),
            "verify_count": verify_count,
            "evidence": sorted(evidence),
            "grade": grade,
            "issues": issues,
            "doc_summary": _doc_summary(sc.doc or {}),
            "flow_summary": [_step_line(s) for s in (sc.flow or []) if isinstance(s, dict) and s],
            "verify_summary": [_verify_line(v) for v in (sc.verify or []) if isinstance(v, dict)],
            "steps": steps,
            "tools": sorted(tools),
            "oracles": sorted(oracles),
            "depends_on": [{"id": d["id"], "mode": d["mode"]} for d in sc.depends_on],
        })

    grades_total = {g: sum(1 for r in rows if r["grade"] == g) for g in GRADES}
    issue_total: dict[str, int] = {}
    for r in rows:
        for i in r["issues"]:
            issue_total[i] = issue_total.get(i, 0) + 1
    tagged = sum(1 for r in rows if r["covers"])
    anchors_covered = len(covered_frs)

    suites = sorted(suite_agg.values(), key=lambda s: s["key"])
    for s in suites:
        s["covers_rate"] = round(100 * s["covers_tagged"] / s["scenarios"], 1) if s["scenarios"] else 0.0

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "anchors_available": bool(anchors),
        "totals": {
            "scenarios": len(rows),
            "suites": len(suites),
            "covers_tagged": tagged,
            "covers_rate": round(100 * tagged / len(rows), 1) if rows else 0.0,
            "grades": grades_total,
            "issues": issue_total,
            "scenarios_with_issues": sum(1 for r in rows if r["issues"]),
            "anchors_total": len(anchors),
            "anchors_covered": anchors_covered,
            "fr_gaps": (len(anchors) - anchors_covered) if anchors else None,
        },
        "suites": suites,
        "capability_matrix": {
            "steps": dict(sorted(matrix_steps.items(), key=lambda kv: -kv[1])),
            "tools": dict(sorted(matrix_tools.items(), key=lambda kv: -kv[1])),
            "oracles": dict(sorted(matrix_oracles.items(), key=lambda kv: -kv[1])),
            "depends": matrix_depends,
        },
        "scenarios": sorted(rows, key=lambda r: r["id"]),
    }
