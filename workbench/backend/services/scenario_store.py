"""场景存储服务：读写 scenarios/**/*.yaml + 解析 DAG 结构。

不修改引擎代码，仅操作 YAML 文件本身。DAG 版本仲裁状态复用引擎 DependencyGraph。
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
                suite_meta = yaml.safe_load(f) or {}
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
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
                "path": str(Path(path).relative_to(SG_ROOT)),
                "abs_path": path,
            })
    return sorted(scenarios, key=lambda s: s["id"])


def list_scenarios() -> list[dict]:
    """场景列表（不含 YAML 原文）"""
    return _scan_scenarios()


def _engine_graph():
    """引擎 DependencyGraph（版本仲裁状态 dep_status / orphans / drift_report）"""
    from engine.scenario_loader import load_scenarios
    from engine.dependency_graph import DependencyGraph
    return DependencyGraph(load_scenarios(str(SCENARIOS_ROOT)))


def get_dag() -> dict:
    """DAG 图数据：{nodes: [...], edges: [...]}（供 React Flow 消费）

    节点带 version；边带版本仲裁状态（match/minor_drift/major_drift/orphan）。
    """
    scenarios = _scan_scenarios()
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
    """漂移/缺失报告（DAG 页与 Dashboard 漂移区块数据源）"""
    graph = _engine_graph()
    return {"items": graph.drift_report(), "orphans": graph.orphans}


def get_scenario_yaml(scenario_id: str) -> Optional[str]:
    """读取场景 YAML 原文"""
    for s in _scan_scenarios():
        if s["id"] == scenario_id:
            with open(s["abs_path"], "r", encoding="utf-8") as f:
                return f.read()
    return None


def save_scenario_yaml(scenario_id: str, content: str) -> dict:
    """保存场景 YAML（校验格式后写入）"""
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
    # 写入
    for s in _scan_scenarios():
        if s["id"] == scenario_id:
            with open(s["abs_path"], "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True}
    return {"ok": False, "error": f"场景 {scenario_id} 不存在"}


def validate_dag() -> dict:
    """循环依赖检测（三色 DFS）"""
    scenarios = _scan_scenarios()
    graph = {s["id"]: [d["id"] for d in s["depends_on"]] for s in scenarios}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {sid: WHITE for sid in graph}
    cycles = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for nb in graph.get(node, []):
            if nb not in color:
                continue
            if color[nb] == GRAY:
                cycle_start = path.index(nb)
                cycles.append(path[cycle_start:] + [nb])
            elif color[nb] == WHITE:
                dfs(nb, path)
        path.pop()
        color[node] = BLACK

    for sid in graph:
        if color[sid] == WHITE:
            dfs(sid, [])

    return {"ok": len(cycles) == 0, "cycles": cycles}


def list_reports(limit: int = 20) -> list[dict]:
    """历史运行列表（读 reports/ 目录）"""
    if not REPORTS_ROOT.is_dir():
        return []
    runs = []
    for d in sorted(REPORTS_ROOT.iterdir(), reverse=True):
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


def get_report(run_id: str) -> Optional[dict]:
    """读取单次运行的 run.json"""
    import json
    run_dir = REPORTS_ROOT / run_id
    run_json = run_dir / "run.json"
    if not run_json.is_file():
        return None
    with open(run_json, "r", encoding="utf-8") as f:
        return json.load(f)


def get_case(run_id: str, case_file: str) -> Optional[dict]:
    """读取单场景详情 JSON"""
    import json
    case_path = REPORTS_ROOT / run_id / case_file
    if not case_path.is_file():
        return None
    with open(case_path, "r", encoding="utf-8") as f:
        return json.load(f)
