"""test_feishu_tag_router.py — tag-taxonomy 标签词表端点路由层单测。

路由函数直调（不走 TestClient——认证/workspace 中间件与 RBAC 另有测试覆盖；
模式同 test_feishu_t948_router.py），patch _material_base 指向 tmp 词表区。
词表核心业务逻辑在 test_feishu_tag_registry.py 已覆盖，此处聚焦 HTTP 语义
转换：成功载荷 / KeyError→404 / ValueError→400 / editor 身份落
_tags_history.jsonl（多用户协作留痕）。
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from routers import feishu_pool as rp  # noqa: E402

_USER = SimpleNamespace(emp_no="90000001", name="王测试")


def _mk_pool(tmp_path: Path, tags: dict | None = None,
             domains: dict | None = None) -> Path:
    """词表区（feishu_pool/ 所在 base）；tags=None 不建档（空骨架路径）。"""
    base = tmp_path / ".specflow"
    (base / "feishu_pool").mkdir(parents=True, exist_ok=True)
    if tags is not None or domains is not None:
        (base / "feishu_pool" / "_tags.yaml").write_text(
            yaml.safe_dump({"version": 1, "tags": tags or {},
                            "domains": domains or {}},
                           allow_unicode=True), encoding="utf-8")
    return base


def _read_registry(base: Path) -> dict:
    return yaml.safe_load(
        (base / "feishu_pool" / "_tags.yaml").read_text(encoding="utf-8"))


def _read_history(base: Path) -> list[dict]:
    path = base / "feishu_pool" / "_tags_history.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ══════════════════════════════════════════════════════════
# GET /tags
# ══════════════════════════════════════════════════════════

def test_get_tags_empty_skeleton(tmp_path):
    """词表未建档 → 空骨架（诚实呈现，前端平铺降级依据）。"""
    base = _mk_pool(tmp_path)
    with patch.object(rp, "_material_base", return_value=base):
        out = rp.get_tag_registry(user=_USER, workspace="tdm")
    assert out == {"version": 1, "tags": {}, "domains": {}}


def test_get_tags_returns_pending_visible(tmp_path):
    """pending 待收录词随清单返回（前端虚线芯片/管理弹层数据源）。"""
    base = _mk_pool(tmp_path, tags={
        "权限": {"aliases": ["数据权限"], "domain": "平台权限",
                 "status": "active", "source": "human", "created_at": ""},
        "新指标": {"aliases": [], "domain": "", "status": "pending",
                   "source": "llm", "created_at": ""},
    })
    with patch.object(rp, "_material_base", return_value=base):
        out = rp.get_tag_registry(user=_USER, workspace="tdm")
    assert out["tags"]["新指标"]["status"] == "pending"
    assert out["tags"]["权限"]["aliases"] == ["数据权限"]


# ══════════════════════════════════════════════════════════
# POST /tags/merge
# ══════════════════════════════════════════════════════════

def test_merge_tag_ok_and_editor_in_history(tmp_path):
    """归并成功：源成别名 + editor 身份落历史（路由层身份透传验证）。"""
    base = _mk_pool(tmp_path, tags={
        "权限": {"aliases": [], "status": "active"},
        "数据权限": {"aliases": [], "status": "pending"}})
    body = rp.TagMergeRequest(source="数据权限", target="权限")
    with patch.object(rp, "_material_base", return_value=base):
        out = rp.merge_tag(body, user=_USER, workspace="tdm")
    assert out["ok"] is True
    assert "数据权限" in out["entry"]["aliases"]
    hist = _read_history(base)
    assert hist[-1]["action"] == "merge"
    assert hist[-1]["editor"] == {"emp": "90000001", "name": "王测试"}


def test_merge_tag_missing_source_404(tmp_path):
    base = _mk_pool(tmp_path, tags={})
    body = rp.TagMergeRequest(source="不存在", target="权限")
    with patch.object(rp, "_material_base", return_value=base), \
         pytest.raises(Exception) as ei:
        rp.merge_tag(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404


def test_merge_tag_same_target_400(tmp_path):
    base = _mk_pool(tmp_path, tags={
        "权限": {"aliases": ["数据权限"], "status": "active"}})
    body = rp.TagMergeRequest(source="数据权限", target="权限")
    with patch.object(rp, "_material_base", return_value=base), \
         pytest.raises(Exception) as ei:
        rp.merge_tag(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 400


# ══════════════════════════════════════════════════════════
# POST /tags/promote ｜ POST /tags/drop
# ══════════════════════════════════════════════════════════

def test_promote_tag_ok(tmp_path):
    base = _mk_pool(tmp_path, tags={
        "同步": {"aliases": [], "status": "pending"}})
    body = rp.TagNameRequest(name="同步")
    with patch.object(rp, "_material_base", return_value=base):
        out = rp.promote_tag(body, user=_USER, workspace="tdm")
    assert out["ok"] is True
    assert out["entry"]["status"] == "active"
    assert _read_history(base)[-1]["action"] == "promote"


def test_promote_tag_missing_404(tmp_path):
    base = _mk_pool(tmp_path, tags={})
    body = rp.TagNameRequest(name="不存在")
    with patch.object(rp, "_material_base", return_value=base), \
         pytest.raises(Exception) as ei:
        rp.promote_tag(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404


def test_drop_tag_pending_ok(tmp_path):
    base = _mk_pool(tmp_path, tags={
        "噪音词": {"aliases": [], "status": "pending"}})
    body = rp.TagNameRequest(name="噪音词")
    with patch.object(rp, "_material_base", return_value=base):
        out = rp.drop_tag(body, user=_USER, workspace="tdm")
    assert out["ok"] is True
    assert "噪音词" not in _read_registry(base)["tags"]
    assert _read_history(base)[-1]["action"] == "drop"


def test_drop_tag_active_400(tmp_path):
    """active 只能被归并走 → 400（防误删正式词）。"""
    base = _mk_pool(tmp_path, tags={
        "权限": {"aliases": [], "status": "active"}})
    body = rp.TagNameRequest(name="权限")
    with patch.object(rp, "_material_base", return_value=base), \
         pytest.raises(Exception) as ei:
        rp.drop_tag(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 400


# ══════════════════════════════════════════════════════════
# POST /tags/domain
# ══════════════════════════════════════════════════════════

def test_set_tag_domain_ok_creates_domain(tmp_path):
    """设域成功：标签挂域 + 域自动建档。"""
    base = _mk_pool(tmp_path, tags={
        "权限": {"aliases": [], "status": "active"}})
    body = rp.TagDomainRequest(name="权限", domain="平台权限")
    with patch.object(rp, "_material_base", return_value=base):
        out = rp.set_tag_domain(body, user=_USER, workspace="tdm")
    assert out["ok"] is True
    assert out["entry"]["domain"] == "平台权限"
    saved = _read_registry(base)
    assert saved["domains"]["平台权限"]["status"] == "active"
    hist = _read_history(base)
    assert hist[-1]["action"] == "set_domain"
    assert hist[-1]["editor"]["emp"] == "90000001"


def test_set_tag_domain_missing_404(tmp_path):
    base = _mk_pool(tmp_path, tags={})
    body = rp.TagDomainRequest(name="不存在", domain="x")
    with patch.object(rp, "_material_base", return_value=base), \
         pytest.raises(Exception) as ei:
        rp.set_tag_domain(body, user=_USER, workspace="tdm")
    assert getattr(ei.value, "status_code", None) == 404
