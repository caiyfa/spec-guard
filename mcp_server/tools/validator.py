"""validator — 场景校验（格式 + covers 关联 + 注册表引用）。

工具：
  validate: 校验场景 YAML 内容，返回结构化报告
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from specstd.anchors import resolve_covers, scan_anchors  # noqa: E402
from specstd.workspace import get_active_workspace  # noqa: E402
from mcp_server.tools.live_registry import oracle_names  # noqa: E402


def _hint(name: str, candidates) -> str:
    """为未注册名称生成相近候选 hint（幻觉自修复的依据）。"""
    import difflib
    matches = difflib.get_close_matches(name, list(candidates), n=3, cutoff=0.5)
    return f"相近候选: {', '.join(matches)}" if matches else ""

TOOLS = [
    Tool(
        name="validate",
        description="校验场景 YAML 内容：格式合规（T1-T7）+ covers 关联（FR 锚点存在性）"
                    "+ 注册表引用有效性（tool/oracle 名称已注册）。编造的 FR 必报 COVER 错误并给 hint。",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "场景 YAML 内容"},
            },
            "required": ["content"]
        }
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "validate":
        return _handle_validate(arguments)
    return []


def _handle_validate(arguments: dict) -> list[TextContent]:
    content = arguments.get("content", "")
    if not content:
        return [TextContent(type="text", text="错误：缺少 content 参数")]
    report = validate_scenario_content(content)
    return [TextContent(type="text", text=json.dumps(report, ensure_ascii=False, indent=2))]


def _scenario_index() -> dict[str, dict]:
    """扫描场景库 + 当前工作区草稿，返回 {场景ID: {version, source}}（T4 依赖连通性用）。

    K-021②：草稿纳入索引——生成期同批次草稿互相依赖是合法的（prep 草稿先入库，
    或整批一起入库），只查场景库会把合法依赖误报成悬空。
    K-025：场景库部分走 scenario_store 指纹缓存（此前每次 validate 全量重解析
    90+ YAML，Agent 批量校验时成本随草稿数线性放大）；草稿部分每次扫（少且常变）。
    """
    import yaml as _yaml
    index: dict[str, dict] = {}

    try:
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        if d.is_dir():
            for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
                try:
                    raw = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                except Exception:
                    continue
                sid = raw.get("id")
                if sid:
                    index[str(sid)] = {"version": str(raw.get("version", "0.1")),
                                       "source": f"draft:{f.name}"}
    except Exception:
        pass
    try:
        # K-016 同构的场景库根（工作区有 scenarios/ 则用，否则 SpecGuard 仓库根）
        from services.draft_promote import _scenarios_root
        from services.scenario_store import _scenarios_cached, SCENARIOS_ROOT as _SS_ROOT
        if _scenarios_root() == _SS_ROOT:
            # K-025：主路径走指纹缓存（此前每次 validate 全量重解析 90+ YAML）
            for s in _scenarios_cached():
                index[str(s["id"])] = {"version": str(s.get("version", "0.1")), "source": "scenarios"}
        else:
            # 工作区自带 scenarios/ 的少见路径：直接扫（量小，不缓存）
            root = _scenarios_root()
            for f in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
                try:
                    raw = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                except Exception:
                    continue
                sid = raw.get("id")
                if sid:
                    index[str(sid)] = {"version": str(raw.get("version", "0.1")), "source": "scenarios"}
    except Exception:
        pass
    return index


def validate_scenario_content(content: str) -> dict:
    """校验场景 YAML 内容，返回结构化报告 dict（供 MCP 工具与 drafts 路由复用）。"""
    import yaml

    # 解析 YAML
    try:
        raw = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        return {
            "verdict": "ERROR",
            "findings": [{"level": "ERROR", "rule": "T1", "message": f"YAML 解析失败: {e}"}],
        }

    findings = []
    sid = raw.get("id", "(unknown)")

    # T1: 格式基本
    flow = raw.get("flow") or []
    verify = raw.get("verify") or []
    if not flow and not verify:
        findings.append({"level": "ERROR", "rule": "T1", "scenario": sid,
                         "message": "flow/verify 均为空，场景不可执行"})

    # T6: 契约指纹
    try:
        from engine.versioning import fingerprint_from_raw, check_t6, load_baseline
        baseline = load_baseline(str(SG_ROOT))
        result = check_t6(sid, fingerprint_from_raw(raw), str(raw.get("version", "0.1")), baseline)
        if result:
            level, message = result
            findings.append({"level": level, "rule": "T6", "scenario": sid, "message": message})
    except Exception:
        pass  # 引擎未就绪时跳过 T6

    # covers 关联校验
    doc = raw.get("doc") or {}
    covers = doc.get("covers") or []
    if covers:
        ws = get_active_workspace()
        if ws:
            anchors = scan_anchors(ws.root)
            cover_findings = resolve_covers([str(c) for c in covers], anchors)
            for f in cover_findings:
                findings.append({
                    "level": f.level, "rule": f.rule,
                    "scenario": sid, "message": f.message,
                    "detail": f.detail,
                })
        else:
            findings.append({"level": "WARN", "rule": "COVERS", "scenario": sid,
                             "message": "无激活工作区，无法校验 covers 关联"})
    else:
        # K-020：covers 是场景↔Spec 的强制锚点（覆盖分析/DAG 编排依赖），缺失必须可见。
        # 此前零告警——Agent 在 ANCHOR 误报时学会「删 covers 就能过」，
        # 批量产生 30 份无锚点草稿、FR 溯源链断裂（用户会话导出取证）
        findings.append({"level": "WARN", "rule": "COVERS", "scenario": sid,
                         "message": "缺少 doc.covers（FR 锚点）——covers 是场景↔Spec 的强制关联，"
                                    "缺失的场景无法参与覆盖分析与 DAG 编排。"
                                    "请补充当前工作区 spec.md 中真实存在的 FR ID（用 read_spec 核实）"})

    # T4/T7 依赖连通性与版本期望（K-021②：此前 Agent 的 validate 不查 depends_on，
    # 悬空依赖/版本不可满足要到 promote 的发布门禁才炸——反馈晚一阶段，
    # 批量生成时错误复制放大；规则语义与工作台 spec_validator 对齐）
    deps = raw.get("depends_on") or []
    if deps:
        try:
            from engine.versioning import match_expectation, MINOR_DRIFT, MAJOR_DRIFT
            index = _scenario_index()
            for d in deps:
                dep_id = d if isinstance(d, str) else (d.get("id", "") if isinstance(d, dict) else "")
                if not dep_id:
                    continue
                target = index.get(str(dep_id))
                if not target:
                    findings.append({"level": "ERROR", "rule": "T4", "scenario": sid,
                                     "message": f"depends_on 引用不存在的场景: {dep_id}"
                                                f"（已查场景库与 drafts/ 草稿）"})
                    continue
                expected = None if isinstance(d, str) else (d.get("version") if isinstance(d, dict) else None)
                if expected is None:
                    findings.append({"level": "WARN", "rule": "T7", "scenario": sid,
                                     "message": f"依赖 {dep_id} 未声明版本期望（接受任意版本），"
                                                f"建议补 version: ^X 显式锁定"})
                    continue
                verdict_v = match_expectation(str(expected), target["version"])
                if verdict_v == MAJOR_DRIFT:
                    findings.append({"level": "ERROR", "rule": "T4", "scenario": sid,
                                     "message": f"依赖 {dep_id} 版本期望 {expected} 不可满足"
                                                f"（实际 {target['version']}，来源 {target['source']}）"})
                elif verdict_v == MINOR_DRIFT:
                    findings.append({"level": "INFO", "rule": "T4", "scenario": sid,
                                     "message": f"依赖 {dep_id} 精确期望 {expected}，实际 minor 更高"
                                                f"（{target['version']}，兼容放行）"})
        except Exception:
            pass  # 引擎未就绪时跳过 T4/T7

    # T8（2.3.0）：requires.upstream 必须在 depends_on 声明——否则跨场景变量
    # {{上游ID.*}} 运行期「变量未定义」（EX-8200eada 教训：声明依赖但未声明来源）
    req = raw.get("requires") or {}
    if isinstance(req, dict):
        req_up = req.get("upstream") or []
        dep_ids = {
            d if isinstance(d, str) else (d.get("id", "") if isinstance(d, dict) else "")
            for d in deps
        }
        for up in req_up:
            if up not in dep_ids:
                findings.append({"level": "ERROR", "rule": "T8", "scenario": sid,
                                 "message": f"requires.upstream 引用 {up} 未在 depends_on 声明——"
                                            f"跨场景变量 {{{{{up}.*}}}} 运行期会「变量未定义」。"
                                            f"请在 depends_on 声明该依赖，或在 requires.upstream 移除"})

    # T5 无孤例（无 depends_on 且非 prep 标签 → 疑似孤立场景）
    tags = raw.get("tags") or []
    if not deps and "prep" not in tags:
        findings.append({"level": "WARN", "rule": "T5", "scenario": sid,
                         "message": "无 depends_on 且非 prep 标签——疑似孤立场景。"
                                    "自包含场景（flow 自建数据）可忽略；否则建议声明依赖或标记 prep"})

    # 注册表引用校验（tool 名称）
    try:
        from services.format_spec import get_tool_catalog
        valid_tools = {t["name"] for t in get_tool_catalog()}
    except Exception:
        valid_tools = set()

    for step in flow:
        if isinstance(step, dict) and "tool" in step:
            tool_body = step["tool"]
            if isinstance(tool_body, dict):
                tool_name = tool_body.get("use", "")
                if tool_name and valid_tools and tool_name not in valid_tools:
                    hint = _hint(tool_name, valid_tools)
                    findings.append({"level": "ERROR", "rule": "REGISTRY", "scenario": sid,
                                     "message": f"未注册的 tool: {tool_name}",
                                     **({"hint": hint} if hint else {})})
        # T-317：call 的 body: 键（2.1.0 前旧语法）→ WARN 提示迁移 json:
        # （标签库存量场景静默丢请求体的根因，Agent 生成时不得再用 body:）
        if isinstance(step, dict) and "call" in step:
            call_body = step["call"]
            if isinstance(call_body, dict) and "body" in call_body and "json" not in call_body:
                findings.append({"level": "WARN", "rule": "BODY_KEY", "scenario": sid,
                                 "message": "call 使用 body: 键（2.1.0 前旧语法，请求体可能未发送）——"
                                            "请改为 json: {…}（见 format_spec §1.4 call 参数体系）"})

    # T-319：未知插值校验（复用 preflight 检测，生成时拦截而非等执行）——
    # {{random:6}} 类（Apifox 语法）不在 fn.*/env.*/上游引用/场景内 save 与
    # set_var vars 集合 → 运行期必 KeyError「变量未定义」（EX-5c6f4c98），ERROR 禁止入库
    try:
        from services.preflight import _static_unresolved_templates
        tpl_text = ""
        for section in ("flow", "verify", "teardown"):
            val = raw.get(section)
            if val:
                tpl_text += yaml.safe_dump(val, allow_unicode=True) + "\n"
        for expr in _static_unresolved_templates(raw, tpl_text):
            findings.append({"level": "ERROR", "rule": "UNKNOWN_TPL", "scenario": sid,
                             "message": f"未知插值 {{{{{expr}}}}}——仅支持 fn.*（内置函数）/ env.*（环境键）/ "
                                        f"{{{{上游ID.*}}}} / 本场景 save 与 set_var 变量；"
                                        f"{{{{random:N}}}} 等 Apifox 语法运行期会「变量未定义」，请改用 "
                                        f"{{{{fn.uuid_short}}}} / {{{{fn.timestamp}}}}"})
    except Exception:
        pass  # 检测服务不可用时跳过（不阻断主校验）

    # V9 修复：verify 段 oracle 引用校验（幻觉拦截——编造 oracle 必报 ERROR + hint）
    valid_oracles = oracle_names()
    for item in verify:
        if not isinstance(item, dict) or "oracle" not in item:
            continue
        oracle_ref = item["oracle"]
        # 两种形态：- oracle: name（字符串）/ - oracle: {name: xxx, params: {...}}（参数化）
        if isinstance(oracle_ref, str):
            oracle_name = oracle_ref
        elif isinstance(oracle_ref, dict):
            oracle_name = str(oracle_ref.get("name", ""))
        else:
            continue
        if oracle_name and valid_oracles and oracle_name not in valid_oracles:
            hint = _hint(oracle_name, valid_oracles)
            findings.append({"level": "ERROR", "rule": "REGISTRY", "scenario": sid,
                             "message": f"未注册的 oracle: {oracle_name}",
                             **({"hint": hint} if hint else {})})

    n_err = sum(1 for f in findings if f["level"] == "ERROR")
    n_warn = sum(1 for f in findings if f["level"] == "WARN")
    verdict = "PASS" if n_err == 0 else "REJECT"

    return {
        "verdict": verdict,
        "scenario": sid,
        "findings": findings,
        "summary": {"error": n_err, "warn": n_warn},
    }
