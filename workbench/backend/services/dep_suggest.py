"""dep_suggest — 依赖建议引擎（K-046，确定性 · 纯读 · 零副作用）。

补齐「needs 侧提取」这一全库空白：此前无论 Agent 还是人都只能肉眼推理
`{{...}}` 插值该由谁生产，本模块用确定性正则 + 图算法给出建议边：

  needs      扫描 YAML 全文 `{{root.path}}` 插值，取首段 root
             - root 形如场景 ID（PP-RC-001.session.id）→ 跨场景引用，高置信直接建议
             - root 为 save 变量名（{{emp.no}}）         → 变量匹配，中置信建议
             - env.* / 本场景自产 save                  → 排除
  producers  库内场景 + drafts/ 草稿的 save 集合（engine.versioning 同款提取）
  匹配剔除   已是现有/传递依赖、自依赖、会成环（DependencyGraph.closure 预检）

HTTP（routers/drafts.py、routers/scenarios.py）与 MCP（scenario_tools.suggest_deps）
共用本实现——建议只由确定性算法产出，LLM/人只做「要不要采纳」。
"""

import re
from pathlib import Path

import yaml

from engine.dependency_graph import DependencyGraph
from engine.scenario_loader import load_scenarios, _parse_scenario
from engine.versioning import _save_names_from_flow

# 插值表达式（与 scenario_runner.render 同一正则语义）
_INTERP = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# 场景 ID 形态：全大写分段（PP-RC-001 / TL-PREP-001），save 名为小写可区分
_SCENARIO_ID = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)+$")
# 引擎内置命名空间（非 save 变量）
_BUILTIN_ROOTS = {"env"}


class _Node:
    """一个场景/草稿的生产与消费画像。"""

    __slots__ = ("id", "title", "version", "saves", "depends_on_ids",
                 "refs", "is_draft", "filename")

    def __init__(self, sid, title, version, saves, depends_on_ids, refs, is_draft, filename):
        self.id = sid
        self.title = title
        self.version = version
        self.saves = saves                    # set[str] 本场景产出的 save 变量名
        self.depends_on_ids = depends_on_ids  # list[str] 已声明的直接依赖
        self.refs = refs                      # list[str] 插值首段 root（去重前）
        self.is_draft = is_draft
        self.filename = filename              # 草稿文件名（库内场景为相对路径）


def _interp_roots(text: str) -> list[str]:
    """提取全部 {{...}} 插值的首段 root（保持出现顺序，去重）。"""
    roots: list[str] = []
    seen = set()
    for m in _INTERP.finditer(text or ""):
        root = m.group(1).strip().split(".")[0].strip()
        if root and root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def _node_from_text(text: str, is_draft: bool, filename: str) -> "_Node | None":
    """从 YAML 文本构建节点画像；解析失败/无 id 返回 None。"""
    try:
        raw = yaml.safe_load(text) or {}
    except Exception:
        return None
    sid = str(raw.get("id", "") or "")
    if not sid:
        return None
    saves = set(_save_names_from_flow(raw.get("flow")))
    deps = []
    for d in (raw.get("depends_on") or []):
        deps.append(str(d.get("id")) if isinstance(d, dict) else str(d))
    return _Node(
        sid=sid,
        title=str(raw.get("title", "") or ""),
        version=str(raw.get("version", "") or ""),
        saves=saves,
        depends_on_ids=deps,
        refs=_interp_roots(text),
        is_draft=is_draft,
        filename=filename,
    )


