"""test_feishu_tag_registry.py — 话题标签词表单测（tag-taxonomy：标签爆炸收口）。

背景：话题 keywords 此前为 LLM 自由文本，无词表无归并——14 张卡裂出 40+ 标签
（Bug/Bug 140594/140594 同义三分、人名单号混入、粒度失控）。词表 = 话题库同域
的受控词汇事实源（_tags.yaml，状态制 active/pending），提供：
- canonicalize：别名→主标签（空白/大小写不敏感键），未知词透传并报告
- register_pending：新词入待收录（幂等；已知主标签/别名跳过）
- 人工动作（merge/promote/set_domain/drop）追加 _tags_history.jsonl；
  自动注册（auto_register）不落历史——词表自然增长量大会淹没人工动作留痕
"""

import json

import pytest
import yaml

from specflow.feishu_pool import tag_registry as tr

_EDITOR = {"emp": "90000001", "name": "王测试"}


def _make_pool(tmp_path):
    """材料池根（feishu_pool/ 所在 base，与 topic_cluster 的 mroot 同语义）。"""
    base = tmp_path / ".specflow"
    (base / "feishu_pool").mkdir(parents=True)
    return base


def _write_registry(base, payload: dict):
    path = base / "feishu_pool" / "_tags.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def _read_registry(base) -> dict:
    return yaml.safe_load(
        (base / "feishu_pool" / "_tags.yaml").read_text(encoding="utf-8"))


def _read_history(base) -> list[dict]:
    path = base / "feishu_pool" / "_tags_history.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ══════════════════════════════════════════════════════════
# 读写与归一
# ══════════════════════════════════════════════════════════

def test_load_empty_returns_skeleton(tmp_path):
    base = _make_pool(tmp_path)
    reg = tr.load_registry(base)
    assert reg == {"version": 1, "tags": {}, "domains": {}}


def test_load_normalizes_entries(tmp_path):
    """存量缺字段条目补默认（status=active/source=human/aliases=[]/domain=''）。"""
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {"权限": None}})
    reg = tr.load_registry(base)
    entry = reg["tags"]["权限"]
    assert entry["status"] == "active" and entry["aliases"] == []
    assert entry["domain"] == "" and entry["source"] == "human"


# ══════════════════════════════════════════════════════════
# canonicalize（别名归并）
# ══════════════════════════════════════════════════════════

def test_canonicalize_alias_to_main_and_dedupe(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": ["数据权限", "权限需求"], "status": "active"}}})
    reg = tr.load_registry(base)
    canon, unknown = tr.canonicalize(reg, ["数据权限", "新词", "权限", "权限 "])
    assert canon == ["权限", "新词"]         # 别名归主标签；按主标签去重保序
    assert unknown == ["新词"]


def test_canonicalize_key_space_case_insensitive(tmp_path):
    """查找键忽略空白与大小写（Bug 140594 / bug140594 同键）；显示名保留原形。"""
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "Bug#140594": {"aliases": ["Bug 140594"], "status": "active"}}})
    reg = tr.load_registry(base)
    canon, unknown = tr.canonicalize(reg, ["bug140594", "BUG  140594"])
    assert canon == ["Bug#140594"]
    assert unknown == []


# ══════════════════════════════════════════════════════════
# register_pending / canonicalize_and_register
# ══════════════════════════════════════════════════════════

def test_register_pending_idempotent_and_skips_known(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": ["数据权限"], "status": "active"}}})
    reg = tr.load_registry(base)
    added = tr.register_pending(reg, ["新词", "权限", "数据权限", "新词"], source="llm")
    assert added == ["新词"]                 # 已知主标签/别名/批内重复均跳过
    assert reg["tags"]["新词"]["status"] == "pending"
    assert reg["tags"]["新词"]["source"] == "llm"
    assert tr.register_pending(reg, ["新词"], source="llm") == []   # 幂等


def test_canonicalize_and_register_persists_without_history(tmp_path):
    """单发路径：归一 + 未知词落 pending 存盘；自动注册不写历史（降噪决策）。"""
    base = _make_pool(tmp_path)
    canon = tr.canonicalize_and_register(base, ["同步", "人力数据中台"], source="llm")
    assert canon == ["同步", "人力数据中台"]
    saved = _read_registry(base)
    assert saved["tags"]["同步"]["status"] == "pending"
    assert saved["tags"]["人力数据中台"]["status"] == "pending"
    assert _read_history(base) == []         # 自动注册不落历史


# ══════════════════════════════════════════════════════════
# 人工动作：merge / promote / set_domain / drop
# ══════════════════════════════════════════════════════════

def test_merge_pending_into_active_becomes_alias(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": [], "status": "active"},
        "数据权限": {"aliases": [], "status": "pending"}}})
    tr.merge_tag(base, "数据权限", "权限", editor=_EDITOR)
    tags = _read_registry(base)["tags"]
    assert "数据权限" not in tags
    assert "数据权限" in tags["权限"]["aliases"]
    hist = _read_history(base)
    assert hist[-1]["action"] == "merge" and hist[-1]["editor"] == _EDITOR
    assert hist[-1]["changes"]["source"] == "数据权限"
    assert hist[-1]["changes"]["target"] == "权限"


