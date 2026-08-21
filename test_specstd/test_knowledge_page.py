"""knowledge_service / knowledge router 测试（T-509 知识维护页一页三区）。

覆盖：
- 词条：加载（词条列表 + 断链校验）、保存（保存即 conformance 校验 + 审计）
- 环境叙事：凭据红线（含凭据拒绝保存）、合法保存
- 经验队列列表
- RBAC：product/viewer 无写权限（后端 require_role）
"""

import os
import sys
from pathlib import Path

import pytest

# mock 鉴权模式才能用 TestClient
os.environ["SG_AUTH_MODE"] = "mock"

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
if str(SG_ROOT / "workbench" / "backend") not in sys.path:
    sys.path.insert(0, str(SG_ROOT / "workbench" / "backend"))

from unittest.mock import patch  # noqa: E402

from specstd.workspace import (  # noqa: E402
    register_local,
    reset_context_emp_no,
    reset_context_workspace,
    set_context_emp_no,
    set_context_workspace,
)


@pytest.fixture()
def ws(tmp_path):
    """注册临时工作区（tdm 系统），写入词典与叙事。"""
    root = tmp_path / "tdm-ws"
    (root / "specs" / "inventory" / "inventory-session").mkdir(parents=True)
    (root / "specs" / "inventory" / "inventory-session" / "spec.md").write_text(
        "### FR-001: 会话唯一\nAC-001 唯一\n\n### FR-004: 完成\n", encoding="utf-8")
    (root / "glossary.md").write_text(
        "### 盘点会话 [token: inventory-session]\n\n"
        "- **语义**：会话唯一\n"
        "- **关联**：FR-001 FR-004；场景 IS-PREP-002\n",
        encoding="utf-8")
    r = register_local("tdm-test", str(root), system="tdm", activate=True,
                       run_conformance=False)
    assert r["ok"], r
    yield root
    # 清理注册表（避免污染其他测试）
    from specstd.workspace import unregister
    unregister("tdm-test")


@pytest.fixture()
def ctx(ws):
    """请求级工作区 + 用户上下文。"""
    t1 = set_context_workspace("tdm-test")
    t2 = set_context_emp_no("90024166")
    yield ws
    reset_context_workspace(t1)
    reset_context_emp_no(t2)


@pytest.fixture()
def client():
    """TestClient（mock 鉴权 + 已登录）。"""
    from fastapi.testclient import TestClient

    from workbench.backend.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def headers(client):
    """mock-login 并返回鉴权 header（admin 角色）。"""
    r = client.post("/api/auth/mock-login", json={"emp_no": "90024166", "name": "测试员"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ══════════════════════════════════════════════════════════
# 词条区
# ══════════════════════════════════════════════════════════

class TestGlossary:
    def test_load_glossary_entries_and_findings(self, ctx):
        from services import knowledge_service as ks
        d = ks.load_glossary()
        assert len(d["entries"]) == 1
        assert d["entries"][0]["token"] == "inventory-session"
        # FR-001/FR-004 均在 spec.md 中 → 无断链
        assert d["findings"] == []

    def test_save_glossary_broken_fr_flagged(self, ctx):
        """保存即校验：词条引用不存在的 FR → 断链标红（保存仍成功，标注 ERROR）。"""
        from services import knowledge_service as ks
        broken = ("### 盘点会话 [token: inventory-session]\n\n"
                  "- **语义**：会话唯一\n"
                  "- **关联**：FR-999；场景 IS-PREP-002\n")
        d = ks.save_glossary(broken, emp="90024166")
        assert len(d["entries"]) == 1
        errs = [f for f in d["findings"] if f["level"] == "ERROR"]
        assert any("FR-999" in f["message"] for f in errs)

    def test_glossary_api_get(self, ctx, client, headers):
        r = client.get("/api/knowledge/glossary", headers={**headers, "X-SG-Workspace": "tdm-test"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["entries"]) == 1
        assert body["entries"][0]["token"] == "inventory-session"

    def test_glossary_api_put(self, ctx, client, headers):
        text = ("### 盘点会话 [token: inventory-session]\n\n"
                "- **语义**：会话唯一 v2\n"
                "- **关联**：FR-001\n")
        r = client.put("/api/knowledge/glossary",
                       headers={**headers, "X-SG-Workspace": "tdm-test"},
                       json={"text": text})
        assert r.status_code == 200
        body = r.json()
        assert body["entries"][0]["semantic"] == "会话唯一 v2"


# ══════════════════════════════════════════════════════════
# 环境叙事区（凭据红线）
# ══════════════════════════════════════════════════════════

class TestEnvNarrative:
    def test_credential_redline_rejects(self, ctx):
        """凭据红线：叙事含 password: xxx 真实值 → 拒绝保存。"""
        from services import knowledge_service as ks
        with patch.object(ks, "_active_system", return_value="tdm"):
            r = ks.save_env_narrative("sit", "# 环境叙事\npassword: hunter2\n",
                                      emp="90024166")
        assert r["saved"] is False
        assert "凭据红线" in r["message"]
        assert any(f["level"] == "ERROR" for f in r["findings"])

    def test_save_env_narrative_ok(self, ctx, tmp_path):
        """合法叙事保存成功（SG_ROOT 重定向 tmp 隔离——2026-08-11 曾误删
        T-506 产物 env.sit.md；2026-08-21 再修：恢复式写盘内容虽同但碰真实文件
        mtime，每轮全量回归后遗留 stat 脏（验收反馈），改为根本不碰真实适配包）。"""
        from services import knowledge_service as ks
        with patch.object(ks, "_active_system", return_value="tdm"), \
             patch.object(ks, "SG_ROOT", tmp_path):
            r = ks.save_env_narrative("sit", "# 环境叙事\n\n## 一、定位\nSIT 环境\n",
                                      emp="90024166")
        assert r["saved"] is True
        assert (tmp_path / "systems" / "tdm" / "config" / "env.sit.md").is_file()

    def test_env_api_credential_rejected(self, ctx, client, headers):
        r = client.put("/api/knowledge/env/sit",
                       headers={**headers, "X-SG-Workspace": "tdm-test"},
                       json={"text": "# 叙事\nclient_secret: 12345\n"})
        assert r.status_code == 200
        body = r.json()
        assert body["saved"] is False
        assert "凭据红线" in body["message"]


# ══════════════════════════════════════════════════════════
# 经验队列 + RBAC
# ══════════════════════════════════════════════════════════

class TestExperienceQueue:
    def test_list_experience_empty(self, ctx):
        from services import knowledge_service as ks
        items = ks.list_experience_queue()
        assert items == []

    def test_experience_api(self, ctx, client, headers):
        r = client.get("/api/knowledge/experience",
                       headers={**headers, "X-SG-Workspace": "tdm-test"})
        assert r.status_code == 200
        assert "items" in r.json()


class TestRbac:
    def test_write_requires_tester_up(self, ctx, client):
        """product/viewer 无写权限（require_role admin/tester 拦截）。"""
        with patch("workbench.backend.services.auth.get_current_user") as mock_user:
            mock_user.return_value = type("U", (), {"emp_no": "90024166", "roles": ["product"]})()
            r = client.put("/api/knowledge/glossary",
                           headers={"X-SG-Workspace": "tdm-test"},
                           json={"text": "### x [token: x]\n- **语义**：x\n"})
            assert r.status_code in (401, 403)
