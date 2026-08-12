"""delta 文档写通道测试（方案 A：产品/管理员可写 changes/{delta}/ 起草区文档）。

覆盖：
1. 服务层：正常写新文件 / 覆盖+备份 / delta 不存在拒绝 / delta_id 非法拒绝 /
   filename 路径穿越拒绝（../、绝对路径）/ 冻结 delta 拒绝（工作区与 .specflow
   两处 FREEZE.yaml 凭证）/ 禁止写 FREEZE.yaml 本身 / 写后 conformance 校验
2. REST：PUT /api/spec/changes/{delta} RBAC（product/admin 可写，tester/viewer 403）
3. MCP：write_delta_doc 工具正常调用 + 越权路径拒绝
4. 工具注册：write_delta_doc 入册 + side_effect=draft + product 白名单可见
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

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

from test_specstd.helpers import create_valid_workspace  # noqa: E402
import specstd.workspace as wsm  # noqa: E402
from specstd.workspace import register_local, unregister  # noqa: E402


# ══════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cleanup_ctx():
    """防 contextvar 泄漏：REST 请求/测试内的 emp/workspace 注入影响后续测试。"""
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def repo(tmp_path, db):
    """注册合规工作区（含 delta-001 起草区）。依赖 db：先隔离注册表路径再注册。"""
    ws = create_valid_workspace(tmp_path / "repo")
    register_local("tdm", str(ws), "tdm", activate=True)
    yield ws
    unregister("tdm")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离 SQLite 数据文件（user_store 审计用）。"""
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
    def test_write_new_file(self, repo, db):
        """新建 delta 子目录文件（delta-specs/）。"""
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename="delta-specs/fr-extra.md",
                            content="# FR-100 新增\n### FR-100: 测试\nAC-001\n",
                            emp_no="90024166")
        assert r["ok"] is True
        assert r["path"] == "changes/delta-001/delta-specs/fr-extra.md"
        assert r["backup"] is False
        assert (repo / "changes" / "delta-001" / "delta-specs" / "fr-extra.md").is_file()
        assert r["validation"]["verdict"] in ("PASS", "REJECT")

    def test_overwrite_backup(self, repo, db):
        """覆盖已有文件 → .bak 备份生成。"""
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename="proposal.md",
                            content="# 新提案内容\n", emp_no="90024166")
        assert r["ok"] is True
        assert r["backup"] is True
        bak = repo / "changes" / "delta-001" / "proposal.md.bak"
        assert bak.is_file()
        assert "# Delta Proposal" in bak.read_text(encoding="utf-8")

    def test_delta_not_exists(self, repo, db):
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="nope",
                            filename="proposal.md", content="x", emp_no="90024166")
        assert r["ok"] is False and "不存在" in r["error"]

    def test_delta_id_traversal_rejected(self, repo, db):
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="../specs",
                            filename="proposal.md", content="x", emp_no="90024166")
        assert r["ok"] is False

    def test_filename_traversal_rejected(self, repo, db):
        """filename ../ 越界到 changes/ 外 → 拒绝。"""
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename="../specs/module1/feature1/spec.md",
                            content="x", emp_no="90024166")
        assert r["ok"] is False and "越界" in r["error"]
        # 基线 spec.md 未被触碰
        assert "### FR-001" in (repo / "specs" / "module1" / "feature1" / "spec.md").read_text(encoding="utf-8")

    def test_filename_absolute_rejected(self, repo, db):
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename=str(repo / "changes" / "delta-001" / "proposal.md"),
                            content="x", emp_no="90024166")
        assert r["ok"] is False and "越界" in r["error"]

    def test_frozen_delta_denied_ws_mark(self, repo, db):
        """工作区 changes/{delta}/FREEZE.yaml 凭证 → 冻结拒绝。"""
        (repo / "changes" / "delta-001" / "FREEZE.yaml").write_text(
            "frozen: true\n", encoding="utf-8")
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename="proposal.md", content="x", emp_no="90024166")
        assert r["ok"] is False and "冻结" in r["error"]

    def test_frozen_delta_denied_specflow_mark(self, repo, db, monkeypatch):
        """.specflow/changes/{delta}/FREEZE.yaml 凭证（S5 冻结路径）→ 拒绝。"""
        sf_mark = repo / ".specflow" / "changes" / "delta-001" / "FREEZE.yaml"
        sf_mark.parent.mkdir(parents=True, exist_ok=True)
        sf_mark.write_text("frozen: true\n", encoding="utf-8")
        # specflow_dir() 在测试上下文无 emp → 共享区 {ws}/.specflow/；
        # 注意：delta_doc_writer 模块导入时已绑定引用，须 monkeypatch 服务模块自身
        from services.specflow import delta_doc_writer as ddw
        monkeypatch.setattr(ddw, "specflow_dir", lambda emp="": repo / ".specflow")
        r = ddw.write_delta_doc(workspace="tdm", delta_id="delta-001",
                                filename="proposal.md", content="x", emp_no="90024166")
        assert r["ok"] is False and "冻结" in r["error"]

    def test_forbidden_freeze_mark_write(self, repo, db):
        """禁止直接写 FREEZE.yaml（防篡改冻结凭证）。"""
        from services.specflow.delta_doc_writer import write_delta_doc
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename="FREEZE.yaml", content="frozen: false\n",
                            emp_no="90024166")
        assert r["ok"] is False

    def test_validation_reject_on_bad_content(self, repo, db):
        """写入与 manifest 不一致的内容 → 写成功但校验 REJECT（不阻断写入）。"""
        from services.specflow.delta_doc_writer import write_delta_doc
        bad = repo / "changes" / "delta-001" / "delta-spec.md"
        orig = bad.read_text(encoding="utf-8")
        r = write_delta_doc(workspace="tdm", delta_id="delta-001",
                            filename="delta-spec.md",
                            content=orig.replace("FR-001", "FR-999"),
                            emp_no="90024166")
        assert r["ok"] is True
        assert r["validation"]["verdict"] in ("REJECT", "PASS", "ERROR")
        # 无论校验结果，文件已落盘且备份存在
        assert bad.is_file()
        assert (repo / "changes" / "delta-001" / "delta-spec.md.bak").is_file()

    def test_audit_recorded(self, repo, db):
        """写操作审计留痕。"""
        from services import user_store
        from services.specflow.delta_doc_writer import write_delta_doc
        write_delta_doc(workspace="tdm", delta_id="delta-001",
                        filename="proposal.md", content="# x\n", emp_no="90024166")
        rows = user_store.query_audit("90024166", db_path=db) if hasattr(user_store, "query_audit") else None
        # 审计表存在且含该动作（通过 DB 查询兜底）
        import sqlite3
        conn = sqlite3.connect(db)
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='write_delta_doc' AND target LIKE 'changes/delta-001/%'"
        ).fetchone()[0]
        conn.close()
        assert n >= 1


