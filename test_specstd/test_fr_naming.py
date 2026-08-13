"""FR-{功能}-{迭代}-{流水} 命名规范测试（方案 A 终版：双右锚 + 迭代命名限制）。

规范要点：
- 流水恒为最右段 \\d{3}、迭代恒为右起第二段（单段，禁 '-'），
  功能名为剩余前缀整体左取——功能名任意含 '-'、前缀重叠免疫
- 迭代代号白名单：字母/数字/点/下划线，禁 '-'（S24/v2.5/2026Q3 合法，
  2026-08-17 非法）——delta 目录创建与 conformance 双点强制
"""

import shutil
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.schema import (  # noqa: E402
    ITER_CODE_RE, FR_DELTA_ID_RE, parse_fr_delta_id,
    RuleName, RuleLevel,
)
from specstd.conformance import check_conformance  # noqa: E402

from test_specstd.helpers import create_valid_workspace  # noqa: E402


class TestParseFrDeltaId:
    """delta FR 编号的命名分组解析（双右锚）。"""

    def test_plain_date_iter(self):
        """常规日期迭代：FR-person-profile-0817-001 正确拆三段。"""
        r = parse_fr_delta_id("FR-person-profile-0817-001")
        assert r == {"func": "person-profile", "iter": "0817", "seq": "001"}

    def test_func_prefix_overlap_immune(self):
        """功能名前缀重叠免疫：person-search 与 person-search-v2 共存不歧义。"""
        r1 = parse_fr_delta_id("FR-person-search-0817-001")
        r2 = parse_fr_delta_id("FR-person-search-v2-0817-001")
        assert r1["func"] == "person-search"
        assert r2["func"] == "person-search-v2"
        assert r1["iter"] == r2["iter"] == "0817"

    def test_func_with_digits(self):
        """功能名含数字：FR-eval-360-0817-001 的 360 不被误判为迭代。"""
        r = parse_fr_delta_id("FR-eval-360-0817-001")
        assert r == {"func": "eval-360", "iter": "0817", "seq": "001"}

    def test_iter_free_form(self):
        """迭代名自由（除 '-'）：S24 / v2.5 / 2026Q3 / hongbao 均可解析。"""
        assert parse_fr_delta_id("FR-eval-360-S24-001")["iter"] == "S24"
        assert parse_fr_delta_id("FR-eval-360-v2.5-001")["iter"] == "v2.5"
        assert parse_fr_delta_id("FR-eval-360-2026Q3-001")["iter"] == "2026Q3"
        assert parse_fr_delta_id("FR-eval-360-hongbao-001")["iter"] == "hongbao"

    def test_baseline_fr_not_matched(self):
        """基线编号 FR-001 不是 delta 格式，返回 None。"""
        assert parse_fr_delta_id("FR-001") is None

    def test_malformed_not_matched(self):
        """非法形态（流水非 3 位数字 / 缺段）返回 None。"""
        assert parse_fr_delta_id("FR-exp-tag-0817-01") is None
        assert parse_fr_delta_id("FR-exp-tag-0817") is None
        assert parse_fr_delta_id("FR-0817-001") is None  # 缺功能段

    def test_known_features_rejects_dashed_iter(self):
        """迭代含 '-' 时功能段会吸进碎片——注册表校验拒绝（如 eval-360-2026-08）。"""
        features = {"eval-360", "exp-tag"}
        assert parse_fr_delta_id(
            "FR-eval-360-2026-08-17-001", known_features=features) is None
        # 同一编号在无注册表时为 best-effort 解析（形态合法），
        # 防线在 delta 目录代号白名单（changes/2026-08-17/ 会被 STRUCT 拒绝）
        assert parse_fr_delta_id("FR-eval-360-2026-08-17-001") is not None
        # 注册表内合法功能正常解析
        assert parse_fr_delta_id(
            "FR-eval-360-S24-001", known_features=features)["func"] == "eval-360"


class TestIterCodeWhitelist:
    """迭代代号字符集白名单。"""

    @pytest.mark.parametrize("code", ["0817", "S24", "v2.5", "2026Q3", "hongbao", "sprint_3"])
    def test_legal_codes(self, code):
        assert ITER_CODE_RE.match(code), f"{code} 应合法"

    @pytest.mark.parametrize("code", ["2026-08-17", "sprint-23", "delta-001", "sp rint", "", "0817/1"])
    def test_illegal_codes(self, code):
        assert not ITER_CODE_RE.match(code), f"{code} 应非法（含 '-' 或非法字符）"


class TestConformanceDeltaCode:
    """conformance 对 delta 目录代号的强制校验（STRUCT）。"""

    def test_dashed_delta_code_rejected(self, tmp_path):
        """changes/2026-08-17/ 应报 STRUCT ERROR（迭代代号禁 '-'）。"""
        ws = create_valid_workspace(tmp_path / "ws-dash")
        shutil.move(str(ws / "changes" / "delta001"), str(ws / "changes" / "2026-08-17"))
        report = check_conformance(ws, "test-dash")
        struct_errors = [
            f for f in report.findings
            if f.rule == RuleName.STRUCT.value and f.level == RuleLevel.ERROR.value
            and "2026-08-17" in f.message
        ]
        assert struct_errors, "含 '-' 的 delta 代号应报 STRUCT ERROR"

    def test_legal_delta_code_passes(self, tmp_path):
        """changes/S24/ 等合法代号不报代号类 STRUCT ERROR。"""
        ws = create_valid_workspace(tmp_path / "ws-legal")
        shutil.move(str(ws / "changes" / "delta001"), str(ws / "changes" / "S24"))
        report = check_conformance(ws, "test-legal")
        code_errors = [
            f for f in report.findings
            if f.rule == RuleName.STRUCT.value and f.level == RuleLevel.ERROR.value
            and "代号" in f.message
        ]
        assert not code_errors, f"合法代号不应报代号错误: {[f.to_dict() for f in code_errors]}"

    def test_valid_workspace_still_passes(self, tmp_path):
        """合规样例（delta001）保持全 PASS。"""
        ws = create_valid_workspace(tmp_path / "ws-valid")
        report = check_conformance(ws, "test-valid")
        errors = [f for f in report.findings if f.level == RuleLevel.ERROR.value]
        assert not errors, f"合规仓库不应有 ERROR: {[f.to_dict() for f in errors]}"
