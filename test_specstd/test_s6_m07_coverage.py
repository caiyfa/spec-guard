"""S6 T-060/T-061：覆盖缺口三态聚合 + sg_draft_gates 三闸状态机。

验收锚点（《研发顺序与里程碑验收》§3 S6）：
- 覆盖缺口三态与真实基线一致；草稿不计覆盖（🟡 与 🔴 同 FR 可并存）
- 排序器确定性（delta 新增 P0 > 修改触及 > 历史缺口 > 边界/冲突；同权重 FR 升序）
- backlink 只读（调用前后工作区哈希不变）
- sg_draft_gates 状态机：write 自动② → 人评审① → promote 硬前置③
- promote 三闸未全过 → 拒绝且 scenarios/ 无变更
- 「生成下一批」只产草稿不产计划
"""

import json
import sqlite3
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

from test_specstd.conftest import create_valid_workspace  # noqa: E402


# ══════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def ws(tmp_path):
    """合规工作区 + 激活上下文。"""
    ws = create_valid_workspace(tmp_path / "ws")
    # 补 inventory-activity 模块 spec（13 FR 基线同构：8 FR 足够断言三态）
    inv_dir = ws / "specs" / "system-settings" / "inventory-activity"
    inv_dir.mkdir(parents=True, exist_ok=True)
    fr_lines = "\n".join(f"### FR-{i:03d}: 功能{i} 描述\nAC-{i} 验收{i}\n"
                         for i in range(1, 9))
    (inv_dir / "spec.md").write_text(
        f"# Inventory Activity\n\n## 一、功能描述\n\n{fr_lines}\n",
        encoding="utf-8")
    # changes/ 下 delta manifest（排序器输入）
    delta_dir = ws / "changes" / "extend-void-scope"
    delta_dir.mkdir(parents=True, exist_ok=True)
    (delta_dir / "delta.manifest.yaml").write_text(
        "delta: extend-void-scope\n"
        "baseline: \"1.0\"\n"
        "operations:\n"
        "  - op: add\n    fr: FR-001\n    section: ADDED Requirements\n"
        "    new: 作废级联逻辑删除\n    task: TSK-001\n"
        "  - op: modify\n    fr: FR-002\n    section: MODIFIED Requirements\n"
        "    original: 旧\n    new: 新\n    reason: 调整\n    task: TSK-002\n",
        encoding="utf-8")
    (delta_dir / "delta-spec.md").write_text(
        "# Delta: extend-void-scope\n\n## ADDED Requirements\n\n"
        "### FR-001: 作废级联逻辑删除 [delta:extend-void-scope]\n\n→ task: TSK-001\n\n"
        "## MODIFIED Requirements\n\n### FR-002: 修改功能 [delta:extend-void-scope]\n\n"
        "**原**: 旧\n**新**: 新\n**原因**: 调整\n\n→ task: TSK-002\n",
        encoding="utf-8")
    (delta_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (delta_dir / "task.md").write_text("### TSK-001 作废级联\n### TSK-002 修改\n", encoding="utf-8")

    # 场景库：FR-003 已覆盖（IS-RVT-001），FR-008 已覆盖但最近 FAIL
    sc_root = SG_ROOT / "scenarios"
    from engine.scenario_loader import load_suite_meta  # noqa: F401
    return ws


@pytest.fixture()
def ctx(tmp_path, ws, monkeypatch):
    """激活工作区 + 临时 DB + 场景/草稿落位（注册表隔离到 tmp 防污染）。"""
    from specstd import workspace as wmod

    monkeypatch.setattr(wmod, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wmod, "CLONES_DIR", tmp_path / "_clones")
    token = wmod.set_context_workspace("testws")
    try:
        wmod.register_local("testws", str(ws), "tdm", activate=True, run_conformance=False)
    except Exception:
        pass
    try:
        wmod.set_active("testws")
    except Exception:
        pass
    db = tmp_path / "test.db"

    # 场景库：FR-003 已覆盖（落工作区内，coverage 扫描工作区 scenarios 优先）
    sc_dir = ws / "scenarios" / "system-settings" / "inventory-activity"
    sc_dir.mkdir(parents=True, exist_ok=True)
    (sc_dir / "IS-RVT-001.yaml").write_text(
        "id: IS-RVT-001\ntitle: 已覆盖场景\n"
        "doc: {given: x, when: y, then: z, covers: [FR-003]}\n"
        "flow: [{call: {method: GET, path: /api/x}}]\nverify: []\n",
        encoding="utf-8")

    # 草稿：d-118 挂 FR-001（未入库）
    draft_dir = wmod.drafts_dir()
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "d-118.yaml").write_text(
        "id: IA-VOID-001\ntitle: 作废级联草稿\n"
        "doc: {given: x, when: y, then: z, covers: [FR-001]}\n"
        "source_delta: extend-void-scope\n"
        "source: {kind: agent, session: s1, suggested_by: gap-order}\n"
        "flow: [{call: {method: GET, path: /api/x}}]\nverify: []\n",
        encoding="utf-8")

    yield {"ws": ws, "db": db, "draft_dir": draft_dir, "sc_dir": sc_dir}
    wmod.reset_context_workspace(token)
    try:
        wmod.unregister("testws")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# T-060：覆盖缺口三态聚合
