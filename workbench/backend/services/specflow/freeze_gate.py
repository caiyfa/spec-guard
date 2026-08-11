"""freeze_gate.py — 需求侧三闸冻结编排服务（M05，T-042）。

第①闸：产品确认（product 角色手工，仅 POST gates/1-product-confirm 触发）
第②闸：specstd 合规校验（确定性，调 conformance.py）
第③闸：P0 清零门禁（转发 M04 gate API，含影响面确认 + 五维达标）
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _evidence_key(interview_id: str, delta_id: str) -> str:
    """闸门证据落库键：interview_id 优先，缺失回退 delta_id。

    确认（product_confirm）与查询（check_all_gates）两端必须用同一 key 表达式，
    否则同一 delta 的证据会落/查不同键。
    """
    return interview_id or delta_id


def get_product_confirmed(workspace: str, interview_id: str,
                          delta_id: str = "") -> dict:
    """闸① 纯读：查询产品确认证据是否存在（无写副作用）。"""
    conn = _connect()
    ledger_init_tables(conn)
    try:
        key = _evidence_key(interview_id, delta_id)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sf_gate_evidence "
            "WHERE interview_id = ? AND gate_item = 'product_confirm' "
            "AND verdict = 'pass' AND workspace = ?",
            (key, workspace))
        row = cursor.fetchone()
        confirmed = bool(row and row[0] > 0)
        return {
            "gate": "product_confirm",
            "status": "pass" if confirmed else "fail",
            "confirmed": confirmed,
            "evidence_key": key,
        }
    finally:
        conn.close()


def product_confirm(delta_id: str, workspace: str, confirmed_by: str,
                    interview_id: str = "") -> dict:
    """闸① 产品确认（人工动作，仅 product 角色端点可调）。

    记录确认证据（pass + 操作人）。confirmed_by 为空时拒绝——
    不允许无主确认写库。
    """
    actor = (confirmed_by or "").strip()
    if not actor:
        return {"gate": "product_confirm", "status": "fail",
                "error": "confirmed_by 不能为空（确认必须带操作人）"}
    conn = _connect()
    ledger_init_tables(conn)
    try:
        key = _evidence_key(interview_id, delta_id)
        evidence = add_gate_evidence(
            conn, workspace, key,
            "product_confirm", "pass",
            evidence=f"delta={delta_id}",
            actor=actor,
        )
        conn.commit()
        return {"gate": "product_confirm", "status": "pass",
                "actor": actor, "evidence": evidence}
    finally:
        conn.close()


def conformance_check(workspace: str, delta_id: str,
                      spec_text: str = "") -> dict:
    """闸② specstd 合规校验（确定性，fail-closed）。

    工作区上下文缺失或校验执行异常时返回 fail（degraded=True），
    绝不静默降级为 pass。
    """
    try:
        from specstd.conformance import check_conformance
        from specstd.workspace import get_active_workspace
        ws = get_active_workspace()
        if not ws:
            return {
                "gate": "conformance",
                "status": "fail",
                "errors": ["工作区上下文缺失，无法执行合规校验"],
                "degraded": True,
            }
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
        logger.warning("conformance 校验执行异常: %s", e, exc_info=True)
        return {
            "gate": "conformance",
            "status": "fail",
            "errors": [f"conformance 校验执行异常: {e}"],
            "degraded": True,
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
    """三闸全量检查（纯读，无任何写副作用）。

    闸①为查询已有确认证据，不在此处插入——确认动作只能由
    POST gates/1-product-confirm（product 角色）触发。
    """
    g1 = get_product_confirmed(workspace, interview_id, delta_id)
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
    """执行冻结（三闸全 pass 才放行，否则返回 gate_detail 供上层映射 409）。

    Returns:
        {"ok": bool, "error": str, "freeze": dict} (freeze_allowed=False 时不落凭证)
    """
    actor = (frozen_by or "").strip()
    if not actor:
        return {"ok": False, "error": "frozen_by 不能为空（冻结必须带操作人）"}
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
            "frozen_by": actor,
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

        # 归档前置：必须已冻结（FREEZE.yaml 凭证存在），防止未冻结绕闸归档
        if not (changes_dir / "FREEZE.yaml").is_file():
            return {"ok": False, "error": f"delta {delta_id} 未冻结，禁止归档"}

        # 先 verify
        v_result = verify_delta_dir(changes_dir)
        if v_result and v_result.get("verdict") == "FAIL":
            return {"ok": False, "error": f"verify-delta 未通过: {v_result.get('errors')}"}

        path = _archive_delta(changes_dir, archive_root)
        return {"ok": True, "archive_path": path}
    except Exception as e:
        return {"ok": False, "error": f"归档失败: {e}"}