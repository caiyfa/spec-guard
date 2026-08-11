"""materials_service.py — 材料包业务编排（T-030/T-031/T-032，M03）。

上传/解析/索引/入包/装配/新鲜度的服务层（REST 与 MCP 共用）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from specflow.materials import pipeline as pl
from specflow.materials import pack_assembler as pa
from specflow.materials import store

from workbench.backend.services.specflow.sf_store import _connect

logger = logging.getLogger(__name__)


def _db_conn():
    conn = _connect()
    store.init_tables(conn)
    return conn


# ══════════════════════════════════════════════════════════
# T-030：上传 + 解析管线
# ══════════════════════════════════════════════════════════

def db_upload_material(iv_id: str, workspace: str, filename: str,
                       content: bytes, uploaded_by: str,
                       specflow_base: Path) -> dict:
    """上传材料：落盘 materials/（原文不动）+ 登记 + 触发解析。

    解析失败（无文本层/损坏/格式不可识别）→ status=failed + parse_error
    （诚实呈现，不静默降级）。

    Returns:
        {material, status, parse_error?}
    """
    conn = _db_conn()
    try:
        fmt = pl.sniff(content, filename)
        if not fmt:
            mat = store.create_material(
                conn, iv_id, workspace, filename, "txt", len(content),
                content, uploaded_by)
            store.update_material_status(conn, mat["material_id"], "failed",
                                         parse_error="无法识别文件格式（非 md/txt/docx/pdf）")
            conn.commit()
            return {"material": store.get_material(conn, mat["material_id"]),
                    "status": "failed", "parse_error": "无法识别文件格式"}
        mat = store.create_material(
            conn, iv_id, workspace, filename, fmt, len(content), content,
            uploaded_by)
        conn.commit()
        result = _run_parse(conn, mat, content, specflow_base)
        conn.commit()
        return result
    finally:
        conn.close()


def _run_parse(conn, mat: dict, content: bytes, specflow_base: Path) -> dict:
    """执行 sniff/extract/chunk 并推进状态机（uploaded→parsing→parsed→indexed）。"""
    mid = mat["material_id"]
    store.update_material_status(conn, mid, "parsing")
    try:
        text = pl.extract(content, mat["fmt"])
    except pl.ExtractError as e:
        store.update_material_status(conn, mid, "failed", parse_error=str(e))
        return {"material": store.get_material(conn, mid),
                "status": "failed", "parse_error": str(e)}

    chunks = pl.chunk(text, mat["fmt"])
    # 解析产物落 _parsed/（派生物，可重建）
    iv_dir = specflow_base / "interviews" / mat["iv_id"]
    parsed_dir = iv_dir / "materials" / "_parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(mat["filename"]).stem or mid
    (parsed_dir / f"{stem}.extract.txt").write_text(text, encoding="utf-8")
    import json
    (parsed_dir / f"{stem}.chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    # T-034：PRD 类材料（pdf 含 § 锚点）额外产出 coverage_map.yaml（机打）
    if mat["fmt"] == "pdf" and any(c.get("section") for c in chunks):
        try:
            from specflow.materials.coverage import build_coverage_map, write_coverage_map
            from specstd.anchors import scan_anchors
            from specstd.workspace import get_workspace_root
            ws_root = get_workspace_root()
            anchors = scan_anchors(ws_root) if ws_root else {}
            coverage = build_coverage_map(chunks, anchors)
            write_coverage_map(coverage, parsed_dir, stem)
        except Exception as e:
            logger.warning("coverage_map 生成失败（不阻断解析）: %s", e)

    store.update_material_status(conn, mid, "indexed")
    return {"material": store.get_material(conn, mid),
            "status": "indexed", "chunks": len(chunks)}


# ══════════════════════════════════════════════════════════
# T-031：议题候选提取 + 确认闸门
# ══════════════════════════════════════════════════════════

def db_add_topic(material_id: str, iv_id: str, workspace: str,
                 title: str, priority_hint: str = "",
                 fr_hints: list[str] = None,
                 prd_section: str = "") -> dict:
    """登记议题候选（LLM 在 Agent 侧，工具落库；confirmed=0 出生）。"""
    conn = _db_conn()
    try:
        t = store.add_topic(conn, material_id, iv_id, workspace, title,
                            priority_hint, fr_hints, prd_section)
        conn.commit()
        return t
    finally:
        conn.close()


def db_list_materials(iv_id: str, workspace: str,
                      status: str = "") -> list[dict]:
    """材料列表（按工作区隔离）。"""
    conn = _db_conn()
    try:
        return store.list_materials(conn, iv_id=iv_id, workspace=workspace,
                                    status=status)
    finally:
        conn.close()


def db_list_topics(iv_id: str, workspace: str,
                   confirmed_only: bool = False,
                   material_id: str = "") -> list[dict]:
    conn = _db_conn()
    try:
        return store.list_topics(conn, iv_id=iv_id, workspace=workspace,
                                 confirmed_only=confirmed_only,
                                 material_id=material_id)
    finally:
        conn.close()


def db_confirm_topic(topic_id: str, workspace: str,
                     confirmed: int = 1) -> dict:
    """人拍板：议题候选生效（归属校验：候选必须属于当前工作区）。"""
    conn = _db_conn()
    try:
        t = store.get_topic(conn, topic_id)
        if not t or t["workspace"] != workspace:
            raise KeyError(f"议题候选不存在: {topic_id}")
        store.confirm_topic(conn, topic_id, confirmed)
        conn.commit()
        return store.get_topic(conn, topic_id)
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# T-032：入包闸门 + 六分区装配 + 新鲜度
# ══════════════════════════════════════════════════════════

def db_include_material(material_id: str, workspace: str,
                        included: int = 1) -> dict:
    """人拍板：材料入信息包（pack_included=1 才被装配器纳入）。"""
    conn = _db_conn()
    try:
        m = store.get_material(conn, material_id)
        if not m or m["workspace"] != workspace:
            raise KeyError(f"材料不存在: {material_id}")
        if m["status"] not in ("parsed", "indexed", "packed"):
            raise ValueError(f"材料 {material_id} 状态={m['status']}，"
                             f"仅已解析（parsed/indexed/packed）可入包")
        store.set_pack_included(conn, material_id, included)
        conn.commit()
        return store.get_material(conn, material_id)
    finally:
        conn.close()


def db_assemble_pack(iv_id: str, workspace: str,
                     specflow_base: Path,
                     baseline_fingerprint: str = "") -> dict:
    """六分区装配 → info_pack.yaml（确定性，零 LLM）。"""
    conn = _db_conn()
    try:
        result = pa.assemble_pack(
            iv_id, workspace, specflow_base, conn,
            topic_provider=lambda: _topic_card(iv_id, specflow_base),
            baseline_provider=lambda: _baseline_refs(specflow_base),
            spq_provider=_open_spqs,
            report_provider=lambda: _last_report_summary(),
            decisions_provider=lambda: _history_decisions(conn, iv_id, workspace),
        )
        if baseline_fingerprint:
            pa.apply_freshness(result, baseline_fingerprint, False)
        return result
    finally:
        conn.close()


def db_read_pack_section(iv_id: str, section: str,
                         specflow_base: Path) -> dict:
    """读单分区（面试官 pack_read_section）。"""
    pack = pa.read_pack(iv_id, specflow_base)
    if not pack:
        return {"error": f"面试 {iv_id} 尚无装配后的信息包（请先 pack_assemble）"}
    return pa.read_section(pack, section)


def db_freshness_check(iv_id: str, workspace: str,
                       specflow_base: Path,
                       current_fingerprint: str = "") -> dict:
    """新鲜度校验（基线指纹比对；stale 时提示材料可能过期）。"""
    pack = pa.read_pack(iv_id, specflow_base)
    if not pack:
        return {"error": f"面试 {iv_id} 尚无信息包"}
    old = (pack.get("freshness") or {}).get("baseline_fingerprint", "")
    stale = bool(old) and current_fingerprint and old != current_fingerprint
    pa.apply_freshness(pack, current_fingerprint or old, stale)
    # 回写文件（保持单一事实源）
    import yaml
    pack_path = specflow_base / "interviews" / iv_id / "info_pack.yaml"
    pack_path.write_text(
        yaml.dump(pack, allow_unicode=True, indent=2, sort_keys=False),
        encoding="utf-8")
    return {"iv_id": iv_id, "freshness": pack["freshness"], "stale": stale}


# ── 六分区数据源（只读） ──

def _topic_card(iv_id: str, specflow_base: Path) -> Optional[dict]:
    from specflow.interview.topic import load_topic
    try:
        t = load_topic(iv_id, specflow_base)
        return {"title": t.title, "status": t.status} if t else None
    except Exception as e:
        logger.warning("议题卡读取失败: %s", e)
        return None


def _baseline_refs(specflow_base: Path) -> list[dict]:
    """基线摘录（specstd.anchors 只读引用，不落副本正文）。"""
    try:
        from specstd.anchors import scan_anchors
        from specstd.workspace import get_workspace_root
        ws_root = get_workspace_root()
        if not ws_root:
            return []
        anchors = scan_anchors(ws_root)
        return [{
            "fr": info.fr_id,
            "title": info.title,
            "file": info.file_path,
            "module": info.module,
        } for info in anchors.values()][:50]
    except Exception as e:
        logger.warning("基线摘录失败: %s", e)
        return []


def _open_spqs() -> list[dict]:
    """未闭环 SPQ（feedback/ledger：pending/in_progress）。"""
    try:
        from pathlib import Path as _P
        from feedback.ledger import FeedbackLedger
        # 与 workspace router 同一加载路径（SG_ROOT/feedback/ledger.json）
        sg_root = _P(__file__).resolve().parent.parent.parent.parent.parent
        ledger = FeedbackLedger(sg_root / "feedback" / "ledger.json")
        return [e for e in ledger.list_entries()
                if e.get("status") in ("pending", "in_progress")][:20]
    except Exception as e:
        logger.warning("SPQ 读取失败: %s", e)
        return []


def _last_report_summary() -> Optional[dict]:
    """上轮执行摘要（最新 run 的 verdict 分布，execution_index 只读查询）。"""
    try:
        from specstd.workspace import reports_dir
        from services import execution_index
        entries = execution_index.query_executions(reports_dir(), limit=1)
        if not entries:
            return {}
        latest = entries[0]
        return {
            "run": latest.get("run_id", latest.get("task_id", "")),
            "scenario": latest.get("scenario_id", ""),
            "verdict": latest.get("verdict", ""),
            "finished_at": latest.get("finished_at", ""),
        }
    except Exception as e:
        logger.warning("上轮执行摘要读取失败: %s", e)
        return {}


def _history_decisions(conn, iv_id: str, workspace: str) -> list[dict]:
    """历史决策（M04 台账，interview 维度只读引用）。"""
    try:
        from specflow.interview.decision_ledger import list_decisions
        return list_decisions(conn, interview_id=iv_id, workspace=workspace)
    except Exception as e:
        logger.warning("历史决策读取失败: %s", e)
        return []
