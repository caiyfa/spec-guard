"""coverage_gaps — 覆盖缺口三态聚合（M07 §4.1，T-060）。

三态永远从源数据确定性派生（图谱红线：删掉重建必须同一结果）：
  spec 锚点（specstd/anchors.py）× 场景 covers（scenarios/）× 草稿（.specguard/drafts/）
  覆盖状态 = {🔴 gap 无覆盖 / 🟡 draft 草稿待审 / 🟢 covered 已覆盖}

草稿不计覆盖：🟡 与 🔴 同 FR 可并存（d-118 未入库前 FR-012 仍是缺口）。

同时提供：
  - rank_gaps：缺口优先级确定性排序（delta 新增 P0 > 修改触及 > 历史缺口 > 边界/冲突）
  - backlink：FR 反向链接（场景/草稿/最近 run），只读派生不落库
  - build_next_batch：生成下一批（只产草稿不产计划，铁律 6）
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

# 覆盖状态 reason 枚举（排序器输入，M07 §4.4）
REASON_DELTA_NEW_P0 = "delta_new_p0"    # 权重 100（delta 新增且 P0 决策命中）
REASON_DELTA_NEW = "delta_new"          # 权重 90（delta 新增但非 P0）
REASON_DELTA_MODIFIED = "delta_modified"  # 权重 80
REASON_HISTORY = "history"              # 权重 50
REASON_EDGE = "edge_conflict"           # 权重 30

# 排序权重（M07 §4.4 确定性规则）
_RANK_WEIGHT = {
    REASON_DELTA_NEW_P0: 100,
    REASON_DELTA_NEW: 90,
    REASON_DELTA_MODIFIED: 80,
    REASON_HISTORY: 50,
    REASON_EDGE: 30,
}


def _fingerprint(*parts: str) -> str:
    """sha256-12 指纹（与 specstd 契约指纹同口径）。"""
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _scenarios_root() -> Path:
    """场景库目录（工作区 scenarios/ 存在则用，否则回退 SpecGuard 仓库 scenarios/）。"""
    try:
        from specstd.workspace import get_workspace_root
        ws = get_workspace_root()
        if ws and (ws / "scenarios").is_dir():
            return ws / "scenarios"
    except Exception:
        pass
    return SG_ROOT / "scenarios"


def _drafts_root() -> Path:
    from specstd.workspace import drafts_dir
    return drafts_dir()


def _load_scenarios() -> list[dict]:
    """加载场景库（covers 清单），逐文件容错。"""
    root = _scenarios_root()
    if not root.is_dir():
        return []
    try:
        from engine.scenario_loader import load_scenarios
        scs = load_scenarios(str(root))
        return [{"id": s.id, "covers": list(s.covers), "module": s.module,
                 "path": s.path} for s in scs]
    except Exception:
        return []


def _load_drafts() -> list[dict]:
    """加载草稿（drafts/*.yaml 解析 id/title/covers/source_delta），逐文件容错。

    T-014：草稿落当前用户私有区（{emp}/drafts/）；聚合时同时扫共享区与
    当前 context 私有区（去重，文件名为 key）。
    """
    import yaml as _yaml
    roots = []
    try:
        roots.append(_drafts_root())          # 当前 context 私有区（无 emp 时即共享区）
        roots.append(_drafts_root_shared())   # 共享区兜底
    except Exception:
        roots = [_drafts_root()]
    drafts, seen = [], set()
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
            if f.name.startswith("_") or f.name in seen:
                continue
            seen.add(f.name)
            try:
                raw = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                # covers 兼容两种形态：doc 内（引擎标准，见 IS-RVT-001.yaml）与顶层（M07 §4.3 草稿示例）
                covers = (raw.get("doc") or {}).get("covers") or raw.get("covers") or []
                drafts.append({
                    "draft_id": f.name,
                    "scenario_id": str(raw.get("id", "") or ""),
                    "title": str(raw.get("title", "") or ""),
                    "covers": [str(c) for c in covers],
                    "source_delta": str(raw.get("source_delta", "") or ""),
                    "source": raw.get("source") or {},
                })
            except Exception:
                continue
    return drafts


def _drafts_root_shared() -> Path:
    """共享区草稿根（emp 为空 → 共享区；与私有区并集读取）。"""
    from specstd.workspace import drafts_dir
    return drafts_dir(emp="")


def _load_anchors() -> dict:
    """当前工作区 FR 锚点（FR ID → AnchorInfo）。"""
    try:
        from specstd.workspace import get_workspace_root
        from specstd.anchors import scan_anchors
        ws = get_workspace_root()
        if not ws:
            return {}
        return scan_anchors(ws)
    except Exception:
        return {}


def _load_delta_manifest() -> dict:
    """changes/{delta}/delta.manifest.yaml 汇总：{fr: op} + P0 标记来源。"""
    result: dict = {}
    try:
        from specstd.workspace import get_workspace_root
        ws = get_workspace_root()
        if not ws:
            return result
        changes_dir = ws / "changes"
        if not changes_dir.is_dir():
            return result
        import yaml as _yaml
        for manifest in sorted(changes_dir.rglob("delta.manifest.yaml")):
            try:
                data = _yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            for op in data.get("operations") or []:
                fr = op.get("fr", "")
                if fr:
                    result[fr] = op.get("op", "")
    except Exception:
        pass
    return result


def _load_p0_decisions() -> set:
    """决策台账 P0 标记（M04 sf_decisions 表 p0 分级）；读不到返回空集。"""
    try:
        import sqlite3
        db = BACKEND_DIR / "data" / "workbench.db"
        if not db.is_file():
            return set()
        conn = sqlite3.connect(str(db), timeout=5)
        try:
            rows = conn.execute(
                "SELECT fr_refs FROM sf_decisions WHERE priority='P0'").fetchall()
        except Exception:
            rows = []
        conn.close()
        p0 = set()
        for (fr_refs,) in rows:
            try:
                for fr in json.loads(fr_refs or "[]"):
                    p0.add(str(fr))
            except Exception:
                continue
        return p0
    except Exception:
        return set()


def compute_coverage(module: str = "") -> dict:
    """三态聚合（M07 §4.1 响应结构）。

    派生：anchors × scenarios covers × drafts → lanes {gap/draft/covered} +
    suggested_order + fingerprint。进程内不缓存（数据量小，直接计算保证新鲜）。
    """
    anchors = _load_anchors()
    scenarios = _load_scenarios()
    drafts = _load_drafts()

    # 场景 covers 反查（FR → 场景列表）
    fr_to_scenarios: dict[str, list[dict]] = {}
    for sc in scenarios:
        for fr in sc["covers"]:
            fr_to_scenarios.setdefault(fr, []).append(sc)

    # 草稿 covers 反查（FR → 草稿列表）
    fr_to_drafts: dict[str, list[dict]] = {}
    for d in drafts:
        for fr in d["covers"]:
            fr_to_drafts.setdefault(fr, []).append(d)

    # 每 FR 归属模块（锚点路径推断）
    fr_module: dict[str, str] = {}
    for fr_id, info in anchors.items():
        m = getattr(info, "module", "")
        feat = getattr(info, "feature", "")
        fr_module[fr_id] = f"{m}/{feat}".strip("/")

    gaps, draft_lane, covered = [], [], []
    p0 = _load_p0_decisions()
    for fr_id, info in sorted(anchors.items()):
        mod = fr_module.get(fr_id, "")
        if module and not (mod == module or mod.startswith(module.rstrip("/") + "/")):
            continue
        name = getattr(info, "title", "") or ""
        scs = fr_to_scenarios.get(fr_id, [])
        dfts = fr_to_drafts.get(fr_id, [])
        if scs:
            covered.append({
                "fr": fr_id, "name": name, "module": mod,
                "scenarios": [s["id"] for s in scs],
            })
        if dfts:
            for d in dfts:
                draft_lane.append({
                    "fr": fr_id, "name": name, "module": mod,
                    "draft_id": d["draft_id"],
                    "scenario_id": d["scenario_id"],
                    "source_delta": d.get("source_delta", ""),
                    "gates": _draft_gates_brief(d["draft_id"]),
                })
        if not scs:
            gaps.append({
                "fr": fr_id, "name": name, "module": mod,
                "reason": _gap_reason(fr_id, p0),
                "source_delta": _gap_source_delta(fr_id, drafts),
            })

    result = {
        "module": module or "all",
        "fr_total": len(anchors),
        "lanes": {"gap": gaps, "draft": draft_lane, "covered": covered},
        "suggested_order": [g["fr"] for g in rank_gaps(gaps)],
        "fingerprint": _fingerprint(
            json.dumps(sorted(anchors.keys()), ensure_ascii=False),
            json.dumps([[s["id"], s["covers"]] for s in scenarios], ensure_ascii=False),
            json.dumps([[d["draft_id"], d["covers"]] for d in drafts], ensure_ascii=False),
        ),
    }
    return result


def _gap_reason(fr_id: str, p0: set = None) -> str:
    """缺口原因（确定性）：delta 新增 → P0 命中 delta_new_p0 / 否则 delta_new；
    修改 → delta_modified；否则 history。"""
    delta_ops = _load_delta_manifest()
    op = delta_ops.get(fr_id, "")
    if op == "add":
        if p0 is None:
            p0 = _load_p0_decisions()
        return REASON_DELTA_NEW_P0 if fr_id in p0 else REASON_DELTA_NEW
    if op == "modify":
        return REASON_DELTA_MODIFIED
    return REASON_HISTORY


def _gap_source_delta(fr_id: str, drafts: list[dict]) -> str:
    """缺口 FR 关联的 source_delta（草稿挂链优先，其次 delta manifest 反向）。"""
    for d in drafts:
        if fr_id in d["covers"] and d.get("source_delta"):
            return d["source_delta"]
    try:
        from specstd.workspace import get_workspace_root
        ws = get_workspace_root()
        if not ws:
            return ""
        import yaml as _yaml
        for manifest in sorted((ws / "changes").rglob("delta.manifest.yaml")):
            data = _yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            ops = data.get("operations") or []
            if any(op.get("fr") == fr_id for op in ops):
                return manifest.parent.name
    except Exception:
        pass
    return ""


def _draft_gates_brief(draft_id: str) -> dict:
    """草稿三闸摘要（读 sg_draft_gates；无登记行 → 全 pending 占位）。"""
    try:
        from services import draft_gates
        g = draft_gates.get_gate(draft_id)
        if g:
            return {"g1": g["gate1_status"], "g2": g["gate2_status"],
                    "g3": g["gate3_status"]}
    except Exception:
        pass
    return {"g1": "pending", "g2": "pending", "g3": "blocked"}


def rank_gaps(gaps: list[dict]) -> list[dict]:
    """缺口优先级确定性排序（M07 §4.4）。

    规则：delta 新增 P0（100）> delta 新增非 P0（90）> delta 修改触及（80）>
    历史缺口（50）> 边界/冲突（30）；同权重按 FR 编号升序（稳定输出）。
    """
    def _key(g: dict):
        fr = g.get("fr", "")
        reason = g.get("reason", REASON_HISTORY)
        weight = _RANK_WEIGHT.get(reason, 50)
        # FR 编号数值化（FR-012 → 12），同权重升序
        num = 0
        try:
            num = int(fr.rsplit("-", 1)[-1])
        except Exception:
            pass
        return (-weight, num, fr)

    return sorted(gaps, key=_key)


def backlink(fr_id: str) -> dict:
    """FR 反向链接（M07 G-6）：场景 / 草稿 / 最近 run / deltas。

    只读派生，不落库不回写任何文件。
    """
    anchors = _load_anchors()
    if fr_id not in anchors:
        return {"fr": fr_id, "exists": False,
                "scenarios": [], "drafts": [], "recent_runs": [], "deltas": []}
    scenarios = [s for s in _load_scenarios() if fr_id in s["covers"]]
    drafts = [d for d in _load_drafts() if fr_id in d["covers"]]
    return {
        "fr": fr_id,
        "exists": True,
        "title": getattr(anchors[fr_id], "title", ""),
        "module": f"{getattr(anchors[fr_id], 'module', '')}/"
                  f"{getattr(anchors[fr_id], 'feature', '')}".strip("/"),
        "scenarios": [{"id": s["id"], "module": s["module"]} for s in scenarios],
        "drafts": [{"draft_id": d["draft_id"], "scenario_id": d["scenario_id"],
                    "source_delta": d.get("source_delta", "")} for d in drafts],
        "recent_runs": _recent_runs_for_fr(fr_id, scenarios),
        "deltas": [_delta_for_fr(fr_id)],
    }


def _recent_runs_for_fr(fr_id: str, scenarios: list[dict]) -> list[dict]:
    """最近执行摘要（数据来自运行台账，M09 呈现层数据源；读不到返回空）。"""
    try:
        from workbench.backend.services import ledger_store
        sid = scenarios[0]["id"] if scenarios else ""
        if not sid:
            return []
        rows = ledger_store.query_scenario_runs(sid, limit=3)
        return [{"run_id": r["run_id"], "verdict": r["verdict"],
                 "finished_at": r.get("finished_at", "")} for r in rows]
    except Exception:
        return []


def _delta_for_fr(fr_id: str) -> str:
    """FR 所属 delta（changes/ 目录反向匹配）。"""
    try:
        from specstd.workspace import get_workspace_root
        ws = get_workspace_root()
        if not ws:
            return ""
        import yaml as _yaml
        for manifest in sorted((ws / "changes").rglob("delta.manifest.yaml")):
            data = _yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            ops = data.get("operations") or []
            if any(op.get("fr") == fr_id for op in ops):
                return manifest.parent.name
    except Exception:
        pass
    return ""


def build_next_batch(frs: list[str], source_delta: str = "") -> dict:
    """「生成下一批」（M07 §5.1 POST /api/coverage/next-batch 的编排核心）。

    圈定 FR 集合 → 逐 FR 生成草稿骨架（确定性模板：id 取号 + covers +
    source_delta 挂链 + 空 flow/verify）→ 全部走 write_draft（三闸通道）。
    **只产草稿不产计划**（铁律 6：计划只能由 delta 导入生成）。

    草稿骨架的 flow/verify 由 Agent（generate-scenario skill）后续填充——
    本函数是确定性编排层，产出可被 Agent/人继续完善。
    """
    from mcp_server.tools.draft_writer import _handle_write_draft

    anchors = _load_anchors()
    drafts = _load_drafts()
    existing_ids = {d["scenario_id"] for d in drafts}
    # 库内已有场景 ID 也占号（防冲突）
    existing_ids |= {s["id"] for s in _load_scenarios()}

    produced, rejected = [], []
    for fr in frs:
        if fr not in anchors:
            rejected.append({"fr": fr, "reason": "锚点不存在"})
            continue
        title = getattr(anchors[fr], "title", "") or fr
        sid = _next_scenario_id(fr, existing_ids)
        content = _draft_skeleton(fr, sid, title, source_delta)
        filename = f"{sid}.yaml"
        try:
            resp = _handle_write_draft({
                "filename": filename, "content": content, "mode": "create"})
            text = resp[0].text if resp else "{}"
        except Exception as e:
            rejected.append({"fr": fr, "reason": f"写入异常: {e}"})
            continue
        try:
            out = json.loads(text)
        except Exception:
            out = {"ok": False, "error": text}
        if out.get("ok"):
            produced.append({"fr": fr, "draft_id": filename, "scenario_id": sid})
            existing_ids.add(sid)
        else:
            rejected.append({"fr": fr, "reason": out.get("error", "写入失败")})

    return {
        "batch_id": _fingerprint(f"{','.join(frs)}|{source_delta}|{len(produced)}"),
        "produced": produced,
        "rejected": rejected,
        "note": "全部产物为草稿态，需走三闸（人工评审→格式校验→发布门禁）后入库；"
                "不产生任何计划（铁律 6）",
    }


def _next_scenario_id(fr_id: str, existing: set) -> str:
    """按 FR 生成场景号（如 FR-012 → IA-VOID-001 语义由 Agent 命名；
    此处确定性生成 {模块缩写}-{FR 序号}-{计数}，保证不撞库内既有 ID。"""
    prefix = "SG"
    try:
        num = int(fr_id.rsplit("-", 1)[-1])
    except Exception:
        num = 0
    for i in range(1, 999):
        sid = f"{prefix}-{num:03d}-{i:03d}"
        if sid not in existing:
            return sid
    return f"{prefix}-{num:03d}-999"


def _draft_skeleton(fr_id: str, sid: str, title: str, source_delta: str) -> str:
    """草稿骨架（格式 2.0 双层 YAML，含挂链字段；flow/verify 由 Agent 填充）。"""
    sd = f"source_delta: {source_delta}\n" if source_delta else ""
    return (
        f"# 生成依据（coverage next-batch）：缺口 FR {fr_id}（确定性编排层产出骨架，"
        f"flow/verify 待 Agent/人工填充）\n"
        f"id: {sid}\n"
        f"title: \"{title}（草稿骨架）\"\n"
        f"{sd}"
        f"source: {{kind: coverage_next_batch}}\n"
        f"doc:\n"
        f"  given: 前置条件待填充\n"
        f"  when: 操作待填充\n"
        f"  then: 预期待填充\n"
        f"  covers: [{fr_id}]\n"
        f"flow: []\n"
        f"verify: []\n"
    )
