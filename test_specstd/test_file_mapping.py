"""文件映射台账化测试（K-xxx：工具查表定位文件，扫描只做自愈兜底）。

覆盖：read_scenario 台账定位优先、未命中回退扫描、扫描后自愈落台账；
read_spec 的 drafts 路径迁移指引（草稿入库后旧路径给出可执行去向）。
"""

import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from mcp_server.tools import scenario_tools  # noqa: E402
from mcp_server.tools import spec_reader  # noqa: E402

SCENARIO_YAML = """id: TL-RC-014
version: "0.1"
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - status: {eq: 200}
"""


@pytest.fixture()
def iso_env(tmp_path, monkeypatch):
    """隔离场景库 + 台账查询（monkeypatch ledger 返回构造数据）。"""
    lib = tmp_path / "scenarios" / "inv"
    lib.mkdir(parents=True)
    (lib / "TL-RC-014.yaml").write_text(SCENARIO_YAML, encoding="utf-8")
    monkeypatch.setattr(scenario_tools, "SCENARIOS_ROOT", tmp_path / "scenarios")
    # _lookup_scenario_path 用 SG_ROOT 拼映射路径 → 一并指向 tmp
    monkeypatch.setattr(scenario_tools, "SG_ROOT", tmp_path)

    from services import ledger_store
    # 台账查询隔离：scenarios 表返回构造映射；upsert 拦截记录调用
    calls = {"upsert": 0}

    def fake_query_scenarios(*a, **k):
        return [{"id": "TL-RC-014", "file_path": "scenarios/inv/TL-RC-014.yaml"}]

    def fake_query_drafts(*a, **k):
        return [{"filename": "TL-RC-014.yaml", "status": "promoted",
                 "module": "inv", "scenario_id": "TL-RC-014"}]

    def fake_upsert(items, *a, **k):
        calls["upsert"] += 1
        return len(items)

    monkeypatch.setattr(ledger_store, "query_scenarios", fake_query_scenarios)
    monkeypatch.setattr(ledger_store, "query_drafts", fake_query_drafts)
    monkeypatch.setattr(ledger_store, "upsert_scenarios", fake_upsert)
    return calls


class TestReadScenarioLedgerFirst:
    def test_lookup_from_ledger(self, iso_env, monkeypatch):
        """台账命中 → 按映射路径读取（不触发全量扫描）。"""
        calls = iso_env
        # 让台账指向一个真实存在的文件
        from services import ledger_store

        def fake_query(*a, **k):
            return [{"id": "TL-RC-014",
                     "file_path": "scenarios/inv/TL-RC-014.yaml"}]
        monkeypatch.setattr(ledger_store, "query_scenarios", fake_query)

        r = scenario_tools._handle_read_scenario({"id": "TL-RC-014"})
        assert "TL-RC-014" in r[0].text
        # 台账命中不触发 upsert 自愈
        assert calls["upsert"] == 0

    def test_fallback_scan_when_ledger_miss(self, iso_env, monkeypatch):
        """台账未命中 → 回退扫描读取 + 自愈落台账。"""
        calls = iso_env
        from services import ledger_store
        monkeypatch.setattr(ledger_store, "query_scenarios", lambda *a, **k: [])

        r = scenario_tools._handle_read_scenario({"id": "TL-RC-014"})
        assert "TL-RC-014" in r[0].text
        assert calls["upsert"] >= 1, "回退扫描后应自愈落台账"

    def test_lookup_missing_scenario(self, iso_env):
        """ID 不存在 → 错误提示。"""
        r = scenario_tools._handle_read_scenario({"id": "NONEXIST-999"})
        assert "不存在" in r[0].text


class TestMigrationHint:
    def test_hint_promoted_draft(self, iso_env):
        """草稿路径已入库 → 指引指向库内当前路径。"""
        h = spec_reader._migration_hint("drafts/TL-RC-014.yaml")
        assert "已入库" in h and "scenarios/inv/TL-RC-014.yaml" in h
        assert "read_scenario" in h

    def test_hint_sg_prefix(self, iso_env):
        h = spec_reader._migration_hint("sg://drafts/TL-RC-014.yaml")
        assert "已入库" in h

    def test_no_hint_non_draft_path(self, iso_env):
        assert spec_reader._migration_hint("scenarios/inv/TL-RC-014.yaml") == ""
        assert spec_reader._migration_hint("specs/employee/x/spec.md") == ""

    def test_no_hint_unmapped(self, iso_env, monkeypatch):
        from services import ledger_store
        monkeypatch.setattr(ledger_store, "query_scenarios", lambda *a, **k: [])
        monkeypatch.setattr(ledger_store, "query_drafts", lambda *a, **k: [])
        assert spec_reader._migration_hint("drafts/NONEXIST-999.yaml") == ""

    def test_read_spec_returns_hint(self, iso_env):
        """read_spec 草稿旧路径 → 错误消息附迁移指引。"""
        r = spec_reader._handle_read_spec({"path": "drafts/TL-RC-014.yaml"})
        assert "文件不存在" in r[0].text
        assert "已入库" in r[0].text
