"""K-055 微服务体系适配单测：多 schema DB 注册表 + 服务前缀 call 路由。"""

import os
import sys
from types import SimpleNamespace

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.db_oracle import normalize_db_config, build_db_connections  # noqa: E402
from engine.scenario_runner import RunContext, step_db_query, step_call, SkipScenario  # noqa: E402
from engine.execution_record import ExecutionRecord  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.dependency_graph import DependencyGraph  # noqa: E402


# ══════════════════════════════════════════════════════════
# R2：db 段双形态归一化
# ══════════════════════════════════════════════════════════

class TestNormalizeDbConfig:
    def test_legacy_single_dict(self):
        cfg = {"host": "h1", "user": "u", "password": "p", "name": "hr_center"}
        conns, default = normalize_db_config(cfg)
        assert default == "default"
        assert conns == {"default": cfg}

    def test_multi_schema_dict(self):
        cfg = {
            "default": {"host": "h1", "user": "u", "name": "hr_center"},
            "tdm": {"host": "h2", "user": "u", "name": "tdm"},
        }
        conns, default = normalize_db_config(cfg)
        assert default == "default"
        assert set(conns) == {"default", "tdm"}

    def test_no_default_key_takes_first(self):
        cfg = {"tdm": {"host": "h2", "user": "u", "name": "tdm"}}
        conns, default = normalize_db_config(cfg)
        assert default == "tdm"

    def test_empty(self):
        assert normalize_db_config(None) == ({}, "")
        assert normalize_db_config({}) == ({}, "")

    def test_entries_without_host_filtered(self):
        cfg = {"default": {"host": "h1", "user": "u"}, "note": "不是连接"}
        conns, _ = normalize_db_config(cfg)
        assert set(conns) == {"default"}


class TestBuildDbConnections:
    def test_build_and_probe(self, monkeypatch):
        created = []

        class FakeDb:
            def __init__(self, **kw):
                created.append(kw)
            def scalar(self, sql):
                return 1

        monkeypatch.setattr("engine.db_oracle.ReadOnlyDb", lambda **kw: FakeDb(**kw))
        dbs, default = build_db_connections({
            "default": {"host": "h1", "user": "u", "password": "p", "name": "hr_center"},
            "tdm": {"host": "h2", "user": "u", "password": "p2", "name": "tdm"},
        })
        assert default == "default"
        assert set(dbs) == {"default", "tdm"}
        assert created[1]["database"] == "tdm"

    def test_failed_connection_skipped(self, monkeypatch):
        def fake_new(**kw):
            if kw["host"] == "bad":
                raise RuntimeError("连不上")
            class FakeDb:
                def scalar(self, sql):
                    return 1
            return FakeDb()

        monkeypatch.setattr("engine.db_oracle.ReadOnlyDb", fake_new)
        dbs, default = build_db_connections({
            "default": {"host": "h1", "user": "u", "name": "hr_center"},
            "tdm": {"host": "bad", "user": "u", "name": "tdm"},
        })
        assert set(dbs) == {"default"}  # 坏连接降级跳过，不阻断其他 schema

    def test_password_fallback(self, monkeypatch):
        seen = []

        class FakeDb:
            def __init__(self, **kw):
                seen.append(kw["password"])
            def scalar(self, sql):
                return 1

        monkeypatch.setattr("engine.db_oracle.ReadOnlyDb", lambda **kw: FakeDb(**kw))
        build_db_connections(
            {"host": "h1", "user": "u", "password": "", "name": "hr_center"},
            password_fallback=lambda cfg: "fallback-pw")
        assert seen == ["fallback-pw"]


# ══════════════════════════════════════════════════════════
# R2：step_db_query schema 参数
# ══════════════════════════════════════════════════════════

def _rctx_with_dbs(dbs, default_db=None):
    return RunContext(registry=Registry(), env_config={}, token_provider=None,
                      graph=DependencyGraph([]), run_dir=".",
                      db=default_db, dbs=dbs)


