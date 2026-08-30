"""T-1042 flow-trace 端点测试——工作台实时跑偏扫描（GET /agent/sessions/{id}/flow-trace）。

全部离线：tmp_path 造会话 + 直调路由函数（duck-typing 伪 user，与
test_session_deeplink_fallback 同款装配）。覆盖：生成会话返回阶段四态与跑偏、
会话不存在 404、非生成会话诚实标注、evals 降级面。
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

SID = "20260830_090000_aaa1b2c3"


class _FakeUser:
    emp_no = "90024166"
    is_admin = False


def _write_generate_session(emp_dir: Path, sid: str = SID):
    """造一个最小「创建测试用例」会话：读需求→校验→写草稿（缺 get_id/registry/参照）。"""
    d = emp_dir / "tdm"
    d.mkdir(parents=True, exist_ok=True)
    rows = [
        {"_type": "session_meta", "session_id": sid, "emp_no": "90024166",
         "workspace": "tdm", "purpose": "test_workbench", "purpose_locked": True},
        {"role": "user", "content": "生成 FR-001 的测试场景"},
        {"role": "assistant", "tool_calls": [{"id": "a", "type": "function",
         "function": {"name": "spec", "arguments": json.dumps({"action": "read"})}}]},
        {"role": "tool", "tool_call_id": "a", "content": "spec 内容"},
        {"role": "assistant", "tool_calls": [{"id": "b", "type": "function",
         "function": {"name": "validate", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "b", "content": '{"verdict": "PASS"}'},
        {"role": "assistant", "tool_calls": [{"id": "c", "type": "function",
         "function": {"name": "draft", "arguments": json.dumps({"action": "write"})}}]},
        {"role": "tool", "tool_call_id": "c", "content": "已写入草稿"},
    ]
    (d / f"{sid}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


@pytest.fixture()
def routed(tmp_path, monkeypatch):
    from routers import agent as agent_mod
    emp_dir = tmp_path / "90024166"
    monkeypatch.setattr(agent_mod, "_sessions_dir", lambda emp: emp_dir)
    monkeypatch.setattr(agent_mod, "_iter_all_session_dirs", lambda: [emp_dir])
    return agent_mod, emp_dir


class TestFlowTraceEndpoint:
    def test_generate_session_returns_stages_and_deviations(self, routed):
        """生成会话 → 阶段四态 + 跑偏清单（缺 get_id/registry/参照如实列出）。"""
        agent_mod, emp_dir = routed
        _write_generate_session(emp_dir)
        r = agent_mod.get_session_flow_trace(SID, workspace="", user=_FakeUser())
        assert r["available"] is True
        assert r["is_generate"] is True
        assert r["flow_id"] == "generate-scenario"
        statuses = {s["key"]: s["status"] for s in r["stages"]}
        assert statuses["read_requirement"] == "in_order"
        assert statuses["validate"] == "in_order"
        assert statuses["write_draft"] == "in_order"
        assert statuses["get_id"] == "missing"
        assert statuses["query_registry"] == "missing"
        assert r["n_missing"] >= 3
        assert "flowchart TD" in r["mermaid"] and "classDef hit" in r["mermaid"]
        assert any("缺失必需阶段「取场景 ID」" in d for d in r["deviations"])
        # 步号证据（spec 第 1 步、draft 第 3 步）
        st_map = {s["key"]: s for s in r["stages"]}
        assert st_map["read_requirement"]["first_step"] == 1
        assert st_map["write_draft"]["first_step"] == 3

    def test_missing_session_404(self, routed):
        agent_mod, emp_dir = routed
        _write_generate_session(emp_dir)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            agent_mod.get_session_flow_trace("20260830_999999_nosuch", workspace="",
                                             user=_FakeUser())
        assert ei.value.status_code == 404

    def test_non_generate_session_still_traced(self, routed):
        """只读问答会话照常返回（is_generate=false，前端标注基线仅供参考）。"""
        agent_mod, emp_dir = routed
        d = emp_dir / "tdm"
        d.mkdir(parents=True, exist_ok=True)
        rows = [
            {"_type": "session_meta", "session_id": SID, "emp_no": "90024166",
             "workspace": "tdm", "purpose": "test_workbench", "purpose_locked": True},
            {"role": "user", "content": "查询场景库有哪些"},
        ]
        (d / f"{SID}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        r = agent_mod.get_session_flow_trace(SID, workspace="", user=_FakeUser())
        assert r["available"] is True
        assert r["is_generate"] is False

    def test_invalid_session_id_400(self, routed):
        agent_mod, _emp = routed
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            agent_mod.get_session_flow_trace("../evil", workspace="", user=_FakeUser())
        assert ei.value.status_code == 400
