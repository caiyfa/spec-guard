"""preflight 执行前依赖预检扫描测试（T-311）。

背景：EX-92a9252f 选中 TL-RC-014 执行——账号别名 platformNoCorp 未在环境配置
accounts 定义，跑完才 SKIP（output.log 只剩「账号别名未定义」）。预检扫描在
确认执行弹窗前静态比对闭包内全部场景的执行依赖（账号/env 键/跨场景变量引用），
缺失先行预警，避免白跑。

验证：
1. 静态兜底：flow 的 as:/account: 账号别名、{{env.*}} 键、{{上游ID.*}} 引用可正则提取
2. requires 声明与静态提取合并去重（格式 2.3.0 声明段）
3. 缺失比对：accounts 缺失 / env 键缺失 / 跨场景引用不在闭包
4. 闭包展开：选中场景的 depends_on 上游一并扫描
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

from services import preflight  # noqa: E402


def _scenario_yaml(sid, flow="", requires=None, depends="[]"):
    """最小场景 YAML；requires 为 None 时不写该段（测静态兜底）。"""
    req = ""
    if requires is not None:
        import yaml as _y
        req = f"requires: {_y.safe_dump(requires, default_flow_style=True).strip()}\n"
    return (
        f"id: {sid}\ntitle: {sid} 标题\nversion: '0.1'\ndoc:\n  given: [g]\n"
        f"  when: [w]\n  then: [t]\n  covers: [FR-X]\ndepends_on: {depends}\n"
        f"{req}flow:\n{flow}"
    )


@pytest.fixture()
def lib(tmp_path):
    """假场景库：{tmp}/scenarios/**/X.yaml；返回场景库根。"""
    root = tmp_path / "scenarios"
    root.mkdir()
    return root


def _write(lib, sid, text):
    d = lib / sid[0:2]
    d.mkdir(exist_ok=True)
    (d / f"{sid}.yaml").write_text(text, encoding="utf-8")


def _env_config(accounts=None, extra=None):
    cfg = {"accounts": accounts or {"default": {"ad": "u1", "emp_no": "1"}},
           "resource_code": "TDM_X", "vars": {"inv_code": "INV"}}
    if extra:
        cfg.update(extra)
    return cfg


# ══════════════════════════════════════════════════════════
# 静态提取
# ══════════════════════════════════════════════════════════

class TestStaticExtraction:
    def test_extract_accounts_from_as(self, lib):
        """EX-92a9252f 案例：flow as: platformNoCorp → 静态提取出该账号别名。"""
        _write(lib, "TL-RC-014", _scenario_yaml(
            "TL-RC-014",
            flow='  - call:\n      as: platformNoCorp\n      method: POST\n      path: /api/system/tags\n'))
        r = preflight.scan_dependencies(["TL-RC-014"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert "platformNoCorp" in r["accounts"]
        miss = r["missing_accounts"]
        assert any(m["account"] == "platformNoCorp" for m in miss), f"应预警账号缺失: {miss}"
        assert r["has_gaps"] is True

    def test_extract_accounts_from_precheck(self, lib):
        """precheck_permission/fetch_permission 的 account: 字段同样是账号依赖。"""
        _write(lib, "IS-PREP-002", _scenario_yaml(
            "IS-PREP-002",
            flow='  - tool:\n      use: precheck_permission\n      with:\n        account: default\n        resource_code: TDM_INV_ACTIVITY\n'))
        r = preflight.scan_dependencies(["IS-PREP-002"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert "default" in r["accounts"]
        assert r["missing_accounts"] == []

    def test_ignore_reserved_accounts(self, lib):
        """as: none/anonymous = 不带 token 匿名调用，不是账号依赖。"""
        _write(lib, "ANON-001", _scenario_yaml(
            "ANON-001",
            flow='  - call:\n      as: none\n      method: GET\n      path: /ping\n'))
        r = preflight.scan_dependencies(["ANON-001"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert r["accounts"] == [], f"匿名调用不应计入账号依赖: {r['accounts']}"

    def test_extract_env_keys_and_upstream(self, lib):
        """{{env.*}} 与 {{上游ID.*}} 引用静态提取。"""
        _write(lib, "EV-IMP-001", _scenario_yaml(
            "EV-IMP-001",
            flow='  - call:\n      method: POST\n      path: /x\n'
                 '      params:\n        code: "{{env.resource_code}}"\n'
                 '        id: "{{IS-PREP-001.session.json.data.id}}"\n',
            requires=None,
            depends='["IS-PREP-001"]'))
        _write(lib, "IS-PREP-001", _scenario_yaml(
            "IS-PREP-001", flow='  - call:\n      as: default\n      method: POST\n      path: /p\n'))
        r = preflight.scan_dependencies(["EV-IMP-001"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert "resource_code" in r["env_keys"]
        assert "IS-PREP-001" in r["upstream_refs"]
        # resource_code 在 env 有定义、IS-PREP-001 在闭包内 → 无缺失
        assert r["missing_env"] == []
        assert r["unresolved_upstream"] == []
        assert r["has_gaps"] is False


# ══════════════════════════════════════════════════════════
# requires 声明合并
# ══════════════════════════════════════════════════════════

class TestRequiresMerge:
    def test_requires_merged_with_static(self, lib):
        """requires.accounts 声明 + flow as: 静态提取 → 合并去重。"""
        _write(lib, "RC-001", _scenario_yaml(
            "RC-001",
            flow='  - call:\n      as: restricted\n      method: GET\n      path: /r\n',
            requires={"accounts": ["restricted", "default"]}))
        r = preflight.scan_dependencies(["RC-001"], scenarios_root=str(lib),
                                        env_config=_env_config(
                                            accounts={"default": {"ad": "u1"}, "restricted": {"ad": "u2"}}))
        assert sorted(r["accounts"]) == ["default", "restricted"]
        assert r["missing_accounts"] == []

    def test_requires_env_deep_key_missing(self, lib):
        """requires.env 声明 vars.xxx 子键，env 无该子键 → 缺失预警。"""
        _write(lib, "RC-002", _scenario_yaml(
            "RC-002",
            flow='  - call:\n      as: default\n      method: GET\n      path: /r\n',
            requires={"env": ["vars.inv_code", "vars.gone_code"]}))
        r = preflight.scan_dependencies(["RC-002"], scenarios_root=str(lib),
                                        env_config=_env_config())
        keys = {m["key"] for m in r["missing_env"]}
        assert "vars.gone_code" in keys
        assert "vars.inv_code" not in keys, "env 已定义键不应预警"


# ══════════════════════════════════════════════════════════
# 闭包展开与缺失比对
# ══════════════════════════════════════════════════════════

class TestClosureAndGaps:
    def test_closure_expands_upstream(self, lib):
        """选中下游场景 → 上游一并扫描（闭包）。"""
        _write(lib, "DOWN-001", _scenario_yaml(
            "DOWN-001",
            flow='  - call:\n      as: default\n      method: GET\n      path: /d\n',
            requires={"upstream": ["UP-001"]},
            depends='["UP-001"]'))
        _write(lib, "UP-001", _scenario_yaml(
            "UP-001",
            flow='  - call:\n      as: ghost_alias\n      method: POST\n      path: /u\n'))
        r = preflight.scan_dependencies(["DOWN-001"], scenarios_root=str(lib),
                                        env_config=_env_config())
        ids = [s["id"] for s in r["scenarios"]]
        assert "UP-001" in ids, "闭包应含上游"
        assert any(m["account"] == "ghost_alias" for m in r["missing_accounts"])
        # 上游引用 UP-001 已在闭包 → 不预警
        assert r["unresolved_upstream"] == []

    def test_upstream_ref_outside_closure(self, lib):
        """跨场景变量引用不在闭包 → 预警（EX-8200eada 类「变量未定义」提前暴露）。"""
        _write(lib, "SOLO-001", _scenario_yaml(
            "SOLO-001",
            flow='  - call:\n      method: GET\n      path: /s\n'
                 '      params:\n        id: "{{GHOST-001.data.id}}"\n'))
        r = preflight.scan_dependencies(["SOLO-001"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert any(u["ref"] == "GHOST-001" for u in r["unresolved_upstream"])
        assert r["has_gaps"] is True

    def test_no_gaps_reports_false(self, lib):
        """依赖全齐 → has_gaps=False。"""
        _write(lib, "OK-001", _scenario_yaml(
            "OK-001",
            flow='  - call:\n      as: default\n      method: GET\n      path: /ok\n',
            requires={"env": ["resource_code"]}))
        r = preflight.scan_dependencies(["OK-001"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert r["has_gaps"] is False
        assert r["missing_accounts"] == [] and r["missing_env"] == []

    def test_unknown_scenario_id(self, lib):
        """选中不存在的场景 → 返回 error 不抛异常。"""
        r = preflight.scan_dependencies(["NOPE-999"], scenarios_root=str(lib),
                                        env_config=_env_config())
        assert r.get("error"), "未知场景应返回 error 字段"


# ══════════════════════════════════════════════════════════
# apply_overrides 执行变量覆盖（T-312）
# ══════════════════════════════════════════════════════════

class TestApplyOverrides:
    """T-312：预检缺失项用户输入值 → 合并进环境配置（弹窗输入替代改配置文件）。"""

    def test_account_override_ad(self):
        cfg = {"accounts": {"default": {"ad": "u1"}}}
        out = preflight.apply_overrides(cfg, [{"kind": "account", "name": "platformNoCorp", "value": "caiyunfei"}])
        assert out["accounts"]["platformNoCorp"] == {"ad": "caiyunfei"}

    def test_account_override_with_emp_no(self):
        """value 支持 ad:emp_no 双段。"""
        cfg = {"accounts": {}}
        out = preflight.apply_overrides(cfg, [{"kind": "account", "name": "restricted", "value": "ad2:90020000"}])
        assert out["accounts"]["restricted"] == {"ad": "ad2", "emp_no": "90020000"}

    def test_env_override_top_key(self):
        cfg = {"resource_code": "OLD"}
        out = preflight.apply_overrides(cfg, [{"kind": "env", "name": "resource_code", "value": "NEW"}])
        assert out["resource_code"] == "NEW"

    def test_env_override_vars_subkey(self):
        cfg = {"vars": {"a": "1"}}
        out = preflight.apply_overrides(cfg, [{"kind": "env", "name": "vars.inv_code", "value": "INV-9"}])
        assert out["vars"]["inv_code"] == "INV-9"
        assert out["vars"]["a"] == "1", "不应覆盖 vars 其他键"

    def test_empty_value_ignored(self):
        """空值/未填写的输入不生效（弹窗只提交有值的项）。"""
        cfg = {"accounts": {}}
        out = preflight.apply_overrides(cfg, [{"kind": "account", "name": "ghost", "value": ""},
                                              {"kind": "env", "name": "k", "value": "  "}])
        assert "ghost" not in out["accounts"]
        assert "k" not in out

    def test_original_cfg_untouched(self):
        """不落盘、不改原配置（纯读副本）。"""
        cfg = {"accounts": {"a": {"ad": "u1"}}}
        preflight.apply_overrides(cfg, [{"kind": "account", "name": "b", "value": "u2"}])
        assert cfg["accounts"] == {"a": {"ad": "u1"}}, "原配置不应被修改"