class TestDbQuerySchema:
    def test_schema_routing(self):
        calls = []

        class FakeDb:
            def __init__(self, name):
                self.name = name
            def query(self, sql):
                calls.append((self.name, sql))
                return [{"v": self.name}]

        dbs = {"default": FakeDb("hr_center"), "tdm": FakeDb("tdm")}
        rctx = _rctx_with_dbs(dbs, dbs["default"])
        record = ExecutionRecord(scenario_id="T")
        out = step_db_query({"sql": "SELECT 1", "schema": "tdm"}, rctx, {}, record)
        assert out == [{"v": "tdm"}]
        assert calls == [("tdm", "SELECT 1")]

    def test_default_schema_uses_rctx_db(self):
        class FakeDb:
            def query(self, sql):
                return [{"v": "d"}]

        rctx = _rctx_with_dbs({"default": FakeDb()}, None)
        record = ExecutionRecord(scenario_id="T")
        out = step_db_query({"sql": "SELECT 1"}, rctx, {}, record)
        assert out == [{"v": "d"}]

    def test_missing_schema_skips(self):
        rctx = _rctx_with_dbs({}, None)
        record = ExecutionRecord(scenario_id="T")
        with pytest.raises(SkipScenario, match="schema 'uac' 不可用"):
            step_db_query({"sql": "SELECT 1", "schema": "uac"}, rctx, {}, record)


# ══════════════════════════════════════════════════════════
# R1：call service 路由
# ══════════════════════════════════════════════════════════

class TestServiceRouting:
    def _rctx(self):
        env = {
            "tdm_base": "http://gw/femsp/hr-tdm",
            "hr_center_base": "http://gw/femsp/hr-center",
            "accounts": {"default": {"ad": "a", "emp_no": "1"}},
        }
        return RunContext(registry=Registry(), env_config=env, token_provider=None,
                          graph=DependencyGraph([]), run_dir=".")

    def test_default_service_tdm(self):
        rctx = self._rctx()
        c = rctx.http_client("default")
        assert c.base_url == "http://gw/femsp/hr-tdm"

    def test_named_service(self):
        rctx = self._rctx()
        c = rctx.http_client("default", "hr_center")
        assert c.base_url == "http://gw/femsp/hr-center"

    def test_missing_service_base_skips(self):
        rctx = self._rctx()
        with pytest.raises(SkipScenario, match="缺少 uac_base"):
            rctx.http_client("default", "uac")

    def test_clients_cached_per_service(self):
        rctx = self._rctx()
        c1 = rctx.http_client("default")
        c2 = rctx.http_client("default", "hr_center")
        c3 = rctx.http_client("default")
        assert c1 is c3 and c1 is not c2  # 按 (service, account) 分键缓存

    def test_step_call_service_field(self, monkeypatch):
        rctx = self._rctx()
        seen = {}

        class FakeClient:
            def request(self, method, path, **kw):
                seen["base"] = self.base_url
                seen["path"] = path
                return SimpleNamespace(status_code=200, headers={}, json=lambda: {"ok": True}, text="{}")

        fake = FakeClient()
        fake.base_url = "http://gw/femsp/hr-center"
        monkeypatch.setattr(RunContext, "http_client",
                            lambda self, account, service="tdm": (seen.update(service=service), fake)[1])
        record = ExecutionRecord(scenario_id="T")
        step_call({"method": "POST", "path": "/api/permission/auth/data-info",
                   "service": "hr_center", "json": {"empNo": "1"}}, rctx, {}, record)
        assert seen["service"] == "hr_center"


# ══════════════════════════════════════════════════════════
# R4/R5：resolve_account / precheck_permission
# ══════════════════════════════════════════════════════════

class _FakeScope:
    def __init__(self, has=True, corps=(), corp_all=False, raw_status="ok"):
        self._has = has
        self.corp_codes = set(corps)
        self.corp_all = corp_all
        self.raw_status = raw_status
        self.raw_message = ""
        self.level_all = True
        self.levels = set()
        self.vm_all = True
        self.vm_codes = set()
    def has_any(self):
        return self._has
    def summary(self):
        return "fake-scope"


