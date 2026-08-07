"""章节提取测试（S0.5 · T-512）：mcp_server/tools/sections.py

覆盖：FR 标题式/列表式、AC 块、md 标题树（编号/文字）、yaml part（保注释）、未命中。
"""

import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from mcp_server.tools.sections import (
    extract_fr_section, extract_heading_section, extract_yaml_part, list_fr_anchors,
)


# ── FR 列表式（tdm 生产 spec 主形态）──
SPEC_LIST_MD = """# 标签库规格

## 4. Functional Requirements

- **FR-001**：标签 CRUD——创建、读取、更新、删除操作。
  系统 SHALL 提供标签管理界面。
- **FR-002**：标签名称唯一性校验——同名拒绝。

## 5. Acceptance Criteria

- [ ] **AC-001**：创建标签后列表立即可见
- [ ] **AC-002**：同名创建返回 409
- [ ] **AC-003**：删除被引用标签返回引用数量
"""

# ── FR 标题式（delta/archive 形态）──
SPEC_HEADING_MD = """## ADDED Requirements

### FR-033: 历史盘点切片绩效数据时点过滤
系统 SHALL 按时点过滤绩效数据。
第二行说明。

### FR-034: 另一条需求
内容。
"""


class TestFrSection:
    def test_list_form(self):
        hit = extract_fr_section(SPEC_LIST_MD, "FR-001")
        assert hit is not None
        assert hit["title"].startswith("FR-001")
        assert "标签 CRUD" in hit["chunk"]
        assert "SHALL 提供标签管理" in hit["chunk"]  # 缩进续行纳入
        assert "FR-002" not in hit["chunk"]
        lines = SPEC_LIST_MD.splitlines()
        assert lines[hit["start"] - 1].startswith("- **FR-001**")
        assert "FR-002" in lines[hit["end"]]  # end 下一行即 FR-002（闭区间外）

    def test_list_form_last_item_to_section_end(self):
        hit = extract_fr_section(SPEC_LIST_MD, "FR-002")
        assert hit is not None
        assert "唯一性校验" in hit["chunk"]
        assert "Acceptance" not in hit["chunk"]  # 止于下一标题

    def test_heading_form(self):
        hit = extract_fr_section(SPEC_HEADING_MD, "FR-033")
        assert hit is not None
        assert "时点过滤" in hit["chunk"]
        assert "第二行说明" in hit["chunk"]
        assert "FR-034" not in hit["chunk"]
        assert hit["title"].startswith("FR-033")

    def test_ac_block(self):
        hit = extract_fr_section(SPEC_LIST_MD, "AC-002")
        assert hit is not None
        assert "AC-001" in hit["chunk"] and "AC-003" in hit["chunk"]  # 连续列表块
        assert "FR-001" not in hit["chunk"]
        assert "同名创建返回 409" in hit["title"]

    def test_miss_returns_none(self):
        assert extract_fr_section(SPEC_LIST_MD, "FR-999") is None
        assert extract_fr_section(SPEC_LIST_MD, "") is None

    def test_list_fr_anchors(self):
        assert list_fr_anchors(SPEC_LIST_MD) == ["FR-001", "FR-002"]
        assert list_fr_anchors(SPEC_HEADING_MD) == ["FR-033", "FR-034"]


class TestHeadingSection:
    def test_by_number(self):
        hit = extract_heading_section(SPEC_LIST_MD, "4")
        assert hit is not None
        assert "FR-001" in hit["chunk"] and "FR-002" in hit["chunk"]
        assert "Acceptance" not in hit["chunk"]  # 止于下一同级标题

    def test_by_text_case_insensitive(self):
        hit = extract_heading_section(SPEC_LIST_MD, "acceptance")
        assert hit is not None
        assert "AC-001" in hit["chunk"]

    def test_miss_returns_none(self):
        assert extract_heading_section(SPEC_LIST_MD, "不存在的章节") is None
        assert extract_heading_section(SPEC_LIST_MD, "") is None


SCENARIO_YAML = """# 场景注释
doc:
  id: PP-RC-001
  covers: [FR-001, FR-002]
  given: 已登录
flow:
  - call: /api/a
    json: {}
  # 步骤注释
  - call: /api/b
verify:
  - expect: status == 200
"""

SCENARIO_YAML_MULTILINE_COVERS = """doc:
  id: X
  covers:
    - FR-001
    - FR-009
  given: ...
flow:
  - call: /a
"""


class TestYamlPart:
    def test_flow_part_keeps_comments(self):
        hit = extract_yaml_part(SCENARIO_YAML, "flow")
        assert hit is not None
        assert "/api/a" in hit["chunk"] and "/api/b" in hit["chunk"]
        assert "# 步骤注释" in hit["chunk"]  # 注释保留
        assert "verify" not in hit["chunk"]
        assert hit["title"] == "flow 段"

    def test_doc_part(self):
        hit = extract_yaml_part(SCENARIO_YAML, "doc")
        assert "covers" in hit["chunk"] and "flow:" not in hit["chunk"]

    def test_verify_part_last_section(self):
        hit = extract_yaml_part(SCENARIO_YAML, "verify")
        assert "status == 200" in hit["chunk"]

    def test_covers_inline(self):
        hit = extract_yaml_part(SCENARIO_YAML, "covers")
        assert "FR-001" in hit["chunk"] and "FR-002" in hit["chunk"]

    def test_covers_multiline(self):
        hit = extract_yaml_part(SCENARIO_YAML_MULTILINE_COVERS, "covers")
        assert "FR-009" in hit["chunk"]
        assert "given" not in hit["chunk"]

    def test_miss_returns_none(self):
        assert extract_yaml_part(SCENARIO_YAML, "不存在") is None
        assert extract_yaml_part(SCENARIO_YAML, "") is None
