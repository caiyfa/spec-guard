"""attribution — 失败归因工具。

工具：
  read_run_report: 读取运行报告，提取失败场景与断言差异
  db_evidence: DB 证据查询（只读 SELECT）
  list_failures: 失败索引查询（K-052：场景 × 任务号 × 失败原因台账）
  read_run_log: 按任务号读执行日志（K-052：output.log 全量 stdout，含 trace_id）
"""

import json
import re
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

def _get_reports_root() -> Path:
    """获取报告目录（优先工作区 .specguard/reports/，无工作区回退 SG_ROOT/reports/）。"""
    try:
        from specstd.workspace import reports_dir
        return reports_dir()
    except Exception:
        return SG_ROOT / "reports"

# V13 修复：run_id 白名单（时间戳目录名或普通标识符，禁路径分隔符）
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# V12 修复：只读 SQL 的逃逸关键词黑名单（startswith(SELECT) 可被这些绕过）
SQL_DENY_RE = re.compile(
    r"\b(FOR\s+UPDATE|LOCK\s+IN\s+SHARE\s+MODE|INTO\s+(OUT|DUMP)FILE|LOCK\s+TABLES|"
    r"HANDLER|LOAD\s+DATA|LOAD\s+XML|DO\s+SLEEP)\b",
    re.IGNORECASE,
)

TOOLS = [
    Tool(
        name="read_run_report",
        description="读取 SpecGuard 运行报告，提取失败场景、断言差异、环境探测结果。"
                    "用于失败归因分析（循环 B）。",
        inputSchema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "任务号（EX-xxxxxxxx；K-050 之前为时间戳目录名）"},
            },
            "required": ["run_id"],
        }
    ),
    Tool(
        name="db_evidence",
        description="查询 DB 证据（只读 SELECT）。用于失败归因时校对数据库状态。"
                    "SQL 必须为 SELECT/SHOW/DESCRIBE/EXPLAIN。",
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "只读 SQL 查询"},
                "scenario_id": {"type": "string", "description": "关联的场景 ID（可选，用于归因报告）"},
            },
            "required": ["sql"],
        }
    ),
    Tool(
        name="list_failures",
        description="查询失败执行索引（K-052）：返回「场景 × 任务号（EX-xxx）× 失败原因」台账，"
                    "最新在前。可按 scenario_id 过滤查某个单元测试最近在什么任务号执行失败；"
                    "拿到任务号后用 read_run_log 取完整执行日志（含 ifelc-trace_id）、"
                    "用 read_run_report 取断言差异。优化失败场景前必查。",
        inputSchema={
            "type": "object",
            "properties": {
                "scenario_id": {"type": "string",
                                "description": "可选：只看该场景的失败记录"},
                "limit": {"type": "integer", "description": "返回条数（默认 10）"},
            }
        }
    ),
    Tool(
        name="read_run_log",
        description="按任务号（EX-xxx）读取执行日志 output.log（K-050 起全量落盘）："
                    "pytest 完整 stdout，含每次接口调用的 method/path/status 与 ifelc-trace_id。"
                    "tail 控制返回行数（默认 200，从尾部取——失败通常在后段）。",
        inputSchema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "任务号（EX-xxxxxxxx，也兼容时间戳目录）"},
                "tail": {"type": "integer", "description": "尾部行数（默认 200）"},
            },
            "required": ["run_id"],
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "read_run_report":
        return _handle_read_report(arguments)
    elif name == "db_evidence":
        return _handle_db_evidence(arguments)
    elif name == "list_failures":
        return _handle_list_failures(arguments)
    elif name == "read_run_log":
        return _handle_read_run_log(arguments)
    return []


def _handle_list_failures(arguments: dict) -> list[TextContent]:
    """失败索引查询（K-052）：services.failure_index 的 MCP 出口。"""
    from services import failure_index

    scenario_id = str(arguments.get("scenario_id", "") or "")
    limit = int(arguments.get("limit", 10) or 10)
    entries = failure_index.query_failures(_get_reports_root(), scenario_id, limit)
    out = {
        "ok": True,
        "count": len(entries),
        "failures": entries,
        "note": "拿到 run_id 后：read_run_log 看完整执行日志（含 trace_id），"
                "read_run_report 看断言差异与步骤轨迹",
    }
    if not entries:
        out["hint"] = ("索引为空或该场景近期无失败记录；索引由执行控制在每次运行完成后写入 "
                       "failures/index.jsonl（K-052 之后的执行才有）")
    return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]


def _handle_read_run_log(arguments: dict) -> list[TextContent]:
    """按任务号读执行日志（K-052）：output.log 尾部 N 行，RUN_ID_RE + 越界守卫。"""
    run_id = str(arguments.get("run_id", "") or "")
    tail = int(arguments.get("tail", 200) or 200)
    if not run_id:
        return [TextContent(type="text", text="错误：缺少 run_id 参数")]
    if not RUN_ID_RE.match(run_id):
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 非法 run_id: {run_id}")]
    reports_root = _get_reports_root()
    log_path = (reports_root / run_id / "output.log").resolve()
    try:
        log_path.relative_to(reports_root.resolve())
    except ValueError:
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界: {run_id}")]
    if not log_path.is_file():
        return [TextContent(type="text", text=json.dumps({
            "ok": False,
            "error": f"执行日志不存在: {run_id}/output.log",
            "hint": "K-050 之前的运行只有 run.json/report.md（无 stdout 落盘），"
                    "可用 read_run_report 读取",
        }, ensure_ascii=False, indent=2))]
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = max(1, min(tail, 2000))
    body = "\n".join(lines[-tail:])
    return [TextContent(type="text", text=json.dumps({
        "ok": True,
        "run_id": run_id,
        "total_lines": len(lines),
        "returned_lines": min(tail, len(lines)),
        "log": body,
    }, ensure_ascii=False, indent=2))]


