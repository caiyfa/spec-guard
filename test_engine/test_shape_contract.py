"""shape_contract + parallel_safety：形状契约与并行安全静态判定（T-1037/T-1038）。

全离线：reports 目录用 tmp fixture 伪造（run.json + cases），场景库用 tmp YAML；
HTTP 不打桩（shape_contract 不触网；accounts 静态扫描只读 YAML 文本）。
"""
import json
import os
from pathlib import Path

import pytest

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402

importlib = __import__("importlib")
importlib.reload(auth_mod)

from services import parallel_safety as ps  # noqa: E402
from services import shape_contract as sc_mod  # noqa: E402

from sg_core import user_store  # noqa: E402

# ── shape_of ──

def test_shape_of_nested_and_array_union():
    v = {"status": "200", "data": {"items": [{"id": 1, "name": "a"}, {"id": 2, "ext": True}]}}
    s = sc_mod.shape_of(v)
    assert s["$"] == "object"
    assert s["$.status"] == "str"
    assert s["$.data.items"] == "array"
    assert s["$.data.items[].id"] == "int"
    assert s["$.data.items[].name"] == "str"
    assert s["$.data.items[].ext"] == "bool"


def test_shape_of_null_and_empty_list():
    s = sc_mod.shape_of({"a": None, "b": []})
    assert s["$.a"] == "null"
    assert s["$.b"] == "array" and "$.b[]" not in s   # 空数组无元素形状


# ── 消费面收集（save→API 映射 + 插值三元组）──

SC_UPSTREAM = """id: UP-001
title: 上游
flow:
  - call:
      method: GET
      path: /api/items
      save: resp
  - db_query:
      sql: SELECT 1
      save: rows
"""
SC_CONSUMER = """id: DOWN-001
title: 消费方
depends_on: [UP-001]
flow:
  - tool:
      use: select_emp
      with: {role: r}
      save: emp
  - call:
      method: GET
      path: /api/detail
      params:
        itemId: "{{UP-001.save.resp.data.items[0].id}}"
        rowCount: "{{UP-001.save.rows[0].cnt}}"
        empNo: "{{emp.no}}"
"""

def test_collect_shape_refs_triples(tmp_path, monkeypatch):
    lib = tmp_path / "scenarios"
    lib.mkdir()
    (lib / "UP-001.yaml").write_text(SC_UPSTREAM, encoding="utf-8")
    (lib / "DOWN-001.yaml").write_text(SC_CONSUMER, encoding="utf-8")
    refs = sc_mod.collect_shape_refs(lib)
    # resp → 上游 call API 形状引用；rows 是 db save → 不产出；同场景自身引用不计
    assert refs == [{"consumer": "DOWN-001", "upstream": "UP-001",
                     "api": "GET /api/items", "path": "$.data.items[0].id"}]


# ── 报告扫描 + 汇聚分析 ──

