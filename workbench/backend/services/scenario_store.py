"""场景存储服务：读写 scenarios/**/*.yaml + 解析 DAG 结构。

不修改引擎代码，仅操作 YAML 文件本身。DAG 版本仲裁状态复用引擎 DependencyGraph。

K-025 性能：①CSafeLoader（libyaml 可用时 C 解析，语义一致快 5-10 倍）；
②目录指纹缓存（文件数+最新 mtime）——此前每个请求全量重扫重解析 90+ YAML
（get_dag 甚至解析两遍），场景/ DAG/草稿页加载慢的主因。
"""

import os
import sys
from pathlib import Path
from typing import Optional

import yaml

# SpecGuard 根目录（services/ → backend/ → workbench/ → specguard/）
SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

SCENARIOS_ROOT = SG_ROOT / "scenarios"
REPORTS_ROOT = SG_ROOT / "reports"

_YAML_LOADER = yaml.CSafeLoader if hasattr(yaml, "CSafeLoader") else yaml.SafeLoader


def _fast_load(text: str):
    """K-025：C 解析器（与 safe_load 语义一致）。"""
    return yaml.load(text, Loader=_YAML_LOADER)


def _infer_category(raw: dict) -> str:
    """推断场景资源行为类型：

    - producer:  资源产出型——有 produces 声明或有 teardown（写型场景需清理）
    - modifier:  资源修改型——flow 中有 POST/PUT/DELETE 但无 produces（修改现有资源）
    - query:     查询型——flow 中只有 GET 调用，无写操作
    - validator: 校验消费型——以 verify 断言为主，消费上游资源做验证
    """
    produces = raw.get("produces") or []
    teardown = raw.get("teardown") or []
    flow = raw.get("flow") or []
    verify = raw.get("verify") or []

    # 有 produces 声明或有 teardown → 资源产出型
    if produces or teardown:
        return "producer"

    # 检查 flow 中的 HTTP 方法
    has_write = False
    has_read = False
    for step in flow:
        if isinstance(step, dict) and "call" in step:
            method = (step["call"] or {}).get("method", "GET").upper()
            if method in ("POST", "PUT", "DELETE", "PATCH"):
                has_write = True
            else:
                has_read = True

    if has_write:
        return "modifier"
    if has_read and verify:
        return "validator"   # 有 GET + 断言 = 查询校验
    if has_read:
        return "query"

    return "validator"


def _scan_scenarios() -> list[dict]:
    """扫描全部场景 YAML，返回元信息列表"""
    scenarios = []
    for dirpath, _dirs, filenames in os.walk(SCENARIOS_ROOT):
        suite_meta = {}
        suite_file = os.path.join(dirpath, "_suite.yaml")
        if os.path.isfile(suite_file):
            with open(suite_file, "r", encoding="utf-8") as f:
                suite_meta = _fast_load(f.read()) or {}
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, "r", encoding="utf-8") as f:
                raw = _fast_load(f.read()) or {}
            sid = raw.get("id")
            if not sid:
                continue
            deps_raw = raw.get("depends_on") or []
            deps = []
            for d in deps_raw:
                if isinstance(d, str):
                    deps.append({"id": d, "mode": "shared", "version": None, "optional": False})
                elif isinstance(d, dict) and d.get("id"):
                    deps.append({"id": d["id"], "mode": d.get("mode", "shared"),
                                 "version": d.get("version"),
                                 "optional": bool(d.get("optional"))})
            try:
                rel_path = str(Path(path).relative_to(SG_ROOT))
            except ValueError:
                # 根被重定向的场景（测试/多库场景）：相对场景库根
                rel_path = str(Path(path).relative_to(SCENARIOS_ROOT))
            scenarios.append({
                "id": sid,
                "title": raw.get("title", ""),
                "version": str(raw.get("version", "0.1")),
                "priority": raw.get("priority", "P1"),
                "tags": raw.get("tags", []) or [],
                "depends_on": deps,
                "produces": raw.get("produces", []) or [],
                "has_teardown": bool(raw.get("teardown")),
                "category": _infer_category(raw),
                "covers": (raw.get("doc") or {}).get("covers", []),
                "module": suite_meta.get("module", ""),
                "path": rel_path,
                "abs_path": path,
                # T-320：场景最后更新时间（YAML 文件 mtime，前端场景列表展示）
                "updated_at": _fmt_mtime(os.stat(path).st_mtime),
            })
    return sorted(scenarios, key=lambda s: s["id"])


