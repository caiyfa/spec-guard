"""evals.harness — Agent 评测基建（T-980）。

把 test_specstd/test_agent.py:33-60 的 MockLLM 模式提升为正式可编程评测基建：

  - ScriptedLLM     脚本化 LLM：按序回放响应（含 tool_calls），记录每次请求；
                    脚本耗尽即停（默认视为用例失败——脚本是 golden 期望的一部分）
  - MockToolModule  工具结果 mock：替换 runtime._tool_map 条目，白名单/参数解析/
                    截断等 runtime 链路保持全真；未 mock 的工具走真实实现
  - 轨迹断言        tool_sequence / tools_required / tools_forbidden /
                    tool_result（jsonpath）/ artifact_validate（复用 validator）
  - run_golden_case 跑单个 golden case，产出含工具维度的 metrics
                    （调用序列/成功率/步数/耗时）

设计原则（docs/架构反馈升级/2026-08-20-第二轮-六点反馈判定-多系统与智能层.md §5）：
轨迹断言先行——确定性断言没穷尽前不上 LLM-as-judge；产物断言复用
validate_scenario_content，不新建评估器。

离线确定性：评测进程内隔离工作区（SG_WORKSPACE/注册表 active/contextvar 全部清空），
validate 的 COVERS 校验等行为不随宿主环境漂移；真实只读工具（list_scenarios/
validate）不依赖网络与 DB。
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from mcp.types import TextContent  # noqa: E402, I001  (sys.path 前置所必需)


# ══════════════════════════════════════════════════════════
# 工具结果成败判定（与 runtime._execute_tool 的错误出口前缀一一对应）
# ══════════════════════════════════════════════════════════

_RESULT_ERROR_PREFIXES = (
    "错误：",                    # 参数解析失败 / todo 校验失败
    "[越权拒绝]",                # T-011 白名单外工具
    "未知工具:",                 # 未注册工具（幻觉）
    "工具执行异常:",             # mod.handle 抛异常
    "[SIDE_EFFECT_VIOLATION]",   # T-081 纯读工具产生副作用
    "[拒绝]",                    # T-081 external-write 级
)


def tool_result_ok(result: str) -> bool:
    """按 runtime 错误出口前缀判定工具调用是否成功（确定性，非启发式）。"""
    return not result.startswith(_RESULT_ERROR_PREFIXES)


# ══════════════════════════════════════════════════════════
# ScriptedLLM：可编程脚本 LLM
# ══════════════════════════════════════════════════════════

class ScriptedLLM:
    """按脚本序列回放响应的 LLM（接口与 LLMClient/MockLLM 对齐）。

    - 脚本条目形如 {"role": "assistant", "content": ..., "tool_calls": [...]}；
      function.arguments 允许写 dict（加载时归一化为 JSON 字符串，与真实
      OpenAI 协议一致，runtime 走 json.loads 路径）
    - 每次调用记录请求概要（消息数/在册工具名），供失败诊断
    - 脚本耗尽后返回默认终止响应，exhausted 置 True——由断言层判失败
    """

    def __init__(self, script: list[dict] = None):
        self.responses = [_normalize_response(r) for r in (script or [])]
        self.requests: list[dict] = []
        self._call_count = 0
        self._total_tokens = 0
        self.max_context_tokens = 0  # 与 LLMClient 接口对齐（0=消息数保底阈值）

    @property
    def is_mock(self):
        return True

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def exhausted(self) -> bool:
        return self._call_count > len(self.responses)

    @property
    def leftover(self) -> int:
        """脚本剩余未消费条数（会话提前结束——熔断/取消——时 >0）。"""
        return max(0, len(self.responses) - self._call_count)

    def chat(self, messages, tools=None, temperature=0.7, on_delta=None):
        self.requests.append({
            "message_count": len(messages),
            "tool_names": [t.get("function", {}).get("name", "")
                           for t in (tools or [])],
        })
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
        else:
            resp = {"role": "assistant",
                    "content": "（脚本耗尽，默认停止）"}
        self._call_count += 1
        self._total_tokens += 15
        return resp, {"prompt_tokens": 10, "completion_tokens": 5,
                      "total_tokens": 15}

    def set_metrics_file(self, path):
        pass

    def get_stats(self):
        return {"cache_hits": 0, "cache_misses": self._call_count,
                "total_tokens": self._total_tokens,
                "is_mock": True, "model": "scripted"}


def _normalize_response(resp: dict) -> dict:
    """脚本条目归一化：function.arguments dict → JSON 字符串。"""
    resp = dict(resp)
    if resp.get("tool_calls"):
        normalized = []
        for tc in resp["tool_calls"]:
            fn = tc.get("function") or {}
            if isinstance(fn.get("arguments"), dict):
                tc = dict(tc, function=dict(
                    fn, arguments=json.dumps(fn["arguments"], ensure_ascii=False)))
            normalized.append(tc)
        resp["tool_calls"] = normalized
    return resp


# ══════════════════════════════════════════════════════════
# MockToolModule：工具结果 mock（替换 runtime._tool_map 条目）
# ══════════════════════════════════════════════════════════

class MockToolModule:
    """被 mock 的工具模块（duck-type 真实 ToolModule 的 handle 协议）。

    mock spec 形态（单个或列表——列表按调用次数取第 n 个，末个重复）：
      {"json": {...}}        → TextContent(json.dumps(...))
      {"text": "..."}        → TextContent(原文)
      {"error": "..."}       → raise RuntimeError（模拟工具炸掉）
    """

    def __init__(self, name: str, spec):
        self.name = name
        self.specs = spec if isinstance(spec, list) else [spec]
        self.calls: list[dict] = []

    async def handle(self, name: str, arguments: dict) -> list[TextContent]:
        self.calls.append(dict(arguments))
        idx = min(len(self.calls) - 1, len(self.specs) - 1)
        spec = self.specs[idx] or {}
        if "error" in spec:
            raise RuntimeError(str(spec["error"]))
        text = (json.dumps(spec["json"], ensure_ascii=False, indent=2)
                if "json" in spec else str(spec.get("text", "")))
        return [TextContent(type="text", text=text)]


# ══════════════════════════════════════════════════════════
# 评测进程的工作区隔离（离线确定性）
# ══════════════════════════════════════════════════════════

@contextmanager
def isolated_eval_context():
    """清空一切工作区解析通道，保证 golden case 不随宿主环境漂移。

    get_active_workspace() 的解析顺序（specstd/workspace.py:246）：
    contextvar → SG_WORKSPACE 环境变量 → 注册表全局 active。
    worktree 会同步 specstd/workspaces 注册表——不隔离的话，宿主机上
    恰好有 active 工作区时 validate 的 COVERS 校验会去扫真实克隆，
    行为不确定且慢。评测语境下统一按「无激活工作区」回放。
    """
    import specstd.workspace as ws_mod

    saved_env = os.environ.pop("SG_WORKSPACE", None)
    orig_loader = ws_mod._load_registry
    ws_mod._load_registry = lambda *a, **k: {"active": "", "workspaces": {}}
    token = ws_mod._CTX_WORKSPACE.set(None)
    try:
        yield
    finally:
        ws_mod._CTX_WORKSPACE.reset(token)
        ws_mod._load_registry = orig_loader
        if saved_env is not None:
            os.environ["SG_WORKSPACE"] = saved_env


# ══════════════════════════════════════════════════════════
# Golden case 装载与执行
# ══════════════════════════════════════════════════════════

@dataclass
class ToolCallRecord:
    tool: str
    arguments: dict
    result: str
    ok: bool
    turn: int


@dataclass
class AssertionResult:
    type: str
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    case_file: str
    passed: bool
    assertions: list[AssertionResult] = field(default_factory=list)
    records: list[ToolCallRecord] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)  # 失败诊断用

    @property
    def failures(self) -> list[AssertionResult]:
        return [a for a in self.assertions if not a.passed]


def load_case(path: str | Path) -> dict:
    """装载 golden case JSON（校验必需字段，脚本参数归一化）。"""
    path = Path(path)
    case = json.loads(path.read_text(encoding="utf-8"))
    for key in ("id", "task_prompt", "llm_script", "expect"):
        if key not in case:
            raise ValueError(f"golden case 缺少必需字段 {key!r}: {path}")
    case.setdefault("max_turns", 8)
    case.setdefault("tool_mocks", {})
    case.setdefault("allow_leftover", False)
    case["_case_file"] = str(path)
    return case


def run_golden_case(case: dict) -> CaseResult:
    """离线回放一个 golden case，返回结构化结果。

    真实链路：AgentRuntime 核心循环 + 白名单 + 参数解析 + 截断；
    mock 点仅两处——LLM 响应（ScriptedLLM）与 case 声明的工具结果。
    """
    from agent.runtime import AgentRuntime

    llm = ScriptedLLM(case["llm_script"])
    records: list[ToolCallRecord] = []
    state = {"fused": False}

    with isolated_eval_context():
        runtime = AgentRuntime(llm, max_turns=int(case["max_turns"]))
        # 评测期中和副作用通道：审计落库/指纹扫描与轨迹断言正交，且会
        # 污染同步来的 workbench.db、rglob 工作区克隆拖慢回放——就地中和
        runtime._record_audit = lambda *a, **k: None
        runtime._take_snapshot_fingerprint = lambda: "eval-constant"
        _patch_user_store_audit(True)
        try:
            for name, spec in case["tool_mocks"].items():
                if name not in runtime._tool_map:
                    raise ValueError(
                        f"tool_mocks 引用未注册工具 {name!r}（case {case['id']}）")
                runtime._tool_map[name] = MockToolModule(name, spec)

            def on_event(event: dict):
                if event["type"] == "tool_call":
                    tc = event.get("tool_call") or {}
                    fn = tc.get("function") or {}
                    raw = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw) if isinstance(raw, str) else raw
                    except json.JSONDecodeError:
                        args = {}
                    result = str(event.get("result", ""))
                    records.append(ToolCallRecord(
                        tool=fn.get("name", ""), arguments=args or {},
                        result=result, ok=tool_result_ok(result),
                        turn=int(event.get("turn", 0))))
                elif event["type"] == "state" and event.get("fused"):
                    state["fused"] = True

            runtime.events.subscribe(on_event)
            started = time.perf_counter()
            messages = runtime.run(
                "（评测模式）你是 SpecGuard 智能测试助手。", case["task_prompt"])
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
        finally:
            _patch_user_store_audit(False)

    assertions = _builtin_assertions(case, llm, state)
    assertions += evaluate_assertions(case.get("expect") or [], records)

    tools_sequence = [r.tool for r in records]
    n_ok = sum(1 for r in records if r.ok)
    metrics = {
        "llm_calls": llm.call_count,
        "turns": sum(1 for m in messages if m.get("role") == "assistant"),
        "steps": len(records),
        "duration_ms": duration_ms,
        "fused": state["fused"],
        "tools_sequence": tools_sequence,
        "tool_calls_total": len(records),
        "tool_calls_ok": n_ok,
        "tool_calls_failed": len(records) - n_ok,
        "tool_success_rate": round(n_ok / len(records), 4) if records else None,
        "assertions_total": len(assertions),
        "assertions_passed": sum(1 for a in assertions if a.passed),
    }
    passed = all(a.passed for a in assertions)
    return CaseResult(
        case_id=str(case["id"]),
        case_file=case.get("_case_file", ""),
        passed=passed,
        assertions=assertions,
        records=records,
        metrics=metrics,
        messages=messages,
    )


def _patch_user_store_audit(enabled: bool):
    """T-011 越权路径直接调 user_store.audit 落 workbench.db——评测期中和。"""
    try:
        from services import user_store
    except Exception:
        return
    if enabled and not getattr(user_store.audit, "_sg_eval_patched", False):
        import functools

        @functools.wraps(user_store.audit)
        def _noop(*a, **k):
            return None

        _noop._sg_eval_patched = True
        user_store._sg_eval_orig_audit = user_store.audit
        user_store.audit = _noop
    elif not enabled and getattr(user_store, "_sg_eval_orig_audit", None):
        user_store.audit = user_store._sg_eval_orig_audit
        del user_store._sg_eval_orig_audit


# ══════════════════════════════════════════════════════════
# 断言引擎
# ══════════════════════════════════════════════════════════

def _builtin_assertions(case: dict, llm: ScriptedLLM, state: dict
                        ) -> list[AssertionResult]:
    """内建断言：脚本消费完整性（脚本本身是 golden 期望的一部分）。"""
    out = []
    if llm.exhausted:
        out.append(AssertionResult(
            "script_usage", "脚本未耗尽即停",
            passed=False,
            detail=f"LLM 调用 {llm.call_count} 次超过脚本 {len(llm.responses)} 条——"
                   f"轨迹比预期长（检查 max_turns/脚本遗漏）"))
    elif llm.leftover and not case.get("allow_leftover"):
        out.append(AssertionResult(
            "script_usage", "脚本未完整消费",
            passed=False,
            detail=f"脚本剩余 {llm.leftover} 条未消费——轨迹提前结束"
                   f"（fused={state['fused']}；测熔断行为可设 allow_leftover: true）"))
    else:
        out.append(AssertionResult(
            "script_usage", "脚本消费完整",
            passed=True,
            detail=f"消费 {llm.call_count}/{len(llm.responses)} 条"))
    return out


def evaluate_assertions(expects: list[dict], records: list[ToolCallRecord]
                        ) -> list[AssertionResult]:
    """按 case 声明顺序评估断言（顺序即报告顺序）。"""
    out = []
    for i, exp in enumerate(expects):
        t = exp.get("type", "")
        try:
            if t == "tool_sequence":
                out.append(_check_sequence(exp, records))
            elif t == "tools_required":
                out.append(_check_required(exp, records))
            elif t == "tools_forbidden":
                out.append(_check_forbidden(exp, records))
            elif t == "tool_result":
                out.append(_check_tool_result(exp, records))
            elif t == "artifact_validate":
                out.append(_check_artifact_validate(exp, records))
            else:
                out.append(AssertionResult(t, f"#{i}", passed=False,
                                           detail=f"未知断言类型: {t}"))
        except Exception as e:  # 断言引擎自身异常 = 该断言失败，不炸整个评测
            out.append(AssertionResult(t, f"#{i}", passed=False,
                                       detail=f"断言执行异常: {e}"))
    return out


def _seq(records: list[ToolCallRecord], ignore: list[str]) -> list[str]:
    return [r.tool for r in records if r.tool not in set(ignore or [])]


def _last_record(tool: str, records: list[ToolCallRecord]):
    for r in reversed(records):
        if r.tool == tool:
            return r
    return None


def _check_sequence(exp: dict, records) -> AssertionResult:
    ignore = exp.get("ignore") or []
    actual = _seq(records, ignore)
    expect = list(exp.get("expect") or [])
    return AssertionResult(
        "tool_sequence", "→".join(expect) or "（空）",
        passed=actual == expect,
        detail=f"期望 {expect}，实际 {actual}")


def _check_required(exp: dict, records) -> AssertionResult:
    called = {r.tool for r in records}
    expect = set(exp.get("expect") or [])
    missing = expect - called
    return AssertionResult(
        "tools_required", "⊇ " + (", ".join(sorted(expect)) or "∅"),
        passed=not missing,
        detail=f"未调用: {sorted(missing)}" if missing
               else f"已调用（实际全集: {sorted(called)}）")


def _check_forbidden(exp: dict, records) -> AssertionResult:
    called = {r.tool for r in records}
    expect = set(exp.get("expect") or [])
    hit = called & expect
    return AssertionResult(
        "tools_forbidden", "∩ " + (", ".join(sorted(expect)) or "∅"),
        passed=not hit,
        detail=f"禁用工具被调用: {sorted(hit)}" if hit else "未触碰禁用工具")


def _check_tool_result(exp: dict, records) -> AssertionResult:
    tool = exp.get("tool", "")
    rec = _last_record(tool, records)
    name = f"{tool} 的结果"
    if rec is None:
        return AssertionResult("tool_result", name, passed=False,
                               detail=f"工具 {tool} 未被调用，无结果可断言")
    jsonpath = exp.get("jsonpath")
    if jsonpath:
        return _check_jsonpath(exp, rec, name)
    if "contains" in exp:
        return AssertionResult(
            "tool_result", f"{name} contains",
            passed=str(exp["contains"]) in rec.result,
            detail=f"期望包含 {exp['contains']!r}，实际: {rec.result[:300]!r}")
    if "equals" in exp:
        return AssertionResult(
            "tool_result", f"{name} equals",
            passed=rec.result == exp["equals"],
            detail=f"期望 {exp['equals']!r}，实际 {rec.result[:300]!r}")
    return AssertionResult("tool_result", name, passed=False,
                           detail="断言缺少 jsonpath/contains/equals 之一")


def _check_jsonpath(exp: dict, rec: ToolCallRecord, name: str) -> AssertionResult:
    from jsonpath_ng import parse

    label = f"{name} [{exp['jsonpath']}]"
    try:
        data = json.loads(rec.result)
    except json.JSONDecodeError:
        return AssertionResult("tool_result", label, passed=False,
                               detail=f"结果不是 JSON: {rec.result[:200]!r}")
    matches = [str(m.value) for m in parse(exp["jsonpath"]).find(data)]
    if not matches:
        return AssertionResult("tool_result", label, passed=False,
                               detail=f"jsonpath 无命中，结果摘要: "
                                      f"{json.dumps(data, ensure_ascii=False)[:300]}")
    value = matches[0]
    if "equals" in exp:
        ok, detail = value == str(exp["equals"]), f"期望 {exp['equals']!r}，实际 {value!r}"
    elif "min" in exp:
        try:
            ok = float(value) >= float(exp["min"])
            detail = f"期望 ≥ {exp['min']}，实际 {value}"
        except ValueError:
            ok, detail = False, f"值非数值: {value!r}"
    elif "contains" in exp:
        ok, detail = str(exp["contains"]) in value, f"期望包含 {exp['contains']!r}，实际 {value!r}"
    else:
        ok, detail = False, "jsonpath 断言缺少 equals/min/contains 比较器"
    return AssertionResult("tool_result", label, passed=ok, detail=detail)


def _check_artifact_validate(exp: dict, records) -> AssertionResult:
    """产物断言：从写型工具调用参数中取产物文本，复用 validator 校验。

    source_tool（默认 write_draft）最后一次调用的 arguments[content_key]
    （默认 content）即产物原文——validate_scenario_content 与 MCP validate
    工具、promote 发布门禁同源，不新建评估器。
    """
    from mcp_server.tools.validator import validate_scenario_content

    tool = exp.get("source_tool", "write_draft")
    key = exp.get("content_key", "content")
    expect_verdict = exp.get("expect_verdict", "PASS")
    rec = _last_record(tool, records)
    label = f"{tool} 产物经 validator"
    if rec is None:
        return AssertionResult("artifact_validate", label, passed=False,
                               detail=f"工具 {tool} 未被调用，无产物可校验")
    content = rec.arguments.get(key)
    if not content:
        return AssertionResult("artifact_validate", label, passed=False,
                               detail=f"调用参数缺少 {key!r}，无产物可校验")
    report = validate_scenario_content(str(content))
    n_err = report.get("summary", {}).get("error", 0)
    ok = report.get("verdict") == expect_verdict and (
        "max_error" not in exp or n_err <= int(exp["max_error"]))
    findings = "; ".join(
        f"[{f.get('rule')}] {f.get('message', '')[:80]}"
        for f in report.get("findings", [])) or "（无 findings）"
    return AssertionResult(
        "artifact_validate", label, passed=ok,
        detail=f"verdict={report.get('verdict')}（期望 {expect_verdict}），"
               f"error={n_err}；findings: {findings[:400]}")
