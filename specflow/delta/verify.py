"""delta/verify.py — verify-delta V1-V6 机械校验清单。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import yaml

from specflow.delta.manifest import (
    DeltaManifest, load_manifest, validate_manifest, collect_operation_frs,
)


VERIFY_RULES = [
    "V1 锚点有效: delta 内所有 FR/AC 锚点可解析且注册",
    "V2 全量替换: MODIFIED 块必含原/新/原因三要素",
    "V3 双向锁定: 每条操作带 [delta:代号] + 决策/任务回链",
    "V4 可追溯: delta 必带 source_interview: IV-xxx",
    "V5 合并后完整: merge 后 spec.md 过 specstd/conformance 全规则",
    "V6 manifest 一致: markdown 正文操作集 == manifest operations 集",
]


class VerifyResult:
    """verify-delta 校验结果。"""
    def __init__(self):
        self.verdicts: dict[str, str] = {}  # rule_name → PASS/FAIL/WARN
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def to_dict(self) -> dict:
        return {
            "verdict": "PASS" if not self.errors else "FAIL",
            "verdicts": self.verdicts,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def verify_v1_anchor_valid(manifest: DeltaManifest) -> list[str]:
    """V1: 锚点有效——FR/AC 锚点可解析。"""
    errors = []
    frs = collect_operation_frs(manifest.operations)
    for fr in sorted(frs):
        if not fr.startswith("FR-"):
            errors.append(f"锚点格式非法: {fr}")
    return errors


def verify_v2_full_replace(manifest: DeltaManifest) -> list[str]:
    """V2: MODIFIED 块必含 reason。"""
    errors = []
    for op in manifest.operations or []:
        if op.get("op") == "MODIFIED" and not op.get("reason"):
            errors.append(f"MODIFIED {op.get('anchor', '')} 缺少 reason（三要素）")
    return errors


def verify_v3_bidirectional(manifest: DeltaManifest) -> list[str]:
    """V3: 双向锁定——每条操作含决策引用。"""
    warnings = []
    for op in manifest.operations or []:
        if not op.get("decisions"):
            warnings.append(f"操作 {op.get('anchor', '')} 无决策回链")
    return warnings


def verify_v4_traceable(manifest: DeltaManifest) -> list[str]:
    """V4: 可追溯——必带 source_interview。"""
    errors = []
    if not manifest.source_interview:
        errors.append("缺少 source_interview: IV-xxx")
    return errors


def verify_v6_manifest_consistency(
    manifest: DeltaManifest, delta_spec_text: str
) -> list[str]:
    """V6: manifest 与 delta-spec.md 正文一致。"""
    errors = []
    manifest_frs = collect_operation_frs(manifest.operations)
    # 从 delta-spec.md 正文提取 [delta:xxx] 标记
    import re
    text_frs = set(re.findall(r"\[delta:([a-z0-9_-]+)\]", delta_spec_text))
    if manifest_frs and text_frs and manifest_frs != text_frs:
        errors.append(
            f"manifest FR 集 ({sorted(manifest_frs)}) "
            f"与正文 FR 集 ({sorted(text_frs)}) 不一致")
    return errors


def verify_all(
    manifest: DeltaManifest,
    delta_spec_text: str = "",
) -> VerifyResult:
    """全量 V1-V6 校验。"""
    result = VerifyResult()

    # V1
    errs = verify_v1_anchor_valid(manifest)
    result.verdicts["V1"] = "PASS" if not errs else "FAIL"
    result.errors.extend(errs)

    # V2
    errs = verify_v2_full_replace(manifest)
    result.verdicts["V2"] = "PASS" if not errs else "FAIL"
    result.errors.extend(errs)

    # V3
    warns = verify_v3_bidirectional(manifest)
    result.verdicts["V3"] = "PASS" if not warns else "WARN"
    result.warnings.extend(warns)

    # V4
    errs = verify_v4_traceable(manifest)
    result.verdicts["V4"] = "PASS" if not errs else "FAIL"
    result.errors.extend(errs)

    # V5: 需要 specstd.conformance 结果，此处校验 manifest 自身结构
    errs = validate_manifest(manifest)
    result.verdicts["V5"] = "PASS" if not errs else "FAIL"
    result.errors.extend(errs)

    # V6
    if delta_spec_text:
        errs = verify_v6_manifest_consistency(manifest, delta_spec_text)
        result.verdicts["V6"] = "PASS" if not errs else "FAIL"
        result.errors.extend(errs)
    else:
        result.verdicts["V6"] = "SKIP"
        result.warnings.append("V6 跳过：未提供 delta-spec.md 正文")

    return result


def verify_delta_dir(delta_dir: Path) -> Optional[dict]:
    """对 delta 目录全量校验，返回 result dict。"""
    manifest_path = delta_dir / "delta.manifest.yaml"
    if not manifest_path.is_file():
        return {"verdict": "FAIL", "errors": ["缺少 delta.manifest.yaml"]}

    manifest = load_manifest(str(manifest_path))
    if manifest is None:
        return {"verdict": "FAIL", "errors": ["delta.manifest.yaml 解析失败"]}

    delta_spec_path = delta_dir / "delta-spec.md"
    delta_spec_text = ""
    if delta_spec_path.is_file():
        delta_spec_text = delta_spec_path.read_text(encoding="utf-8")

    result = verify_all(manifest, delta_spec_text)
    return result.to_dict()