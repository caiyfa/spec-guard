"""FR-{功能}-{迭代}-{流水} 命名规范测试（方案 B：注册表锚定解析 + 迭代名自由）。

规范要点：
- 解析 = 右锚流水（最右 \\d{3} 定宽）+ 左锚功能注册表（specs/{模块}/{功能}/ 目录名，
  最长匹配）+ 中段迭代完全自由（含 '-'、'.'、'_'、中文等）
- 迭代代号（changes/{代号}/ 目录名）只受文件系统安全底线约束：
  禁路径分隔符/空白/Windows 保留字符，首字符禁 '.'（防隐藏目录/穿越）；
  2026-08-17、sprint-23、v2.5 均合法
- 基线编号 FR-001 不在解析范围；解析必须携带功能注册表（known_features）
"""

import shutil
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from specstd.schema import (  # noqa: E402
    ITER_CODE_RE, FR_DELTA_ID_RE, parse_fr_delta_id,
    RuleName, RuleLevel,
)
from specstd.conformance import check_conformance  # noqa: E402

from test_specstd.helpers import create_valid_workspace  # noqa: E402

# 模拟功能注册表（真实工作区 specs/{module}/{feature}/ 的二级目录名集合）
_FEATURES = {"person-profile", "person-search", "person-search-v2",
             "eval-360", "exp-tag", "history-inventory"}


class TestParseFrDeltaId:
    """注册表锚定解析。"""

    def test_plain_date_iter(self):
        """常规日期迭代：FR-person-profile-0817-001 正确拆三段。"""
        r = parse_fr_delta_id("FR-person-profile-0817-001", known_features=_FEATURES)
        assert r == {"func": "person-profile", "iter": "0817", "seq": "001"}

    def test_dashed_iter_supported(self):
        """核心能力：迭代名含 '-' 完全支持——2026-08-17 / sprint-23 不再被劈开。"""
        r = parse_fr_delta_id("FR-eval-360-2026-08-17-001", known_features=_FEATURES)
        assert r == {"func": "eval-360", "iter": "2026-08-17", "seq": "001"}
        r2 = parse_fr_delta_id("FR-exp-tag-sprint-23-001", known_features=_FEATURES)
        assert r2 == {"func": "exp-tag", "iter": "sprint-23", "seq": "001"}

    def test_func_prefix_overlap_longest_match(self):
        """同前缀子模块：最长匹配——person-search-v2 完整命中而非拆给 person-search。"""
        r = parse_fr_delta_id("FR-person-search-v2-0817-001", known_features=_FEATURES)
        assert r == {"func": "person-search-v2", "iter": "0817", "seq": "001"}
        r2 = parse_fr_delta_id("FR-person-search-0817-001", known_features=_FEATURES)
        assert r2 == {"func": "person-search", "iter": "0817", "seq": "001"}

    def test_func_with_digits(self):
        """功能名含数字：eval-360 的 360 不误判为迭代。"""
        r = parse_fr_delta_id("FR-eval-360-0817-001", known_features=_FEATURES)
        assert r == {"func": "eval-360", "iter": "0817", "seq": "001"}

    def test_iter_free_form(self):
        """迭代名自由形态：S24 / v2.5 / 2026Q3 / hongbao / 点横线混合均可解析。"""
        for it in ("S24", "v2.5", "2026Q3", "hongbao", "2026_08_17"):
            r = parse_fr_delta_id(f"FR-exp-tag-{it}-001", known_features=_FEATURES)
            assert r is not None and r["iter"] == it, f"{it} 应可解析"

    def test_baseline_fr_not_matched(self):
        """基线编号 FR-001 不是 delta 格式，返回 None。"""
        assert parse_fr_delta_id("FR-001", known_features=_FEATURES) is None

    def test_malformed_not_matched(self):
        """非法形态（流水非 3 位数字 / 缺段 / 缺功能名）返回 None。"""
        assert parse_fr_delta_id("FR-exp-tag-0817-01", known_features=_FEATURES) is None
        assert parse_fr_delta_id("FR-exp-tag-0817", known_features=_FEATURES) is None
        assert parse_fr_delta_id("FR-0817-001", known_features=_FEATURES) is None  # 缺功能段

    def test_missing_iter_segment(self):
        """迭代段缺失（FR-eval-360-001）：rest 无 '功能-' 前缀结构 → None。"""
        assert parse_fr_delta_id("FR-eval-360-001", known_features=_FEATURES) is None

    def test_requires_registry(self):
        """无注册表（known_features=None）无法确定功能边界 → None（解析必须带注册表）。"""
        assert parse_fr_delta_id("FR-eval-360-0817-001") is None
        assert parse_fr_delta_id("FR-person-profile-0817-001") is None

    def test_unregistered_func_rejected(self):
        """功能名不在注册表 → None（迭代碎片会被整体留在 iter 段，func 必须命中）。"""
        assert parse_fr_delta_id("FR-no-such-feat-0817-001", known_features=_FEATURES) is None
        assert parse_fr_delta_id("FR-eval-360-0817-001", known_features={"exp-tag"}) is None


