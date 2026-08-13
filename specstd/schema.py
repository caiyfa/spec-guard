"""specstd.schema — Spec 仓库结构标准 v1 的代码化（单一事实源）。

取材自 Spec 工作流手册 V3，经 SpecGuard 裁剪固化为机器可校验规则。
本模块只定义「标准是什么」，不执行校验（校验逻辑在 conformance.py）。

§2.1 目录结构 + §2.2 合规校验规则 + manifest schema 全部在此定义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════════════════
# 标准版本
# ══════════════════════════════════════════════════════════

SPECSTD_VERSION = "1.0"


# ══════════════════════════════════════════════════════════
# §2.1 目录结构常量（强制）
# ══════════════════════════════════════════════════════════

# 必备顶级目录/文件
DIR_SPECS = "specs"          # 基线——「系统当前长什么样」
DIR_CHANGES = "changes"      # 进行中的 delta（可选，无迭代时为空目录）
DIR_ARCHIVE = "archive"      # 归档只读冻结（必备，初始可为空）
FILE_AGENTS_MD = "AGENTS.md"  # 规则层：Project Overview + 术语 token 清单 + Always/Never

# specs/{module}/{feature}/ 下必备文件
FILE_SPEC_MD = "spec.md"     # 11 章契约；FR 锚点 ### FR-<id>:
FILE_API_YAML = "api.yaml"   # OpenAPI 3.0.3 完整契约

# changes/<代号>/ 下文件
FILE_PROPOSAL_MD = "proposal.md"           # 为什么做 + 做什么 + 影响范围
FILE_DELTA_SPEC_MD = "delta-spec.md"       # 三段式
FILE_API_DELTA_YAML = "api-delta.yaml"     # OpenAPI 3.0.3 delta
FILE_MANIFEST = "delta.manifest.yaml"      # 机器清单

# 必备顶级目录列表
REQUIRED_TOP_DIRS = [DIR_SPECS, DIR_CHANGES, DIR_ARCHIVE]
REQUIRED_TOP_FILES = [FILE_AGENTS_MD]

# changes/<代号>/ 下 delta 必备文件
DELTA_REQUIRED_FILES = [FILE_PROPOSAL_MD, FILE_DELTA_SPEC_MD, FILE_MANIFEST]
DELTA_OPTIONAL_FILES = [FILE_API_DELTA_YAML]


# ══════════════════════════════════════════════════════════
# 锚点正则
# ══════════════════════════════════════════════════════════

# FR 锚点标题：### FR-001: 或 ### FR-SEC-001:（支持字母数字下划线 ID）
# FR ID 结构：基线 `FR-{序号}`（模块内唯一）；delta 新增 `FR-{功能}-{迭代}-{流水号}`
# （如 FR-person-profile-0817-001，全局唯一、永久保留）——正则以宽匹配兼容两种格式
FR_HEADING_RE = re.compile(r"^###\s+(FR-[\w-]+)\s*[:：]\s*(.*)$", re.MULTILINE)

# ── FR-{功能}-{迭代}-{流水} 结构化解析（双右锚，方案 A 终版）──
# 解析规则（全部锚点在右侧，功能名彻底自由）：
#   流水 = 恒为最右段 \d{3}；迭代 = 恒为右起第二段（单段，禁 '-'）；
#   功能 = 剩余前缀整体左取——功能名任意含 '-'、同前缀子模块（person-search /
#   person-search-v2）共存零歧义，功能名内数字段（eval-360）不误判为迭代。
# 迭代代号白名单：字母/数字/下划线开头，后续可含 '.'（S24/v2.5/2026Q3 合法），
# 禁 '-'——迭代代号含 '-' 时功能段会吸进迭代碎片，字符串层面不可判，
# 故由 delta 目录创建入口与 conformance STRUCT 双点强制。
ITER_CODE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.]*$")

# delta FR 编号命名分组解析（仅匹配 delta 新格式；基线 FR-001 不匹配）
FR_DELTA_ID_RE = re.compile(
    r"^FR-(?P<func>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<iter>[A-Za-z0-9_.]+)-(?P<seq>\d{3})$"
)


def parse_fr_delta_id(fr_id: str, known_features: Optional[set[str]] = None) -> Optional[dict[str, str]]:
    """解析 delta FR 编号为 {func, iter, seq}；非法形态返回 None。

    无 known_features 时为形态级 best-effort 解析（迭代含 '-' 的编号会被
    形态合法地误切——防线在 ITER_CODE_RE 对 delta 目录代号的强制）；
    提供 known_features（功能名注册表）时功能段必须命中，否则返回 None，
    可结构性拦截 'FR-eval-360-2026-08-17-001' 这类迭代含 '-' 的编号。
    """
    m = FR_DELTA_ID_RE.match(fr_id)
    if not m:
        return None
    if known_features is not None and m.group("func") not in known_features:
        return None
    return {"func": m.group("func"), "iter": m.group("iter"), "seq": m.group("seq")}

# FR 列表定义：- **FR-001**：描述（K-020：真实工作区 spec 的合法写法——
# tdm specs/system-settings/tag-library/spec.md 等用列表加粗而非三级标题；
# 仅匹配「行首列表项 + 加粗 FR + 冒号」的定义格式，正文内联引用 **FR-001** 不算锚点）
FR_LIST_RE = re.compile(r"^\s*[-*]\s+\*\*(FR-[\w-]+)\*\*\s*[:：]\s*(.*)$", re.MULTILINE)

# FR 内联引用：**FR-001**（在文本中引用其他 FR）
FR_INLINE_RE = re.compile(r"\*\*(FR-[\w-]+)\*\*")

# AC 锚点：AC-001（在 spec.md 正文中标记验收标准）
AC_RE = re.compile(r"\bAC-\d+\b")

# delta 标记：[delta:代号]（标记 delta-spec.md 中的变更条目）
DELTA_MARKER_RE = re.compile(r"\[delta:([\w-]+)\]")

# task 引用：→ task:TSK-001（delta → task 正向引用）
TASK_REF_RE = re.compile(r"→\s*task:\s*([\w-]+)")

# task 反向引用：← delta:代号（task.md 中的反向引用）
TASK_BACK_REF_RE = re.compile(r"←\s*delta:([\w-]+)")


# ══════════════════════════════════════════════════════════
# Delta 三段式（delta-spec.md 结构）
# ══════════════════════════════════════════════════════════

SECTION_ADDED = "ADDED Requirements"
SECTION_MODIFIED = "MODIFIED Requirements"
SECTION_REMOVED = "REMOVED Requirements"

DELTA_SECTIONS = [SECTION_ADDED, SECTION_MODIFIED, SECTION_REMOVED]

# 三段式标题正则（## ADDED / ## MODIFIED / ## REMOVED）
DELTA_SECTION_RE = re.compile(
    r"^##\s+(" + "|".join(re.escape(s) for s in DELTA_SECTIONS) + r")\s*$",
    re.MULTILINE,
)


# ══════════════════════════════════════════════════════════
# 操作类型（manifest operations）
# ══════════════════════════════════════════════════════════

OP_ADD = "add"
OP_MODIFY = "modify"
OP_REMOVE = "remove"

VALID_OPERATIONS = [OP_ADD, OP_MODIFY, OP_REMOVE]


# ══════════════════════════════════════════════════════════
# §2.2 合规校验规则定义
# ══════════════════════════════════════════════════════════

class RuleName(str, Enum):
    """合规校验规则名称（§2.2）。"""
    STRUCT = "STRUCT"          # 必备目录/文件存在；changes/ 下每个 delta 含 manifest
    AGENTS = "AGENTS"          # AGENTS.md 含 Project Overview 与术语 token 清单节
    ANCHOR = "ANCHOR"         # FR 锚点匹配 ^### FR-\d+: 且全局唯一；covers 可解析
    MANIFEST = "MANIFEST"     # manifest operations 与 delta-spec.md 三段式解析结果逐条一致
    MODIFY_FULL = "MODIFY_FULL"  # MODIFIED 条目含 原/新/原因 三要素且「新」为全量描述
    TRACE = "TRACE"           # delta 的 →task 与 task.md 的 ←delta 双向锁定集合相等
    API_LINT = "API_LINT"    # api.yaml / api-delta.yaml 可被 OpenAPI 3.0.3 解析


class RuleLevel(str, Enum):
    """规则级别。ERROR 拒绝接入，WARN 仅告警。"""
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


# 规则定义表：规则名 → (描述, 默认级别)
RULE_DEFS: dict[str, tuple[str, str]] = {
    RuleName.STRUCT.value: (
        "必备目录/文件存在；changes/ 下每个 delta 含 manifest",
        RuleLevel.ERROR.value,
    ),
    RuleName.AGENTS.value: (
        "AGENTS.md 含 Project Overview 与术语 token 清单节",
        RuleLevel.ERROR.value,
    ),
    RuleName.ANCHOR.value: (
        "所有 spec.md 的 FR 锚点匹配 ^### FR-\\d+: 且全局唯一；covers 可解析",
        RuleLevel.ERROR.value,
    ),
    RuleName.MANIFEST.value: (
        "manifest operations 与 delta-spec.md 三段式解析结果逐条一致（手册 V6）",
        RuleLevel.ERROR.value,
    ),
    RuleName.MODIFY_FULL.value: (
        "MODIFIED 条目含 原/新/原因 三要素且「新」为全量描述（手册 V2）",
        RuleLevel.ERROR.value,
    ),
    RuleName.TRACE.value: (
        "delta 的 →task 与 task.md 的 ←delta 双向锁定集合相等（手册 V3）",
        RuleLevel.WARN.value,
    ),
    RuleName.API_LINT.value: (
        "api.yaml / api-delta.yaml 可被 OpenAPI 3.0.3 解析",
        RuleLevel.ERROR.value,
    ),
}


# ══════════════════════════════════════════════════════════
# Manifest Schema（delta.manifest.yaml 的结构定义）
# ══════════════════════════════════════════════════════════

MANIFEST_SCHEMA: dict = {
    "required_fields": ["delta", "baseline", "operations"],
    "optional_fields": ["baseline_sha", "description"],
    "operations_schema": {
        "required_fields": ["op", "fr", "section"],
        "optional_fields": ["reason", "original", "new", "task"],
        "op_values": VALID_OPERATIONS,
        "section_values": DELTA_SECTIONS,
    },
}


# ══════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════

@dataclass
class Finding:
    """单条校验发现。"""
    rule: str               # RuleName 枚举值
    level: str              # RuleLevel 枚举值
    message: str            # 人类可读的描述
    path: str = ""          # 相关文件路径（相对工作区根）
    detail: dict = field(default_factory=dict)  # 附加详情（如 FR ID、operation 等）

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "level": self.level,
            "message": self.message,
            "path": self.path,
            "detail": self.detail,
        }


@dataclass
class ConformanceReport:
    """合规校验报告。verdict=PASS 时无 ERROR findings。"""
    verdict: str                    # PASS / REJECT
    workspace: str                  # 工作区名称
    findings: list[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.summary:
            n_err = sum(1 for f in self.findings if f.level == RuleLevel.ERROR.value)
            n_warn = sum(1 for f in self.findings if f.level == RuleLevel.WARN.value)
            n_info = sum(1 for f in self.findings if f.level == RuleLevel.INFO.value)
            self.summary = {"error": n_err, "warn": n_warn, "info": n_info}
            if not self.findings:
                self.verdict = "PASS"
            elif n_err > 0:
                self.verdict = "REJECT"
            else:
                self.verdict = "PASS"

    def add(self, rule: str, level: str, message: str, path: str = "", **detail):
        """添加一条 finding。"""
        self.findings.append(Finding(rule=rule, level=level, message=message,
                                     path=path, detail=detail))
        # 重算 summary 和 verdict
        self.__post_init__()

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "workspace": self.workspace,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
        }


@dataclass
class AnchorInfo:
    """FR/AC 锚点信息。"""
    fr_id: str                    # FR-001
    file_path: str                # 所属 spec.md 路径
    module: str = ""              # 模块名（specs/{module}/...）
    feature: str = ""             # 功能名（specs/{module}/{feature}/...）
    title: str = ""               # 锚点标题文本
    ac_ids: list[str] = field(default_factory=list)  # 关联的 AC 列表
    covers_set: set[str] = field(default_factory=set)  # 引用此 FR 的场景 covers


@dataclass
class DeltaOperation:
    """delta manifest 中的单条操作。"""
    op: str            # add / modify / remove
    fr: str            # FR-001
    section: str       # ADDED / MODIFIED / REMOVED Requirements
    reason: str = ""   # 变更原因
    original: str = "" # 原描述（modify/remove 用）
    new: str = ""      # 新全量描述（add/modify 用）
    task: str = ""     # 关联 task ID


@dataclass
class ParsedDeltaSpec:
    """delta-spec.md 的解析结果。"""
    delta_code: str
    sections: dict[str, list[dict]] = field(default_factory=dict)
    # sections 形如 {"ADDED Requirements": [{"fr": "FR-001", "title": "...", "task": "TSK-001"}], ...}

    def all_frs(self) -> set[str]:
        """提取全部 FR ID。"""
        frs = set()
        for items in self.sections.values():
            for item in items:
                if "fr" in item:
                    frs.add(item["fr"])
        return frs

    def all_task_refs(self) -> set[str]:
        """提取全部 →task 引用。"""
        tasks = set()
        for items in self.sections.values():
            for item in items:
                if "task" in item and item["task"]:
                    tasks.add(item["task"])
        return tasks
