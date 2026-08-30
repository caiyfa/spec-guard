"""evals.flowpath — 会话路径重放：§16.1 flow 图基线 vs 实际走径逐节点比对（T-1042）。

用户视角的问题：「让它创建测试用例，它走的路和应该走的路差在哪？」
本模块把基线文档 §16.1 的 mermaid flow 图编码为**可执行的 golden flow**
（12 个阶段节点，必选/可选 + 硬顺序约束），对单个会话做逐节点重放：

  - 实际路径：会话工具调用序列 →（基名, action）单元 → 映射到阶段（首次出现步号+次数）
  - 判定四态：in_order 顺序正确 / out_of_order 乱序 / missing 缺失必需 / skipped 跳过可选
  - 计划外工具：基线外旁支（benign 元工具剔除），旁支不等于违规，但跑偏可见
  - 产物：着色 mermaid 路径图（🟩对 🟨乱序 🟥缺失 ⬜跳过）+ 差异明细表（带步号证据）

与 replay.score_trajectory 的关系：replay 出聚合指标（会话集层面），本模块出
**样本级可解释证据**（单会话层面）——聚合发现「序列合理率 56%」，路径重放回答
「具体哪个会话、第几步、先写了草稿还是先读了需求」。

硬顺序约束（只设两条，防噪声；其余为软顺序不判乱序）：
  read_requirement < write_draft（生成前必读需求——§16 硬约束 1）
  validate < write_draft（写草稿前必校验——§16 硬约束 2）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evals.baseline import SessionScan, scan_session
from evals.replay import (
    is_generate_scenario_session,
    normalize_tool_unit,
    scan_units,
)

# ══════════════════════════════════════════════════════════
# golden flow：§16.1 主流程的阶段级编码（顺序即 flow 图主链）
# ══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FlowStage:
    key: str
    label: str            # 中文节点名（对齐 §16.1 流程图措辞）
    units: tuple          # （基名, action）候选；action="" 表示任意 action
    required: bool        # 必选=True（缺失即红）；False=可选（缺失灰）
    note: str = ""        # 判定说明（差异表里给上下文）


def _st(*specs: str) -> tuple:
    """阶段候选简写：助记/legacy/基名字符串 → 归一单元元组。"""
    return tuple(normalize_tool_unit(s) for s in specs)


FLOW_STAGES: list[FlowStage] = [
    FlowStage("read_skill", "取技能正文", _st("knowledge", "read_skill"), False,
              "knowledge(action=skill)——正文不常驻，执行任务前先取"),
    FlowStage("read_requirement", "读需求", _st("info_pack", "read_info_pack",
                                                "spec(action=read)", "spec(action=list)",
                                                "spec(action=search)", "read_spec",
                                                "list_spec_files"), True,
              "info_pack(action=read) 或 spec(action=read, anchor=FR-xxx)"),
    FlowStage("get_id", "取场景 ID", _st("scenario(action=next_id)", "next_scenario_id"), True,
              "scenario(action=next_id)"),
    FlowStage("query_registry", "查注册表", _st("query_registry"), True,
              "确认 tool/oracle 已注册（禁编造）"),
    FlowStage("find_reference", "找同类参照", _st("scenario(action=list)", "scenario(action=read)",
                                                  "list_scenarios", "read_scenario"), True,
              "scenario(action=list) 定位同类 → 读 1~2 个参照"),
    FlowStage("permission_precheck", "权限预检/账号解析", _st("precheck_permission",
                                                              "resolve_account"), False,
              "权限/写操作场景必做（K-055），普通场景可跳过"),
    FlowStage("dag_design", "DAG 拓扑预演", _st("scenario(action=check_dag)", "check_dag"), False,
              "≥2 场景时必做（K-021），单场景可跳"),
    FlowStage("validate", "validate 校验", _st("validate"), True,
              "生成后必须 validate（UNKNOWN_TPL/BODY_KEY 硬伤拦在这里）"),
    FlowStage("write_draft", "写草稿", _st("draft(action=write)", "write_draft"), True,
              "draft(action=write) 写入 drafts/ 并自动登记三闸"),
    FlowStage("suggest_deps", "依赖建议", _st("scenario(action=suggest_deps)", "suggest_deps"), False,
              "写完草稿必做（K-046），拒绝建议须说明"),
    FlowStage("trial_run", "试跑/归因", _st("scenario(action=run)", "run_scenario",
                                            "attribution"), False,
              "用户要求「跑一下」时；失败走 attribution 归因"),
    FlowStage("promote", "入库 promote", _st("draft(action=promote)", "draft(action=promote_batch)",
                                             "promote_draft", "promote_drafts"), False,
              "用户明确确认后；自带三闸"),
]

# 硬顺序约束（earlier, later)：both hit 且 earlier 首步晚于 later → later 判乱序
HARD_ORDER: tuple[tuple[str, str], ...] = (
    ("read_requirement", "write_draft"),
    ("validate", "write_draft"),
)

# 计划外统计时剔除的 benign 元工具（会话基建，不代表跑偏）
BENIGN_BASES = {"todo_write", "topic", "gate_dock_status", "parent"}

_STAGE_BY_KEY = {s.key: s for s in FLOW_STAGES}


def _unit_to_stage(unit: tuple[str, str]) -> str | None:
    """单元 → 所属阶段 key（flow 图视角；一单元只归一个阶段，先命中先得）。"""
    b, a = unit
    for st in FLOW_STAGES:
        for cb, ca in st.units:
            if b == cb and (ca == "" or a == ca):
                return st.key
    return None


@dataclass
class StageState:
    key: str
    label: str
    required: bool
    status: str                  # in_order / out_of_order / missing / skipped
    first_step: int | None = None   # 首次出现步号（1-based，工具调用序）
    times: int = 0               # 该阶段被命中的调用次数
    tools: list = field(default_factory=list)  # 命中的原始工具名（去重）
    note: str = ""


@dataclass
class FlowTrace:
    session_id: str
    is_generate: bool
    stages: list[StageState]
    deviations: list[str]        # 人读差异句（带步号证据）
    extras: list[str]            # 计划外工具（base×次数，benign 已剔除）
    n_tool_calls: int = 0
    total_tokens: int = 0
    purpose: str = ""
    workspace: str = ""

    @property
    def n_missing(self) -> int:
        return sum(1 for s in self.stages if s.status == "missing")

    @property
    def n_out_of_order(self) -> int:
        return sum(1 for s in self.stages if s.status == "out_of_order")


def trace_session(path: str | Path) -> FlowTrace | None:
    """单会话路径重放：§16.1 golden flow vs 实际走径。解析失败返回 None。"""
    scan = scan_session(path)
    if scan is None:
        return None
    return trace_scan(scan)


def trace_scan(scan: SessionScan) -> FlowTrace:
    """对已扫描的会话做路径重放（复用 scan，避免重复读盘）。"""
    units = scan_units(scan)
    # 每个工具调用 = 一步；单元映射到阶段，记首次步号/次数/原始名
    first: dict[str, int] = {}
    times: dict[str, int] = {}
    stage_tools: dict[str, list] = {}
    extras: dict[str, int] = {}
    for i, unit in enumerate(units, start=1):
        key = _unit_to_stage(unit)
        if key is None:
            if unit[0] not in BENIGN_BASES:
                # 展示键带 action（sync_workspace 归一为 spec(sync)——基名裸列会误导成 read_spec）
                disp = f"{unit[0]}({unit[1]})" if unit[1] else unit[0]
                extras[disp] = extras.get(disp, 0) + 1
            continue
        times[key] = times.get(key, 0) + 1
        first.setdefault(key, i)
        raw_name = scan.tool_calls_raw[i - 1][0] if i - 1 < len(scan.tool_calls_raw) else unit[0]
        if raw_name not in stage_tools.setdefault(key, []):
            stage_tools[key].append(raw_name)

    states: list[StageState] = []
    for st in FLOW_STAGES:
        if st.key in times:
            states.append(StageState(st.key, st.label, st.required, "in_order",
                                     first[st.key], times[st.key], stage_tools.get(st.key, [])))
        elif st.required:
            states.append(StageState(st.key, st.label, True, "missing", note=st.note))
        else:
            states.append(StageState(st.key, st.label, False, "skipped", note=st.note))

    # 硬顺序约束 → 乱序判定（flag 后来者：它开跑早了）
    deviations: list[str] = []
    for earlier, later in HARD_ORDER:
        if earlier in first and later in first and first[earlier] > first[later]:
            if _STAGE_BY_KEY[later].key and states[_state_idx(states, later)].status != "missing":
                states[_state_idx(states, later)].status = "out_of_order"
            deviations.append(
                f"「{_STAGE_BY_KEY[later].label}」（第 {first[later]} 步）先于"
                f"「{_STAGE_BY_KEY[earlier].label}」（第 {first[earlier]} 步）——"
                f"违反基线顺序（应先{_STAGE_BY_KEY[earlier].label}再{_STAGE_BY_KEY[later].label}）")
    for st in states:
        if st.status == "missing":
            deviations.append(f"缺失必需阶段「{st.label}」——{st.note}")

    return FlowTrace(
        session_id=scan.session_id,
        is_generate=is_generate_scenario_session(scan),
        stages=states,
        deviations=deviations,
        extras=[f"{b}×{n}" for b, n in sorted(extras.items(), key=lambda kv: -kv[1])],
        n_tool_calls=scan.n_tool_calls,
        total_tokens=scan.total_tokens,
        purpose=scan.purpose,
        workspace=scan.workspace,
    )


def _state_idx(states: list[StageState], key: str) -> int:
    for i, s in enumerate(states):
        if s.key == key:
            return i
    return -1


# ══════════════════════════════════════════════════════════
# 渲染：着色 mermaid 路径图 + 差异明细表
# ══════════════════════════════════════════════════════════

_STATUS_GLYPH = {"in_order": "✓", "out_of_order": "⇄", "missing": "✗", "skipped": "－"}
_STATUS_CN = {"in_order": "顺序正确", "out_of_order": "乱序", "missing": "缺失必需",
              "skipped": "跳过（可选）"}


def render_flow_mermaid(trace: FlowTrace) -> str:
    """把重放结果着色回 §16.1 阶段级 flow 图（🟩对 🟨乱序 🟥缺失 ⬜跳过）。"""
    cls = {"in_order": "hit", "out_of_order": "warn", "missing": "missing", "skipped": "skip"}
    lines = ["flowchart TD"]
    for i, st in enumerate(trace.stages, start=1):
        cnt = f" ×{st.times}" if st.times > 1 else ""
        step = f"（第{st.first_step}步）" if st.first_step else ""
        label = f"{st.label}{cnt}{step} {_STATUS_GLYPH[st.status]}"
        lines.append(f'    S{i}["{i}. {label}"]:::{cls[st.status]}')
    for i in range(len(trace.stages) - 1):
        lines.append(f"    S{i + 1} --> S{i + 2}")
    lines += [
        "    classDef hit fill:#d4edda,stroke:#28a745,color:#155724",
        "    classDef warn fill:#fff3cd,stroke:#856404,color:#856404",
        "    classDef missing fill:#f8d7da,stroke:#dc3545,color:#721c24",
        "    classDef skip fill:#e9ecef,stroke:#6c757d,color:#6c757d,stroke-dasharray: 5 5",
    ]
    return "\n".join(lines)


def render_trace_markdown(trace: FlowTrace) -> str:
    """单会话路径重放报告（mermaid 图 + 差异明细 + 计划外工具）。"""
    verdict = "是" if trace.is_generate else "否（基线仅供参考）"
    n_dev = len(trace.deviations)
    lines = [
        f"# 会话路径重放：{trace.session_id}",
        "",
        f"> purpose={trace.purpose or '?'} · workspace={trace.workspace or '?'} · "
        f"工具调用 {trace.n_tool_calls} 步 · token {trace.total_tokens:,} · "
        f"生成会话判定：**{verdict}** · 差异 {n_dev} 处",
        "",
        "## 路径重放图（§16.1 基线 vs 实际）",
        "",
        "```mermaid",
        render_flow_mermaid(trace),
        "```",
        "",
        "## 差异明细",
        "",
        "| # | 阶段 | 判定 | 实际证据 |",
        "|---|------|------|----------|",
    ]
    for i, st in enumerate(trace.stages, start=1):
        ev = (f"第 {st.first_step} 步 · {st.times} 次 · 工具 {'、'.join(st.tools)}"
              if st.first_step else f"（{st.note}）" if st.status == "skipped" else "全程未调用")
        lines.append(f"| {i} | {st.label} | {_STATUS_CN[st.status]} | {ev} |")

    if trace.deviations:
        lines += ["", "### 跑偏点", ""]
        lines += [f"- {d}" for d in trace.deviations]
    else:
        lines += ["", "**无跑偏：全部必需阶段按基线顺序走完。**"]

    lines += ["", "## 计划外工具（基线外旁支）", ""]
    if trace.extras:
        lines.append(f"- {'、'.join(trace.extras)}")
        lines.append("")
        lines.append("> 旁支不等于违规（排查/执行类工具常合理出现），但对照 flow 图可见精力去向；"
                     "benign 元工具（todo_write/topic/gate_dock_status/parent）已剔除。")
    else:
        lines.append("- （无——全部调用都落在基线阶段内）")
    lines.append("")
    lines.append("> 图例：🟩 in_order 顺序正确 · 🟨 out_of_order 乱序 · 🟥 missing 缺失必需 · "
                 "⬜ skipped 跳过可选；硬顺序仅两条（读需求<写草稿、校验<写草稿），其余软顺序不判乱序防噪声。")
    return "\n".join(lines)


def trace_all_generate(sessions_root: str | Path, out_dir: str | Path,
                       limit: int | None = None) -> dict:
    """批量：对全部「创建测试用例」会话落盘路径重放报告，返回索引摘要。

    输出 {out_dir}/{sid}.md + index.md（按差异数降序——最跑偏的排最前）。
    """
    import glob
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pattern = str(Path(sessions_root) / "**" / "*.jsonl")
    files = [f for f in glob.glob(pattern, recursive=True)
             if "_metrics" not in f and "_truncated" not in f.replace("\\", "/")]
    if limit:
        files = files[:limit]

    index: list[dict] = []
    for f in files:
        scan = scan_session(f)
        if scan is None or not is_generate_scenario_session(scan):
            continue
        trace = trace_scan(scan)
        md = render_trace_markdown(trace)
        (out / f"{trace.session_id}.md").write_text(md, encoding="utf-8")
        index.append({
            "session_id": trace.session_id,
            "path": str(f),
            "deviations": len(trace.deviations),
            "missing": trace.n_missing,
            "out_of_order": trace.n_out_of_order,
            "tool_calls": trace.n_tool_calls,
        })
    index.sort(key=lambda x: (-x["deviations"], -x["missing"]))

    idx_lines = [
        "# 路径重放索引（生成会话，按差异数降序）",
        "",
        f"> 共 {len(index)} 个生成会话；来源 `{sessions_root}`",
        "",
        "| 会话 | 差异 | 缺失必需 | 乱序 | 工具步数 |",
        "|------|------|----------|------|----------|",
    ]
    for r in index:
        idx_lines.append(
            f"| [{r['session_id']}]({r['session_id']}.md) | {r['deviations']} "
            f"| {r['missing']} | {r['out_of_order']} | {r['tool_calls']} |")
    (out / "index.md").write_text("\n".join(idx_lines), encoding="utf-8")
    return {"traced": len(index), "out_dir": str(out), "index": index}
