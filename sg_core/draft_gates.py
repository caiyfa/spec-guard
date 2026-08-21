"""draft_gates — 草稿三闸状态机（M07 §4.2，T-061）。

闸门语义（与原型一致）：
  ② 格式校验在草稿写入时自动先跑（write_draft 挂钩）→ gate2=pass/fail
  ① 人工评审（人拍板）→ gate1=pending/approved/rejected（gate2 fail 时不可 approved）
  ③ 发布门禁在 promote 时自动跑 → gate3=blocked/pass/fail
  三闸全过前 promote_draft 一律拒绝（铁律 3：每个产出必过闸）。

表 sg_draft_gates（SQLite workbench.db）：
  draft_id / workspace / scenario_id / covers_json / source_delta /
  gate1_status(+reviewer/comment/ts) / gate2_status(+report) /
  gate3_status / promoted_at / created_by / created_at

约束：与 ledger_store 同模式（单 worker、WAL、短事务）；写入失败绝不影响
文件主流程（调用侧 try/except 包裹）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "workbench" / "backend"
DB_PATH = BACKEND_DIR / "data" / "workbench.db"

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sg_draft_gates (
    draft_id       TEXT PRIMARY KEY,
    workspace      TEXT NOT NULL DEFAULT '',
    scenario_id    TEXT NOT NULL DEFAULT '',
    covers_json    TEXT NOT NULL DEFAULT '[]',
    source_delta   TEXT NOT NULL DEFAULT '',
    gate1_status   TEXT NOT NULL DEFAULT 'pending',
    gate1_reviewer TEXT NOT NULL DEFAULT '',
    gate1_comment  TEXT NOT NULL DEFAULT '',
    gate1_ts       TEXT NOT NULL DEFAULT '',
    gate2_status   TEXT NOT NULL DEFAULT 'pending',
    gate2_report   TEXT NOT NULL DEFAULT '',
    gate3_status   TEXT NOT NULL DEFAULT 'blocked',
    gate3_report   TEXT NOT NULL DEFAULT '',
    promoted_at    TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT ''
);
"""

# 合法值（M07 §4.2 状态机）
GATE1_VALID = ("pending", "approved", "rejected")
GATE2_VALID = ("pending", "pass", "fail")
GATE3_VALID = ("blocked", "pass", "fail")


