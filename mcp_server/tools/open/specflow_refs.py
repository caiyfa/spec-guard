"""open/specflow_refs.py — 需求侧冻结产物只读面（M13 §4.5，T-083）。

L0 工具（side_effect 全部 none）：
  get_frozen_spec      读冻结基线 spec（FR 锚点 + SHALL 条款 + delta 标记 + 已冻结 delta 清单）
  get_proposal         读 proposal.md 四段式（为什么做/做什么/不做什么/验收口径）
  query_decisions      决策台账查询（D-xxx 分级/状态/amendment 增补链，支持 FR/delta 反查）
  get_interview_status 面试进度查询（IV-xxx：进度/P0 清零/闸门状态）
  get_delta_contract   读 delta 契约（manifest 操作集 + FREEZE 凭证 + 契约期望）

数据源 owner：M05（冻结产物）/ M04（决策台账）；本模块只做查询面，不拥有产物。
红线：全部纯读——不写台账、不触碰 drafts/、不调图谱重建。
"""

from __future__ import annotations

import json
import re

from mcp.types import Tool, TextContent

from mcp_server.tools.open import (
    resolve_workspace_root, delta_dir, frozen_deltas, is_frozen, read_text,
)


def _render(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False,
                                                     indent=2, default=str))]


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

get_frozen_spec_tool = Tool(
    name="get_frozen_spec",
    description="读冻结基线 spec：指定模块（specs/{module}/）的 FR 锚点清单 + SHALL 强制"
                "条款 + [delta:xxx] 变更标记 + 已冻结 delta 清单。编码前读这份「合同」。",
    inputSchema={
        "type": "object",
        "properties": {
            "module": {"type": "string", "description": "模块名（specs/ 下第一级目录，如 inventory-session）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["module"],
    },
)

get_proposal_tool = Tool(
    name="get_proposal",
    description="读 delta 的 proposal 四段式（为什么做/做什么/不做什么/验收口径）——"
                "回答「这个变更为什么存在、边界在哪」",
    inputSchema={
        "type": "object",
        "properties": {
            "delta_id": {"type": "string", "description": "delta 代号（如 grid-rule-perf）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["delta_id"],
    },
)

query_decisions_tool = Tool(
    name="query_decisions",
    description="查询决策台账 D-xxx：按优先级/状态过滤，或按业务引用（FR-xxx/delta 代号）"
                "反查相关决策；每条含 amendment 增补链（落锤不可推翻，只可增补）。",
    inputSchema={
        "type": "object",
        "properties": {
            "biz_ref": {"type": "string", "description": "可选：FR 锚点（FR-012）或 delta 代号，反查关联决策"},
            "level": {"type": "string", "enum": ["P0", "P1", "P2"], "description": "可选：按优先级过滤"},
            "status": {"type": "string", "enum": ["pending", "resolved", "superseded"],
                       "description": "可选：按状态过滤"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
    },
)

get_interview_status_tool = Tool(
    name="get_interview_status",
    description="查询需求面试进度（IV-xxx）：问题作答进度 / P0 清零状态 / 冻结闸门状态。",
    inputSchema={
        "type": "object",
        "properties": {
            "iv_id": {"type": "string", "description": "面试编号（IV-xxx）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["iv_id"],
    },
)

get_delta_contract_tool = Tool(
    name="get_delta_contract",
    description="读 delta 契约：manifest 操作集（ADDED/MODIFIED/REMOVED × FR 锚点）+ 冻结凭证"
                "（FREEZE.yaml）+ 契约期望（基线与 specstd 版本）。已冻结 delta 才有契约。",
    inputSchema={
        "type": "object",
        "properties": {
            "delta_id": {"type": "string", "description": "delta 代号（须已冻结）"},
            "workspace": {"type": "string", "description": "工作区名（默认当前激活工作区）"},
        },
        "required": ["delta_id"],
    },
)

TOOLS = [
    get_frozen_spec_tool,
    get_proposal_tool,
    query_decisions_tool,
    get_interview_status_tool,
    get_delta_contract_tool,
]


# ══════════════════════════════════════════════════════════
# 只读数据源辅助
# ══════════════════════════════════════════════════════════

def _load_manifest(delta_path) -> dict:
    """读 delta.manifest.yaml（容错返回空结构）。"""
    import yaml
    p = delta_path / "delta.manifest.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_freeze(delta_path) -> dict:
    """读 FREEZE.yaml 冻结凭证（容错返回空结构）。"""
    import yaml
    p = delta_path / "FREEZE.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _list_decisions(biz_ref: str = "", level: str = "", status: str = "",
                    workspace: str = "") -> list[dict]:
    """决策台账查询（纯读 sf_decisions/sf_decision_links/sf_decision_amendments）。"""
    from specflow.interview.decision_ledger import init_tables, list_decisions
    from workbench.backend.services.specflow.sf_store import _connect

    conn = _connect()
    try:
        init_tables(conn)
        # biz_ref 反查：sf_decision_links 命中 decision_id 集
        ids: set = set()
        if biz_ref:
            rows = conn.execute(
                "SELECT DISTINCT decision_id FROM sf_decision_links "
                "WHERE link_ref = ?", (biz_ref,)).fetchall()
            ids = {r[0] for r in rows}
        rows = list_decisions(conn, status=status, priority=level, workspace=workspace)
        result = []
        for r in rows:
            if ids and r.get("id") not in ids:
                continue
            # amendment 增补链（base → new，递归收集）
            chain = []
            cur = r.get("id", "")
            while cur:
                am = conn.execute(
                    "SELECT new_decision, reason FROM sf_decision_amendments "
                    "WHERE base_decision = ? ORDER BY id", (cur,)).fetchone()
                if not am:
                    break
                chain.append({"id": am[0], "reason": am[1]})
                cur = am[0]
            result.append({**{k: r.get(k) for k in
                              ("id", "interview_id", "priority", "question", "status",
                               "resolution", "resolved_by", "resolved_at")},
                           "amend_chain": chain})
        return result
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# 工具处理
# ══════════════════════════════════════════════════════════

def _handle_get_frozen_spec(args: dict) -> list[TextContent]:
    module = str(args.get("module", "") or "").strip()
    if not module or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", module):
        return _render({"ok": False, "error": "module 必填（specs/ 下第一级目录名）"})
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})

    specs_root = root / "specs"
    spec_files = sorted(specs_root.glob(f"{module}/**/spec.md")) if specs_root.is_dir() else []
    if not spec_files:
        available = sorted({p.relative_to(specs_root).parts[0]
                            for p in specs_root.glob("*/**/spec.md")}) if specs_root.is_dir() else []
        return _render({"ok": False, "error": f"模块 {module!r} 无 spec.md",
                        "available_modules": available})

    spec_md_parts: list[str] = []
    anchors: dict = {}
    shall_lines: list[dict] = []
    delta_marks: list[str] = []
    for f in spec_files:
        text = read_text(f)
        spec_md_parts.append(f"--- {f.relative_to(specs_root)} ---\n{text}")
        # SHALL 条款（强制语义行）
        for i, line in enumerate(text.splitlines(), 1):
            if "SHALL" in line.upper() and line.strip():
                shall_lines.append({"file": str(f.relative_to(specs_root)),
                                    "line": i, "text": line.strip()})
        # delta 标记
        marks = re.findall(r"\[delta:([a-z0-9_-]+)(?:\s+\w+)?\]", text)
        delta_marks.extend(marks)

    # FR 锚点（按模块过滤）
    from specstd.anchors import scan_anchors
    for fr_id, info in sorted(scan_anchors(root).items()):
        if info.module != module:
            continue
        anchors[fr_id] = {
            "title": info.title,
            "ac_ids": sorted(info.ac_ids),
            "module": info.module,
            "feature": info.feature,
            "file": str(info.file_path).replace("\\", "/"),
        }

    return _render({
        "ok": True,
        "workspace": ws_name,
        "module": module,
        "spec_md": "\n".join(spec_md_parts),
        "anchors": anchors,
        "anchor_count": len(anchors),
        "shall_clauses": shall_lines,
        "delta_marks": sorted(set(delta_marks)),
        "frozen_deltas": frozen_deltas(root),
    })


def _handle_get_proposal(args: dict) -> list[TextContent]:
    delta_id = str(args.get("delta_id", "") or "").strip()
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    d = delta_dir(root, delta_id)
    if d is None:
        return _render({"ok": False, "error": f"delta {delta_id!r} 不存在"})
    proposal_path = d / "proposal.md"
    if not proposal_path.is_file():
        return _render({"ok": False, "error": f"delta {delta_id!r} 无 proposal.md"})

    from specflow.anchor.proposal_schema import parse_proposal_sections
    text = read_text(proposal_path)
    sections = parse_proposal_sections(text)
    return _render({
        "ok": True,
        "workspace": ws_name,
        "delta_id": delta_id,
        "sections": {k: sections.get(k, "") for k in
                     ("为什么做", "做什么", "不做什么", "验收口径")},
        "missing_sections": [k for k in ("为什么做", "做什么", "不做什么", "验收口径")
                             if k not in sections],
    })


def _handle_query_decisions(args: dict) -> list[TextContent]:
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    decisions = _list_decisions(
        biz_ref=str(args.get("biz_ref") or ""),
        level=str(args.get("level") or ""),
        status=str(args.get("status") or ""),
        workspace=ws_name)
    return _render({
        "ok": True,
        "workspace": ws_name,
        "count": len(decisions),
        "decisions": decisions,
        "note": "biz_ref 按 FR 锚点/delta 代号反查决策链（sf_decision_links）",
    })


def _handle_get_interview_status(args: dict) -> list[TextContent]:
    iv_id = str(args.get("iv_id", "") or "").strip()
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    if not iv_id:
        return _render({"ok": False, "error": "iv_id 必填（IV-xxx）"})

    from workbench.backend.services.specflow.sf_store import _connect, get_interview

    row = get_interview(iv_id)
    if row is None:
        return _render({"ok": False, "error": f"面试 {iv_id!r} 不存在"})

    conn = _connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM sf_questions WHERE iv_id = ? AND workspace = ?",
            (iv_id, ws_name)).fetchone()[0]
        answered = conn.execute(
            "SELECT COUNT(*) FROM sf_questions WHERE iv_id = ? AND workspace = ? "
            "AND status = 'answered'", (iv_id, ws_name)).fetchone()[0]
        from specflow.interview.decision_ledger import count_pending_p0, init_tables
        init_tables(conn)
        p0_pending = count_pending_p0(conn, iv_id, workspace=ws_name)
    finally:
        conn.close()

    return _render({
        "ok": True,
        "workspace": ws_name,
        "iv_id": iv_id,
        "title": row.get("title", ""),
        "status": row.get("status", ""),          # opened / p0_cleared / frozen
        "target_delta": row.get("target_delta", ""),
        "opened_at": row.get("opened_at", ""),
        "frozen_at": row.get("frozen_at", ""),
        "progress": {"total_questions": total, "answered": answered,
                     "pending": total - answered},
        "p0_pending": p0_pending,
        "p0_cleared": p0_pending == 0,
        "gate_status": "frozen" if row.get("status") == "frozen"
                       else ("p0_cleared" if p0_pending == 0 else "open"),
    })


def _handle_get_delta_contract(args: dict) -> list[TextContent]:
    delta_id = str(args.get("delta_id", "") or "").strip()
    root, ws_name = resolve_workspace_root(str(args.get("workspace") or ""))
    if root is None:
        return _render({"ok": False, "error": "工作区不可用（未激活或不存在）"})
    d = delta_dir(root, delta_id)
    if d is None:
        return _render({"ok": False, "error": f"delta {delta_id!r} 不存在"})
    if not is_frozen(d):
        return _render({"ok": False, "error": f"delta {delta_id!r} 未冻结"
                        "（冻结产物是开放面唯一契约来源，未冻结态不可达）"})

    manifest = _load_manifest(d)
    freeze = _load_freeze(d)
    ops = manifest.get("operations") or []
    sections = {
        "ADDED": [op for op in ops if op.get("op") == "ADDED"],
        "MODIFIED": [op for op in ops if op.get("op") == "MODIFIED"],
        "REMOVED": [op for op in ops if op.get("op") == "REMOVED"],
    }
    return _render({
        "ok": True,
        "workspace": ws_name,
        "delta_id": delta_id,
        "sections": sections,
        "manifest": {
            "specstd_version": manifest.get("specstd_version", "1.0"),
            "source_interview": manifest.get("source_interview", ""),
            "base_spec": manifest.get("base_spec", ""),
            "base_spec_sha": manifest.get("base_spec_sha", ""),
        },
        "freeze": {
            "frozen_at": freeze.get("frozen_at", ""),
            "frozen_by": freeze.get("frozen_by", ""),
            "spec_sha": freeze.get("spec_sha", ""),
            "gates": freeze.get("gates", {}),
        },
        "contract_expectations": {
            "tool": "specguard-open-l0",
            "version": manifest.get("specstd_version", "1.0"),
            "delta": delta_id,
        },
    })


HANDLERS = {
    "get_frozen_spec": _handle_get_frozen_spec,
    "get_proposal": _handle_get_proposal,
    "query_decisions": _handle_query_decisions,
    "get_interview_status": _handle_get_interview_status,
    "get_delta_contract": _handle_get_delta_contract,
}


async def handle(name: str, arguments: dict) -> list[TextContent]:
    fn = HANDLERS.get(name)
    if fn is None:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    return fn(arguments)