# ══════════════════════════════════════════════════════════

class TestCoverageGaps:
    def test_three_lanes_consistent_with_baseline(self, ctx):
        """8 FR 基线：FR-001 缺口+草稿并存、FR-003 已覆盖、其余缺口。"""
        from workbench.backend.services.coverage_gaps import compute_coverage
        result = compute_coverage()
        assert result["fr_total"] == 8
        lanes = result["lanes"]
        # FR-001：草稿存在但未入库 → 同时出现在 gap 与 draft（草稿不计覆盖）
        gap_ids = {g["fr"] for g in lanes["gap"]}
        assert "FR-001" in gap_ids
        draft_ids = {d["fr"] for d in lanes["draft"]}
        assert "FR-001" in draft_ids
        # FR-003 已覆盖 → 不在 gap
        assert "FR-003" not in gap_ids
        covered_ids = {c["fr"] for c in lanes["covered"]}
        assert "FR-003" in covered_ids
        # 草稿 lane 带 gates 与 scenario_id
        d118 = next(d for d in lanes["draft"] if d["fr"] == "FR-001")
        assert d118["draft_id"] == "d-118.yaml"
        assert d118["scenario_id"] == "IA-VOID-001"
        assert d118["gates"]["g1"] in ("pending", "approved")

    def test_draft_not_counted_as_coverage(self, ctx):
        """草稿不计覆盖：FR-001 在 gap 与 draft 同时存在。"""
        from workbench.backend.services.coverage_gaps import compute_coverage
        result = compute_coverage()
        gap_ids = {g["fr"] for g in result["lanes"]["gap"]}
        assert "FR-001" in gap_ids

    def test_fingerprint_deterministic(self, ctx):
        """同源数据两次聚合指纹一致（进程内缓存键 = 指纹）。"""
        from workbench.backend.services.coverage_gaps import compute_coverage
        r1 = compute_coverage()
        r2 = compute_coverage()
        assert r1["fingerprint"] == r2["fingerprint"]

    def test_priority_order_deterministic(self, ctx):
        """排序器：delta 新增 P0 > 修改触及 > 历史缺口；同权重 FR 升序。"""
        from workbench.backend.services.coverage_gaps import rank_gaps
        gaps = [
            {"fr": "FR-008", "reason": "history"},
            {"fr": "FR-002", "reason": "delta_modified"},
            {"fr": "FR-001", "reason": "delta_new_p0"},
            {"fr": "FR-004", "reason": "history"},
        ]
        order = rank_gaps(gaps)
        assert [g["fr"] for g in order] == ["FR-001", "FR-002", "FR-004", "FR-008"]

    def test_non_p0_add_ranked_below_p0_add(self, ctx):
        """P0 判定生效：delta 新增非 P0（90）位于 P0（100）与修改（80）之间。"""
        from workbench.backend.services.coverage_gaps import (
            rank_gaps, REASON_DELTA_NEW_P0, REASON_DELTA_NEW)
        gaps = [
            {"fr": "FR-003", "reason": "delta_modified"},
            {"fr": "FR-001", "reason": REASON_DELTA_NEW_P0},
            {"fr": "FR-002", "reason": REASON_DELTA_NEW},
        ]
        order = rank_gaps(gaps)
        assert [g["fr"] for g in order] == ["FR-001", "FR-002", "FR-003"]

    def test_gap_reason_distinguishes_p0(self, ctx):
        """_gap_reason：delta add + P0 决策命中 → delta_new_p0；否则 delta_new。"""
        from workbench.backend.services.coverage_gaps import (
            _gap_reason, REASON_DELTA_NEW_P0, REASON_DELTA_NEW, REASON_DELTA_MODIFIED)
        assert _gap_reason("FR-001", p0=set()) == REASON_DELTA_NEW
        assert _gap_reason("FR-001", p0={"FR-001"}) == REASON_DELTA_NEW_P0
        assert _gap_reason("FR-002", p0=set()) == REASON_DELTA_MODIFIED
        assert _gap_reason("FR-003", p0=set()) == "history"

    def test_module_filter_exact_segment(self, ctx):
        """module 过滤精确段匹配：'inventory-activity' 命中，'inventory' 不误匹配。"""
        from workbench.backend.services.coverage_gaps import compute_coverage
        r = compute_coverage(module="system-settings/inventory-activity")
        assert r["module"] == "system-settings/inventory-activity"
        # 所有返回 FR 的 module 均精确命中该模块（子串误匹配为 0）
        for lane in ("gap", "draft", "covered"):
            for item in r["lanes"][lane]:
                assert item["module"] == "system-settings/inventory-activity"
        # 不存在模块 → 空泳道（fr_total 是全量锚点基线，不过滤）
        r2 = compute_coverage(module="inventory-activity-not-exist")
        assert not r2["lanes"]["gap"]
        assert not r2["lanes"]["draft"]
        assert not r2["lanes"]["covered"]

    def test_backlink_readonly(self, ctx):
        """backlink 只读：调用前后工作区/scenarios/drafts 哈希不变。"""
        import hashlib

        def _snapshot():
            digest = hashlib.sha256()
            for root in (ctx["ws"], ctx["sc_dir"], ctx["draft_dir"]):
                for p in sorted(root.rglob("*")):
                    if p.is_file():
                        digest.update(p.read_bytes())
            return digest.hexdigest()

        from workbench.backend.services.coverage_gaps import backlink
        before = _snapshot()
        bl = backlink("FR-003")
        assert any(s["id"] == "IS-RVT-001" for s in bl["scenarios"])
        after = _snapshot()
        assert before == after

    def test_backlink_unknown_fr_empty(self, ctx):
        """未知 FR → 空结构而非异常。"""
        from workbench.backend.services.coverage_gaps import backlink
        bl = backlink("FR-999")
        assert bl["scenarios"] == []
        assert bl["drafts"] == []