class GateError(Exception):
    """三闸操作失败（code: not_found / invalid_state / missing_reviewer /
    gate2_not_pass / missing_source_delta）。"""

    def __init__(self, code: str, message: str, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def _active_workspace() -> str:
    try:
        from specstd.workspace import get_active_workspace
        info = get_active_workspace()
        if info is None:
            return ""
        name = info.get("name") if isinstance(info, dict) else getattr(info, "name", "")
        return str(name or "")
    except Exception:
        return ""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_tables(db_path: Path | None = None):
    """建表（幂等），应用启动时调用；旧库补 gate3_report 列迁移。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sg_draft_gates)")]
        if "gate3_report" not in cols:
            conn.execute(
                "ALTER TABLE sg_draft_gates "
                "ADD COLUMN gate3_report TEXT NOT NULL DEFAULT ''")


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["covers"] = json.loads(d.pop("covers_json", "[]") or "[]")
    except Exception:
        d["covers"] = []
    if d.get("gate2_report"):
        try:
            d["gate2_report"] = json.loads(d["gate2_report"])
        except Exception:
            pass
    return d


def _find(draft_id: str, db_path: Path | None = None) -> sqlite3.Row | None:
    with _LOCK, _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM sg_draft_gates WHERE draft_id = ?", (draft_id,)
        ).fetchone()


# ══════════════════════════════════════════════════════════
# 第②闸：格式校验（write 时自动跑；与 validator / covers_gate 同一实现）
# ══════════════════════════════════════════════════════════

def run_gate2(draft_id: str, db_path: Path | None = None) -> dict:
    """重跑第②闸：格式 2.0 + covers 锚点存在性 + covers 标签。

    从 drafts/ 读草稿内容（与文件事实源一致）；报告 = validator 结果。
    返回更新后的 gate 行 dict。
    """
    row = _find(draft_id, db_path)
    if row is None:
        raise GateError("not_found", f"草稿三闸记录不存在: {draft_id}")
    ws = row["workspace"] or _active_workspace()

    # 读取草稿内容（drafts/ 文件是真相源；优先当前 context 私有区，
    # 落 created_by 私有区时回退——T-014 emp 维度）
    from specstd.workspace import drafts_dir
    try:
        draft_path = drafts_dir() / draft_id
        if not draft_path.is_file() and row["created_by"]:
            alt = drafts_dir(emp=row["created_by"]) / draft_id
            if alt.is_file():
                draft_path = alt
        content = draft_path.read_text(encoding="utf-8")
    except Exception as e:
        report = {"verdict": "FAIL", "findings": [
            {"level": "ERROR", "rule": "FILE", "message": f"草稿文件不可读: {e}"}]}
        return _update_gate2(draft_id, "fail", report, db_path)

    # 格式校验（validator 权威实现）
    from mcp_server.tools.validator import validate_scenario_content
    try:
        report = validate_scenario_content(content)
    except Exception as e:
        report = {"verdict": "FAIL", "findings": [
            {"level": "ERROR", "rule": "VALIDATE", "message": f"格式校验异常: {e}"}]}

    verdict = "pass" if report.get("verdict") == "PASS" else "fail"
    # 附加锚点核对（covers 标签可解析）
    try:
        import yaml as _yaml
        raw = _yaml.safe_load(content) or {}
        covers = (raw.get("doc") or {}).get("covers") or []
        ws_root = getattr(__import__("specstd.workspace", fromlist=["get_workspace_root"]),
                          "get_workspace_root")()
        if ws_root:
            from specstd.anchors import scan_anchors, resolve_covers
            anchors = scan_anchors(ws_root)
            anchor_findings = resolve_covers([str(c) for c in covers], anchors)
            if anchor_findings:
                verdict = "fail"
                report = dict(report)
                report["verdict"] = "FAIL"  # 与 gate2_status 保持同口径
                report["findings"] = list(report.get("findings") or []) + [
                    f.to_dict() for f in anchor_findings]
    except Exception:
        pass  # 锚点核对失败不阻断（validator 已覆盖主路径）

    return _update_gate2(draft_id, verdict, report, db_path)


def _update_gate2(draft_id: str, verdict: str, report: dict, db_path: Path | None) -> dict:
    assert verdict in GATE2_VALID
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE sg_draft_gates SET gate2_status=?, gate2_report=? WHERE draft_id=?",
            (verdict, json.dumps(report, ensure_ascii=False), draft_id))
    row = _find(draft_id, db_path)
    return _row_to_dict(row)


# ══════════════════════════════════════════════════════════
# 登记 / 查询
# ══════════════════════════════════════════════════════════

def register_draft(draft_id: str, scenario_id: str, covers: list,
                   source_delta: str = "", created_by: str = "",
                   workspace: str = "", db_path: Path | None = None) -> dict:
    """write_draft 落盘后登记三闸行，并自动跑第②闸。

    draft_id 已存在时更新（重写草稿场景）；返回含 gate2 结果的完整行。
    """
    ws = workspace or _active_workspace()
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO sg_draft_gates (draft_id, workspace, scenario_id,
                 covers_json, source_delta, gate1_status, gate2_status,
                 gate3_status, created_by, created_at)
               VALUES (?,?,?,?,?, 'pending', 'pending', 'blocked', ?, ?)
               ON CONFLICT(draft_id) DO UPDATE SET
                 scenario_id=excluded.scenario_id, covers_json=excluded.covers_json,
                 source_delta=excluded.source_delta,
                 gate1_status=CASE WHEN gate1_status='approved' THEN 'pending'
                                   ELSE gate1_status END,
                 gate2_status='pending', gate3_status='blocked'""",
            (draft_id, ws, scenario_id, json.dumps(list(covers), ensure_ascii=False),
             source_delta or "", created_by, now))
    return run_gate2(draft_id, db_path)


