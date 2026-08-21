"""T-973 系统包加载器与分级闸——离线单测（不依赖 DB/HTTP/FastAPI）。

锁定契约：
- manifest 读写与 tier/layout 校验
- 代码型评审闸不可绕：未评审不加载；评审通过 = sha256 绑定；改文件即失配
- config/template/code 三级装配语义（apply_system_package 返回值）
- 模板断言注册期 SELECT-only 确定性校验 + 运行期参数绑定/expect 比对
- TOOLS system:name 命名空间共存 + 裸名/限定名解析 + 按系统注销
- bootstrap 对动态 extensions 包的端到端装配
"""

import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from engine import system_package  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.tool_registry import (  # noqa: E402
    TOOLS,
    register_tool,
    resolve_tool,
    unregister_system_tools,
)

EXT_CODE = '''\
"""demo extensions（测试用）。"""

from engine.tool_registry import register_tool


def register(registry, env_config, db=None):
    registry.step("boom", lambda body, rctx, ns, record: "boom-ok")
    register_tool("boom", desc="demo 扩展步骤")
'''


@pytest.fixture()
def dyn_root(tmp_path, monkeypatch):
    """动态系统包根：{tmp}/systems，隔离仓内包。"""
    root = tmp_path / "systems"
    root.mkdir()
    monkeypatch.setenv("SG_SYSTEMS_ROOT", str(root))
    return root


def _make_pkg(root, name, manifest: dict, extensions: str | None = None,
              assertions: str | None = None, env_yaml: str | None = None):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    system_package.save_manifest(name, manifest)
    if extensions is not None:
        (pkg / "extensions.py").write_text(extensions, encoding="utf-8")
    if assertions is not None:
        (pkg / "assertions.yaml").write_text(assertions, encoding="utf-8")
    if env_yaml is not None:
        (pkg / "config").mkdir(exist_ok=True)
        (pkg / "config" / "env.sit.yaml").write_text(env_yaml, encoding="utf-8")
    return pkg


# ══════════════════════════════════════════════════════════
# manifest 与评审闸
# ══════════════════════════════════════════════════════════

class TestManifest:
    def test_roundtrip_and_defaults(self, dyn_root):
        _make_pkg(dyn_root, "demo", {"tier": "config"})
        m = system_package.load_manifest("demo")
        assert m["tier"] == "config"
        assert m["layout"] == "package"      # 缺省 package
        assert m["enabled"] is True

    def test_invalid_tier_rejected(self, dyn_root):
        _make_pkg(dyn_root, "bad", {"tier": "wizard"})
        with pytest.raises(ValueError, match="tier 非法"):
            system_package.load_manifest("bad")

    def test_missing_manifest_returns_empty(self, dyn_root):
        (dyn_root / "ghost").mkdir()
        assert system_package.load_manifest("ghost") == {}


class TestReviewGate:
    def test_unreviewed_not_loadable(self, dyn_root):
        _make_pkg(dyn_root, "demo", {"tier": "code", "layout": "extensions"},
                  extensions=EXT_CODE)
        gate = system_package.extension_gate_status("demo")
        assert gate["present"] and not gate["loadable"]
        assert "待评审" in gate["reason"]

    def test_approval_binds_sha256(self, dyn_root):
        pkg = _make_pkg(dyn_root, "demo", {"tier": "code", "layout": "extensions"},
                        extensions=EXT_CODE)
        sha = system_package.sha256_of(pkg / "extensions.py")
        m = system_package.load_manifest("demo")
        m["review"] = {"approved_by": "ad1", "approved_at": "2026-08-21T00:00:00",
                       "sha256": sha}
        system_package.save_manifest("demo", m)
        gate = system_package.extension_gate_status("demo")
        assert gate["loadable"] and gate["approved_by"] == "ad1"

    def test_file_change_breaks_gate(self, dyn_root):
        """闸不可绕：评审后改文件 → 指纹失配自动回到未评审态。"""
        pkg = _make_pkg(dyn_root, "demo", {"tier": "code", "layout": "extensions"},
                        extensions=EXT_CODE)
        sha = system_package.sha256_of(pkg / "extensions.py")
        m = system_package.load_manifest("demo")
        m["review"] = {"approved_by": "ad1", "sha256": sha}
        system_package.save_manifest("demo", m)
        (pkg / "extensions.py").write_text(EXT_CODE + "\n# 改动\n", encoding="utf-8")
        gate = system_package.extension_gate_status("demo")
        assert not gate["loadable"] and "失配" in gate["reason"]

    def test_apply_gated_does_not_execute(self, dyn_root):
        _make_pkg(dyn_root, "demo", {"tier": "code", "layout": "extensions"},
                  extensions=EXT_CODE)
        reg = Registry()
        how = system_package.apply_system_package(reg, "demo", {}, None)
        assert how == "extensions-gated"
        assert "boom" not in reg.step_handlers, "未评审代码不得执行"

    def test_apply_approved_executes(self, dyn_root):
        pkg = _make_pkg(dyn_root, "demo", {"tier": "code", "layout": "extensions"},
                        extensions=EXT_CODE)
        sha = system_package.sha256_of(pkg / "extensions.py")
        m = system_package.load_manifest("demo")
        m["review"] = {"approved_by": "ad1", "sha256": sha}
        system_package.save_manifest("demo", m)
        reg = Registry()
        how = system_package.apply_system_package(reg, "demo", {}, None)
        assert how == "extensions"
        assert "boom" in reg.step_handlers
        assert TOOLS.get("demo:boom") is not None, "注册上下文应命名空间化 tool 元数据"


