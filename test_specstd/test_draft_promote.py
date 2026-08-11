"""draft_promote replace 模式测试（T-313：Agent 更新已有场景的写入路径）。

背景：promote 对同名场景报 conflict——Agent 按新格式要求（如 2.3.0 requires）
更新已有场景时无法入库。replace 模式 = 同名覆盖 + 原文件备份 + 三道闸失败回滚。
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import draft_promote as dr  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path, monkeypatch):
    """K-xxx：台账投影隔离到 tmp 库——promote/discard 的草稿状态落库不得污染真实 workbench.db。"""
    from services import ledger_store
    monkeypatch.setattr(ledger_store, "DB_PATH", tmp_path / "ledger.db")

SCENARIO = """
id: TL-RC-014
version: "0.1"
doc:
  given: 测试
  when: 测试
  then: 测试
  covers: []
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - status: {eq: 200}
"""


@pytest.fixture()
def promote_env(tmp_path, monkeypatch):
    """隔离 promote 环境：drafts/ + scenarios/{module}/ + 基线。

    T-061 适配：三闸前置（sg_draft_gates）语义由 test_s6_m07_coverage 专项覆盖，
    此处 mock 通过——本文件专注 replace/conflict/回滚等既有行为。
    """
    from services import draft_gates
    monkeypatch.setattr(draft_gates, "check_promote_allowed",
                        lambda fn, db_path=None: (True, ""))
    monkeypatch.setattr(draft_gates, "mark_promoted", lambda *a, **k: None)
    monkeypatch.setattr(draft_gates, "mark_gate3_fail", lambda *a, **k: None)
    drafts = tmp_path / "drafts"
    scenarios = tmp_path / "scenarios" / "mod" / "a"
    drafts.mkdir(parents=True)
    scenarios.mkdir(parents=True)
    monkeypatch.setattr(dr, "_drafts_root", lambda: drafts)
    monkeypatch.setattr(dr, "_scenarios_root", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(dr, "SG_ROOT", tmp_path)
    (tmp_path / "contracts_baseline.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dr, "_run_release_gate", lambda: {"ok": True, "output": ""})
    return drafts, scenarios, tmp_path


class TestPromoteReplace:
    def test_replace_overwrites_existing(self, promote_env):
        """T-313：同名场景 replace=True → 覆盖更新 + 基线重建。"""
        drafts, scenarios, tmp_path = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        existing = scenarios / "TL-RC-014.yaml"
        existing.write_text("旧版本内容\n", encoding="utf-8")

        result = dr.promote("TL-RC-014.yaml", "mod/a", skip_gate=True, replace=True)
        assert result["ok"] is True
        assert "旧版本" not in existing.read_text(encoding="utf-8"), "应被新内容覆盖"
        assert not (drafts / "TL-RC-014.yaml").exists(), "草稿已入库"
        baseline = json.loads((tmp_path / "contracts_baseline.json").read_text(encoding="utf-8"))
        assert "TL-RC-014" in baseline, "基线重建应含场景"

    def test_conflict_without_replace(self, promote_env):
        """既有行为保留：同名 + replace=False → conflict 错误。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (scenarios / "TL-RC-014.yaml").write_text("旧\n", encoding="utf-8")
        with pytest.raises(dr.PromoteError) as ei:
            dr.promote("TL-RC-014.yaml", "mod/a", skip_gate=True)
        assert "同名" in str(ei.value)

    def test_replace_rolls_back_on_gate_failure(self, promote_env, monkeypatch):
        """T-313：replace 发布门禁失败 → 原文件恢复 + 草稿保留 + 备份清理。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        existing = scenarios / "TL-RC-014.yaml"
        existing.write_text("旧版本内容\n", encoding="utf-8")
        monkeypatch.setattr(dr, "_run_release_gate", lambda: {"ok": False, "output": "T6 失败"})

        with pytest.raises(dr.PromoteError):
            dr.promote("TL-RC-014.yaml", "mod/a", skip_gate=False, replace=True)
        assert "旧版本内容" in existing.read_text(encoding="utf-8"), "失败应恢复原文件"
        assert (drafts / "TL-RC-014.yaml").is_file(), "失败草稿保留"
        assert not (scenarios / "TL-RC-014.yaml.bak").exists(), "回滚后清理备份"

    def test_success_cleans_backup(self, promote_env):
        """replace 成功后 .bak 备份删除（场景库在 git 内，历史可查）。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (scenarios / "TL-RC-014.yaml").write_text("旧\n", encoding="utf-8")
        dr.promote("TL-RC-014.yaml", "mod/a", skip_gate=True, replace=True)
        assert not (scenarios / "TL-RC-014.yaml.bak").exists()


