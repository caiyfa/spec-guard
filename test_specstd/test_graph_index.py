"""test_graph_index.py — 图谱索引（T-070，M11 §9 G1 验收）单测。

覆盖：
- 构建正确性：nodes/edges 类型与 source_ref 定位（v1.19 补强）
- 确定性：删库重建逐条一致（派生物可删可重建铁律）
- 指纹失效即重建：改场景 covers → stale=true → rebuild → stale=false
- 三层视图：L0/L1/L2（对齐 PANODATA 口径）
- backlink：计算型反向链接
- 健康分公式行为
"""

import json
import shutil
from pathlib import Path

import pytest

from graph_index import service
from graph_index.builder import build_index, compute_source_fingerprint
from graph_index.service import index_path
from graph_index.store import GraphStore


# ══════════════════════════════════════════════════════════
# 假工作区构造（完全 tmp 隔离，不触碰真实场景库）
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def fake_ws(tmp_path):
    """构造假工作区：specs/ + changes/ + scenarios/ + .specguard/ + feedback/。"""
    ws = tmp_path / "ws"
    scenarios = tmp_path / "scenarios"
    (ws / "specs" / "inventory" / "grid-placement").mkdir(parents=True)
    (ws / "specs" / "inventory" / "person-list").mkdir(parents=True)
    (ws / "specs" / "system-settings" / "tag-library").mkdir(parents=True)
    (ws / "changes" / "extend-void-scope").mkdir(parents=True)
    (scenarios / "inventory").mkdir(parents=True)
    (ws / ".specguard" / "plans").mkdir(parents=True)
    (ws / ".specguard" / "reports" / "EX-abcdef12").mkdir(parents=True)
    (tmp_path / "feedback").mkdir(parents=True)

    # spec.md（FR 标题式 + 列表式双形态 + AC）
    (ws / "specs" / "inventory" / "grid-placement" / "spec.md").write_text(
        "# 九宫格落位\n"
        "## 一、概述\n"
        "### FR-012: 作废级联删除 [delta:extend-void-scope]\n"
        "作废会话后级联删除人员/快照/结果表。AC-001 校验删除完整性。\n"
        "### FR-013: 落位结果冻结\n"
        "落位结果冻结后不可修改。AC-002/AC-003 校验冻结语义。\n",
        encoding="utf-8")
    (ws / "specs" / "inventory" / "person-list" / "spec.md").write_text(
        "# 盘点人员清单\n"
        "## 一、概述\n"
        "- **FR-009**：名单过滤\n"
        "  按组织/状态过滤盘点名单，AC-004。\n",
        encoding="utf-8")
    (ws / "specs" / "system-settings" / "tag-library" / "spec.md").write_text(
        "# 标签库\n"
        "### FR-030: 标签增删改\n"
        "标签 CRUD。AC-005 校验。\n",
        encoding="utf-8")

    # delta-spec.md（contains 边）
    (ws / "changes" / "extend-void-scope" / "delta-spec.md").write_text(
        "## ADDED Requirements\n"
        "### FR-012: 作废级联删除 [delta:extend-void-scope]\n"
        "→ task: TSK-001\n",
        encoding="utf-8")

    # 场景（covers + depends_on）
    (scenarios / "inventory" / "IA-VOID-001.yaml").write_text(
        "id: IA-VOID-001\n"
        "title: 作废活动级联逻辑删除\n"
        "doc:\n"
        "  covers: [FR-012]\n"
        "depends_on:\n"
        "  - {id: IS-PREP-003, mode: exclusive}\n",
        encoding="utf-8")
    (scenarios / "inventory" / "IS-PREP-003.yaml").write_text(
        "id: IS-PREP-003\n"
        "title: 盘点前置准备\n"
        "doc:\n"
        "  covers: [FR-009]\n",
        encoding="utf-8")

    # 计划 + 报告（run 节点）
    (ws / ".specguard" / "plans" / "plan-001.yaml").write_text(
        "id: plan-001\n"
        "title: 作废级联计划\n"
        "scenarios: [IA-VOID-001, IS-PREP-003]\n",
        encoding="utf-8")
    (ws / ".specguard" / "reports" / "EX-abcdef12" / "trigger.json").write_text(
        json.dumps({"plan_id": "plan-001"}, ensure_ascii=False), encoding="utf-8")

    # SPQ 台账
    (tmp_path / "feedback" / "ledger.json").write_text(
        json.dumps([
            {"spq_id": "SPQ-001", "title": "名单过滤未刷新", "status": "pending",
             "scenario_id": "IS-PREP-003"},
            {"spq_id": "SPQ-002", "title": "已闭环", "status": "closed",
             "scenario_id": "IA-VOID-001"},
        ], ensure_ascii=False), encoding="utf-8")

    return {"ws": ws, "scenarios": scenarios, "root": tmp_path,
            "index": ws / ".specguard" / "graph_index.db"}