# ══════════════════════════════════════════════════════════
# 三级装配语义
# ══════════════════════════════════════════════════════════

class TestApplyTiers:
    def test_config_tier_registers_nothing(self, dyn_root):
        _make_pkg(dyn_root, "cfg", {"tier": "config", "layout": "extensions"},
                  env_yaml="tdm_base: http://x\n")
        reg = Registry()
        assert system_package.apply_system_package(reg, "cfg", {}, None) == "config"
        assert not reg.oracles and not reg.step_handlers

    def test_template_tier_registers_assertions(self, dyn_root):
        _make_pkg(dyn_root, "tpl", {"tier": "template", "layout": "extensions"},
                  assertions="assertions:\n"
                             "  - name: cnt_ok\n"
                             "    desc: 计数断言\n"
                             "    sql: 'SELECT COUNT(*) AS c FROM t WHERE id = :id'\n"
                             "    expect: {c: '#number'}\n")
        reg = Registry()
        assert system_package.apply_system_package(reg, "tpl", {}, None) == "config"
        assert "cnt_ok" in reg.oracles


# ══════════════════════════════════════════════════════════
# 模板断言
# ══════════════════════════════════════════════════════════

class TestTemplateAssertions:
    def test_write_sql_rejected_at_registration(self, dyn_root):
        _make_pkg(dyn_root, "tpl", {"tier": "template", "layout": "extensions"},
                  assertions="assertions:\n"
                             "  - name: evil\n"
                             "    sql: 'DELETE FROM t'\n")
        with pytest.raises(ValueError, match="SELECT"):
            system_package.register_assertions(Registry(), "tpl")

    def test_multi_statement_rejected(self, dyn_root):
        _make_pkg(dyn_root, "tpl", {"tier": "template", "layout": "extensions"},
                  assertions="assertions:\n"
                             "  - name: two\n"
                             "    sql: 'SELECT 1; DROP TABLE t'\n")
        with pytest.raises(ValueError, match="多语句"):
            system_package.register_assertions(Registry(), "tpl")

    def _oracle_setup(self, dyn_root, expect, rows):
        _make_pkg(dyn_root, "tpl", {"tier": "template", "layout": "extensions"},
                  assertions=f"assertions:\n"
                             f"  - name: cnt\n"
                             f"    sql: 'SELECT COUNT(*) AS c FROM t WHERE id = :id'\n"
                             f"    expect: {expect}\n")
        reg = Registry()
        system_package.register_assertions(reg, "tpl")
        return reg.get_oracle("cnt"), rows

    def test_runtime_match_and_params(self, dyn_root):
        oracle, _ = self._oracle_setup(dyn_root, "{c: '#number'}", None)

        class FakeDb:
            def __init__(self, rows):
                self.rows = rows
                self.seen = None

            def query(self, sql, params=None, max_rows=1000):
                self.seen = (sql, params)
                return self.rows

        ok_db, bad_db = FakeDb([{"c": 3}]), FakeDb([{"c": "not-a-number"}])
        ok_rec = type("Rec", (), {"db_traces": []})()
        ns = {"id": "42"}
        oracle({"id": "{{id}}"}, type("R", (), {"db": ok_db})(), ns, ok_rec)
        assert ok_db.seen[1] == {"id": "42"}, "参数应插值后命名绑定"
        # 失配路径：c 非 number
        with pytest.raises(AssertionError, match="失败"):
            oracle({"id": "{{id}}"}, type("R", (), {"db": bad_db})(), ns,
                   type("Rec2", (), {"db_traces": []})())

    def test_runtime_no_rows_fails(self, dyn_root):
        oracle, _ = self._oracle_setup(dyn_root, "", None)

        class EmptyDb:
            def query(self, sql, params=None, max_rows=1000):
                return []

        with pytest.raises(AssertionError, match="无结果"):
            oracle({}, type("R", (), {"db": EmptyDb()})(), {},
                   type("R2", (), {"db_traces": []})())

    def test_runtime_db_missing_skips(self, dyn_root):
        from engine.scenario_runner import SkipScenario
        oracle, _ = self._oracle_setup(dyn_root, "{c: '#number'}", None)
        rctx = type("R", (), {"db": None})()
        with pytest.raises(SkipScenario):
            oracle({}, rctx, {}, type("Rec", (), {"db_traces": []})())


