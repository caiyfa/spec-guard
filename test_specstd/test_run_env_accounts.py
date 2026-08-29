"""runs 路由 T-1039 扩展：envs 环境清单 / accounts 带 env / resolve-account 按权限解析。

TestClient 隔离装配同 test_scenario_quality_api.py 模式（mock 鉴权 + 隔离工作区 +
临时场景库）。权限探针打桩在 systems.tdm.account_probe.probe——服务层经
importlib 动态导入该模块，monkeypatch 模块属性即可生效（不联网）。
"""
import importlib
import os

import pytest

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402

importlib.reload(auth_mod)  # 确保以 mock 模式加载

from sg_core import user_store  # noqa: E402

PERM_YAML = """id: RES-001
title: 资源码字面量场景
doc:
  covers: []
flow:
  - call:
      method: GET
      path: /api/x
      params: {empNo: "{{emp.no}}", resourceCode: "VIEW_TELENT_SEARCH"}
verify:
  - status: {eq: 200}
"""

ENVREF_YAML = """id: RES-002
title: 资源码 env 引用场景（显式别名 special）
doc:
  covers: []
flow:
  - call:
      as: special
      method: GET
      path: /api/y
      params: {resourceCode: "{{env.default_resource_code}}"}
verify:
  - status: {eq: 200}
"""

ENGINE_ALIAS_YAML = """id: RES-005
title: 引擎别名 resource_code 场景（{{env.resource_code}} → default_resource_code）
doc:
  covers: []
flow:
  - call:
      method: GET
      path: /api/v
      params: {resourceCode: "{{env.resource_code}}"}
verify:
  - status: {eq: 200}
"""

NOREQ_YAML = """id: RES-003
title: 无资源码场景
doc:
  covers: []
flow:
  - call:
      method: GET
      path: /api/z
verify:
  - status: {eq: 200}
"""

