"""plan_store 归一化测试（K-011：_normalize 白名单丢弃 breakpoints/delta 溯源字段的回归）。

隔离方式与 test_workspace_pull.py 一致：monkeypatch specstd.workspace 的
SG_ROOT / REGISTRY_PATH / CLONES_DIR 到 tmp_path，register_local 激活临时工作区，
计划落盘到该工作区的 .specguard/plans/。
"""

import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import specstd.workspace as wsm  # noqa: E402
from services import plan_store  # noqa: E402
from test_specstd.conftest import create_valid_workspace  # noqa: E402


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """隔离注册表 + 激活一个临时本地工作区（计划落 .specguard/plans/）。"""
    monkeypatch.setattr(wsm, "SG_ROOT", tmp_path)
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    ws_dir = tmp_path / "ws"
    create_valid_workspace(ws_dir)
    result = wsm.register_local("ws1", str(ws_dir), "tdm",
                                activate=True, run_conformance=False)
    assert result["ok"], result.get("error")
    return ws_dir


class TestNormalizeRoundtrip:
    def test_breakpoints_survive_save_get(self, workspace):
        """断点字段：save_plan → get_plan 往返后保留（修复前被 _normalize 丢弃）。"""
        plan_store.save_plan("p1", {
            "name": "回归计划",
            "env": "sit",
            "filter": {"scenarios": ["PP-RC-001", "PP-RC-002"]},
            "breakpoints": ["PP-RC-002"],
        })
        plan = plan_store.get_plan("p1")
        assert plan is not None
        assert plan["breakpoints"] == ["PP-RC-002"]

    def test_breakpoints_survive_resave(self, workspace):
        """编辑再保存（模拟前端 save 只提交部分字段）后断点不丢。"""
        plan_store.save_plan("p1", {
            "name": "回归计划",
            "filter": {"scenarios": ["A", "B", "C"]},
            "breakpoints": ["B"],
        })
        # 前端编辑：读回 → 改名称 → 整体提交
        plan = plan_store.get_plan("p1")
        plan["name"] = "改名后"
        plan_store.save_plan("p1", plan)
        assert plan_store.get_plan("p1")["breakpoints"] == ["B"]

    def test_delta_provenance_survives(self, workspace):
        """delta 溯源字段（source_delta/source_frs/unmatched_frs/imported_files）同样保留。"""
        plan_store.save_plan("p1", {
            "name": "delta 导入计划",
            "filter": {"scenarios": ["A"]},
            "breakpoints": [],
            "source_delta": "delta-001",
            "source_frs": ["FR-001", "FR-002"],
            "unmatched_frs": ["FR-099"],
            "imported_files": ["changes/delta-001/test-cases/a.yaml"],
        })
        plan = plan_store.get_plan("p1")
        assert plan["source_delta"] == "delta-001"
        assert plan["source_frs"] == ["FR-001", "FR-002"]
        assert plan["unmatched_frs"] == ["FR-099"]
        assert plan["imported_files"] == ["changes/delta-001/test-cases/a.yaml"]

    def test_list_plans_includes_breakpoints(self, workspace):
        """列表路径（list_plans 也走 _normalize）同样暴露 breakpoints。"""
        plan_store.save_plan("p1", {
            "name": "x", "filter": {"scenarios": ["A"]}, "breakpoints": ["A"],
        })
        plans = plan_store.list_plans()
        assert len(plans) == 1
        assert plans[0]["breakpoints"] == ["A"]

    def test_defaults_for_legacy_plan_files(self, workspace):
        """旧版计划文件（无新字段）读出为空默认值，不报错。"""
        plan_store.save_plan("p1", {"name": "旧计划", "filter": {"scenarios": ["A"]}})
        plan = plan_store.get_plan("p1")
        assert plan["breakpoints"] == []
        assert plan["source_delta"] == ""
        assert plan["source_frs"] == []