class TestIterCodeSafety:
    """迭代代号文件系统安全底线（替代原白名单——含 '-' 完全合法）。"""

    @pytest.mark.parametrize("code", [
        "0817", "S24", "v2.5", "2026Q3", "hongbao", "sprint_3",
        "2026-08-17", "sprint-23", "tag-enhancement", "2026_08_17",
    ])
    def test_legal_codes(self, code):
        assert ITER_CODE_RE.match(code), f"{code} 应合法（含 '-' 允许）"

    @pytest.mark.parametrize("code", [
        "a/b", "a\\b", "a:b", "a?b", 'a"b', "a<b", "a>b", "a|b", "a*b",
        "..", ".hidden", "sp rint", "a\tb", "",
    ])
    def test_illegal_codes(self, code):
        assert not ITER_CODE_RE.match(code), f"{code} 应非法（路径/空白/保留字符/点开头）"


class TestConformanceDeltaCode:
    """conformance 对 delta 目录代号的强制校验（安全底线语义）。"""

    def test_dashed_delta_code_accepted(self, tmp_path):
        """核心反转：changes/2026-08-17/ 合法，不再报代号类 ERROR。"""
        ws = create_valid_workspace(tmp_path / "ws-dash")
        shutil.move(str(ws / "changes" / "delta001"), str(ws / "changes" / "2026-08-17"))
        report = check_conformance(ws, "test-dash")
        code_errors = [
            f for f in report.findings
            if f.rule == RuleName.STRUCT.value and f.level == RuleLevel.ERROR.value
            and "代号" in f.message
        ]
        assert not code_errors, f"含 '-' 代号应合法: {[f.to_dict() for f in code_errors]}"

    def test_legal_delta_code_passes(self, tmp_path):
        """changes/S24/ 等自由代号不报代号类 STRUCT ERROR。"""
        ws = create_valid_workspace(tmp_path / "ws-legal")
        shutil.move(str(ws / "changes" / "delta001"), str(ws / "changes" / "S24"))
        report = check_conformance(ws, "test-legal")
        code_errors = [
            f for f in report.findings
            if f.rule == RuleName.STRUCT.value and f.level == RuleLevel.ERROR.value
            and "代号" in f.message
        ]
        assert not code_errors, f"合法代号不应报代号错误: {[f.to_dict() for f in code_errors]}"

    def test_hidden_dir_rejected(self, tmp_path):
        """changes/.hidden/ 首字符为点 → STRUCT ERROR。"""
        ws = create_valid_workspace(tmp_path / "ws-hidden")
        (ws / "changes" / ".hidden").mkdir()
        report = check_conformance(ws, "test-hidden")
        code_errors = [
            f for f in report.findings
            if f.rule == RuleName.STRUCT.value and f.level == RuleLevel.ERROR.value
            and "代号" in f.message and ".hidden" in f.message
        ]
        assert code_errors, "点开头的隐藏目录应报代号错误"

    def test_valid_workspace_still_passes(self, tmp_path):
        """合规样例（delta001）保持全 PASS。"""
        ws = create_valid_workspace(tmp_path / "ws-valid")
        report = check_conformance(ws, "test-valid")
        errors = [f for f in report.findings if f.level == RuleLevel.ERROR.value]
        assert not errors, f"合规仓库不应有 ERROR: {[f.to_dict() for f in errors]}"
