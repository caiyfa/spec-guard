"""execution_index — 全量执行索引（场景 × 执行 × 结果绑定台账）。

每次执行完成后，把 run.json 中全部场景（不过滤 verdict）追加到
`{reports_root}/executions/index.jsonl`——「场景 × 任务号 × 全量结果（含 PASS）
× 断言摘要 × 执行上下文变量 saved_vars」可查询台账，供 Agent list_executions
工具与工作台 API 查询。

设计约束（对称 failure_index）：
- 只追加不修改（jsonl append），并发安全由 runner 单实例串行保证
- 文件仍是真相源；写文件后顺带投影到 SQLite（ledger_store）
- 读路径纯读零副作用；台账不可用时降级读文件
"""

import json
from pathlib import Path

EXECUTIONS_INDEX_REL = Path("executions") / "index.jsonl"


def append_executions(reports_root: Path, run_id: str) -> int:
    """从 {reports_root}/{run_id}/run.json + cases/*.json 提取全部场景条目追加索引。

    返回追加条数；run.json 不存在（如 engine_modes 离线自测）返回 0。
    幂等：同一 run_id 重复调用不产生重复条目。
    写文件后同步落库（投影层，失败不影响主流程）。
    """
    reports_root = Path(reports_root)
    run_json = reports_root / run_id / "run.json"
    if not run_json.is_file():
        return 0
    try:
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return 0

    index_path = reports_root / EXECUTIONS_INDEX_REL
    # 幂等检查：索引中已有该 run_id 的条目则跳过
    if index_path.is_file():
        try:
            if f'"run_id": "{run_id}"' in index_path.read_text(encoding="utf-8"):
                return 0
        except Exception:
            pass

    entries = []
    for case in run_data.get("cases", []):
        sid = case.get("id", "")
        if not sid:
            continue
        # 断言摘要与 saved_vars 在 cases/{id}.json（file 字段自带 cases/ 前缀）
        detail = {}
        case_file = case.get("file") or ""
        case_path = None
        if case_file:
            case_path = reports_root / run_id / case_file
            if not case_path.is_file():
                case_path = reports_root / run_id / "cases" / Path(case_file).name
        if case_path and case_path.is_file():
            try:
                detail = json.loads(case_path.read_text(encoding="utf-8"))
            except Exception:
                detail = {}
        failure = detail.get("failure") or {}
        assertions = detail.get("assertions") or []
        entries.append({
            "run_id": run_id,
            "scenario_id": sid,
            "verdict": case.get("verdict", ""),
            "title": case.get("title", ""),
            "env": run_data.get("env", ""),
            "finished_at": run_data.get("finished_at", ""),
            "duration_ms": case.get("duration_ms", 0) or 0,
            "covers": case.get("covers") or [],
            "category": str(failure.get("category", "")),
            "message": str(failure.get("message", ""))[:500],
            "assertion_summary": {
                "passed": sum(1 for a in assertions if a.get("passed")),
                "total": len(assertions),
            },
            "saved_vars": detail.get("saved_vars") or {},
        })

    if not entries:
        return 0
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    # 投影到 SQLite 台账（失败不影响文件主流程）
    try:
        from sg_core import ledger_store
        ledger_store.upsert_run_from_json(reports_root, run_id)
    except Exception:
        pass
    return len(entries)


def query_executions(reports_root: Path, scenario_id: str = "", run_id: str = "",
                     verdict: str = "", limit: int = 10) -> list[dict]:
    """查询执行索引（按时间倒序，可按场景/任务号/结果过滤）。纯读。

    优先查 SQLite 台账；台账不可用时回退读 index.jsonl 文件——保证降级可用。
    """
    reports_root = Path(reports_root)
    try:
        from sg_core import ledger_store
        rows = ledger_store.query_executions_db(reports_root, scenario_id, run_id,
                                                verdict, limit)
        if rows:
            return rows
    except Exception:
        pass
    return _query_from_file(reports_root, scenario_id, run_id, verdict, limit)


def _query_from_file(reports_root: Path, scenario_id: str = "", run_id: str = "",
                     verdict: str = "", limit: int = 10) -> list[dict]:
    """原文件读法（台账不可用时的降级路径）。"""
    index_path = Path(reports_root) / EXECUTIONS_INDEX_REL
    if not index_path.is_file():
        return []
    entries = []
    try:
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if scenario_id and e.get("scenario_id") != scenario_id:
                continue
            if run_id and e.get("run_id") != run_id:
                continue
            if verdict and e.get("verdict") != verdict:
                continue
            entries.append(e)
    except Exception:
        return []
    entries.reverse()  # 最新在前
    return entries[:limit]
