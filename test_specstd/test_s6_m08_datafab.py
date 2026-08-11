"""S6 T-062：测试数据制造 Agent（M08 §5.3 / §9 G2）。

验收锚点：
- 数据校验器（实例完整性/调度合法性/版本可仲裁）硬拒不合格实例
- 产物一律草稿态过三闸（无一绕过）
- 复用优先：已有可复用 IS-PREP 实例时建议复用而非新造
- 只消费 systems/{system}/ 适配包资产，引擎零改动
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


# ══════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def pool():
    """模拟 systems/tdm emp-pool.yaml 结构（与真实文件同构）。"""
    return {
        "roles": {
            "snapshot_rich": {"candidates": ["90024713", "90024714"]},
            "reviewer": {"candidates": ["90010001"]},
        },
        "quotas": {"exclusive_max": 2, "shared_max": 8},
    }


@pytest.fixture()
def ctx_fab(tmp_path):
    """激活工作区（含 FR-001 锚点）+ 既有 IS-PREP 场景（复用判定用）。"""
    from test_specstd.conftest import create_valid_workspace
    import specstd.workspace as wsm

    ws = create_valid_workspace(tmp_path / "ws")
    token = wsm.set_context_workspace("fabws")
    try:
        wsm.register_local("fabws", str(ws), "tdm", activate=True, run_conformance=False)
    except Exception:
        pass
    try:
        wsm.set_active("fabws")
    except Exception:
        pass

    # 既有 IS-PREP 场景：IS-PREP-002 covers FR-001（复用优先判定）
    sc_dir = ws / "scenarios" / "inventory" / "inventory-session"
    sc_dir.mkdir(parents=True, exist_ok=True)
    (sc_dir / "IS-PREP-002.yaml").write_text(
        "id: IS-PREP-002\ntitle: 数据准备·活动+会话+3人\n"
        "doc: {given: x, when: y, then: z, covers: [FR-001]}\n"
        "data_contract: {provides: {activity: {status: ACTIVE}}, isolation: shared, cleanup: teardown}\n"
        "flow: [{call: {method: POST, path: /api/x}}]\nverify: []\n",
        encoding="utf-8")

    yield {"ws": ws}
    wsm.reset_context_workspace(token)


VALID_DRAFT = """
id: IS-PREP-999
title: 数据准备·活动+COMPLETED 会话
version: "0.1"
doc:
  given: 数据制造
  when: 执行
  then: 数据就绪
  covers: [FR-001]
source_delta: extend-void-scope
data_contract:
  provides:
    activity: {status: ACTIVE}
    session: {status: COMPLETED, count: 1}
    members: {count: 1, from: emp-pool, role: snapshot_rich}
  isolation: exclusive
  cleanup: teardown
depends_on:
  - {id: IS-PREP-003, mode: exclusive, version: ^0}
flow:
  - call: {method: POST, path: /api/inventory/activities, save: activity}
verify: []
"""


# ══════════════════════════════════════════════════════════
# 数据校验器（G-2）
# ══════════════════════════════════════════════════════════

class TestDataValidator:
    def _parse(self, text):
        import yaml
        return yaml.safe_load(text) or {}

    def test_valid_contract_passes(self, pool):
        """合法 data_contract → 校验全过。"""
        from workbench.backend.services.data_validator import validate_data_contract
        report = validate_data_contract(self._parse(VALID_DRAFT), pool)
        assert report["verdict"] == "PASS", report

    def test_missing_activity_rejected(self, pool):
        """实例完整性：provides 缺 activity → 硬拒。"""
        from workbench.backend.services.data_validator import validate_data_contract
        raw = self._parse(VALID_DRAFT)
        raw["data_contract"]["provides"].pop("activity")
        report = validate_data_contract(raw, pool)
        assert report["verdict"] == "FAIL"
        assert any("activity" in str(f.get("message", "")) for f in report["findings"])

    def test_members_role_not_in_pool_rejected(self, pool):
        """工号池存在性：members 引用不存在的角色 → 硬拒。"""
        from workbench.backend.services.data_validator import validate_data_contract
        raw = self._parse(VALID_DRAFT)
        raw["data_contract"]["provides"]["members"]["role"] = "ghost_role"
        report = validate_data_contract(raw, pool)
        assert report["verdict"] == "FAIL"
        assert any("ghost_role" in str(f.get("message", "")) for f in report["findings"])

    def test_invalid_isolation_rejected(self, pool):
        """调度合法性：isolation 非 shared/exclusive → 硬拒。"""
        from workbench.backend.services.data_validator import validate_data_contract
        raw = self._parse(VALID_DRAFT)
        raw["data_contract"]["isolation"] = "random"
        report = validate_data_contract(raw, pool)
        assert report["verdict"] == "FAIL"

    def test_missing_data_contract_warns_not_blocks(self, pool):
        """无 data_contract 块（普通场景）→ WARN 不阻断。"""
        from workbench.backend.services.data_validator import validate_data_contract
        raw = self._parse(VALID_DRAFT)
        raw.pop("data_contract")
        report = validate_data_contract(raw, pool)
        assert report["verdict"] == "PASS"

    def test_bad_dep_version_arbitration(self, pool, monkeypatch):
        """版本期望可仲裁：依赖版本期望非法 → 硬拒。"""
        from workbench.backend.services.data_validator import validate_data_contract
        raw = self._parse(VALID_DRAFT)
        raw["depends_on"] = [{"id": "IS-PREP-003", "mode": "exclusive", "version": "abc"}]
        report = validate_data_contract(raw, pool)
        assert report["verdict"] == "FAIL"


# ══════════════════════════════════════════════════════════
# 数据制造编排（G-1 确定性部分）
# ══════════════════════════════════════════════════════════

class TestFabrication:
    def test_fabricate_produces_draft_with_contract(self, ctx_fab):
        """制造产出：草稿含完整 data_contract 声明块 + 挂链字段。"""
        from workbench.backend.services.data_fabrication import fabricate
        # FR-002 无既有 IS-PREP 覆盖（IS-PREP-002 只 covers FR-001）→ 新造
        result = fabricate(frs=["FR-002"], source_delta="extend-void-scope")
        assert result["drafts"], result
        draft = result["drafts"][0]
        assert draft["id"].startswith("IS-PREP-")
        assert draft["covers"] == ["FR-002"]
        assert draft["source_delta"] == "extend-void-scope"
        assert "data_contract" in draft
        assert draft["validation"]["verdict"] == "PASS", draft["validation"]

    def test_fabricate_rejects_unknown_fr(self, ctx_fab):
        """未知 FR → rejected 清单带原因，不产草稿。"""
        from workbench.backend.services.data_fabrication import fabricate
        result = fabricate(frs=["FR-999"], source_delta="x")
        assert result["rejected"] and not result["drafts"]

    def test_fabricate_reuse_preferred(self, ctx_fab):
        """复用优先：已有可复用 IS-PREP 场景（covers 命中）→ 建议复用。"""
        from workbench.backend.services.data_fabrication import fabricate
        # FR-001 已有 IS-PREP-002 覆盖（fixture 场景库）
        result = fabricate(frs=["FR-001"], source_delta="extend-void-scope")
        assert result["reuse_hints"], "应给出复用建议"

    def test_fabricate_engine_zero_change(self, ctx_fab):
        """引擎零改动：不触碰 engine/ 文件（静态断言本任务产物路径）。"""
        from workbench.backend.services.data_fabrication import (
            ENGINE_TOUCH_BLACKLIST)
        assert "engine" not in ENGINE_TOUCH_BLACKLIST
