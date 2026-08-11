"""open/dev_context.py — 研发侧 dev-context-pack 装配（M13 §6.3，T-085 旗舰场景群）。

三入口（side_effect 全部 none）：
  dev_context_by_zt_ref  场景 A 接需求 / 场景 C 修 BUG：sf_external_refs 反查 → 冻结版 pack
  dev_context_by_anchor  场景 B 开发接口：graph_index 锚点反查 → pack 附血缘上下游（改前知震感）
  dev_context_by_fr      精准取版：FR + 可选 delta 版本（默认当前冻结版）

DevContextPack 六分区：
  identity            聚合指纹/冻结版本/delta 号/装配时间（消费端可校验是否仍是当前版）
  spec_excerpt        SHALL 条款/FR 段落（只读冻结态）
  acceptance          AC 锚点
  scenarios           覆盖场景 Gherkin（doc 层）
  data_contracts      数据约定（save/verify 摘要）+ DAG 依赖位置
  lineage_decisions   血缘上下游 + D-xxx/amendment

三红线（铁律 2/4）：
  ① 只读冻结态——草稿物理不可达（不触碰 drafts/）；未冻结 delta 返回不可达
  ② 研发无写通道——本模块无任何写参数，反馈走禅道/SPQ 人工通道
  ③ pack 是带聚合指纹的快照而非订阅——消费端可校验是否仍是当前版
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mcp.types import Tool, TextContent

from mcp_server.tools.open import (
    resolve_workspace_root, delta_dir, delta_dirs, is_frozen, open_graph, read_text,
)
from specstd.schema import FR_HEADING_RE, FR_LIST_RE, AC_RE


def _render(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False,
                                                     indent=2, default=str))]


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

dev_context_by_zt_ref_tool = Tool(
    name="dev_context_by_zt_ref",
    description="研发开工取包（场景 A 接需求 / C 修 BUG）：从禅道故事/BUG 号拿到六分区"
                "dev-context-pack（需求→锚点→delta→影响面→图谱→报告），带聚合指纹。"
                "只读冻结态，草稿零泄漏。",
    inputSchema={
        "type": "object",
        "properties": {
            "ref_type": {"type": "string", "enum": ["zt_story", "zt_bug"],
                         "description": "外部资产类型（默认 zt_story）"},
            "ref_id": {"type": "string",
                       "description": "外部编号（ZT-STORY-4821 或 4821）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["ref_id"],
    },
)

dev_context_by_anchor_tool = Tool(
    name="dev_context_by_anchor",
    description="开发接口取包（场景 B）：按锚点（FR-xxx / 场景 ID）取六分区"
                "dev-context-pack——spec 段落/AC/覆盖场景/数据约定/血缘上下游（改前知震感）。",
    inputSchema={
        "type": "object",
        "properties": {
            "anchor": {"type": "string", "description": "锚点（FR-xxx / 场景 ID）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["anchor"],
    },
)

dev_context_by_fr_tool = Tool(
    name="dev_context_by_fr",
    description="按 FR 精准取版（场景 B 变体）：FR-xxx + 可选 delta 代号（默认当前冻结版）。"
                "指定 delta 时读该 delta 的冻结段（未冻结不可达）。",
    inputSchema={
        "type": "object",
        "properties": {
            "fr_id": {"type": "string", "description": "FR 锚点（如 FR-012）"},
            "delta_id": {"type": "string", "description": "可选：delta 代号（精准取版）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["fr_id"],
    },
)

TOOLS = [dev_context_by_zt_ref_tool, dev_context_by_anchor_tool, dev_context_by_fr_tool]


# ══════════════════════════════════════════════════════════
# 只读数据源辅助
# ══════════════════════════════════════════════════════════

def _fr_excerpt(text: str, fr_id: str) -> str:
    """从 spec 文本提取 FR 锚点段落（锚点行 → 下一锚点前，含 AC 行）。"""
    lines = text.splitlines()
    matches: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = FR_HEADING_RE.match(line) or FR_LIST_RE.match(line)
        if m:
            matches.append((i, m.group(1)))
    for idx, (line_no, fid) in enumerate(matches):
        if fid == fr_id:
            end = matches[idx + 1][0] - 1 if idx + 1 < len(matches) else len(lines) - 1
            return "\n".join(lines[line_no:end + 1])
    return ""


def _find_fr_in_specs(root: Path, fr_id: str) -> dict:
    """在基线 specs/ 中定位 FR：{file, module, feature, text, ac_ids}。"""
    from specstd.anchors import scan_anchors
    info = scan_anchors(root).get(fr_id)
    if info is None:
        return {}
    path = Path(info.file_path)
    return {
        "file": str(path).replace("\\", "/"),
        "module": info.module,
        "feature": info.feature,
        "text": _fr_excerpt(read_text(path), fr_id),
        "ac_ids": sorted(info.ac_ids),
    }


def _shall_clauses(text: str, limit: int = 20) -> list[str]:
    """SHALL 强制条款行（去重、截断）。"""
    seen: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if "SHALL" in s.upper() and s and s not in seen:
            seen.append(s)
        if len(seen) >= limit:
            break
    return seen


def _load_manifest(delta_path) -> dict:
    import yaml
    p = delta_path / "delta.manifest.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _resolve_source_file(rel_file: str, ws_root: Path, sg_root: Path) -> Path:
    """解析图谱 source_ref 文件：工作区根优先，回退 SpecGuard 仓库根/场景库。"""
    for base in (ws_root, sg_root, sg_root / "scenarios"):
        p = base / rel_file
        if p.is_file():
            return p
    return Path(sg_root) / rel_file


def _scenario_docs(scenario_ids: list[str], store, ws_root: Path, sg_root: Path) -> list[dict]:
    """读覆盖场景 doc 层（Gherkin 人读层）+ depends_on（图谱节点 attrs 兜底）。"""
    import yaml
    out: list[dict] = []
    for sid in sorted(scenario_ids):
        node = store.get_node(sid)
        if node is None:
            continue
        source_ref = node.get("source_ref") or {}
        rel_file = (source_ref.get("file") or "").replace("\\", "/")
        doc_text = ""
        if rel_file:
            path = _resolve_source_file(rel_file, ws_root, sg_root)
            if path.is_file():
                doc_text = read_text(path)
        raw = {}
        try:
            raw = yaml.safe_load(doc_text) or {}
        except Exception:
            pass
        doc = raw.get("doc") or {}
        attrs = node.get("attrs") or {}
        out.append({
            "scenario_id": sid,
            "title": raw.get("title") or node.get("title") or "",
            "module": node.get("module", ""),
            "given": doc.get("given", ""),
            "when": doc.get("when", ""),
            "then": doc.get("then", ""),
            "covers": attrs.get("covers") or [],
            "depends_on": attrs.get("depends_on") or [],
            "source_file": rel_file or "",
        })
    return out


def _data_contracts(scenario_ids: list[str], store, ws_root: Path, sg_root: Path) -> list[dict]:
    """数据约定：flow call 摘要（method+path+save）+ verify 断言摘要 + DAG 依赖位置。"""
    import yaml
    out: list[dict] = []
    for sid in sorted(scenario_ids):
        node = store.get_node(sid)
        if node is None:
            continue
        source_ref = node.get("source_ref") or {}
        rel_file = (source_ref.get("file") or "").replace("\\", "/")
        raw = {}
        if rel_file:
            path = _resolve_source_file(rel_file, ws_root, sg_root)
            if path.is_file():
                try:
                    raw = yaml.safe_load(read_text(path)) or {}
                except Exception:
                    pass
        calls: list[dict] = []
        for step in raw.get("flow") or []:
            if isinstance(step, dict) and "call" in step:
                call = step["call"]
                calls.append({
                    "method": call.get("method", ""),
                    "path": call.get("path", ""),
                    "save": call.get("save", ""),
                })
        asserts: list[dict] = []
        for v in raw.get("verify") or []:
            if not isinstance(v, dict):
                continue
            if "json" in v:
                j = v["json"]
                asserts.append({"type": "json", "of": j.get("of", ""),
                                "path": j.get("path", ""),
                                "expect": (j.get("eq") if "eq" in j else
                                           ("not_null" if j.get("not_null") else ""))})
            elif "status" in v:
                s = v["status"]
                asserts.append({"type": "status", "of": s.get("of", ""),
                                "expect": s.get("eq", "")})
        out.append({
            "scenario_id": sid,
            "calls": calls,
            "verify_asserts": asserts,
            "depends_on": raw.get("depends_on") or [],
            "batch_hint": f"依赖 {len(raw.get('depends_on') or [])} 个上游场景（DAG 位置）"
                          if raw.get("depends_on") else "无上游依赖（可并行）",
        })
    return out


def _decisions_for_refs(biz_refs: list[str], workspace: str) -> list[dict]:
    """按 FR/delta 反查决策 + amendment 链（复用 specflow_refs 查询面）。"""
    from mcp_server.tools.open.specflow_refs import _list_decisions
    merged: dict = {}
    for ref in biz_refs:
        if not ref:
            continue
        for d in _list_decisions(biz_ref=ref, workspace=workspace):
            merged[d["id"]] = d
    return sorted(merged.values(), key=lambda x: x["id"])


def _trace_both(store, node_id: str) -> dict:
    """谱系上下游投影（只读存量索引；节点不存在时返回空）。"""
    from graph_index.service import trace
    result = {"upstream": [], "downstream": []}
    for direction, key in (("up", "upstream"), ("down", "downstream")):
        try:
            t = trace(store, node_id, direction=direction, max_depth=6)
            result[key] = [{"id": p["id"], "type": p["type"], "title": p["title"]}
                           for p in t["path"]]
        except KeyError:
            result[key] = []
    return result


def _freeze_version(root: Path, delta_id: str) -> dict:
    """delta 冻结版本信息（FREEZE.yaml 凭证，纯读）。"""
    import yaml
    d = delta_dir(root, delta_id)
    if d is None or not is_frozen(d):
        return {}
    try:
        data = yaml.safe_load((d / "FREEZE.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return {"delta_id": delta_id,
            "frozen_at": data.get("frozen_at", ""),
            "spec_sha": data.get("spec_sha", ""),
            "interview_id": data.get("interview_id", "")}


def _frozen_delta_for_fr(root: Path, fr_id: str) -> str:
    """当前冻结版发现：在已冻结 delta 中找包含该 FR 的最新一个（确定性：delta 名序）。

    默认取版语义（M13 §6.3）：未指定 delta 时返回当前冻结版。
    草稿/未冻结 delta 一律不参与（只读冻结态）。
    """
    from specflow.delta.manifest import load_manifest as _lm
    for d in delta_dirs(root):
        if not is_frozen(d):
            continue
        m = _lm(str(d / "delta.manifest.yaml"))
        ops = m.operations if m else []
        anchors = {op.get("anchor", "") for op in ops} | {op.get("fr", "") for op in ops}
        if fr_id in anchors:
            return d.name
        # delta-spec.md 锚点兜底
        spec = d / "delta-spec.md"
        if spec.is_file() and fr_id in read_text(spec):
            return d.name
    return ""


# ══════════════════════════════════════════════════════════
# 六分区装配核心
# ══════════════════════════════════════════════════════════

def _assemble_pack(*, ws_name: str, root: Path, ref: str, fr_id: str = "",
                   delta_id: str = "", sg_root: Path = None) -> dict:
    """装配 dev-context-pack 六分区（只读冻结态，草稿物理不可达）。

    从基线 specs/ + 冻结 changes/ + 场景库 + workbench.db 台账确定性派生。
    分区内容先构造，聚合指纹最后计算（identity.fingerprint 覆盖全包内容）。
    """
    from specstd.workspace import SG_ROOT as _SG
    sg_root = sg_root or _SG

    # ── 1. spec_excerpt + acceptance（基线段落 + delta 冻结段）──
    fr_info = _find_fr_in_specs(root, fr_id) if fr_id else {}
    # 默认取版：未指定 delta 时自动发现当前冻结版（只读冻结态）
    if not delta_id and fr_id:
        delta_id = _frozen_delta_for_fr(root, fr_id)
    excerpt_parts: list[str] = []
    if fr_info.get("text"):
        excerpt_parts.append(f"### {fr_id}（基线 {fr_info.get('module')}/{fr_info.get('feature')}）\n"
                             f"{fr_info['text']}")
    delta_fr_text = ""
    if delta_id:
        d = delta_dir(root, delta_id)
        if d is not None and is_frozen(d):
            delta_spec = read_text(d / "delta-spec.md") if (d / "delta-spec.md").is_file() else ""
            delta_fr_text = _fr_excerpt(delta_spec, fr_id)
            if delta_fr_text:
                excerpt_parts.append(f"### {fr_id}（delta {delta_id} 冻结段）\n{delta_fr_text}")
    spec_excerpt = {
        "fr_id": fr_id,
        "excerpt": "\n\n".join(excerpt_parts),
        "shall_clauses": _shall_clauses("\n".join(excerpt_parts)),
        "source_files": ([fr_info["file"]] if fr_info else [])
                        + ([str((delta_dir(root, delta_id) / "delta-spec.md")).replace("\\", "/")]
                           if delta_id and delta_dir(root, delta_id) else []),
    }

    acceptance = {
        "fr_id": fr_id,
        "ac_ids": fr_info.get("ac_ids") or [],
        "ac_lines": [ln.strip() for ln in (fr_info.get("text") or "").splitlines()
                     if AC_RE.search(ln)][:20],
    }

    # ── 2. scenarios + data_contracts（graph covers 边反查覆盖场景）──
    store, st = open_graph(root)
    scenario_ids: list[str] = []
    lineage = {"upstream": [], "downstream": []}
    decisions: list[dict] = []
    scenarios: list[dict] = []
    data_contracts: list[dict] = []
    if store is not None:
        try:
            if fr_id:
                edges = store.list_edges(edge_type="covers")
                scenario_ids = sorted({e["src"] for e in edges if e["dst"] == fr_id})
            lineage = _trace_both(store, fr_id or (scenario_ids[0] if scenario_ids else ""))
            scenarios = _scenario_docs(scenario_ids, store, root, sg_root)
            data_contracts = _data_contracts(scenario_ids, store, root, sg_root)
        except Exception:
            pass
        finally:
            store.close()
    else:
        lineage = {"upstream": [], "downstream": [], "index_unavailable": True}

    # ── 3. lineage_decisions（D-xxx + amendment，经 sf_decision_links 反查）──
    biz_refs = [fr_id] if fr_id else []
    if delta_id:
        biz_refs.append(delta_id)
    decisions = _decisions_for_refs(biz_refs, ws_name)

    # ── 4. identity（聚合指纹最后计算）──
    body = {
        "spec_excerpt": spec_excerpt,
        "acceptance": acceptance,
        "scenarios": scenarios,
        "data_contracts": data_contracts,
        "lineage_decisions": {"upstream": lineage.get("upstream", []),
                              "downstream": lineage.get("downstream", []),
                              "decisions": decisions},
    }
    fingerprint = _sha12(json.dumps(body, ensure_ascii=False, sort_keys=True))
    pack = {
        "identity": {
            "pack_type": "dev-context-pack",
            "ref": ref,
            "fr_id": fr_id,
            "delta_id": delta_id,
            "workspace": ws_name,
            "frozen_version": _freeze_version(root, delta_id) if delta_id else {},
            "index_stale": bool(st.get("stale")) if store is not None else None,
            "assembled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprint": fingerprint,
            "verify_hint": "消费端可重拉本工具比对 identity.fingerprint，校验是否仍是当前版",
        },
        **body,
    }
    return pack


def _handle_dev_context_by_zt_ref(args: dict) -> list[TextContent]:
    ref_type = str(args.get("ref_type") or "zt_story").strip()
    ref_id = str(args.get("ref_id") or "").strip()
    if ref_type not in ("zt_story", "zt_bug"):
        return _render({"ok": False, "error": "ref_type 仅支持 zt_story/zt_bug"})
    if not ref_id:
        return _render({"ok": False, "error": "ref_id 必填（ZT-STORY-4821 或 4821）"})
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})

    # ref 归一化（前缀补全）
    prefix = {"zt_story": "ZT-STORY", "zt_bug": "ZT-BUG"}[ref_type]
    candidates = [ref_id]
    if ref_id.upper().startswith(prefix + "-"):
        candidates.append(ref_id[len(prefix) + 1:])
    else:
        candidates.append(f"{prefix}-{ref_id}")

    from workbench.backend.services.specflow import sf_refs_store
    rows = []
    seen: set = set()
    for cand in candidates:
        for r in sf_refs_store.list_refs(workspace=ws_name, ref_type=ref_type, ref=cand):
            key = (r.get("linked_type"), r.get("linked"))
            if key not in seen:
                seen.add(key)
                rows.append(r)
    if not rows:
        return _render({"ok": False, "error": f"{ref_type}:{ref_id} 未登记"
                        "（sf_external_refs 无记录，请先在禅道面板建故事/提单完成挂链）"})

    # linked 解析：delta 优先，其次 fr_anchor
    delta_id, fr_id = "", ""
    for r in rows:
        if r.get("linked_type") == "delta" and not delta_id:
            delta_id = r.get("linked", "")
        elif r.get("linked_type") == "fr_anchor" and not fr_id:
            fr_id = r.get("linked", "")
    if not delta_id and not fr_id:
        return _render({"ok": False, "error": "登记行缺少 delta/fr_anchor 挂链",
                        "refs": [{k: r.get(k) for k in ("type", "ref", "linked_type",
                                                        "linked")} for r in rows]})

    # 冻结校验（三红线①：未冻结 delta 物理不可达）
    if delta_id:
        d = delta_dir(root, delta_id)
        if d is None or not is_frozen(d):
            return _render({"ok": False, "error": f"delta {delta_id!r} 未冻结（缺少 FREEZE.yaml）"
                            "——只读冻结态，草稿/未确认产物物理不可达"})

    if not fr_id and delta_id:
        manifest = _load_manifest(delta_dir(root, delta_id))
        ops = manifest.get("operations") or []
        if ops and ops[0].get("anchor"):
            fr_id = ops[0]["anchor"]
        elif ops and ops[0].get("fr"):
            fr_id = ops[0]["fr"]

    # ref 归一化：以登记行为准（ZT-STORY-4821 形态，兼容纯数字入参）
    actual_ref = rows[0].get("ref") or f"{prefix}-{ref_id}"
    pack = _assemble_pack(ws_name=ws_name, root=root, ref=f"{ref_type}:{actual_ref}",
                          fr_id=fr_id, delta_id=delta_id)
    return _render({"ok": True, "pack": pack})


def _handle_dev_context_by_anchor(args: dict) -> list[TextContent]:
    anchor = str(args.get("anchor") or "").strip()
    if not anchor:
        return _render({"ok": False, "error": "anchor 必填（FR-xxx / 场景 ID）"})
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})

    store, st = open_graph(root)
    node = None
    if store is not None:
        try:
            node = store.get_node(anchor)
        except Exception:
            node = None
        finally:
            store.close()

    # FR 锚点路径
    if node is not None and node.get("node_type") in ("fr", "ac"):
        fr_id = anchor if node.get("node_type") == "fr" else (
            (node.get("title") or "").split()[0] if node.get("node_type") == "ac" else anchor)
        # ac 节点标题形态「FR-012 验收标准 AC-001」→ 取 FR
        if node.get("node_type") == "ac":
            m = re.search(r"(FR-\d{3,})", node.get("title") or "")
            fr_id = m.group(1) if m else anchor
        pack = _assemble_pack(ws_name=ws_name, root=root, ref=anchor, fr_id=fr_id)
        return _render({"ok": True, "pack": pack})

    # 场景节点路径（by_anchor 直接给场景 ID）
    if node is not None and node.get("node_type") == "scenario":
        attrs = node.get("attrs") or {}
        covers = attrs.get("covers") or []
        fr_id = sorted(covers)[0] if covers else ""
        pack = _assemble_pack(ws_name=ws_name, root=root, ref=anchor, fr_id=fr_id)
        pack["identity"]["anchor_node"] = {
            "type": "scenario", "id": anchor, "title": node.get("title", "")}
        return _render({"ok": True, "pack": pack})

    return _render({"ok": False, "error": f"锚点 {anchor!r} 未命中（图谱无此节点）",
                    "hint": "可尝试 FR-xxx（spec 锚点）或场景 ID（IS-xxx/PP-xxx）；"
                            "接口锚点请先确认 specs/ 中已登记" + (
                            f"；索引 stale（{st.get('reason', '')}）" if not store else "")})


def _handle_dev_context_by_fr(args: dict) -> list[TextContent]:
    fr_id = str(args.get("fr_id") or "").strip()
    delta_id = str(args.get("delta_id") or "").strip()
    if not fr_id:
        return _render({"ok": False, "error": "fr_id 必填（如 FR-012）"})
    if not re.fullmatch(r"FR-\d{3,}", fr_id):
        return _render({"ok": False, "error": f"fr_id 格式非法: {fr_id!r}（应为 FR-xxx）"})
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})

    if delta_id:
        d = delta_dir(root, delta_id)
        if d is None:
            return _render({"ok": False, "error": f"delta {delta_id!r} 不存在"})
        if not is_frozen(d):
            return _render({"ok": False, "error": f"delta {delta_id!r} 未冻结——"
                            "只读冻结态，未确认产物物理不可达"})

    pack = _assemble_pack(ws_name=ws_name, root=root, ref=f"fr:{fr_id}",
                          fr_id=fr_id, delta_id=delta_id)
    return _render({"ok": True, "pack": pack})


HANDLERS = {
    "dev_context_by_zt_ref": _handle_dev_context_by_zt_ref,
    "dev_context_by_anchor": _handle_dev_context_by_anchor,
    "dev_context_by_fr": _handle_dev_context_by_fr,
}


async def handle(name: str, arguments: dict) -> list[TextContent]:
    fn = HANDLERS.get(name)
    if fn is None:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return fn(arguments)