# ══════════════════════════════════════════════════════════
# T-061：sg_draft_gates 三闸状态机
# ══════════════════════════════════════════════════════════

class TestDraftGates:
    def test_register_runs_gate2_auto(self, ctx):
        """write 登记时自动跑第②闸：合法草稿 gate2=pass，g1 pending g3 blocked。"""
        from workbench.backend.services.draft_gates import ensure_tables, register_draft
        ensure_tables(ctx["db"])
        g = register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                           source_delta="extend-void-scope", created_by="t1",
                           db_path=ctx["db"])
        assert g["gate1_status"] == "pending"
        assert g["gate2_status"] == "pass"
        assert g["gate3_status"] == "blocked"
        assert "gate2_report" in g and g["gate2_report"]

    def test_gate2_fail_on_bad_covers(self, ctx):
        """covers 锚点失效的草稿 → gate2=fail 且报告逐项。"""
        from workbench.backend.services.draft_gates import ensure_tables, register_draft
        ensure_tables(ctx["db"])
        # 先落盘 covers 锚点失效的草稿（文件是 gate2 校验的真相源）
        (ctx["draft_dir"] / "d-200.yaml").write_text(
            "id: IA-X-001\ntitle: 坏 covers 草稿\n"
            "doc: {given: x, when: y, then: z, covers: [FR-999]}\n"
            "flow: [{call: {method: GET, path: /api/x}}]\nverify: []\n",
            encoding="utf-8")
        g = register_draft("d-200.yaml", "IA-X-001", ["FR-999"],
                           source_delta="extend-void-scope", created_by="t1",
                           db_path=ctx["db"])
        assert g["gate2_status"] == "fail"
        report = g["gate2_report"]  # 已由 _row_to_dict 解析为 dict
        assert any("FR-999" in str(item) for item in report.get("findings", []))

    def test_gate1_review_approved_requires_gate2_pass(self, ctx):
        """gate2 未 pass 时 review approved 被拒（②失败打回，①不生效）。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft, review_draft, GateError,
        )
        ensure_tables(ctx["db"])
        register_draft("d-200.yaml", "IA-X-001", ["FR-999"],
                       source_delta="x", created_by="t1", db_path=ctx["db"])
        with pytest.raises(GateError):
            review_draft("d-200.yaml", "approved", "t1", "", db_path=ctx["db"])

    def test_promote_blocked_until_all_gates_pass(self, ctx):
        """三闸未全过 promote 被拒（gate_failed 语义：g3 blocked）。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft, check_promote_allowed,
        )
        ensure_tables(ctx["db"])
        register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                       source_delta="extend-void-scope", created_by="t1",
                       db_path=ctx["db"])
        # gate1 未 approved → 拒绝
        ok, reason = check_promote_allowed("d-118.yaml", db_path=ctx["db"])
        assert not ok
        assert "①闸" in reason or "gate1" in reason

    def test_promote_allowed_after_review(self, ctx):
        """gate1 approved + gate2 pass 后，promote 前置通过（g3 由发布门禁执行）。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft, review_draft, check_promote_allowed,
        )
        ensure_tables(ctx["db"])
        register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                       source_delta="extend-void-scope", created_by="t1",
                       db_path=ctx["db"])
        review_draft("d-118.yaml", "approved", "t1", "评审通过", db_path=ctx["db"])
        ok, reason = check_promote_allowed("d-118.yaml", db_path=ctx["db"])
        assert ok

    def test_review_requires_reviewer(self, ctx):
        """评审必须留痕 reviewer。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft, review_draft, GateError,
        )
        ensure_tables(ctx["db"])
        register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                       source_delta="x", created_by="t1", db_path=ctx["db"])
        with pytest.raises(GateError):
            review_draft("d-118.yaml", "approved", "", "", db_path=ctx["db"])

    def test_workspace_isolation(self, ctx):
        """跨工作区隔离：gate 查询只返回本工作区行。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft, list_gates,
        )
        ensure_tables(ctx["db"])
        register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                       source_delta="x", created_by="t1", db_path=ctx["db"])
        gates = list_gates(workspace="other-ws", db_path=ctx["db"])
        assert gates == []
        gates = list_gates(workspace="testws", db_path=ctx["db"])
        assert len(gates) == 1

    def test_gate3_report_persisted(self, ctx):
        """mark_gate3_fail 落库 gate3_report（发布门禁失败原因可查）。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft, mark_gate3_fail, get_gate,
        )
        ensure_tables(ctx["db"])
        register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                       source_delta="extend-void-scope", created_by="t1",
                       db_path=ctx["db"])
        mark_gate3_fail("d-118.yaml", report="release_check: DRIFT 未通过",
                        db_path=ctx["db"])
        g = get_gate("d-118.yaml", db_path=ctx["db"])
        assert g["gate3_status"] == "fail"
        assert "DRIFT" in g["gate3_report"]

    def test_gate2_report_verdict_consistent(self, ctx):
        """锚点核对失败时 gate2_report 的 verdict 与 gate2_status 同口径（FAIL）。"""
        from workbench.backend.services.draft_gates import (
            ensure_tables, register_draft,
        )
        ensure_tables(ctx["db"])
        (ctx["draft_dir"] / "d-200.yaml").write_text(
            "id: IA-X-001\ntitle: 坏 covers 草稿\n"
            "doc: {given: x, when: y, then: z, covers: [FR-999]}\n"
            "flow: [{call: {method: GET, path: /api/x}}]\nverify: []\n",
            encoding="utf-8")
        g = register_draft("d-200.yaml", "IA-X-001", ["FR-999"],
                           source_delta="x", created_by="t1", db_path=ctx["db"])
        assert g["gate2_status"] == "fail"
        assert g["gate2_report"]["verdict"] == "FAIL"


