"""failure_index — 失败执行索引（K-052，入仓库持久化）。

每次执行完成后，把 run.json 中 FAIL/BLOCKED/ERROR 的场景追加到
`{reports_root}/failures/index.jsonl`——形成「场景 × 任务号 × 失败原因」的
可查询台账，供 Agent 对话排障（list_failures/read_run_log 工具）与人工追溯。

设计约束：
- 只追加不修改（jsonl append），并发安全由 runner 单实例串行保证
- 失败索引是运行产物（.specguard/ 目录 git 已忽略），但持久落盘不丢
- 读路径纯读零副作用
"""

import json
from pathlib import Path

FAILURE_VERDICTS = ("FAIL", "ERROR", "BLOCKED")
INDEX_REL = Path("failures") / "index.jsonl"


def append_failures(reports_root: Path, run_id: str) -> int:
    """从 {reports_root}/{run_id}/run.json + cases/*.json 提取失败条目追加索引。

    返回追加条数；run.json 不存在（如 engine_modes 离线自测）时返回 0。
    幂等：同一 run_id 重复调用不产生重复条目。
    """
    reports_root = Path(reports_root)
    run_json = reports_root / run_id / "run.json"
    if not run_json.is_file():
        return 0
    try:
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return 0

    index_path = reports_root / INDEX_REL
    # 幂等检查：索引中已有该 run_id 的条目则跳过
    if index_path.is_file():
        try:
            if f'"run_id": "{run_id}"' in index_path.read_text(encoding="utf-8"):
                return 0
        except Exception:
            pass

    entries = []
    for case in run_data.get("cases", []):
        if case.get("verdict") not in FAILURE_VERDICTS:
            continue
        sid = case.get("id", "")
        message = ""
        category = ""
        # failure 详情在 cases/{id}[_upstream].json 里（run.json 的 file 字段自带 cases/ 前缀）
        case_file = case.get("file") or ""
        case_path = None
        if case_file:
            case_path = reports_root / run_id / case_file
            if not case_path.is_file():
                case_path = reports_root / run_id / "cases" / Path(case_file).name
        if case_path and case_path.is_file():
            try:
                detail = json.loads(case_path.read_text(encoding="utf-8"))
                failure = detail.get("failure") or {}
                message = str(failure.get("message", ""))[:500]
                category = str(failure.get("category", ""))
            except Exception:
                pass
        entries.append({
            "run_id": run_id,
            "scenario_id": sid,
            "verdict": case.get("verdict"),
            "category": category,
            "message": message,
            "env": run_data.get("env", ""),
            "finished_at": run_data.get("finished_at", ""),
            "log": f"reports/{run_id}/output.log",
        })

    if not entries:
        return 0
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return len(entries)


def query_failures(reports_root: Path, scenario_id: str = "", limit: int = 10) -> list[dict]:
    """查询失败索引（按时间倒序，可按场景过滤）。纯读。"""
    index_path = Path(reports_root) / INDEX_REL
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
            entries.append(e)
    except Exception:
        return []
    entries.reverse()  # 最新在前
    return entries[:limit]
