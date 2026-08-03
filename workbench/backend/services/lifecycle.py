"""lifecycle — 单元测试生命周期聚合（K-xxx）。

以「一条测试」为主线，聚合台账投影层（ledger_store）：
- 草稿状态（drafts：draft/promoted/discarded）
- 库内资产（scenarios：已入库场景）
- 执行史（runs/run_cases：每次执行结果 + 失败详情）

回答三类问题：
1. 这条测试现在什么状态？（草稿待评审 / 已入库 / 更新中 / 已废弃）
2. 最近一次执行结果？失败原因？（last_run / last_failure）
3. 失败→修复闭环了吗？（run 序列 FAIL→PASS 转换次数 + 时间线闭环事件）

状态机（优先级从高到低）：
- drafts 有 status=draft 记录         → 草稿待评审（库内已有 = 更新中；库内无 = 新建中）
- drafts 有 status=promoted 记录      → 已入库（最近一次操作 = 入库）
- drafts 有 status=discarded 记录     → 库内仍有 → 已入库（废弃的是草稿）
- drafts 无记录 且 库内有             → 已入库
- drafts status=discarded 且库内无    → 已废弃
"""

from __future__ import annotations

from pathlib import Path

from services import ledger_store

# 状态 → 前端展示文案
STATUS_LABEL = {
    "draft_pending": "草稿待评审",
    "draft_updating": "更新中（有草稿）",
    "in_library": "已入库",
    "discarded": "已废弃",
}

FAILURE_VERDICTS = ("FAIL", "ERROR", "BLOCKED")


def _latest_draft(drafts: list[dict], scenario_id: str) -> dict | None:
    """该场景最近的草稿台账记录（按更新时间取最新）。"""
    best = None
    for d in drafts:
        if d.get("scenario_id") != scenario_id:
            continue
        if best is None or (d.get("updated_at") or "") > (best.get("updated_at") or ""):
            best = d
    return best


def _status_of(draft: dict | None, in_library: bool) -> str:
    """状态机判定（见模块 docstring）。"""
    if draft is None:
        return "in_library" if in_library else "unknown"
    st = draft.get("status", "")
    if st == "draft":
        return "draft_updating" if in_library else "draft_pending"
    if st == "promoted":
        return "in_library"
    if st == "discarded":
        return "in_library" if in_library else "discarded"
    return "in_library" if in_library else "unknown"


def list_lifecycle(db_path: Path | None = None) -> dict:
    """全部测试的生命周期行（场景主干 + 未入库草稿 + 已废弃草稿）。"""
    scs = ledger_store.query_scenarios(db_path)
    drafts = ledger_store.query_drafts(db_path)
    stats = ledger_store.query_scenario_stats(db_path)

    items: list[dict] = []
    seen: set[str] = set()

    # 主干 1：库内场景
    for sc in scs:
        sid = sc["id"]
        draft = _latest_draft(drafts, sid)
        items.append(_build_item(sid, sc.get("title", ""), sc, draft, stats))
        seen.add(sid)

    # 主干 2/3：未入库草稿（draft/discarded 状态、库内无）
    for d in drafts:
        sid = d.get("scenario_id") or ""
        if not sid or sid in seen:
            continue
        if d.get("status") in ("draft", "discarded"):
            items.append(_build_item(sid, d.get("title", ""), None, d, stats))
            seen.add(sid)

    items.sort(key=lambda it: it["updated_at"] or "", reverse=True)

    now = _now()
    recent_fail = [it for it in items
                   if it.get("last_run_at") and _within_days(it["last_run_at"], 7)
                   and it.get("last_verdict") in FAILURE_VERDICTS]
    summary = {
        "total": len(items),
        "in_library": sum(1 for it in items if it["status"] == "in_library"),
        "draft_pending": sum(1 for it in items if it["status"] == "draft_pending"),
        "draft_updating": sum(1 for it in items if it["status"] == "draft_updating"),
        "discarded": sum(1 for it in items if it["status"] == "discarded"),
        "recent_failed_7d": len(recent_fail),
        "closed_loops": sum(it.get("closed_loops", 0) for it in items),
    }
    return {"summary": summary, "items": items}


