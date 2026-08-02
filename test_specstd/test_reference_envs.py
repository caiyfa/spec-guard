"""环境配置独立菜单后端测试（T-306）。

验证：
1. GET /reference/envs 列出可用环境（扫描 env.*.yaml）
2. GET /reference/env-config?env= 按环境读取（不存在的环境 exists=False）
3. 非法环境名 → 400（路径穿越防护）
4. PUT /reference/env-config?env= 保存（YAML 校验 + 写盘）
"""

import os
import sys
import importlib

import pytest

SG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)
BACKEND_DIR = os.path.join(SG_ROOT, "workbench", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402
importlib.reload(auth_mod)

from fastapi.testclient import TestClient  # noqa: E402
from workbench.backend.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from services import user_store
    monkeypatch.setattr(user_store, "DB_PATH", tmp_path / "wb.db")  # 隔离库：首登录用户 bootstrap 为 admin
    with TestClient(app) as c:
        tok = c.post("/api/auth/mock-login", json={"emp_no": "90000001"}).json()["token"]
        c.headers.update({"Authorization": f"Bearer {tok}"})
        yield c


class TestEnvEndpoints:
    def test_envs_lists_available_envs(self, client):
        r = client.get("/api/reference/envs")
        assert r.status_code == 200
        data = r.json()
        assert data["system"] == "tdm"
        names = [e["name"] for e in data["envs"]]
        assert "sit" in names
        assert data["current"] == "sit"

    def test_env_config_by_env(self, client):
        r = client.get("/api/reference/env-config?env=sit")
        assert r.status_code == 200
        data = r.json()
        assert data["exists"] is True
        assert "accounts" in data["parsed"]
        # 未创建的环境：exists=False 而非 500
        r2 = client.get("/api/reference/env-config?env=uat")
        assert r2.status_code == 200
        assert r2.json()["exists"] is False

    def test_env_config_rejects_illegal_name(self, client):
        """路径穿越防护：非法环境名 → 400（此前 HTTPException 未 import 会 500）。"""
        r = client.get("/api/reference/env-config?env=../evil")
        assert r.status_code == 400

    def test_save_env_config_roundtrip(self, client, tmp_path, monkeypatch):
        """保存到指定环境文件（YAML 校验 + 写盘）。

        双保险（经验包 2026-08-02-测试污染生产配置）：monkeypatch 目标必须与 main
        同模块实例（from routers import reference），且真实 env.sit.yaml 的 mtime
        不得变化——monkeypatch 失效会立即红而非静默污染生产配置。
        """
        from routers import reference  # 与 main 同一模块实例（BACKEND_DIR sys.path）
        real_env = reference.SYSTEMS_TDM / "config" / "env.sit.yaml"
        real_mtime = real_env.stat().st_mtime_ns if real_env.is_file() else None
        target = tmp_path / "config"
        target.mkdir(parents=True)
        monkeypatch.setattr(reference, "SYSTEMS_TDM", tmp_path)
        assert reference.SYSTEMS_TDM == tmp_path, "monkeypatch 未生效（模块实例不一致）"
        (tmp_path / "config").mkdir(exist_ok=True)

        r = client.put("/api/reference/env-config?env=sit", json={"raw": "accounts:\n  default: {ad: u1, emp_no: '90000001'}\n"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        saved = (tmp_path / "config" / "env.sit.yaml").read_text(encoding="utf-8")
        assert "default" in saved
        # mtime 守卫：真实配置未被写
        if real_mtime is not None:
            assert real_env.stat().st_mtime_ns == real_mtime, "真实 env.sit.yaml 被测试写入！monkeypatch 失效"

    def test_save_rejects_bad_yaml(self, client, tmp_path, monkeypatch):
        from routers import reference  # 与 main 同一模块实例（BACKEND_DIR sys.path）
        monkeypatch.setattr(reference, "SYSTEMS_TDM", tmp_path)
        r = client.put("/api/reference/env-config?env=sit", json={"raw": "a: [unclosed"})
        assert r.status_code == 200
        assert r.json()["ok"] is False
