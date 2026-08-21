"""T-973 系统包管理面 REST 测试——分级注册/评审闸/热重建。

覆盖：
- GET /api/systems 目录（含 tier/评审闸状态）
- POST /api/systems 配置型注册即时生效（非 admin 403；重名 409；非法名 400）
- PUT env-config / assertions（SELECT-only 确定性校验拒绝写 SQL）
- extensions 上传 → 待评审（不加载）；review → 热加载（steps 计数可见）
- 评审闸不可绕：评审后改文件再查 → 失配未评审
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
def dyn_root(tmp_path, monkeypatch):
    root = tmp_path / "dyn_systems"
    root.mkdir()
    monkeypatch.setenv("SG_SYSTEMS_ROOT", str(root))
    return root


@pytest.fixture()
def client(db, dyn_root):
    from main import app
    with TestClient(app) as c:
        yield c


def _login(client, emp_no):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": "t"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestCatalogAndCreate:
    def test_list_contains_repo_tdm(self, client):
        h = _login(client, "90000001")
        r = client.get("/api/systems", headers=h)
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["systems"]]
        assert "tdm" in names, "仓内 tdm 包必须在目录（动态根之外兜底可见）"
        tdm = next(s for s in r.json()["systems"] if s["name"] == "tdm")
        assert tdm["tier"] == "code" and not tdm["dynamic"]

    def test_create_config_system_immediate(self, client, dyn_root):
        h = _login(client, "90000001")   # mock 模式首个登录用户成为 admin
        r = client.post("/api/systems", headers=h, json={
            "name": "orders", "display_name": "订单系统", "tier": "config",
            "description": "e2e 配置型", "env_name": "sit",
            "env_yaml": "orders_base: http://orders-sit\n",
        })
        assert r.status_code == 200, r.text
        # 即时生效：目录可见 + 引擎可装配（无需重启）
        r2 = client.get("/api/systems", headers=h)
        entry = next(s for s in r2.json()["systems"] if s["name"] == "orders")
        assert entry["tier"] == "config" and entry["dynamic"]
        assert "sit" in entry["envs"]
        from engine.bootstrap import load_system_env
        cfg = load_system_env("orders", "sit")
        assert cfg["orders_base"] == "http://orders-sit"

    def test_create_requires_admin(self, client, dyn_root):
        _login(client, "90000001")
        h2 = _login(client, "90000002")   # 第二个用户非 admin
        r = client.post("/api/systems", headers=h2, json={
            "name": "nope", "tier": "config"})
        assert r.status_code == 403

    def test_create_duplicate_409(self, client, dyn_root):
        h = _login(client, "90000001")
        body = {"name": "dup", "tier": "config"}
        assert client.post("/api/systems", headers=h, json=body).status_code == 200
        assert client.post("/api/systems", headers=h, json=body).status_code == 409

    def test_create_bad_name_400(self, client, dyn_root):
        h = _login(client, "90000001")
        r = client.post("/api/systems", headers=h, json={"name": "bad-name!", "tier": "config"})
        assert r.status_code == 400


class TestEnvAndAssertions:
    def test_write_env_config(self, client, dyn_root):
        h = _login(client, "90000001")
        client.post("/api/systems", headers=h, json={
            "name": "orders", "tier": "config",
            "env_yaml": "orders_base: http://a\n"})
        r = client.put("/api/systems/orders/env-config", headers=h, json={
            "env_name": "uat", "raw": "orders_base: http://orders-uat\n"})
        assert r.status_code == 200
        from engine.bootstrap import load_system_env
        assert load_system_env("orders", "uat")["orders_base"] == "http://orders-uat"

    def test_write_bad_yaml_400(self, client, dyn_root):
        h = _login(client, "90000001")
        client.post("/api/systems", headers=h, json={"name": "orders", "tier": "config"})
        r = client.put("/api/systems/orders/env-config", headers=h, json={
            "env_name": "sit", "raw": "a: [unclosed"})
        assert r.status_code == 400

    def test_assertions_write_sql_rejected(self, client, dyn_root):
        h = _login(client, "90000001")
        client.post("/api/systems", headers=h, json={
            "name": "orders", "tier": "template",
            "env_yaml": "orders_base: http://a\n"})
        r = client.put("/api/systems/orders/assertions", headers=h, json={
            "raw": "assertions:\n  - name: evil\n    sql: 'UPDATE t SET x=1'\n"})
        assert r.status_code == 400 and "SELECT" in r.json()["detail"]
        # 确定性校验通过的模板 → 注册为 oracle
        r2 = client.put("/api/systems/orders/assertions", headers=h, json={
            "raw": "assertions:\n  - name: cnt\n    sql: 'SELECT COUNT(*) AS c FROM t'\n"
                   "    expect: {c: '#number'}\n"})
        assert r2.status_code == 200 and "cnt" in r2.json()["registered"]


EXT_PY = (
    "from engine.tool_registry import register_tool\n"
    "\n"
    "def register(registry, env_config, db=None):\n"
    "    registry.step('boom', lambda body, rctx, ns, record: 'boom-ok')\n"
    "    register_tool('boom', desc='orders 扩展')\n"
)


class TestExtensionsReviewGate:
    def _create_and_upload(self, client, content=EXT_PY):
        h = _login(client, "90000001")
        client.post("/api/systems", headers=h, json={
            "name": "orders", "tier": "code",
            "env_yaml": "orders_base: http://a\n"})
        r = client.post("/api/systems/orders/extensions", headers=h,
                        json={"content": content})
        assert r.status_code == 200, r.text
        return h, r.json()

    def test_upload_pending_not_loaded(self, client, dyn_root):
        h, body = self._create_and_upload(client)
        assert body["status"] == "pending_review"
        # 未评审 → 装配不含扩展步骤（闸不可绕）
        from engine.bootstrap import build_registry
        reg = build_registry("orders", {})
        assert "boom" not in reg.step_handlers

    def test_review_activates_hot_load(self, client, dyn_root):
        h, _ = self._create_and_upload(client)
        r = client.post("/api/systems/orders/review", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["warmed"], "评审通过后热加载（steps 计数回传）"
        from engine.bootstrap import build_registry
        reg = build_registry("orders", {})
        assert "boom" in reg.step_handlers

    def test_gate_breaks_on_file_change(self, client, dyn_root):
        """评审后改文件 → 指纹失配自动回未评审（不需要显式撤销）。"""
        h, _ = self._create_and_upload(client)
        assert client.post("/api/systems/orders/review", headers=h).status_code == 200
        # 再上传改动版（同一 admin 也必须重新评审）
        r = client.post("/api/systems/orders/extensions", headers=h,
                        json={"content": EXT_PY + "\n# touched\n"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending_review"
        from engine.bootstrap import build_registry
        reg = build_registry("orders", {})
        assert "boom" not in reg.step_handlers, "改动后未经评审不得加载"

    def test_review_leaves_trail(self, client, dyn_root):
        h, _ = self._create_and_upload(client)
        r = client.post("/api/systems/orders/review", headers=h)
        review = r.json()["review"]
        assert review["approved_by"] == "90000001"   # 谁审的
        assert review["sha256"] and review["approved_at"]

    def test_reload_endpoint(self, client, dyn_root):
        h, _ = self._create_and_upload(client)
        client.post("/api/systems/orders/review", headers=h)
        r = client.post("/api/systems/orders/reload", headers=h)
        assert r.status_code == 200 and r.json()["warmed"]
        assert r.json()["gate"]["loadable"]
