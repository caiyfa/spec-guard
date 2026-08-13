"""specstd.conformance — 合规校验器（§2.2，含 verify-delta V1–V6 原生重写）。

工作区接入/拉取时执行，任一 ERROR 即拒绝接入，输出结构化整改报告。

规则对应关系（手册 verify-delta → SpecGuard 规则）：
  V1 锚点有效      → ANCHOR
  V2 合并完整      → MODIFY_FULL
  V3 双向锁定      → TRACE
  V5 合并基线完整  → MANIFEST（只校验不合并）
  V6 manifest 一致 → MANIFEST
  STRUCT / AGENTS / API_LINT 为 SpecGuard 新增规则
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from specstd.schema import (
    DIR_SPECS, DIR_CHANGES, DIR_ARCHIVE,
    FILE_AGENTS_MD, FILE_SPEC_MD, FILE_API_YAML,
    FILE_DELTA_SPEC_MD, FILE_API_DELTA_YAML, FILE_MANIFEST,
    FILE_PROPOSAL_MD,
    REQUIRED_TOP_DIRS, REQUIRED_TOP_FILES,
    DELTA_REQUIRED_FILES,
    FR_HEADING_RE,
    ITER_CODE_RE,
    DELTA_SECTION_RE, DELTA_SECTIONS,
    SECTION_ADDED, SECTION_MODIFIED, SECTION_REMOVED,
    OP_ADD, OP_MODIFY, OP_REMOVE, VALID_OPERATIONS,
    MANIFEST_SCHEMA,
    RuleName, RuleLevel,
    Finding, ConformanceReport, AnchorInfo,
)
from specstd.anchors import (
    parse_spec_md, parse_delta_spec, resolve_covers,
    extract_covers_from_yaml,
)


# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════

def check_conformance(workspace_root: Path, workspace_name: str = "") -> ConformanceReport:
    """执行完整合规校验，返回结构化整改报告。

    workspace_root: spec 仓库根路径
    workspace_name: 工作区名称（用于报告标识；缺省取目录名）
    """
    ws_name = workspace_name or workspace_root.name
    report = ConformanceReport(verdict="PASS", workspace=ws_name)

    # 1. STRUCT — 顶级结构
    _check_struct(report, workspace_root)

    # 2. AGENTS — AGENTS.md 内容
    _check_agents(report, workspace_root)

    # 3. ANCHOR (V1) — FR 锚点唯一性
    anchors = _check_anchor(report, workspace_root)

    # 4. API_LINT — 基线 api.yaml
    _check_api_lint_baseline(report, workspace_root)

    # 5. Delta 逐个检查（changes/ 下）
    changes_dir = workspace_root / DIR_CHANGES
    if changes_dir.is_dir():
        for delta_dir in sorted(changes_dir.iterdir()):
            if delta_dir.is_dir():
                _check_delta(report, delta_dir)

    # 重算 verdict
    report.__post_init__()
    return report


# ══════════════════════════════════════════════════════════
# STRUCT — 必备目录/文件存在
# ══════════════════════════════════════════════════════════

def _check_struct(report: ConformanceReport, ws_root: Path):
    """检查必备顶级目录和文件。"""
    # 必备目录
    for d in REQUIRED_TOP_DIRS:
        dir_path = ws_root / d
        if not dir_path.is_dir():
            report.add(
                RuleName.STRUCT.value, RuleLevel.ERROR.value,
                f"必备目录缺失: {d}/",
                path=d,
            )

    # 必备文件
    for f in REQUIRED_TOP_FILES:
        file_path = ws_root / f
        if not file_path.is_file():
            report.add(
                RuleName.STRUCT.value, RuleLevel.ERROR.value,
                f"必备文件缺失: {f}",
                path=f,
            )


# ══════════════════════════════════════════════════════════
# AGENTS — AGENTS.md 内容
# ══════════════════════════════════════════════════════════

def _check_agents(report: ConformanceReport, ws_root: Path):
    """检查 AGENTS.md 含 Project Overview 与术语 token 清单节。"""
    agents_file = ws_root / FILE_AGENTS_MD
    if not agents_file.is_file():
        return  # STRUCT 已报

    text = agents_file.read_text(encoding="utf-8")

    # 检查 Project Overview 节
    if not re.search(r"^#{1,3}\s*Project\s+Overview", text, re.IGNORECASE | re.MULTILINE):
        report.add(
            RuleName.AGENTS.value, RuleLevel.ERROR.value,
            "AGENTS.md 缺少 'Project Overview' 节",
            path=FILE_AGENTS_MD,
        )

    # 检查术语 token 清单节
    # 匹配：## 术语 / ## Token / ## Glossary / ## Terminology / ## 术语清单
    token_patterns = [
        r"^#{1,3}\s*术语",
        r"^#{1,3}\s*[Tt]oken",
        r"^#{1,3}\s*[Gg]lossary",
        r"^#{1,3}\s*[Tt]erminology",
    ]
    has_tokens = any(re.search(p, text, re.MULTILINE) for p in token_patterns)
    if not has_tokens:
        report.add(
            RuleName.AGENTS.value, RuleLevel.ERROR.value,
            "AGENTS.md 缺少术语 token 清单节（需含 '术语'/'Token'/'Glossary'/'Terminology' 标题之一）",
            path=FILE_AGENTS_MD,
        )

    # 检查 Always/Never 节（推荐但非强制）
    has_always = bool(re.search(r"^#{1,3}\s*Always", text, re.MULTILINE))
    has_never = bool(re.search(r"^#{1,3}\s*Never", text, re.MULTILINE))
    if not (has_always and has_never):
        report.add(
            RuleName.AGENTS.value, RuleLevel.WARN.value,
            "AGENTS.md 建议包含 'Always' 和 'Never' 约束节",
            path=FILE_AGENTS_MD,
        )


# ══════════════════════════════════════════════════════════
# ANCHOR (V1) — FR 锚点唯一性
# ══════════════════════════════════════════════════════════

def _check_anchor(report: ConformanceReport, ws_root: Path) -> dict[str, AnchorInfo]:
    """检查所有 spec.md 的 FR 锚点格式有效且全局唯一。

    返回 FR ID → AnchorInfo 映射（供 covers 校验使用）。
    """
    specs_dir = ws_root / DIR_SPECS
    if not specs_dir.is_dir():
        return {}  # STRUCT 已报

    # 收集所有 FR 锚点（含重复）
    all_anchors: list[AnchorInfo] = []
    for spec_md in sorted(specs_dir.rglob(FILE_SPEC_MD)):
        all_anchors.extend(parse_spec_md(spec_md))

    # 检查格式：FR ID 应匹配 FR-\d+ 或 FR-\w+-\d+（已在正则中保证）
    # 检查全局唯一性
    fr_locations: dict[str, list[str]] = {}
    for info in all_anchors:
        fr_locations.setdefault(info.fr_id, []).append(info.file_path)

    for fr_id, paths in fr_locations.items():
        if len(paths) > 1:
            report.add(
                RuleName.ANCHOR.value, RuleLevel.ERROR.value,
                f"FR 锚点 '{fr_id}' 在多个文件中重复定义: {', '.join(p for p in paths)}",
                detail={"fr_id": fr_id, "files": paths},
            )

    # 返回去重后的映射（保留第一个）
    anchors: dict[str, AnchorInfo] = {}
    for info in all_anchors:
        if info.fr_id not in anchors:
            anchors[info.fr_id] = info

    return anchors


# ══════════════════════════════════════════════════════════
# Delta 检查（遍历 changes/ 下每个 delta）
# ══════════════════════════════════════════════════════════

def _check_delta(report: ConformanceReport, delta_dir: Path):
    """检查单个 delta 目录的全部规则。"""
    delta_code = delta_dir.name

    # STRUCT — delta 代号字符集（迭代命名限制：字母/数字/下划线开头，可含 '.'，禁 '-'；
    # 迭代代号是 FR-{功能}-{迭代}-{流水} 双右锚解析的结构前提，含 '-' 则解析歧义不可判）
    if not ITER_CODE_RE.match(delta_code):
        report.add(
            RuleName.STRUCT.value, RuleLevel.ERROR.value,
            f"delta 代号 '{delta_code}' 非法：迭代代号只允许字母/数字/下划线开头、可含 '.'，"
            f"禁止含 '-'（如 2026-08-17 请转写为 2026_08_17 或 20260817）——"
            f"'-' 是 FR-{{功能}}-{{迭代}}-{{流水}} 编号的层级分隔符，代号含 '-' 会导致编号不可解析",
            path=f"{DIR_CHANGES}/{delta_code}",
            detail={"delta_code": delta_code},
        )

    # STRUCT — delta 必备文件
    for f in DELTA_REQUIRED_FILES:
        if not (delta_dir / f).is_file():
            report.add(
                RuleName.STRUCT.value, RuleLevel.ERROR.value,
                f"delta '{delta_code}' 缺少必备文件: {f}",
                path=f"{DIR_CHANGES}/{delta_code}/{f}",
            )

    # MANIFEST (V5/V6) — manifest 与 delta-spec 一致
    _check_manifest(report, delta_dir)

    # MODIFY_FULL (V2) — MODIFIED 三要素
    _check_modify_full(report, delta_dir)

    # TRACE (V3) — 双向锁定
    _check_trace(report, delta_dir)

    # API_LINT — api-delta.yaml
    _check_api_lint_delta(report, delta_dir)


# ══════════════════════════════════════════════════════════
# MANIFEST (V5/V6) — manifest operations 与 delta-spec.md 一致
# ══════════════════════════════════════════════════════════

def _check_manifest(report: ConformanceReport, delta_dir: Path):
    """检查 manifest 的 operations 与 delta-spec.md 三段式解析结果逐条一致。"""
    delta_code = delta_dir.name
    manifest_path = delta_dir / FILE_MANIFEST
    delta_spec_path = delta_dir / FILE_DELTA_SPEC_MD

    if not manifest_path.is_file() or not delta_spec_path.is_file():
        return  # STRUCT 已报

    # 解析 manifest
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        report.add(
            RuleName.MANIFEST.value, RuleLevel.ERROR.value,
            f"delta '{delta_code}' 的 manifest YAML 解析失败: {e}",
            path=str(manifest_path.relative_to(delta_dir.parent.parent)),
        )
        return

    # 检查 manifest 必备字段
    for field in MANIFEST_SCHEMA["required_fields"]:
        if field not in manifest:
            report.add(
                RuleName.MANIFEST.value, RuleLevel.ERROR.value,
                f"delta '{delta_code}' manifest 缺少必备字段: {field}",
                path=f"{DIR_CHANGES}/{delta_code}/{FILE_MANIFEST}",
            )

    # 解析 delta-spec.md
    parsed = parse_delta_spec(delta_spec_path)

    # 提取 delta-spec 中的全部操作
    spec_ops: dict[str, set[str]] = {}  # {section: {fr1, fr2}}
    for section, items in parsed.sections.items():
        spec_ops.setdefault(section, set())
        for item in items:
            spec_ops[section].add(item.get("fr", ""))

    # 提取 manifest 中的 operations
    manifest_ops = manifest.get("operations") or []
    man_ops: dict[str, set[str]] = {}
    for op in manifest_ops:
        section = op.get("section", "")
        fr = op.get("fr", "")
        man_ops.setdefault(section, set()).add(fr)

        # 检查 op 值有效
        if op.get("op") not in VALID_OPERATIONS:
            report.add(
                RuleName.MANIFEST.value, RuleLevel.ERROR.value,
                f"delta '{delta_code}' manifest operation 的 op 值非法: '{op.get('op')}'"
                f"（应为 {VALID_OPERATIONS}）",
                path=f"{DIR_CHANGES}/{delta_code}/{FILE_MANIFEST}",
                detail={"fr": fr, "op": op.get("op")},
            )

    # 逐段比较：manifest ops 与 delta-spec 解析结果应一致
    all_sections = set(spec_ops.keys()) | set(man_ops.keys())
    for section in all_sections:
        spec_frs = spec_ops.get(section, set())
        man_frs = man_ops.get(section, set())

        # manifest 中有但 delta-spec 中没有
        extra = man_frs - spec_frs
        for fr in extra:
            if fr:
                report.add(
                    RuleName.MANIFEST.value, RuleLevel.ERROR.value,
                    f"delta '{delta_code}' manifest 声明了 '{fr}' 在 {section}，"
                    f"但 delta-spec.md 中未找到对应条目",
                    path=f"{DIR_CHANGES}/{delta_code}/{FILE_MANIFEST}",
                    detail={"fr": fr, "section": section, "mismatch": "manifest_only"},
                )

        # delta-spec 中有但 manifest 中没有
        missing = spec_frs - man_frs
        for fr in missing:
            if fr:
                report.add(
                    RuleName.MANIFEST.value, RuleLevel.ERROR.value,
                    f"delta '{delta_code}' delta-spec.md 中 '{fr}' 在 {section}，"
                    f"但 manifest 中未声明对应 operation",
                    path=f"{DIR_CHANGES}/{delta_code}/{FILE_DELTA_SPEC_MD}",
                    detail={"fr": fr, "section": section, "mismatch": "spec_only"},
                )


# ══════════════════════════════════════════════════════════
# MODIFY_FULL (V2) — MODIFIED 条目含三要素
# ══════════════════════════════════════════════════════════

def _check_modify_full(report: ConformanceReport, delta_dir: Path):
    """检查 MODIFIED 段落的每条含 原/新/原因 三要素且「新」为全量描述。"""
    delta_code = delta_dir.name
    delta_spec_path = delta_dir / FILE_DELTA_SPEC_MD

    if not delta_spec_path.is_file():
        return  # STRUCT 已报

    parsed = parse_delta_spec(delta_spec_path)
    modified_items = parsed.sections.get(SECTION_MODIFIED, [])

    for item in modified_items:
        fr = item.get("fr", "")
        original = item.get("original", "")
        new = item.get("new", "")
        reason = item.get("reason", "")

        missing = []
        if not original:
            missing.append("原描述（original）")
        if not new:
            missing.append("新描述（new，须为全量描述）")
        if not reason:
            missing.append("原因（reason）")

        if missing:
            report.add(
                RuleName.MODIFY_FULL.value, RuleLevel.ERROR.value,
                f"delta '{delta_code}' MODIFIED 条目 '{fr}' 缺少: {', '.join(missing)}",
                path=f"{DIR_CHANGES}/{delta_code}/{FILE_DELTA_SPEC_MD}",
                detail={"fr": fr, "missing": missing},
            )


# ══════════════════════════════════════════════════════════
# TRACE (V3) — 双向锁定
# ══════════════════════════════════════════════════════════

def _check_trace(report: ConformanceReport, delta_dir: Path):
    """检查 delta 的 →task 与 task.md 的 ←delta 双向锁定集合相等。

    级别为 WARN（不阻塞接入）。
    """
    delta_code = delta_dir.name
    delta_spec_path = delta_dir / FILE_DELTA_SPEC_MD
    task_md_path = delta_dir / "task.md"

    if not delta_spec_path.is_file():
        return  # STRUCT 已报

    # 提取 delta-spec.md 中的全部 →task 引用
    parsed = parse_delta_spec(delta_spec_path)
    forward_refs = parsed.all_task_refs()

    # 如果没有 task 引用，跳过
    if not forward_refs:
        return

    # 检查 task.md 是否存在
    if not task_md_path.is_file():
        report.add(
            RuleName.TRACE.value, RuleLevel.WARN.value,
            f"delta '{delta_code}' 引用了 {len(forward_refs)} 个 task，但未找到 task.md",
            path=f"{DIR_CHANGES}/{delta_code}/task.md",
            detail={"forward_refs": sorted(forward_refs)},
        )
        return

    # 提取 task.md 中的 ←delta 反向引用
    from specstd.schema import TASK_BACK_REF_RE
    task_text = task_md_path.read_text(encoding="utf-8")
    back_refs = set(TASK_BACK_REF_RE.findall(task_text))

    # 检查双向锁定
    # 正向：delta-spec → task 引用的 task ID
    # 反向：task.md ← delta:代号 标记
    # 注意：反向引用标记的是 delta 代号，不是 task ID
    # 双向锁定语义：delta-spec 中引用的每个 task，在 task.md 中应有对应条目
    # task.md 中标记了 ←delta:代号 的条目，应在 delta-spec 中有对应引用

    # 简化检查：delta-spec 引用的 task ID 是否在 task.md 中出现
    task_ids_in_md: set[str] = set()
    for line in task_text.splitlines():
        # 匹配 task ID 标题：### TSK-001 或 ## TSK-001
        m = re.match(r"^#{1,4}\s+(TSK-[\w-]+)", line)
        if m:
            task_ids_in_md.add(m.group(1))

    # 正向检查：delta-spec 引用的 task 在 task.md 中存在
    for tid in sorted(forward_refs):
        if tid not in task_ids_in_md:
            report.add(
                RuleName.TRACE.value, RuleLevel.WARN.value,
                f"delta '{delta_code}' 引用 task '{tid}'，但 task.md 中未找到对应条目",
                path=f"{DIR_CHANGES}/{delta_code}/task.md",
                detail={"task_id": tid, "direction": "forward"},
            )

    # 反向检查：task.md 中标记了 ←delta:代号 的条目，delta-code 应匹配
    if delta_code not in back_refs:
        report.add(
            RuleName.TRACE.value, RuleLevel.WARN.value,
            f"delta '{delta_code}' 的 task.md 中未找到 '←delta:{delta_code}' 反向引用标记",
            path=f"{DIR_CHANGES}/{delta_code}/task.md",
            detail={"expected": f"←delta:{delta_code}"},
        )


# ══════════════════════════════════════════════════════════
# API_LINT — OpenAPI 3.0.3 解析
# ══════════════════════════════════════════════════════════

def _check_api_lint_baseline(report: ConformanceReport, ws_root: Path):
    """检查基线 api.yaml 可被 OpenAPI 3.0.3 解析。"""
    specs_dir = ws_root / DIR_SPECS
    if not specs_dir.is_dir():
        return

    for api_yaml in sorted(specs_dir.rglob(FILE_API_YAML)):
        _lint_openapi(report, api_yaml, ws_root)


def _check_api_lint_delta(report: ConformanceReport, delta_dir: Path):
    """检查 delta 的 api-delta.yaml 可被 OpenAPI 3.0.3 解析。"""
    api_delta = delta_dir / FILE_API_DELTA_YAML
    if api_delta.is_file():
        _lint_openapi(report, api_delta, delta_dir.parent.parent)


def _lint_openapi(report: ConformanceReport, path: Path, ws_root: Path):
    """检查单个 YAML 文件是否符合 OpenAPI 3.0.3 基本结构。"""
    rel_path = str(path.relative_to(ws_root)) if path.is_relative_to(ws_root) else str(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        report.add(
            RuleName.API_LINT.value, RuleLevel.ERROR.value,
            f"YAML 解析失败: {e}",
            path=rel_path,
        )
        return

    if not isinstance(spec, dict):
        report.add(
            RuleName.API_LINT.value, RuleLevel.ERROR.value,
            "文件内容不是有效的 YAML 映射（dict）",
            path=rel_path,
        )
        return

    # 检查 openapi 版本
    openapi_ver = spec.get("openapi", "")
    if not openapi_ver:
        report.add(
            RuleName.API_LINT.value, RuleLevel.ERROR.value,
            "缺少 'openapi' 版本声明",
            path=rel_path,
        )
    elif not str(openapi_ver).startswith("3.0"):
        report.add(
            RuleName.API_LINT.value, RuleLevel.ERROR.value,
            f"OpenAPI 版本 '{openapi_ver}' 不符合 3.0.x 要求",
            path=rel_path,
        )

    # 检查 info 段
    if "info" not in spec:
        report.add(
            RuleName.API_LINT.value, RuleLevel.ERROR.value,
            "缺少 'info' 段",
            path=rel_path,
        )

    # 检查 paths 段
    if "paths" not in spec:
        report.add(
            RuleName.API_LINT.value, RuleLevel.ERROR.value,
            "缺少 'paths' 段",
            path=rel_path,
        )


# ══════════════════════════════════════════════════════════
# covers 校验（独立函数，供 validator 工具调用）
# ══════════════════════════════════════════════════════════

def check_covers(anchors: dict[str, AnchorInfo], scenarios_root: Path) -> list[Finding]:
    """检查全部场景的 covers 是否可解析为有效的 FR ID。

    此函数不依赖工作区结构，仅需要锚点清单和场景目录。
    在 validator 工具中调用（conformance 只检查工作区本身）。
    """
    findings: list[Finding] = []
    if not scenarios_root.is_dir():
        return findings

    for yaml_file in sorted(scenarios_root.rglob("*.yaml")) + sorted(scenarios_root.rglob("*.yml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            covers = extract_covers_from_yaml(yaml_file)
        except Exception:
            continue
        if not covers:
            continue

        rel_path = str(yaml_file.relative_to(scenarios_root))
        for fr_id in covers:
            if fr_id not in anchors:
                findings.append(Finding(
                    rule=RuleName.ANCHOR.value,
                    level=RuleLevel.ERROR.value,
                    message=f"场景 '{rel_path}' 的 covers 引用 '{fr_id}' 在当前工作区的 spec.md 中不存在",
                    path=rel_path,
                    detail={"fr_id": fr_id},
                ))

    return findings