def _build(fake_ws):
    return build_index(
        workspace_root=fake_ws["ws"],
        index_path=fake_ws["index"],
        scenarios_root=fake_ws["scenarios"],
        sg_root=fake_ws["root"],
    )


def _snapshot(path: Path) -> list[tuple]:
    """节点/边全量快照（确定性比对用）。"""
    with GraphStore(path) as store:
        nodes = sorted((n["id"], n["node_type"], n["title"], n["module"],
                        n["feature"], json.dumps(n["attrs"], sort_keys=True),
                        json.dumps(n["source_ref"], sort_keys=True) if n["source_ref"] else "")
                       for n in store.list_nodes())
        edges = sorted((e["src"], e["dst"], e["edge_type"]) for e in store.list_edges())
    return nodes, edges


# ══════════════════════════════════════════════════════════
# 构建正确性
# ══════════════════════════════════════════════════════════

class TestBuildIndex:
    def test_build_counts(self, fake_ws):
        result = _build(fake_ws)
        assert result["nodes"] > 0 and result["edges"] > 0
        assert result["source_fingerprint"]

    def test_node_types_and_source_ref(self, fake_ws):
        _build(fake_ws)
        with GraphStore(fake_ws["index"]) as store:
            fr = store.get_node("FR-012")
            assert fr["node_type"] == "fr"
            assert fr["module"] == "inventory"
            assert fr["feature"] == "grid-placement"
            # source_ref 定位（v1.19 补强）：file 相对路径 + 真实行区间
            ref = fr["source_ref"]
            assert ref and ref["file"].endswith("grid-placement/spec.md")
            assert ref["line_range"][0] == 3  # "### FR-012" 在第 3 行
            assert ref["line_range"][1] == 4  # 到下一个 FR 前一行

            # 列表式锚点（FR-009）
            fr9 = store.get_node("FR-009")
            assert fr9 and fr9["source_ref"]["line_range"][0] == 3

            # 场景 source_ref 定位到 covers 行
            sc = store.get_node("IA-VOID-001")
            assert sc["source_ref"]["file"].startswith("scenarios/")
            assert sc["source_ref"]["line_range"] == [4, 4]  # covers 行

            # module/feature 节点与 contains 边
            assert store.get_node("mod:inventory")["node_type"] == "module"
            assert store.get_node("feat:inventory/grid-placement")["node_type"] == "feature"
            assert any(e["edge_type"] == "contains"
                       for e in store.list_edges_by_node("mod:inventory"))

            # delta 节点 + contains 边
            delta = store.get_node("extend-void-scope")
            assert delta and delta["node_type"] == "delta"
            assert any(e["edge_type"] == "contains" and e["dst"] == "FR-012"
                       for e in store.list_edges_by_node(delta["id"]))

            # plan/run/spq 节点
            assert store.get_node("plan:plan-001")["node_type"] == "plan"
            assert store.get_node("run:EX-abcdef12")["node_type"] == "run"
            assert any(e["edge_type"] == "executes" and e["dst"] == "plan:plan-001"
                       for e in store.list_edges_by_node("run:EX-abcdef12"))
            spq = store.get_node("SPQ-001")
            assert spq and spq["attrs"]["status"] == "pending"
            assert any(e["edge_type"] == "feedback" and e["dst"] == "IS-PREP-003"
                       for e in store.list_edges_by_node("SPQ-001"))

    def test_covers_and_depends_edges(self, fake_ws):
        _build(fake_ws)
        with GraphStore(fake_ws["index"]) as store:
            edges = store.list_edges_by_node("IA-VOID-001")
            types = {(e["edge_type"], e["dst"]) for e in edges}
            assert ("covers", "FR-012") in types
            assert ("depends_on", "IS-PREP-003") in types


