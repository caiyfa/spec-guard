"""T-974 多系统 e2e——第二个配置型系统全程 mock 接入，不重启后端。

全链路（进程内，等价于后端运行期行为——热注册靠缓存失效而非进程重启）：
  ① admin 经 POST /api/systems 注册配置型系统 orders（manifest + env 落盘）
  ② 注册工作区绑定 system=orders → resolve_system 按工作区解析
  ③ load_system_env / build_registry 装配（bootstrap 组合根，动态包路径）
  ④ 引擎执行该系统下的场景（纯离线原语：set_var/random + schema_match 断言）
  ⑤ live_registry 分键查询 orders 的注册快照（format_spec tool 目录同源）
  ⑥ tdm 主系统不受影响（分键隔离）

验收锚点：新系统从注册到跑通全程不重启后端（T-974）。
"""

import os
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from services import user_store
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    from services.auth import _TOKEN_CACHE
    _TOKEN_CACHE.clear()
    return db_file


@pytest.fixture()
def e2e_env(tmp_path, monkeypatch):
    """动态系统根 + 报告目录隔离。"""
    root = tmp_path / "dyn_systems"
    root.mkdir()
    monkeypatch.setenv("SG_SYSTEMS_ROOT", str(root))
    monkeypatch.setenv("SG_REPORTS_ROOT", str(tmp_path / "reports"))
    return root


@pytest.fixture()
def client(db, e2e_env):
    from main import app
    with TestClient(app) as c:
        yield c


def _login(client, emp_no):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": "t"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_second_config_system_full_chain(client, e2e_env, tmp_path):
    # ① 注册配置型系统（admin，UI 同款端点；即时生效 = 落盘 + 缓存失效，无重启）
    h = _login(client, "90000001")
    r = client.post("/api/systems", headers=h, json={
        "name": "orders", "display_name": "订单系统", "tier": "config",
        "description": "T-974 e2e 第二系统", "env_name": "sit",
        "env_yaml": ("orders_base: http://orders-sit\n"
                     "default_service: orders\n"
                     "vars: {marker: SG-E2E}\n"),
    })
    assert r.status_code == 200, r.text

    # ② 工作区绑定 system=orders → resolve_system 一等公民口径
    import specstd.workspace as wsm
    ws_root = tmp_path / "orders-ws"
    (ws_root / "scenarios").mkdir(parents=True)
    (ws_root / "scenarios" / "ORD-001.yaml").write_text(
        "id: ORD-001\ntitle: 订单系统冒烟\nversion: \"0.1\"\n"
        "flow:\n"
        "  - set_var: {vars: {who: e2e}}\n"
        "  - random: {type: number, min: 1, max: 1, save: n}\n"
        "verify:\n"
        "  - python: {script: \"assert ns['who'] == 'e2e' and ns['n'] == 1\"}\n"
        "  - oracle: {name: schema_match, params: {of: n, spec: '#number'}}\n",
        encoding="utf-8")
    wsm.register_local("orders-ws", str(ws_root), "orders", activate=True)
    token = wsm.set_context_workspace("orders-ws")
    try:
        from specstd.workspace import resolve_system
        assert resolve_system() == "orders", "工作区绑定的 system 必须生效"

        # ③ bootstrap 组合根装配（动态包路径：load_manifest → load_package_env）
        from engine.bootstrap import build_registry, build_scenario_graph, load_system_env
        cfg = load_system_env("orders", "sit")
        assert cfg["orders_base"] == "http://orders-sit"
        assert cfg["default_service"] == "orders"
        assert cfg["vars"]["marker"] == "SG-E2E"
        reg = build_registry("orders", cfg)
        assert "call" in reg.step_handlers and "schema_match" in reg.oracles

        # ④ 引擎执行该系统下的场景（工作区场景库）
        from engine.scenario_runner import RunContext, run_with_deps
        from engine.token_provider import TokenProvider
        graph = build_scenario_graph(ws_root / "scenarios")
        rctx = RunContext(registry=reg, env_config=cfg,
                          token_provider=TokenProvider("", "", ""),
                          graph=graph, run_dir=str(tmp_path / "run"))
        record = run_with_deps(graph.by_id["ORD-001"], rctx)
        assert record.verdict == "PASS", f"第二系统场景应跑通: {record.verdict} {getattr(record, 'failure', '')}"

        # ⑤ live_registry 按 system 分键（orders 快照独立于 tdm）
        from mcp_server.tools.live_registry import get_live_registry
        reg_o = get_live_registry("orders")
        assert reg_o is not None and "schema_match" in reg_o.oracles

        # ⑥ tdm 主系统不受影响（分键隔离，主包照常装配）
        from mcp_server.tools.live_registry import invalidate_live_registry
        invalidate_live_registry("orders")
        reg_t = get_live_registry("tdm")
        assert reg_t is not None
        assert "select_emp" in reg_t.step_handlers, "tdm 专属步骤仍在位"
        assert "boom" not in reg_t.step_handlers
    finally:
        wsm.reset_context_workspace(token)
        wsm.unregister("orders-ws")


def test_runner_spawn_injects_second_system(client, e2e_env, tmp_path, monkeypatch):
    """RunControl 断链修复的 e2e 侧证：orders 工作区触发的执行注入 orders system。"""
    import specstd.workspace as wsm
    ws_root = tmp_path / "orders-ws2"
    (ws_root / "scenarios").mkdir(parents=True)
    wsm.register_local("orders-ws2", str(ws_root), "orders", activate=True)

    # 先注册系统（上一测试的动态根是独立 tmp；这里补注册）
    h = _login(client, "90000001")
    r = client.post("/api/systems", headers=h, json={
        "name": "orders", "tier": "config", "env_name": "sit",
        "env_yaml": "orders_base: http://orders-sit\n"})
    assert r.status_code == 200, r.text

    from services import user_store
    from services.runner import RunManager
    m = RunManager()
    spawns = []
    monkeypatch.setattr("services.runner._get_reports_root", lambda: tmp_path)
    monkeypatch.setattr("services.runner._spawn_pytest",
                        lambda cmd, env, run_id="", account_override="", overrides=None,
                        system="", scenarios_root="": spawns.append(
                            {"system": system, "scenarios_root": scenarios_root})
                        or type("P", (), {"terminate": lambda s: None,
                                          "kill": lambda s: None,
                                          "returncode": 0})())
    monkeypatch.setattr(user_store, "enqueue_run", lambda *a, **k: 1)
    monkeypatch.setattr(user_store, "audit", lambda *a, **k: None)

    async def _noop_async(*a, **k):
        pass

    monkeypatch.setattr(m, "broadcast", _noop_async)
    monkeypatch.setattr(m, "_record_failures", lambda: None)
    monkeypatch.setattr(m, "_record_executions", lambda: None)
    monkeypatch.setattr(m, "_push_run_notifications", _noop_async)
    monkeypatch.setattr(m, "_finish_current_run", _noop_async)

    import asyncio
    result = asyncio.run(m.trigger(scope="scenario", target="ORD-001", env="sit",
                                   emp_no="u1", workspace="orders-ws2"))
    assert result["ok"] is True
    assert spawns, "spawn 应被调用"
    assert spawns[-1]["system"] == "orders", "RunControl 执行必须按工作区 system 注入"
    assert spawns[-1]["scenarios_root"], "工作区场景库应注入子进程"
