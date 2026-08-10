"""引擎离线单测：schema_match 结构断言（fuzzy-match-lite，T-501）——不依赖 DB/HTTP。

匹配语义（第三批评估 §6.2 施工规格，Karate-lite 子集，只实现这些、不多做）：
- 类型标记：#string / #number / #boolean / #null；字面值 = 精确相等（==）
- 可选键：##key（键可不存在，存在则按规则匹配）
- 数组模式：#[] <rule>（数组每元素匹配 rule，空数组通过）
- 对象：键集严格匹配（多出未声明键 = 失败）；全部嵌套递归
- 明确不支持：#regex / #? JS 表达式 / #(var) 引用 / #present 等扩展
"""

import os
import sys

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.registry import Registry  # noqa: E402
from engine.schema_match import (  # noqa: E402
    match, oracle_schema_match, register_builtin_oracles,
)


# ══════════════════════════════════════════════════════════
# 类型标记
# ══════════════════════════════════════════════════════════

def test_type_markers_pass():
    spec = {"s": "#string", "n": "#number", "b": "#boolean", "z": "#null"}
    actual = {"s": "文本", "n": 1.5, "b": False, "z": None}
    assert match(spec, actual) is None


def test_number_rejects_bool():
    # Python bool 是 int 子类，JSON 语义下 true 不是 number
    fail = match("#number", True)
    assert fail is not None and "期望 #number" in fail


def test_boolean_rejects_int():
    fail = match("#boolean", 1)
    assert fail is not None and "期望 #boolean" in fail


def test_string_rejects_number():
    fail = match("#string", 42)
    assert fail == "$: 期望 #string，实际 42"


def test_null_rejects_zero():
    fail = match("#null", 0)
    assert fail is not None and "期望 #null" in fail


# ══════════════════════════════════════════════════════════
# 字面值精确相等
# ══════════════════════════════════════════════════════════

def test_literal_equal():
    assert match({"code": 200, "msg": "ok"}, {"code": 200, "msg": "ok"}) is None


def test_literal_mismatch():
    fail = match({"code": 200}, {"code": 500})
    assert fail == "$.code: 期望 200，实际 500"


def test_literal_bool_not_int():
    # True == 1 在 Python 成立，但 JSON 语义类型不同，应判不匹配
    fail = match(True, 1)
    assert fail is not None


def test_literal_list_exact():
    # 字面 list 按精确相等处理（数组模式请用 "#[]" 字符串形式）
    assert match([1, 2], [1, 2]) is None
    assert match([1, 2], [1, 3]) is not None


# ══════════════════════════════════════════════════════════
# 可选键（## 前缀）
# ══════════════════════════════════════════════════════════

def test_optional_key_absent_pass():
    assert match({"a": "#number", "##b": "#string"}, {"a": 1}) is None


def test_optional_key_present_match():
    assert match({"a": "#number", "##b": "#string"}, {"a": 1, "b": "x"}) is None


def test_optional_key_present_mismatch():
    fail = match({"a": "#number", "##b": "#string"}, {"a": 1, "b": 2})
    assert fail is not None and "$.b" in fail and "期望 #string" in fail


# ══════════════════════════════════════════════════════════
# 数组模式（#[]）
# ══════════════════════════════════════════════════════════

def test_array_pattern_pass():
    assert match("#[] #string", ["a", "b", "c"]) is None


def test_array_pattern_empty_pass():
    assert match("#[] #number", []) is None


def test_array_pattern_element_fail():
    fail = match("#[] #string", ["a", 42])
    assert fail == "$[1]: 期望 #string，实际 42"


def test_array_pattern_rejects_non_list():
    fail = match("#[] #string", "abc")
    assert fail is not None and "期望数组" in fail


# ══════════════════════════════════════════════════════════
# 嵌套递归 + 失败消息路径定位
# ══════════════════════════════════════════════════════════