class TestIdConflictPreCheck:
    """K-xxx：ID 全局唯一预检——「场景 id 重复」类失败前置化（TL-RC-014 案例）。"""

    def test_check_id_conflict_finds_existing(self, promote_env):
        """check_id_conflict：草稿 ID 已存在于库内另一模块 → 返回既有位置与模块。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (scenarios / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")  # 库内既有 TL-RC-014

        r = dr.check_id_conflict("TL-RC-014.yaml")
        assert r["ok"] is True and r["count"] == 1
        assert r["existing"]["id"] == "TL-RC-014"
        assert r["existing"]["module"] == "mod/a"
        assert r["existing"]["path"].endswith("TL-RC-014.yaml")

    def test_check_id_conflict_none_for_new(self, promote_env):
        """check_id_conflict：库内无该 ID（新场景）→ existing=None。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (scenarios / "OTHER.yaml").write_text(SCENARIO.replace("TL-RC-014", "OTHER-001"), encoding="utf-8")

        r = dr.check_id_conflict("TL-RC-014.yaml")
        assert r["ok"] is True and r["existing"] is None

    def test_check_id_conflict_file_missing_hit_library(self, promote_env):
        """草稿文件不存在（已入库）+ ID 命中库内 → existing 返回 + file_missing=True（刷新后去向判定）。"""
        drafts, scenarios, _ = promote_env
        (scenarios / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")  # 库内已有，草稿已移走

        r = dr.check_id_conflict("TL-RC-014.yaml")
        assert r["file_missing"] is True
        assert r["existing"]["id"] == "TL-RC-014"
        assert r["existing"]["module"] == "mod/a"

    def test_check_id_conflict_file_missing_no_library(self, promote_env):
        """草稿文件不存在（已删除）+ 库内无该 ID → existing=None + file_missing=True。"""
        drafts, scenarios, _ = promote_env

        r = dr.check_id_conflict("TL-RC-014.yaml")
        assert r["file_missing"] is True
        assert r["existing"] is None

    def test_promote_wrong_module_raises_id_conflict(self, promote_env):
        """选错模块入库：目标无同名文件但 ID 已在库内其他模块 → id_conflict 拦截，草稿不动。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (scenarios / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")

        with pytest.raises(dr.PromoteError) as ei:
            dr.promote("TL-RC-014.yaml", "mod/b", skip_gate=True)
        assert ei.value.code == "id_conflict"
        assert "mod/a" in str(ei.value), "提示语应给出既有位置"
        assert (drafts / "TL-RC-014.yaml").is_file(), "草稿不得被移动"
        assert not (tmp := scenarios.parent / "mod" / "b").exists() or not (tmp / "TL-RC-014.yaml").exists()

    def test_promote_right_module_replace_still_works(self, promote_env):
        """同模块 + replace=True：ID 预检放行，覆盖更新照常（与 T-313 不冲突）。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (scenarios / "TL-RC-014.yaml").write_text("旧版本内容\n", encoding="utf-8")

        result = dr.promote("TL-RC-014.yaml", "mod/a", skip_gate=True, replace=True)
        assert result["ok"] is True
        assert "旧版本" not in (scenarios / "TL-RC-014.yaml").read_text(encoding="utf-8")

    def test_batch_skips_id_conflict(self, promote_env):
        """批量入库：ID 已存在于库内其他模块 → 该份跳过并注明原因（批量不支持覆盖）。"""
        drafts, scenarios, _ = promote_env
        (drafts / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")
        (drafts / "OTHER-001.yaml").write_text(SCENARIO.replace("TL-RC-014", "OTHER-001"), encoding="utf-8")
        (scenarios / "TL-RC-014.yaml").write_text(SCENARIO, encoding="utf-8")

        r = dr.promote_batch(["TL-RC-014.yaml", "OTHER-001.yaml"], "mod/b", skip_gate=True)
        assert r["promoted"] == ["OTHER-001.yaml"] or [m["file"] for m in r["promoted"]] == ["OTHER-001.yaml"]
        skipped = {s["file"]: s["reason"] for s in r["skipped"]}
        assert "TL-RC-014.yaml" in skipped and "已存在" in skipped["TL-RC-014.yaml"]
