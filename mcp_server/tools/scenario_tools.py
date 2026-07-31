"""scenario_tools — 场景列表 / 读取 / ID 分配 / DAG 预演。

工具：
  list_scenarios: 列出全部场景
  read_scenario: 读取单个场景 YAML
  next_scenario_id: 获取下一可用场景 ID
  check_dag: DAG 预演（K-021③：拓扑序/环/DRIFT/孤例，含草稿并入）
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.format_spec import get_next_scenario_id  # noqa: E402

SCENARIOS_ROOT = SG_ROOT / "scenarios"

TOOLS = [
    Tool(
        name="list_scenarios",
        description="列出 SpecGuard 仓库的全部场景（扫描 scenarios/ 目录，返回 ID/标题/标签/模块）",
        inputSchema={"type": "object", "properties": {}}
    ),
    Tool(
        name="read_scenario",
        description="读取单个场景的 YAML 内容（根据场景 ID 查找文件）",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "场景 ID（如 PP-RC-001）"}
            },
            "required": ["id"]
        }
    ),
    Tool(
        name="next_scenario_id",
        description="获取下一可用的场景 ID（扫描已有 ID，返回下一序号）",
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "模块前缀（如 PP, IS, EV）"},
                "type_abbr": {"type": "string", "description": "类型缩写（如 RC, SNAP, PERM）"}
            },
            "required": ["prefix", "type_abbr"]
        }
    ),
    Tool(
        name="check_dag",
        description="DAG 预演：对场景库（可选并入 drafts/ 草稿）建依赖图，返回拓扑执行序、"
                    "循环依赖、DRIFT/ORPHANED 版本仲裁报告、孤例清单。"
                    "入库前必查——多场景批量生成后用它确认依赖拓扑正确、无环、无悬空依赖。",
        inputSchema={
            "type": "object",
            "properties": {
                "include_drafts": {"type": "boolean",
                                   "description": "是否并入当前工作区 drafts/ 草稿（默认 true——生成期预演）"},
                "focus": {"type": "string",
                          "description": "可选：只输出指定场景的依赖闭包（上游链）与下游依赖者"}
            }
        }
    ),
    Tool(
        name="run_scenario",
        description="试执行场景（真实环境联网调用，会产生真实测试数据）：按依赖闭包执行"
                    "场景库中的场景或 drafts/ 草稿，返回闭包内逐场景 verdict、失败原因与报告目录。"
                    "用途：生成/修改场景后的执行验证闭环（validate 只查格式，run 才验证真实行为）。"
                    "执行前请确认用户意图；失败时用 read_run_report 深入归因。",
        inputSchema={
            "type": "object",
            "properties": {
                "scenario_id": {"type": "string",
                                "description": "场景库中的场景 ID（与 draft 二选一）"},
                "draft": {"type": "string",
                          "description": "drafts/ 草稿文件名（如 TL-RC-001.yaml，与 scenario_id 二选一）"},
                "env": {"type": "string", "description": "目标环境（默认 sit）"},
                "strict_deps": {"type": "boolean", "description": "严格依赖模式（默认 false）"}
            }
        }
    ),
    Tool(
        name="edit_dependency",
        description="编排场景依赖边（K-027 补全 Agent 的 DAG 编排能力）：给库内场景添加/移除 "
                    "depends_on 条目（文本外科手术，保留 YAML 注释）。depends_on 写在【下游消费者】身上——"
                    "add 时 scenario_id=下游、dep_id=上游。自带守卫：自依赖拒绝、目标不存在拒绝、"
                    "循环依赖 409。版本期望自动按上游当前版本推导 ^主版本（推荐语义）。",
        inputSchema={
            "type": "object",
            "properties": {
                "scenario_id": {"type": "string",
                                "description": "下游场景 ID（depends_on 写在它身上）"},
                "action": {"type": "string", "enum": ["add", "remove"],
                           "description": "add=添加依赖边 / remove=移除依赖边"},
                "dep_id": {"type": "string",
                           "description": "上游场景 ID（被依赖方）"},
                "mode": {"type": "string", "enum": ["shared", "exclusive"],
                         "description": "依赖模式（默认 shared 只读共享；写型消费用 exclusive）",
                         "default": "shared"}
            },
            "required": ["scenario_id", "action", "dep_id"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "list_scenarios":
        return _handle_list_scenarios(arguments)
    elif name == "read_scenario":
        return _handle_read_scenario(arguments)
    elif name == "next_scenario_id":
        return _handle_next_scenario_id(arguments)
    elif name == "check_dag":
        return _handle_check_dag(arguments)
    elif name == "run_scenario":
        return _handle_run_scenario(arguments)
    elif name == "edit_dependency":
        return _handle_edit_dependency(arguments)
    return []


def _handle_list_scenarios(arguments: dict) -> list[TextContent]:
    import yaml

    scenarios = []
    for yaml_file in sorted(SCENARIOS_ROOT.rglob("*.yaml")) + sorted(SCENARIOS_ROOT.rglob("*.yml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            continue
        sid = raw.get("id", "")
        if not sid:
            continue
        rel = str(yaml_file.relative_to(SCENARIOS_ROOT)).replace("\\", "/")
        scenarios.append({
            "id": sid,
            "title": raw.get("title", ""),
            "tags": raw.get("tags", []),
            "module": rel.split("/")[0] if "/" in rel else "",
            "path": rel,
        })

    return [TextContent(type="text", text=json.dumps(scenarios, ensure_ascii=False, indent=2))]


def _handle_read_scenario(arguments: dict) -> list[TextContent]:
    import yaml

    sid = arguments.get("id", "")
    if not sid:
        return [TextContent(type="text", text="错误：缺少 id 参数")]

    for yaml_file in SCENARIOS_ROOT.rglob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if raw.get("id") == sid:
                content = yaml_file.read_text(encoding="utf-8")
                return [TextContent(type="text", text=content)]
        except Exception:
            continue

    return [TextContent(type="text", text=f"错误：场景不存在: {sid}")]


def _handle_next_scenario_id(arguments: dict) -> list[TextContent]:
    prefix = arguments.get("prefix", "")
    type_abbr = arguments.get("type_abbr", "")
    if not prefix or not type_abbr:
        return [TextContent(type="text", text="错误：缺少 prefix 或 type_abbr 参数")]

    result = get_next_scenario_id(prefix, type_abbr)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


def _handle_check_dag(arguments: dict) -> list[TextContent]:
    """DAG 预演（K-021③）：场景库 + 可选并入 drafts/ 草稿建图。

    只读校验（dependency_graph 纯内存建图），不写任何文件。
    草稿节点经 engine.scenario_loader._parse_scenario 归一化（与入库后同一语义），
    解析失败的草稿记入 load_errors 而非中断——预演目的就是暴露问题。
    """
    from engine.dependency_graph import DependencyGraph, CycleError
    from engine.scenario_loader import load_scenarios, _parse_scenario

    include_drafts = arguments.get("include_drafts", True)
    focus = str(arguments.get("focus", "") or "")

    result: dict = {"ok": True}
    try:
        scenarios = load_scenarios(str(SCENARIOS_ROOT))
    except Exception as e:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": f"场景库加载失败: {e}"}, ensure_ascii=False, indent=2))]

    result["scenario_count"] = len(scenarios)
    draft_ids: list[str] = []
    load_errors: list[str] = []
    duplicates: list[str] = []

    if include_drafts:
        try:
            from specstd.workspace import drafts_dir
            d = drafts_dir()
            if d.is_dir():
                known = {s.id for s in scenarios}
                for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
                    try:
                        sc = _parse_scenario(str(f), {})
                    except Exception as e:
                        load_errors.append(f"{f.name}: {e}")
                        continue
                    if sc.id in known:
                        duplicates.append(sc.id)
                    known.add(sc.id)
                    draft_ids.append(sc.id)
                    scenarios.append(sc)
        except Exception as e:
            load_errors.append(f"drafts 目录读取失败: {e}")

    result["draft_count"] = len(draft_ids)
    result["drafts_included"] = draft_ids
    if load_errors:
        result["load_errors"] = load_errors
    if duplicates:
        result["duplicates"] = duplicates
        result["ok"] = False

    try:
        graph = DependencyGraph(scenarios)
    except CycleError as e:
        result["ok"] = False
        result["cycles"] = [str(e)]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    # 漂移/孤例报告
    drift = graph.drift_report()
    result["drift"] = drift
    result["orphans"] = graph.orphans
    if drift or graph.orphans:
        result["ok"] = False

    if focus:
        if focus not in graph.by_id:
            result["ok"] = False
            result["error"] = f"focus 场景不存在: {focus}"
        else:
            # 下游依赖者（谁依赖了 focus）
            dependents = sorted(sid for sid, ups in graph.edges.items() if focus in ups)
            result["focus"] = {
                "id": focus,
                "upstream_chain": graph.upstreams_of(focus),
                "dependents": dependents,
                "dep_status": graph.dep_status.get(focus, []),
            }
    else:
        result["topo_order"] = graph.topo_order()
        result["edges"] = {sid: sorted(ups) for sid, ups in sorted(graph.edges.items()) if ups}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


def _handle_run_scenario(arguments: dict) -> list[TextContent]:
    """试执行场景（K-021④：执行验证闭环）。

    复用 plan_executor 的运行时装配（registry/env/token/db/graph）；
    草稿经 _parse_scenario 归一化后重建图（与入库后同一依赖语义）。
    真实环境联网调用——同步执行（工具本身已在独立线程中运行）。
    """
    import os
    from datetime import datetime

    sid = str(arguments.get("scenario_id", "") or "")
    draft = str(arguments.get("draft", "") or "")
    env_name = str(arguments.get("env", "") or "sit")
    strict_deps = bool(arguments.get("strict_deps", False))

    if bool(sid) == bool(draft):
        return [TextContent(type="text", text="错误：scenario_id 与 draft 必须二选一")]

    from services.plan_executor import _setup_runtime
    from services.draft_promote import _scenarios_root
    from engine.dependency_graph import DependencyGraph, CycleError
    from engine.scenario_loader import _parse_scenario
    from engine.scenario_runner import RunContext, run_single, run_teardowns
    from specstd.workspace import get_active_workspace, specguard_dir

    scenarios_root = _scenarios_root()
    if not scenarios_root.is_dir():
        return [TextContent(type="text", text=f"错误：场景库目录不存在: {scenarios_root}")]

    ws = get_active_workspace()
    system = (ws.system if ws else "") or os.environ.get("SPEC_GUARD_SYSTEM", "tdm")

    try:
        env_config, db, registry, token_provider, graph = _setup_runtime(
            system, env_name, scenarios_root, strict_deps)
    except Exception as e:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": f"运行时装配失败（环境 {env_name} 可达性/配置）: {e}"},
            ensure_ascii=False, indent=2))]

    # 草稿并入图（重建 DependencyGraph——dep_status/edges 在建图时计算）
    target_id = sid
    if draft:
        if "/" in draft or "\\" in draft or ".." in draft:
            return [TextContent(type="text", text=f"错误：非法草稿文件名: {draft}")]
        try:
            from specstd.workspace import drafts_dir
            f = drafts_dir() / draft
        except Exception:
            return [TextContent(type="text", text="错误：无激活工作区，无法定位 drafts/")]
        if not f.is_file():
            return [TextContent(type="text", text=f"错误：草稿不存在: {draft}")]
        try:
            sc = _parse_scenario(str(f), {})
            graph = DependencyGraph(list(graph.by_id.values()) + [sc])
            target_id = sc.id
        except CycleError as e:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error": f"并入草稿后检测到循环依赖: {e}"},
                ensure_ascii=False, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error": f"草稿解析失败: {e}"}, ensure_ascii=False, indent=2))]

    if target_id not in graph.by_id:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": f"场景不存在: {target_id}"}, ensure_ascii=False, indent=2))]

    # 运行上下文（报告落盘到工作区 .specguard/reports/）
    run_id = "agent_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        run_dir = specguard_dir(workspace_root=ws.root) / "reports" / run_id if ws else None
    except Exception:
        run_dir = None
    if run_dir is None:
        run_dir = SG_ROOT / "reports" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rctx = RunContext(registry=registry, env_config=env_config,
                      token_provider=token_provider, graph=graph,
                      run_dir=str(run_dir), db=db, strict_deps=strict_deps)

    scenario = graph.by_id[target_id]
    try:
        record = run_single(scenario, rctx)
        run_teardowns(rctx)
    except Exception as e:
        return [TextContent(type="text", text=json.dumps(
            {"ok": False, "error": f"执行异常: {e}", "report_dir": str(run_dir)},
            ensure_ascii=False, indent=2))]
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    # 闭包内全部记录（上游 + 目标），verdict 分布一目了然
    records = []
    for r in rctx.records:
        item = {"scenario_id": r.scenario_id, "verdict": r.verdict,
                "duration_ms": getattr(r, "duration_ms", 0)}
        if r.verdict == "FAIL" and getattr(r, "failure", None):
            item["error"] = str(r.failure.get("message", ""))[:500]
        elif getattr(r, "skip_reason", ""):
            item["reason"] = r.skip_reason
        records.append(item)

    out = {
        "ok": record.verdict == "PASS",
        "target": target_id,
        "verdict": record.verdict,
        "env": env_name,
        "records": records,
        "report_dir": str(run_dir),
        "note": "validate 查格式，run 验证真实行为；FAIL 时用 read_run_report 归因",
    }
    if record.verdict == "FAIL" and getattr(record, "failure", None):
        out["error"] = str(record.failure.get("message", ""))[:1000]
    elif getattr(record, "skip_reason", ""):
        out["reason"] = record.skip_reason

    return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

def _handle_edit_dependency(arguments: dict) -> list[TextContent]:
    """编排依赖边（K-027：deps_editor 文本外科手术 + 服务端守卫）。

    与 routers/scenarios.py 的 /deps 端点同一语义（自依赖/存在性/环校验），
    供 Agent 直接编排库内场景 DAG——此前只能给新草稿声明 depends_on，
    已入库场景的依赖边只能在画布上手工连线。
    """
    scenario_id = str(arguments.get("scenario_id", "") or "")
    action = str(arguments.get("action", "") or "")
    dep_id = str(arguments.get("dep_id", "") or "")
    mode = str(arguments.get("mode", "") or "shared")

    if not scenario_id or not dep_id:
        return [TextContent(type="text", text="错误：缺少 scenario_id 或 dep_id 参数")]
    if action not in ("add", "remove"):
        return [TextContent(type="text", text=f"错误：action 非法: {action}（仅支持 add/remove）")]
    if mode not in ("shared", "exclusive"):
        return [TextContent(type="text", text=f"错误：mode 非法: {mode}（仅支持 shared/exclusive）")]
    if scenario_id == dep_id:
        return [TextContent(type="text", text="错误：不允许自依赖")]

    from services import deps_editor, scenario_store

    scenarios = {s["id"]: s for s in scenario_store.list_scenarios()}
    if scenario_id not in scenarios:
        return [TextContent(type="text", text=f"错误：场景 {scenario_id} 不存在")]
    if action == "add" and dep_id not in scenarios:
        return [TextContent(type="text", text=f"错误：依赖目标 {dep_id} 不存在")]

    if action == "add":
        # 环校验：dep 的依赖闭包中若已含本场景，新增边将成环
        from engine.dependency_graph import DependencyGraph
        from engine.scenario_loader import load_scenarios
        graph = DependencyGraph(load_scenarios(str(SCENARIOS_ROOT)))
        if scenario_id in graph.closure(dep_id):
            return [TextContent(type="text", text=json.dumps({
                "ok": False, "error_code": "cycle",
                "error": f"会形成循环依赖: {scenario_id} → {dep_id} → … → {scenario_id}",
            }, ensure_ascii=False, indent=2))]
        try:
            deps_editor.add_dep(
                scenarios[scenario_id]["abs_path"], dep_id, mode,
                scenarios[dep_id]["version"])
        except deps_editor.DepsEditError as e:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error_code": "edit_failed", "error": str(e)},
                ensure_ascii=False, indent=2))]
    else:
        try:
            deps_editor.remove_dep(scenarios[scenario_id]["abs_path"], dep_id)
        except deps_editor.DepsEditError as e:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error_code": "edit_failed", "error": str(e)},
                ensure_ascii=False, indent=2))]

    # 编辑后返回最新 depends_on（文件 mtime 变化 → 场景缓存自动失效重扫）
    updated = {s["id"]: s for s in scenario_store.list_scenarios()}[scenario_id]
    return [TextContent(type="text", text=json.dumps({
        "ok": True,
        "scenario_id": scenario_id,
        "action": action,
        "dep_id": dep_id,
        "depends_on": updated["depends_on"],
        "note": "版本期望已按上游当前版本自动推导（^主版本）；"
                "建议用 check_dag 复核整体拓扑，validate 复核该场景格式",
    }, ensure_ascii=False, indent=2))]
