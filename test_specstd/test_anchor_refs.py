"""anchor_refs 解析测试（T-1023）：FR/AC 锚点 → spec 原文片段。

覆盖：FR 标题式 / FR 列表式 / AC 反查 / 未命中诚实 found=False /
同号歧义返回全部候选 + hint 路径词排序 / ids 上限。
数据源为临时工作区目录（specs/{module}/{feature}/spec.md 布局），零网络零 DB。
"""

from pathlib import Path

from services import anchor_refs

_SPEC_HEADING = """# 历史盘点

### FR-005: 历史盘点查询
支持按快照五条件 + corp_code 范围查询历史盘点记录。

- [ ] **AC-005**：PART 权限仅返回授权 corp 范围数据

### FR-007: 历史盘点导出
查询结果可导出。
"""

_SPEC_LIST = """# 系统设置

- **FR-101**：标签库维护
  支持标签的增删改查。
- **FR-102**：标签发布
"""

_SPEC_DUP = """# 数据导出

- **FR-005**：前端使用 pollExport 模式下载导出结果
"""


def _mk_ws(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_fr_heading_section(tmp_path):
    ws = _mk_ws(tmp_path, {"specs/inventory/history/spec.md": _SPEC_HEADING})
    (ref,) = anchor_refs.resolve_anchor_refs(ws, ["FR-005"])
    assert ref["found"] is True
    (m,) = ref["matches"]
    assert "历史盘点查询" in m["title"]
    assert "corp_code" in m["chunk"]
    # 到下一同级标题为止，不吞 FR-007
    assert "导出" not in m["chunk"]
    assert m["start"] < m["end"]
    assert m["module"] == "inventory" and m["feature"] == "history"
    assert m["rel"] == "specs/inventory/history/spec.md"


def test_fr_list_section(tmp_path):
    ws = _mk_ws(tmp_path, {"specs/system-settings/tag-library/spec.md": _SPEC_LIST})
    (ref,) = anchor_refs.resolve_anchor_refs(ws, ["FR-101"])
    assert ref["found"] is True
    assert "标签库维护" in ref["matches"][0]["chunk"]
    assert "FR-102" not in ref["matches"][0]["chunk"]


def test_ac_reverse_lookup(tmp_path):
    ws = _mk_ws(tmp_path, {"specs/inventory/history/spec.md": _SPEC_HEADING})
    (ref,) = anchor_refs.resolve_anchor_refs(ws, ["AC-005"])
    assert ref["found"] is True
    assert "AC-005" in ref["matches"][0]["chunk"]


def test_not_found_is_honest(tmp_path):
    ws = _mk_ws(tmp_path, {"specs/inventory/history/spec.md": _SPEC_HEADING})
    refs = anchor_refs.resolve_anchor_refs(ws, ["FR-999", "AC-999", ""])
    assert refs == [
        {"id": "FR-999", "found": False, "matches": []},
        {"id": "AC-999", "found": False, "matches": []},
    ]


def test_duplicate_fr_returns_all_candidates_sorted_by_hint(tmp_path):
    ws = _mk_ws(tmp_path, {
        "specs/inventory/history/spec.md": _SPEC_HEADING,
        "specs/data/data-export/spec.md": _SPEC_DUP,
    })
    # 无 hint：两候选都返回
    (ref,) = anchor_refs.resolve_anchor_refs(ws, ["FR-005"])
    assert ref["found"] is True
    assert len(ref["matches"]) == 2
    # hint 为场景路径（inventory 模块）：历史盘点候选排第一
    (ref2,) = anchor_refs.resolve_anchor_refs(
        ws, ["FR-005"], hint="inventory/inventory-session/HI-PERM-002.yaml")
    assert "历史盘点查询" in ref2["matches"][0]["title"]
    assert "pollExport" in ref2["matches"][1]["title"]


def test_empty_specs_dir(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    assert anchor_refs.resolve_anchor_refs(tmp_path, ["FR-005"]) == [
        {"id": "FR-005", "found": False, "matches": []}
    ]


def test_ids_capped(tmp_path):
    ws = _mk_ws(tmp_path, {"specs/inventory/history/spec.md": _SPEC_HEADING})
    refs = anchor_refs.resolve_anchor_refs(ws, [f"FR-{i:03d}" for i in range(80)])
    assert len(refs) == anchor_refs.MAX_IDS