class _FakeOracle:
    def __init__(self, scopes):
        self.scopes = scopes  # emp_no -> _FakeScope
    def fetch_scope(self, emp_no, resource_code, account=None):
        return self.scopes.get(emp_no, _FakeScope(has=False))


def _rctx_perm(candidates, scopes):
    class FakeDb:
        def query(self, sql, params=None):
            return candidates
    rctx = RunContext(registry=Registry(), env_config={"hr_center_base": "http://x"},
                      token_provider=SimpleNamespace(INTERNAL_ACCOUNT="__internal__",
                                                     _internal_cfg=None),
                      graph=DependencyGraph([]), run_dir=".",
                      db=FakeDb(), dbs={"default": FakeDb()})
    rctx.shared_ns["env"] = {"resource_code": "RC-X"}
    rctx._hr_oracle = _FakeOracle(scopes)
    return rctx


class TestResolveAccount:
    CANDS = [{"emp_no": "80016782", "username": "zhangsan", "emp_name": "张三", "role_code": "TDM_ADMIN"}]

    def test_resolve_success(self):
        from systems.tdm.steps import step_resolve_account
        rctx = _rctx_perm(self.CANDS, {"80016782": _FakeScope(has=True, corps=("1002",))})
        out = step_resolve_account({"resource_code": "RC-X", "corp_code": "1002"},
                                   rctx, {}, ExecutionRecord(scenario_id="T"))
        assert out["emp_no"] == "80016782"
        assert out["ad"] == "zhangsan"

    def test_no_candidates_skips(self):
        from systems.tdm.steps import step_resolve_account
        rctx = _rctx_perm([], {})
        with pytest.raises(SkipScenario, match="找不到绑定资源码"):
            step_resolve_account({"resource_code": "RC-X"}, rctx, {}, ExecutionRecord(scenario_id="T"))

    def test_corp_mismatch_skips(self):
        from systems.tdm.steps import step_resolve_account
        rctx = _rctx_perm(self.CANDS, {"80016782": _FakeScope(has=True, corps=("1174",))})
        with pytest.raises(SkipScenario, match="未通过复核"):
            step_resolve_account({"resource_code": "RC-X", "corp_code": "1002"},
                                 rctx, {}, ExecutionRecord(scenario_id="T"))

    def test_corp_all_passes_corp_check(self):
        from systems.tdm.steps import step_resolve_account
        rctx = _rctx_perm(self.CANDS, {"80016782": _FakeScope(has=True, corp_all=True)})
        out = step_resolve_account({"resource_code": "RC-X", "corp_code": "1002"},
                                   rctx, {}, ExecutionRecord(scenario_id="T"))
        assert out["emp_no"] == "80016782"


class TestPrecheckPermission:
    def test_no_permission_skips(self):
        from systems.tdm.steps import step_precheck_permission
        rctx = _rctx_perm([], {})
        rctx.env["accounts"] = {"default": {"ad": "a", "emp_no": "1"}}
        rctx._hr_oracle = _FakeOracle({"1": _FakeScope(has=False)})
        with pytest.raises(SkipScenario, match="无任何数据权限"):
            step_precheck_permission({"account": "default", "resource_code": "RC-X"},
                                     rctx, {}, ExecutionRecord(scenario_id="T"))

    def test_has_permission_passes(self):
        from systems.tdm.steps import step_precheck_permission
        rctx = _rctx_perm([], {})
        rctx.env["accounts"] = {"default": {"ad": "a", "emp_no": "1"}}
        rctx._hr_oracle = _FakeOracle({"1": _FakeScope(has=True, corps=("1002",))})
        out = step_precheck_permission({"account": "default", "resource_code": "RC-X",
                                        "corp_code": "1002"}, rctx, {}, ExecutionRecord(scenario_id="T"))
        assert out["has_any"]