def scan_nodes(scenarios_root: Path, drafts_root: "Path | None" = None) -> "list[_Node]":
    """扫描库内场景 + 草稿，构建节点画像列表（纯读）。"""
    nodes: list[_Node] = []
    root = Path(scenarios_root)
    if root.is_dir():
        for f in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
            if f.name.startswith("_"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            node = _node_from_text(text, False, str(f.relative_to(root)).replace("\\", "/"))
            if node:
                nodes.append(node)
    if drafts_root and Path(drafts_root).is_dir():
        known = {n.id for n in nodes}
        for f in sorted(Path(drafts_root).glob("*.yaml")) + sorted(Path(drafts_root).glob("*.yml")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            node = _node_from_text(text, True, f.name)
            if node and node.id not in known:   # 与库内同 id 的草稿视为已入库副本，跳过
                known.add(node.id)
                nodes.append(node)
    return nodes


def _build_graph(scenarios_root: Path, drafts_root: "Path | None") -> "tuple":
    """库内场景 + 草稿并入建图（与 check_dag 同一语义）。

    T-104：建图失败返回 (None, 错误信息)——环预检失效必须显式提示，
    不再静默降级（此前返回 None 后所有成环检查被跳过，建议可能引入环）。
    """
    try:
        scenarios = load_scenarios(str(scenarios_root))
        if drafts_root and Path(drafts_root).is_dir():
            known = {s.id for s in scenarios}
            for f in sorted(Path(drafts_root).glob("*.yaml")) + sorted(Path(drafts_root).glob("*.yml")):
                try:
                    sc = _parse_scenario(str(f), {})
                except Exception:
                    continue
                if sc.id not in known:
                    known.add(sc.id)
                    scenarios.append(sc)
        return DependencyGraph(scenarios), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def suggest_deps(scenarios_root: Path, drafts_root: "Path | None" = None,
                 target_id: str = "", drafts_only: bool = False) -> dict:
    """计算依赖建议。

    target_id   指定时只为该场景/草稿出建议；否则为全部消费者出建议
    drafts_only 仅对草稿出建议（草稿评审页批量视图）

    返回 {ok, suggestions: [{consumer, consumer_title, dep_id, dep_title, dep_version,
                             reason, confidence, kind}], unresolved: {...}}
    """
    nodes = scan_nodes(scenarios_root, drafts_root)
    by_id = {n.id: n for n in nodes}
    graph, graph_error = _build_graph(scenarios_root, drafts_root)

    # 变量 → 生产者索引（同名 save 可能多生产者，全列出让呈现层选择）
    var_producers: "dict[str, list[_Node]]" = {}
    for n in nodes:
        for v in n.saves:
            var_producers.setdefault(v, []).append(n)

    suggestions: list[dict] = []
    unresolved: "dict[str, list[str]]" = {}

    for consumer in nodes:
        if target_id and consumer.id != target_id:
            continue
        if drafts_only and not consumer.is_draft:
            continue

        # 已覆盖的上游（直接 + 传递），无需再建议
        covered = set(consumer.depends_on_ids)
        if graph and consumer.id in graph.by_id:
            try:
                covered |= set(graph.closure(consumer.id))
            except Exception:
                pass

        own = set(consumer.saves) | _BUILTIN_ROOTS
        unresolved_roots: list[str] = []
        seen_deps: set[str] = set()

        for root in consumer.refs:
            if root in own:
                continue
            # ① 跨场景引用：root 即场景 ID → 高置信
            if _SCENARIO_ID.match(root):
                if root == consumer.id or root in covered or root in seen_deps:
                    continue
                dep = by_id.get(root)
                if not dep:
                    unresolved_roots.append(f"{root}（引用场景不存在）")
                    continue
                if graph and consumer.id in graph.by_id and root in graph.by_id:
                    try:
                        if consumer.id in graph.closure(root):
                            continue   # 会成环
                    except Exception:
                        pass
                seen_deps.add(root)
                suggestions.append({
                    "consumer": consumer.id, "consumer_title": consumer.title,
                    "consumer_is_draft": consumer.is_draft,
                    "dep_id": dep.id, "dep_title": dep.title, "dep_version": dep.version,
                    "reason": f"消费了跨场景变量 {{{{{root}.…}}}}",
                    "confidence": "high", "kind": "cross_ref",
                })
                continue
            # ② save 变量匹配：root 是某生产者 save → 中置信
            producers = [p for p in var_producers.get(root, [])
                         if p.id != consumer.id and p.id not in covered and p.id not in seen_deps]
            if not producers:
                if root not in covered and not _SCENARIO_ID.match(root):
                    unresolved_roots.append(root)
                continue
            for dep in producers:
                if graph and consumer.id in graph.by_id and dep.id in graph.by_id:
                    try:
                        if consumer.id in graph.closure(dep.id):
                            continue   # 会成环
                    except Exception:
                        pass
                seen_deps.add(dep.id)
                suggestions.append({
                    "consumer": consumer.id, "consumer_title": consumer.title,
                    "consumer_is_draft": consumer.is_draft,
                    "dep_id": dep.id, "dep_title": dep.title, "dep_version": dep.version,
                    "reason": f"消费了变量 {{{{{root}.…}}}}，{dep.id} 通过 save: {root} 产出",
                    "confidence": "medium", "kind": "var_match",
                })
        if unresolved_roots:
            unresolved[consumer.id] = unresolved_roots

    # 高置信在前，同消费者内按 dep_id 排序
    suggestions.sort(key=lambda s: (s["consumer"], 0 if s["confidence"] == "high" else 1, s["dep_id"]))
    # T-104：建图失败时显式返回 graph_error（环预检失效，前端必须提示不可静默）
    return {"ok": True, "suggestions": suggestions, "unresolved": unresolved,
            "graph_error": graph_error}