def _fmt_mtime(mtime_ts: float) -> str:
    """mtime → 'YYYY-MM-DD HH:MM'（执行控制场景列表展示用）。"""
    from datetime import datetime
    return datetime.fromtimestamp(mtime_ts).strftime("%Y-%m-%d %H:%M")


# ══════════════════════════════════════════════════════════
# K-025：目录指纹缓存（编辑/promote 改动 mtime 即自动失效）
# ══════════════════════════════════════════════════════════

def _dir_fingerprint(root: Path) -> tuple:
    """目录指纹：(yaml 文件数, 最新 mtime_ns)。任一文件增删改都会变化。"""
    count = 0
    latest = 0
    for dirpath, _dirs, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith((".yaml", ".yml")):
                count += 1
                mt = os.stat(os.path.join(dirpath, fn)).st_mtime_ns
                if mt > latest:
                    latest = mt
    return (count, latest)


_cache: dict = {"fingerprint": None, "scenarios": None, "graph": None}
# K-xxx：台账投影目标（None=真实 workbench.db；测试重定向场景库时必须一并
# 重定向到 tmp 库，否则扫描源（tmp 场景）与投影目标（真实库）错配造成污染）
_LEDGER_DB_PATH = None


class _DegradedGraph:
    """T-101：场景库存在依赖环时的降级图——仲裁数据置空，仅保 /dag 与历史可用。

    环清单由 get_drift_report 合并返回；修复场景库（保存/编辑）后指纹变化即恢复真图。
    """

    dep_status = {}
    orphans = {}

    def drift_report(self):
        return []


def _scenarios_cached() -> list[dict]:
    fp = _dir_fingerprint(SCENARIOS_ROOT)
    if _cache["fingerprint"] != fp or _cache["scenarios"] is None:
        _cache["fingerprint"] = fp
        _cache["scenarios"] = _scan_scenarios()  # 唯一真实扫描点
        _cache["graph"] = None  # 场景变了，图一并失效
        # K-xxx：扫描结果投影到 SQLite 台账（文件仍是权威；台账供统计/检索，
        # 列表主链路继续走本缓存——文件变化天然被指纹捕获，不做查询层切换）
        try:
            from services import ledger_store
            ledger_store.upsert_scenarios(_cache["scenarios"], db_path=_LEDGER_DB_PATH)
        except Exception:
            pass
    return _cache["scenarios"]


def list_scenarios() -> list[dict]:
    """场景列表（不含 YAML 原文）"""
    return _scenarios_cached()


def _engine_graph():
    """引擎 DependencyGraph（版本仲裁状态 dep_status / orphans / drift_report）。

    K-025：随场景缓存复用——此前每次调用重解析全库（与 _scan_scenarios 双份解析）。
    T-101：建图遇依赖环不抛 500——降级为空仲裁图（环清单由 get_drift_report 合并返回），
    坏图（如 git 拉取带入）不再瘫痪 /dag 与历史页面。
    """
    _scenarios_cached()  # 确保指纹检查 + graph 失效联动
    if _cache["graph"] is None:
        from engine.scenario_loader import load_scenarios
        from engine.dependency_graph import DependencyGraph, CycleError
        try:
            _cache["graph"] = DependencyGraph(load_scenarios(str(SCENARIOS_ROOT)))
        except CycleError as e:
            print(f"[SpecGuard WARN] 场景库存在依赖环，DAG 仲裁降级: {e}")
            _cache["graph"] = _DegradedGraph()
            _cache["cycles"] = validate_dag()["cycles"]
    return _cache["graph"]


