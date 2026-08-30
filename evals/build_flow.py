#!/usr/bin/env python3
"""evals/build_flow.py — 从技能文件重建 golden flow 定义（T-1042 可扩展性入口）。

场景：generate-scenario 技能改了（新增/删除工具、调整流程）→ flow 定义需要跟着变。
本工具从技能 frontmatter 的 depends_tools（权威工具清单），对
`evals/flows/{name}.flow.json` 做**确定性合并重建**：

  - 技能新出现的工具 → 按（基名, action）路由到既有阶段（ACTION_STAGE_MAP），
    归不进任何既有阶段的追加为新阶段（required=false，人工定夺）
  - 技能已删除的工具 → 从阶段候选中摘除并记录进 drift 报告；基名候选（action=""）
    被同名任意 action 的 depends 条目蕴含，不算删除
  - 人工标注（label/required/note/hard_order）原样保留——重建只动工具集，不动语义

用法：
  python evals/build_flow.py --skill agent/skills/generate-scenario.md            # 重建（写回）
  python evals/build_flow.py --skill ... --check                                  # 只查漂移不写（可挂门禁）
  python evals/build_flow.py --skill ... --out evals/flows/my-flow.flow.json      # 新 flow

诚实边界：合并结果仍是「草稿级」——步骤顺序/必选性等语义判断留给人工复核，
报告里明确列出本次变更；skill 正文与 flow 定义冲突时以 skill 为准并提示复核。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from evals.replay import normalize_tool_unit  # noqa: E402

# depends_tools 条目 → 阶段 key 的确定性路由（基名+action 精确；基名-only 落默认阶段）
ACTION_STAGE_MAP: dict[tuple[str, str], str] = {
    ("knowledge", ""): "read_skill",
    ("info_pack", ""): "read_requirement",
    ("spec", "read"): "read_requirement",
    ("spec", "list"): "read_requirement",
    ("spec", "search"): "read_requirement",
    ("scenario", "next_id"): "get_id",
    ("scenario", "list"): "find_reference",
    ("scenario", "read"): "find_reference",
    ("query_registry", ""): "query_registry",
    ("validate", ""): "validate",
    ("draft", "write"): "write_draft",
    ("scenario", "suggest_deps"): "suggest_deps",
    ("scenario", "check_dag"): "dag_design",
    ("scenario", "run"): "trial_run",
    ("attribution", ""): "trial_run",
    ("draft", "promote"): "promote",
    ("draft", "promote_batch"): "promote",
}

# flow 特有工具（不在技能 depends_tools 属常态：权限预检/DAG/试跑/promote 等），
# INFO 静默集——只列 depends_tools 覆盖缺口时不再重复报这些已知旁路
_FLOW_SPECIFIC_BASES = {
    "knowledge", "precheck_permission", "resolve_account", "check_dag",
    "run_scenario", "attribution", "promote_draft", "promote_drafts",
}


def parse_skill(path: str | Path) -> dict:
    """解析技能文件：frontmatter（name/version/depends_tools）。

    depends_tools 形如 `[info_pack(action=read), spec(action=read), ...]`——
    工具 token 用「tool 或 tool(action=x)」正则提取（逗号是分隔符不是 token 的一部分）。
    """
    text = Path(path).read_text(encoding="utf-8")
    fm: dict = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"^(\w+):\s*(.*)$", line)
            if not mm:
                continue
            k, v = mm.group(1), mm.group(2).strip()
            if k == "depends_tools":
                # 提取 tool / tool(action=x)；丢弃分隔符与方括号
                tools = re.findall(r"[a-z_]+(?:\(action=[a-z_]+\))?", v)
                fm[k] = [t for t in tools if t not in ("action", "depends_tools")]
            else:
                fm[k] = v.strip("[]\"'")
    return {"frontmatter": fm, "version": str(fm.get("version", "?")),
            "name": str(fm.get("name", Path(path).stem))}


def _implied_by_deps(unit: tuple[str, str], dep_keys: set[tuple[str, str]]) -> bool:
    """flow 候选是否被技能 depends 蕴含：完全相等，或基名候选被同名任意 action 蕴含。"""
    if unit in dep_keys:
        return True
    return unit[1] == "" and any(d[0] == unit[0] for d in dep_keys)


def build_flow(skill_path: str | Path, out_path: str | Path, check: bool = False,
               flow_name: str | None = None) -> int:
    skill = parse_skill(skill_path)
    out = Path(out_path)
    dep_tools = skill["frontmatter"].get("depends_tools", [])
    dep_keys = {normalize_tool_unit(t) for t in dep_tools}

    existing: dict = {}
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    if not existing:
        return _no_existing_flow(skill, str(skill_path), dep_tools, out, check, flow_name)

    drift: list[str] = []
    notes: list[str] = []
    stages = existing.get("stages", [])
    key_set = {s["key"] for s in stages}

    # 1) 技能工具 → 路由进既有阶段（按 ACTION_STAGE_MAP：精确 (基名,action) 命中，
    #    回退 (基名,"") 基名键——info_pack 等按基名登记的阶段）；归不进的追加新阶段。
    #    语义：depends_tools 只做「增量补充」——绝不摘除既有候选。flow 是 depends
    #    的超集（权限/DAG/试跑/promote 等阶段本就不在 depends_tools，旧会话
    #    legacy 候选也必须保留供重放）；「flow 有而 skill 无」降为 INFO 提示人工复核。
    routed: dict[str, list] = {}
    for orig in dep_tools:
        unit = normalize_tool_unit(orig)
        stage_key = ACTION_STAGE_MAP.get(unit) or ACTION_STAGE_MAP.get((unit[0], ""))
        if stage_key and stage_key in key_set:
            routed.setdefault(stage_key, []).append(orig)
        else:
            new_key = f"new_{unit[0]}_{unit[1] or 'x'}"
            drift.append(f"技能新工具 {orig!r} 无法路由到既有阶段（基名 {unit[0]}）"
                         f"——已追加为新可选阶段，请人工归位/定必选性")
            stages.append({"key": new_key, "label": orig, "tools": [orig], "required": False,
                           "note": "build_flow 自动追加（技能 depends_tools 新条目），人工定夺",
                           "_new": True})
            key_set.add(new_key)
            routed[new_key] = [orig]
    for s in stages:
        for orig in routed.get(s["key"], []):
            # 去重按蕴含关系：既有候选是基名（任意 action）或同 action 即已覆盖
            unit = normalize_tool_unit(orig)
            covered = any(
                unit[0] == normalize_tool_unit(t)[0]
                and normalize_tool_unit(t)[1] in ("", unit[1])
                for t in s["tools"])
            if not covered:
                s["tools"].append(orig)

    # 2) INFO：flow 候选不被 depends 蕴含且非已知豁免 → 列出供人工复核（不摘除）
    for s in stages:
        uncovered = [t for t in s.get("tools", [])
                     if not _implied_by_deps(normalize_tool_unit(t), dep_keys)
                     and normalize_tool_unit(t)[0] not in _FLOW_SPECIFIC_BASES]
        if uncovered:
            notes.append(f"阶段「{s['label']}」候选 {uncovered} 不在 skill depends_tools"
                         f"（flow 特有/旧会话兼容候选——若确认废弃请人工摘除）")

    existing["stages"] = stages
    existing["_meta"] = {
        "rebuilt_at": datetime.now().isoformat(timespec="seconds"),
        "skill": str(skill_path), "skill_version": skill["version"],
        "depends_tools": dep_tools, "drift": drift, "notes": notes,
    }
    if check:
        if drift:
            print(f"[build_flow --check] 检测到 {len(drift)} 处漂移（flow 定义滞后于 skill）:")
            for d in drift:
                print(f"  - {d}")
            return 1
        print("[build_flow --check] 无漂移：flow 定义已覆盖 skill depends_tools 全部工具")
        for n in notes:
            print(f"  ℹ {n}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_flow] 已重建: {out}（skill={skill_path} v{skill['version']}，"
          f"depends_tools {len(dep_tools)} 条，漂移 {len(drift)} 处）")
    for d in drift:
        print(f"  - {d}")
    if drift:
        print("  ⚠ 存在自动处置项（追加/摘除），请人工复核阶段语义后提交")
    return 0


def _no_existing_flow(skill: dict, skill_path: str | Path, dep_tools: list, out: Path,
                      check: bool, flow_name: str | None) -> int:
    """目标 flow 文件不存在：生成按 depends_tools 路由的初始草稿（全可选，人工定必选）。"""
    stages: list[dict] = []
    seen: dict[str, dict] = {}
    for orig in dep_tools:
        unit = normalize_tool_unit(orig)
        key = ACTION_STAGE_MAP.get(unit) or f"new_{unit[0]}_{unit[1] or 'x'}"
        if key in seen:
            if normalize_tool_unit(orig) not in {normalize_tool_unit(t) for t in seen[key]["tools"]}:
                seen[key]["tools"].append(orig)
        else:
            st = {"key": key, "label": orig, "tools": [orig], "required": False,
                  "note": "build_flow 初始草稿——label/required/note 请人工定夺"}
            stages.append(st)
            seen[key] = st
    draft = {
        "id": flow_name or skill["name"],
        "title": f"{skill['name']} golden flow（初始草稿）",
        "source": f"{skill_path} v{skill['version']}",
        "rebuild": "python evals/build_flow.py --skill <技能文件>",
        "hard_order": [],
        "benign_bases": ["todo_write", "topic", "gate_dock_status", "parent"],
        "stages": stages,
        "_meta": {"rebuilt_at": datetime.now().isoformat(timespec="seconds"),
                  "skill": str(skill_path), "skill_version": skill["version"],
                  "depends_tools": dep_tools, "drift": []},
    }
    if check:
        print(f"[build_flow --check] flow 文件不存在: {out}——视为漂移（缺定义）")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_flow] 初始草稿已生成: {out}（{len(stages)} 阶段，全可选——"
          f"label/required/note/hard_order 请人工定夺后再作为评测基线）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从技能文件重建 golden flow 定义（确定性合并）")
    ap.add_argument("--skill", required=True, help="技能文件路径（含 depends_tools frontmatter）")
    ap.add_argument("--out", default=str(SG_ROOT / "evals" / "flows" / "generate-scenario.flow.json"),
                    help="flow 定义输出路径（默认 generate-scenario.flow.json）")
    ap.add_argument("--check", action="store_true",
                    help="只查漂移不写回（有漂移退出码 1，可挂门禁）")
    args = ap.parse_args(argv)
    return build_flow(args.skill, args.out, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
