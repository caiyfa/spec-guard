"""specstd — SpecGuard Spec 标准层。

SpecGuard 定标准的代码化（§2.5）。本包是 Spec 仓库结构标准 v1 的单一事实源，
为合规校验器、锚点解析、内容签名、工作区接入提供统一定义。

引擎层 engine/ 零接触——本包不导入任何 engine 模块。
"""

from specstd.schema import (
    SPECSTD_VERSION,
    # 目录/文件常量
    DIR_SPECS, DIR_CHANGES, DIR_ARCHIVE,
    FILE_AGENTS_MD, FILE_SPEC_MD, FILE_API_YAML,
    FILE_DELTA_SPEC_MD, FILE_API_DELTA_YAML, FILE_MANIFEST,
    FILE_PROPOSAL_MD,
    # 锚点正则
    FR_HEADING_RE, FR_LIST_RE, FR_INLINE_RE, AC_RE,
    DELTA_MARKER_RE, TASK_REF_RE, TASK_BACK_REF_RE,
    # Delta 三段式
    SECTION_ADDED, SECTION_MODIFIED, SECTION_REMOVED,
    DELTA_SECTIONS,
    # 操作类型
    OP_ADD, OP_MODIFY, OP_REMOVE,
    # 合规规则
    RuleName, RuleLevel, RULE_DEFS,
    # 数据类
    Finding, ConformanceReport,
    AnchorInfo, DeltaOperation, ParsedDeltaSpec,
)