def _json_list(raw) -> list:
    """台账里 tags/covers 存 JSON 字符串，统一解析为数组。"""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    try:
        import json
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _build_item(scenario_id: str, title: str, sc: dict | None,
                draft: dict | None, stats: dict) -> dict:
    """组装单条生命周期行。sc=库内场景台账（无则 None），draft=最近草稿记录。"""
    in_library = sc is not None
    st = stats.get(scenario_id) or {}
    draft_updated = (draft or {}).get("updated_at", "")
    sc_updated = (sc or {}).get("updated_at", "")
    # 更新时间 = 场景文件 mtime 与草稿更新时间取最大
    updated = max(draft_updated, sc_updated) if (draft_updated and sc_updated) else (draft_updated or sc_updated)
    return {
        "id": scenario_id,
        "title": title,
        "status": _status_of(draft, in_library),
        "status_label": STATUS_LABEL.get(_status_of(draft, in_library), _status_of(draft, in_library)),
        "draft_status": (draft or {}).get("status", ""),
        "draft_filename": (draft or {}).get("filename", ""),
        "module": (sc or {}).get("module", "") or (draft or {}).get("module", ""),
        "version": (sc or {}).get("version", ""),
        "test_type": (sc or {}).get("test_type", "scenario"),
        "tags": _json_list((sc or {}).get("tags")),
        "covers": _json_list((sc or {}).get("covers")),
        "file_path": (sc or {}).get("file_path", ""),
        "updated_at": updated,
        "run_count": st.get("run_count", 0),
        "fail_count": st.get("fail_count", 0),
        "last_run_id": st.get("last_run_id", ""),
        "last_verdict": st.get("last_verdict", ""),
        "last_run_at": st.get("last_run_at", ""),
        "recent_verdicts": st.get("recent_verdicts", []),
        "closed_loops": st.get("closed_loops", 0),
        "last_failure": st.get("last_failure"),
    }


def scenario_detail(scenario_id: str, db_path: Path | None = None) -> dict:
    """单条测试的完整生命周期：基础信息 + 时间线 + 执行历史。"""
    scs = {s["id"]: s for s in ledger_store.query_scenarios(db_path)}
    drafts = [d for d in ledger_store.query_drafts(db_path)
              if d.get("scenario_id") == scenario_id]
    draft = _latest_draft(drafts, scenario_id)
    sc = scs.get(scenario_id)
    runs = ledger_store.query_scenario_runs(scenario_id, 50, db_path)

    events: list[dict] = []
    # 草稿生命周期事件（草稿更新/入库/废弃——台账只有最新状态点）
    if draft:
        _map = {"draft": ("draft_updated", "草稿更新"),
                "promoted": ("promoted", "入库"),
                "discarded": ("discarded", "废弃")}
        etype, label = _map.get(draft.get("status", ""), ("draft_updated", "草稿更新"))
        events.append({
            "at": draft.get("updated_at", ""), "type": etype, "label": label,
            "detail": f"{draft.get('filename', '')}（工作区 {draft.get('workspace', '-')}）",
        })
    # 执行事件 + 闭环事件（FAIL→PASS 转换，按时间正序推导）
    prev_verdict = ""
    for run in reversed(runs):  # runs 是倒序（最新在前）→ 反转为正序推导
        events.append({
            "at": run.get("finished_at", ""), "type": "run",
            "label": f"执行 {run['run_id']}",
            "verdict": run.get("verdict", ""),
            "detail": f"{run.get('duration_ms', 0)}ms"
                      + (f" · {run.get('category', '')}" if run.get("category") else ""),
            "run_id": run.get("run_id", ""),
        })
        if run.get("verdict") == "PASS" and prev_verdict in FAILURE_VERDICTS:
            events.append({
                "at": run.get("finished_at", ""), "type": "loop_closed",
                "label": "🔄 失败修复闭环",
                "detail": f"{prev_verdict} → PASS（{run['run_id']}）",
                "run_id": run.get("run_id", ""),
            })
        prev_verdict = run.get("verdict", "")

    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    return {
        "id": scenario_id,
        "title": (sc or draft or {}).get("title", ""),
        "module": (sc or {}).get("module", "") or (draft or {}).get("module", ""),
        "version": (sc or {}).get("version", ""),
        "file_path": (sc or {}).get("file_path", ""),
        "status": _status_of(draft, sc is not None),
        "status_label": STATUS_LABEL.get(_status_of(draft, sc is not None), ""),
        "draft_status": (draft or {}).get("status", ""),
        "draft_filename": (draft or {}).get("filename", ""),
        "timeline": events,
        "runs": runs,
    }


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _within_days(iso_at: str, days: int) -> bool:
    """ISO 时间是否在最近 N 天内（解析失败视为 False）。"""
    try:
        from datetime import datetime
        at = datetime.fromisoformat(iso_at.replace("Z", "+00:00"))
        if at.tzinfo:
            at = at.astimezone().replace(tzinfo=None)
        from datetime import timedelta
        return datetime.now() - at <= timedelta(days=days)
    except Exception:
        return False
