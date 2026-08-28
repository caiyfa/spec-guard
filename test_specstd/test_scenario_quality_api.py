"""scenario_quality router + service：场景库质量全景聚合（T-1035）。

TestClient 隔离装配同 test_db_console.py 模式（mock 鉴权 + 打桩模块级常量）。
场景库用临时目录 fixture：3 个控制场景覆盖 deep/shallow/no-verify 三档评级 +
missing-covers/invalid-covers/probe 三类问题标记；锚点走 create_valid_workspace
的 specs/module1/feature1/spec.md（FR-001/FR-002）。
"""
import importlib
import os
from pathlib import Path

import pytest

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402

importlib.reload(auth_mod)  # 确保以 mock 模式加载

from sg_core import user_store  # noqa: E402

SUITE_A = """feature: 特性A
module: module1/feature1
spec_ref: specs/module1/feature1/spec.md
spec_version: V1
"""

SUITE_B = """feature: 特性B
module: module2/feature2
"""

DEEP_YAML = """id: DEEP-001
title: 深断言场景
doc:
  given: 库里有一行数据
  when: 查询并断言
  then: 返回一行
  covers: [FR-001]
  dimensions: [state]
flow:
  - db_query:
      sql: SELECT 1
      save: rows
verify:
  - status: {eq: 200}
  - json: {path: $.rows, of: rows, len_eq: 1}
"""

SHALLOW_YAML = """id: SHALLOW-001
title: 浅断言场景
doc:
  covers: []
flow:
  - call:
      method: GET
      path: /api/x
verify:
  - status: {eq: 200}
"""

PROBE_YAML = """id: PROBE-001
title: 探针场景
doc:
  covers: [FR-999]
flow:
  - python:
      script: print(1)
verify: []
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """装配 TestClient（隔离 DB + 隔离工作区注册表 + 临时场景库 fixture）。"""
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    auth_mod._TOKEN_CACHE.clear()

    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from routers import agent as agent_router
    monkeypatch.setattr(agent_router, "SESSIONS_ROOT", tmp_path / "sessions")

    # 临时场景库：deep（有效 covers）/ shallow（缺 covers）/ 探针（失效 covers）
    lib = tmp_path / "scenarios"
    (lib / "suiteA").mkdir(parents=True)
    (lib / "suiteB").mkdir(parents=True)
    (lib / "suiteA" / "_suite.yaml").write_text(SUITE_A, encoding="utf-8")
    (lib / "suiteA" / "DEEP-001.yaml").write_text(DEEP_YAML, encoding="utf-8")
    (lib / "suiteA" / "SHALLOW-001.yaml").write_text(SHALLOW_YAML, encoding="utf-8")
    (lib / "suiteB" / "_suite.yaml").write_text(SUITE_B, encoding="utf-8")
    (lib / "suiteB" / "PROBE-001.yaml").write_text(PROBE_YAML, encoding="utf-8")
    import services.scenario_store as store
    monkeypatch.setattr(store, "SCENARIOS_ROOT", lib)
    from services import scenario_quality as sq
    sq.invalidate_cache()

    # 合规工作区（无 scenarios/ 目录 → scenarios_root 回退上面打桩的临时库）
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


def test_overview_aggregates_grades_issues_and_suites(client):
    h = _login(client)
    r = client.get("/api/scenario-quality/overview?refresh=1", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()

    t = data["totals"]
    assert t["scenarios"] == 3
    assert t["suites"] == 2
    assert t["covers_tagged"] == 2
    assert t["covers_rate"] == 66.7
    assert t["grades"] == {"deep": 1, "medium": 0, "shallow": 1, "no-verify": 1}
    assert t["issues"]["missing-covers"] == 1
    assert t["issues"]["invalid-covers"] == 1
    assert t["issues"]["shallow"] == 1
    assert t["issues"]["no-verify"] == 1
    assert t["issues"]["probe"] == 1
    assert t["scenarios_with_issues"] == 2

    # 锚点联动：FR-001 被 DEEP-001 覆盖，FR-002 缺口；FR-999 判失效
    assert data["anchors_available"] is True
    assert t["anchors_total"] == 2
    assert t["anchors_covered"] == 1
    assert t["fr_gaps"] == 1

    rows = {s["id"]: s for s in data["scenarios"]}
    assert rows["DEEP-001"]["grade"] == "deep"
    assert rows["DEEP-001"]["issues"] == []
    assert "db_proof" in rows["DEEP-001"]["evidence"]
    assert rows["DEEP-001"]["suite"] == "suiteA"
    assert rows["DEEP-001"]["path"] == str(Path("suiteA") / "DEEP-001.yaml")

    # 内容字段：doc 语义快速预览 + covers 逐条解析（完整结构化内容前端走 ScenarioFormEditor）
    deep = rows["DEEP-001"]
    assert deep["doc_summary"] == {"given": "库里有一行数据", "when": "查询并断言", "then": "返回一行"}
    assert len(deep["covers_detail"]) == 1
    cd = deep["covers_detail"][0]
    assert cd["fr"] == "FR-001" and cd["valid"] is True
    assert "查询功能" in cd["title"]

    assert rows["SHALLOW-001"]["grade"] == "shallow"
    assert set(rows["SHALLOW-001"]["issues"]) == {"missing-covers", "shallow"}
    assert rows["SHALLOW-001"]["covers_detail"] == []

    assert rows["PROBE-001"]["grade"] == "no-verify"
    assert set(rows["PROBE-001"]["issues"]) == {"invalid-covers", "no-verify", "probe"}
    assert rows["PROBE-001"]["invalid_covers"] == ["FR-999"]
    assert rows["PROBE-001"]["covers_detail"][0] == {"fr": "FR-999", "valid": False, "title": "", "module": ""}

    suites = {s["key"]: s for s in data["suites"]}
    assert suites["suiteA"]["scenarios"] == 2
    assert suites["suiteA"]["covers_tagged"] == 1
    assert suites["suiteA"]["covers_rate"] == 50.0
    assert suites["suiteA"]["feature"] == "特性A"
    assert suites["suiteA"]["spec_ref"] == "specs/module1/feature1/spec.md"
    assert suites["suiteA"]["scenarios_with_issues"] == 1
    assert suites["suiteB"]["grades"]["no-verify"] == 1

    m = data["capability_matrix"]
    assert m["steps"]["db_query"] == 1
    assert m["steps"]["call"] == 1
    assert m["steps"]["python"] == 1
    assert m["depends"] == {"shared": 0, "exclusive": 0}


def test_overview_empty_library_honest_empty(client, tmp_path, monkeypatch):
    """空场景库：诚实空态（全零、空列表），不报错不虚构。"""
    import services.scenario_store as store
    from services import scenario_quality as sq
    empty = tmp_path / "empty_scenarios"
    empty.mkdir()
    monkeypatch.setattr(store, "SCENARIOS_ROOT", empty)
    sq.invalidate_cache()

    h = _login(client)
    r = client.get("/api/scenario-quality/overview?refresh=1", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["totals"]["scenarios"] == 0
    assert data["totals"]["covers_rate"] == 0.0
    assert data["scenarios"] == []
    assert data["suites"] == []
