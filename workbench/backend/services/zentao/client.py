"""workbench/services/zentao/client.py — 禅道写作业编排（M06 §6，T-053/T-055）。

职责：
- 故事创建（冻结 delta 唯一输入）、故事点回写、BUG 提单（双入口）
- 幂等：sf_zentao_jobs.idem_key UNIQUE，重复点击/重试命中返回原作业
- 重试：同 job_id 同幂等键，指数退避，不产生第二单
- 回滚：失败只回滚 SpecGuard 侧作业状态与登记，不删禅道资产（铁律 4）
- 凭据：token 经 config 解析只在内存传递，不落日志/argv

写动作必须由人经 REST（RBAC）触发；本模块不暴露给 MCP。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from integrations.zentao.api import ZenTaoClient, ZenTaoAPIError
from workbench.backend.services.specflow import sf_refs_store
from workbench.backend.services.zentao.config import (
    get_zentao_config, has_zentao_credentials,
)

logger = logging.getLogger(__name__)

# 重试参数（M06 §4.2：指数退避）
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [2, 8, 20]

# 提 BUG 入口① 拒绝的诚实结果 verdict（SKIP/BLOCKED = 环境问题，禁止提单）
HONEST_BLOCKED_VERDICTS = ("SKIP", "BLOCKED", "SKIPPED")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _specflow_changes_dir() -> Path:
    """工作区 .specflow/changes 目录。"""
    from specstd.workspace import specflow_dir
    return specflow_dir() / "changes"


def _require_credentials() -> None:
    """无凭据时拒绝写通道（fail-closed，不静默）。"""
    if not has_zentao_credentials():
        raise ValueError("禅道凭据未配置（SG_ZENTAO_TOKEN 或 settings zentao_token）")


def _require_frozen(delta_id: str) -> str:
    """冻结校验：changes/{delta}/FREEZE.yaml 必须存在（铁律 3）。"""
    changes = _specflow_changes_dir()
    if not (changes / delta_id / "FREEZE.yaml").is_file():
        return f"delta {delta_id} 未冻结（缺少 FREEZE.yaml），冻结产物是故事创建唯一输入"
    return ""


def _load_manifest(delta_id: str):
    """读取 delta manifest（故事正文 FR 拆解来源）。"""
    from specflow.delta.manifest import load_manifest
    manifest_path = _specflow_changes_dir() / delta_id / "delta.manifest.yaml"
    if not manifest_path.is_file():
        return None
    return load_manifest(str(manifest_path))


def _story_body(delta_id: str, manifest) -> str:
    """故事正文：FR 操作集 + 决策引用 + proposal 摘要（M06 §6.1 步骤 5）。"""
    lines = [f"# {delta_id}", ""]
    if manifest:
        ops = manifest.operations or []
        if ops:
            lines.append("## 涉及功能点")
            for op in ops:
                anchor = op.get("anchor", "")
                op_type = op.get("op", "")
                reason = op.get("reason", "")
                line = f"- {anchor}（{op_type}）"
                if reason:
                    line += f": {reason}"
                lines.append(line)
            decs = []
            for op in ops:
                decs.extend(op.get("decisions") or [])
            if decs:
                lines.append("")
                lines.append("## 决策引用")
                for d in sorted(set(decs)):
                    lines.append(f"- {d}")
    # proposal 摘要
    proposal_path = _specflow_changes_dir() / delta_id / "proposal.md"
    if proposal_path.is_file():
        text = proposal_path.read_text(encoding="utf-8")
        summary = " ".join(text.split())[:500]
        lines.append("")
        lines.append("## 需求来源摘要")
        lines.append(summary)
    return "\n".join(lines)


def _run_with_retry(action, kind: str) -> tuple[Optional[dict], str, str]:
    """执行禅道写动作（指数退避重试，同作业不产生第二单）。

    Returns:
        (result, stdout, stderr)
    """
    last_err = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = action()
            return result, f"attempt={attempt} ok", ""
        except Exception as e:  # noqa: BLE001 禅道 API 错误与网络错误统一重试
            last_err = str(e)
            logger.warning("zentao %s 第 %s 次尝试失败: %s", kind, attempt, e)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SECONDS[min(attempt - 1,
                                               len(BACKOFF_SECONDS) - 1)])
    return None, "", last_err


def create_story_job(workspace: str, delta_id: str, title: str,
                     actor: str, product_id: int = None) -> dict:
    """故事创建作业（冻结校验 + 幂等 + 重试 + 锚点登记）。

    Returns:
        job dict；duplicate=True 表示幂等命中（返回原作业，不重复建故事）
    """
    _require_credentials()
    err = _require_frozen(delta_id)
    if err:
        raise ValueError(err)
    manifest = _load_manifest(delta_id)
    idem_key = f"story:{workspace}:{delta_id}"
    job = sf_refs_store.create_job(
        workspace, "story_create", idem_key,
        {"delta_id": delta_id, "title": title, "actor": actor},
        created_by=actor)
    if job.get("duplicate"):
        return job
    try:
        body = _story_body(delta_id, manifest)
        cfg = get_zentao_config()
        client = ZenTaoClient(base_url=cfg["base_url"], token=cfg["token"])
        story_title = title or delta_id
        data = {
            "product": int(product_id) if product_id else _resolve_product(cfg["product"]),
            "title": story_title,
            "spec": body,
            "category": "feature",
        }
        result, stdout, stderr = _run_with_retry(
            lambda: client.story_create(data), "story_create")
        if result is None:
            sf_refs_store.update_job(job["job_id"], status="failed",
                                     stderr=stderr)
            return sf_refs_store.get_job(job["job_id"])
        story = result.get("story", result)
        story_id = str(story.get("id", ""))
        sf_refs_store.update_job(job["job_id"], status="succeeded",
                                 zt_ref=story_id, stdout=stdout)
        # 锚点登记：zt_story → delta + fr_anchor（每条）
        sf_refs_store.register_ref(
            workspace, "zt_story", story_id, "delta", delta_id,
            ref_url=_story_url(story_id),
            note=f"story_create by {actor}", registered_by=actor)
        for op in (manifest.operations if manifest else []) or []:
            anchor = op.get("anchor", "")
            if anchor:
                sf_refs_store.register_ref(
                    workspace, "zt_story", story_id, "fr_anchor", anchor,
                    ref_url=_story_url(story_id),
                    note=f"{delta_id} {op.get('op', '')}",
                    registered_by=actor)
        return sf_refs_store.get_job(job["job_id"])
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        sf_refs_store.update_job(job["job_id"], status="failed", stderr=str(e))
        return sf_refs_store.get_job(job["job_id"])


def writeback_points_job(workspace: str, estimate_id: int, actor: str) -> dict:
    """故事点回写作业（estimate 必须已 confirmed——产品确认闸门）。

    回写失败不回滚删除禅道资产（铁律 4），作业标 failed 由人处理。
    """
    _require_credentials()
    estimate = sf_refs_store.get_estimate(estimate_id)
    if not estimate:
        raise KeyError(f"评估记录不存在: {estimate_id}")
    if estimate["status"] != "confirmed":
        raise ValueError(
            f"评估记录状态为 {estimate['status']}，产品确认（confirmed）后才可回写")
    zt_story = estimate.get("zt_story") or _find_story_for_delta(
        workspace, estimate["delta_id"])
    if not zt_story:
        raise ValueError("未找到关联禅道故事（zt_story），请先创建故事")
    idem_key = f"storypoint:{workspace}:{estimate_id}"
    job = sf_refs_store.create_job(
        workspace, "story_point_writeback", idem_key,
        {"estimate_id": estimate_id, "points": estimate["points"],
         "zt_story": zt_story, "actor": actor},
        created_by=actor)
    if job.get("duplicate"):
        return job
    try:
        cfg = get_zentao_config()
        client = ZenTaoClient(base_url=cfg["base_url"], token=cfg["token"])
        result, stdout, stderr = _run_with_retry(
            lambda: client.story_update(zt_story, {"estimate": estimate["points"]}),
            "story_point_writeback")
        if result is None:
            sf_refs_store.update_job(job["job_id"], status="failed",
                                     stderr=stderr)
            return sf_refs_store.get_job(job["job_id"])
        sf_refs_store.update_job(job["job_id"], status="succeeded",
                                 zt_ref=zt_story, stdout=stdout)
        sf_refs_store.update_estimate_status(
            estimate_id, "written_back", actor=actor, zt_story=zt_story)
        return sf_refs_store.get_job(job["job_id"])
    except Exception as e:  # noqa: BLE001
        sf_refs_store.update_job(job["job_id"], status="failed", stderr=str(e))
        return sf_refs_store.get_job(job["job_id"])


def create_bug_from_run_job(workspace: str, run_id: str, scenario_id: str,
                            severity: int, title: str, actor: str,
                            spq_id: str = "", story_id: str = "",
                            product_id: int = None) -> dict:
    """提 BUG 入口①：DAG 执行 FAIL 归因后一键提单。

    确定性闸门：该场景 verdict 必须 FAIL（SKIP/BLOCKED 提单被拒——诚实结果）。
    """
    _require_credentials()
    verdict, _ = read_run_verdict(workspace, run_id, scenario_id)
    if verdict is None:
        raise ValueError(f"run {run_id} 中未找到场景 {scenario_id} 的执行记录")
    if verdict in HONEST_BLOCKED_VERDICTS:
        raise ValueError(
            f"场景 {scenario_id} verdict={verdict}（环境问题），禁止提单"
            f"——仅 FAIL 且经人为疑似缺陷定性才可提 BUG")
    if verdict != "FAIL":
        raise ValueError(
            f"场景 {scenario_id} verdict={verdict}，仅 FAIL 可提单")
    if not title:
        title = f"[{scenario_id}] 执行失败待确认缺陷"
    idem_key = f"bug:{workspace}:{spq_id or f'{run_id}:{scenario_id}'}"
    job = sf_refs_store.create_job(
        workspace, "bug_create", idem_key,
        {"run_id": run_id, "scenario_id": scenario_id, "severity": severity,
         "title": title, "spq_id": spq_id, "story_id": story_id,
         "actor": actor},
        created_by=actor)
    if job.get("duplicate"):
        return job
    try:
        steps = build_repro_steps(workspace, run_id, scenario_id)
        data = {
            "product": int(product_id) if product_id else _resolve_product(
                get_zentao_config()["product"]),
            "title": title,
            "steps": steps,
            "severity": severity or 3,
        }
        if story_id:
            data["story"] = story_id
        cfg = get_zentao_config()
        client = ZenTaoClient(base_url=cfg["base_url"], token=cfg["token"])
        result, stdout, stderr = _run_with_retry(
            lambda: client.bug_create(data), "bug_create")
        if result is None:
            sf_refs_store.update_job(job["job_id"], status="failed",
                                     stderr=stderr)
            return sf_refs_store.get_job(job["job_id"])
        bug = result.get("bug", result)
        bug_id = str(bug.get("id", ""))
        sf_refs_store.update_job(job["job_id"], status="succeeded",
                                 zt_ref=bug_id, stdout=stdout)
        # 四元关联登记：zt_bug → spq / scenario / run / fr_anchor
        links = [(spq_id, "spq"), (scenario_id, "scenario"),
                 (f"run#{run_id}", "run")]
        for linked, linked_type in links:
            if linked:
                sf_refs_store.register_ref(
                    workspace, "zt_bug", bug_id, linked_type, linked,
                    ref_url=_bug_url(bug_id),
                    note=f"bug_create by {actor}", registered_by=actor)
        return sf_refs_store.get_job(job["job_id"])
    except Exception as e:  # noqa: BLE001
        sf_refs_store.update_job(job["job_id"], status="failed", stderr=str(e))
        return sf_refs_store.get_job(job["job_id"])


def create_bug_manual_job(workspace: str, title: str, steps: str,
                          severity: int, actor: str, story_id: str = "",
                          fr_ref: str = "", idem_key: str = "") -> dict:
    """提 BUG 入口②：手工录入，与入口① 同一作业/幂等/登记管线。"""
    _require_credentials()
    if not title or not steps:
        raise ValueError("title 与 steps 不能为空")
    key = idem_key or f"bug-manual:{workspace}:{_now()}"
    job = sf_refs_store.create_job(
        workspace, "bug_create", key,
        {"title": title, "steps_len": len(steps), "severity": severity,
         "story_id": story_id, "fr_ref": fr_ref, "actor": actor,
         "manual": True},
        created_by=actor)
    if job.get("duplicate"):
        return job
    try:
        data = {
            "product": _resolve_product(get_zentao_config()["product"]),
            "title": title,
            "steps": steps,
            "severity": severity or 3,
        }
        if story_id:
            data["story"] = story_id
        cfg = get_zentao_config()
        client = ZenTaoClient(base_url=cfg["base_url"], token=cfg["token"])
        result, stdout, stderr = _run_with_retry(
            lambda: client.bug_create(data), "bug_create")
        if result is None:
            sf_refs_store.update_job(job["job_id"], status="failed",
                                     stderr=stderr)
            return sf_refs_store.get_job(job["job_id"])
        bug = result.get("bug", result)
        bug_id = str(bug.get("id", ""))
        sf_refs_store.update_job(job["job_id"], status="succeeded",
                                 zt_ref=bug_id, stdout=stdout)
        if fr_ref:
            sf_refs_store.register_ref(
                workspace, "zt_bug", bug_id, "fr_anchor", fr_ref,
                ref_url=_bug_url(bug_id),
                note=f"bug_create(manual) by {actor}", registered_by=actor)
        return sf_refs_store.get_job(job["job_id"])
    except Exception as e:  # noqa: BLE001
        sf_refs_store.update_job(job["job_id"], status="failed", stderr=str(e))
        return sf_refs_store.get_job(job["job_id"])


def poll_bug(workspace: str, bug_id: str) -> dict:
    """禅道 BUG 状态回查（纯读；resolved/closed → 回归建议）。"""
    cfg = get_zentao_config()
    client = ZenTaoClient(base_url=cfg["base_url"], token=cfg["token"])
    data = client.bug_get(bug_id)
    bug = data.get("bug", data)
    status = str(bug.get("status", ""))
    return {
        "bug_id": bug_id,
        "status": status,
        "title": bug.get("title", ""),
        "regression_suggested": status in ("resolved", "closed"),
        "message": ("已修复，建议回归关联场景" if status in ("resolved", "closed")
                    else f"当前状态: {status}"),
    }


def reconcile_refs(workspace: str) -> list[dict]:
    """对账：succeeded 但缺 zt_ref 锚点登记的作业补登记（崩溃窗口补账）。

    幂等键 UNIQUE 保底，不会产生重复行。
    """
    fixed = []
    jobs = sf_refs_store.list_jobs(workspace=workspace, status="succeeded")
    for job in jobs:
        zt_ref = job.get("zt_ref") or ""
        if not zt_ref:
            continue
        payload = job.get("payload") or {}
        kind = job.get("kind", "")
        if kind == "story_create":
            delta_id = payload.get("delta_id", "")
            existing = sf_refs_store.list_refs(
                workspace=workspace, ref_type="zt_story", ref=zt_ref,
                linked_type="delta", linked=delta_id)
            if delta_id and not existing:
                sf_refs_store.register_ref(
                    workspace, "zt_story", zt_ref, "delta", delta_id,
                    registered_by="system:reconcile")
                fixed.append(job["job_id"])
        elif kind == "bug_create":
            spq_id = payload.get("spq_id", "")
            existing = sf_refs_store.list_refs(
                workspace=workspace, ref_type="zt_bug", ref=zt_ref,
                linked_type="spq", linked=spq_id)
            if spq_id and not existing:
                sf_refs_store.register_ref(
                    workspace, "zt_bug", zt_ref, "spq", spq_id,
                    registered_by="system:reconcile")
                fixed.append(job["job_id"])
    return fixed


# ══════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════

def _resolve_product(product: str) -> int:
    aliases = {"tdm": 251}
    v = (product or "tdm").strip().lower()
    if v in aliases:
        return aliases[v]
    return int(v)


def _story_url(story_id: str) -> str:
    return f"{get_zentao_config()['base_url'].rstrip('/')}/story-view-{story_id}.html"


def _bug_url(bug_id: str) -> str:
    return f"{get_zentao_config()['base_url'].rstrip('/')}/bug-view-{bug_id}.html"


def _find_story_for_delta(workspace: str, delta_id: str) -> str:
    """经 sf_external_refs 反查 delta 关联的禅道故事编号。"""
    rows = sf_refs_store.list_refs(
        workspace=workspace, ref_type="zt_story",
        linked_type="delta", linked=delta_id)
    return rows[0]["ref"] if rows else ""


def read_run_verdict(workspace: str, run_id: str,
                     scenario_id: str) -> tuple[Optional[str], Optional[dict]]:
    """从运行报告读取场景 verdict（纯读）。

    Returns:
        (verdict, case_dict)；未找到返回 (None, None)
    """
    from specstd.workspace import get_active_workspace
    ws = get_active_workspace()
    if not ws:
        return None, None
    run_dir = Path(ws.root) / ".specguard" / "reports" / run_id
    run_json = run_dir / "run.json"
    if not run_json.is_file():
        # 断点批次目录 {EX-xxx}-b{N}/run.json
        for sub in sorted(run_dir.glob("*-b*/run.json")):
            run_json = sub
            break
    if not run_json.is_file():
        return None, None
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None, None
    for case in (data.get("cases") or []):
        if str(case.get("id") or case.get("scenario_id") or "") == scenario_id:
            return str(case.get("verdict", "")).upper(), case
    return None, None


def build_repro_steps(workspace: str, run_id: str,
                      scenario_id: str) -> str:
    """复现步骤装配（repro_builder 主入口）：doc 层 given/when/then + 执行证据。

    场景 YAML 从工作区场景库读取（covers 定位），执行证据从 run 报告取
    失败断言/差异摘要。
    """
    from workbench.backend.services.zentao.repro_builder import build_steps
    return build_steps(workspace, run_id, scenario_id)
