"""Workbench deps_editor 单测：depends_on 文本外科手术（离线，临时文件）。"""

import os
import sys

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(SG_ROOT, "workbench", "backend")

from services.deps_editor import (  # noqa: E402
    DepsEditError, add_dep, remove_dep, expected_version_of,
)

SAMPLE = """id: T-001
title: 测试场景
version: "0.1"
depends_on:
  - {id: UP-001, version: ^0}   # 已有依赖
  - UP-002
produces:
  - {resource: inv_session, state: IN_PROGRESS}
doc:
  given: 多行
         折叠文本不要动
flow:
  - tool: {use: select_emp, with: {role: x}, save: emp}
  - call:
      method: GET
      path: /api/x
      save: resp
verify:
  - status: {eq: 200}
"""

NO_DEPS = """id: T-002
title: 无依赖场景
version: "0.1"
flow:
  - call: {method: GET, path: /api/x, save: resp}
verify:
  - status: {eq: 200}
"""

EMPTY_DEPS = """id: T-003
title: 空依赖场景
version: "0.1"
depends_on: []
flow:
  - call: {method: GET, path: /api/x, save: resp}
"""

@pytest.fixture()
def yaml_file(tmp_path):
    def _make(content):
        p = tmp_path / "sc.yaml"
        p.write_text(content, encoding="utf-8")
        return str(p)
    return _make

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

def test_expected_version():
    assert expected_version_of("0.1") == "^0"
    assert expected_version_of("1.2") == "^1"

def test_add_dep_shared(yaml_file):
    path = yaml_file(SAMPLE)
    add_dep(path, "UP-003", "shared", "0.1")
    text = _read(path)
    assert "  - {id: UP-003, version: ^0}" in text
    # 既有内容零改动（注释/标量依赖/doc 折叠文本都在）
    assert "# 已有依赖" in text
    assert "- UP-002" in text
    assert "折叠文本不要动" in text

def test_add_dep_exclusive(yaml_file):
    path = yaml_file(SAMPLE)
    add_dep(path, "UP-004", "exclusive", "1.2")
    assert "{id: UP-004, mode: exclusive, version: ^1}" in _read(path)

def test_add_dep_duplicate_rejected(yaml_file):
    path = yaml_file(SAMPLE)
    with pytest.raises(DepsEditError, match="已存在"):
        add_dep(path, "UP-001", "shared", "0.1")

def test_add_dep_no_section(yaml_file):
    path = yaml_file(NO_DEPS)
    add_dep(path, "UP-001", "shared", "0.1")
    text = _read(path)
    assert "depends_on:\n  - {id: UP-001, version: ^0}\nflow:" in text

def test_add_dep_empty_section(yaml_file):
    path = yaml_file(EMPTY_DEPS)
    add_dep(path, "UP-001", "shared", "0.1")
    text = _read(path)
    assert "depends_on:\n  - {id: UP-001, version: ^0}" in text
    assert "depends_on: []" not in text

def test_remove_dep_dict_form(yaml_file):
    path = yaml_file(SAMPLE)
    remove_dep(path, "UP-001")
    text = _read(path)
    assert "UP-001" not in text
    assert "- UP-002" in text   # 其余依赖保留

def test_remove_dep_scalar_form(yaml_file):
    path = yaml_file(SAMPLE)
    remove_dep(path, "UP-002")
    assert "- UP-002" not in _read(path)

def test_remove_dep_missing_rejected(yaml_file):
    path = yaml_file(SAMPLE)
    with pytest.raises(DepsEditError, match="不存在"):
        remove_dep(path, "GHOST")

def test_remove_last_dep_collapses_section(yaml_file):
    path = yaml_file(SAMPLE)
    remove_dep(path, "UP-001")
    remove_dep(path, "UP-002")
    assert "depends_on: []" in _read(path)
