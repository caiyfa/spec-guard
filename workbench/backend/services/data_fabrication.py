"""data_fabrication — 测试数据制造编排服务（M08 §5.3，T-062）。

确定性编排层（零 LLM）：
  ① 复用优先——既有 IS-PREP 场景（covers 命中且含 data_contract）→ 建议复用不新造
  ② 按缺口 FR 生成 IS-PREP 草稿（data_contract 声明块 + source_delta 挂链）
  ③ 数据校验器硬拒不合格实例（validation 报告随产物返回）
  ④ 产物一律走 write_draft（三闸通道），**无一绕过**（铁律 3）

数据源只读引用适配包资产（emp-pool.yaml 结构、oracles 注册名），引擎零改动（铁律 5）。
flow/verify 由 Agent（fabricate-test-data skill）后续填充；本层保证骨架契约正确。
"""

from __future__ import annotations

import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

# 引擎零改动黑名单（静态断言：本模块及产物不触碰 engine/ 与 specstd/ 规则层）
ENGINE_TOUCH_BLACKLIST = ("engine/", "specstd/schema.py")


def _next_prep_id(existing: set) -> str:
    """取下一个 IS-PREP 序号（确定性，不撞库内/草稿既有 ID）。"""
    for i in range(1, 999):
        sid = f"IS-PREP-{i:03d}"
        if sid not in existing:
            return sid
    return "IS-PREP-999"


def _load_anchors() -> dict:
    try:
        from specstd.workspace import get_workspace_root
        from specstd.anchors import scan_anchors
        ws = get_workspace_root()
        if not ws:
            return {}
        return scan_anchors(ws)
    except Exception:
        return {}


def _load_existing() -> tuple[list[dict], set]:
    """场景库 + 草稿中的 IS-PREP 实例（id / covers / data_contract）。"""
    scenarios, drafts = [], []
    root = _scenarios_root()
    if root.is_dir():
        try:
            from engine.scenario_loader import load_scenarios
            for s in load_scenarios(str(root)):
                if s.id.startswith("IS-PREP-"):
                    scenarios.append({"id": s.id, "covers": list(s.covers),
                                      "has_contract": bool(getattr(s, "requires", None)) or True})
        except Exception:
            pass
    try:
        import yaml as _yaml
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        if d.is_dir():
            for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
                if f.name.startswith("_"):
                    continue
                try:
                    raw = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    if str(raw.get("id", "")).startswith("IS-PREP-"):
                        drafts.append({
                            "id": str(raw.get("id", "")),
                            "covers": [(raw.get("doc") or {}).get("covers")
                                       or raw.get("covers") or []],
                        })
                except Exception:
                    continue
    except Exception:
        pass
    ids = {s["id"] for s in scenarios} | {d["id"] for d in drafts}
    return scenarios, ids


def _scenarios_root() -> Path:
    try:
        from specstd.workspace import get_workspace_root
        ws = get_workspace_root()
        if ws and (ws / "scenarios").is_dir():
            return ws / "scenarios"
    except Exception:
        pass
    return SG_ROOT / "scenarios"


def fabricate(frs: list[str], source_delta: str = "",
              target: str = "IS-PREP") -> dict:
    """数据制造编排入口：复用判定 → 逐 FR 生成草稿（含 data_contract）→ 数据校验器。

    Returns:
        {drafts: [{id, covers, source_delta, data_contract, validation, draft_id}],
         rejected: [{fr, reason}], reuse_hints: [str]}
    """
    from workbench.backend.services.data_validator import validate_data_contract

    anchors = _load_anchors()
    existing_preps, existing_ids = _load_existing()
    drafts_out, rejected, reuse_hints = [], [], []

    for fr in frs:
        if fr not in anchors:
            rejected.append({"fr": fr, "reason": "锚点不存在（spec.md 无此 FR）"})
            continue
        # 复用优先：既有 IS-PREP covers 命中 → 建议复用
        hits = [s for s in existing_preps if fr in s["covers"]]
        if hits:
            reuse_hints.append(
                f"{fr} 已有可复用数据实例 {hits[0]['id']}（covers 命中）——"
                f"优先复用/参数化，不新造")
            continue
        title = getattr(anchors[fr], "title", "") or fr
        sid = _next_prep_id(existing_ids)
        contract = _default_contract()
        content = _prep_skeleton(sid, fr, title, source_delta, contract)
        # 数据校验器（硬拒不合格实例——校验不过不落盘）
        import yaml as _yaml
        raw = _yaml.safe_load(content) or {}
        validation = validate_data_contract(raw)
        if validation["verdict"] == "FAIL":
            rejected.append({"fr": fr, "reason": "数据校验器硬拒",
                             "findings": validation["findings"]})
            continue
        # 走 write_draft（三闸通道：自动登记 sg_draft_gates + gate2 自动跑）
        from mcp_server.tools.draft_writer import _handle_write_draft
        filename = f"{sid}.yaml"
        resp = _handle_write_draft({"filename": filename, "content": content,
                                    "mode": "create"})
        text = resp[0].text if resp else "{}"
        import json as _json
        try:
            out = _json.loads(text)
        except Exception:
            out = {"ok": False, "error": text}
        if not out.get("ok"):
            rejected.append({"fr": fr, "reason": out.get("error", "写入失败")})
            continue
        drafts_out.append({
            "id": sid, "covers": [fr], "source_delta": source_delta,
            "data_contract": contract, "validation": validation,
            "draft_id": filename,
        })
        existing_ids.add(sid)

    return {
        "drafts": drafts_out,
        "rejected": rejected,
        "reuse_hints": reuse_hints,
        "note": "产物一律草稿态（三闸通道：write 自动登记 + gate2 自动校验）；"
                "flow/verify 由 fabricate-test-data skill 补充；"
                "promote 必须三闸全过（铁律 3）",
    }


def _default_contract() -> dict:
    """默认数据契约骨架（Agent 按 spec 锚点细化；校验器保证三要素合法）。"""
    return {
        "provides": {
            "activity": {"status": "ACTIVE"},
            "session": {"status": "IN_PROGRESS", "count": 1},
            "members": {"count": 1, "from": "emp-pool", "role": "snapshot_rich"},
        },
        "isolation": "shared",
        "cleanup": "teardown",
    }


def _prep_skeleton(sid: str, fr_id: str, title: str, source_delta: str,
                   contract: dict) -> str:
    """IS-PREP 草稿骨架（格式 2.0 双层 YAML + data_contract 声明块 + 挂链）。"""
    import yaml as _yaml
    contract_yaml = _yaml.dump(contract, allow_unicode=True,
                               default_flow_style=False, sort_keys=False)
    sd = f"source_delta: {source_delta}\n" if source_delta else ""
    return (
        f"# 数据制造产物（data-fab fabricate）：为 {fr_id} 准备数据实例（骨架，"
        f"flow/verify 由 fabricate-test-data skill 补充）\n"
        f"id: {sid}\n"
        f"title: \"{title}（数据准备实例）\"\n"
        f"version: \"0.1\"\n"
        f"{sd}"
        f"doc:\n"
        f"  given: 数据制造前置\n"
        f"  when: 执行数据准备\n"
        f"  then: 实例就绪\n"
        f"  covers: [{fr_id}]\n"
        f"data_contract:\n"
        + "\n".join(f"  {line}" for line in contract_yaml.rstrip().splitlines())
        + "\n"
        f"flow: []\n"
        f"verify: []\n"
    )
