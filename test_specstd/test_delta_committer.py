"""delta 受限提交测试（方案 A 扩展：commit_delta_changes）。

覆盖：
1. 服务层：非 git 工作区拒绝 / delta 不存在拒绝 / 冻结拒绝 / conformance
   未通过拒绝 / message 前缀校验 / 无变更拒绝 / 正常提交（排除 .bak）/
   .bak 不进入提交
2. REST：POST /api/spec/changes/{delta}/commit RBAC（product/admin 可，
   tester/viewer 403）
3. MCP：commit_delta_changes 工具注册 + 调用
"""

import os
import subprocess
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

from test_specstd.helpers import create_valid_workspace  # noqa: E402
import specstd.workspace as wsm  # noqa: E402
from specstd.workspace import register_local, unregister  # noqa: E402


def _git(args: list, cwd: Path):
    """测试辅助：执行 git 命令（UTF-8）。"""
    return subprocess.run(args, cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def git_init_workspace(path: Path) -> Path:
    """把合规工作区初始化为 git 仓库（含初始 commit），返回工作区根。"""
    _git(["git", "init", "-b", "main"], path)
    _git(["git", "config", "user.email", "test@specguard.local"], path)
    _git(["git", "config", "user.name", "SpecGuard Test"], path)
    _git(["git", "add", "-A"], path)
    r = _git(["git", "commit", "-m", "chore: 初始基线"], path)
    assert r.returncode == 0, r.stderr
    return path


# ══════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cleanup_ctx():
    """防 contextvar 泄漏。"""
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def git_repo(tmp_path, db):
    """git 型合规工作区（含 delta001 起草区 + 初始 commit）。"""
    ws = create_valid_workspace(tmp_path / "repo")
    git_init_workspace(ws)
    register_local("tdm", str(ws), "tdm", activate=True)
    yield ws
    unregister("tdm")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离 SQLite 数据文件。"""
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from services import user_store
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    from services.auth import _TOKEN_CACHE
    _TOKEN_CACHE.clear()
    return db_file


# ══════════════════════════════════════════════════════════
# 服务层
# ══════════════════════════════════════════════════════════

class TestService:
    def _change(self, repo, filename="proposal.md", content="# 变更内容\n"):
        """先写文件制造变更（走 write_delta_doc 产生 .bak 的可控变更）。"""
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta001",
                            filename=filename, content=content, emp_no="90024166")
        assert r["ok"] is True

    def test_non_git_repo_rejected(self, tmp_path, db):
        """非 git 工作区拒绝（.git 不存在）。"""
        ws = create_valid_workspace(tmp_path / "plain")
        register_local("plain", str(ws), "tdm", activate=True)
        try:
            from services.specflow.delta_committer import commit_delta_changes
            r = commit_delta_changes(workspace="plain", delta_id="delta001",
                                     emp_no="90024166")
            assert r["ok"] is False and "不是 git 仓库" in r["error"]
        finally:
            unregister("plain")

    def test_delta_not_exists(self, git_repo, db):
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="nope", emp_no="90024166")
        assert r["ok"] is False and "不存在" in r["error"]

    def test_frozen_rejected(self, git_repo, db):
        (git_repo / "changes" / "delta001" / "FREEZE.yaml").write_text(
            "frozen: true\n", encoding="utf-8")
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="delta001", emp_no="90024166")
        assert r["ok"] is False and "冻结" in r["error"]

    def test_conformance_error_rejected(self, git_repo, db):
        """写入破坏 conformance 的内容 → 提交被门禁拦截。"""
        bad = git_repo / "changes" / "delta001" / "delta-spec.md"
        orig = bad.read_text(encoding="utf-8")
        (bad).write_text(orig.replace("FR-001", "FR-999"), encoding="utf-8")
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="delta001", emp_no="90024166")
        assert r["ok"] is False
        assert "conformance" in r["error"] or "校验" in r["error"]

    def test_bad_message_prefix_rejected(self, git_repo, db):
        self._change(git_repo)
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="delta001",
                                 message="随便写", emp_no="90024166")
        assert r["ok"] is False and "前缀" in r["error"]

    def test_no_changes_rejected(self, git_repo, db):
        """无变更 → 拒绝（避免空提交）。"""
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="delta001", emp_no="90024166")
        assert r["ok"] is False and "无变更" in r["error"]

    def test_commit_success_auto_message(self, git_repo, db):
        """正常提交：自动 message、.bak 被排除、文件清单正确。"""
        self._change(git_repo)  # proposal.md 变更 + 生成 .bak
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="delta001", emp_no="90024166")
        assert r["ok"] is True, r
        assert r["message"].startswith("feat: delta delta001")
        assert "未 push" in r["note"]
        # 文件清单：proposal.md 在，.bak 不在
        assert any("proposal.md" in f for f in r["files"])
        assert not any(f.endswith(".bak") for f in r["files"])
        # HEAD 前进且工作区干净（proposal.md.bak 未跟踪但被 gitignore？断言提交生效即可）
        out = _git(["git", "log", "-1", "--pretty=%s"], git_repo)
        assert "delta delta001" in out.stdout

    def test_commit_custom_message(self, git_repo, db):
        self._change(git_repo)
        from services.specflow.delta_committer import commit_delta_changes
        r = commit_delta_changes(workspace="tdm", delta_id="delta001",
                                 message="docs: 修正编号映射", emp_no="90024166")
        assert r["ok"] is True
        out = _git(["git", "log", "-1", "--pretty=%s"], git_repo)
        assert "修正编号映射" in out.stdout

    def test_commit_audit_recorded(self, git_repo, db):
        self._change(git_repo)
        from services.specflow.delta_committer import commit_delta_changes
        commit_delta_changes(workspace="tdm", delta_id="delta001", emp_no="90024166")
        import sqlite3
        conn = sqlite3.connect(db)
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='commit_delta_changes'"
        ).fetchone()[0]
        conn.close()
        assert n >= 1


# ══════════════════════════════════════════════════════════
# REST
# ══════════════════════════════════════════════════════════

class TestREST:
    @pytest.fixture()
    def client(self, git_repo, db):
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c

    def _login(self, client, emp_no: str, roles: list):
        r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": emp_no})
        assert r.status_code == 200, r.text
        from services import user_store
        user_store.set_roles(emp_no, roles, actor=emp_no)
        user_store.grant_workspace("tdm", emp_no, emp_no)
        tok = r.json()["token"]
        return {"Authorization": f"Bearer {tok}", "X-SG-Workspace": "tdm"}

    def _make_change(self, git_repo):
        from services.specflow.delta_doc_writer import write_delta_doc
        write_delta_doc(workspace="tdm", delta_id="delta001",
                        filename="proposal.md", content="# 变更\n", emp_no="90024166")

    def test_product_can_commit(self, client, git_repo, db):
        self._make_change(git_repo)
        h = self._login(client, "90024170", ["product"])
        r = client.post("/api/spec/changes/delta001/commit", json={}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_tester_denied(self, client, git_repo, db):
        h = self._login(client, "90024172", ["tester"])
        r = client.post("/api/spec/changes/delta001/commit", json={}, headers=h)
        assert r.status_code == 403

    def test_viewer_denied(self, client, git_repo, db):
        h = self._login(client, "90024173", ["viewer"])
        r = client.post("/api/spec/changes/delta001/commit", json={}, headers=h)
        assert r.status_code == 403

    def test_frozen_denied_403(self, client, git_repo, db):
        (git_repo / "changes" / "delta001" / "FREEZE.yaml").write_text(
            "frozen: true\n", encoding="utf-8")
        h = self._login(client, "90024170", ["product"])
        r = client.post("/api/spec/changes/delta001/commit", json={}, headers=h)
        assert r.status_code == 403
        assert "冻结" in r.json()["detail"]


# ══════════════════════════════════════════════════════════
# MCP 工具
# ══════════════════════════════════════════════════════════

class TestMCP:
    def _call(self, module, name, arguments):
        import asyncio
        return asyncio.run(module.handle(name, arguments))

    def test_tool_registered(self):
        from mcp_server.server import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "commit_delta_changes" in names

    def test_side_effect_draft(self):
        from mcp_server.tools.side_effect_registry import get_side_effect
        assert get_side_effect("commit_delta_changes") == "draft"

    def test_commit_success(self, git_repo, db):
        from services.specflow.delta_doc_writer import write_delta_doc
        write_delta_doc(workspace="tdm", delta_id="delta001",
                        filename="proposal.md", content="# MCP 提交\n", emp_no="")
        from mcp_server.tools import delta_doc_writer
        r = self._call(delta_doc_writer, "commit_delta_changes", {"delta_id": "delta001"})
        assert '"ok": true' in r[0].text
        assert "未 push" in r[0].text

    def test_commit_no_changes(self, git_repo, db):
        from mcp_server.tools import delta_doc_writer
        r = self._call(delta_doc_writer, "commit_delta_changes", {"delta_id": "delta001"})
        assert '"ok": false' in r[0].text
        assert "无变更" in r[0].text

    def test_product_whitelist_visible(self):
        """product 角色可见 commit_delta_changes（三层交集）。"""
        from agent.runtime import resolve_tools
        from agent.purpose_loader import load_purpose
        pdef = load_purpose("requirement_interview")
        tools = resolve_tools(purpose_tools=list(pdef.tools), user_roles=["product"])
        names = {t.name for t in tools}
        assert "commit_delta_changes" in names