# ══════════════════════════════════════════════════════════
# 确定性（删库重建同图）
# ══════════════════════════════════════════════════════════

class TestDeterminism:
    def test_rebuild_same_graph(self, fake_ws):
        _build(fake_ws)
        before = _snapshot(fake_ws["index"])
        fake_ws["index"].unlink()
        _build(fake_ws)
        after = _snapshot(fake_ws["index"])
        assert before == after, "删库重建必须得到逐条一致的图（派生物确定性铁律）"

    def test_fingerprint_stale_and_rebuild(self, fake_ws):
        _build(fake_ws)
        st = service.status(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        assert st["stale"] is False

        # 修改场景 covers → 指纹失配 → stale=true
        sc = fake_ws["scenarios"] / "inventory" / "IA-VOID-001.yaml"
        sc.write_text(sc.read_text(encoding="utf-8").replace("FR-012", "FR-013"),
                      encoding="utf-8")
        st = service.status(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        assert st["stale"] is True

        # rebuild 后 stale=false 且边已更新
        service.rebuild(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        st = service.status(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        assert st["stale"] is False
        with GraphStore(fake_ws["index"]) as store:
            edges = store.list_edges_by_node("IA-VOID-001")
            assert any(e["edge_type"] == "covers" and e["dst"] == "FR-013"
                       for e in edges)
            assert not any(e["edge_type"] == "covers" and e["dst"] == "FR-012"
                           for e in edges)

    def test_query_ensure_fresh_auto_rebuild(self, fake_ws):
        """查询前保鲜：改源数据后 query 自动重建，无需手动 rebuild。"""
        _build(fake_ws)
        sc = fake_ws["scenarios"] / "inventory" / "IA-VOID-001.yaml"
        sc.write_text(sc.read_text(encoding="utf-8").replace("FR-012", "FR-013"),
                      encoding="utf-8")
        l2 = service.query(fake_ws["ws"], level="L2",
                           module="inventory", feature="grid-placement",
                           scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        fr_ids = {f["id"] for f in l2["frs"]}
        scenario_covers = {c for s in l2["scenarios"] for c in s["covers"]}
        assert "FR-013" in scenario_covers
        assert len(fr_ids) == 2


# ══════════════════════════════════════════════════════════
# 三层视图
# ══════════════════════════════════════════════════════════

class TestPanorama:
    def test_l0(self, fake_ws):
        _build(fake_ws)
        l0 = service.query(fake_ws["ws"], level="L0",
                           scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        assert set(l0["l0mods"]) == {"inventory", "system-settings"}
        assert l0["l0mods"]["inventory"]["fr_count"] == 3
        assert isinstance(l0["l0edges"], list)

    def test_l1_health(self, fake_ws):
        _build(fake_ws)
        l1 = service.query(fake_ws["ws"], level="L1", module="inventory",
                           scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        assert "grid-placement" in l1
        gp = l1["grid-placement"]
        assert gp["nCov"] == 1 and gp["nGap"] == 1  # FR-012 有覆盖，FR-013 无
        assert gp["health"] is not None

    def test_l2_neighborhood(self, fake_ws):
        _build(fake_ws)
        l2 = service.query(fake_ws["ws"], level="L2",
                           module="inventory", feature="grid-placement",
                           scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        fr_ids = {f["id"] for f in l2["frs"]}
        assert fr_ids == {"FR-012", "FR-013"}
        sc_ids = {s["id"] for s in l2["scenarios"]}
        assert sc_ids == {"IA-VOID-001"}
        assert "FR-012" in l2["scenarios"][0]["covers"]
        assert l2["frs"][0]["source_ref"]["line_range"] == [3, 4]

    def test_health_formula(self, fake_ws):
        """健康分：无场景覆盖的 feature 覆盖率项扣分。"""
        _build(fake_ws)
        l1 = service.query(fake_ws["ws"], level="L1", module="system-settings",
                           scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        tag = l1["tag-library"]
        assert tag["nCov"] == 0 and tag["nGap"] == 1
        # 覆盖率 0 + 无场景（stale_factor=0）→ 100 - 30 = 70
        assert tag["health"] == 70.0


# ══════════════════════════════════════════════════════════
# backlink
# ══════════════════════════════════════════════════════════

class TestBacklink:
    def test_backlink_covered_and_modified(self, fake_ws):
        _build(fake_ws)
        with GraphStore(fake_ws["index"]) as store:
            bl = service.backlink(store, "FR-012")
        assert bl["covered_by"] == ["IA-VOID-001"]
        assert bl["modified_by"] == ["extend-void-scope"]
        assert bl["decided_by"] == [] and bl["referenced_by"] == []

    def test_backlink_unknown_node(self, fake_ws):
        _build(fake_ws)
        with GraphStore(fake_ws["index"]) as store:
            bl = service.backlink(store, "FR-999")
        assert bl["covered_by"] == []


# ══════════════════════════════════════════════════════════
# 红线：构建/查询不写源文件
# ══════════════════════════════════════════════════════════

class TestRedLines:
    def test_build_never_touches_sources(self, fake_ws):
        _build(fake_ws)
        sources = list((fake_ws["ws"] / "specs").rglob("*")) + \
                  list(fake_ws["scenarios"].rglob("*"))
        mtimes_before = {p: p.stat().st_mtime for p in sources if p.is_file()}
        service.rebuild(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        mtimes_after = {p: p.stat().st_mtime for p in sources if p.is_file()}
        assert mtimes_before == mtimes_after, "重建不得触碰任何源文件（红线 2）"

    def test_stage_mapping(self):
        from graph_index.service import node_stage
        assert node_stage("fr") == "req"
        assert node_stage("scenario") == "test"
        assert node_stage("spq") == "feedback"
        assert node_stage("external_ref") == "dev_ext"


# ══════════════════════════════════════════════════════════
# 里程碑快照 + 演化 diff（T-072，M11 §6.2/§6.3）
# ══════════════════════════════════════════════════════════

class TestSnapshot:
    def test_create_snapshot(self, fake_ws):
        _build(fake_ws)
        from graph_index import snapshot
        result = snapshot.create_snapshot(
            fake_ws["ws"], label="es-acceleration 归档", trigger="delta_archived",
            scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"],
        )
        assert result["snapshot_id"].startswith("snap_")
        assert result["nodes"] > 0 and result["edges"] > 0
        assert result["source_fingerprint"]
        # 快照文件落 .specflow/graph_snapshots/ 且带指纹
        snap_file = fake_ws["ws"] / ".specflow" / "graph_snapshots" / f'{result["snapshot_id"]}.json'
        assert snap_file.is_file()
        data = json.loads(snap_file.read_text(encoding="utf-8"))
        assert data["trigger"] == "delta_archived"
        assert data["source_fingerprint"] == result["source_fingerprint"]

    def test_list_snapshots(self, fake_ws):
        _build(fake_ws)
        from graph_index import snapshot
        snapshot.create_snapshot(fake_ws["ws"], label="v1", trigger="manual",
                                 scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        snapshot.create_snapshot(fake_ws["ws"], label="v2", trigger="plan_completed",
                                 scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        items = snapshot.list_snapshots(fake_ws["ws"])
        assert len(items) == 2
        assert items[0]["nodes"] > 0
        assert {i["trigger"] for i in items} == {"manual", "plan_completed"}

    def test_diff_between_snapshots(self, fake_ws):
        _build(fake_ws)
        from graph_index import snapshot
        s1 = snapshot.create_snapshot(fake_ws["ws"], label="v1", trigger="manual",
                                      scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        # 改源数据（新增场景）+ 重建 + 再打快照
        (fake_ws["scenarios"] / "inventory" / "NEW-SC-001.yaml").write_text(
            "id: NEW-SC-001\ntitle: 新增场景\ndoc:\n  covers: [FR-013]\n", encoding="utf-8")
        service.rebuild(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        d = snapshot.diff_snapshots(fake_ws["ws"], s1["snapshot_id"], "current",
                                    index_path=fake_ws["index"])
        assert d["added"] >= 1 and "NEW-SC-001" in d["added_ids"]
        assert d["removed"] == 0
        assert d["fingerprint_from"] and d["fingerprint_to"]
        assert d["fingerprint_from"] != d["fingerprint_to"]
        assert "inventory" in d["per_module"]

    def test_diff_modified(self, fake_ws):
        _build(fake_ws)
        from graph_index import snapshot
        s1 = snapshot.create_snapshot(fake_ws["ws"], label="v1", trigger="manual",
                                      scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"])
        # 改 covers（SPQ 状态不变，场景 attrs.covers 变化 → modified）
        sc = fake_ws["scenarios"] / "inventory" / "IA-VOID-001.yaml"
        sc.write_text(sc.read_text(encoding="utf-8").replace("FR-012", "FR-013"),
                      encoding="utf-8")
        service.rebuild(fake_ws["ws"], fake_ws["scenarios"], fake_ws["root"])
        d = snapshot.diff_snapshots(fake_ws["ws"], s1["snapshot_id"], "current",
                                    index_path=fake_ws["index"])
        assert "IA-VOID-001" in d["modified_ids"]

    def test_diff_missing_snapshot_404(self, fake_ws):
        _build(fake_ws)
        from graph_index import snapshot
        with pytest.raises(FileNotFoundError):
            snapshot.diff_snapshots(fake_ws["ws"], "snap_2099-01-01_none")


# ══════════════════════════════════════════════════════════
# 血缘链（T-073，M10 §6）：DB 挂链派生 + trace 投影
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def fake_db(tmp_path, fake_ws):
    """构造 workbench.db（sf_interviews/sf_decisions/sf_decision_links/sf_external_refs）。"""
    import sqlite3
    db = tmp_path / "workbench.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
    CREATE TABLE sf_interviews (
      iv_id TEXT PRIMARY KEY, workspace TEXT NOT NULL, session_id TEXT NOT NULL,
      title TEXT NOT NULL, initiator TEXT NOT NULL, target_delta TEXT,
      status TEXT NOT NULL DEFAULT 'opened', opened_at TEXT NOT NULL, frozen_at TEXT
    );
    CREATE TABLE sf_decisions (
      id TEXT PRIMARY KEY, workspace TEXT NOT NULL, interview_id TEXT NOT NULL,
      question_ref TEXT, priority TEXT NOT NULL, question TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', resolution TEXT, resolved_by TEXT,
      resolved_at TEXT, superseded_by TEXT, created_by TEXT NOT NULL DEFAULT 'agent',
      created_at TEXT NOT NULL DEFAULT (datetime('now')), content_sha TEXT NOT NULL
    );
    CREATE TABLE sf_decision_links (
      decision_id TEXT NOT NULL, link_type TEXT NOT NULL, link_ref TEXT NOT NULL,
      direction TEXT NOT NULL DEFAULT 'out', PRIMARY KEY (decision_id, link_type, link_ref)
    );
    CREATE TABLE sf_external_refs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT NOT NULL, type TEXT NOT NULL,
      ref TEXT NOT NULL, ref_url TEXT, linked_type TEXT NOT NULL, linked TEXT NOT NULL,
      note TEXT, registered_by TEXT NOT NULL, created_at TEXT NOT NULL,
      UNIQUE (workspace, type, ref, linked_type, linked)
    );
    """)
    conn.execute("INSERT INTO sf_interviews VALUES ('IV-003','ws','s1','作废范围扩展面试','tester','extend-void-scope','frozen','2026-08-01T10:00:00','2026-08-01T11:00:00')")
    conn.execute("INSERT INTO sf_decisions VALUES ('D-012','ws','IV-003','q1','P0','作废级联含 6 张结果表','resolved','tester','2026-08-01T11:00:00',NULL,NULL,'agent',datetime('now'),'sha1')")
    conn.execute("INSERT INTO sf_decision_links VALUES ('D-012','fr_anchor','FR-012','out')")
    conn.execute("INSERT INTO sf_decision_links VALUES ('D-012','delta','extend-void-scope','out')")
    conn.execute("INSERT INTO sf_external_refs VALUES (1,'ws','ZT-STORY','A-02','https://zt.example/story/A-02','fr','FR-012','','tester','2026-08-01T12:00:00')")
    conn.commit()
    conn.close()
    return db


class TestLineage:
    def _build_with_db(self, fake_ws, fake_db):
        return build_index(
            workspace_root=fake_ws["ws"],
            index_path=fake_ws["index"],
            scenarios_root=fake_ws["scenarios"],
            sg_root=fake_ws["root"],
            db_path=fake_db,
        )

    def test_db_lineage_nodes(self, fake_ws, fake_db):
        self._build_with_db(fake_ws, fake_db)
        from graph_index import service
        with GraphStore(fake_ws["index"]) as store:
            assert store.get_node("IV-003")["node_type"] == "interview"
            d = store.get_node("D-012")
            assert d["node_type"] == "decision"
            assert d["attrs"]["priority"] == "P0"
            ext = store.get_node("ZT-STORY:A-02")
            assert ext["node_type"] == "external_ref"
            assert ext["attrs"]["url"]
            # 谱系边
            edges = {(e["edge_type"], e["src"], e["dst"])
                     for e in store.list_edges()}
            assert ("produces", "IV-003", "D-012") in edges
            assert ("decides", "D-012", "FR-012") in edges
            assert ("produces", "D-012", "extend-void-scope") in edges
            assert ("references", "ZT-STORY:A-02", "FR-012") in edges

    def test_trace_up_q1(self, fake_ws, fake_db):
        """Q1：场景为什么存在 → FR → delta → 决策 → 面试。"""
        self._build_with_db(fake_ws, fake_db)
        from graph_index import service
        with GraphStore(fake_ws["index"]) as store:
            result = service.trace(store, "IA-VOID-001", direction="up")
        ids = [p["id"] for p in result["path"]]
        assert "IA-VOID-001" in ids
        assert "FR-012" in ids
        assert "extend-void-scope" in ids
        assert "D-012" in ids
        assert "IV-003" in ids
        assert result["path"][0]["type"] == "scenario"
        assert not result["truncated"]

    def test_trace_down_q2(self, fake_ws, fake_db):
        """Q2：需求被验证了吗 → 场景 → 计划 → 报告 → SPQ。"""
        self._build_with_db(fake_ws, fake_db)
        from graph_index import service
        with GraphStore(fake_ws["index"]) as store:
            result = service.trace(store, "FR-012", direction="down")
        ids = [p["id"] for p in result["path"]]
        assert "IA-VOID-001" in ids
        assert "plan:plan-001" in ids
        assert "run:EX-abcdef12" in ids
        assert "SPQ-002" in ids

    def test_trace_external_marked(self, fake_ws, fake_db):
        self._build_with_db(fake_ws, fake_db)
        from graph_index import service
        with GraphStore(fake_ws["index"]) as store:
            result = service.trace(store, "FR-012", direction="both")
        ext_nodes = [p for p in result["path"] if p["external"]]
        assert any(p["id"] == "ZT-STORY:A-02" for p in ext_nodes)
        assert ext_nodes[0]["url"].startswith("https://")

    def test_trace_unknown_node(self, fake_ws):
        _build(fake_ws)
        from graph_index import service
        import pytest as _pytest
        with GraphStore(fake_ws["index"]) as store:
            with _pytest.raises(KeyError):
                service.trace(store, "NOPE-999", direction="up")


# ══════════════════════════════════════════════════════════
# 断链规则集（T-074，M10 §4.3/§6.3）
# ══════════════════════════════════════════════════════════

class TestLineageCheck:
    def test_rules_loaded(self):
        from specflow.lineage import lineage_check
        rules = lineage_check.load_rules()
        ids = [r["id"] for r in rules]
        assert ids == [f"BL-{i:02d}" for i in range(1, 7)]
        assert all(r["level"] == "WARNING" for r in rules)

    def test_check_warns_missing_covers_and_delta(self, fake_ws):
        """无 covers 的场景（BL-01）与无 source_delta 的场景（BL-02）应报 WARNING。"""
        # fake 场景 IA-VOID-001 无 source_delta → BL-02 命中；
        # 全部场景均有 covers → BL-01 不命中
        _build(fake_ws)
        from specflow.lineage import lineage_check
        result = lineage_check.run_checks(fake_ws["ws"], fake_ws["index"],
                                          write_output=False)
        bl01 = [w for w in result["warnings"] if w["rule"] == "BL-01"]
        bl02 = [w for w in result["warnings"] if w["rule"] == "BL-02"]
        assert bl01 == []
        assert {w["node"] for w in bl02} == {"IA-VOID-001", "IS-PREP-003"}

    def test_check_fr_double_broken(self, fake_ws):
        """FR-013 无场景覆盖无外部锚点 → BL-04 命中；FR-012 有覆盖不命中。"""
        _build(fake_ws)
        from specflow.lineage import lineage_check
        result = lineage_check.run_checks(fake_ws["ws"], fake_ws["index"],
                                          write_output=False)
        bl04 = {w["node"] for w in result["warnings"] if w["rule"] == "BL-04"}
        assert "FR-013" in bl04
        assert "FR-012" not in bl04

    def test_check_spq_and_delta_rules(self, fake_ws, fake_db):
        """SPQ-002 已 closed 但 feedback 边存在（SPQ-002→IA-VOID-001）→ BL-05 不命中；
        delta 无 produces 入边 → BL-03 命中（fake_db 有决策挂链时不命中）。"""
        from graph_index.builder import build_index as _bi
        _bi(workspace_root=fake_ws["ws"], index_path=fake_ws["index"],
            scenarios_root=fake_ws["scenarios"], sg_root=fake_ws["root"],
            db_path=fake_db)
        from specflow.lineage import lineage_check
        result = lineage_check.run_checks(fake_ws["ws"], fake_ws["index"],
                                          write_output=False)
        bl03 = [w for w in result["warnings"] if w["rule"] == "BL-03"]
        bl05 = [w for w in result["warnings"] if w["rule"] == "BL-05"]
        # fake_db 的 D-012 → extend-void-scope produces 边存在 → BL-03 不命中
        assert bl03 == []
        # SPQ 均有 feedback 边 → BL-05 不命中
        assert bl05 == []

    def test_check_output_rebuildable(self, fake_ws):
        """结果缓存可删可重建（派生物非事实源）。"""
        _build(fake_ws)
        from specflow.lineage import lineage_check
        lineage_check.run_checks(fake_ws["ws"], fake_ws["index"], write_output=True)
        target = fake_ws["ws"] / ".specguard" / "lineage_check.json"
        assert target.is_file()
        first = json.loads(target.read_text(encoding="utf-8"))
        target.unlink()
        lineage_check.run_checks(fake_ws["ws"], fake_ws["index"], write_output=True)
        second = json.loads(target.read_text(encoding="utf-8"))
        assert [w for w in first["warnings"]] == [w for w in second["warnings"]]


# ══════════════════════════════════════════════════════════
# 飞书知识图谱一期 T3：飞书材料派生段（feishu_doc/feishu_minutes/topic + mentions）
# ══════════════════════════════════════════════════════════

class TestFeishuNodes:
    def _add_feishu_facts(self, fake_ws):
        """共享区事实源 fixture：topics.yaml + material_links.yaml + materials/。"""
        fe = fake_ws["ws"] / ".specguard" / "feishu"
        (fe / "materials").mkdir(parents=True)
        (fe / "materials" / "fd-tokABC.md").write_text("# PRD 导出\n", encoding="utf-8")
        (fe / "topics.yaml").write_text(
            "version: 1\ntopics:\n"
            "  - id: tp:3f9a2c-0807-01\n    title: 导出权限讨论\n"
            "    summary: 按 corpCode 过滤\n    chat_sha8: 3f9a2c\n"
            "    window: ['2026-08-07T14:00', '2026-08-07T15:30']\n"
            "    message_count: 23\n    participants_count: 4\n"
            "    source: chats/3f9a2c/20260807.md\n", encoding="utf-8")
        (fe / "material_links.yaml").write_text(
            "version: 1\nlinks:\n"
            "  - src: fd:tokABC\n    dst: FR-012\n    edge: mentions\n"
            "    confidence: 0.9\n    evidence: 级联删除\n"
            "    status: confirmed\n    confirmed_by: u1\n"
            "    confirmed_at: '2026-08-13T10:00:00'\n"
            "  - src: tp:3f9a2c-0807-01\n    dst: FR-012\n    edge: mentions\n"
            "    confidence: 0.8\n    evidence: 权限过滤\n"
            "    status: confirmed\n    confirmed_by: u1\n"
            "    confirmed_at: '2026-08-13T10:01:00'\n", encoding="utf-8")

    def test_feishu_nodes_and_mentions_edges(self, fake_ws):
        self._add_feishu_facts(fake_ws)
        _build(fake_ws)
        with GraphStore(fake_ws["index"]) as store:
            doc = store.get_node("fd:tokABC")
            assert doc["node_type"] == "feishu_doc" and doc["stage"] == "req"
            tp = store.get_node("tp:3f9a2c-0807-01")
            assert tp["node_type"] == "topic"
            assert tp["attrs"]["message_count"] == 23
            edges = [e for e in store.list_edges("mentions") if e["dst"] == "FR-012"]
            assert {e["src"] for e in edges} == {"fd:tokABC", "tp:3f9a2c-0807-01"}
            bl = service.backlink(store, "FR-012")
            assert "fd:tokABC" in bl.get("mentioned_by", [])

    def test_rejected_link_not_in_graph(self, fake_ws):
        self._add_feishu_facts(fake_ws)
        fe = fake_ws["ws"] / ".specguard" / "feishu"
        (fe / "material_links.yaml").write_text(
            "version: 1\nlinks:\n"
            "  - src: fd:tokABC\n    dst: FR-012\n    edge: mentions\n"
            "    confidence: 0.9\n    evidence: x\n    status: rejected\n"
            "    confirmed_by: u1\n    confirmed_at: '2026-08-13T10:00:00'\n",
            encoding="utf-8")
        _build(fake_ws)
        with GraphStore(fake_ws["index"]) as store:
            assert store.list_edges("mentions") == []

    def test_feishu_facts_change_triggers_stale(self, fake_ws):
        _build(fake_ws)
        st = service.status(fake_ws["ws"], scenarios_root=fake_ws["scenarios"],
                            sg_root=fake_ws["root"])
        assert st["stale"] is False
        self._add_feishu_facts(fake_ws)   # 新增事实源 → 指纹失配
        st = service.status(fake_ws["ws"], scenarios_root=fake_ws["scenarios"],
                            sg_root=fake_ws["root"])
        assert st["stale"] is True