def _write_run(root: Path, run_id: str, cases: dict[str, dict]):
    d = root / run_id
    (d / "cases").mkdir(parents=True)
    idx = []
    for cid, body in cases.items():
        (d / "cases" / f"{cid}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        idx.append({"id": cid, "file": f"cases/{cid}.json", "verdict": body.get("verdict", "PASS")})
    (d / "run.json").write_text(json.dumps({"run_id": run_id, "cases": idx}), encoding="utf-8")


def _case(api_path: str, body, method="GET"):
    return {"scenario_id": "X", "steps": [
        {"type": "call", "request": {"method": method, "path": api_path},
         "response_status": 200, "body_excerpt": body, "response_body": body},
    ], "verdict": "PASS"}


@pytest.fixture()
def shape_env(tmp_path, monkeypatch):
    """伪造 reports 目录（3 早期 + 3 近期 run）+ 场景库 + 打桩根。"""
    reports = tmp_path / "reports"
    for i in range(1, 4):   # 早期：$.data.old 存在
        _write_run(reports, f"EX-early{i:02d}", {"C": _case("/api/items", {"data": {"old": 1, "items": [1]}})})
    for i in range(1, 4):   # 近期：$.data.old 消失、$.data.added 新增
        _write_run(reports, f"EX-late{i:02d}", {"C": _case("/api/items", {"data": {"added": 1, "items": [1]}})})
    import services.scenario_store as store
    lib = tmp_path / "scenarios"
    lib.mkdir(exist_ok=True)
    (lib / "UP-001.yaml").write_text(SC_UPSTREAM, encoding="utf-8")
    (lib / "DOWN-001.yaml").write_text(SC_CONSUMER, encoding="utf-8")
    monkeypatch.setattr(store, "SCENARIOS_ROOT", lib)
    monkeypatch.setattr(store, "_reports_root", lambda: reports)
    monkeypatch.setattr(sc_mod, "_reports_root", lambda: reports)
    sc_mod.invalidate_cache()
    ps.invalidate_cache()
    return reports


def test_analyze_reports_unresolved_ref_and_drift(shape_env):
    # DOWN-001 引用 $.data.items[0].id（历史中出现过——items 数组元素是 int 标量，无 .id 子路径）
    data = sc_mod.analyze_shape_contract(refresh=True)
    assert data["n_runs"] == 6
    apis = {a["api"]: a for a in data["apis"]}
    assert apis["GET /api/items"]["runs"] == 6

    types = {(f["type"], f.get("path", "")): f for f in data["findings"]}
    # ① 引用完整性：$.data.items[0].id 在历史响应中从未出现（元素是 int）→ WARN
    f = types[("unresolved-ref", "$.data.items[0].id")]
    assert f["level"] == "WARN" and f["consumers"] == ["DOWN-001"]
    # ② 漂移：$.data.old 早期 3 run 均有、近期全无，但无人引用 → 消费面修剪不报警
    assert ("removed-path", "$.data.old") not in types
    # ③ 新增字段：$.data.added → INFO 汇总（新增放行）
    added = [x for x in data["findings"] if x["type"] == "added-paths"]
    assert added and "$.data.added" in added[0]["message"]


def test_analyze_removed_path_warns_only_when_referenced(shape_env):
    # 消费方引用 $.data.old（早期有、近期无）→ 漂移应升格 WARN；无人引用则不报警（前一波断言已验）
    lib = shape_env.parent / "scenarios"
    (lib / "DOWN-001.yaml").write_text(
        SC_CONSUMER.replace('itemId: "{{UP-001.save.resp.data.items[0].id}}"',
                            'old: "{{UP-001.save.resp.data.old}}"'),
        encoding="utf-8")
    sc_mod.invalidate_cache()
    data = sc_mod.analyze_shape_contract(refresh=True)
    drift = [f for f in data["findings"] if f["type"] == "removed-path"]
    assert len(drift) == 1
    assert drift[0]["path"] == "$.data.old" and drift[0]["level"] == "WARN"
    assert drift[0]["consumers"] == ["DOWN-001"]   # 早期 3 run 均出现 → WARN 而非 INFO


def test_case_without_response_body_falls_back_to_excerpt(tmp_path):
    """老报告无 response_body → body_excerpt 兜底；截断字符串体诚实舍弃。"""
    case = {"scenario_id": "X", "steps": [
        {"type": "call", "request": {"method": "GET", "path": "/api/old"},
         "body_excerpt": {"status": "200"}},
        {"type": "call", "request": {"method": "GET", "path": "/api/cut"},
         "body_excerpt": '{"truncated": "…(已截断，原始共9字符'},
    ], "verdict": "PASS"}
    reports = tmp_path / "reports"
    _write_run(reports, "EX-old1", {"C": case})
    shapes = sc_mod._case_shapes(reports / "EX-old1" / "cases" / "C.json")
    assert "$.status" in shapes["GET /api/old"]
    assert "GET /api/cut" not in shapes   # 字符串体不进形状基线


# ── parallel_safety ──

READER_YAML = """id: R-001
title: 纯查询
flow:
  - call:
      method: GET
      path: /api/list
verify:
  - status: {eq: 200}
"""
WRITER_YAML = """id: W-001
title: 写场景
flow:
  - call:
      as: default
      method: POST
      path: /api/items
      body: {name: x}
teardown:
  - call:
      method: DELETE
      path: /api/items/1
"""


def test_parallel_safety_rules(tmp_path, monkeypatch):
    import services.scenario_store as store
    lib = tmp_path / "scenarios"
    lib.mkdir()
    (lib / "R-001.yaml").write_text(READER_YAML, encoding="utf-8")
    (lib / "W-001.yaml").write_text(WRITER_YAML, encoding="utf-8")
    monkeypatch.setattr(store, "SCENARIOS_ROOT", lib)
    ps.invalidate_cache()
    data = ps.analyze_parallel_safety(refresh=True)
    assert data["totals"]["readers"] == 1
    assert data["totals"]["writers"] == 1
    assert data["totals"]["max_parallelism"] == 1   # 只有一个读场景
    assert [w["id"] for w in data["writers"]] == ["W-001"]
    assert data["writers"][0]["accounts"] == ["default"]   # as: 静态扫描
    assert data["readers"][0]["accounts"] == []


# ── API 端点 ──

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    auth_mod._TOKEN_CACHE.clear()
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from routers import agent as agent_router
    monkeypatch.setattr(agent_router, "SESSIONS_ROOT", tmp_path / "sessions")
    from test_specstd.helpers import create_valid_workspace
    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _login(client):
    r = client.post("/api/auth/mock-login", json={"emp_no": "90000001", "name": "测试"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_shape_and_safety_endpoints(client, shape_env):
    h = _login(client)
    r = client.get("/api/scenario-quality/shape-contract?refresh=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["n_runs"] == 6
    r2 = client.get("/api/scenario-quality/parallel-safety?refresh=1", headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["totals"]["scenarios"] >= 2
