"""interview_service.py — 面试服务（T-020，M02）。

开标/提问/记录/门禁/冻结业务逻辑编排。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from specflow.interview.topic import (
    Topic, SourceRef, BaselineRef, create_topic, load_topic,
)
from specflow.interview.iv_lifecycle import (
    transition_status, append_transcript, iv_transcript_path,
    iv_snapshot_path,
)
from specflow.interview.gate import (
    gate_aggregate, GateResult, validate_freeze_request,
)
from specflow.interview.decision_ledger import (
    count_pending_p0, get_impact_confirmed, calculate_total_score,
    export_ledger,
)


def open_interview(title: str, initiator_emp: str, initiator_role: str,
                   source: list[dict], target_delta: str = "",
                   baseline_refs: list[dict] = None,
                   session_id: str = "",
                   workspace: str = "",
                   specflow_base: Path = None) -> dict:
    """开标：创建议题卡 + 更新状态 interviewing + DB 记录。

    Returns:
        {iv_id, topic, status}
    """
    from workbench.backend.services.specflow import sf_store as sf
    import logging
    logger = logging.getLogger(__name__)

    if not specflow_base:
        from specstd.workspace import specflow_dir
        specflow_base = specflow_dir()

    src_objs = [SourceRef(**s) for s in source]
    bl_objs = [BaselineRef(**r) for r in (baseline_refs or [])]
    topic = create_topic(
        title=title,
        initiator_emp=initiator_emp,
        initiator_role=initiator_role,
        source=src_objs,
        target_delta=target_delta,
        baseline_refs=bl_objs,
        specflow_base=specflow_base,
    )
    # 状态推进：opened → interviewing
    transition_status(topic.status, "interviewing")
    topic.status = "interviewing"
    topic.write(specflow_base / "interviews" / topic.iv_id)

    # DB 记录（索引失败不阻断主链路，但记录日志供排查）
    if workspace and session_id:
        try:
            sf.create_interview(topic.iv_id, workspace, session_id,
                                title, initiator_emp, target_delta)
            # 同时初始化 decision_ledger 表（复用 sf_store 连接，路径单一事实源）
            from specflow.interview.decision_ledger import init_tables as dl_init
            conn = sf._connect()
            dl_init(conn)
            conn.close()
        except Exception as e:
            logger.warning("sf 索引失败（不阻断开标）: %s", e)

    return {"iv_id": topic.iv_id, "topic": topic, "status": "interviewing"}


def get_gate_status(iv_id: str, workspace: str = "",
                    specflow_base: Path = None) -> GateResult:
    """获取门禁聚合状态（按工作区隔离）。"""
    from workbench.backend.services.specflow.sf_store import _connect
    import logging
    logger = logging.getLogger(__name__)

    p0_pending = 0
    impact_confirmed = False
    total_score = 0.0

    try:
        conn = _connect()
        p0_pending = count_pending_p0(conn, iv_id, workspace)
        impact_confirmed = get_impact_confirmed(conn, iv_id, workspace)
        total_score = calculate_total_score(conn, iv_id, workspace)
        conn.close()
    except Exception as e:
        logger.warning("门禁聚合读取失败（按全零 fail-closed）: %s", e)

    return gate_aggregate(
        p0_pending_count=p0_pending,
        impact_confirmed=impact_confirmed,
        total_score=total_score,
    )


def confirm_impact(iv_id: str, actor: str, affected_frs: list[str] = None,
                   snapshot_path: str = "",
                   workspace: str = "",
                   specflow_base: Path = None) -> dict:
    """影响面人工确认。"""
    from specflow.interview.decision_ledger import add_gate_evidence
    from workbench.backend.services.specflow.sf_store import _connect

    if not specflow_base:
        from specstd.workspace import specflow_dir
        specflow_base = specflow_dir()

    conn = _connect()
    result = add_gate_evidence(conn, workspace, iv_id,
                               "impact_confirm", "pass",
                               evidence=snapshot_path or "",
                               actor=actor)
    conn.commit()
    conn.close()

    # 写快照文件
    if affected_frs:
        import json
        snap = iv_snapshot_path(specflow_base, iv_id)
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(json.dumps({
            "iv_id": iv_id,
            "affected_frs": affected_frs,
            "confirmed_by": actor,
            "snapshot_path": snapshot_path,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def record_transcript(iv_id: str, role: str, text: str,
                      q_ref: str = "",
                      extracted_decision: dict = None,
                      specflow_base: Path = None) -> dict:
    """记录面试流水。"""
    from datetime import datetime, timezone
    if not specflow_base:
        from specstd.workspace import specflow_dir
        specflow_base = specflow_dir()

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "text": text,
    }
    if q_ref:
        entry["q_ref"] = q_ref
    if extracted_decision:
        entry["extracted_decision"] = extracted_decision
        entry["confirmed"] = False

    tpath = iv_transcript_path(specflow_base, iv_id)
    append_transcript(tpath, entry)
    return entry


def check_freeze(iv_id: str, workspace: str = "",
                 specflow_base: Path = None) -> dict:
    """检查冻结条件并返回门禁聚合结果。"""
    result = get_gate_status(iv_id, workspace, specflow_base)
    error = validate_freeze_request(result)
    return {
        "allowed": error is None,
        "gate": result.to_dict(),
        "error": error,
    }