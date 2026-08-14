"""match_expectation / parse_version 属性测试（Hypothesis）。

钉住版本匹配不变量：caret 同主版本恒 MATCH；精确期望三段语义；
空期望恒 MATCH（任何 actual，包括非法字符串——实现上先短路不解析）。
"""
from hypothesis import given, strategies as st

from engine.versioning import (
    MATCH, MINOR_DRIFT, MAJOR_DRIFT, match_expectation, parse_version,
)

version_str = st.integers(0, 99).flatmap(
    lambda major: st.integers(0, 99).map(lambda minor: f"{major}.{minor}")
)


@given(v=version_str)
def test_parse_version_roundtrip(v):
    major, minor = parse_version(v)
    assert f"{major}.{minor}" == v


@given(v=version_str)
def test_caret_matches_same_major(v):
    major = v.split(".")[0]
    assert match_expectation(f"^{major}", v) == MATCH


@given(major=st.integers(0, 99), emin=st.integers(0, 99), amin=st.integers(0, 99))
def test_exact_semantics(major, emin, amin):
    result = match_expectation(f"{major}.{emin}", f"{major}.{amin}")
    if amin == emin:
        assert result == MATCH
    elif amin > emin:
        assert result == MINOR_DRIFT
    else:
        assert result == MAJOR_DRIFT


@given(a=st.text())
def test_empty_expected_matches_anything(a):
    assert match_expectation(None, a) == MATCH
    assert match_expectation("", a) == MATCH