def test_merge_canonical_moves_own_aliases(tmp_path):
    """源本身是主标签（自带别名）→ 别名随迁入目标，源条目移除。"""
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": ["权限控制"], "status": "active"},
        "权限需求": {"aliases": ["数据权限"], "status": "active"}}})
    tr.merge_tag(base, "权限需求", "权限", editor=_EDITOR)
    tags = _read_registry(base)["tags"]
    assert "权限需求" not in tags
    assert set(tags["权限"]["aliases"]) == {"权限控制", "数据权限", "权限需求"}


def test_merge_promotes_pending_target(tmp_path):
    """归并到待收录词 = 人工收录该词并吸收源（目标转 active）。"""
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "140594": {"aliases": [], "status": "pending"},
        "Bug#140594": {"aliases": [], "status": "pending"}}})
    tr.merge_tag(base, "140594", "Bug#140594", editor=_EDITOR)
    tags = _read_registry(base)["tags"]
    assert tags["Bug#140594"]["status"] == "active"
    assert tags["Bug#140594"]["source"] == "human"
    assert "140594" in tags["Bug#140594"]["aliases"]


def test_merge_creates_missing_target(tmp_path):
    """目标不在词表 → 以人工名义新建 active 条目并吸收源（收录新词同步归并）。"""
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "Bug 140594": {"aliases": [], "status": "pending"}}})
    tr.merge_tag(base, "Bug 140594", "Bug#140594", editor=_EDITOR)
    tags = _read_registry(base)["tags"]
    assert tags["Bug#140594"]["status"] == "active"
    assert "Bug 140594" in tags["Bug#140594"]["aliases"]


def test_merge_same_target_rejected(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": ["数据权限"], "status": "active"}}})
    with pytest.raises(ValueError):
        tr.merge_tag(base, "数据权限", "权限", editor=_EDITOR)   # 已是别名=同词
    with pytest.raises(ValueError):
        tr.merge_tag(base, "权限", "权限", editor=_EDITOR)


def test_merge_missing_source_raises(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {}})
    with pytest.raises(KeyError):
        tr.merge_tag(base, "不存在", "权限", editor=_EDITOR)


def test_promote_and_drop_pending(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "同步": {"aliases": [], "status": "pending"},
        "噪音词": {"aliases": [], "status": "pending"},
        "权限": {"aliases": [], "status": "active"}}})
    tr.promote_tag(base, "同步", editor=_EDITOR)
    assert _read_registry(base)["tags"]["同步"]["status"] == "active"
    with pytest.raises(KeyError):
        tr.promote_tag(base, "不存在", editor=_EDITOR)
    with pytest.raises(ValueError):
        tr.drop_tag(base, "权限", editor=_EDITOR)      # active 只能被归并走
    tr.drop_tag(base, "噪音词", editor=_EDITOR)        # pending 可丢弃（噪音清理）
    assert "噪音词" not in _read_registry(base)["tags"]
    hist = _read_history(base)
    assert [h["action"] for h in hist] == ["promote", "drop"]


def test_set_tag_domain_creates_domain_entry(tmp_path):
    """设域：域不存在自动建档（active）；空串清除；标签不存在 KeyError。"""
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": [], "status": "active"}}})
    tr.set_tag_domain(base, "权限", "平台权限", editor=_EDITOR)
    saved = _read_registry(base)
    assert saved["tags"]["权限"]["domain"] == "平台权限"
    assert saved["domains"]["平台权限"]["status"] == "active"
    tr.set_tag_domain(base, "权限", "", editor=_EDITOR)
    assert _read_registry(base)["tags"]["权限"]["domain"] == ""
    with pytest.raises(KeyError):
        tr.set_tag_domain(base, "不存在", "x", editor=_EDITOR)
    hist = _read_history(base)
    assert [h["action"] for h in hist] == ["set_domain", "set_domain"]


# ══════════════════════════════════════════════════════════
# known_tags_digest（prompt 注入清单）
# ══════════════════════════════════════════════════════════

def test_known_tags_digest_active_first_with_alias_and_pending_mark(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "权限": {"aliases": ["数据权限"], "status": "active"},
        "新词": {"aliases": [], "status": "pending"},
        "同步": {"aliases": [], "status": "active"}}})
    reg = tr.load_registry(base)
    lines = tr.known_tags_digest(reg).splitlines()
    assert len(lines) == 3
    pend_idx = next(i for i, ln in enumerate(lines) if ln.startswith("- 新词"))
    assert pend_idx == 2                       # active 优先，pending 殿后
    assert "待收录" in lines[pend_idx]
    perm_line = next(ln for ln in lines if ln.startswith("- 权限"))
    assert perm_line == "- 权限（别名: 数据权限）"


def test_known_tags_digest_cap_and_empty(tmp_path):
    base = _make_pool(tmp_path)
    _write_registry(base, {"version": 1, "tags": {
        "甲": {"aliases": [], "status": "active"},
        "乙": {"aliases": [], "status": "active"}}})
    reg = tr.load_registry(base)
    assert len(tr.known_tags_digest(reg, limit=1).splitlines()) == 1
    assert tr.known_tags_digest(
        {"version": 1, "tags": {}, "domains": {}}) == ""
