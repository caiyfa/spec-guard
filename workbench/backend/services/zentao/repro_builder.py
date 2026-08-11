"""workbench/services/zentao/repro_builder.py — 复现步骤装配器（M06 G6，T-055）。

入口①（from-run）提单时，把场景 doc 层 given/when/then 与 run 执行证据
（失败断言/差异摘要）合成为禅道 steps 文本。
纯读：场景 YAML 与 run 报告都是既有产物，本模块零副作用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def _find_scenario(workspace_root: Path, scenario_id: str):
    """按 id 在场景库定位场景（引擎 loader，纯读）。"""
    from engine.scenario_loader import load_scenarios, ScenarioLoadError
    scenarios_root = workspace_root / "scenarios"
    if not scenarios_root.is_dir():
        return None
    try:
        for s in load_scenarios(scenarios_root):
            if s.id == scenario_id:
                return s
    except ScenarioLoadError:
        return None
    return None


def _doc_text(doc: dict, key: str) -> str:
    """doc 层字段取值（兼容字符串/列表）。"""
    val = doc.get(key, "")
    if isinstance(val, list):
        return "\n".join(f"- {v}" for v in val)
    return str(val or "")


def _run_case(workspace_root: Path, run_id: str,
              scenario_id: str) -> Optional[dict]:
    """从运行报告读取该场景的 case（含失败断言/差异）。"""
    run_dir = workspace_root / ".specguard" / "reports" / run_id
    run_json = run_dir / "run.json"
    if not run_json.is_file():
        for sub in sorted(run_dir.glob("*-b*/run.json")):
            run_json = sub
            break
    if not run_json.is_file():
        return None
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for case in (data.get("cases") or []):
        if str(case.get("id") or case.get("scenario_id") or "") == scenario_id:
            return case
    return None


def build_steps(workspace: str, run_id: str, scenario_id: str) -> str:
    """合成复现步骤（doc 层 + 执行证据）。"""
    from specstd.workspace import get_active_workspace
    ws = get_active_workspace()
    root = Path(ws.root) if ws else None
    lines = [f"## 复现步骤（场景 {scenario_id}）"]
    if root:
        scenario = _find_scenario(root, scenario_id)
        if scenario:
            doc = scenario.doc or {}
            given = _doc_text(doc, "given")
            when = _doc_text(doc, "when")
            then = _doc_text(doc, "then")
            if given:
                lines.append("\n### 前置\n" + given)
            if when:
                lines.append("\n### 操作\n" + when)
            if then:
                lines.append("\n### 预期\n" + then)
        else:
            lines.append("（场景文件未找到，仅附执行证据）")
        case = _run_case(root, run_id, scenario_id)
        if case:
            lines.append(f"\n## 执行证据（run {run_id}）")
            lines.append(f"- verdict: {case.get('verdict')}")
            msg = case.get("message") or case.get("failure") or ""
            if msg:
                lines.append(f"- 失败信息: {str(msg)[:500]}")
            diffs = case.get("diffs") or case.get("assertions") or []
            if diffs:
                lines.append("- 断言差异:")
                for d in diffs[:5]:
                    lines.append(f"  - {str(d)[:200]}")
        lines.append(f"\n## 关联\n- run: {run_id}\n- 场景: {scenario_id}")
    else:
        lines.append("（无工作区上下文）")
    return "\n".join(lines)
