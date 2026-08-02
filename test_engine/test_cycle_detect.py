"""detect_cycles 环检测单一事实源测试（T-102）。

验证：
1. 无环 → 空清单
2. 单环 → 收集完整环路径
3. 多环 → 全部收集（scenario_store.validate_dag 消费）
4. DependencyGraph 构造仍抛 CycleError（行为等价，不回归）
"""

import pytest

from engine.dependency_graph import DependencyGraph, CycleError, detect_cycles


class TestDetectCycles:
    def test_no_cycle(self):
        edges = {"A": ["B"], "B": [], "C": ["A"]}
        assert detect_cycles(edges) == []

    def test_single_cycle(self):
        edges = {"A": ["B"], "B": ["C"], "C": ["A"]}
        cycles = detect_cycles(edges)
        assert len(cycles) == 1
        assert cycles[0][0] == cycles[0][-1]
        assert set(cycles[0]) == {"A", "B", "C"}

    def test_multiple_cycles_collected(self):
        # 两个独立环：A↔B 与 C↔D
        edges = {"A": ["B"], "B": ["A"], "C": ["D"], "D": ["C"]}
        cycles = detect_cycles(edges)
        assert len(cycles) == 2
        for c in cycles:
            assert c[0] == c[-1]

    def test_orphan_edges_ignored(self):
        # 依赖不存在的节点（孤儿）不构成环
        edges = {"A": ["GHOST"], "B": ["A"]}
        assert detect_cycles(edges) == []

    def test_graph_still_raises_first_cycle(self):
        """DependencyGraph 构造语义不回归：有环仍抛 CycleError（含环路径）。"""
        from engine.scenario_loader import Scenario
        scenarios = [
            Scenario(id="A", depends_on=[{"id": "B", "mode": "shared"}]),
            Scenario(id="B", depends_on=[{"id": "A", "mode": "shared"}]),
        ]
        with pytest.raises(CycleError, match="A -> B -> A"):
            DependencyGraph(scenarios)
