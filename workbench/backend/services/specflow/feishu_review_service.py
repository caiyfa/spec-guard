"""feishu_review_service.py — 关联复核服务与提升闸门（飞书知识图谱一期 T5）。

人拍板唯一闸门：LLM 候选边经复核队列（私有区）→ 确认/拒绝 → 共享区事实源。
- 确认：material_links.yaml（confirmed）+ 材料/话题提升共享区 → 图谱派生源
- 拒绝：material_links.yaml（status=rejected，工作区级防重复建议；builder 过滤不进图谱）
- invalid（evidence 校验失败）条目展示但不可确认

复核队列：.specflow/{emp}/feishu_pool/_review_queue.json（覆盖式 JSON，
量小随用户，一期不建表）。队列按 emp 目录天然隔离——只能复核本人材料。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from specflow.feishu_pool import facts, pool_store
from specflow.feishu_pool.paths import pool_dirs, shared_dirs

_QUEUE_NAME = "_review_queue.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _queue_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / _QUEUE_NAME


def _load_queue(specflow_emp_base: Path) -> list[dict]:
    path = _queue_path(specflow_emp_base)
    if not path.is_file():
        return []
    try:
        return [dict(i) for i in json.loads(path.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _save_queue(specflow_emp_base: Path, items: list[dict]):
    path = _queue_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def list_queue(specflow_emp_base: Path) -> list[dict]:
    """复核队列（当前用户私有区；含 pending/confirmed/rejected 全态）。"""
    return _load_queue(specflow_emp_base)


def enqueue_suggestions(specflow_emp_base: Path, suggested_by: str,
                        suggestions: list[dict]) -> int:
    """候选边入队（去重：同 (src,dst) 已有 pending/confirmed 记录则跳过）。

    Returns:
        实际入队条数
    """
    items = _load_queue(specflow_emp_base)
    existing = {(i.get("src"), i.get("dst")) for i in items
                if i.get("status") in ("pending", "confirmed")}
    added = 0
    for s in suggestions:
        key = (s.get("src"), s.get("dst"))
        if key in existing:
            continue
        items.append({
            "src": s.get("src"), "dst": s.get("dst"),
            "confidence": s.get("confidence", 0),
            "evidence": s.get("evidence", ""),
            "valid": bool(s.get("valid", True)),
            "status": "pending",
            "suggested_by": suggested_by,
            "suggested_at": _now(),
        })
        existing.add(key)
        added += 1
    _save_queue(specflow_emp_base, items)
    return added


def _find_pending(items: list[dict], src: str, dst: str) -> dict | None:
    for i in items:
        if i.get("src") == src and i.get("dst") == dst \
                and i.get("status") == "pending":
            return i
    return None


def _promote_material(specflow_emp_base: Path, workspace_root: Path,
                      src: str) -> None:
    """材料/话题提升共享区（fd/fm 复制快照副本；tp 写 topics.yaml）。"""
    pool = pool_dirs(specflow_emp_base)
    shared = shared_dirs(workspace_root)
    if src.startswith("fd:") or src.startswith("fm:"):
        prefix, token = src.split(":", 1)
        sub = "docs" if prefix == "fd" else "minutes"
        ext = "md" if prefix == "fd" else "json"
        stem = f"{prefix}-{token}"
        src_file = pool[sub] / f"{stem}.{ext}"
        if src_file.is_file():
            shared["materials"].mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, shared["materials"] / f"{stem}.{ext}")
    elif src.startswith("tp:"):
        cand = pool["root"] / "_candidate_topics.yaml"
        if cand.is_file():
            import yaml
            topics = (yaml.safe_load(cand.read_text(encoding="utf-8"))
                      or {}).get("topics") or []
            for t in topics:
                if t.get("id") == src:
                    facts.upsert_topic(workspace_root, t)
                    break


def confirm_suggestions(specflow_emp_base: Path, workspace_root: Path,
                        emp_no: str, pairs: list[tuple]) -> dict:
    """批量确认：写共享区事实源 + 提升材料 + 队列置 confirmed。

    invalid 条目跳过（skipped 计数），不落事实源。
    """
    items = _load_queue(specflow_emp_base)
    confirmed = skipped = 0
    for src, dst in pairs:
        item = _find_pending(items, src, dst)
        if item is None or not item.get("valid", True):
            skipped += 1
            continue
        facts.append_link(workspace_root, src=src, dst=dst, edge="mentions",
                          confidence=item.get("confidence", 0),
                          evidence=item.get("evidence", ""),
                          confirmed_by=emp_no, status="confirmed")
        _promote_material(specflow_emp_base, workspace_root, src)
        item["status"] = "confirmed"
        item["confirmed_at"] = _now()
        confirmed += 1
    _save_queue(specflow_emp_base, items)
    return {"confirmed": confirmed, "skipped": skipped}


def reject_suggestions(specflow_emp_base: Path, workspace_root: Path,
                       emp_no: str, pairs: list[tuple]) -> dict:
    """批量拒绝：共享区 rejected 留痕（防重复建议）+ 队列置 rejected。"""
    items = _load_queue(specflow_emp_base)
    rejected = skipped = 0
    for src, dst in pairs:
        item = _find_pending(items, src, dst)
        if item is None:
            skipped += 1
            continue
        facts.append_link(workspace_root, src=src, dst=dst, edge="mentions",
                          confidence=item.get("confidence", 0),
                          evidence=item.get("evidence", ""),
                          confirmed_by=emp_no, status="rejected")
        item["status"] = "rejected"
        item["confirmed_at"] = _now()
        rejected += 1
    _save_queue(specflow_emp_base, items)
    return {"rejected": rejected, "skipped": skipped}
