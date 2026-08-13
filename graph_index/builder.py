"""graph_index.builder — 图谱索引确定性派生构建器（M11 §6.4）。

源数据（全部只读，绝不回写）：
- specs/{module}/{feature}/spec.md         FR/AC 锚点（specstd.anchors）
- changes/<代号>/delta-spec.md + manifest  delta 节点与 contains 边
- scenarios/（仓库根）                     场景节点 + covers 边 + depends_on 边
- {ws}/.specguard/plans/                   计划节点
- {ws}/.specguard/reports/                 执行报告（run 节点）
- feedback/ledger.json                    SPQ 节点

确定性铁律：同一份源数据两次构建必须得到逐条一致的 nodes/edges（全部排序写入）；
删库重建同图；红线：任何写路径不触碰 specs/scenarios/台账。

source_ref（v1.19 源头定位补强）：fr/ac 节点记录 {file, line_range}，
前端可一键打开源头文件定位到行。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import yaml

from specstd.schema import (
    DIR_SPECS, DIR_CHANGES, FILE_SPEC_MD, FILE_DELTA_SPEC_MD, FILE_MANIFEST,
    FR_HEADING_RE, FR_LIST_RE, AC_RE, DELTA_MARKER_RE,
)
from specstd.anchors import scan_anchors

from graph_index.store import GraphStore

# 场景目录名（仓库根 scenarios/，与 covers_gate / scenario_store 同源）
SCENARIOS_DIR = "scenarios"
# 报告目录（工作区 .specguard/reports/）
REPORTS_SUBDIR = "reports"
PLANS_SUBDIR = "plans"
# 需求侧 delta 兼容目录（.specflow/changes/，S5 落地路径）
SPECFLOW_CHANGES = ".specflow/changes"


# ══════════════════════════════════════════════════════════
# 指纹
# ══════════════════════════════════════════════════════════

def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _file_sha12(path: Path) -> str:
    try:
        return _sha12(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ""


def _dir_snapshot(directory: Path) -> str:
    """目录内容指纹：相对路径 + sha256-12，排序拼接。"""
    if not directory.is_dir():
        return ""
    parts = []
    for p in sorted(directory.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(directory)).replace("\\", "/")
            parts.append(f"{rel}:{_file_sha12(p)}")
    return "|".join(parts)


def compute_source_fingerprint(workspace_root: Path, scenarios_root: Path,
                               sg_root: Path) -> str:
    """计算源数据聚合指纹（specs + changes + 场景库 + SPQ + plans/reports 清单）。

    plans/reports 是运行产物，用文件清单 + mtime 而非内容（报告体量大且非契约源）。
    """
    materials = [
        ("specs", _dir_snapshot(Path(workspace_root) / DIR_SPECS)),
        ("changes", _dir_snapshot(Path(workspace_root) / DIR_CHANGES)),
        ("sf_changes", _dir_snapshot(Path(workspace_root) / SPECFLOW_CHANGES)),
        ("scenarios", _dir_snapshot(Path(scenarios_root))),
        ("spq", _file_sha12(Path(sg_root) / "feedback" / "ledger.json")),
        # 飞书知识图谱一期：共享区事实源（topics/material_links/materials 副本）
        ("feishu", _dir_snapshot(Path(workspace_root) / ".specguard" / "feishu")),
    ]
    for sub in (REPORTS_SUBDIR, PLANS_SUBDIR):
        d = Path(workspace_root) / ".specguard" / sub
        if d.is_dir():
            parts = []
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    rel = str(p.relative_to(d)).replace("\\", "/")
                    parts.append(f"{rel}:{int(p.stat().st_mtime)}")
            materials.append((sub, "|".join(parts)))
        else:
            materials.append((sub, ""))
    raw = "||".join(f"{k}={v}" for k, v in materials)
    return _sha12(raw)


# ══════════════════════════════════════════════════════════
# 锚点行号（source_ref 定位）
# ══════════════════════════════════════════════════════════

def _anchor_line_ranges(text: str) -> dict:
    """提取每个 FR 锚点的行区间 {fr_id: [start_line, end_line]}（1 基，含 AC 段）。

    复用 schema 正则（FR 标题式 + 列表式双形态），逐行扫描保证行号真实；
    行区间 = 锚点行 到 下一个锚点前一行的文本范围（与 sections.py 同口径）。
    """
    lines = text.splitlines()
    matches: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = FR_HEADING_RE.match(line) or FR_LIST_RE.match(line)
        if m:
            matches.append((i, m.group(1)))
        # 列表式锚点的 AC 常在同一定义行内（- **FR-x**：… AC-001），
        # 行区间仍按「锚点行 → 下一锚点前一行」计算，前端打开即定位。
    ranges: dict = {}
    for idx, (line_no, fr_id) in enumerate(matches):
        end = matches[idx + 1][0] - 1 if idx + 1 < len(matches) else len(lines) - 1
        ranges[fr_id] = [line_no + 1, end + 1]
    return ranges


def _covers_line_range(text: str) -> Optional[list]:
    """场景 YAML 中 doc.covers 所在行区间（用于 scenario 节点 source_ref 定位）。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*covers\s*:", line):
            return [i + 1, i + 1]
    return None


