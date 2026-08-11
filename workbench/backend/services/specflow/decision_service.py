"""decision_service.py — 决策服务（T-023，M04）。

决策登记/落锤/增补/门禁聚合的业务逻辑编排。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from specflow.interview.decision_ledger import (
    init_tables, create_decision, resolve_decision, amend_decision,
    get_decision, list_decisions, count_pending_p0,
    add_gate_evidence, get_impact_confirmed,
    add_score, confirm_score, list_scores, calculate_total_score,
    has_suggested_score, export_ledger,
)
from specflow.interview.gate import gate_aggregate, GateResult

from workbench.backend.services.specflow.sf_store import _connect


def db_propose_decision(workspace: str, interview_id: str,
                        priority: str, question: str,
                        question_ref: str = "",
                        links: list[dict] = None) -> dict:
    """登记决策候选（Agent 建议，永远 pending 出生）。"""
    conn = _connect()
    init_tables(conn)
    try:
        dec = create_decision(conn, workspace, interview_id, priority,
                              question, question_ref, links)
        conn.commit()
        return dec
    finally:
        conn.close()


def db_resolve_decision(d_id: str, resolution: str,
                        resolved_by: str) -> dict:
    """人拍板确认决策（仅 product 角色）。"""
    conn = _connect()
    init_tables(conn)
    try:
        dec = resolve_decision(conn, d_id, resolution, resolved_by)
        conn.commit()
        return dec
    finally:
        conn.close()


def db_amend_decision(d_id: str, new_priority: str, new_question: str,
                      new_resolution: str, reason: str, created_by: str,
                      workspace: str, interview_id: str) -> dict:
    """增补决策（生成新 D-xxx，原条目标 superseded）。"""
    conn = _connect()
    init_tables(conn)
    try:
        old_dec, new_dec = amend_decision(
            conn, d_id, new_priority, new_question, new_resolution,
            reason, created_by, workspace, interview_id)
        conn.commit()
        return {"old": old_dec, "new": new_dec}
    finally:
        conn.close()


def db_list_decisions(interview_id: str = "", status: str = "",
                      priority: str = "", workspace: str = "") -> list[dict]:
    """查询决策列表。"""
    conn = _connect()
    init_tables(conn)
    try:
        return list_decisions(conn, interview_id, status, priority, workspace)
    finally:
        conn.close()


def db_get_gate(interview_id: str, workspace: str = "") -> dict:
    """P0 清零门禁聚合（按工作区隔离，防跨工作区 IV-xxx 重号串扰）。"""
    conn = _connect()
    init_tables(conn)
    try:
        p0_pending = count_pending_p0(conn, interview_id, workspace)
        impact_confirmed = get_impact_confirmed(conn, interview_id, workspace)
        total_score = calculate_total_score(conn, interview_id, workspace)
        result = gate_aggregate(
            p0_pending_count=p0_pending,
            impact_confirmed=impact_confirmed,
            total_score=total_score,
        )
        return result.to_dict()
    finally:
        conn.close()


def db_confirm_impact(workspace: str, interview_id: str,
                      actor: str, affected_frs: list[str] = None,
                      snapshot_path: str = "") -> dict:
    """影响面人工确认。"""
    conn = _connect()
    init_tables(conn)
    try:
        result = add_gate_evidence(conn, workspace, interview_id,
                                   "impact_confirm", "pass",
                                   evidence=snapshot_path or "",
                                   actor=actor)
        conn.commit()
        return result
    finally:
        conn.close()


def db_add_score(workspace: str, interview_id: str,
                 dimension: str, score: int, source: str,
                 evidence: str = "", spec_sha: str = "",
                 skip_if_suggested: bool = False) -> dict:
    """添加评分条目（skip_if_suggested=True 时已有 suggested 则跳过，幂等）。"""
    conn = _connect()
    init_tables(conn)
    try:
        if skip_if_suggested and has_suggested_score(
                conn, interview_id, dimension, workspace):
            return {"id": None, "dimension": dimension,
                    "score": None, "source": source,
                    "status": "suggested", "skipped": True}
        result = add_score(conn, workspace, interview_id, dimension,
                           score, source, evidence, spec_sha)
        conn.commit()
        return result
    finally:
        conn.close()


def db_confirm_score(score_id: int, verdict: str, confirmed_by: str,
                     workspace: str = "") -> dict:
    """QA 确认/驳回评分。

    先校验 workspace 归属再 commit（防跨工作区误操作）。
    """
    conn = _connect()
    init_tables(conn)
    try:
        # 校验评分归属工作区（防跨工作区误操作）
        if workspace:
            row = conn.execute(
                "SELECT workspace FROM sf_scores WHERE id = ?", (score_id,)).fetchone()
            if not row:
                raise KeyError(f"评分条目不存在: {score_id}")
            if row[0] != workspace:
                raise KeyError(f"评分条目不存在: {score_id}")
        result = confirm_score(conn, score_id, verdict, confirmed_by)
        conn.commit()
        return result
    finally:
        conn.close()


def db_list_scores(interview_id: str, workspace: str = "") -> dict:
    """列出评分记录（按工作区隔离）。"""
    conn = _connect()
    init_tables(conn)
    try:
        scores = list_scores(conn, interview_id, workspace)
        total = calculate_total_score(conn, interview_id, workspace)
        return {"scores": scores, "total": round(total, 1), "pass": total >= 70.0}
    finally:
        conn.close()


def db_export_ledger(interview_id: str, workspace: str = "") -> dict:
    """导出面试台账快照（按工作区隔离）。"""
    conn = _connect()
    init_tables(conn)
    try:
        return export_ledger(conn, interview_id, workspace)
    finally:
        conn.close()