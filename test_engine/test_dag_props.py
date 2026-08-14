"""detect_cycles 属性测试（Hypothesis）。

钉住环检测不变量：只含前向边（小编号→大编号）的图必无环；
任意无环图叠加自环必被检出。
"""
from hypothesis import given, strategies as st

from engine.dependency_graph import detect_cycles

N = 8
PAIRS = [(i, j) for i in range(N) for j in range(i + 1, N)]  # 28 个前向边位
mask28 = st.lists(st.integers(0, 1), min_size=len(PAIRS), max_size=len(PAIRS))


def _build(mask):
    """按位掩码建前向边图：i < j 才允许有边，结构上保证无环。"""
    edges = {f"n{i}": [] for i in range(N)}
    for (i, j), bit in zip(PAIRS, mask):
        if bit:
            edges[f"n{i}"].append(f"n{j}")
    return edges


@given(mask=mask28)
def test_forward_edges_never_cycle(mask):
    assert detect_cycles(_build(mask)) == []


@given(mask=mask28)
def test_self_loop_always_detected(mask):
    edges = _build(mask)
    edges["n3"].append("n3")
    cycles = detect_cycles(edges)
    assert any("n3" in c for c in cycles)
