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
    """隔离 promote 环境：drafts/ + scenarios/{module}/ + 基线。"""
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