# ══════════════════════════════════════════════════════════
# 源数据解析
# ══════════════════════════════════════════════════════════

def _parse_scenario_yaml(path: Path) -> Optional[dict]:
    """解析场景 YAML（doc.covers / depends_on / title）。损坏文件跳过（与 scenario_store 一致）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    return raw


def _build_lineage_nodes(store: "GraphStore", anchors: dict, db_path: Optional[Path]):
    """从 workbench.db 派生 interview/decision/external_ref 节点与谱系边。

    源数据：sf_interviews / sf_decisions + sf_decision_links / sf_external_refs。
    DB 不可用（路径缺失/表缺失）时静默跳过——索引仍可构建（红线：可删可重建）。
    """
    if db_path is None or not Path(db_path).is_file():
        return
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception:
        return
    try:
        # 面试节点（IV-xxx，阶段 req）
        interviews = {}
        try:
            rows = conn.execute(
                "SELECT iv_id, title, target_delta FROM sf_interviews ORDER BY iv_id").fetchall()
        except Exception:
            rows = []
        for r in rows:
            iv_id = r["iv_id"]
            interviews[iv_id] = r
            store.upsert_node(id=iv_id, node_type="interview",
                              title=str(r["title"] or iv_id))

        # 决策节点（D-xxx，阶段 req）+ produces/decides 边
        decisions = {}
        try:
            rows = conn.execute(
                "SELECT id, interview_id, priority, question, status"
                " FROM sf_decisions ORDER BY id").fetchall()
        except Exception:
            rows = []
        for r in rows:
            did = r["id"]
            decisions[did] = r
            store.upsert_node(id=did, node_type="decision",
                              title=str(r["question"] or did)[:80],
                              attrs={"priority": r["priority"],
                                     "status": r["status"]})
            iv_id = r["interview_id"]
            if iv_id in interviews:
                store.upsert_edge(src=iv_id, dst=did, edge_type="produces")
        # 决策链接（fr_anchor → decides 边；delta → produces 边）
        try:
            links = conn.execute(
                "SELECT decision_id, link_type, link_ref FROM sf_decision_links"
                " ORDER BY decision_id, link_type, link_ref").fetchall()
        except Exception:
            links = []
        for l in links:
            did = l["decision_id"]
            if did not in decisions:
                continue
            if l["link_type"] == "fr_anchor" and l["link_ref"] in anchors:
                store.upsert_edge(src=did, dst=l["link_ref"], edge_type="decides")
            elif l["link_type"] == "delta":
                store.upsert_edge(src=did, dst=l["link_ref"], edge_type="produces")

        # 外部锚点节点（stage dev_ext）+ references 边
        try:
            rows = conn.execute(
                "SELECT type, ref, ref_url, linked_type, linked FROM sf_external_refs"
                " ORDER BY type, ref, linked_type, linked").fetchall()
        except Exception:
            rows = []
        for r in rows:
            ref_id = f"{r['type']}:{r['ref']}"
            attrs = {}
            if r["ref_url"]:
                attrs["url"] = r["ref_url"]
            store.upsert_node(id=ref_id, node_type="external_ref",
                              title=str(r["ref"]), attrs=attrs)
            if r["linked_type"] == "fr" and r["linked"] in anchors:
                store.upsert_edge(src=ref_id, dst=r["linked"], edge_type="references")
            elif r["linked_type"] == "delta":
                store.upsert_edge(src=ref_id, dst=r["linked"], edge_type="references")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _scan_delta_dirs(workspace_root: Path) -> list[Path]:
    """扫描 delta 目录（工作区 changes/ 优先，兼容 .specflow/changes/）。"""
    dirs: list[Path] = []
    for base in (Path(workspace_root) / DIR_CHANGES,
                 Path(workspace_root) / SPECFLOW_CHANGES):
        if base.is_dir():
            dirs.extend(sorted(base.iterdir()))
    seen: set = set()
    result = []
    for d in dirs:
        if d.is_dir() and d.name not in seen:
            seen.add(d.name)
            result.append(d)
    return result


def _delta_contains_frs(delta_dir: Path) -> list[str]:
    """delta 覆盖的 FR 清单（delta-spec [delta:代号] 标记 或 manifest operations.anchor）。"""
    frs: list[str] = []
    spec_path = delta_dir / FILE_DELTA_SPEC_MD
    if spec_path.is_file():
        try:
            text = spec_path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        for m in FR_HEADING_RE.finditer(text):
            frs.append(m.group(1))
        for m in FR_LIST_RE.finditer(text):
            frs.append(m.group(1))
        # 列表式锚点行内的 delta 标记（- **FR-x**：… [delta:代号]）
        if not frs:
            frs = list({m.group(1) for m in DELTA_MARKER_RE.finditer(text)})
    manifest_path = delta_dir / FILE_MANIFEST
    if manifest_path.is_file():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}
            for op in manifest.get("operations") or []:
                anchor = op.get("anchor", "")
                if anchor and anchor not in frs:
                    frs.append(anchor)
        except Exception:
            pass
    return sorted(set(frs))


# ══════════════════════════════════════════════════════════
# 飞书材料派生段（飞书知识图谱一期）
# ══════════════════════════════════════════════════════════

def _topic_line_ranges(text: str) -> dict:
    """topics.yaml 每个话题的行区间（- id: tp:xxx 行 → 下一话题前一行，1 基）。"""
    lines = text.splitlines()
    matches: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s*-\s*id:\s*(\S+)\s*$", line)
        if m:
            matches.append((i, m.group(1)))
    ranges: dict = {}
    for idx, (line_no, tid) in enumerate(matches):
        end = matches[idx + 1][0] - 1 if idx + 1 < len(matches) else len(lines) - 1
        ranges[tid] = [line_no + 1, end + 1]
    return ranges


def _build_feishu_nodes(store: "GraphStore", workspace_root: Path):
    """飞书材料派生段（共享区事实源 → 节点/边；只读，绝不回写）。

    源数据：{ws}/.specguard/feishu/
    - materials/fd-*.md / fm-*.json → feishu_doc / feishu_minutes 节点
    - topics.yaml → topic 节点
    - material_links.yaml（仅 status=confirmed）→ mentions 边（src/dst 均须已存在）
    """
    from specflow.feishu_pool.paths import shared_dirs
    workspace_root = Path(workspace_root)
    shared = shared_dirs(workspace_root)
    if not shared["root"].is_dir():
        return

    # 1. 材料节点（fd/fm，扫描共享区 materials/ 副本）
    mat_dir = shared["materials"]
    if mat_dir.is_dir():
        for f in sorted(mat_dir.iterdir()):
            if not f.is_file():
                continue
            if f.suffix == ".md" and f.stem.startswith("fd-"):
                node_id, ntype = f"fd:{f.stem[3:]}", "feishu_doc"
            elif f.suffix == ".json" and f.stem.startswith("fm-"):
                node_id, ntype = f"fm:{f.stem[3:]}", "feishu_minutes"
            else:
                continue
            rel = str(f.relative_to(workspace_root)).replace("\\", "/")
            store.upsert_node(
                id=node_id, node_type=ntype, title=f.stem,
                attrs={"sha": _file_sha12(f)},
                source_ref={"file": rel, "line_range": [1, 1]},
                commit=False)

    # 2. 话题节点（topics.yaml 全量条目）
    topics_yaml = shared["topics_yaml"]
    if topics_yaml.is_file():
        try:
            text = topics_yaml.read_text(encoding="utf-8")
            raw = yaml.safe_load(text) or {}
        except Exception:
            text, raw = "", {}
        ranges = _topic_line_ranges(text)
        rel = str(topics_yaml.relative_to(workspace_root)).replace("\\", "/")
        for t in raw.get("topics") or []:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id", ""))
            if not tid:
                continue
            store.upsert_node(
                id=tid, node_type="topic", title=str(t.get("title") or tid),
                attrs={"summary": str(t.get("summary") or ""),
                       "message_count": int(t.get("message_count") or 0),
                       "window": t.get("window") or [],
                       "participants_count": int(t.get("participants_count") or 0)},
                source_ref={"file": rel, "line_range": ranges.get(tid, [1, 1])},
                commit=False)

    # 3. mentions 边（仅 confirmed；src/dst 均须已存在，断链不建边）
    links_yaml = shared["links_yaml"]
    if links_yaml.is_file():
        try:
            raw = yaml.safe_load(links_yaml.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
        for l in raw.get("links") or []:
            if not isinstance(l, dict) or l.get("status") != "confirmed":
                continue
            src, dst = str(l.get("src", "")), str(l.get("dst", ""))
            if not src or not dst:
                continue
            if store.get_node(src) is None or store.get_node(dst) is None:
                continue
            store.upsert_edge(
                src=src, dst=dst, edge_type="mentions",
                attrs={"confidence": l.get("confidence", 0),
                       "evidence": str(l.get("evidence") or ""),
                       "confirmed_by": str(l.get("confirmed_by") or ""),
                       "confirmed_at": str(l.get("confirmed_at") or "")},
                commit=False)


# ══════════════════════════════════════════════════════════
# 构建主流程
# ══════════════════════════════════════════════════════════

def build_index(workspace_root: Path, index_path: Path,
                scenarios_root: Optional[Path] = None,
                sg_root: Optional[Path] = None,
                db_path: Optional[Path] = None) -> dict:
    """确定性构建图谱索引。

    Args:
        workspace_root: 工作区根（specs/changes/.specguard 所在）
        index_path: 索引库落点（{ws}/.specguard/graph_index.db）
        scenarios_root: 场景库根（默认 {SG_ROOT}/scenarios）
        sg_root: SpecGuard 仓库根（默认 workspace_root 的上级推断）
        db_path: workbench.db（sf_interviews/sf_decisions/sf_external_refs，
                 T-073 血缘链挂链数据；None 时跳过 DB 派生）

    Returns:
        {nodes, edges, source_fingerprint, built_at} 统计
    """
    workspace_root = Path(workspace_root)
    if sg_root is None:
        sg_root = Path(__file__).resolve().parent.parent
    sg_root = Path(sg_root)
    scenarios_root = Path(scenarios_root) if scenarios_root else sg_root / SCENARIOS_DIR

    store = GraphStore(index_path)
    try:
        # BEGIN EXCLUSIVE：整个构建在单事务内完成，提交前其他连接不可见（配合 WAL 模式），
        # 杜绝清空后读到部分数据的并发窗口（M-01 修复）
        store.conn.execute("BEGIN IMMEDIATE")
        store.clear_all(commit=False)

        # ── 1. module / feature / fr / ac 节点（specs 锚点）──
        anchors = scan_anchors(workspace_root)
        modules: set[str] = set()
        features: set[str] = set()
        fr_lines = {}
        for spec_md in sorted((Path(workspace_root) / DIR_SPECS).rglob(FILE_SPEC_MD)):
            try:
                text = spec_md.read_text(encoding="utf-8")
            except Exception:
                continue
            fr_lines.update(_anchor_line_ranges(text))

        for fr_id, info in sorted(anchors.items()):
            module = info.module
            feature = info.feature
            if module:
                modules.add(module)
            if module and feature:
                features.add(f"{module}/{feature}")
            source_ref = None
            if info.file_path:
                rel = info.file_path.replace("\\", "/")
                line_range = fr_lines.get(fr_id)
                source_ref = {"file": rel, "line_range": line_range or [1, 1]}
            store.upsert_node(
                id=fr_id, node_type="fr", title=info.title,
                module=module, feature=feature,
                attrs={"cov": "ok" if info.ac_ids else "gap"},
                source_ref=source_ref,
                commit=False,
            )
            for ac_id in sorted(info.ac_ids):
                store.upsert_node(
                    id=ac_id, node_type="ac", title=f"{fr_id} 验收标准 {ac_id}",
                    module=module, feature=feature,
                    source_ref={"file": rel, "line_range": line_range or [1, 1]},
                    commit=False,
                )
                store.upsert_edge(src=fr_id, dst=ac_id, edge_type="contains",
                                  commit=False)

        for module in sorted(modules):
            store.upsert_node(id=f"mod:{module}", node_type="module",
                              title=module, module=module, feature="",
                              commit=False)
        for feature in sorted(features):
            module = feature.split("/", 1)[0]
            store.upsert_node(id=f"feat:{feature}", node_type="feature",
                              title=feature.split("/", 1)[1], module=module, feature=feature,
                              commit=False)
            store.upsert_edge(src=f"mod:{module}", dst=f"feat:{feature}",
                              edge_type="contains", commit=False)

        # ── 2. 场景节点 + covers/depends_on 边（两遍扫描：先收集全集再建边，
        #    保证 depends_on 指向的场景无论扫描先后都存在）──
        scenarios = {}
        for yaml_file in sorted(scenarios_root.rglob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue
            raw = _parse_scenario_yaml(yaml_file)
            if raw is None:
                continue
            sid = str(raw["id"])
            scenarios[sid] = yaml_file
        for sid, yaml_file in sorted(scenarios.items()):
            raw = _parse_scenario_yaml(yaml_file)
            doc = raw.get("doc") or {}
            covers = sorted({str(c) for c in (doc.get("covers") or [])})
            deps = []
            for d in raw.get("depends_on") or []:
                if isinstance(d, str):
                    deps.append(d)
                elif isinstance(d, dict) and d.get("id"):
                    deps.append(str(d["id"]))
            deps = sorted(set(deps))
            try:
                text = yaml_file.read_text(encoding="utf-8")
            except Exception:
                text = ""
            line_range = _covers_line_range(text)
            # 场景模块归属：scenarios/{module}/... 一级目录（与 _suite.yaml 模块划分一致）
            rel_parts = yaml_file.relative_to(scenarios_root).parts
            sc_module = rel_parts[0] if len(rel_parts) > 1 else ""
            # source_delta（M07 挂链字段，BL-02 断链规则依据）
            source_delta = str(raw.get("source_delta") or "")
            store.upsert_node(
                id=sid, node_type="scenario",
                title=str(raw.get("title") or ""),
                module=sc_module,
                attrs={"covers": covers, "depends_on": deps,
                       "source_delta": source_delta},
                source_ref={"file": str(yaml_file.relative_to(sg_root)).replace("\\", "/"),
                            "line_range": line_range or [1, 1]},
                commit=False,
            )
            for fr_id in covers:
                if fr_id in anchors:
                    store.upsert_edge(src=sid, dst=fr_id, edge_type="covers",
                                      commit=False)
            for dep in deps:
                if dep in scenarios:
                    store.upsert_edge(src=sid, dst=dep, edge_type="depends_on",
                                      commit=False)

        # ── 3. delta 节点 + contains 边 ──
        for delta_dir in _scan_delta_dirs(workspace_root):
            frs = _delta_contains_frs(delta_dir)
            store.upsert_node(
                id=delta_dir.name, node_type="delta",
                title=delta_dir.name,
                source_ref={"file": str(delta_dir.relative_to(workspace_root)).replace("\\", "/"),
                            "line_range": [1, 1]},
                commit=False,
            )
            for fr_id in frs:
                if fr_id in anchors:
                    store.upsert_edge(src=delta_dir.name, dst=fr_id, edge_type="contains",
                                      commit=False)

        # ── 3.5 血缘链挂链数据（T-073）：面试/决策/外部锚点（workbench.db）──
        _build_lineage_nodes(store, anchors, db_path)

        # ── 4. plan 节点 ──
        plans_dir = Path(workspace_root) / ".specguard" / PLANS_SUBDIR
        if plans_dir.is_dir():
            for plan_file in sorted(plans_dir.glob("*.yaml")):
                raw = _parse_scenario_yaml(plan_file)
                plan_id = raw.get("id") if raw else ""
                title = raw.get("title") if raw else plan_file.stem
                if plan_id:
                    scenarios_list = sorted({str(s) for s in (raw.get("scenarios") or [])})
                    store.upsert_node(
                        id=f"plan:{plan_id}", node_type="plan",
                        title=str(title),
                        source_ref={"file": str(plan_file.relative_to(workspace_root))
                                    .replace("\\", "/"), "line_range": [1, 1]},
                        commit=False,
                    )
                    for sid in scenarios_list:
                        if sid in scenarios:
                            store.upsert_edge(src=f"plan:{plan_id}", dst=sid,
                                              edge_type="schedules", commit=False)

        # ── 5. run 节点（reports 归档目录）──
        reports_dir = Path(workspace_root) / ".specguard" / REPORTS_SUBDIR
        if reports_dir.is_dir():
            for run_dir in sorted(reports_dir.iterdir()):
                if not run_dir.is_dir() or run_dir.name.startswith("."):
                    continue
                run_id = run_dir.name
                plan_id = ""
                trigger = run_dir / "trigger.json"
                if trigger.is_file():
                    try:
                        with open(trigger, "r", encoding="utf-8") as f:
                            plan_id = str((json.load(f) or {}).get("plan_id") or "")
                    except Exception:
                        pass
                store.upsert_node(
                    id=f"run:{run_id}", node_type="run",
                    title=run_id,
                    source_ref={"file": str(run_dir.relative_to(workspace_root))
                                .replace("\\", "/"), "line_range": [1, 1]},
                    commit=False,
                )
                if plan_id:
                    store.upsert_edge(src=f"run:{run_id}", dst=f"plan:{plan_id}",
                                      edge_type="executes", commit=False)

        # ── 6. SPQ 节点 ──
        ledger_path = Path(sg_root) / "feedback" / "ledger.json"
        if ledger_path.is_file():
            try:
                with open(ledger_path, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except Exception:
                entries = []
            for entry in entries if isinstance(entries, list) else []:
                spq_id = entry.get("spq_id", "")
                if not spq_id:
                    continue
                store.upsert_node(
                    id=spq_id, node_type="spq",
                    title=str(entry.get("title") or ""),
                    attrs={"status": str(entry.get("status") or ""),
                           "scenario_id": str(entry.get("scenario_id") or "")},
                    commit=False,
                )
                sid = str(entry.get("scenario_id") or "")
                if sid in scenarios:
                    store.upsert_edge(src=spq_id, dst=sid, edge_type="feedback",
                                      commit=False)

        # ── 6.5 飞书材料（飞书知识图谱一期：共享区事实源派生）──
        _build_feishu_nodes(store, workspace_root)

        # ── 7. 指纹落库 + 提交事务 ──
        fingerprint = compute_source_fingerprint(workspace_root, scenarios_root, sg_root)
        store.set_meta("source_fingerprint", fingerprint, commit=False)
        store.set_meta("built_at", __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                       commit=False)
        store.set_meta("workspace", workspace_root.name, commit=False)
        store.conn.commit()

        return {
            "nodes": store.count_nodes(),
            "edges": store.count_edges(),
            "source_fingerprint": fingerprint,
            "built_at": store.get_meta("built_at"),
        }
    except BaseException:
        store.conn.rollback()
        raise
    finally:
        store.close()