def get_dag() -> dict:
    """DAG 图数据：{nodes: [...], edges: [...]}（供 React Flow 消费）

    节点带 version；边带版本仲裁状态（match/minor_drift/major_drift/orphan）。
    """
    scenarios = _scenarios_cached()
    graph = _engine_graph()
    status_map = {
        (consumer, st["id"]): st
        for consumer, statuses in graph.dep_status.items()
        for st in statuses
    }
    nodes = []
    edges = []
    for s in scenarios:
        nodes.append({
            "id": s["id"],
            "data": {
                "label": s["id"],
                "title": s["title"],
                "version": s["version"],
                "priority": s["priority"],
                "tags": s["tags"],
                "has_teardown": s["has_teardown"],
                "category": s["category"],
                "module": s.get("module", ""),  # K-027：DAG 页按模块分组筛选
            },
        })
        for dep in s["depends_on"]:
            st = status_map.get((s["id"], dep["id"]), {})
            edges.append({
                "id": f"{dep['id']}->{s['id']}",
                "source": dep["id"],
                "target": s["id"],
                "animated": dep["mode"] == "exclusive",
                "label": dep["mode"] if dep["mode"] == "exclusive" else "",
                "status": st.get("status", "match"),
                "expected": st.get("version"),
                "actual": st.get("actual"),
            })
    return {"nodes": nodes, "edges": edges}


def get_drift_report() -> dict:
    """漂移/缺失报告（DAG 页与 Dashboard 漂移区块数据源）

    T-101：库存在依赖环时合并返回 cycles 环清单（降级图无仲裁数据）。
    """
    graph = _engine_graph()
    return {"items": graph.drift_report(), "orphans": graph.orphans,
            "cycles": _cache.get("cycles", [])}


def get_scenario_yaml(scenario_id: str) -> Optional[str]:
    """读取场景 YAML 原文"""
    for s in _scenarios_cached():
        if s["id"] == scenario_id:
            with open(s["abs_path"], "r", encoding="utf-8") as f:
                return f.read()
    return None


def _cycle_check_with(scenario_id: str, new_depends_raw) -> Optional[str]:
    """T-101：保存前环预检——以「新 depends_on」替换目标场景后构造全库依赖图。

    - 成环 → 返回错误信息（含环路径），不写盘；
    - 孤儿依赖（上游不存在）不拦截——缺失上游运行时判 ORPHANED（诚实语义）；
    - depends_on 格式非法（mode/version）→ 返回错误（此前静默存盘、建图时才炸）。
    返回 None 表示通过。
    """
    from engine.dependency_graph import DependencyGraph, CycleError
    from engine.scenario_loader import Scenario, ScenarioLoadError, _normalize_depends
    try:
        new_deps = _normalize_depends(new_depends_raw, f"待保存场景 {scenario_id}")
    except ScenarioLoadError as e:
        return str(e)
    scenarios = [
        Scenario(id=s["id"], version=s["version"], depends_on=s["depends_on"],
                 teardown=bool(s["has_teardown"]))
        for s in _scenarios_cached()
    ]
    for sc in scenarios:
        if sc.id == scenario_id:
            sc.depends_on = new_deps
            break
    try:
        DependencyGraph(scenarios)
    except CycleError as e:
        return str(e)
    return None