def test_nested_recursive_pass():
    spec = {"data": {"list": "#[] #number", "meta": {"total": "#number", "##extra": "#null"}}}
    actual = {"data": {"list": [1, 2], "meta": {"total": 2}}}
    assert match(spec, actual) is None


def test_failure_path_locates_field():
    spec = {"data": {"list": "#[] #string"}}
    actual = {"data": {"list": ["ok", "ok", 42]}}
    assert match(spec, actual) == "$.data.list[2]: 期望 #string，实际 42"


def test_failure_path_nested_dict():
    spec = {"data": {"meta": {"total": "#number"}}}
    actual = {"data": {"meta": {"total": "2"}}}
    assert match(spec, actual) == "$.data.meta.total: 期望 #number，实际 '2'"


# ══════════════════════════════════════════════════════════
# 键集严格（结构漂移检测核心语义）
# ══════════════════════════════════════════════════════════

def test_extra_key_fails():
    fail = match({"a": "#number"}, {"a": 1, "b": 2})
    assert fail is not None and "多出未声明键" in fail and "'b'" in fail


def test_missing_required_key_fails():
    fail = match({"a": "#number", "b": "#string"}, {"a": 1})
    assert fail is not None and "$.b" in fail and "缺少必需键" in fail


def test_non_dict_actual_fails():
    fail = match({"a": "#number"}, [1, 2])
    assert fail is not None and "期望对象" in fail


# ══════════════════════════════════════════════════════════
# 明确不支持的扩展标记
# ══════════════════════════════════════════════════════════

def test_unsupported_marker_fails_clearly():
    for marker in ("#regex \\d+", "#present", "#? _ > 0"):
        fail = match(marker, "x")
        assert fail is not None and "不支持的 schema 标记" in fail, marker


# ══════════════════════════════════════════════════════════
# oracle 包装（of 解析 / U-1 取值 / 插值 / 注册）
# ══════════════════════════════════════════════════════════

def _ns_resp():
    return {"resp": {"status": 200, "json": {"code": 200, "data": {"id": 5, "name": "张三"}}}}


def test_oracle_default_of_resp():
    params = {"spec": {"code": 200, "data": {"id": "#number", "name": "#string"}}}
    oracle_schema_match(params, None, _ns_resp(), None)  # 不抛即通过


def test_oracle_explicit_of():
    ns = {"createResp": {"json": {"id": 1}}}
    oracle_schema_match({"of": "createResp", "spec": {"id": "#number"}}, None, ns, None)


def test_oracle_bare_value_passthrough():
    # U-1 语义：of 指向非 call 产出（无 json 键的 dict / 裸值）时直通
    ns = {"payload": {"a": 1}}
    oracle_schema_match({"of": "payload", "spec": {"a": "#number"}}, None, ns, None)


def test_oracle_missing_target_raises():
    with pytest.raises(AssertionError, match="找不到断言目标变量: resp"):
        oracle_schema_match({"spec": {"a": "#number"}}, None, {}, None)


def test_oracle_missing_spec_raises():
    with pytest.raises(AssertionError, match="缺少 spec"):
        oracle_schema_match({}, None, _ns_resp(), None)


def test_oracle_failure_message_has_path():
    spec = {"code": "#number", "data": {"id": "#string", "name": "#string"}}
    with pytest.raises(AssertionError, match=r"schema 不匹配.*\$\.data\.id"):
        oracle_schema_match({"spec": spec}, None, _ns_resp(), None)


def test_oracle_params_render_interpolation():
    ns = _ns_resp()
    ns["expectCode"] = 200
    params = {"spec": {"code": "{{expectCode}}", "data": {"id": "#number", "name": "#string"}}}
    oracle_schema_match(params, None, ns, None)


def test_register_builtin_oracles():
    reg = Registry()
    register_builtin_oracles(reg)
    assert reg.get_oracle("schema_match") is oracle_schema_match