def get_gate(draft_id: str, db_path: Path | None = None) -> dict | None:
    row = _find(draft_id, db_path)
    return _row_to_dict(row) if row else None


def list_gates(workspace: str = "", db_path: Path | None = None) -> list[dict]:
    ws = workspace or _active_workspace()
    try:
        with _LOCK, _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM sg_draft_gates WHERE workspace = ? ORDER BY created_at DESC",
                (ws,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════
# 第①闸：人工评审（人拍板，留痕）
# ══════════════════════════════════════════════════════════

def review_draft(draft_id: str, decision: str, reviewer: str, comment: str = "",
                 db_path: Path | None = None) -> dict:
    """第①闸人工评审。gate2 未 pass 时 approved 被拒（打回语义）。

    decision: approved / rejected；reviewer 必填留痕。
    """
    if decision not in GATE1_VALID:
        raise GateError("invalid_state", f"非法评审决定: {decision}")
    if not reviewer:
        raise GateError("missing_reviewer", "评审必须留痕 reviewer")
    row = _find(draft_id, db_path)
    if row is None:
        raise GateError("not_found", f"草稿三闸记录不存在: {draft_id}")
    if decision == "approved" and row["gate2_status"] != "pass":
        raise GateError("gate2_not_pass",
                        "格式校验（第②闸）未通过，不可评审通过——请先修改草稿或重跑校验")
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE sg_draft_gates SET gate1_status=?, gate1_reviewer=?, "
            "gate1_comment=?, gate1_ts=? WHERE draft_id=?",
            (decision, reviewer, comment, now, draft_id))
    row = _find(draft_id, db_path)
    return _row_to_dict(row)


# ══════════════════════════════════════════════════════════
# promote 前置（第③闸由 draft_promote 的发布门禁执行）
# ══════════════════════════════════════════════════════════

def check_promote_allowed(draft_id: str, db_path: Path | None = None) -> tuple[bool, str]:
    """promote 前置硬校验：gate1=approved + gate2=pass。

    第③闸（发布门禁 release_check）由 draft_promote.promote 在入库时自动跑，
    失败回滚——此处只校验前两闸（③在 promote 流程内执行并回填）。
    返回 (ok, reason)。
    """
    row = _find(draft_id, db_path)
    if row is None:
        # 无三闸记录 = 未走新通道（存量草稿）→ 拒绝（fail-closed，铁律 3）
        return False, "草稿无三闸登记（sg_draft_gates 缺失），禁止 promote"
    if row["gate1_status"] != "approved":
        return False, f"第①闸人工评审未通过（当前 {row['gate1_status']}），禁止 promote"
    if row["gate2_status"] != "pass":
        return False, f"第②闸格式校验未通过（当前 {row['gate2_status']}），禁止 promote"
    return True, ""


def mark_promoted(draft_id: str, db_path: Path | None = None):
    """promote 成功后回填 gate3=pass + promoted_at。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE sg_draft_gates SET gate3_status='pass', promoted_at=? "
            "WHERE draft_id=?",
            (now, draft_id))


def mark_gate3_fail(draft_id: str, report: str = "", db_path: Path | None = None):
    """发布门禁失败：gate3=fail 滞留草稿（附门禁报告摘要，排障可查）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE sg_draft_gates SET gate3_status='fail', gate3_report=? "
            "WHERE draft_id=?",
            (report or "", draft_id))


def source_delta_of(draft_id: str, db_path: Path | None = None) -> str:
    """草稿挂链的 source_delta（缺失 → 合规 WARNING 的数据源）。"""
    row = _find(draft_id, db_path)
    return row["source_delta"] if row else ""


def delete_workspace_gates(workspace: str, db_path: Path | None = None):
    """删除指定工作区的全部三闸记录（草稿区重置时调用）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM sg_draft_gates WHERE workspace = ?", (workspace,))


def set_draft_status_keep_gates(filename: str, status: str, module: str = "",
                                db_path: Path | None = None):
    """草稿台账状态更新（对齐 ledger_store.set_draft_status 语义，兼容调用）。"""
    from sg_core import ledger_store
    ledger_store.set_draft_status(filename, status, module)
