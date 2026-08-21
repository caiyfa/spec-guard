"""specstd.glossary 测试：语义词典（glossary.md）轻解析。

T-505：词条格式约定（七维适配版 + [token:] 锚点）+ 候选提取；
词条↔FR 关联校验进 conformance 留 T-508 后评（本测试只测解析能力）。
"""

from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from specstd.glossary import (
    GLOSSARY_FILE,
    parse_glossary,
    scan_glossary,
    extract_fr_refs,
)

# ── 样例词典（覆盖七维字段 + [token:] 锚点 + 歧义史）──

SAMPLE_GLOSSARY = """# 语义词典（TDM 工作区）

> 词条格式约定：### 词条标题 [token: 词条token]
> 七维字段：语义 / 规则 / 数据 / 关联 / 歧义史 / 出处（锚点 [token:] 为第七维）。

## 词条区

### 盘点会话 [token: inventory-session]

- **语义**：一次盘点活动内的会话，由活动+平台唯一确定
- **规则**：仅 ACTIVE 或 CLOSED 状态的活动下允许创建/操作会话
- **数据**：tdm_inv_session，session_status（IN_PROGRESS/COMPLETED）
- **关联**：FR-001 FR-004（inventory-session）；场景 IS-PREP-002；资源码 TDM_INV_ACTIVITY
- **歧义史**：CLOSED 活动重开会话曾误判为禁止
- **出处**：specs/inventory/inventory-session/spec.md

### 权限预检 [token: precheck-permission]

- **语义**：写型场景首步校验账号权限
- **规则**：无权限时首步诚实 SKIP
- **关联**：资源码 TDM_INV_ACTIVITY；场景 IS-PREP-002
- **出处**：docs/经验包/2026-08-02-EX-8200eada

### 无关联词条 [token: no-ref]

- **语义**：没有任何 FR/场景关联的词条（收录标准警告对象）
"""


@pytest.fixture()
def sample_dict(tmp_path: Path) -> Path:
    p = tmp_path / GLOSSARY_FILE
    p.write_text(SAMPLE_GLOSSARY, encoding="utf-8")
    return p


def test_parse_glossary_extracts_entries(sample_dict):
    entries = parse_glossary(sample_dict)
    assert len(entries) == 3
    tokens = [e.token for e in entries]
    assert tokens == ["inventory-session", "precheck-permission", "no-ref"]


def test_parse_glossary_fields(sample_dict):
    entries = parse_glossary(sample_dict)
    inv = entries[0]
    assert inv.title == "盘点会话"
    assert inv.token == "inventory-session"
    assert "一次盘点活动内的会话" in inv.semantic
    assert "仅 ACTIVE 或 CLOSED 状态" in inv.rules
    assert "tdm_inv_session" in inv.data
    assert "FR-001" in inv.refs
    assert "IS-PREP-002" in inv.refs
    assert "TDM_INV_ACTIVITY" in inv.refs
    assert "CLOSED 活动重开会话曾误判" in inv.history
    assert "specs/inventory/inventory-session/spec.md" in inv.source


def test_parse_glossary_missing_file_returns_empty(tmp_path):
    assert parse_glossary(tmp_path / "nope.md") == []


def test_parse_glossary_ignores_non_token_headings(sample_dict):
    """没有 [token:] 锚点的标题不算词条（与 anchors 同款纪律）。"""
    text = SAMPLE_GLOSSARY + "\n### 普通标题（无锚点）\n\n- **语义**：不算词条\n"
    p = sample_dict.parent / "extra.md"
    p.write_text(text, encoding="utf-8")
    entries = parse_glossary(p)
    assert len(entries) == 3


def test_scan_glossary_from_workspace_root(tmp_path):
    """scan_glossary 从工作区根解析 glossary.md。"""
    p = tmp_path / GLOSSARY_FILE
    p.write_text(SAMPLE_GLOSSARY, encoding="utf-8")
    result = scan_glossary(tmp_path)
    assert set(result.keys()) == {"inventory-session", "precheck-permission", "no-ref"}


def test_scan_glossary_missing_returns_empty(tmp_path):
    assert scan_glossary(tmp_path) == {}


def test_extract_fr_refs(sample_dict):
    entries = parse_glossary(sample_dict)
    frs = extract_fr_refs(entries)
    assert frs["inventory-session"] == ["FR-001", "FR-004"]
    assert frs["precheck-permission"] == []
    assert frs["no-ref"] == []


def test_parse_glossary_duplicate_token_last_wins(tmp_path):
    text = SAMPLE_GLOSSARY + """
### 重复词条 [token: inventory-session]

- **语义**：重复定义（后者覆盖）
"""
    p = tmp_path / GLOSSARY_FILE
    p.write_text(text, encoding="utf-8")
    entries = parse_glossary(p)
    by_token = {e.token: e for e in entries}
    assert len(by_token) == 3
    assert "重复定义" in by_token["inventory-session"].semantic
