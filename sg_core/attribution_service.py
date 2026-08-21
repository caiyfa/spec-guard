"""attribution_service — 失败归因服务（M09 §4/§5，T-063/T-064）。

核心职责：
  assemble_evidence  证据包装配（响应快照 + DB 快照 + flow digest + 环境指纹），
                     确定性采集不靠 LLM 编造；DB 证据只读（db_oracle SELECT-only）
  suggest_kind       确定性定性建议（仅建议，不落台账——suggestion 永不自动转 decided）
  create_spq         人定性建档（留痕 decided_by/decided_at；缺挂链 → WARNING）
  build_honesty_review  环境问题定性强制诚实性复核（铁律 7）
  sync_spq_to_info_pack SPQ → 面试信息包自动装配（T-064 loop-back，幂等）
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

# 定性分类口径（M09 §4.3，Agent 建议与人定性共用同一枚举）
KIND_PRODUCT_DEFECT = "product_defect"
KIND_SPEC_QUESTION = "spec_question"
KIND_ENVIRONMENT = "environment"
VALID_KINDS = (KIND_PRODUCT_DEFECT, KIND_SPEC_QUESTION, KIND_ENVIRONMENT)

# 环境问题线索（诚实性复核触发词，确定性匹配）
_ENV_CLUES = ("502", "503", "504", "gateway", "网关", "超时", "timeout",
              "连接拒绝", "connection refused", "工号池", "pool_leased",
              "账号未配置", "DB 不可用", "数据库连接", "SKIP", "未配置")

# 归因证据目录（report 内）
EVIDENCE_DIR = "evidence"


class EvidenceError(Exception):
    """证据采集失败（code: run_not_found / case_not_found / invalid_run_id）。"""


def _reports_root() -> Path:
    """报告根目录（工作区 .specguard/reports/ 或仓库根 reports/）。"""
    try:
        from specstd.workspace import reports_dir
        return reports_dir()
    except Exception:
        return SG_ROOT / "reports"


# ══════════════════════════════════════════════════════════
# 证据包装配（G-2）
# ══════════════════════════════════════════════════════════

def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def assemble_evidence(run_id: str, scenario_id: str) -> dict:
    """装配失败场景证据包（M09 §4.2）。

    四要素：flow_digest（场景版本绑定）+ response_snapshot（失败断言现场）+
    db_snapshots（SELECT-only 只读）+ env_fingerprint（环境指纹）。
    纯读取：不写任何文件（落盘由调用方/Agent 决定）。
    """
    import re
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", run_id or ""):
        raise EvidenceError("invalid_run_id", f"非法 run_id: {run_id}")
    root = _reports_root()
    run_dir = (root / run_id).resolve()
    try:
        run_dir.relative_to(root.resolve())
    except ValueError:
        raise EvidenceError("invalid_run_id", f"路径越界: {run_id}")

    # 场景 case（断言失败现场 + 步骤轨迹）
    case = _load_case(run_dir, scenario_id)
    if case is None:
        raise EvidenceError("case_not_found",
                            f"场景 {scenario_id} 在运行 {run_id} 中未找到")

    # ① flow digest：场景 YAML 指纹（与契约指纹同口径）
    flow_digest = _digest(json.dumps({
        "steps": case.get("steps", []),
        "assertions": case.get("assertions", []),
        "saved_vars": case.get("saved_vars", {}),
    }, ensure_ascii=False, default=str))

    # ② 响应快照（失败断言现场摘录，全量流水在 record.jsonl）
    response_snapshot = {"status": None, "body_excerpt": "", "assertion_failed": ""}
    for step in case.get("steps") or []:
        if step.get("status"):
            response_snapshot["status"] = step.get("status")
            response_snapshot["body_excerpt"] = _truncate(
                json.dumps(step.get("response", ""), ensure_ascii=False, default=str))
            break
    for a in case.get("assertions") or []:
        if not a.get("passed"):
            response_snapshot["assertion_failed"] = str(a.get("message", ""))[:500]

    # ③ DB 快照（只读 SELECT-only；无 DB 配置时为空数组不阻塞）
    db_snapshots = _collect_db_snapshots(case)

    # ④ 环境指纹
    run_data = {}
    try:
        run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    env_fingerprint = {
        "env": run_data.get("env", ""),
        "started_at": run_data.get("started_at", ""),
        "gateway": "",
    }

    return {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "flow_digest": flow_digest,
        "response_snapshot": response_snapshot,
        "db_snapshots": db_snapshots,
        "env_fingerprint": env_fingerprint,
        "collected_by": "attribution-service",
        "note": "DB 快照只能经 db_oracle.py（SELECT-only 硬守卫）采集；"
                "响应快照只存摘录（body_excerpt），全量流水在 record.jsonl",
    }


def _load_case(run_dir: Path, scenario_id: str) -> dict | None:
    cases_dir = run_dir / "cases"
    if not cases_dir.is_dir():
        return None
    for f in sorted(cases_dir.glob("*.json")):
        try:
            case = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if case.get("scenario_id") == scenario_id or case.get("id") == scenario_id:
            return case
    return None


def _truncate(text: str, limit: int = 800) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def _collect_db_snapshots(case: dict) -> list[dict]:
    """DB 快照：从 case 提取 db 断言上下文（SELECT-only 语义由 db_oracle 保证）。

    真实 DB 连接采集由 Agent 经 db_evidence 工具完成；此处装配断言侧
    的 DB 证据摘要（sql 模板 + 断言结果），保持确定性。
    """
    snapshots = []
    for step in case.get("steps") or []:
        if step.get("type") == "db_query" or "sql" in step:
            snapshots.append({
                "oracle": step.get("oracle", ""),
                "sql_digest": _digest(str(step.get("sql", ""))),
                "rows_excerpt": _truncate(json.dumps(
                    step.get("rows", ""), ensure_ascii=False, default=str), 400),
                "captured_at": step.get("captured_at", ""),
            })
    return snapshots


# ══════════════════════════════════════════════════════════
# 定性建议（G-1：确定性规则，仅建议不落台账）
# ══════════════════════════════════════════════════════════

def suggest_kind(verdict: str, category: str = "", message: str = "") -> dict:
    """确定性定性建议（M09 §4.3 枚举）。

    规则（非 LLM）：
      - 失败消息/类别含环境线索（网关/超时/池耗尽/未配置）→ environment 候选
      - 断言失败（assertion 类）→ product_defect（诚实 FAIL）
      - spec 相关（歧义/缺预期）→ spec_question
    返回 {kind, rationale}；调用方只存 suggestion 字段，不产生台账。
    """
    text = f"{category} {message}".lower()
    if any(clue in text for clue in _ENV_CLUES):
        return {
            "kind": KIND_ENVIRONMENT,
            "rationale": f"失败线索含环境特征（{category or '?'}），"
                         f"疑似环境问题——须诚实性复核（是否应改判 SKIP）",
        }
    if "spec" in text or "歧义" in text or "预期" in text:
        return {
            "kind": KIND_SPEC_QUESTION,
            "rationale": "失败与预期表述歧义相关——建议需求侧澄清",
        }
    return {
        "kind": KIND_PRODUCT_DEFECT,
        "rationale": "断言失败且无环境线索——诚实 FAIL，疑似产品缺陷（非环境 SKIP）",
    }


def build_honesty_review(verdict: str, kind: str, clues: list = None) -> dict:
    """诚实性复核结论（铁律 7：绝不把环境问题报成 FAIL）。

    kind=environment 时强制附复核结论；否则不强制。
    应改判 SKIP 的线索子串匹配（与 _ENV_CLUES 同口径，不依赖调用方传精确短语）。
    """
    clues = clues or []
    if kind != KIND_ENVIRONMENT:
        return {"required": False, "verdict": verdict, "conclusion": "维持原 verdict"}
    # 环境定性成立：必须复核是否应改判 SKIP（数据缺失/服务不可用类线索 → SKIP）
    text = " ".join(str(c) for c in clues).lower()
    skip_marks = ("502", "503", "504", "gateway", "网关", "超时", "timeout",
                  "连接拒绝", "connection refused", "工号池", "pool",
                  "账号未配置", "未配置", "db 不可用", "数据库连接")
    if any(m in text for m in skip_marks):
        conclusion = "改判 SKIP"
    else:
        conclusion = "维持 FAIL 但附证据"
    return {
        "required": True,
        "verdict": verdict,
        "kind": KIND_ENVIRONMENT,
        "conclusion": conclusion,
        "evidence_required": True,
        "rule": "环境问题记成 FAIL 是数据事故——归因 Agent 对环境类定性强制附复核结论",
    }


# ══════════════════════════════════════════════════════════
# 人定性建档（G-4：suggestion 永不自动转 decided）
# ══════════════════════════════════════════════════════════

def create_spq(ledger, title: str, run_id: str = "", scenario_id: str = "",
               fr_refs: list = None, suggestion_kind: str = "",
               decided_kind: str = "", decided_by: str = "",
               comment: str = "") -> dict:
    """人定性建档 SPQ（M09 §5.1 POST /api/feedback/spq 的服务层）。

    - decided_by 必填（人拍板留痕，铁律 1）
    - 缺 run_id / fr_refs → linkage_warnings（挂链完整性，与 M10 共用口径）
    """
    entry = ledger.create_attributed(
        title=title, run_id=run_id, scenario_id=scenario_id,
        fr_refs=fr_refs, suggestion_kind=suggestion_kind,
        decided_kind=decided_kind, decided_by=decided_by, comment=comment)
    entry["linkage_warnings"] = _linkage_warnings(run_id, fr_refs)
    return entry


def _linkage_warnings(run_id: str, fr_refs: list) -> list[str]:
    warnings = []
    if not run_id:
        warnings.append("缺少 run_id（血缘断链：SPQ 未挂执行证据）")
    if not fr_refs:
        warnings.append("缺少 fr_refs（血缘断链：SPQ 未挂 FR 锚点）")
    return warnings


def transition_spq(ledger, spq_id: str, new_status: str) -> dict:
    """SPQ 状态流转（状态机非法迁移 → ValueError → REST 409）。"""
    return ledger.transition(spq_id, new_status)


# ══════════════════════════════════════════════════════════
# T-064：SPQ → 面试信息包 loop-back（G-5）
# ══════════════════════════════════════════════════════════

def sync_spq_to_info_pack(spq_id: str, iv_id: str, pack_dir: Path,
                          ledger=None) -> dict:
    """把未闭环 SPQ 装配进指定面试信息包（幂等：已装配不重复入包）。

    pack_dir 下写 {iv_id}/spq_feedback.yaml（与 specflow interviews 布局对齐）；
    台账回填 info_pack_synced（去重）。ledger 缺省从 feedback/ledger.json 加载。
    """
    if ledger is None:
        from feedback.ledger import FeedbackLedger
        ledger = FeedbackLedger(SG_ROOT / "feedback" / "ledger.json")
    entry = ledger.get(spq_id)
    if entry is None:
        raise KeyError(f"台账条目不存在: {spq_id}")
    synced = entry.get("info_pack_synced") or []
    if iv_id in synced:
        return {"added": False, "spq_id": spq_id, "iv_id": iv_id,
                "reason": "已装配（幂等）"}

    # 路径守卫 + 布局对齐：{pack_dir}/interviews/{iv_id}/（与 db_assemble_pack 同布局，
    # iv_dir 内置 validate_iv_id 防目录穿越）
    from specflow.interview.iv_lifecycle import iv_dir as _iv_dir
    iv_target = _iv_dir(pack_dir, iv_id)
    iv_target.mkdir(parents=True, exist_ok=True)
    payload = {
        "spq_id": spq_id,
        "title": entry.get("title", ""),
        "status": entry.get("status", ""),
        "run_id": entry.get("run_id", ""),
        "scenario_id": entry.get("scenario_id", ""),
        "fr_refs": entry.get("fr_refs", []),
        "decided_kind": entry.get("decided_kind", ""),
        "report_summary": _run_summary(entry.get("run_id", "")),
    }
    target = iv_target / "spq_feedback.yaml"
    try:
        import yaml as _yaml
        existing = []
        if target.is_file():
            existing = _yaml.safe_load(target.read_text(encoding="utf-8")) or []
        existing = [e for e in existing if e.get("spq_id") != spq_id]
        existing.append(payload)
        target.write_text(
            _yaml.dump(existing, allow_unicode=True, indent=2, sort_keys=False),
            encoding="utf-8")
    except Exception as e:
        return {"added": False, "spq_id": spq_id, "iv_id": iv_id,
                "error": f"写入失败: {e}"}

    ledger.mark_info_pack_synced(spq_id, iv_id)
    return {"added": True, "spq_id": spq_id, "iv_id": iv_id,
            "path": str(target)}


def _run_summary(run_id: str) -> dict:
    """run 报告摘要（读 reports/{run_id}/run.json；读不到返回空）。"""
    if not run_id:
        return {}
    try:
        p = _reports_root() / run_id / "run.json"
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            "run_id": run_id,
            "env": data.get("env", ""),
            "stats": data.get("stats", {}),
        }
    except Exception:
        return {}
