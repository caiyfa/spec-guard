"""scenario_runner.render 插值属性测试（Hypothesis）。

钉住插值不变量：无占位符字符串恒等；完全匹配 {{expr}} 保留类型；
未定义变量诚实抛 KeyError（绝不静默吞掉）。
"""
import pytest
from hypothesis import given, strategies as st

from engine.scenario_runner import render

plain_text = st.text(alphabet=st.characters(blacklist_characters="{}"))


@given(s=plain_text)
def test_no_placeholder_is_identity(s):
    assert render(s, {}) == s


@given(v=st.one_of(st.integers(), st.booleans(),
                   st.floats(allow_nan=False), st.lists(st.integers())))
def test_fullmatch_preserves_type(v):
    out = render("{{a.b}}", {"a": {"b": v}})
    assert out == v
    assert type(out) is type(v)


def test_undefined_variable_raises_keyerror():
    with pytest.raises(KeyError, match="变量未定义"):
        render("{{definitely_missing_key}}", {})
