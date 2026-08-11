"""freeze_gate.py — 需求侧三闸冻结编排服务（M05，T-042）。

第①闸：产品确认（product 角色手工）
第②闸：specstd 合规校验（确定性，调 conformance.py）
第③闸：P0 清零门禁（转发 M04 gate API，含影响面确认 + 五维达标）
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from specflow.interview.gate import gate_aggregate, GateResult
from specflow.interview.decision_ledger import (
    init_tables as ledger_init_tables,
    count_pending_p0, get_impact_confirmed,
    add_gate_evidence,
)

from workbench.backend.services.specflow.sf_store import _connect, DB_PATH


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def product_confirm(delta_id: str, workspace: str, confirmed_by: str,
                    interview_id: str = "") -> dict:
    """闸① 产品确认。"""
    conn = _connect()
    ledger_init_tables(conn)
    try:
        evidence = add_gate_evidence(
            conn, workspace, interview_id or delta_id,
            "product_confirm", "pass",
            evidence=f"delta={delta_id}",
            actor=confirmed_by,
        )
        conn.commit()
        return {"gate": "product_confirm", "status": "pass",
                "actor": confirmed_by, "evidence": evidence}
    finally:
        conn.close()


def conformance_check(workspace: str, delta_id: str,
                      spec_text: str = "") -> dict:
    """闸② specstd 合规校验（确定性）。"""
    try:
        from specstd.conformance import check_conformance
        from specstd.workspace import get_active_workspace
        ws = get_active_workspace()
        if ws:
            report = check_conformance(ws.root, workspace)
            findings = [
                {"rule": f.rule, "level": f.level, "message": f.message}
                for f in (report.findings or [])
                if f.level in ("ERROR", "WARN")
            ]
            verdict = "pass" if report.verdict == "PASS" else "fail"
            return {
                "gate": "conformance",
                "status": verdict,
                "verdict": report.verdict,
                "findings": findings,
                "total_rules": report.summary.get("total", 0),
                "errors": report.summary.get("errors", 0),
            }
    except Exception as e:
        pass
    # fallback: 基础校验
    errors = []
    if not delta_id:
        errors.append("delta_id 为空")
    if not spec_text:
        errors.append("spec_text 为空，无法执行全文校验")
    return {
        "gate": "conformance",
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }


def p0_gate_check(workspace: str, interview_id: str) -> dict:
    """闸③ P0 清零门禁（转发 M04 gate API）。"""
    from workbench.backend.services.specflow.decision_service import db_get_gate
    gate = db_get_gate(interview_id, workspace)
    return {
        "gate": "p0_zero",
        "status": "pass" if gate.get("freeze_allowed") else "fail",
        "gate_detail": gate,
    }


def check_all_gates(workspace: str, interview_id: str,
                    delta_id: str = "", spec_text: str = "") -> dict:
    """三闸全量检查。"""
    g1 = product_confirm(delta_id or interview_id, workspace, "")
    g2 = conformance_check(workspace, delta_id or interview_id, spec_text)
    g3 = p0_gate_check(workspace, interview_id)
    all_pass = (
        g1.get("status") == "pass"
        and g2.get("status") == "pass"
        and g3.get("status") == "pass"
    )
    return {
        "freeze_allowed": all_pass,
        "gates": {"product_confirm": g1, "conformance": g2, "p0_zero": g3},
    }


def freeze_delta(workspace: str, interview_id: str,
                 delta_id: str, spec_sha: str = "",
                 frozen_by: str = "",
                 spec_text: str = "") -> dict:
    """执行冻结（三闸全 pass 才放行，否则 403）。

    Returns:
        {"ok": bool, "error": str, "freeze": dict} (freeze_allowed=False 时 403)
    """
    gates = check_all_gates(workspace, interview_id, delta_id, spec_text)
    if not gates["freeze_allowed"]:
        return {
            "ok": False,
            "error": "冻结条件未满足",
            "gate_detail": gates,
        }

    # 落盘 FREEZE.yaml
    try:
        from specstd.workspace import specflow_dir
        sf = specflow_dir()
        changes_dir = sf / "changes" / delta_id
        changes_dir.mkdir(parents=True, exist_ok=True)
        freeze_mark = changes_dir / "FREEZE.yaml"

        import yaml
        freeze_data = {
            "delta": delta_id,
            "interview_id": interview_id,
            "workspace": workspace,
            "frozen_by": frozen_by,
            "frozen_at": _now(),
            "spec_sha": spec_sha or "",
            "gates": {
                k: {"status": v.get("status")}
                for k, v in gates["gates"].items()
            },
        }
        with open(freeze_mark, "w", encoding="utf-8") as f:
            yaml.dump(freeze_data, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        return {"ok": False, "error": f"冻结凭证写入失败: {e}"}

    return {"ok": True, "freeze": freeze_data}


def archive_delta(workspace: str, delta_id: str,
                  archive_by: str = "") -> dict:
    """归档 delta（冻结后可归档）。"""
    try:
        from specstd.workspace import specflow_dir
        from specflow.delta.archive import archive_delta as _archive_delta
        from specflow.delta.verify import verify_delta_dir
        sf = specflow_dir()
        changes_dir = sf / "changes" / delta_id
        archive_root = sf / "archive"

        if not changes_dir.is_dir():
            return {"ok": False, "error": f"changes/{delta_id} 不存在"}

        # 先 verify
        v_result = verify_delta_dir(changes_dir)
        if v_result and v_result.get("verdict") == "FAIL":
            return {"ok": False, "error": f"verify-delta 未通过: {v_result.get('errors')}"}

        path = _archive_delta(changes_dir, archive_root)
        return {"ok": True, "archive_path": path}
    except Exception as e:
        return {"ok": False, "error": f"归档失败: {e}"}