# ══════════════════════════════════════════════════════════
# T-060/T-061：REST 层（coverage 路由 + drafts review/revalidate）
# ══════════════════════════════════════════════════════════

class TestCoverageREST:
    @pytest.fixture(autouse=True)
    def _cleanup_ctx(self):
        yield
        from specstd.workspace import set_context_emp_no, set_context_workspace
        set_context_emp_no(None)
        set_context_workspace(None)

    @pytest.fixture()
    def rest_env(self, tmp_path, monkeypatch):
        """REST 测试环境：隔离 DB + 隔离注册表 + mock 认证。"""
        import os
        os.environ["SG_AUTH_MODE"] = "mock"
        os.environ.pop("SG_ADMIN_ACCOUNTS", None)
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
        from services import user_store
        from services import draft_gates as dg
        db_file = tmp_path / "workbench.db"
        monkeypatch.setattr(user_store, "DB_PATH", db_file)
        monkeypatch.setattr(dg, "DB_PATH", db_file)
        user_store.init_db(db_file)
        from services.auth import _TOKEN_CACHE
        _TOKEN_CACHE.clear()

        from test_specstd.conftest import create_valid_workspace
        repo = create_valid_workspace(tmp_path / "repo")
        inv_dir = repo / "specs" / "system-settings" / "inventory-activity"
        inv_dir.mkdir(parents=True, exist_ok=True)
        fr_lines = "\n".join(f"### FR-{i:03d}: 功能{i} 描述\nAC-{i} 验收{i}\n"
                              for i in range(1, 5))
        (inv_dir / "spec.md").write_text(
            f"# Inventory Activity\n\n## 一、功能描述\n\n{fr_lines}\n",
            encoding="utf-8")
        # T-1000 verdict 修复暴露的存量冲突：fixture 在 module1 之外补的
        # inventory-activity spec 复用 FR-001~004（与 create_valid_workspace 基线
        # FR-001/002 重复，ANCHOR 唯一性 ERROR → 注册拒绝 → 「无激活工作区」）。
        # 真实意图是 inventory-activity 模块独立成库——单独注册并激活。
        inv_repo = tmp_path / "repo-inv"
        for d in ("specs", "changes", "archive"):
            (inv_repo / d).mkdir(parents=True, exist_ok=True)
        (inv_repo / "AGENTS.md").write_text(
            '# WS\n\n## Project Overview\n\nx\n\n## 术语\n\n- FR\n',
            encoding="utf-8")
        import shutil
        shutil.copytree(repo / "specs" / "system-settings",
                        inv_repo / "specs" / "system-settings")
        delta_src = repo / "changes" / "extend-void-scope"
        if delta_src.is_dir():
            shutil.copytree(delta_src, inv_repo / "changes" / "extend-void-scope")
        wsm.register_local("tdm", str(inv_repo), "tdm", activate=True)
        assert wsm.get_active_workspace() is not None

        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield {"client": c, "repo": repo}
        wsm.unregister("tdm")

    def _login(self, client, emp_no="90000002"):
        from services import user_store
        h_admin = _login(client, "90000001")
        h_user = _login(client, emp_no)
        user_store.set_roles(emp_no, ["tester"], actor="90000001")
        user_store.grant_workspace("tdm", emp_no, "90000001")
        return {**h_user, "X-SG-Workspace": "tdm"}

    def test_gaps_endpoint(self, rest_env):
        """GET /api/coverage/gaps 返回三态结构。"""
        client = rest_env["client"]
        headers = self._login(client)
        r = client.get("/api/coverage/gaps", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["fr_total"] >= 4
        assert "gap" in data["lanes"] and "draft" in data["lanes"]
        assert data["fingerprint"]

    def test_backlink_endpoint_readonly(self, rest_env):
        """GET /api/coverage/backlink/{fr} 只读（被测资产 specs/changes 哈希不变）。"""
        import hashlib
        client = rest_env["client"]
        headers = self._login(client)

        def _snapshot():
            digest = hashlib.sha256()
            for root in (rest_env["repo"] / "specs", rest_env["repo"] / "changes"):
                for p in sorted(root.rglob("*")):
                    if p.is_file():
                        digest.update(p.read_bytes())
            return digest.hexdigest()

        before = _snapshot()
        r = client.get("/api/coverage/backlink/FR-001", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["exists"] is True
        assert _snapshot() == before

    def test_next_batch_endpoint(self, rest_env):
        """POST /api/coverage/next-batch 只产草稿不产计划。"""
        client = rest_env["client"]
        headers = self._login(client)
        r = client.post("/api/coverage/next-batch", headers=headers,
                        json={"frs": ["FR-001"], "source_delta": "extend-void-scope"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["produced"], data
        # 草稿已落盘（REST 认证链注入 emp → 落私有区，T-014）且自动登记三闸（gate2 自动跑）
        from specstd.workspace import drafts_dir
        draft_files = list(drafts_dir(emp="90000002").glob("*.yaml"))
        assert draft_files
        from services import draft_gates
        gate = draft_gates.get_gate(data["produced"][0]["draft_id"])
        assert gate is not None and gate["gate2_status"] in ("pass", "fail")

    def test_next_batch_empty_frs_400(self, rest_env):
        client = rest_env["client"]
        headers = self._login(client)
        r = client.post("/api/coverage/next-batch", headers=headers, json={"frs": []})
        assert r.status_code == 400

    def test_review_and_revalidate_endpoints(self, rest_env):
        """POST /drafts/{fn}/review + /revalidate 端点可用（REST 认证链注入 emp）。"""
        from specstd.workspace import drafts_dir
        draft_dir = drafts_dir(emp="90000002")
        draft_dir.mkdir(parents=True, exist_ok=True)
        (draft_dir / "d-300.yaml").write_text(
            "id: IA-TEST-001\ntitle: 测试草稿\n"
            "doc: {given: x, when: y, then: z, covers: [FR-001]}\n"
            "flow: [{call: {method: GET, path: /api/x}}]\nverify: []\n",
            encoding="utf-8")
        from services import draft_gates
        draft_gates.ensure_tables()  # sg_draft_gates 表（monkeypatch DB_PATH 已指向隔离 db）
        draft_gates.register_draft("d-300.yaml", "IA-TEST-001", ["FR-001"],
                                   source_delta="x", created_by="90000002")

        client = rest_env["client"]
        headers = self._login(client)
        r = client.post("/api/drafts/d-300.yaml/review", headers=headers,
                        json={"decision": "approved", "comment": "OK"})
        assert r.status_code == 200, r.text
        assert r.json()["gates"]["g1"] == "approved"
        r2 = client.post("/api/drafts/d-300.yaml/revalidate", headers=headers)
        assert r2.status_code == 200, r2.text
        assert r2.json()["gate2_status"] in ("pass", "fail")


def _login(client, emp_no, name=""):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestPromoteHardGate:
    def test_promote_rejected_without_gate1(self, ctx, monkeypatch):
        """gate1 未 approved：promote 被拒且 scenarios/ 无变更。"""
        from services import draft_gates, draft_promote

        draft_gates.ensure_tables(ctx["db"])
        draft_gates.register_draft("d-118.yaml", "IA-VOID-001", ["FR-001"],
                                   source_delta="x", created_by="t1",
                                   db_path=ctx["db"])
        monkeypatch.setattr(draft_gates, "DB_PATH", ctx["db"])
        before = set(ctx["sc_dir"].rglob("*.yaml"))
        with pytest.raises(draft_promote.PromoteError) as ei:
            draft_promote.promote(
                "d-118.yaml", "system-settings/inventory-activity",
                emp_no="t1", skip_gate=True)
        assert ei.value.code in ("gate_blocked", "gate_failed")
        after = set(ctx["sc_dir"].rglob("*.yaml"))
        assert before == after

    def test_next_batch_only_drafts(self, ctx):
        """「生成下一批」只产草稿：plans 目录无任何产物。"""
        from workbench.backend.services.coverage_gaps import build_next_batch
        batch = build_next_batch(frs=["FR-001", "FR-002"],
                                 source_delta="extend-void-scope")
        assert batch["produced"]
        # 不产生计划：plans_dir 为空
        from specstd.workspace import plans_dir
        plan_files = list(plans_dir().rglob("*"))
        assert not plan_files
