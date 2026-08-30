"""evals.flowpath — 会话路径重放：golden flow 基线 vs 实际走径逐节点比对（T-1042）。

用户视角的问题：「让它创建测试用例，它走的路和应该走的路差在哪？」
本模块把 golden flow 编码为**定义驱动的阶段图**（JSON 单一事实源
`evals/flows/{name}.flow.json`，内置兜底），对单个会话做逐节点重放：

  - 实际路径：会话工具调用序列 →（基名, action）单元 → 映射到阶段（首次出现步号+次数）
  - 判定四态：in_order 顺序正确 / out_of_order 乱序 / missing 缺失必需 / skipped 跳过可选
  - 计划外工具：基线外旁支（benign 元工具剔除），旁支不等于违规，但跑偏可见
  - 产物：着色 mermaid 路径图（🟩对 🟨乱序 🟥缺失 ⬜跳过）+ 差异明细表（带步号证据）

可扩展重建（改了 skill / 工具之后）：
  python evals/build_flow.py --skill agent/skills/generate-scenario.md   # 从技能重建 flow 定义
  python evals/run_replay.py --flow                                     # 可视化当前 golden flow
定义只描述「阶段→工具候选 + 必选性 + 硬顺序」，工具名三种形态（助记/legacy/
基名+action）在归一层统一消化（见 replay.normalize_tool_unit），换工具名不改图。

与 replay.score_trajectory 的关系：replay 出聚合指标（会话集层面），本模块出
**样本级可解释证据**（单会话层面）——聚合发现「序列合理率 56%」，路径重放回答
「具体哪个会话、第几步、先写了草稿还是先读了需求」。

实时扫描（工作台对话面板）：会话 JSONL 每轮增量落盘（runtime 每轮 save），
后端按 session_id 读行 → baseline.scan_rows → trace_scan，即可在对话进行中
拿到当前跑偏态——见 workbench GET /agent/sessions/{id}/flow-trace。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from evals.baseline import SessionScan, scan_session
from evals.replay import (
    is_generate_scenario_session,
    normalize_tool_unit,
    scan_units,
)

_FLOWS_DIR = Path(__file__).resolve().parent / "flows"
DEFAULT_FLOW_NAME = "generate-scenario"

# ══════════════════════════════════════════════════════════
# flow 定义（JSON 单一事实源；内置兜底=文件缺失/损坏时诚实降级）
# ══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FlowStage:
    key: str
    label: str            # 中文节点名（对齐 §16.1 流程图措辞）
    units: tuple          # （基名, action）候选；action="" 表示任意 action
    required: bool        # 必选=True（缺失即红）；False=可选（缺失灰）
    note: str = ""        # 判定说明（差异表里给上下文）


@dataclass(frozen=True)
class FlowEdge:
    """拓扑边：阶段间真实走向（§16.1 的条件分支与回边，打破线性链失真）。

    kind: main 主路径 / cond 条件分支（多场景/涉权限/用户要试跑） / loop 回边
    （修复重校、FAIL 归因重跑、下一场景）——线性链只表达 main，loop/cond 是
    「流程本来有条件」的证据面。
    """
    from_key: str
    to_key: str
    label: str = ""
    kind: str = "main"


@dataclass(frozen=True)
class FlowGate:
    """交互门（对话层决策点，无工具调用：规划确认/入库确认）。

    只作拓扑语义节点（菱形展示），不参与四态判定——门的「经过」由相邻阶段
    边推导（find_reference→…→validate 视为穿过规划门）。
    """
    key: str
    label: str


@dataclass(frozen=True)
class FlowDef:
    """golden flow 定义：阶段图 + 硬顺序 + 拓扑边 + 交互门 + benign 集合。"""
    id: str
    title: str
    source: str
    stages: tuple[FlowStage, ...]
    hard_order: tuple[tuple[str, str], ...]
    benign_bases: frozenset[str]
    topology: tuple[FlowEdge, ...] = ()
    gates: tuple[FlowGate, ...] = ()
    rebuilt_from_file: bool = False   # True=来自 evals/flows/*.json；False=内置兜底

    @property
    def stage_by_key(self) -> dict[str, FlowStage]:
        return {s.key: s for s in self.stages}


def _builtin_flow_def() -> FlowDef:
    """内置兜底定义（与 generate-scenario.flow.json 同源维护）。"""
    def st(*specs: str) -> tuple:
        return tuple(normalize_tool_unit(s) for s in specs)
    return FlowDef(
        id="generate-scenario",
        title="创建测试用例 golden flow",
        source="内置兜底（evals/flows/generate-scenario.flow.json 缺失）",
        stages=(
            FlowStage("read_skill", "取技能正文", st("knowledge", "read_skill"), False,
                      "knowledge(action=skill)——正文不常驻，执行任务前先取"),
            FlowStage("read_requirement", "读需求",
                      st("info_pack", "read_info_pack", "spec(action=read)", "spec(action=list)",
                         "spec(action=search)", "read_spec", "list_spec_files"), True,
                      "info_pack(action=read) 或 spec(action=read, anchor=FR-xxx)"),
            FlowStage("get_id", "取场景 ID", st("scenario(action=next_id)", "next_scenario_id"), True,
                      "scenario(action=next_id)"),
            FlowStage("query_registry", "查注册表", st("query_registry"), True,
                      "确认 tool/oracle 已注册（禁编造）"),
            FlowStage("find_reference", "找同类参照",
                      st("scenario(action=list)", "scenario(action=read)",
                         "list_scenarios", "read_scenario"), True,
                      "scenario(action=list) 定位同类 → 读 1~2 个参照"),
            FlowStage("permission_precheck", "权限预检/账号解析",
                      st("precheck_permission", "resolve_account"), False,
                      "权限/写操作场景必做（K-055），普通场景可跳过"),
            FlowStage("dag_design", "DAG 拓扑预演",
                      st("scenario(action=check_dag)", "check_dag"), False,
                      "≥2 场景时必做（K-021），单场景可跳"),
            FlowStage("validate", "validate 校验", st("validate"), True,
                      "生成后必须 validate（UNKNOWN_TPL/BODY_KEY 硬伤拦在这里）"),
            FlowStage("write_draft", "写草稿", st("draft(action=write)", "write_draft"), True,
                      "draft(action=write) 写入 drafts/ 并自动登记三闸"),
            FlowStage("suggest_deps", "依赖建议",
                      st("scenario(action=suggest_deps)", "suggest_deps"), False,
                      "写完草稿必做（K-046），拒绝建议须说明"),
            FlowStage("trial_run", "试跑/归因",
                      st("scenario(action=run)", "run_scenario", "attribution"), False,
                      "用户要求「跑一下」时；失败走 attribution 归因"),
            FlowStage("promote", "入库 promote",
                      st("draft(action=promote)", "draft(action=promote_batch)",
                         "promote_draft", "promote_drafts"), False,
                      "用户明确确认后；自带三闸"),
        ),
        hard_order=(("read_requirement", "write_draft"), ("validate", "write_draft")),
        benign_bases=frozenset({"todo_write", "topic", "gate_dock_status", "parent", "flow"}),
        gates=(
            FlowGate("gate_plan", "规划确认"),
            FlowGate("gate_promote", "确认入库"),
        ),
        # §16.1 条件拓扑：主路 + 条件分支 + 回边（与 flow JSON 同源维护）
        topology=(
            FlowEdge("read_skill", "read_requirement"),
            FlowEdge("read_requirement", "get_id"),
            FlowEdge("get_id", "query_registry"),
            FlowEdge("query_registry", "find_reference"),
            FlowEdge("find_reference", "gate_plan"),
            FlowEdge("gate_plan", "dag_design", "多场景", "cond"),
            FlowEdge("gate_plan", "permission_precheck", "涉权限/写操作", "cond"),
            FlowEdge("gate_plan", "validate", "确认规划"),
            FlowEdge("dag_design", "permission_precheck", "涉权限/写操作", "cond"),
            FlowEdge("dag_design", "validate"),
            FlowEdge("permission_precheck", "validate"),
            FlowEdge("validate", "validate", "重新生成再校", "loop"),
            FlowEdge("validate", "write_draft", "PASS"),
            FlowEdge("write_draft", "suggest_deps"),
            FlowEdge("suggest_deps", "validate", "采纳建议边·重校", "loop"),
            FlowEdge("suggest_deps", "trial_run", "用户要试跑", "cond"),
            FlowEdge("suggest_deps", "gate_promote"),
            FlowEdge("trial_run", "trial_run", "归因重跑", "loop"),
            FlowEdge("trial_run", "gate_promote", "PASS"),
            FlowEdge("gate_promote", "promote", "确认"),
            FlowEdge("write_draft", "get_id", "下一场景", "loop"),
        ),
    )


def _linear_topology(stages: tuple[FlowStage, ...]) -> tuple[FlowEdge, ...]:
    """旧定义（无 topology 键）线性兜底：阶段序直链——兼容面，新定义都走真实拓扑。"""
    return tuple(FlowEdge(stages[i].key, stages[i + 1].key) for i in range(len(stages) - 1))


def load_flow(name: str = DEFAULT_FLOW_NAME) -> FlowDef:
    """装载 golden flow 定义：evals/flows/{name}.flow.json 优先，缺失回退内置。

    JSON 里 tools 是人写形态（助记/legacy/基名），装载时统一归一为（基名, action），
    换工具名只需改 JSON 或跑 build_flow 重建，不改比对逻辑。
    topology/gates 缺省时按阶段序线性兜底（旧 JSON 兼容）。
    """
    path = _FLOWS_DIR / f"{name}.flow.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            stages = tuple(
                FlowStage(
                    key=s["key"], label=s["label"],
                    units=tuple(normalize_tool_unit(t) for t in s.get("tools", [])),
                    required=bool(s.get("required", False)),
                    note=str(s.get("note", "")),
                )
                for s in raw.get("stages", [])
            )
            if stages:
                topology = tuple(
                    FlowEdge(str(e["from"]), str(e["to"]),
                             str(e.get("label", "")), str(e.get("kind", "main")))
                    for e in raw.get("topology", [])
                )
                if not topology:
                    topology = _linear_topology(stages)
                gates = tuple(
                    FlowGate(str(g["key"]), str(g["label"]))
                    for g in raw.get("gates", [])
                )
                return FlowDef(
                    id=str(raw.get("id", name)), title=str(raw.get("title", name)),
                    source=str(raw.get("source", "")), stages=stages,
                    hard_order=tuple(tuple(p) for p in raw.get("hard_order", [])),
                    benign_bases=frozenset(raw.get("benign_bases", [])),
                    topology=topology, gates=gates,
                    rebuilt_from_file=True,
                )
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass  # 定义损坏 → 诚实回退内置（与体验基线①失效回退同款）
    return _builtin_flow_def()


def flow_def_to_mermaid(defn: FlowDef) -> str:
    """渲染 golden flow 本体拓扑（无会话着色：主路+条件分支+回边+交互门全展示）。"""
    node_id = {st.key: f"S{i}" for i, st in enumerate(defn.stages, start=1)}
    gate_id = {g.key: f"G{i}" for i, g in enumerate(defn.gates, start=1)}
    lines = [_MERMAID_INIT, "flowchart TD"]
    for st in defn.stages:
        num = node_id[st.key][1:]
        mark = "必选" if st.required else "可选"
        cls = "req" if st.required else "opt"
        lines.append(f'    {node_id[st.key]}("{num}. {st.label}<br/>{mark}"):::{cls}')
    for g in defn.gates:
        lines.append(f'    {gate_id[g.key]}{{"{g.label}"}}:::gate')
    lines += _render_edges(defn, node_id, gate_id, {}, {})
    lines += [
        f"    classDef req {_CLS_HIT}",
        f"    classDef opt {_CLS_SKIP}",
        f"    classDef gate {_CLS_GATE}",
    ]
    return "\n".join(lines)


# 模块级默认定义（向后兼容旧导入面：FLOW_STAGES / HARD_ORDER / BENIGN_BASES）
FLOW_DEF: FlowDef = load_flow()
FLOW_STAGES: list[FlowStage] = list(FLOW_DEF.stages)
HARD_ORDER: tuple[tuple[str, str], ...] = FLOW_DEF.hard_order
BENIGN_BASES = set(FLOW_DEF.benign_bases)

_STAGE_BY_KEY = FLOW_DEF.stage_by_key


def _unit_to_stage(unit: tuple[str, str], defn: FlowDef | None = None) -> str | None:
    """单元 → 所属阶段 key（flow 图视角；一单元只归一个阶段，先命中先得）。"""
    b, a = unit
    for st in (defn or FLOW_DEF).stages:
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
    fails: int = 0               # 结果非 ok 的调用次数（问题调用角标）


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
    flow_id: str = ""
    flow_title: str = ""
    flow_source: str = ""
    # 历程边热力：(from_stage, to_stage) → 经过次数（按「命中阶段序列」相邻对推导，
    # 旁支/benign 调用不占位；自环=连续命中同阶段，即重试/修复轮次）
    edge_hits: dict = field(default_factory=dict)

    @property
    def n_missing(self) -> int:
        return sum(1 for s in self.stages if s.status == "missing")

    @property
    def n_out_of_order(self) -> int:
        return sum(1 for s in self.stages if s.status == "out_of_order")


def trace_session(path: str | Path, flow: FlowDef | None = None) -> FlowTrace | None:
    """单会话路径重放：golden flow vs 实际走径。解析失败返回 None。"""
    scan = scan_session(path)
    if scan is None:
        return None
    return trace_scan(scan, flow=flow)


def trace_scan(scan: SessionScan, flow: FlowDef | None = None) -> FlowTrace:
    """对已扫描的会话做路径重放（复用 scan，避免重复读盘；后端实时扫描走此口）。"""
    defn = flow or FLOW_DEF
    units = scan_units(scan)
    verdicts = list(getattr(scan, "tool_call_verdicts", []) or [])
    # 每个工具调用 = 一步；单元映射到阶段，记首次步号/次数/原始名/失败数
    first: dict[str, int] = {}
    times: dict[str, int] = {}
    stage_tools: dict[str, list] = {}
    fails: dict[str, int] = {}
    extras: dict[str, int] = {}
    edge_hits: dict[tuple[str, str], int] = {}
    prev_key: str | None = None
    for i, unit in enumerate(units, start=1):
        key = _unit_to_stage(unit, defn)
        if key is None:
            if unit[0] not in defn.benign_bases:
                # 展示键带 action（sync_workspace 归一为 spec(sync)——基名裸列会误导成 read_spec）
                disp = f"{unit[0]}({unit[1]})" if unit[1] else unit[0]
                extras[disp] = extras.get(disp, 0) + 1
            continue
        times[key] = times.get(key, 0) + 1
        first.setdefault(key, i)
        if i - 1 < len(verdicts) and verdicts[i - 1] == "fail":
            fails[key] = fails.get(key, 0) + 1
        if prev_key is not None:
            pair = (prev_key, key)
            edge_hits[pair] = edge_hits.get(pair, 0) + 1
        prev_key = key
        raw_name = scan.tool_calls_raw[i - 1][0] if i - 1 < len(scan.tool_calls_raw) else unit[0]
        if raw_name not in stage_tools.setdefault(key, []):
            stage_tools[key].append(raw_name)

    states: list[StageState] = []
    for st in defn.stages:
        if st.key in times:
            states.append(StageState(st.key, st.label, st.required, "in_order",
                                     first[st.key], times[st.key], stage_tools.get(st.key, []),
                                     fails=fails.get(st.key, 0)))
        elif st.required:
            states.append(StageState(st.key, st.label, True, "missing", note=st.note))
        else:
            states.append(StageState(st.key, st.label, False, "skipped", note=st.note))

    # 硬顺序约束 → 乱序判定（flag 后来者：它开跑早了）
    deviations: list[str] = []
    for earlier, later in defn.hard_order:
        if earlier in first and later in first and first[earlier] > first[later]:
            idx = _state_idx(states, later)
            if idx >= 0 and states[idx].status != "missing":
                states[idx].status = "out_of_order"
            deviations.append(
                f"「{defn.stage_by_key[later].label}」（第 {first[later]} 步）先于"
                f"「{defn.stage_by_key[earlier].label}」（第 {first[earlier]} 步）——"
                f"违反基线顺序（应先{defn.stage_by_key[earlier].label}再{defn.stage_by_key[later].label}）")
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
        flow_id=defn.id,
        flow_title=defn.title,
        flow_source=defn.source,
        edge_hits=edge_hits,
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


# mermaid 图共享样式（面板/报告两生成器同源）：
# 淡透明填充 + 状态色描边 + 文字色继承主题——K-041 按 dark/default 双主题渲染时都融合，
# 不写死 color/fill 实色（旧实色卡片在深色面板下是突兀浅块，验收反馈「样式粗糙」）
_MERMAID_INIT = (
    '%%{init: {"flowchart": {"curve": "linear", "nodeSpacing": 10, "rankSpacing": 22, '
    '"padding": 5}, "themeVariables": {"fontSize": "13px", '
    "\"fontFamily\": \"-apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif\"}}}%%"
)
# mermaid classDef 按逗号切分属性，rgba() 函数形式的逗号会触发 Parse error——
# 透明度用 8 位 hex 尾两位表达（#RRGGBBAA）
_CLS_HIT = "fill:#34c77b29,stroke:#34c77b,stroke-width:1.6px"
_CLS_WARN = "fill:#f0b42926,stroke:#f0b429,stroke-width:2px"
_CLS_MISSING = "fill:#eb57572b,stroke:#eb5757,stroke-width:2px"
_CLS_SKIP = "fill:#94a3b81a,stroke:#94a3b8,stroke-width:1.2px,stroke-dasharray:4 4"
_CLS_GATE = "fill:transparent,stroke:#94a3b8,stroke-width:1.2px"


def _hits_on_topology(edge_hits: dict, defn: FlowDef) -> tuple[dict, dict]:
    """历程相邻对 → 拓扑边命中（topo_hits）与野跳对（wild，历程偏离拓扑的信号）。

    归一规则：直接边优先；无直接边时尝试「单跳门穿透」（a→gate→b 视作穿过交互门，
    门无工具调用本不会产生边）；其余为野跳（如写草稿直接跳试跑——真实历程的旁逸）。
    """
    direct = {(e.from_key, e.to_key) for e in defn.topology}
    ins: dict[str, list] = {}
    outs: dict[str, list] = {}
    for e in defn.topology:
        outs.setdefault(e.from_key, []).append(e.to_key)
        ins.setdefault(e.to_key, []).append(e.from_key)
    gate_through: dict[tuple[str, str], str] = {}
    for g in defn.gates:
        for a in ins.get(g.key, []):
            for b in outs.get(g.key, []):
                gate_through[(a, b)] = g.key
    topo_hits: dict[tuple[str, str], int] = {}
    wild: dict[tuple[str, str], int] = {}
    for (a, b), n in edge_hits.items():
        if (a, b) in direct:
            topo_hits[(a, b)] = topo_hits.get((a, b), 0) + n
        elif a == b:
            pass  # 未定义的自环=阶段内多次调用（节点 ×N 已表达），不算旁逸
        elif (a, b) in gate_through:
            g = gate_through[(a, b)]
            topo_hits[(a, g)] = topo_hits.get((a, g), 0) + n
            topo_hits[(g, b)] = topo_hits.get((g, b), 0) + n
        else:
            wild[(a, b)] = wild.get((a, b), 0) + n
    return topo_hits, wild


def _render_edges(defn: FlowDef, node_id: dict[str, str], gate_id: dict[str, str],
                  topo_hits: dict, wild: dict,
                  violated: set[tuple[str, str]] | None = None) -> list[str]:
    """拓扑边 + 野跳边 + hard_order 约束边 + linkStyle 行（mermaid 边索引按声明序）。"""
    violated = violated or set()

    def nid(k: str) -> str:
        return node_id.get(k) or gate_id.get(k) or k

    lines: list[str] = []
    styles: list[str] = []
    for e in defn.topology:
        n = topo_hits.get((e.from_key, e.to_key), 0)
        label = " ".join(p for p in (e.label, f"×{n}" if n else "") if p)
        arrow = "-.->" if e.kind == "loop" else "-->"
        if label:
            lines.append(f'    {nid(e.from_key)} {arrow}|"{label}"| {nid(e.to_key)}')
        else:
            lines.append(f"    {nid(e.from_key)} {arrow} {nid(e.to_key)}")
        if n:
            styles.append("stroke-width:2.4px")
        elif e.kind == "loop":
            styles.append("stroke-width:1px,stroke-dasharray:3 3,opacity:0.55")
        else:
            styles.append("stroke-width:1px,opacity:0.5")
    # 野跳：历程里不在拓扑定义的相邻对——旁逸信号（琥珀虚线，退为背景纹理；
    # 高频野跳（≥2 次）才加粗提权，视觉主角留给主干经过边）
    for (a, b), n in sorted(wild.items()):
        lines.append(f'    {nid(a)} -.->|"×{n}"| {nid(b)}')
        if n >= 2:
            styles.append("stroke:#f0b429,stroke-width:2px,stroke-dasharray:4 3,opacity:0.9")
        else:
            styles.append("stroke:#f0b429,stroke-width:1.2px,stroke-dasharray:4 3,opacity:0.45")
    # hard_order 前置约束：显式边（正常淡灰虚线提示，违例红色加粗）
    for earlier, later in defn.hard_order:
        elabel = defn.stage_by_key[earlier].label if earlier in defn.stage_by_key else earlier
        lines.append(f'    {nid(earlier)} -. "须先 {elabel}" .-> {nid(later)}')
        if (earlier, later) in violated:
            styles.append("stroke:#eb5757,stroke-width:2.2px")
        else:
            styles.append("stroke:#94a3b8,stroke-width:1px,stroke-dasharray:2 3,opacity:0.6")
    for i, stl in enumerate(styles):
        lines.append(f"    linkStyle {i} {stl}")
    return lines


def render_flow_mermaid(trace: FlowTrace, defn: FlowDef | None = None) -> str:
    """把重放结果叠加到 golden flow 条件拓扑（网状：主路+条件分支+回边+交互门）。

    节点两行徽章（四态描边+fail 角标），边带历程热力（×N 经过次数，经过加粗），
    野跳边=历程旁逸（琥珀虚线），hard_order 前置约束显式成边（违例红）。
    """
    defn = defn or FLOW_DEF
    cls = {"in_order": "hit", "out_of_order": "warn", "missing": "missing", "skipped": "skip"}
    node_id = {st.key: f"S{i}" for i, st in enumerate(defn.stages, start=1)}
    gate_id = {g.key: f"G{i}" for i, g in enumerate(defn.gates, start=1)}
    by_key = {s.key: s for s in trace.stages}

    def _evidence(s: StageState) -> str:
        if s.status == "missing":
            base = "✗ 未调用"
        elif s.status == "skipped":
            base = "－ 可跳过"
        else:
            cnt = f" ×{s.times}" if s.times > 1 else ""
            step = f"第{s.first_step}步" if s.first_step else ""
            sep = " · " if cnt and step else ""
            base = f"{cnt}{sep}{step} {_STATUS_GLYPH[s.status]}".strip()
        if s.fails:
            base += f" ⚠{s.fails}"
        return base

    violated: set[tuple[str, str]] = set()
    for earlier, later in defn.hard_order:
        e_state, l_state = by_key.get(earlier), by_key.get(later)
        if (e_state and l_state and e_state.first_step and l_state.first_step
                and l_state.first_step < e_state.first_step):
            violated.add((earlier, later))

    topo_hits, wild = _hits_on_topology(trace.edge_hits, defn)
    lines = [_MERMAID_INIT, "flowchart TD"]
    for st in defn.stages:
        s = by_key[st.key]
        num = node_id[st.key][1:]
        lines.append(f'    {node_id[st.key]}("{num}. {st.label}<br/>{_evidence(s)}"):::{cls[s.status]}')
    for g in defn.gates:
        lines.append(f'    {gate_id[g.key]}{{"{g.label}"}}:::gate')
    lines += _render_edges(defn, node_id, gate_id, topo_hits, wild, violated)
    lines += [
        f"    classDef hit {_CLS_HIT}",
        f"    classDef warn {_CLS_WARN}",
        f"    classDef missing {_CLS_MISSING}",
        f"    classDef skip {_CLS_SKIP}",
        f"    classDef gate {_CLS_GATE}",
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
        f"生成会话判定：**{verdict}** · 差异 {n_dev} 处 · flow=`{trace.flow_id}`",
        "",
        "## 路径重放图（golden flow vs 实际）",
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
                     "benign 元工具（flow 定义 benign_bases：自检/待办/话题等）已剔除。")
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


def resolve_session_path(sessions_root: str | Path, session_id: str) -> Path | None:
    """按会话 ID 解析 JSONL 路径（跨 emp/workspace 子目录全局查）。

    多命中取最近修改（并注明）；0 命中返回 None。CLI --session 的解析口，
    与后端 get_session 的子目录兜底语义对齐。
    """
    import glob
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        return None
    root = Path(sessions_root)
    if not root.exists():
        return None
    matches = [Path(f) for f in glob.glob(str(root / "**" / f"{session_id}.jsonl"), recursive=True)]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    return max(matches, key=lambda p: p.stat().st_mtime)
