"""register_git 自定义克隆落点（clone_dir）+ browse-dir 目录浏览端点测试。

安全语义（自定义落点与 SpecGuard 自管 _clones/ 的边界）：
- 自定义落点：绝不清理已有目录（防误删用户数据）；注销只注销注册表、不删目录
- 默认落点（_clones/{name}）：SpecGuard 自管，注销删除（现有语义不变）
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import specstd.workspace as wsm
from test_specstd.conftest import create_valid_workspace


def _git(args, cwd):
    """执行 git 命令，失败即断言（测试基建自身不应失败）。"""
    proc = subprocess.run(
        ["git", "-c", "user.email=test@specguard.local", "-c", "user.name=specguard-test",
         *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"
    return proc


@pytest.fixture()
def remote_src(tmp_path, monkeypatch):
    """搭建：隔离注册表/克隆目录 + 合规源仓库（本地 git remote）。"""
    monkeypatch.setattr(wsm, "SG_ROOT", tmp_path)
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    src = tmp_path / "remote_src"
    create_valid_workspace(src)
    _git(["init", "-b", "main"], cwd=src)
    _git(["add", "-A"], cwd=src)
    _git(["commit", "-m", "init"], cwd=src)
    return src


class TestRegisterGitCloneDir:
    def test_custom_clone_dir_clones_and_registers(self, remote_src, tmp_path):
        """自定义落点：克隆成功，注册表 local_path 为绝对路径，root 指向落点。"""
        target = tmp_path / "custom" / "ws1"
        result = wsm.register_git("ws1", str(remote_src), "tdm", branch="main",
                                  activate=False, run_conformance=False,
                                  clone_dir=str(target))
        assert result["ok"], result.get("error")
        info = wsm.get_workspace("ws1")
        assert info.source_type == "git"
        assert Path(info.local_path).is_absolute()
        assert info.root == target
        assert (target / "AGENTS.md").is_file()

    def test_custom_clone_dir_existing_non_empty_not_cleared(self, remote_src, tmp_path):
        """自定义落点已存在且非空：clone 失败，但目录内容绝不清理（防误删）。"""
        target = tmp_path / "custom" / "occupied"
        target.mkdir(parents=True)
        (target / "user_data.txt").write_text("keep me", encoding="utf-8")
        result = wsm.register_git("ws2", str(remote_src), "tdm",
                                  activate=False, run_conformance=False,
                                  clone_dir=str(target))
        assert result["ok"] is False
        assert "git clone 失败" in result["error"]
        assert (target / "user_data.txt").read_text(encoding="utf-8") == "keep me"
        assert wsm.get_workspace("ws2") is None

    def test_custom_clone_dir_existing_empty_ok(self, remote_src, tmp_path):
        """自定义落点已存在但为空：git clone 成功。"""
        target = tmp_path / "custom" / "empty_ok"
        target.mkdir(parents=True)
        result = wsm.register_git("ws3", str(remote_src), "tdm",
                                  activate=False, run_conformance=False,
                                  clone_dir=str(target))
        assert result["ok"], result.get("error")
        assert (target / "AGENTS.md").is_file()

    def test_relative_clone_dir_rejected(self, remote_src, tmp_path):
        """相对路径落点拒绝。"""
        result = wsm.register_git("ws4", str(remote_src), "tdm",
                                  activate=False, run_conformance=False,
                                  clone_dir="relative/path")
        assert result["ok"] is False
        assert "绝对路径" in result["error"]

    def test_unregister_keeps_custom_clone_dir(self, remote_src, tmp_path):
        """注销自定义落点工作区：只注销注册表，不删目录。"""
        target = tmp_path / "custom" / "ws5"
        result = wsm.register_git("ws5", str(remote_src), "tdm",
                                  activate=False, run_conformance=False,
                                  clone_dir=str(target))
        assert result["ok"], result.get("error")
        assert wsm.unregister("ws5")
        assert target.exists()
        assert (target / "AGENTS.md").is_file()
        assert wsm.get_workspace("ws5") is None

    def test_unregister_default_clone_dir_still_removed(self, remote_src, tmp_path):
        """默认落点（clone_dir 留空）：注销仍删除 _clones/{name}（现有语义不变）。"""
        result = wsm.register_git("ws6", str(remote_src), "tdm",
                                  activate=False, run_conformance=False)
        assert result["ok"], result.get("error")
        assert wsm.unregister("ws6")
        assert not (wsm.CLONES_DIR / "ws6").exists()


# ══════════════════════════════════════════════════════════
# browse-dir 端点（TestClient，mock 认证）
# ══════════════════════════════════════════════════════════

os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离 SQLite 数据文件 + 隔离工作区注册表。"""
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
def client(db):
    """装配 TestClient（mock 认证，首个登录用户自动成为 admin）。"""
    from main import app
    with TestClient(app) as c:
        yield c


def _login(client, emp_no):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": "t"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestBrowseDir:
    def test_admin_browses_dir(self, client, tmp_path):
        """目录浏览：只列子目录、过滤隐藏目录、带父级路径。"""
        (tmp_path / "ws-a").mkdir()
        (tmp_path / "ws-b").mkdir()
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".hidden").mkdir()
        headers = _login(client, "90000001")
        r = client.get("/api/workspace/browse-dir",
                       params={"path": str(tmp_path)}, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        names = [e["name"] for e in data["entries"]]
        assert "ws-a" in names and "ws-b" in names
        assert "file.txt" not in names   # 只列目录
        assert ".hidden" not in names    # 隐藏目录过滤
        assert data["parent"] == str(tmp_path.resolve().parent)

    def test_root_view_returns_entries(self, client):
        """path 为空：返回根视图（Windows 驱动器 / 其他平台根目录）。"""
        headers = _login(client, "90000001")
        r = client.get("/api/workspace/browse-dir", params={"path": ""}, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["entries"]) >= 1

    def test_nonexistent_path_errors(self, client, tmp_path):
        """不存在的路径：ok=False 且给出明确错误。"""
        headers = _login(client, "90000001")
        r = client.get("/api/workspace/browse-dir",
                       params={"path": str(tmp_path / "nope")}, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert "目录不存在" in data["error"]

    def test_non_admin_forbidden(self, client):
        """非 admin（tester）无权浏览服务器目录。"""
        from services import user_store
        _login(client, "90000001")
        h_user = _login(client, "90000002")
        user_store.set_roles("90000002", ["tester"], actor="90000001")
        r = client.get("/api/workspace/browse-dir", params={"path": ""}, headers=h_user)
        assert r.status_code == 403

    def test_register_git_with_clone_dir(self, client, tmp_path):
        """REST 层完整链路：register-git 携带 clone_dir 克隆到自定义落点。"""
        src = tmp_path / "remote_src"
        create_valid_workspace(src)
        _git(["init", "-b", "main"], cwd=src)
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "init"], cwd=src)

        target = tmp_path / "custom" / "ws-api"
        headers = _login(client, "90000001")
        r = client.post("/api/workspace/register-git", headers=headers, json={
            "name": "ws-api", "url": str(src), "system": "tdm",
            "branch": "main", "clone_dir": str(target),
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True, data.get("error")
        assert (target / "AGENTS.md").is_file()
        info = wsm.get_workspace("ws-api")
        assert info and Path(info.local_path).is_absolute()
        assert info.root == target
        # 清理注册表（自定义落点目录保留，符合注销语义）
        wsm.unregister("ws-api")
        assert target.exists()
