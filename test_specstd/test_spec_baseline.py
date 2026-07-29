"""spec 签名基线测试（K-007）。

覆盖：init/has_changes/update 基线管理 + spec_body/api 变更检测 +
无基线自动初始化（防 register 误触发）+ settings_store 开关。
全部离线：tmp 工作区 + tmp DB。
"""

import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import spec_baseline, settings_store, user_store  # noqa: E402

SPEC_V1 = "# M1-F1\n\n### FR-001: 查询功能\nAC-001 查询返回 200\n"
SPEC_V2 = "# M1-F1\n\n### FR-001: 查询功能\nAC-001 查询返回 200\nAC-002 结果非空\n"

API_V1 = """openapi: 3.0.3
paths:
  /api/query:
    get:
      parameters:
        - name: id
          in: query
          required: true
          schema: {type: string}
      responses:
        '200':
          description: ok
"""

API_V2_ADD_FIELD = """openapi: 3.0.3
paths:
  /api/query:
    get:
      parameters:
        - name: id
          in: query
          required: true
          schema: {type: string}
        - name: page
          in: query
          required: false
          schema: {type: integer}
      responses:
        '200':
          description: ok
"""


@pytest.fixture()
def ws(tmp_path):
    """最小 spec 工作区（spec.md + api.yaml）。"""
    repo = tmp_path / "repo"
    d = repo / "specs" / "m1" / "f1"
    d.mkdir(parents=True)
    (d / "spec.md").write_text(SPEC_V1, encoding="utf-8")
    (d / "api.yaml").write_text(API_V1, encoding="utf-8")
    return repo


# ══════════════════════════════════════════════════════════
# 基线管理核心
# ══════════════════════════════════════════════════════════

def test_init_and_no_changes(ws):
    assert spec_baseline.init_baseline(ws) is True
    assert spec_baseline.has_spec_changes(ws) is False


def test_no_baseline_auto_init(ws):
    """无基线时自动建初始基线并视为无变更（防 register 误触发，K-007 核心）。"""
    bp = spec_baseline._baseline_path(ws)
    assert not bp.is_file()
    assert spec_baseline.detect_spec_changes(ws) == []
    assert spec_baseline.has_spec_changes(ws) is False
    assert bp.is_file()  # 已自动建基线


def test_detect_spec_body_change(ws):
    spec_baseline.init_baseline(ws)
    (ws / "specs" / "m1" / "f1" / "spec.md").write_text(SPEC_V2, encoding="utf-8")
    assert spec_baseline.has_spec_changes(ws) is True
    changes = spec_baseline.detect_spec_changes(ws)
    assert any(c["type"] == "spec_body_changed" for c in changes)


def test_detect_api_field_change(ws):
    """api.yaml 字段级变更可检测（研发修正接口的典型场景）。"""
    spec_baseline.init_baseline(ws)
    (ws / "specs" / "m1" / "f1" / "api.yaml").write_text(API_V2_ADD_FIELD, encoding="utf-8")
    assert spec_baseline.has_spec_changes(ws) is True


def test_update_baseline_resets(ws):
    """审计后更新基线 → 变更被消化，不再重复触发。"""
    spec_baseline.init_baseline(ws)
    (ws / "specs" / "m1" / "f1" / "spec.md").write_text(SPEC_V2, encoding="utf-8")
    assert spec_baseline.has_spec_changes(ws) is True
    spec_baseline.update_baseline(ws)
    assert spec_baseline.has_spec_changes(ws) is False


def test_closed_loop(ws):
    """完整闭环：建基线 → 变更 → 检测 → 更新 → 再变更 → 再检测。"""
    spec_baseline.init_baseline(ws)
    (ws / "specs" / "m1" / "f1" / "spec.md").write_text(SPEC_V2, encoding="utf-8")
    assert spec_baseline.has_spec_changes(ws) is True   # 研发第一次修正
    spec_baseline.update_baseline(ws)                    # 审计完成
    assert spec_baseline.has_spec_changes(ws) is False
    (ws / "specs" / "m1" / "f1" / "spec.md").write_text(SPEC_V1, encoding="utf-8")
    assert spec_baseline.has_spec_changes(ws) is True   # 研发再次修正（回退也算变更）


# ══════════════════════════════════════════════════════════
# settings_store 开关
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    return db_file


def test_settings_default_manual(db):
    """K-007 决策 1：默认手动（自动更新开关默认 False）。"""
    assert settings_store.audit_auto_update_baseline() is False


def test_settings_toggle(db):
    settings_store.set_bool(settings_store.KEY_AUDIT_AUTO_UPDATE_BASELINE, True)
    assert settings_store.audit_auto_update_baseline() is True
    settings_store.set_bool(settings_store.KEY_AUDIT_AUTO_UPDATE_BASELINE, False)
    assert settings_store.audit_auto_update_baseline() is False
