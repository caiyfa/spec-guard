"""gate_dock_service.py — 对话操作台（GateDock）汇总编排（一期，纯读）。

按面试上下文聚合待办闸门卡片，供 AgentChat「操作台」页签渲染。
铁律：本模块零写副作用；闸门写操作仍走原面板 REST（人拍板）。

卡片 kind 与接管档位（分档矩阵见设计文档 §5）：
- topic_confirm     议题候选确认（L3 白名单，可逆低危）
- material_include  材料入包（L3 白名单，可逆低危）
- score_confirm     评分 QA 确认（L2，永远人拍板）
- freeze_gates      冻结三闸 + 冻结（L2，永远人拍板）
- zentao_story      禅道建故事（L2，永远人拍板）
"""

from __future__ import annotations

import logging

from workbench.backend.services.specflow.sf_store import _connect

logger = logging.getLogger(__name__)


def _is_delta_frozen(delta_id: str) -> bool:
    """delta 是否已冻结（FREEZE.yaml 凭证存在）。"""
    try:
        from specstd.workspace import specflow_dir
        return (specflow_dir() / "changes" / delta_id / "FREEZE.yaml").is_file()
    except Exception as e:  # noqa: BLE001
        logger.warning("冻结凭证检查异常（按未冻结处理）: %s", e)
        return False


def _story_built(workspace: str, delta_id: str) -> bool:
    """该 delta 是否已有成功的建故事作业（幂等键含 delta_id）。"""
    from workbench.backend.services.specflow import sf_refs_store
    jobs = sf_refs_store.list_jobs(
        workspace=workspace, kind="story_create", status="succeeded")
    return any(delta_id in (j.get("idem_key") or "") for j in jobs)


def build_gate_dock(workspace: str, iv: dict) -> dict:
    """聚合当前面试上下文的待办闸门卡片（纯读）。

    Args:
        workspace: 当前工作区（隔离边界，fail-closed）
        iv: sf_interviews 行（含 iv_id/title/status/target_delta）
    """
    from specflow.materials import store as mat_store
    from workbench.backend.services.specflow.decision_service import (
        db_list_scores)

    iv_id = iv["iv_id"]
    cards: list[dict] = []

    # ── 材料类待办（议题确认 + 入包）──
    conn = _connect()
    mat_store.init_tables(conn)
    try:
        materials = mat_store.list_materials(
            conn, iv_id=iv_id, workspace=workspace)
        topics = mat_store.list_topics(conn, iv_id=iv_id, workspace=workspace)
    finally:
        conn.close()

    unconfirmed_by_mid: dict[str, list] = {}
    for t in topics:
        if not t.get("confirmed"):
            unconfirmed_by_mid.setdefault(t.get("material_id") or "", []).append(t)

    for m in materials:
        pend = unconfirmed_by_mid.get(m["material_id"], [])
        if m["status"] == "indexed" and pend:
            cards.append({
                "kind": "topic_confirm",
                "level": "L3",
                "title": "议题候选确认",
                "summary": f"《{m['filename']}》{len(pend)} 个议题候选待确认",
                "ref_id": m["material_id"],
                "payload": {
                    "iv_id": iv_id,
                    "mid": m["material_id"],
                    "filename": m["filename"],
                    "topics": [
                        {"tid": t["topic_id"], "title": t["title"],
                         "summary": t.get("summary") or ""}
                        for t in pend
                    ],
                },
            })

    for m in materials:
        if (m["status"] in ("parsed", "indexed", "packed")
                and not m.get("pack_included")):
            cards.append({
                "kind": "material_include",
                "level": "L3",
                "title": "材料入包",
                "summary": f"《{m['filename']}》已解析（{m['status']}），未入信息包",
                "ref_id": m["material_id"],
                "payload": {
                    "iv_id": iv_id,
                    "mid": m["material_id"],
                    "filename": m["filename"],
                    "status": m["status"],
                },
            })

    # ── 评分待办（suggested 待 QA/产品确认）──
    scores_resp = db_list_scores(iv_id, workspace)
    suggested = [s for s in scores_resp.get("scores", [])
                 if s.get("status") == "suggested"]
    if suggested:
        cards.append({
            "kind": "score_confirm",
            "level": "L2",
            "title": "评分确认",
            "summary": f"{len(suggested)} 条机器/LLM 评分待确认",
            "ref_id": iv_id,
            "payload": {
                "iv_id": iv_id,
                "scores": [
                    {"id": s["id"], "dimension": s["dimension"],
                     "score": s["score"], "source": s["source"],
                     "evidence": s.get("evidence") or ""}
                    for s in suggested
                ],
            },
        })

    # ── 冻结/禅道待办（挂在 target_delta 上）──
    delta_id = (iv.get("target_delta") or "").strip()
    if delta_id:
        if _is_delta_frozen(delta_id):
            if not _story_built(workspace, delta_id):
                cards.append({
                    "kind": "zentao_story",
                    "level": "L2",
                    "title": "禅道建故事",
                    "summary": f"delta「{delta_id}」已冻结，尚未创建禅道故事",
                    "ref_id": delta_id,
                    "payload": {
                        "delta_id": delta_id,
                        "suggested_title": iv.get("title") or "",
                    },
                })
        else:
            from workbench.backend.services.specflow.freeze_gate import (
                check_all_gates)
            gates = check_all_gates(workspace, iv_id, delta_id)
            gate_brief = {
                k: {"status": v.get("status")}
                for k, v in gates.get("gates", {}).items()
            }
            cards.append({
                "kind": "freeze_gates",
                "level": "L2",
                "title": "冻结三闸",
                "summary": (
                    f"delta「{delta_id}」未冻结 · "
                    f"①产品确认 {gate_brief.get('product_confirm', {}).get('status', '-')} · "
                    f"②合规 {gate_brief.get('conformance', {}).get('status', '-')} · "
                    f"③P0清零 {gate_brief.get('p0_zero', {}).get('status', '-')}"
                ),
                "ref_id": delta_id,
                "payload": {
                    "iv_id": iv_id,
                    "delta_id": delta_id,
                    "gates": gate_brief,
                    "freeze_allowed": bool(gates.get("freeze_allowed")),
                },
            })

    return {
        "interview": {
            "iv_id": iv_id,
            "title": iv.get("title") or "",
            "status": iv.get("status") or "",
            "target_delta": delta_id,
        },
        "cards": cards,
    }
