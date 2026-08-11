"""delta/manifest.py — delta.manifest.yaml 读写（机器清单，合并单一真相）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class ManifestOperation:
    """delta 单条操作记录。"""
    op: str                     # ADDED / MODIFIED / REMOVED
    anchor: str                 # FR-006 等锚点
    version_mark: str = ""      # [V1.1 MODIFIED] / [delta:代号 ADDED]
    requires_full_block: bool = False  # MODIFIED 必须含原/新/原因三要素
    decisions: list[str] = field(default_factory=list)
    spq_refs: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class DeltaManifest:
    """delta.manifest.yaml 完整模型。"""
    delta: str                      # grid-rule-perf
    specstd_version: str = "1.0"
    source_interview: str = ""      # IV-xxx
    base_spec: str = ""             # specs/.../spec.md
    base_spec_sha: str = ""
    operations: list[dict] = field(default_factory=list)
    freeze: dict = field(default_factory=lambda: {
        "gates": {"product_confirm": "pass", "conformance": "pass", "p0_zero": "pass"},
        "frozen_at": None,
    })


def load_manifest(path) -> Optional[DeltaManifest]:
    """加载 delta.manifest.yaml。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return DeltaManifest(
            delta=raw.get("delta", ""),
            specstd_version=raw.get("specstd_version", "1.0"),
            source_interview=raw.get("source_interview", ""),
            base_spec=raw.get("base_spec", ""),
            base_spec_sha=raw.get("base_spec_sha", ""),
            operations=raw.get("operations", []),
            freeze=raw.get("freeze", {}),
        )
    except Exception:
        return None


def write_manifest(path, manifest: DeltaManifest):
    """写入 delta.manifest.yaml。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "delta": manifest.delta,
        "specstd_version": manifest.specstd_version,
        "source_interview": manifest.source_interview,
        "base_spec": manifest.base_spec,
        "base_spec_sha": manifest.base_spec_sha,
        "operations": manifest.operations,
        "freeze": manifest.freeze,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def collect_operation_frs(operations: list[dict]) -> set[str]:
    """从 operations 中收集全部 FR 锚点引用。"""
    frs: set[str] = set()
    for op in operations:
        anchor = op.get("anchor", "")
        if anchor:
            frs.add(anchor)
    return frs


def validate_manifest(manifest: DeltaManifest) -> list[str]:
    """manifest 结构性校验，返回错误消息列表。"""
    errors: list[str] = []
    if not manifest.delta:
        errors.append("delta 代号不能为空")
    if not manifest.source_interview:
        errors.append("缺少 source_interview（必须挂 IV-xxx）")
    if not manifest.base_spec:
        errors.append("缺少 base_spec 路径")
    for i, op in enumerate(manifest.operations or []):
        if op.get("op") not in ("ADDED", "MODIFIED", "REMOVED"):
            errors.append(f"operations[{i}]: 非法操作类型 {op.get('op')!r}")
        if not op.get("anchor"):
            errors.append(f"operations[{i}]: 缺少 anchor")
        if op.get("op") == "MODIFIED" and not op.get("reason"):
            errors.append(f"operations[{i}]: MODIFIED 必须含 reason（三要素）")
    return errors