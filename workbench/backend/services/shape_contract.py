"""shape_contract — API 形状契约分析（T-1037）。

问题：一个 API 被多个场景调用，需要的层级/字段各不相同；映射知识散落在各
消费方 YAML 的插值路径里，生产者响应形状变更只能在运行期断言失败时发现。

本模块零埋点建立「形状事实」：
  数据源 = 执行报告既有落盘面（reports/{EX-xxx}/cases/*.json 的 steps：call
  步骤的 request.method/path + response_body 20KB 留痕 ENG-T04；老报告降级
  body_excerpt）——删掉重建同一结果（确定性派生，图谱红线口径）。

三类发现（口径 2026-08-28 讨论定稿）：
  引用完整性 WARN   消费方插值引用的上游路径在所有历史响应并集中从未出现
                    ——抓幻觉/写错路径，对 Agent 生成的场景是即时价值
  破坏性漂移 WARN   早期 run 存在、最近 3 个 run 全无的「被引用」路径；
                    仅单 run 出现过 → 降级 INFO（条件字段防误报）
  新增字段 INFO     近期新出现的路径（新增放行，只汇总计数不报警）

形状按 API（method+path）聚合而非按场景——正对「一个 API 多个调用方」。
消费面修剪：无人引用的路径变更不报警。重要性 = 写入类目 × 被依赖数 × P0。

纯读派生：不触发执行、不落库；60s 模块级缓存 + refresh 强制重扫。
未来扩展：depends_on 仲裁从版本号升级到形状指纹（二期，动冻结层需评审）。
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from services.scenario_store import scenarios_root

RUNS_TO_SCAN = 15        # 形状基线时间窗（最近 N 个 run）
RECENT_WINDOW = 3        # 「最近」判定窗口（漂移：早期有、最近 3 run 全无）
_CACHE_TTL = 60.0
_cache: dict = {"key": None, "ts": 0.0, "payload": None}

# 插值占位符（与 engine/interpolation.py 同源口径：{{expr}}）
_INTERP = re.compile(r"\{\{([^{}]+)\}\}")


def invalidate_cache():
    _cache.update(key=None, ts=0.0, payload=None)


# ── 形状提取 ──

def shape_of(value, prefix="$", out: dict | None = None) -> dict:
    """递归形状：值 → {路径: 类型名}。数组取元素并集形状（[] 标记层级）。确定性纯函数。"""
    if out is None:
        out = {}
    if isinstance(value, dict):
        out[prefix] = "object"
        for k, v in value.items():
            shape_of(v, f"{prefix}.{k}", out)
    elif isinstance(value, list):
        out[prefix] = "array"
        for v in value:
            shape_of(v, f"{prefix}[]", out)
    elif value is None:
        out.setdefault(prefix, "null")
    else:
        out[prefix] = type(value).__name__
    return out


# ── 场景静态解析 ──

def scenario_saves(sc) -> dict[str, str]:
    """场景 flow 中 call 步骤的 save 变量 → API key（METHOD path）。

    db_query/tool 信封的 save 不是 API 响应形状，不收录（消费引用时跳过）。
    """
    saves: dict[str, str] = {}
    for step in sc.flow or []:
        if isinstance(step, dict) and isinstance(step.get("call"), dict):
            c = step["call"]
            save = c.get("save")
            if save:
                saves[str(save)] = f"{str(c.get('method', 'GET')).upper()} {c.get('path', '')}"
    return saves


def collect_shape_refs(root: Path | None = None) -> list[dict]:
    """全库跨场景形状引用三元组：[{consumer, upstream, api, path}]。

    扫描场景 YAML 原文 {{X.save.a.b}}（engine/interpolation 同源 {{}} 口径），
    按 X 的 flow 静态解析 save→API 落到具体 API；X 未引用 API 响应（db/tool
    save）或场景缺失时不产出。纯读。
    """
    from engine.scenario_loader import load_scenarios
    root = root or scenarios_root()
    refs: list[dict] = []
    try:
        scenarios = load_scenarios(str(root))
    except Exception:
        return []
    saves_map = {s.id: scenario_saves(s) for s in scenarios}
    for sc in scenarios:
        try:
            text = Path(sc.path).read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _INTERP.finditer(text):
            parts = [p.strip() for p in m.group(1).split(".")]
            if "save" not in parts:
                continue
            i = parts.index("save")
            # 跨场景语法 {{上游ID.save.变量名.路径}}：save 变量名在 .save. 之后一段
            upstream = parts[0] if i == 1 else ""
            var = parts[i + 1] if len(parts) > i + 1 else ""
            rel = parts[i + 2:]
            if not upstream or upstream == sc.id or not rel or upstream not in saves_map:
                continue
            api_key = saves_map[upstream].get(var)
            if not api_key:
                continue   # db/tool save 或非 save 引用——不在形状契约范围
            refs.append({"consumer": sc.id, "upstream": upstream,
                         "api": api_key, "path": "$." + ".".join(rel)})
    return refs


# ── 报告扫描 ──

def _reports_root() -> Path:
    from services.scenario_store import _reports_root
    return _reports_root()


def _recent_run_dirs(limit: int = RUNS_TO_SCAN) -> list[tuple[str, Path]]:
    """最近 N 个 run 目录（目录名排序；EX- 与时间戳/agent_ 格式兼容）。"""
    root = _reports_root()
    if not root.is_dir():
        return []
    dirs = [d for d in root.iterdir() if d.is_dir() and (d / "run.json").is_file()]
    dirs.sort(key=lambda d: d.name)
    return [(d.name, d) for d in dirs[-limit:]]


def _case_shapes(case_path: Path) -> dict[str, dict]:
    """case JSON → {(METHOD path): 形状集}（call 步骤；response_body 优先，老报告降级 body_excerpt；截断字符串体诚实舍弃）。"""
    try:
        data = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    shapes: dict[str, dict] = {}
    for step in data.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "call":
            continue
        body = step.get("response_body")
        if body is None:
            body = step.get("body_excerpt")
        if not isinstance(body, (dict, list)):
            continue
        req = step.get("request") or {}
        key = f"{str(req.get('method', 'GET')).upper()} {req.get('path', '')}"
        shapes.setdefault(key, {}).update(shape_of(body))
    return shapes


def collect_api_shapes() -> dict:
    """扫描最近 N 个 run → 形状时间线 {runs: [{run_id, shapes}], n_runs}（同 run 同 API 并集）。"""
    timeline = []
    for run_id, d in _recent_run_dirs():
        try:
            run = json.loads((d / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shapes: dict[str, dict] = {}
        for case in run.get("cases") or []:
            case_file = case.get("file")
            if case_file:
                for key, sh in _case_shapes(d / case_file).items():
                    shapes.setdefault(key, {}).update(sh)
        timeline.append({"run_id": run_id, "shapes": shapes})
    return {"runs": timeline, "n_runs": len(timeline)}


# ── 汇聚分析 ──

def analyze_shape_contract(refresh: bool = False) -> dict:
    """形状契约全景（引用完整性 + 漂移分类 + 重要性标注；60s 缓存）。"""
    key = str((_reports_root(), scenarios_root()))
    now = time.time()
    if (not refresh and _cache["payload"] is not None
            and _cache["key"] == key and now - _cache["ts"] < _CACHE_TTL):
        return _cache["payload"]
    payload = _build()
    _cache.update(key=key, ts=now, payload=payload)
    return payload


def _build() -> dict:
    from engine.scenario_loader import load_scenarios
    from services.scenario_store import list_scenarios

    timeline = collect_api_shapes()
    refs = collect_shape_refs()
    scenarios = load_scenarios(str(scenarios_root()))
    owner_map: dict[str, list[str]] = defaultdict(list)   # api key → 所属场景（写该 API 的场景）
    for sc in scenarios:
        for api_key in scenario_saves(sc).values():
            owner_map[api_key].append(sc.id)
    summaries = {s["id"]: s for s in list_scenarios()}
    dependents: dict[str, int] = defaultdict(int)
    for s in summaries.values():
        for d in s.get("depends_on") or []:
            dependents[d["id"]] += 1

    runs = timeline["runs"]
    base = {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "n_runs": timeline["n_runs"], "apis": [], "findings": []}
    if not runs:
        return base

    recent, older = runs[-RECENT_WINDOW:], runs[:-RECENT_WINDOW]
    union_all: dict[str, dict] = defaultdict(dict)
    for entry in runs:
        for key, sh in entry["shapes"].items():
            union_all[key].update(sh)
    union_recent: dict[str, dict] = defaultdict(dict)
    for entry in recent:
        for key, sh in entry["shapes"].items():
            union_recent[key].update(sh)
    union_older: dict[str, dict] = defaultdict(dict)
    for entry in older:
        for key, sh in entry["shapes"].items():
            union_older[key].update(sh)

    refs_by_api: dict[str, list[dict]] = defaultdict(list)
    for r in refs:
        refs_by_api[r["api"]].append(r)

    findings: list[dict] = []
    api_rows = []
    for key in sorted(set(union_all) | set(refs_by_api)):
        union = union_all.get(key, {})
        api_refs = refs_by_api.get(key, [])
        n_appear = sum(1 for e in runs if key in e["shapes"])

        # ① 引用完整性：引用路径从未在任何历史响应出现
        seen: set[str] = set()
        for r in api_refs:
            if r["path"] in union:
                seen.add(r["path"])
                continue
            if r["path"] in seen:
                continue   # 同路径多消费方只报一条
            seen.add(r["path"])
            consumers = sorted({x["consumer"] for x in api_refs if x["path"] == r["path"]})
            findings.append({
                "type": "unresolved-ref", "level": "WARN", "api": key, "path": r["path"],
                "consumers": consumers,
                "message": f"引用路径 {r['path']} 在 {n_appear} 个历史响应中从未出现（幻觉/写错路径？）",
            })

        # ② 破坏性漂移：早期有、最近全无的「被引用」路径（消费面修剪；单 run 出现降 INFO）
        if union_older.get(key) and union_recent.get(key):
            for p, t in sorted(union_older[key].items()):
                if p in union_recent[key]:
                    continue
                ref_paths = {r["path"] for r in api_refs}
                if p not in ref_paths:
                    continue   # 无人引用 → 不报警（消费面修剪）
                appear_runs = sum(1 for e in runs if p in e["shapes"].get(key, {}))
                findings.append({
                    "type": "removed-path",
                    "level": "WARN" if appear_runs >= 2 else "INFO",
                    "api": key, "path": p, "was_type": t,
                    "consumers": sorted({x["consumer"] for x in api_refs if x["path"] == p}),
                    "message": f"路径 {p}（{t}）曾出现于 {appear_runs} 个 run，最近 {RECENT_WINDOW} 个 run 全部消失",
                })
            # ③ 新增字段（新增放行，只汇总）
            added = sorted(set(union_recent[key]) - set(union_older[key]))
            if added:
                findings.append({
                    "type": "added-paths", "level": "INFO", "api": key, "path": "",
                    "consumers": [],
                    "message": f"近期新增 {len(added)} 个路径（新增放行）：{', '.join(added[:8])}" + ("…" if len(added) > 8 else ""),
                })

        owner_ids = owner_map.get(key, [])
        imp = 0
        cats = set()
        for sid in owner_ids:
            info = summaries.get(sid) or {}
            if info.get("category") in ("producer", "modifier"):
                imp += 1
            if dependents.get(sid, 0) >= 2:
                imp += 1
            if info.get("priority") == "P0":
                imp += 1
            cats.add(info.get("category", ""))
        api_rows.append({
            "api": key, "runs": n_appear, "fields": len(union),
            "refs": len(api_refs),
            "owner_scenarios": owner_ids[:5],
            "importance": min(imp, 3),
            "category": "/".join(sorted(c for c in cats if c)) or "-",
        })

    level_rank = {"WARN": 0, "INFO": 1}
    findings.sort(key=lambda f: (level_rank.get(f["level"], 2), f["api"], f["path"]))
    base["apis"] = api_rows
    base["findings"] = findings
    return base