# ══════════════════════════════════════════════════════════
# TOOLS 命名空间
# ══════════════════════════════════════════════════════════

class TestToolNamespace:
    def test_same_name_coexists_across_systems(self):
        register_tool("dup", desc="a", system="sysa")
        register_tool("dup", desc="b", system="sysb")
        assert TOOLS["sysa:dup"].desc == "a"
        assert TOOLS["sysb:dup"].desc == "b"

    def test_resolve_bare_and_qualified(self):
        register_tool("uniq_x", desc="x", system="sysx")
        spec, handler = resolve_tool("sysx:uniq_x")
        assert spec is not None and handler == "uniq_x"
        spec2, handler2 = resolve_tool("uniq_x")
        assert spec2 is spec and handler2 == "uniq_x"

    def test_resolve_ambiguous_bare_name(self):
        register_tool("amb", desc="a", system="sysa")
        register_tool("amb", desc="b", system="sysb")
        spec, _ = resolve_tool("amb")
        assert spec is None, "多系统同名裸名不得静默命中"

    def test_reregister_overwrites_same_system(self):
        register_tool("hot", desc="v1", system="sysh")
        register_tool("hot", desc="v2", system="sysh")
        assert TOOLS["sysh:hot"].desc == "v2"

    def test_unregister_system_tools(self):
        register_tool("gone", desc="", system="sysg")
        n = unregister_system_tools("sysg")
        assert n == 1 and "sysg:gone" not in TOOLS


# ══════════════════════════════════════════════════════════
# bootstrap 端到端 + env 加载
# ══════════════════════════════════════════════════════════

class TestBootstrapIntegration:
    def test_build_registry_dynamic_code_system(self, dyn_root):
        pkg = _make_pkg(dyn_root, "demo", {"tier": "code", "layout": "extensions"},
                        extensions=EXT_CODE,
                        env_yaml="demo_base: http://demo\n")
        sha = system_package.sha256_of(pkg / "extensions.py")
        m = system_package.load_manifest("demo")
        m["review"] = {"approved_by": "ad1", "sha256": sha}
        system_package.save_manifest("demo", m)

        from engine.bootstrap import build_registry, load_system_env
        cfg = load_system_env("demo", "sit")
        assert cfg["demo_base"] == "http://demo"
        reg = build_registry("demo", cfg)
        assert "boom" in reg.step_handlers
        assert "call" in reg.step_handlers, "内置步骤仍须在位"

    def test_build_registry_unapproved_degrades(self, dyn_root):
        _make_pkg(dyn_root, "demo2", {"tier": "code", "layout": "extensions"},
                  extensions=EXT_CODE)
        from engine.bootstrap import build_registry
        reg = build_registry("demo2", {})
        assert "boom" not in reg.step_handlers
        assert "call" in reg.step_handlers

    def test_load_package_env_placeholder(self, dyn_root, monkeypatch):
        monkeypatch.setenv("DEMO_SECRET", "s3cr3t")
        _make_pkg(dyn_root, "cfg2", {"tier": "config", "layout": "extensions"},
                  env_yaml="secret: ${DEMO_SECRET:fallback}\n"
                           "plain: ${NO_SUCH_VAR:def2}\n")
        cfg = system_package.load_package_env("cfg2", "sit")
        assert cfg["secret"] == "s3cr3t"
        assert cfg["plain"] == "def2"
