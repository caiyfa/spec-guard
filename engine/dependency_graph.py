"""场景依赖图（DAG）：建图 / 循环检测 / 依赖闭包 / 拓扑排序 / 版本仲裁。

格式 2.0：
- 上游缺失不再建图期硬崩，记入 orphans（运行时目标场景判 ORPHANED）
- dep_status 记录每条依赖边的版本匹配状态（match/minor_drift/major_drift/orphan）
"""

from engine.versioning import MATCH, MINOR_DRIFT, MAJOR_DRIFT, match_expectation

ORPHAN = "orphan"


class CycleError(Exception):
    pass


class UnknownDependencyError(Exception):
    pass


def detect_cycles(edges: dict) -> list:
    """三色 DFS 收集依赖图中的全部环（T-102：环检测单一事实源）。

    供 scenario_store.validate_dag 等需要「全部环清单」的调用方使用；
    构造路径保持抛 CycleError（第一个环）语义不变。
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in edges}
    stack = []
    cycles = []

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for dep in edges.get(node, ()):
            if dep not in color:
                continue  # 孤儿依赖（上游不存在）不参与环检测
            if color[dep] == GRAY:
                cycle = stack[stack.index(dep):] + [dep]
                cycles.append(cycle)
            if color[dep] == WHITE:
                dfs(dep)
        stack.pop()
        color[node] = BLACK

    for node in edges:
        if color[node] == WHITE:
            dfs(node)
    return cycles


class DependencyGraph:
    def __init__(self, scenarios):
        """scenarios: list[Scenario]（全场景库，依赖解析需要跨模块可见）"""
        self.by_id = {s.id: s for s in scenarios}
        self.edges = {}  # id -> set(上游 id)（仅含存在的上游）
        self.orphans = {}      # consumer_id -> [缺失的上游 id]
        self.dep_status = {}   # consumer_id -> [{id, mode, version, optional, actual, status}]
        exclusive_consumed = set()   # 被至少一个消费者独占的上游
        for s in scenarios:
            statuses = []
            for dep in s.depends_on:
                dep_id = dep["id"]
                actual = self.by_id[dep_id].version if dep_id in self.by_id else None
                if actual is None:
                    status = ORPHAN
                    self.orphans.setdefault(s.id, []).append(dep_id)
                else:
                    status = match_expectation(dep.get("version"), actual)
                    if dep["mode"] == "exclusive":
                        exclusive_consumed.add(dep_id)
                statuses.append({
                    "id": dep_id,
                    "mode": dep["mode"],
                    "version": dep.get("version"),
                    "optional": bool(dep.get("optional")),
                    "actual": actual,
                    "status": status,
                })
            self.dep_status[s.id] = statuses
            self.edges[s.id] = {d["id"] for d in s.depends_on if d["id"] in self.by_id}
        self._detect_cycles()
        # 守卫告警：独占消费意味着上游会被重复执行产生多份数据，无 teardown 则 SIT 数据会堆积
        for sid in sorted(exclusive_consumed):
            if not self.by_id[sid].teardown:
                print(f"[SpecGuard WARN] 场景 {sid} 被独占消费（会多实例执行）但未声明 teardown，"
                  f"注意测试环境数据堆积")

    def drift_report(self):
        """漂移/缺失报告：[{consumer, id, expected, actual, status, optional}]（仅非正常状态）"""
        items = []
        for consumer, statuses in self.dep_status.items():
            for st in statuses:
                if st["status"] in (MAJOR_DRIFT, MINOR_DRIFT, ORPHAN):
                    items.append({
                        "consumer": consumer,
                        "id": st["id"],
                        "expected": st["version"],
                        "actual": st["actual"],
                        "status": st["status"],
                        "optional": st["optional"],
                    })
        return sorted(items, key=lambda x: (x["status"] != ORPHAN, x["consumer"]))

    def _detect_cycles(self):
        """循环检测：发现环时抛出完整环路径（T-102：算法本体收口到 detect_cycles）。"""
        cycles = detect_cycles(self.edges)
        if cycles:
            raise CycleError(f"场景依赖存在循环: {' -> '.join(cycles[0])}")

    def closure(self, target_id):
        """目标场景的依赖闭包（含自身），按拓扑序返回（上游在前）"""
        if target_id not in self.by_id:
            raise UnknownDependencyError(f"未知场景: {target_id}")
        visited, order = set(), []

        def visit(node):
            if node in visited:
                return
            visited.add(node)
            for dep in self.edges.get(node, ()):
                visit(dep)
            order.append(node)

        visit(target_id)
        return order

    def topo_order(self, ids=None):
        """对给定场景集合（默认全图）做拓扑排序"""
        ids = list(ids) if ids else list(self.edges)
        visited, order = set(), []

        def visit(node):
            if node in visited:
                return
            visited.add(node)
            for dep in self.edges.get(node, ()):
                visit(dep)
            order.append(node)

        for sid in ids:
            visit(sid)
        return order

    def upstreams_of(self, target_id):
        """目标场景的上游集合（不含自身），拓扑序"""
        chain = self.closure(target_id)
        return [sid for sid in chain if sid != target_id]
