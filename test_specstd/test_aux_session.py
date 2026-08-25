"""辅助会话 session 模型（设计 2026-08-25 §B2）：extra_meta 透传 / save 继承 / list 返回 / set_meta_fields。"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def sm(tmp_path):
    from agent.session import SessionManager
    return SessionManager(tmp_path, workspace="w1")


def test_create_with_extra_meta(sm):
    sid = sm.create(emp_no="90024166", workspace="w1", purpose="sql_assistant",
                    extra_meta={"kind": "aux", "parent_session_id": "PARENT1"})
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["kind"] == "aux"
    assert meta["parent_session_id"] == "PARENT1"
    mfile = sm.sessions_dir / f"{sid}_meta.json"
    assert json.loads(mfile.read_text(encoding="utf-8"))["kind"] == "aux"


def test_create_without_extra_meta_unchanged(sm):
    sid = sm.create(emp_no="e", workspace="w1")
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert "kind" not in meta  # 非辅助会话不写 kind（存量语义不变）


def test_save_inherits_aux_fields(sm):
    sid = sm.create(emp_no="e", workspace="w1", purpose="sql_assistant",
                    extra_meta={"kind": "aux", "parent_session_id": "P1", "last_parent_fp": "abc"})
    sm.save(sid, [{"role": "user", "content": "hi"}], emp_no="e", workspace="w1")
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["kind"] == "aux"
    assert meta["parent_session_id"] == "P1"
    assert meta["last_parent_fp"] == "abc"


def test_list_sessions_returns_aux_fields(sm):
    p = sm.create(emp_no="e", workspace="w1")
    a = sm.create(emp_no="e", workspace="w1", purpose="sql_assistant",
                  extra_meta={"kind": "aux", "parent_session_id": p})
    sessions = sm.list_sessions()
    aux = next(s for s in sessions if s["id"] == a)
    parent = next(s for s in sessions if s["id"] == p)
    assert aux["kind"] == "aux"
    assert aux["parent_session_id"] == p
    assert parent.get("kind", "") == ""


def test_set_meta_fields_roundtrip(sm):
    sid = sm.create(emp_no="e", workspace="w1")
    ok = sm.set_meta_fields(sid, last_parent_fp="fp123")
    assert ok is True
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["last_parent_fp"] == "fp123"
    sm.set_meta_fields(sid, kind="aux")
    meta = sm._read_meta(sm.sessions_dir / f"{sid}.jsonl")
    assert meta["last_parent_fp"] == "fp123" and meta["kind"] == "aux"


def test_set_meta_fields_missing_session(sm):
    assert sm.set_meta_fields("nonexistent_sid", kind="aux") is False
