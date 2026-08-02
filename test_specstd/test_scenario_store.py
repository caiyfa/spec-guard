"""scenario_store 场景保存环预检 + 建图降级测试（T-101）。

背景：此前 PUT /api/scenarios/{id} 保存只校验 YAML 语法/flow 非空，
依赖环可被存盘 → 下一次 get_dag 建图抛 CycleError → /dag 500，
且 pytest 侧 scenario_graph fixture 同源崩溃 → 整个执行链路瘫痪。

验证：
1. 保存前环预检：新依赖与全库成环 → 拒绝保存（不再产生坏图）
2. 无环保存正常；孤儿依赖（上游不存在）不拦截（运行时 ORPHANED 诚实语义）
3. depends_on 格式非法（mode/version）→ 保存拒绝（此前静默存盘后建图才炸）
4. 场景库已存在坏图（如 git 拉取带入）时 get_dag/get_drift_report 降级不抛
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

from services import scenario_store as ss  # noqa: E402


def _scenario_yaml(sid, deps=(), bad_dep=None):
    """最小合法场景 YAML（格式 2.0 双层）；bad_dep 直接替换 depends_on 行（构造非法格式）。"""
    lines = [
        f"id: {sid}",
        f"title: {sid} 标题",
        "version: '0.1'",
        "doc:",
        "  given: [g]",
        "  when: [w]",
        "  then: [t]",
        "  covers: [FR-X]",
        "depends_on:",
    ]
    if bad_dep is not None:
        lines.append(f"  - {bad_dep}")
    elif deps:
        for d in deps:
            lines.append(f"  - {{id: {d}}}")
    else:
        lines.append("  []")
    lines.append("flow:")
    lines.append("  - python: {code: 'x = 1'}")
    lines.append("verify: []")
    return "\n".join(lines) + "\n"


@pytest.fixture()
def library(tmp_path, monkeypatch):
    """隔离场景库：SCENARIOS_ROOT 指向 tmp_path，缓存重置。"""
    root = tmp_path / "scenarios"
    root.mkdir()
    monkeypatch.setattr(ss, "SCENARIOS_ROOT", root)
    monkeypatch.setattr(ss, "_cache", {"fingerprint": None, "scenarios": None,
                                       "graph": None})
    return root


def _write(root, name, text):
    p = root / name
    p.write_text(text, encoding="utf-8")
    return p


class TestSaveCyclePrecheck:
    def test_save_rejects_cycle(self, library):
        """A 依赖 B 已入库；把 A 改成依赖 B、B 又依赖 A → 拒绝保存（含环路径信息）。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=[]))
        _write(library, "B.yaml", _scenario_yaml("B", deps=[]))
        # 先正常保存 B 为依赖 A（此时 A←B 单向，无环）
        r1 = ss.save_scenario_yaml("B", _scenario_yaml("B", deps=["A"]))
        assert r1["ok"] is True
        # 再保存 A 依赖 B → A→B 且 B→A 成环
        r2 = ss.save_scenario_yaml("A", _scenario_yaml("A", deps=["B"]))
        assert r2["ok"] is False
        assert "循环" in r2["error"]
        # 坏内容未落盘：文件仍是上一版（无依赖）
        on_disk = ss.get_scenario_yaml("A")
        assert "id: B" not in on_disk

    def test_save_accepts_dag(self, library):
        """无环依赖正常保存。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=[]))
        _write(library, "B.yaml", _scenario_yaml("B", deps=[]))
        r = ss.save_scenario_yaml("B", _scenario_yaml("B", deps=["A"]))
        assert r["ok"] is True

    def test_save_allows_orphan_dep(self, library):
        """依赖不存在的场景（孤儿）→ 允许保存（运行时判 ORPHANED，诚实语义）。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=[]))
        r = ss.save_scenario_yaml("A", _scenario_yaml("A", deps=["GHOST-001"]))
        assert r["ok"] is True

    def test_save_rejects_bad_mode(self, library):
        """depends_on.mode 非法 → 保存拒绝（此前静默存盘，建图时才炸）。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=[]))
        r = ss.save_scenario_yaml("A", _scenario_yaml("A", deps=[], bad_dep="{id: B, mode: illegal}"))
        assert r["ok"] is False
        assert "mode" in r["error"]

    def test_save_rejects_bad_version(self, library):
        """depends_on.version 非法 → 保存拒绝。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=[]))
        r = ss.save_scenario_yaml("A", _scenario_yaml("A", deps=[], bad_dep="{id: B, version: ^x.y}"))
        assert r["ok"] is False


class TestDegradedGraph:
    def test_get_dag_degrades_on_existing_cycle(self, library):
        """库中已有坏图（如 git 拉取带入）→ get_dag 不抛 500，降级出节点+边。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=["B"]))
        _write(library, "B.yaml", _scenario_yaml("B", deps=["A"]))
        dag = ss.get_dag()
        ids = {n["id"] for n in dag["nodes"]}
        assert ids == {"A", "B"}
        assert len(dag["edges"]) == 2

    def test_drift_report_exposes_cycles(self, library):
        """降级时 get_drift_report 合并返回环清单（前端漂移面板可见）。"""
        _write(library, "A.yaml", _scenario_yaml("A", deps=["B"]))
        _write(library, "B.yaml", _scenario_yaml("B", deps=["A"]))
        report = ss.get_drift_report()
        assert report["cycles"]
        assert any("A" in c and "B" in c for c in report["cycles"])


class TestListReportsBatchGrouping:
    """T-120：断点批次目录（{run_id}-bN）不单独成条——同一任务归并到主任务。"""

    def test_batch_dirs_filtered(self, tmp_path, monkeypatch):
        import json
        reports = tmp_path / "reports"
        # 主任务 + 两个批次目录，各带 run.json
        for name in ("EX-main0001", "EX-main0001-b0", "EX-main0001-b1"):
            d = reports / name
            d.mkdir(parents=True)
            (d / "run.json").write_text(json.dumps({
                "run_id": name, "env": "sit", "stats": {"pass": 1, "fail": 0,
                                                        "skip": 0, "blocked": 0, "total": 1}}),
                encoding="utf-8")
        monkeypatch.setattr(ss, "_reports_root", lambda: reports)
        runs = ss.list_reports(limit=20)
        ids = [r["run_id"] for r in runs]
        assert ids == ["EX-main0001"], f"批次目录不应单独成条: {ids}"