def _handle_read_report(arguments: dict) -> list[TextContent]:
    run_id = arguments.get("run_id", "")
    if not run_id:
        return [TextContent(type="text", text="错误：缺少 run_id 参数")]

    # V13 修复：run_id 白名单校验 + 解析结果必须落在 reports/ 之内
    if not RUN_ID_RE.match(run_id):
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 非法 run_id: {run_id}")]
    reports_root = _get_reports_root()
    run_dir = (reports_root / run_id).resolve()
    try:
        run_dir.relative_to(reports_root.resolve())
    except ValueError:
        return [TextContent(type="text", text=f"OUT_OF_SCOPE: 路径越界: {run_id}")]
    if not run_dir.is_dir():
        return [TextContent(type="text", text=f"错误：运行报告不存在: {run_id}")]

    # 读取 run.json
    run_json_path = run_dir / "run.json"
    run_data = {}
    if run_json_path.is_file():
        with open(run_json_path, "r", encoding="utf-8") as f:
            run_data = json.load(f)

    # K-053：触发上下文（trigger.json——选中场景/环境/轻量选项/触发人）
    trigger_path = run_dir / "trigger.json"
    trigger = {}
    if trigger_path.is_file():
        try:
            trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 读取 cases/ 下的单场景详情
    cases_dir = run_dir / "cases"
    failed_cases = []
    all_cases = []
    if cases_dir.is_dir():
        for case_file in sorted(cases_dir.glob("*.json")):
            try:
                with open(case_file, "r", encoding="utf-8") as f:
                    case = json.load(f)
                all_cases.append(case)
                verdict = case.get("verdict", "")
                if verdict in ("FAIL", "ERROR", "BLOCKED"):
                    failed_cases.append({
                        "scenario_id": case.get("scenario_id", ""),
                        "verdict": verdict,
                        "error": case.get("error", ""),
                        "assertions": case.get("assertions", []),
                        "steps": case.get("steps", []),
                    })
            except Exception:
                continue

    # K-053：run.json cases 提供完整场景清单（id+verdict），Agent 无需逐个翻 case 文件
    cases_brief = [
        {"id": c.get("id"), "verdict": c.get("verdict"), "duration_ms": c.get("duration_ms", 0)}
        for c in run_data.get("cases", [])
    ]

    # 读取 report.md（如果存在）
    report_md_path = run_dir / "report.md"
    report_md = ""
    if report_md_path.is_file():
        report_md = report_md_path.read_text(encoding="utf-8")[:2000]

    summary = {
        "run_id": run_id,
        "env": run_data.get("env"),
        "started_at": run_data.get("started_at"),
        "finished_at": run_data.get("finished_at"),
        "stats": run_data.get("stats", {}),
        "trigger": trigger,          # K-053：触发上下文（无 trigger.json 时为空 dict）
        "cases": cases_brief,        # K-053：全部场景清单（id+verdict）
        "total_cases": len(all_cases),
        "failed_cases": failed_cases,
        "report_md_preview": report_md,
    }

    return [TextContent(type="text", text=json.dumps(summary, ensure_ascii=False, indent=2, default=str))]


def _handle_db_evidence(arguments: dict) -> list[TextContent]:
    sql = arguments.get("sql", "").strip()
    scenario_id = arguments.get("scenario_id", "")

    if not sql:
        return [TextContent(type="text", text="错误：缺少 sql 参数")]

    # 只读守卫（V12 修复：补充逃逸关键词黑名单——FOR UPDATE 加锁 / INTO OUTFILE 写文件等）
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith(("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")):
        return [TextContent(type="text", text="错误：仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN")]
    m = SQL_DENY_RE.search(sql)
    if m:
        return [TextContent(type="text", text=f"错误：只读守卫拒绝危险子句: {m.group(1)}")]

    # 尝试使用引擎的 DB 客户端
    try:
        BACKEND_DIR = SG_ROOT / "workbench" / "backend"
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))

        from engine.db_oracle import DBClient
        client = DBClient()
        rows = client.query(sql)
        return [TextContent(type="text", text=json.dumps({
            "sql": sql,
            "scenario_id": scenario_id,
            "row_count": len(rows),
            "rows": rows[:100],
        }, ensure_ascii=False, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "sql": sql,
            "scenario_id": scenario_id,
            "error": f"DB 查询失败（可能未配置 DB 连接）: {e}",
            "hint": "请检查 systems/tdm/config/env.*.yaml 中的 db 段配置",
        }, ensure_ascii=False, indent=2))]