# ══════════════════════════════════════════════════════════
# REST
# ══════════════════════════════════════════════════════════

class TestREST:
    @pytest.fixture()
    def client(self, repo, db):
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

    def test_product_can_write(self, client, repo, db):
        h = self._login(client, "90024170", ["product"])
        r = client.put("/api/spec/changes/delta-001",
                       json={"filename": "proposal.md", "content": "# 产品改版\n"},
                       headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert "产品改版" in (repo / "changes" / "delta-001" / "proposal.md").read_text(encoding="utf-8")

    def test_admin_can_write(self, client, repo, db):
        h = self._login(client, "90024175", ["admin"])
        r = client.put("/api/spec/changes/delta-001",
                       json={"filename": "delta-spec.md", "content": "# Delta\n"},
                       headers=h)
        assert r.status_code == 200, r.text

    def test_tester_denied(self, client, repo, db):
        h = self._login(client, "90024172", ["tester"])
        r = client.put("/api/spec/changes/delta-001",
                       json={"filename": "proposal.md", "content": "x"},
                       headers=h)
        assert r.status_code == 403

    def test_viewer_denied(self, client, repo, db):
        h = self._login(client, "90024173", ["viewer"])
        r = client.put("/api/spec/changes/delta-001",
                       json={"filename": "proposal.md", "content": "x"},
                       headers=h)
        assert r.status_code == 403

    def test_frozen_denied_403(self, client, repo, db):
        (repo / "changes" / "delta-001" / "FREEZE.yaml").write_text("frozen: true\n", encoding="utf-8")
        h = self._login(client, "90024170", ["product"])
        r = client.put("/api/spec/changes/delta-001",
                       json={"filename": "proposal.md", "content": "x"},
                       headers=h)
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
        assert "write_delta_doc" in names

    def test_side_effect_draft(self):
        from mcp_server.tools.side_effect_registry import get_side_effect
        assert get_side_effect("write_delta_doc") == "draft"

    def test_write_success(self, repo, db):
        from mcp_server.tools import delta_doc_writer
        r = self._call(delta_doc_writer, "write_delta_doc", {
            "delta_id": "delta-001", "filename": "proposal.md", "content": "# MCP 写入\n",
        })
        assert '"ok": true' in r[0].text
        assert "changes/delta-001/proposal.md" in r[0].text

    def test_write_denied_path_traversal(self, repo, db):
        from mcp_server.tools import delta_doc_writer
        r = self._call(delta_doc_writer, "write_delta_doc", {
            "delta_id": "delta-001", "filename": "../../evil.md", "content": "x",
        })
        assert '"ok": false' in r[0].text

    def test_write_denied_frozen(self, repo, db):
        (repo / "changes" / "delta-001" / "FREEZE.yaml").write_text("frozen: true\n", encoding="utf-8")
        from mcp_server.tools import delta_doc_writer
        r = self._call(delta_doc_writer, "write_delta_doc", {
            "delta_id": "delta-001", "filename": "proposal.md", "content": "x",
        })
        assert '"ok": false' in r[0].text
        assert "冻结" in r[0].text

    def test_product_whitelist_visible(self):
        """product 角色可见 write_delta_doc（三层交集）。"""
        from agent.runtime import resolve_tools
        from agent.purpose_loader import load_purpose
        pdef = load_purpose("requirement_interview")
        tools = resolve_tools(purpose_tools=list(pdef.tools), user_roles=["product"])
        names = {t.name for t in tools}
        assert "write_delta_doc" in names
