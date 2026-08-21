"""引擎离线单测：版本解析 / 期望匹配 / 契约指纹 / T6 校验（不依赖 DB/HTTP）。"""

import os

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engine.versioning import (  # noqa: E402
    MATCH, MINOR_DRIFT, MAJOR_DRIFT,
    parse_version, match_expectation, is_snapshot, VersionError,
    _fingerprint, check_t6,
)


# ══════════════════════════════════════════════════════════
# parse_version
# ══════════════════════════════════════════════════════════

def test_parse_two_segments():
    assert parse_version("1.2") == (1, 2)

def test_parse_single_segment_defaults_minor_zero():
    assert parse_version("2") == (2, 0)

def test_parse_snapshot():
    assert parse_version("0.1") == (0, 1)
    assert is_snapshot("0.3")
    assert not is_snapshot("1.0")

def test_parse_numeric_input():
    assert parse_version(1) == (1, 0)

def test_parse_invalid():
    with pytest.raises(VersionError):
        parse_version("abc")
    with pytest.raises(VersionError):
        parse_version("1.2.3")
    with pytest.raises(VersionError):
        parse_version("")


# ══════════════════════════════════════════════════════════
# match_expectation 矩阵
# ══════════════════════════════════════════════════════════

@pytest.mark.parametrize("expected,actual,status", [
    (None, "1.2", MATCH),          # 未声明期望 → 任意接受
    ("", "1.2", MATCH),
    ("^1", "1.0", MATCH),          # 同主版本
    ("^1", "1.9", MATCH),
    ("^0", "0.1", MATCH),          # 快照期宽容
    ("^0", "0.9", MATCH),
    ("^1", "2.0", MAJOR_DRIFT),    # 主版本不符
    ("^0", "1.0", MAJOR_DRIFT),    # 快照上游已归档
    ("1.2", "1.2", MATCH),         # 精确匹配
    ("1.2", "1.5", MINOR_DRIFT),   # 兼容增强（实际更高）
    ("1.2", "1.0", MAJOR_DRIFT),   # 精确期望高于实际（契约未到位）
    ("1.2", "2.0", MAJOR_DRIFT),
])
def test_match_matrix(expected, actual, status):
    assert match_expectation(expected, actual) == status


# ══════════════════════════════════════════════════════════
# 契约指纹
# ══════════════════════════════════════════════════════════

def test_fingerprint_stable_and_sensitive():
    base = _fingerprint([{"resource": "inv_session", "state": "IN_PROGRESS"}], ["emp", "resp"], ["FR-001"])
    same = _fingerprint([{"state": "IN_PROGRESS", "resource": "inv_session"}], ["resp", "emp"], ["FR-001"])
    assert base == same  # 顺序无关
    diff_produces = _fingerprint([{"resource": "inv_session", "state": "COMPLETED"}], ["emp", "resp"], ["FR-001"])
    assert base != diff_produces
    diff_saves = _fingerprint([{"resource": "inv_session", "state": "IN_PROGRESS"}], ["emp"], ["FR-001"])
    assert base != diff_saves
    diff_covers = _fingerprint([{"resource": "inv_session", "state": "IN_PROGRESS"}], ["emp", "resp"], [])
    assert base != diff_covers


# ══════════════════════════════════════════════════════════
# T6 校验
# ══════════════════════════════════════════════════════════

def test_t6_new_scenario_info():
    assert check_t6("NEW-001", "fp1", "0.1", {})[0] == "INFO"

def test_t6_contract_changed_without_bump_is_error():
    baseline = {"A-001": {"version": "0.1", "fingerprint": "fp_old"}}
    level, msg = check_t6("A-001", "fp_new", "0.1", baseline)
    assert level == "ERROR"
    assert "未 bump" in msg

def test_t6_proper_bump_passes():
    baseline = {"A-001": {"version": "0.1", "fingerprint": "fp_old"}}
    assert check_t6("A-001", "fp_new", "0.2", baseline) is None

def test_t6_redundant_bump_warns():
    baseline = {"A-001": {"version": "0.1", "fingerprint": "fp_same"}}
    assert check_t6("A-001", "fp_same", "0.2", baseline)[0] == "WARN"

def test_t6_unchanged_passes():
    baseline = {"A-001": {"version": "0.1", "fingerprint": "fp_same"}}
    assert check_t6("A-001", "fp_same", "0.1", baseline) is None
