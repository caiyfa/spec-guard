"""质量中心扫描服务（2026-08-14 基线可视化）。

五个「秒级」质量工具的 on-demand 扫描 + 内存缓存（v1 不落库、不自动扫、不接 coverage）。
计划文档：docs/upgrade-plans/2026-08-14-质量基线可视化页实施计划.md

铁律（AGENTS.md Never + 计划 §3 约束）：
- 扫描纯读——禁止任何 --fix / 写回仓库
- jscpd 报告写系统临时目录，读完即删，绝不落仓库
- 工具退出码非 0 属正常（发现问题），以「输出可解析」判成败，不按 returncode

基线数字硬编码自 docs/质量基线/README.md「首批基线 2026-08-14」摘要表，
仅用于页面清偿进度对比；刷新基线报告时同步更新此处并注明日期。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # .../specguard
FRONTEND = ROOT / "workbench" / "frontend"
SCAN_TIMEOUT_SEC = 60                                # 计划 §4.2：单工具超时上限
MAX_ISSUES = 1000                                    # 单工具明细行上限（防大 payload）
MAX_BY_FILE = 200                                    # 按文件聚合返回上限
MAX_BY_RULE = 60                                     # 规则分布返回上限

# 首批基线（2026-08-14，docs/质量基线/README.md 摘要表）
BASELINE: dict[str, dict] = {
    # oxlint-baseline.txt：60 文件 8 errors（correctness，优先清）+ 3100 warnings
    "oxlint": {"total": 3108, "errors": 8, "warnings": 3100, "files": 60},
    # ruff-baseline.txt / ruff-statistics.txt：1331 项；F401 175 + F841 28 是真 bug 信号
    "ruff": {"total": 1331, "f401": 175, "f841": 28},
    # knip-baseline.txt：1 死文件 + 2 幽灵依赖 + 14 未用导出 + 25 未用类型
    "knip": {"total": 42, "files": 1, "dependencies": 2, "exports": 14, "types": 25},
    # jscpd-baseline.txt：36 处克隆，总重复率 0.97%；YAML 13.93%（5 处）是主要热点
    "jscpd": {"total": 36, "percentage": 0.97, "yaml_percentage": 13.93},
    # vulture-baseline.txt：8 行（min-confidence 80）
    "vulture": {"total": 8},
}

TOOL_LABELS: dict[str, str] = {
    "oxlint": "Oxlint · 前端 Lint",
    "ruff": "Ruff · Python Lint",
    "knip": "Knip · 前端死代码",
    "jscpd": "JSCPD · 全仓查重",
    "vulture": "Vulture · Python 死代码",
}

TOOL_IDS: tuple[str, ...] = ("oxlint", "ruff", "knip", "jscpd", "vulture")


class QualityScanError(Exception):
    """扫描配置/环境类失败（命令缺失、输出不可解析等）。"""


# ── 基础设施 ─────────────────────────────────────────────────────────────


def _exec(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """执行子进程（utf-8 解码，超时 SCAN_TIMEOUT_SEC）。

    argv[0] 为绝对路径直接用；否则 shutil.which 解析（Windows 下 npx/npm 是
    .cmd，which 返回全路径后 CreateProcess 可直接执行）。
    """
    head = argv[0]
    if Path(head).is_absolute() and Path(head).exists():
        exe = head
    else:
        exe = shutil.which(head)
        if not exe:
            raise QualityScanError(f"命令不可用: {head}（请确认已在部署环境安装并在 PATH 中）")
    proc = subprocess.run(
        [exe, *argv[1:]], cwd=str(cwd), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=SCAN_TIMEOUT_SEC,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _norm(path: str) -> str:
    """路径归一：反斜杠转正斜杠（Windows 展示一致性）。"""
    return (path or "").replace("\\", "/")


def _rel_root(path: str) -> str:
    """扫描输出路径转仓库相对（相对路径按扫描 cwd=ROOT 解析，不能用进程 cwd）。"""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except Exception:
        return _norm(str(p))


def _rel_front(path: str) -> str:
    """oxlint/knip 的 frontend 相对路径补全为仓库相对。"""
    p = _norm(path)
    if p.startswith("workbench/"):
        return p
    return f"workbench/frontend/{p}"


def _clip(counter: Counter, limit: int) -> list[dict]:
    return [{"code": k, "count": v} for k, v in counter.most_common(limit)]


def _file_table(stats: dict[str, dict]) -> list[dict]:
    rows = sorted(stats.values(), key=lambda r: (-r["count"], r["file"]))
    return rows[:MAX_BY_FILE]


def _empty_core() -> dict:
    return {"summary": {}, "by_rule": [], "by_file": [], "issues": []}


# ── oxlint ───────────────────────────────────────────────────────────────
# cwd=workbench/frontend；JSON 形状（实测 2026-08-15，oxlint 1.76）：
#   {diagnostics: [{message, code, severity(error|warning), filename,
#                   labels: [{span: {line, column, ...}}]}], number_of_files, ...}


def _parse_oxlint(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise QualityScanError(f"oxlint 输出不可解析: {e}")
    diags = data.get("diagnostics") or []
    issues: list[dict] = []
    by_rule: Counter = Counter()
    stats: dict[str, dict] = {}
    for d in diags:
        labels = d.get("labels") or []
        span = (labels[0].get("span") or {}) if labels else {}
        fname = _rel_front(d.get("filename") or "")
        sev = d.get("severity") or "warning"
        code = d.get("code") or "unknown"
        issues.append({
            "file": fname, "line": span.get("line"), "column": span.get("column"),
            "rule": code, "severity": sev, "message": d.get("message") or "",
        })
        by_rule[code] += 1
        st = stats.setdefault(fname, {"file": fname, "count": 0, "errors": 0})
        st["count"] += 1
        if sev == "error":
            st["errors"] += 1
    errors = sum(1 for d in diags if d.get("severity") == "error")
    return {
        "summary": {
            "total": len(diags), "errors": errors, "warnings": len(diags) - errors,
            "files": data.get("number_of_files") or len(stats),
        },
        "by_rule": _clip(by_rule, MAX_BY_RULE),
        "by_file": _file_table(stats),
        "issues": issues[:MAX_ISSUES],
        "issues_truncated": len(issues) > MAX_ISSUES,
    }


def _scan_oxlint() -> dict:
    code, out, err = _exec(
        ["npx", "oxlint", "-c", ".oxlintrc.json", "--format", "json", "src"], FRONTEND)
    if not out.strip():
        raise QualityScanError(f"oxlint 无输出（exit={code}）: {err[:300]}")
    return _parse_oxlint(out)


# ── ruff ─────────────────────────────────────────────────────────────────
# cwd=仓库根；JSON 形状（实测 2026-08-15，ruff 0.16.3）：
#   [{code, filename(绝对), location: {row, column}, message, fix?, severity, url, ...}]
# 展示严重度派生：F 类（PyFlakes 真 bug 信号，基线判读优先）= error，其余 warning。


def _parse_ruff(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise QualityScanError(f"ruff 输出不可解析: {e}")
    issues: list[dict] = []
    by_rule: Counter = Counter()
    stats: dict[str, dict] = {}
    fixable = 0
    f_class = 0
    for d in data:
        code = d.get("code") or "?"
        fname = _rel_root(d.get("filename") or "")
        loc = d.get("location") or {}
        sev = "error" if code.startswith("F") else "warning"
        if d.get("fix"):
            fixable += 1
        if code.startswith("F"):
            f_class += 1
        issues.append({
            "file": fname, "line": loc.get("row"), "column": loc.get("column"),
            "rule": code, "severity": sev, "message": d.get("message") or "",
        })
        by_rule[code] += 1
        st = stats.setdefault(fname, {"file": fname, "count": 0, "errors": 0})
        st["count"] += 1
        if sev == "error":
            st["errors"] += 1
    return {
        "summary": {"total": len(data), "fixable": fixable, "fClass": f_class,
                    "files": len(stats)},
        "by_rule": _clip(by_rule, MAX_BY_RULE),
        "by_file": _file_table(stats),
        "issues": issues[:MAX_ISSUES],
        "issues_truncated": len(issues) > MAX_ISSUES,
    }


def _scan_ruff() -> dict:
    code, out, err = _exec(["ruff", "check", "--output-format", "json"], ROOT)
    if not out.strip():
        # 0 问题时 ruff 输出 []，空串说明命令本身失败
        raise QualityScanError(f"ruff 无输出（exit={code}）: {err[:300]}")
    return _parse_ruff(out)


# ── knip ─────────────────────────────────────────────────────────────────
# cwd=workbench/frontend；JSON 形状（实测 2026-08-15，knip 6.16）：
#   {issues: [{file, dependencies: [{name, line, col}], devDependencies,
#              exports: [{name, line, col}], types, files: [{name}],
#              unlisted, unresolved, duplicates, ...}]}

_KNIP_CATEGORIES: list[tuple[str, str]] = [
    ("files", "未用文件"),
    ("dependencies", "幽灵依赖"),
    ("devDependencies", "幽灵 devDep"),
    ("exports", "未用导出"),
    ("types", "未用类型"),
    ("unlisted", "未声明依赖"),
    ("unresolved", "未解析导入"),
    ("duplicates", "重复导出"),
]


def _parse_knip(stdout: str) -> dict:
    # knip 的 json reporter 把 JSON 打到 stdout，但可能夹带警告行——截取首个 { 到末个 }
    text = stdout.strip()
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        raise QualityScanError("knip 输出无 JSON 体")
    try:
        data = json.loads(text[lo:hi + 1])
    except json.JSONDecodeError as e:
        raise QualityScanError(f"knip 输出不可解析: {e}")
    issues: list[dict] = []
    by_rule: Counter = Counter()
    stats: dict[str, dict] = {}
    summary: dict[str, int] = {}
    for entry in data.get("issues") or []:
        fname = _rel_front(entry.get("file") or "")
        for cat, kind in _KNIP_CATEGORIES:
            items = entry.get(cat) or []
            if not items:
                continue
            by_rule[kind] += len(items)
            summary[cat] = summary.get(cat, 0) + len(items)
            st = stats.setdefault(fname, {"file": fname, "count": 0, "errors": 0})
            st["count"] += len(items)
            for it in items:
                name = it.get("name") or it.get("file") or "?"
                line = it.get("line") or (it.get("pos") and None) or None
                issues.append({
                    "file": fname, "line": line, "column": it.get("col"),
                    "rule": kind, "severity": "warning", "message": f"{kind}: {name}",
                })
    summary["total"] = sum(v for k, v in summary.items())
    return {
        "summary": summary,
        "by_rule": _clip(by_rule, MAX_BY_RULE),
        "by_file": _file_table(stats),
        "issues": issues[:MAX_ISSUES],
        "issues_truncated": len(issues) > MAX_ISSUES,
    }


def _scan_knip() -> dict:
    code, out, err = _exec(["npx", "knip", "--reporter", "json"], FRONTEND)
    if not out.strip():
        raise QualityScanError(f"knip 无输出（exit={code}）: {err[:300]}")
    return _parse_knip(out)


# ── jscpd ────────────────────────────────────────────────────────────────
# cwd=仓库根，路径参数与根 package.json dup:scan 完全一致（保证与基线可比）；
# 报告写临时目录（AGENTS.md Never：产物不落仓库）。JSON 形状（实测 2026-08-15）：
#   {duplicates: [{firstFile: {name, start, end}, secondFile: {...}, format,
#                  lines, tokens, fragment(大块文本，丢弃)}],
#    statistics: {total: {...}, formats: {yaml: {total: {clones, percentage, ...}}}}}
# name 形如 "scenarios/x.yaml:yaml"，取末冒号前为文件名。


def _parse_jscpd(data: dict) -> dict:
    dups = data.get("duplicates") or []
    stats_src = ((data.get("statistics") or {}).get("formats") or {})
    issues: list[dict] = []
    by_rule: Counter = Counter()
    stats: dict[str, dict] = {}
    for d in dups:
        fmt = d.get("format") or "?"
        a = ((d.get("firstFile") or {}).get("name") or "").rsplit(":", 1)[0]
        b = ((d.get("secondFile") or {}).get("name") or "").rsplit(":", 1)[0]
        lines = d.get("lines") or 0
        tokens = d.get("tokens") or 0
        sev = "error" if fmt == "yaml" else "warning"   # 基线判读：YAML 是主要热点
        issues.append({
            "file": _norm(a), "fileB": _norm(b),
            "line": (d.get("firstFile") or {}).get("start"),
            "rule": fmt, "severity": sev,
            "message": f"{lines} 行重复（{tokens} tokens）: {a} ↔ {b}",
        })
        by_rule[fmt] += 1
        for f in (a, b):
            fn = _norm(f)
            st = stats.setdefault(fn, {"file": fn, "count": 0, "errors": 0})
            st["count"] += 1
            if sev == "error":
                st["errors"] += 1
    formats: dict[str, dict] = {}
    for fmt, body in stats_src.items():
        total = (body or {}).get("total") or {}
        if total.get("clones"):
            formats[fmt] = {
                "clones": total.get("clones", 0),
                "percentage": total.get("percentage", 0),
            }
    grand = ((data.get("statistics") or {}).get("total") or {})
    return {
        "summary": {
            "total": len(dups),
            "percentage": grand.get("percentage", 0),
            "duplicatedLines": grand.get("duplicatedLines", 0),
            "formats": dict(sorted(formats.items(), key=lambda kv: -kv[1]["clones"])),
        },
        "by_rule": _clip(by_rule, MAX_BY_RULE),
        "by_file": _file_table(stats),
        "issues": issues[:MAX_ISSUES],
        "issues_truncated": len(issues) > MAX_ISSUES,
    }


def _scan_jscpd() -> dict:
    # 产物目录用运行产物区（.gitignore 已覆盖 workbench/backend/data/，与
    # workbench.db 同待遇）而非系统临时区：Windows 下系统临时区存在句柄/杀软
    # 瞬时占用导致的非确定性 EACCES（实测 node 子进程写入会被间歇拒绝），
    # 运行产物区是后端确定性可写路径；读完即清，清理失败也无碍（gitignored）。
    import shutil as _shutil

    tmp = ROOT / "workbench" / "backend" / "data" / "quality-jscpd"
    _shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        argv = [
            "npx", "jscpd", "--reporters", "json", "--output", str(tmp),
            "scenarios", "engine", "specstd", "agent", "mcp_server",
            "workbench/backend", "workbench/frontend/src",
        ]
        code, out, err = _exec(argv, ROOT)
        report = tmp / "jscpd-report.json"
        if not report.exists():
            raise QualityScanError(f"jscpd 未产报告（exit={code}）: {err[:300]}")
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise QualityScanError(f"jscpd 报告不可解析: {e}")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)
    return _parse_jscpd(data)


# ── vulture ──────────────────────────────────────────────────────────────
# cwd=仓库根；无 JSON，文本行（实测 2026-08-15，exit=3 表示有发现，属正常）：
#   engine\scenario_runner.py:17: unused import 'CAT_UPSTREAM' (90% confidence)


_VULTURE_RE = re.compile(r"^(.+?):(\d+):\s+(.+?)\s+\((\d+)% confidence\)$")


def _parse_vulture(stdout: str) -> dict:
    issues: list[dict] = []
    by_rule: Counter = Counter()
    stats: dict[str, dict] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _VULTURE_RE.match(line)
        if not m:
            continue
        path, lineno, msg, conf = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        fname = _rel_root(path)
        kind = msg.split(" ", 2)[:2]
        kind = " ".join(kind) if len(kind) == 2 else msg   # "unused import" 等
        sev = "error" if conf >= 100 else "warning"
        issues.append({
            "file": fname, "line": lineno, "column": None,
            "rule": f"{kind} ({conf}%)", "severity": sev, "message": msg,
        })
        by_rule[f"{kind} ({conf}%)"] += 1
        st = stats.setdefault(fname, {"file": fname, "count": 0, "errors": 0})
        st["count"] += 1
        if sev == "error":
            st["errors"] += 1
    return {
        "summary": {"total": len(issues), "files": len(stats)},
        "by_rule": _clip(by_rule, MAX_BY_RULE),
        "by_file": _file_table(stats),
        "issues": issues[:MAX_ISSUES],
        "issues_truncated": len(issues) > MAX_ISSUES,
    }


def _scan_vulture() -> dict:
    argv = [sys.executable, "-m", "vulture",
            "engine", "specstd", "agent", "mcp_server", "workbench/backend",
            "--min-confidence", "80"]
    code, out, err = _exec(argv, ROOT)
    # exit=0（无发现，输出空）也正常
    return _parse_vulture(out)


# ── 对外接口 ─────────────────────────────────────────────────────────────

_SCANNERS: dict[str, callable] = {
    "oxlint": _scan_oxlint,
    "ruff": _scan_ruff,
    "knip": _scan_knip,
    "jscpd": _scan_jscpd,
    "vulture": _scan_vulture,
}

_LATEST: dict[str, dict] = {}
_LOCK = threading.Lock()


def run_tool(tool: str) -> dict:
    """执行单工具扫描并更新缓存。扫描失败不抛异常，返回 ok=False 的结果体。"""
    scanner = _SCANNERS.get(tool)
    if scanner is None:
        raise QualityScanError(f"未知工具: {tool}（可选: {'/'.join(TOOL_IDS)}）")
    started = datetime.now()
    t0 = time.monotonic()
    err_text: str | None = None
    core = _empty_core()
    try:
        core = scanner()
    except subprocess.TimeoutExpired:
        err_text = f"扫描超时（>{SCAN_TIMEOUT_SEC}s）"
    except QualityScanError as e:
        err_text = str(e)
    except Exception as e:  # noqa: BLE001 — 扫描失败要反馈到页面而非 500
        err_text = f"扫描失败: {type(e).__name__}: {e}"
    payload = {
        "tool": tool,
        "label": TOOL_LABELS[tool],
        "ok": err_text is None,
        "error": err_text,
        "scanned_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_ms": int((time.monotonic() - t0) * 1000),
        **core,
        "baseline": BASELINE[tool],
    }
    with _LOCK:
        _LATEST[tool] = payload
    return payload


def latest() -> dict:
    """各工具最近一次扫描结果；未扫描的工具返回带基线的空态（页面可先渲染卡片）。"""
    with _LOCK:
        out: dict[str, dict] = {}
        for t in TOOL_IDS:
            out[t] = _LATEST.get(t) or {
                "tool": t, "label": TOOL_LABELS[t], "ok": None, "error": None,
                "scanned_at": None, "duration_ms": None,
                "summary": None, "by_rule": None, "by_file": None,
                "issues": None, "issues_truncated": False,
                "baseline": BASELINE[t],
            }
    return out
