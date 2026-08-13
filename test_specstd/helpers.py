"""specstd 测试辅助：创建各种 spec 仓库样例（合规 + 7 类违规）。

从 conftest.py 分离出来，避免与根目录 conftest.py 的模块名冲突。
"""

import sys
from pathlib import Path

# 添加仓库根到 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))


# ══════════════════════════════════════════════════════════
# 合规仓库样例
# ══════════════════════════════════════════════════════════

AGENTS_MD = """# Test Spec Repository

## Project Overview

这是一个测试用的 spec 仓库，用于验证 SpecGuard 合规校验器。

## 术语 Token

- FR: Functional Requirement（功能需求）
- AC: Acceptance Criteria（验收标准）
- delta: 变更代号

## Always

- 写场景前先读 format_spec.py

## Never

- 不在代码里硬编码环境凭据
"""

SPEC_MD = """# Module1 - Feature1

## 一、功能描述

### FR-001: 查询功能
AC-001 查询返回 200
AC-002 查询结果非空

### FR-002: 创建功能
AC-003 创建返回 201
"""

API_YAML = """openapi: 3.0.3
info:
  title: Test API
  version: 1.0.0
paths:
  /api/test:
    get:
      summary: Test endpoint
"""

DELTA_SPEC_MD = """# Delta: delta001

## ADDED Requirements

### FR-001: 新增查询功能 [delta:delta001]

全量描述：新增查询接口，支持分页和过滤。

→ task: TSK-001

## MODIFIED Requirements

### FR-002: 修改创建功能 [delta:delta001]

**原描述**: 原来的创建功能
**新描述**: 修改后的创建功能，增加了参数校验
**原因**: 需要增加参数校验以防止非法输入

→ task: TSK-002

## REMOVED Requirements

### FR-003: 删除旧功能 [delta:delta001]

**原描述**: 旧的废弃功能

→ task: TSK-003
"""

MANIFEST_YAML = """delta: delta001
baseline: "1.0"
baseline_sha: "a3f8c21"
operations:
  - op: add
    fr: FR-001
    section: ADDED Requirements
    new: "新增查询功能"
    task: TSK-001
  - op: modify
    fr: FR-002
    section: MODIFIED Requirements
    original: "原来的创建功能"
    new: "修改后的创建功能"
    reason: "需要增加参数校验"
    task: TSK-002
  - op: remove
    fr: FR-003
    section: REMOVED Requirements
    original: "旧的废弃功能"
    task: TSK-003
"""

TASK_MD = """# Task List

### TSK-001 新增查询功能 ←delta:delta001

### TSK-002 修改创建功能 ←delta:delta001

### TSK-003 删除旧功能 ←delta:delta001
"""

API_DELTA_YAML = """openapi: 3.0.3
info:
  title: API Delta
  version: 1.0.0
paths:
  /api/query:
    get:
      summary: Query endpoint
"""


def create_valid_workspace(path: Path) -> Path:
    """创建完全合规的 spec 仓库样例。"""
    (path / "specs" / "module1" / "feature1").mkdir(parents=True, exist_ok=True)
    (path / "changes" / "delta001").mkdir(parents=True, exist_ok=True)
    (path / "archive").mkdir(parents=True, exist_ok=True)

    (path / "AGENTS.md").write_text(AGENTS_MD, encoding="utf-8")
    (path / "specs" / "module1" / "feature1" / "spec.md").write_text(SPEC_MD, encoding="utf-8")
    (path / "specs" / "module1" / "feature1" / "api.yaml").write_text(API_YAML, encoding="utf-8")

    delta_dir = path / "changes" / "delta001"
    (delta_dir / "proposal.md").write_text("# Delta Proposal: delta001\n", encoding="utf-8")
    (delta_dir / "delta-spec.md").write_text(DELTA_SPEC_MD, encoding="utf-8")
    (delta_dir / "delta.manifest.yaml").write_text(MANIFEST_YAML, encoding="utf-8")
    (delta_dir / "task.md").write_text(TASK_MD, encoding="utf-8")
    (delta_dir / "api-delta.yaml").write_text(API_DELTA_YAML, encoding="utf-8")

    return path


def create_struct_violation(path: Path) -> Path:
    """STRUCT 违规：缺少必备目录。"""
    ws = create_valid_workspace(path)
    import shutil
    shutil.rmtree(ws / "archive")
    return ws


def create_agents_violation(path: Path) -> Path:
    """AGENTS 违规：AGENTS.md 缺少术语 token 清单节。"""
    ws = create_valid_workspace(path)
    (ws / "AGENTS.md").write_text(
        "# Test Spec Repository\n\n## Project Overview\n\n缺少术语节。\n",
        encoding="utf-8",
    )
    return ws


def create_anchor_violation(path: Path) -> Path:
    """ANCHOR 违规：FR 锚点重复。"""
    ws = create_valid_workspace(path)
    (ws / "specs" / "module1" / "feature2").mkdir(parents=True, exist_ok=True)
    (ws / "specs" / "module1" / "feature2" / "spec.md").write_text(
        "# Module1 - Feature2\n\n### FR-001: 重复的查询功能\nAC-001\n",
        encoding="utf-8",
    )
    return ws


def create_manifest_violation(path: Path) -> Path:
    """MANIFEST 违规：manifest operations 与 delta-spec 不一致。"""
    ws = create_valid_workspace(path)
    (ws / "changes" / "delta001" / "delta.manifest.yaml").write_text(
        MANIFEST_YAML
        + """  - op: add
    fr: FR-099
    section: ADDED Requirements
    new: "不存在的功能"
    task: TSK-099
""",
        encoding="utf-8",
    )
    return ws


def create_modify_full_violation(path: Path) -> Path:
    """MODIFY_FULL 违规：MODIFIED 条目缺少三要素。"""
    ws = create_valid_workspace(path)
    (ws / "changes" / "delta001" / "delta-spec.md").write_text(
        """# Delta: delta001

## ADDED Requirements

### FR-001: 新增查询功能 [delta:delta001]

全量描述：新增查询接口。

→ task: TSK-001

## MODIFIED Requirements

### FR-002: 修改创建功能 [delta:delta001]

**原描述**: 原来的创建功能
**新描述**: 修改后的创建功能

→ task: TSK-002

## REMOVED Requirements

### FR-003: 删除旧功能 [delta:delta001]

**原描述**: 旧的废弃功能

→ task: TSK-003
""",
        encoding="utf-8",
    )
    return ws


def create_trace_violation(path: Path) -> Path:
    """TRACE 违规：delta-spec 引用的 task 在 task.md 中不存在。"""
    ws = create_valid_workspace(path)
    (ws / "changes" / "delta001" / "delta-spec.md").write_text(
        DELTA_SPEC_MD.replace("→ task: TSK-001", "→ task: TSK-099"),
        encoding="utf-8",
    )
    return ws


def create_api_lint_violation(path: Path) -> Path:
    """API_LINT 违规：api.yaml 缺少 openapi 版本声明。"""
    ws = create_valid_workspace(path)
    (ws / "specs" / "module1" / "feature1" / "api.yaml").write_text(
        "info:\n  title: Bad API\npaths:\n  /api:\n    get:\n      summary: Bad\n",
        encoding="utf-8",
    )
    return ws
