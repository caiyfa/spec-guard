"""check_import_cycles — 仓库顶层包 import 依赖环检查（T-976，进 release_check 门禁）。

规则：
- AST 扫描生产代码 .py（排除测试/docs/前端/克隆区），按仓库顶层目录聚合为包节点
  （engine/specstd/sg_core/agent/mcp_server/graph_index/specflow/integrations/
   feedback/systems/workbench/conftest 等）。
- 模块级 import（含顶层 try/except）构成「强依赖图」：出现强连通分量（环）→ FAIL。
- 函数级延迟 import 构成「弱依赖」：不 FAIL，打印为已知回边（供架构演进参考，
  当前已知 workbench↔mcp_server 混合环由 M-A T-970/T-971 收编）。

用法：
    python scripts/check_import_cycles.py        # 独立运行
    python release_check.py                      # 集成运行（④ 环检查）
"""

from __future__ import annotations

import ast
import os
import sys
from collections import defaultdict
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

# 顶层包分组：路径首段 → 节点名；workbench 整体一个节点（backend 为唯一 py 区）
SKIP_DIRS = {"test_engine", "test_specstd", "test_suites", "test_workbench",
             "docs", "node_modules", "__pycache__", ".git", ".zcode", ".agents",
             ".pytest_cache", "scenarios", "systems", "sg_core_workspaces"}
# systems 是被测适配包（按 SPEC_GUARD_SYSTEM 动态加载），conftest/pytest 装配属测试侧
ROOT_FILES = {"conftest", "release_check", "migrate_format_2"}

KNOWN_LAZY_BACKEDGES = {
    ("workbench", "mcp_server"): "lark_binding 等正向挂载工具；M-A T-970/T-971 装配归一后收编",
    ("mcp_server", "workbench"): "M-A 邻区 services（preflight/scenario_store/plan_executor 等）延迟引用",
    ("mcp_server", "sg_core"): "入库流程复用 validate_scenario_content 与 write_draft 三闸通道；M-C T-982 工具收敛时评估校验核心下沉",
    ("sg_core", "specflow"): "attribution 的面试目录布局对齐 iv_dir（防穿越校验单一实现）",
}


def _package_of(rel: str) -> str | None:
    parts = rel.replace("\\", "/").split("/")
    head = parts[0].removesuffix(".py")
    if len(parts) == 1:
        return head if head in ROOT_FILES else None
    if head in SKIP_DIRS or head.startswith("."):
        return None
    return head


def _top_targets(tree: ast.AST) -> set[str]:
    """文件内 import 的顶层目标（a.b.c → a）。"""
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            targets.add(node.module.split(".")[0])
    return targets


def _module_level_targets(tree: ast.AST) -> set[str]:
    """仅模块顶层（含 try/except、函数体之外）的 import 目标。"""
    targets = set()

    def visit(nodes):
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    targets.update(a.name.split(".")[0] for a in node.names)
                elif node.module and node.level == 0:
                    targets.add(node.module.split(".")[0])
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
            elif isinstance(node, (ast.If,)) and not isinstance(node, (ast.FunctionDef,)):
                # if TYPE_CHECKING: 块不算运行时依赖，跳过；普通顶层 if 少见，保守跳过
                continue
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # 函数/类体内的是延迟 import

    visit(tree.body)
    return targets


LOCAL_PKGS = {"engine", "specstd", "sg_core", "agent", "mcp_server", "graph_index",
              "specflow", "integrations", "feedback", "workbench", "scripts",
              "conftest", "release_check", "migrate_format_2"}


def build_dependency_maps() -> tuple[dict, dict]:
    """返回 (模块级强依赖图, 全量依赖图)：{包: set(依赖包)}。"""
    strong: dict[str, set[str]] = defaultdict(set)
    all_edges: dict[str, set[str]] = defaultdict(set)
    for dirpath, dirnames, filenames in os.walk(SG_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(SG_ROOT)
            pkg = _package_of(str(rel))
            if not pkg:
                continue
            try:
                tree = ast.parse(full.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            targets = _top_targets(tree)
            local = {t for t in targets if t in LOCAL_PKGS and t != pkg}
            all_edges[pkg] |= local
            strong[pkg] |= (_module_level_targets(tree) & local)
    return dict(strong), dict(all_edges)


def _scc_failures(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjoo SCC：返回所有 >1 节点的强连通分量（环）。"""
    index_counter = [0]
    stack, on_stack = [], set()
    index, lowlink = {}, {}
    result = []

    def strongconnect(v):
        # 迭代版避免深递归（包数少，直接递归也够）
        index[v] = lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                result.append(sorted(comp))

    for v in graph:
        if v not in index:
            strongconnect(v)
    return result


def check_cycles() -> tuple[int, list[str]]:
    """返回 (阻塞数, 报告行)。纯模块级环=阻塞；函数级回边=提示。"""
    strong, all_edges = build_dependency_maps()
    lines = []
    blockers = 0

    cycles = _scc_failures(strong)
    if cycles:
        blockers += len(cycles)
        lines.append(f"   ✗ 模块级 import 环 {len(cycles)} 个（必须解环）：")
        for c in cycles:
            lines.append(f"     - {' ↔ '.join(c)}")
    else:
        lines.append("   模块级依赖图无环 ✓")

    # 函数级回边：双向都有依赖、但至少一侧只靠函数级延迟 import 维系（非结构性环，
    # 模块级 SCC 不受影响；混合环在此提示）
    lazy = []
    seen = set()
    for pkg, deps in sorted(all_edges.items()):
        for dep in sorted(deps):
            if pkg in all_edges.get(dep, set()) and (pkg, dep) not in seen:
                if dep in strong.get(pkg, set()) and pkg in strong.get(dep, set()):
                    continue  # 双向模块级（SCC 已 FAIL，不重复报）
                seen.add((pkg, dep))
                seen.add((dep, pkg))
                note = KNOWN_LAZY_BACKEDGES.get((pkg, dep)) or KNOWN_LAZY_BACKEDGES.get((dep, pkg))
                tag = f"（{note}）" if note else ""
                lazy.append(f"     - {pkg} ⇄ {dep} 含函数级回边{tag}")
    if lazy:
        lines.append(f"   ⚠ 函数级回边 {len(lazy)} 条（不卡关，架构演进参考）：")
        lines.extend(lazy)
    return blockers, lines


def main():
    blockers, lines = check_cycles()
    print("④ 包依赖环检查（模块级 import）：")
    for ln in lines:
        print(ln)
    return blockers


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