def save_scenario_yaml(scenario_id: str, content: str) -> dict:
    """保存场景 YAML（校验格式后写入）

    T-101：保存前环预检——新依赖与全库成环时拒绝写盘（此前坏图落盘后
    get_dag 建图 500、pytest scenario_graph fixture 同源崩溃，执行链路瘫痪）。
    """
    # 校验 YAML 语法
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return {"ok": False, "error": f"YAML 语法错误: {e}"}
    if not isinstance(parsed, dict) or not parsed.get("id"):
        return {"ok": False, "error": "YAML 必须包含 id 字段"}
    if parsed["id"] != scenario_id:
        return {"ok": False, "error": f"id 不匹配: 文件声明 {parsed['id']}，期望 {scenario_id}"}
    # 校验 flow/verify 至少有一个
    if not parsed.get("flow") and not parsed.get("verify"):
        return {"ok": False, "error": "flow/verify 均为空，场景不可执行"}
    # T-101：依赖环/格式预检（依赖目标不存在的孤儿允许保存）
    cycle_err = _cycle_check_with(scenario_id, parsed.get("depends_on"))
    if cycle_err:
        return {"ok": False, "error": cycle_err}
    # 写入
    for s in _scenarios_cached():
        if s["id"] == scenario_id:
            with open(s["abs_path"], "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True}
    return {"ok": False, "error": f"场景 {scenario_id} 不存在"}


def validate_dag() -> dict:
    """循环依赖检测（T-102：算法收口到 engine.detect_cycles，删除本地重复 DFS）。

    与引擎构造路径（抛第一个环）行为一致，但返回全部环清单（前端/降级展示用）。
    """
    from engine.dependency_graph import detect_cycles
    scenarios = _scenarios_cached()
    edges = {s["id"]: [d["id"] for d in s["depends_on"]] for s in scenarios}
    cycles = detect_cycles(edges)
    return {"ok": len(cycles) == 0, "cycles": cycles}


def _reports_root() -> Path:
    """报告目录（K-050：工作区 .specguard/reports/ 优先，无工作区回退 SG_ROOT/reports/）。

    此前硬编码 SG_ROOT/reports——多工作区下执行报告落在工作区 .specguard/reports/，
    历史/详情/用例三个读取端全部 404（EX- 任务编号验证时暴露）。
    与 runner._get_reports_root 同一策略。
    """
    try:
        from specstd.workspace import reports_dir
        return reports_dir()
    except Exception:
        return REPORTS_ROOT


def list_reports(limit: int = 20) -> list[dict]:
    """历史运行列表（读 reports/ 目录）

    T-120：断点批次目录（{run_id}-bN）不单独成条——同一任务归并到主任务展示
    （此前 History 页把同一任务拆成 N 条记录）。
    """
    reports_root = _reports_root()
    if not reports_root.is_dir():
        return []
    runs = []
    for d in sorted(reports_root.iterdir(), reverse=True):
        # T-120：跳过批次目录（EX-xxx-b0 等），批次 case 经主任务详情/失败索引读取
        name = d.name
        dash = name.rfind("-b")
        if dash > 0 and name[dash + 2:].isdigit():
            continue
        run_json = d / "run.json"
        if run_json.is_file():
            import json
            with open(run_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            runs.append({
                "run_id": data.get("run_id", d.name),
                "env": data.get("env"),
                "system": data.get("system"),
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "stats": data.get("stats", {}),
                "leases": data.get("leases", {}),
                "dir": str(d),
            })
        if len(runs) >= limit:
            break
    return runs


def _enrich_case_reason(case: dict, root: Path) -> dict:
    """T-310：从 case 文件补充 skip_reason/failure（History 页直接显示「为什么跳过/失败」）。

    run.json 的 case 摘要只有 verdict+id+duration；原因在 cases/*.json（如
    IS-PREP-002_upstream.json 的 skip_reason、failure.message）。摘要已有字段不覆盖。
    """
    f = case.get("file", "")
    if not isinstance(f, str) or not f.endswith(".json"):
        return case
    p = (root / f).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return case
    if not p.is_file():
        return case
    try:
        import json
        with open(p, "r", encoding="utf-8") as fh:
            detail = json.load(fh)
    except Exception:
        return case
    out = dict(case)
    for k in ("skip_reason", "skip_category", "failure"):
        if k in detail and k not in out:
            out[k] = detail[k]
    return out


def get_report(run_id: str) -> Optional[dict]:
    """读取单次运行的 run.json

    T-203：断点分批执行的 case 在 {run_id}-bN 目录——主报告归并 batches 字段
    （T-120 历史归组后的详情可读面，History 主任务下展开批次）。
    T-310：cases 摘要聚合 case 文件里的 skip_reason/failure。
    """
    import json
    root = _reports_root()
    run_json = root / run_id / "run.json"
    if not run_json.is_file():
        return None
    with open(run_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data.get("cases"), list):
        data["cases"] = [_enrich_case_reason(c, root / run_id) for c in data["cases"]]
    batches = []
    for d in sorted(root.glob(f"{run_id}-b*")):
        bjson = d / "run.json"
        if bjson.is_file():
            try:
                with open(bjson, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                bcases = bdata.get("cases", [])
                if isinstance(bcases, list):
                    bcases = [_enrich_case_reason(c, d) for c in bcases]
                batches.append({"dir": d.name, "cases": bcases})
            except Exception:
                continue
    if batches:
        data["batches"] = batches
    return data


def get_case(run_id: str, case_file: str) -> Optional[dict]:
    """读取单场景详情 JSON（含路径穿越守卫，与 api_get_run_log 同级别）。"""
    import json
    reports_root = _reports_root()
    case_path = (reports_root / run_id / case_file).resolve()
    try:
        case_path.relative_to(reports_root.resolve())
    except ValueError:
        return None
    if not case_path.is_file():
        return None
    with open(case_path, "r", encoding="utf-8") as f:
        return json.load(f)
