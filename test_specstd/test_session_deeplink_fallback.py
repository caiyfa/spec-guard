"""T-1040 getSession 深链兜底测试——历史会话目录名与 meta.workspace 错位可读。

背景（2026-08-29 主库验收返修自验发现）：早期会话的存盘子目录名与 meta.workspace
可能错位（如 smoke/ 目录的会话 meta 记为「人才发展」），深链/树外打开按任一名字
查都 404 空态。get_session 增加第三层兜底：指定 workspace 与根目录都 miss 时按
子目录名逐一尝试。

全部离线：tmp_path 造目录 + 直调路由函数（duck-typing 伪 user）。
"""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.auth as auth_mod  # noqa: E402

importlib.reload(auth_mod)

SID = "20260829_123324_cddd2b0a"


def _write_session(emp_dir: Path, sub: str, sid: str):
    """造一个最小会话文件：meta 行 + 一条 user 消息。"""
    d = emp_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    meta = {"_type": "session_meta", "session_id": sid, "emp_no": "90024166",
            "workspace": "人才发展", "purpose": "test_workbench", "purpose_locked": True}
    msg = {"role": "user", "content": "深链兜底测试消息"}
    (d / f"{sid}.jsonl").write_text(
        json.dumps(meta, ensure_ascii=False) + "\n" + json.dumps(msg, ensure_ascii=False) + "\n",
        encoding="utf-8")


class _FakeUser:
    emp_no = "90024166"
    is_admin = False


@pytest.fixture()
def routed(tmp_path, monkeypatch):
    from routers import agent as agent_mod
    emp_dir = tmp_path / "90024166"
    monkeypatch.setattr(agent_mod, "_sessions_dir", lambda emp: emp_dir)
    monkeypatch.setattr(agent_mod, "_iter_all_session_dirs", lambda: [emp_dir])
    return agent_mod, emp_dir


class TestDeepLinkFallback:
    def test_workspace_mismatch_falls_back_to_subdirs(self, routed):
        """meta.workspace（人才发展）≠ 存盘子目录（smoke）——兜底扫描命中并如实返回真实子目录。"""
        agent_mod, emp_dir = routed
        _write_session(emp_dir, "smoke", SID)
        r = agent_mod.get_session(SID, workspace="人才发展", user=_FakeUser())
        assert r["session_id"] == SID
        assert r["workspace"] == "smoke", "兜底命中应返回真实存盘子目录"
        assert any(m.get("content") == "深链兜底测试消息" for m in r["messages"])

    def test_workspace_match_direct(self, routed):
        """目录名与请求 workspace 一致时直接命中（不进兜底）。"""
        agent_mod, emp_dir = routed
        _write_session(emp_dir, "人才发展", SID)
        r = agent_mod.get_session(SID, workspace="人才发展", user=_FakeUser())
        assert r["workspace"] == "人才发展"
        assert r["messages"]

    def test_missing_everywhere_404(self, routed):
        agent_mod, emp_dir = routed
        _write_session(emp_dir, "smoke", SID)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            agent_mod.get_session("20260829_999999_nosuch", workspace="tdm", user=_FakeUser())
        assert ei.value.status_code == 404