UNRESOLVED_YAML = """id: RES-004
title: 资源码为跨场景引用（静态不可判）
doc:
  covers: []
flow:
  - call:
      method: GET
      path: /api/w
      params: {resourceCode: "{{UP.save.rc}}"}
verify:
  - status: {eq: 200}
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """装配 TestClient（隔离 DB + 隔离工作区注册表 + 临时场景库）。"""
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    auth_mod._TOKEN_CACHE.clear()

    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")

    lib = tmp_path / "scenarios"
    lib.mkdir()
    for name, body in (("RES-001", PERM_YAML), ("RES-002", ENVREF_YAML),
                       ("RES-003", NOREQ_YAML), ("RES-004", UNRESOLVED_YAML),
                       ("RES-005", ENGINE_ALIAS_YAML)):
        (lib / f"{name}.yaml").write_text(body, encoding="utf-8")
    import services.scenario_store as store
    monkeypatch.setattr(store, "SCENARIOS_ROOT", lib)

    # 合规工作区（无 scenarios/ 目录 → scenarios_root 回退打桩的临时库）
    from test_specstd.helpers import create_valid_workspace
    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _login(client, emp_no="90000001", name="测试"):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_envs_lists_env_files_with_source(client):
    """T-1039：envs 端点枚举 env.{name}.yaml，逐环境带配置源（nacos/file）。"""
    h = _login(client)
    r = client.get("/api/runs/envs", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["system"] == "tdm"
    assert data["default"] == "sit"
    names = [e["name"] for e in data["envs"]]
    assert "sit" in names
    sit = next(e for e in data["envs"] if e["name"] == "sit")
    assert sit["ok"] is True
    assert sit["source"]  # config_source 如实透出（file / nacos:xxx）


def test_accounts_accepts_env_param(client):
    """T-1039：accounts 端点带 env 参数（试跑面板环境切换联动）。"""
    h = _login(client)
    r = client.get("/api/runs/accounts?env=sit", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["env"] == "sit"
    assert "default" in data["accounts"]
    assert data["accounts"]["default"]["ad"]
    assert data["source"]


def test_resolve_account_matches_by_probe(client, monkeypatch):
    """探针全码 has_any 的首个候选即匹配；override_value 可直接塞 SG_OVERRIDES。"""
    import sys

    import systems.tdm.account_probe as probe_mod
    monkeypatch.setattr(probe_mod, "probe",
                        lambda cfg, emp_nos, codes: {
                            "results": {no: {c: {"has_any": True, "summary": "corpCode=ALL",
                                                 "status": "0"} for c in codes}
                                        for no in emp_nos},
                            "errors": [], "probe_account": "default"})
    assert "systems.tdm.account_probe" in sys.modules  # 打桩先于服务层动态导入

    h = _login(client)
    r = client.get("/api/runs/resolve-account?scenarios=RES-001&env=sit", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["supported"] is True
    assert data["requirements"] == {"default": ["VIEW_TELENT_SEARCH"]}
    assert data["candidates"], "配置账号（含 emp_no）应成为候选"
    assert all(c["matched"] for c in data["candidates"])
    assert data["matched"]["alias"] == "default"     # 候选按配置序，首个满足即匹配
    assert data["override_value"]  # ad:emp_no
    assert data["override_value"].count(":") == 1


def test_resolve_account_env_ref_and_alias_isolation(client):
    """{{env.*}} 引用解析为真实资源码；显式别名需求不冒充 default（无需求→诚实说明）。"""
    h = _login(client)
    r = client.get("/api/runs/resolve-account?scenarios=RES-002&env=sit", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["requirements"].get("special") == ["VIEW_HISTORY"]  # env 引用已解析
    assert "default" not in data["requirements"]                    # default 别名无需求
    assert data["matched"] is None and not data["override_value"]
    assert "default 别名无资源码需求" in data["reason"]


def test_resolve_account_engine_alias_resource_code(client, monkeypatch):
    """回归钉：{{env.resource_code}} 与引擎 shared_ns 别名同源（→ default_resource_code），
    不因裸 env 配置无此键而误判静态不可判。探针打桩（测试永不真登录 SSO）。"""
    import systems.tdm.account_probe as probe_mod
    monkeypatch.setattr(probe_mod, "probe",
                        lambda cfg, emp_nos, codes: {
                            "results": {no: {c: {"has_any": True, "summary": "",
                                                 "status": "0"} for c in codes}
                                        for no in emp_nos},
                            "errors": [], "probe_account": "default"})
    h = _login(client)
    r = client.get("/api/runs/resolve-account?scenarios=RES-005", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["requirements"] == {"default": ["VIEW_HISTORY"]}  # 真实配置 default_resource_code
    assert data["unresolved"] == []
    assert data["matched"] is not None  # 探针打桩全真 → default 候选匹配


def test_resolve_account_no_requirement_and_unresolved(client):
    """无资源码场景回退固定配置；跨场景引用静态不可判进 unresolved（不猜）。"""
    h = _login(client)
    r = client.get("/api/runs/resolve-account?scenarios=RES-003", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["matched"] is None
    assert "无资源码需求" in data["reason"]

    r = client.get("/api/runs/resolve-account?scenarios=RES-004", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["requirements"] == {}          # 不可判 → 不报假需求
    assert data["unresolved"] and "UP.save.rc" in data["unresolved"][0]


def test_resolve_account_requires_tester_role(client):
    """探针会执行 SSO 登录——仅 admin/tester 可调（与 trigger 同门槛）。"""
    r = client.post("/api/auth/mock-login", json={"emp_no": "90000002", "name": "只读"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    # mock 登录默认 tester 可过；此处只验证端点存在且不 500（纯读兜底语义）
    resp = client.get("/api/runs/resolve-account?scenarios=RES-003", headers=h)
    assert resp.status_code == 200, resp.text
    unauth = client.get("/api/runs/resolve-account?scenarios=RES-003")
    assert unauth.status_code in (401, 403)
