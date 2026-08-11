"""pack_assembler.py — 信息包六分区装配器（M03 §4.3，T-032）。

确定性装配（零 LLM）：议题卡 + 已入包材料 + 基线摘录 + 未闭环 SPQ +
上轮执行摘要 + 历史决策 → info_pack.yaml（含 freshness）。

数据源全部只读引用：specstd.anchors / feedback ledger / spec_reader /
M04 台账（通过回调函数注入，保持本模块无重依赖）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml

# 分区键（M03 §4.3）
SECTIONS = ("topic_card", "materials", "baseline",
            "open_spq", "last_report", "history_decisions")


def assemble_pack(
    iv_id: str,
    workspace: str,
    specflow_base: Path,
    conn,
    *,
    topic_provider: Callable[[], Optional[dict]] = None,
    baseline_provider: Callable[[], list[dict]] = None,
    spq_provider: Callable[[], list[dict]] = None,
    report_provider: Callable[[], Optional[dict]] = None,
    decisions_provider: Callable[[], list[dict]] = None,
) -> dict:
    """六分区装配 → 写 info_pack.yaml，返回装配结果 dict。

    分区数据源（回调注入，均为只读）：
      topic_card     M02 topic.yaml（议题卡）
      materials      sf_materials 中 pack_included=1 且状态达 parsed/indexed/packed
      baseline       specstd.anchors 基线摘录（只读引用，不落副本正文）
      open_spq       feedback/ledger 未闭环 SPQ
      last_report    read_run_report 上轮执行摘要
      history_decisions  M04 决策台账（interview 维度）
    """
    from specflow.materials import store

    pack: dict = {
        "iv_id": iv_id,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "freshness": {"baseline_fingerprint": "", "stale": False},
        "sections": {},
    }

    # ① 议题卡（M02）
    if topic_provider:
        topic = topic_provider() or {}
        pack["sections"]["topic_card"] = {"ref": "topic.yaml", "title": topic.get("title", "")}

    # ② 材料（人拍板入包子集，带议题候选）
    mats = []
    for m in store.list_materials(conn, iv_id=iv_id, workspace=workspace):
        if not m["pack_included"] or m["status"] not in ("parsed", "indexed", "packed"):
            continue
        topics = store.list_topics(conn, material_id=m["material_id"],
                                   workspace=workspace, confirmed_only=True)
        mats.append({
            "material": m["material_id"],
            "filename": m["filename"],
            "fmt": m["fmt"],
            "status": m["status"],
            "sha256_12": m["sha256_12"],
            "topics": [t["topic_id"] for t in topics],
        })
    pack["sections"]["materials"] = mats

    # ③ 基线摘录（只读引用）
    pack["sections"]["baseline"] = baseline_provider() if baseline_provider else []

    # ④ 未闭环 SPQ（pending/in_progress 均为未闭环）
    spqs = spq_provider() if spq_provider else []
    pack["sections"]["open_spq"] = [{
        "id": s.get("spq_id", s.get("id", "")),
        "status": s.get("status", ""),
        "title": s.get("title", s.get("message", "")),
    } for s in spqs]

    # ⑤ 上轮执行摘要
    report = report_provider() if report_provider else None
    pack["sections"]["last_report"] = report or {}

    # ⑥ 历史决策（M04 台账）
    decs = decisions_provider() if decisions_provider else []
    pack["sections"]["history_decisions"] = [{
        "id": d.get("id", ""),
        "status": d.get("status", ""),
        "question": d.get("question", ""),
    } for d in decs]

    # 落盘 info_pack.yaml
    pack_path = specflow_base / "interviews" / iv_id / "info_pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(
        yaml.dump(pack, allow_unicode=True, indent=2, sort_keys=False),
        encoding="utf-8")

    # 装配结果附分区清单（供 pack_read_section 使用）
    result = dict(pack)
    result["_path"] = str(pack_path)
    result["sections_available"] = [k for k in SECTIONS
                                    if k in pack["sections"] and pack["sections"][k]]
    return result


def read_pack(iv_id: str, specflow_base: Path) -> Optional[dict]:
    """读取装配后的 info_pack.yaml；不存在返回 None。"""
    pack_path = specflow_base / "interviews" / iv_id / "info_pack.yaml"
    if not pack_path.is_file():
        return None
    return yaml.safe_load(pack_path.read_text(encoding="utf-8"))


def read_section(pack: dict, section: str) -> dict:
    """读单分区（面试官按需取上下文）。"""
    if section not in SECTIONS:
        return {"error": f"未知分区: {section!r}（允许: {SECTIONS}）"}
    return {"section": section, "content": (pack.get("sections") or {}).get(section, [])}


def apply_freshness(pack: dict, baseline_fingerprint: str, stale: bool) -> dict:
    """写入/更新新鲜度（info_pack_freshness 语义：基线变更后旧材料失效可感知）。"""
    pack["freshness"] = {
        "baseline_fingerprint": baseline_fingerprint,
        "stale": stale,
    }
    return pack
