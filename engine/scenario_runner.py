"""场景执行器：步骤调度 + 断言执行 + 依赖闭包回溯 + ExecutionRecord 填充。

变量插值规则：
- 字符串完全匹配 {{expr}} → 返回解析值（保留原始类型，如 int/list/dict）
- 字符串内嵌 {{expr}} → 字符串替换（str(value)）
- expr 支持点号路径：{{emp.no}}（本场景变量）/ {{PP-PREP-001.activityId}}（上游场景命名空间）
"""

import os
import pathlib
import random
import string
import time
import uuid as _uuid

from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JSONPathError

from engine.execution_record import (
    CAT_ASSERT,
    CAT_ENV,
    CAT_ORACLE,
    CAT_SCENARIO,
    VERDICT_PASS,
    VERDICT_SKIP,
    AssertionTrace,
    ExecutionRecord,
    StepTrace,
    truncate,
    truncate_body,
)
from engine.http_client import HttpClient, _trace_id_of

# T-999c 抽出：插值器 → engine/interpolation.py，实例池 → engine/instance_pool.py；
# 此处再导出保持 `from engine.scenario_runner import render/LeaseRegistry/...` 存量引用零改动
from engine.instance_pool import (  # noqa: F401
    LeaseRegistry,
    _acquire_instance,
    _blocked_record,
    _check_dep_versions,
    _Instance,
    _resolve_dep_ns,
    _UpstreamFailed,
    _verdict_record,
)
from engine.scenario_loader import MODE_SHARED

# 抽出段常量再导出（test_engine_modes 等存量 `from engine.scenario_runner import VERDICT_*` 零改动）
from engine.execution_record import (  # noqa: F401,E402  # isort:skip
    CAT_CONTRACT_DRIFT, CAT_CONTRACT_ORPHAN, CAT_UPSTREAM,
    VERDICT_BLOCKED, VERDICT_DRIFT, VERDICT_FAIL, VERDICT_ORPHANED,
)
from engine.interpolation import _FNS, RenderError, _resolve, render  # noqa: F401


class SkipScenario(Exception):
    """场景前置条件不满足（工号池无候选/账号未配置等）→ verdict=SKIP

    category: SKIP 归类（pool_empty/pool_leased_out/account_missing/db_unavailable/
    oracle_infra/poll_timeout/uncategorized——ENG-MNT-002 补 poll_timeout，实际取值
    以 grep category= 全仓核对为准）
    向后兼容：不带 category 的调用点一律归为 uncategorized，无需批量修改业务代码。
    """
    def __init__(self, message, category="uncategorized"):
        super().__init__(message)
        self.category = category


class ScenarioScriptError(Exception):
    """python 步骤 / python 断言脚本内的非 SkipScenario 异常经此重包装。

    ENG-T01：脚本错误属「场景编写错误」，应归 CAT_SCENARIO 而非 CAT_ENV。
    step_python / python 断言的 exec 捕获到脚本异常后重抛为本类；run_scenario
    的 except 链据此映射 CAT_SCENARIO。脚本内主动 raise SkipScenario 的语义
    必须原样保留（不包装），故 step_python 中 SkipScenario 单独 re-raise。
    """


class ScenarioTimeout(Exception):
    """场景级软看门狗（ENG-T03）：场景累计耗时超过 SG_SCENARIO_TIMEOUT（秒，默认 300）。

    检查点在 flow 步骤边界 / verify 断言边界 / poll 轮询边界——exec 内死循环
    （while True 不回到边界）软看门狗拦不住，进程级兜底靠 workbench runner 层
    T-118 看门狗（settings KV run_timeout_sec / 环境变量 SG_RUN_TIMEOUT，默认 0=禁用）。
    归类 CAT_ENV（环境/未知，非场景编写错误）。
    """



def _scenario_timeout_sec():
    """读取场景级软看门狗阈值：SG_SCENARIO_TIMEOUT（秒）。

    缺省/空/非法/非正值一律回退默认 300。每次调用现读（测试与运行期可调）。
    """
    raw = (os.environ.get("SG_SCENARIO_TIMEOUT") or "").strip()
    if not raw:
        return 300.0
    try:
        val = float(raw)
        return val if val > 0 else 300.0
    except ValueError:
        return 300.0


def _check_scenario_deadline(rctx, where):
    """检查点：超阈值抛 ScenarioTimeout。deadline 由 run_scenario 挂在 rctx 上
    （嵌套场景各自设置/恢复，结束即还原——不跨场景泄漏）。"""
    deadline = getattr(rctx, "_scenario_deadline", None)
    timeout_sec = getattr(rctx, "_scenario_timeout_sec", None)
    if deadline is not None and time.time() > deadline:
        raise ScenarioTimeout(
            f"场景执行超过 {timeout_sec:g}s（{where}边界触发软看门狗；"
            f"脚本内死循环无法触发，进程级兜底见 runner 层 T-118 run_timeout_sec）")


# ══════════════════════════════════════════════════════════
# 执行上下文（pytest session 级共享）
# ══════════════════════════════════════════════════════════

class RunContext:
    def __init__(self, registry, env_config, token_provider, graph, run_dir,
                 skip_upstream_verify=False, prep_only=False, db=None, strict_deps=False,
                 dbs=None):
        self.registry = registry
        self.env = env_config
        self.token_provider = token_provider
        self.graph = graph
        self.run_dir = run_dir
        self.skip_upstream_verify = skip_upstream_verify
        self.prep_only = prep_only
        self.db = db                     # 默认连接 engine.db_oracle.ReadOnlyDb（可为 None）
        # K-055：多 schema 命名连接注册表（{"default": ReadOnlyDb, "biz": ...}）；未传时由 db 合成
        self.dbs = dbs if dbs is not None else ({"default": db} if db else {})
        self.strict_deps = strict_deps   # 严格依赖模式：DRIFT/ORPHANED 升格为 FAIL（发版门禁用）
        self.leases = LeaseRegistry()    # session 级资源租约注册表（工号池/账号/配置层共用）
        self.records = []              # list[ExecutionRecord] 本次运行全部记录
        self.instances = {}            # scenario_id -> list[_Instance]（实例池：shared 复用 / exclusive 新建）
        self.teardown_stack = []       # [(scenario, _Instance)] 已执行且声明 teardown 的实例，session 末 LIFO 清理
        self.shared_ns = {}            # 跨场景变量命名空间 {scenario_id: saved_vars}（仅共享实例发布）
        # T-972 引擎去领域化：默认资源码/默认服务名不再内置任何系统字面量——
        # 由 systems/{system}/config/env.*.yaml 声明（default_service/default_resource_code）
        self.default_service = env_config.get("default_service", "")
        # env 命名空间：场景可用 {{env.resource_code}} / {{env.vars.*}} 引用环境级配置
        self.shared_ns["env"] = {
            "resource_code": env_config.get("default_resource_code", ""),
            "vars": env_config.get("vars", {}),   # REQ-3：自定义变量段全量暴露
        }
        self._clients = {}             # (service, account) -> HttpClient（K-055 服务路由）

    def http_client(self, account, service=None):
        """按账号别名 + 服务获取客户端（account=None 表示不带 token 的匿名调用）。

        K-055 服务前缀路由：service → env 配置的 `{service}_base`（如 hr_center_base/
        oss_base/uac_base），解决「接口全路径的服务段（hr-center 等）丢失」——
        场景只写服务内相对路径，服务由 service 字段声明。
        T-972：service 缺省（None）用 env 配置 default_service（系统主网关）；
        未声明时 SkipScenario（环境配置缺口，不误报 FAIL）。
        别名（default/restricted 等）必须在 env 配置 accounts 中映射为真实 AD 账号；
        未配置时抛 SkipScenario（支持"受限账号后补，缺账号时 SKIP"的场景约定）。
        服务 base 未配置同样 SkipScenario（环境配置缺口，不误报 FAIL）。
        """
        if service is None:
            service = self.default_service
            if not service:
                raise SkipScenario(
                    "环境配置缺少 default_service（call/poll 未声明 service 时的默认"
                    "服务名，请在 systems/{system}/config/env.*.yaml 声明——"
                    "default_service: <名> 对应 <名>_base）")
        key = (service, account or "__anonymous__")
        if key not in self._clients:
            base = self.env.get(f"{service}_base")
            if not base:
                raise SkipScenario(
                    f"环境配置缺少 {service}_base（service={service} 的服务地址，"
                    f"请在 systems/{{system}}/config/env.*.yaml 补充）")
            real_account = None
            if account:
                # K-055：账号声明 type: internal → 走 internal token（无身份服务凭证）
                info = self.account_info(account)
                if info and info.get("type") == "internal":
                    real_account = self.token_provider.INTERNAL_ACCOUNT
                else:
                    real_account = self.account_emp_no(account)
                if not real_account:
                    raise SkipScenario(
                        f"账号别名 '{account}' 未在环境配置 accounts 中定义"
                        f"（请在 systems/{{system}}/config/env.*.yaml 的 accounts 补充真实 AD 账号）")
            self._clients[key] = HttpClient(
                base,
                token_provider=self.token_provider if real_account else None,
                account=real_account,
                check_version=bool(self.env.get("check_version_header", False)),
            )
        return self._clients[key]

    def account_info(self, account):
        """账号配置：accounts 中 {别名: {ad, emp_no}}（兼容 {别名: ad} 简单形式）"""
        cfg = (self.env.get("accounts") or {}).get(account)
        if cfg is None:
            return None
        if isinstance(cfg, str):
            return {"ad": cfg, "emp_no": None}
        return cfg

    def account_emp_no(self, account):
        """账号别名 → 真实 AD 账号（token 换取用）"""
        info = self.account_info(account)
        return info.get("ad") if info else None


# ══════════════════════════════════════════════════════════
# 内置步骤处理器
# ══════════════════════════════════════════════════════════

# ENG-T03：幂等方法默认自动重试一次；其余方法需显式声明才重试
_IDEMPOTENT_METHODS = ("GET", "HEAD", "OPTIONS")
_RETRY_ON_STATUS_DEFAULT = (500, 502, 503, 504)


def _call_retry_config(body, method):
    """call 步骤的幂等重试配置（ENG-T03）。

    - GET/HEAD/OPTIONS：默认 {"times": 1}（不声明即自动重试一次）；
    - 其他方法：需显式二选一——retry: {times: N, backoff?: 秒, on_status?: [状态码]}
      或 idempotent: true（等价 times=1 的语义糖）；
    - retry: {times: 0} 显式关闭（含 GET 默认）。
    返回 None 表示不重试。配置非法抛 ValueError（归 CAT_SCENARIO 场景编写错误）。
    """
    retry = body.get("retry")
    idem = body.get("idempotent")
    if retry is not None and idem is not None:
        raise ValueError("call 步骤 retry 与 idempotent 二选一，不可同时声明")
    if idem is not None and not isinstance(idem, bool):
        raise ValueError("call 步骤 idempotent 只接受 true/false")
    if retry is not None:
        if not isinstance(retry, dict):
            raise ValueError("call 步骤 retry 应为 dict（{times: N, backoff?: 秒, "
                             f"on_status?: [状态码]}}），实际类型 {type(retry).__name__}")
        times = retry.get("times")
        if isinstance(times, bool) or not isinstance(times, int) or times < 0:
            raise ValueError(f"call 步骤 retry.times 应为非负整数，实际 {times!r}")
        cfg = dict(retry)
        cfg.setdefault("backoff", 1.0)
        cfg.setdefault("on_status", list(_RETRY_ON_STATUS_DEFAULT))
        return cfg
    if idem:
        return {"times": 1, "backoff": 1.0, "on_status": list(_RETRY_ON_STATUS_DEFAULT)}
    if method in _IDEMPOTENT_METHODS:
        return {"times": 1, "backoff": 1.0, "on_status": list(_RETRY_ON_STATUS_DEFAULT)}
    return None

def step_call(body, rctx, ns, record):
    """HTTP 调用（Apifox 风格参数体系）。

    as: 账号别名（default 等），none/anonymous 表示不带 token
    headers/cookies: KV dict，支持 {{var}} 插值；headers 可显式覆盖 Authorization（负向测试）
    body_type: json（默认）| form | urlencoded | raw | binary
      - json:        {json: {...}}
      - form:        {form: {k: v, file_field: "@path/to/file"}}（@前缀=文件字段，multipart）
      - urlencoded:  {urlencoded: {k: v}}
      - raw:         {raw: "文本", content_type: "text/plain"（默认）}
      - binary:      {file: "path/to/file"}（文件字节流作为 body）
    retry/idempotent: 幂等重试声明（ENG-T03，见 _call_retry_config）
    """
    account = body.get("as", "default")
    if account in ("none", "anonymous"):
        account = None
    # K-055：服务前缀路由——service 字段（支持 {{}} 插值；缺省用 env 的
    # default_service，T-972 起引擎不内置系统名）
    raw_service = body.get("service")
    service = (str(render(raw_service, ns)) if raw_service is not None
               else (getattr(rctx, "default_service", "") or None))
    client = rctx.http_client(account, service)
    method = body.get("method", "GET").upper()
    path = render(body["path"], ns)
    params = render(body.get("params"), ns)
    headers = render(body.get("headers"), ns)
    cookies = render(body.get("cookies"), ns)
    # T-317：body: 键兼容（2.1.0 前旧语法）——标签库 85 处存量场景仍用 body:，
    # 引擎只认 json: 导致请求体静默丢失（日志无 body、网关 500）。
    # 兼容：body: 且无 json: 时按 json 发送 + WARN 提示迁移；json: 存在时 json: 优先。
    if "body" in body and "json" not in body and body.get("body") is not None:
        print("[SpecGuard] WARN call 使用 body: 键（2.1.0 前旧语法，已按 json 发送）——"
              "请迁移为 json:（见 format_spec §1.4 call 参数体系）", flush=True)
        body = dict(body)
        body["json"] = body.pop("body")
    body_type = body.get("body_type") or ("json" if body.get("json") is not None else None)

    json_body = None
    data = None
    files = None
    if body_type == "json":
        json_body = render(body.get("json"), ns)
    elif body_type == "form":
        form = render(body.get("form") or {}, ns) or {}
        data, files = {}, {}
        for k, v in form.items():
            if isinstance(v, str) and v.startswith("@"):
                fpath = v[1:]
                if not os.path.isabs(fpath):
                    fpath = os.path.join(os.getcwd(), fpath)
                # ENG-T03（ENG-BUG-004/011）：读 bytes 而非流式句柄——句柄不 close 有
                # fd 泄漏风险，且 401/重试重发时流已耗尽会发出空 body
                files[k] = (os.path.basename(fpath), pathlib.Path(fpath).read_bytes())
            else:
                data[k] = v
        files = files or None
    elif body_type == "urlencoded":
        data = render(body.get("urlencoded") or {}, ns)
        if headers is None:
            headers = {}
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body_type == "raw":
        data = render(body.get("raw", ""), ns)
        if headers is None:
            headers = {}
        headers.setdefault("Content-Type", body.get("content_type", "text/plain"))
    elif body_type == "binary":
        fpath = render(body.get("file", ""), ns)
        if not os.path.isabs(fpath):
            fpath = os.path.join(os.getcwd(), fpath)
        # ENG-T03（ENG-BUG-004/011）：同 form——bytes 化，句柄不再存在，重试任意次安全
        data = pathlib.Path(fpath).read_bytes()
        if headers is None:
            headers = {}
        headers.setdefault("Content-Type", "application/octet-stream")
    elif body_type:
        raise ValueError(f"body_type 非法: {body_type}（支持 json/form/urlencoded/raw/binary）")

    started = time.time()
    resp = client.request(method, path, params=params, json_body=json_body,
                          data=data, files=files, headers=headers, cookies=cookies,
                          raise_on_error=False, timeout=body.get("timeout", 30),
                          retry=_call_retry_config(body, method))
    elapsed = int((time.time() - started) * 1000)
    try:
        resp_json = resp.json()
    except Exception:
        resp_json = None
    # 提取 trace_id（复用 http_client 的函数，与执行日志同源）
    trace_id = _trace_id_of(resp)
    record.steps.append(StepTrace(
        type="call",
        # T-316：请求体进报告（与执行日志调用前信息对齐）——此前 request 只有
        # as/method/path/params，发了什么 body 查不到；文件流 data 不落盘
        request={"as": account or "(匿名)", "method": method, "path": path,
                 "params": params, **({"body_type": body_type} if body_type else {}),
                 **({"headers": dict(headers)} if headers else {})},
        response_status=resp.status_code,
        duration_ms=elapsed,
        body_excerpt=truncate(resp_json),
        trace_id=trace_id,
        response_headers=dict(resp.headers),
        # ENG-T04：完整落盘的成本在付、详细查询消费端未落地——改 20KB 上限截断留痕
        response_body=truncate_body(resp_json if resp_json is not None else resp.text),
    ))
    # 完整的请求体/表单数据并入 request（20KB 上限截断留痕，ENG-T04——与响应体同口径）
    body_data = json_body if json_body is not None else (data if isinstance(data, (str, dict, list)) else None)
    if body_data is not None:
        record.steps[-1].request["body"] = truncate_body(body_data)
    return {"status": resp.status_code, "json": resp_json,
            "headers": dict(resp.headers)}


def step_set_var(body, rctx, ns, record):
    """变量设置：{save: emp, vars: {no: '90024713', name: '张超'}}

    K-051：vars 直接注入顶层命名空间——format_spec §3.4 契约即
    `tool: {use: set_var, with: {vars: {activity_name: ...}}}` 后以 `{{activity_name}}`
    裸名引用（无 save）；此前无 save 时返回值被 flow 循环丢弃，变量全部未定义
    （IS-PREP-002/003 即按规范书写却 FAIL: 变量未定义）。带 save 的旧用法
    （{{emp.no}}）不受影响——ns[save] 仍由 flow 循环写入。
    """
    values = {k: render(v, ns) for k, v in (body.get("vars") or {}).items()}
    ns.update(values)
    record.steps.append(StepTrace(type="set_var", note=f"设置变量: {values}"))
    return values


def step_db_query(body, rctx, ns, record):
    """只读 SQL 查询：{sql: 'SELECT ...', save: rows}。sql 支持 {{var}} 插值。

    K-055：可选 schema 字段——多 schema 命名连接注册表（env db 段 dict-of-dicts），
    默认 default；schema 未配置 → SkipScenario（环境配置缺口，诚实语义）。
    """
    schema = str(render(body.get("schema", "default"), ns) or "default")
    db = rctx.dbs.get(schema) or (rctx.db if schema == "default" else None)
    if db is None:
        available = sorted(rctx.dbs) or ["（无可用连接）"]
        # 诚实语义：DB 不可用 → SKIP，归类 db_unavailable（skip_category 枚举见 execution_record 默认）
        raise SkipScenario(
            f"当前环境 DB schema '{schema}' 不可用（可用: {available}），db_query 步骤无法执行",
            category="db_unavailable")
    sql = render(body["sql"], ns)
    # ENG-T06（ENG-BUG-009）：显式豁免——截断仍落 db_traces 痕，但不再 WARN/告警
    allow_truncate = bool(body.get("allow_truncate", False))
    started = time.time()
    rows = db.query(sql)
    elapsed = int((time.time() - started) * 1000)
    note = body.get("note", "db_query")
    # ENG-T06 三层落痕：截断事实不再静默——db_traces 标记 / 执行日志 WARN / 场景级 warnings
    truncated = bool(getattr(db, "last_truncated", False))
    if truncated and not allow_truncate:
        print("[SpecGuard WARN] db_query 结果截断于 1000 行（实际更多），计数类断言将失真"
              "——如只取样本属预期，可声明 allow_truncate: true 豁免告警", flush=True)
        record.warnings.append(f"db_query '{note}' 结果截断于 1000 行（计数类断言将失真）")
    record.db_traces.append({"purpose": note,
                             "sql": sql, "rows": len(rows),
                             "truncated": truncated,
                             "excerpt": truncate(rows[:3])})
    record.steps.append(StepTrace(type="db_query", duration_ms=elapsed,
                                  note=f"{note} → {len(rows)} 行"
                                       + ("（截断）" if truncated else "")))
    return rows


def step_poll(body, rctx, ns, record):
    """异步轮询：重复调用直至条件满足或超时。

    用法：
    - poll:
        call: {method: GET, path: /api/task/result, params: {taskNo: "{{submit.json.data.taskNo}}"}}
        until:
          - json: {path: "$.data.status", eq: "DONE"}
        interval_ms: 2000
        timeout_ms: 60000
        on_timeout: fail          # fail（默认）| skip
        save: result
    """
    call_body = body.get("call", {})
    until_conditions = body.get("until", [])
    interval_ms = body.get("interval_ms", 2000)
    timeout_ms = body.get("timeout_ms", 60000)
    on_timeout = body.get("on_timeout", "fail")

    if not call_body:
        raise ValueError("poll 步骤缺少 call 配置")
    if not until_conditions:
        raise ValueError("poll 步骤缺少 until 条件")

    account = call_body.get("as", "default")
    if account in ("none", "anonymous"):
        account = None
    # ENG-T05（ENG-BUG-014）：poll 的 call 段补 service 路由与 headers/cookies 透传
    # （与 step_call 同款参数语义；urlencoded 等复杂 body_type 仍属 call 步骤能力；
    #   service 缺省用 env 的 default_service，T-972 起引擎不内置系统名）
    raw_service = call_body.get("service")
    service = (str(render(raw_service, ns)) if raw_service is not None
               else (getattr(rctx, "default_service", "") or None))
    client = rctx.http_client(account, service)
    method = call_body.get("method", "GET").upper()
    path = render(call_body["path"], ns)
    params = render(call_body.get("params"), ns)
    json_body = render(call_body.get("json"), ns)
    headers = render(call_body.get("headers"), ns)
    cookies = render(call_body.get("cookies"), ns)

    started_total = time.time()
    attempt = 0
    last_result = None

    while True:
        attempt += 1
        elapsed_total = int((time.time() - started_total) * 1000)
        if elapsed_total > timeout_ms:
            msg = (f"poll 超时（{timeout_ms}ms，{attempt} 轮）："
                   f"until 条件未满足，最后响应 status={last_result.get("status") if last_result else "无"}")
            if on_timeout == "skip":
                raise SkipScenario(msg, category="poll_timeout")
            raise AssertionError(msg)
        # ENG-T03：poll 轮询边界检查点（场景阈值可比 poll 自身 timeout_ms 更小）
        _check_scenario_deadline(rctx, "poll 轮询")

        # 执行 HTTP 调用
        started = time.time()
        resp = client.request(method, path, params=params, json_body=json_body,
                              headers=headers, cookies=cookies,
                              raise_on_error=False, timeout=call_body.get("timeout", 30))
        elapsed = int((time.time() - started) * 1000)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None

        last_result = {"status": resp.status_code, "json": resp_json,
                       "headers": dict(resp.headers)}

        record.steps.append(StepTrace(
            type=f"poll:{attempt}",
            request={"as": account or "(匿名)", "method": method, "path": path, "params": params},
            response_status=resp.status_code,
            duration_ms=elapsed,
            body_excerpt=truncate(resp_json),
            note=f"轮询第 {attempt} 轮",
        ))

        # 评估 until 条件（复用 json 断言逻辑）
        all_passed = True
        for cond in until_conditions:
            if "json" in cond:
                jb = cond["json"]
                try:
                    payload = resp_json
                    actual = _jsonpath_find(jb["path"], payload)
                    if not _eval_json_condition(jb, actual):
                        all_passed = False
                        break
                except AssertionError:
                    # 条件不满足（含 jsonpath 无匹配）→ 正常轮询
                    all_passed = False
                    break
                except Exception as e:
                    # ENG-T05（ENG-BUG-008）：配置错误（jsonpath 拼错/KeyError 等）快速失败，
                    # 不再被当成"任务还没好"轮询至超时掩盖真实错误；ValueError → CAT_SCENARIO
                    raise ValueError(
                        f"poll until 条件配置错误: {type(e).__name__}: {e}") from e
            elif "status" in cond:
                sb = cond["status"]
                expected = render(sb.get("eq"), ns)
                if resp.status_code != expected:
                    all_passed = False
                    break

        if all_passed:
            record.steps.append(StepTrace(
                type="poll:done",
                note=f"轮询完成：{attempt} 轮，总耗时 {int((time.time() - started_total) * 1000)}ms",
            ))
            return last_result

        # 间隔后重试
        time.sleep(interval_ms / 1000.0)


def _eval_json_condition(body, actual):
    """评估单条 json 条件是否满足（用于 poll until 判断，不产生 trace）"""
    if "eq" in body:
        return actual == body["eq"]
    if "ne" in body:
        return actual != body["ne"]
    if body.get("not_null"):
        return actual is not None
    if "contains" in body:
        return actual is not None and body["contains"] in actual
    if "len_gt" in body:
        return actual is not None and len(actual) > body["len_gt"]
    if "len_eq" in body:
        return actual is not None and len(actual) == body["len_eq"]
    if body.get("absent"):
        # absent 语义：字段不存在（actual is None）时条件满足
        return actual is None
    return actual is not None


# ══════════════════════════════════════════════════════════
# 随机文本池（T-972 引擎去领域化）
# ══════════════════════════════════════════════════════════
# 领域词库不在引擎内置——系统适配包在 register() 时注入 registry.pools
# （如 systems/{system}/random_pools.py），引擎 grep 零领域词命中。


def step_random(body, rctx, ns, record):
    """随机数据生成：随机数 / 随机文本 / 随机池抓取 / UUID。

    用法：
    - random: {type: number, min: 1, max: 100, save: num}           # 随机整数
    - random: {type: float, min: 0, max: 100, precision: 1, save: f} # 随机浮点数
    - random: {type: text, pool: activity_name, save: name}          # 从词库随机选
    - random: {type: text, pool: person_name, suffix: true, save: n} # 词库+随机后缀
    - random: {type: text, length: 8, save: s}                       # 随机字符串
    - random: {type: uuid, save: id}                                 # 短 UUID
    """
    rtype = body.get("type", "number")

    if rtype == "number":
        lo = int(render(str(body.get("min", 1)), ns) or 1)
        hi = int(render(str(body.get("max", 100)), ns) or 100)
        value = random.randint(lo, hi)

    elif rtype == "float":
        lo = float(render(str(body.get("min", 0)), ns) or 0)
        hi = float(render(str(body.get("max", 100)), ns) or 100)
        precision = int(body.get("precision", 1))
        value = round(random.uniform(lo, hi), precision)

    elif rtype == "text":
        pool_name = body.get("pool", "")
        if pool_name:
            pools = getattr(rctx.registry, "pools", None) or {}
            pool = pools.get(pool_name)
            if not pool:
                raise ValueError(f"随机文本池不存在: {pool_name}（可用: {sorted(pools)}"
                                 f"；领域词库由系统适配包 register() 注入 registry.pools）")
            value = random.choice(pool)
        else:
            length = int(body.get("length", 8))
            value = "".join(random.choices(string.ascii_lowercase + string.digits, k=length))
        # 可选随机数字后缀（保证唯一性）
        if body.get("suffix"):
            value = f"{value}-{random.randint(100, 999)}"

    elif rtype == "uuid":
        value = _uuid.uuid4().hex[:8]

    elif rtype == "pick":
        # 从自定义列表随机选
        items = body.get("items", [])
        if not items:
            raise ValueError("random type=pick 需要 items 列表")
        value = random.choice(items)

    else:
        raise ValueError(f"random.type 非法: {rtype}（支持 number/float/text/uuid/pick）")

    record.steps.append(StepTrace(
        type="random",
        note=f"随机生成 {rtype} = {value!r}",
    ))
    return value


def step_tool(body, rctx, ns, record):
    """tool 信封分发器（格式 2.0）：{use, with, save} → 注册工具的 handler。

    YAML 语法层冻结为 3 原语（call/db_query/poll）+ 本信封；领域能力全部以
    tool 形式调用。with 段为工具参数，save 为产出变量名（注入命名空间）。
    工具元数据见 engine.tool_registry.TOOLS（T-973 起按 system:name 命名空间
    组织；use 支持裸名唯一命中与限定名两种写法，handler 一律按裸名绑定）。
    """
    from engine.tool_registry import resolve_tool
    use = body.get("use")
    if not use:
        raise ValueError("tool 步骤缺少 use 字段（工具名）")
    spec, handler_name = resolve_tool(use)
    if spec is None:
        from engine.tool_registry import TOOLS
        raise ValueError(f"未注册的 tool: {use}（可用: {sorted(TOOLS)}；"
                         f"多系统同名时用 `system:name` 限定）")
    handler = rctx.registry.get_step(handler_name)
    inner = dict(body.get("with") or {})
    if body.get("save"):
        inner["save"] = body["save"]
    return handler(inner, rctx, ns, record)


def _fn_namespace():
    """fn 内置函数的命名空间视图（脚本内 fn.date() 点号调用）"""
    from types import SimpleNamespace
    return SimpleNamespace(**{k.split(".", 1)[1]: v for k, v in _FNS.items()})


def step_python(body, rctx, ns, record):
    """Python 脚本原语（格式 2.1）：在引擎上下文执行脚本，处理复杂逻辑。

    ⚠️ 安全（ENG-SEC-001）：script 经 exec 以引擎进程身份执行——执行场景 YAML
    等同执行代码，外部贡献场景必须人工评审后才允许入库执行。

    用法：
    - python:
        script: |
          rows = ns['rows']
          output = [r for r in rows if r['total_score'] is None]
          print(f'过滤出 {len(output)} 行')
        save: null_rows          # 可选：取脚本中 output 变量注入 ns[save]
    或：
    - python: {file: "scripts/xxx.py", save: out}   # 相对 specguard 根目录

    脚本可用上下文：
    - ns            变量命名空间 dict（直接读写；ns['x']=1 对下游可见）
    - save(k, v)    等价 ns[k] = v
    - output        约定产出变量（step 声明 save 时被取走）
    - rctx / record 运行上下文 / 执行记录
    - http(account) 取 HTTP 客户端（含 token），db 只读 DB 连接（可为 None）
    - fn            内置函数（fn.timestamp() 等）
    - json / re / time / datetime / uuid 预导入模块；SkipScenario 主动跳过

    浅拷贝注意（ENG-BUG-013）：不要对 ns 中来自上游的 dict/list 做原地修改
    （append/pop/改键）——共享引用会泄漏到其他场景；需要修改时先 list(x)/dict(x) 拷贝。
    """
    script = body.get("script")
    if not script and body.get("file"):
        fpath = render(body["file"], ns)
        if not os.path.isabs(fpath):
            fpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), fpath)
        with open(fpath, encoding="utf-8") as f:
            script = f.read()
    if not script:
        raise ValueError("python 步骤缺少 script（或 file）")

    import datetime as _datetime
    import io as _io
    import json as _json
    import re as _re
    ctx = {
        "ns": ns,
        "save": lambda k, v: ns.__setitem__(k, v),
        "rctx": rctx,
        "record": record,
        "http": lambda account="default": rctx.http_client(account),
        "db": rctx.db,
        "fn": _fn_namespace(),
        "json": _json, "re": _re, "time": time, "datetime": _datetime, "uuid": _uuid,
        "SkipScenario": SkipScenario,
        "output": None,
        "print": print,
    }
    buf = _io.StringIO()
    started = time.time()
    from contextlib import redirect_stdout
    try:
        with redirect_stdout(buf):
            exec(compile(script, "<python_step>", "exec"), ctx)
    except SkipScenario:
        raise   # 脚本内主动跳过：原样保留 SKIP 语义
    except Exception as e:
        # ENG-T01：脚本异常属场景编写错误，归 CAT_SCENARIO（而非 CAT_ENV）
        raise ScenarioScriptError(
            f"python 步骤脚本异常（场景编写错误）: {type(e).__name__}: {e}") from e
    elapsed = int((time.time() - started) * 1000)

    printed = buf.getvalue().strip()
    record.steps.append(StepTrace(
        type="python",
        duration_ms=elapsed,
        note=(printed[:200] if printed else "脚本执行完成"),
    ))
    return ctx.get("output")


def register_builtin_steps(registry):
    registry.step("call", step_call)
    registry.step("set_var", step_set_var)
    registry.step("db_query", step_db_query)
    registry.step("poll", step_poll)
    registry.step("random", step_random)
    registry.step("tool", step_tool)
    registry.step("python", step_python)


# ══════════════════════════════════════════════════════════
# 断言执行
# ══════════════════════════════════════════════════════════

def _jsonpath_find(path, data):
    matches = jsonpath_parse(path).find(data)
    if not matches:
        raise AssertionError(f"jsonpath 无匹配: {path}")
    return matches[0].value


def _assert_json_ops(body, actual, ns, trace):
    """json 断言的操作符判定，就地更新 trace"""
    if "eq" in body:
        expected = render(body["eq"], ns)
        trace.expected, trace.actual = expected, actual
        trace.passed = actual == expected
        trace.expr += f" == {expected!r}"
        if not trace.passed:
            trace.message = f"实际值 {actual!r} ≠ 预期 {expected!r}"
    elif "ne" in body:
        expected = render(body["ne"], ns)
        trace.expected, trace.actual = f"≠{expected!r}", actual
        trace.passed = actual != expected
        trace.expr += f" != {expected!r}"
    elif body.get("not_null"):
        trace.expected, trace.actual = "非 null", actual
        trace.passed = actual is not None
        trace.expr += " 非 null"
    elif "contains" in body:
        expected = render(body["contains"], ns)
        trace.expected, trace.actual = f"包含 {expected!r}", actual
        trace.passed = actual is not None and expected in actual
        trace.expr += f" 包含 {expected!r}"
    elif "len_gt" in body:
        n = render(body["len_gt"], ns)
        trace.expected, trace.actual = f"长度>{n}", (len(actual) if actual is not None else None)
        trace.passed = actual is not None and len(actual) > n
        trace.expr += f" 长度>{n}"
    elif "len_eq" in body:
        n = render(body["len_eq"], ns)
        trace.expected, trace.actual = f"长度={n}", (len(actual) if actual is not None else None)
        trace.passed = actual is not None and len(actual) == n
        trace.expr += f" 长度={n}"
    else:
        trace.passed = actual is not None
        trace.expr += " 存在"


def format_assertion_log(trace) -> str:
    """T-314：断言结果日志行——每条 verify 实时进执行日志（-s stdout）。

    此前断言详情只在 run.json（case JSON assertions），执行日志只有场景末尾
    pytest.fail 的 evidence 摘要——EX-a78498c3 类失败看不到逐条断言过程。
    """
    flag = "✅PASS" if trace.passed else "❌FAIL"
    line = f"[SpecGuard] 断言 {getattr(trace, 'expr', '?')} → {flag}"
    if not trace.passed and getattr(trace, "message", ""):
        line += f" | {trace.message}"
    return line


def _run_verifies(scenario, rctx, ns, record, last_call_ref):
    first_fail_category = None
    for v in scenario.verify:
        _check_scenario_deadline(rctx, "断言")   # ENG-T03：断言边界检查点
        if "status" in v:
            body = v["status"]
            try:
                target = ns[body.get("of", last_call_ref)]
            except KeyError:
                # ENG-BUG-012：of 写错变量名 → 该断言 FAIL + 归场景错误，不中断后续断言
                trace = AssertionTrace(expr=f"{body.get('of', last_call_ref)}.status")
                trace.passed = False
                trace.message = (f"断言对象 {body.get('of', last_call_ref)!r} 不存在"
                                f"（flow 未 save 该变量）")
                record.assertions.append(trace)
                print(format_assertion_log(trace), flush=True)  # T-314：断言实时进日志
                if not first_fail_category:
                    first_fail_category = CAT_SCENARIO
                continue
            expected = render(body["eq"], ns)
            actual = target["status"]
            trace = AssertionTrace(expr=f"{body.get('of', last_call_ref)}.status == {expected}",
                                   actual=actual, expected=expected,
                                   passed=actual == expected,
                                   message="" if actual == expected else f"实际状态 {actual} ≠ 预期 {expected}")
            record.assertions.append(trace)
            print(format_assertion_log(trace), flush=True)  # T-314：断言实时进日志
            if not trace.passed and not first_fail_category:
                first_fail_category = CAT_ASSERT

        elif "json" in v:
            body = v["json"]
            trace = AssertionTrace(expr=f"{body.get('of', last_call_ref)}{body['path']}")
            try:
                target = ns[body.get("of", last_call_ref)]
            except KeyError:
                # ENG-BUG-012：of 写错变量名 → 该断言 FAIL + 归场景错误，不中断后续断言
                trace.passed = False
                trace.message = (f"断言对象 {body.get('of', last_call_ref)!r} 不存在"
                                f"（flow 未 save 该变量）")
                record.assertions.append(trace)
                print(format_assertion_log(trace), flush=True)  # T-314：断言实时进日志
                if not first_fail_category:
                    first_fail_category = CAT_SCENARIO
                continue
            try:
                # U-1: call 产出取 ["json"]，db_query 裸数组直通（支持 DB 断言）
                payload = target["json"] if isinstance(target, dict) and "json" in target else target
                actual = _jsonpath_find(body["path"], payload)
                if body.get("absent"):
                    # absent 语义：路径有匹配 → 失败（不应存在）
                    trace.passed = False
                    trace.actual = actual
                    trace.expected = "路径不应存在"
                    trace.expr += " 不应存在"
                    trace.message = f"路径应不存在但存在值: {actual!r}"
                else:
                    _assert_json_ops(body, actual, ns, trace)
            except AssertionError as e:
                if body.get("absent"):
                    # absent 语义：路径无匹配 → 通过
                    trace.passed = True
                    trace.expected = "路径不存在"
                    trace.expr += " 不存在"
                else:
                    trace.passed, trace.message = False, str(e)
            except JSONPathError as e:
                # ENG-BUG-001：jsonpath 拼错（语法/词法错误）→ 场景编写错误，原地落 trace
                trace.passed = False
                trace.message = f"断言 jsonpath 语法错误（场景编写错误）: {e}"
                if not first_fail_category:
                    first_fail_category = CAT_SCENARIO
            record.assertions.append(trace)
            print(format_assertion_log(trace), flush=True)  # T-314：断言实时进日志
            if not trace.passed and not first_fail_category:
                first_fail_category = CAT_ASSERT

        elif "oracle" in v:
            body = v["oracle"]
            name, params = (body, {}) if isinstance(body, str) else (body["name"], body.get("params", {}))
            fn = rctx.registry.get_oracle(name)
            trace = AssertionTrace(expr=f"oracle: {name}")
            try:
                fn(params, rctx, ns, record)
                trace.passed = True
            except AssertionError as e:
                trace.passed, trace.message = False, str(e)
            record.assertions.append(trace)
            print(format_assertion_log(trace), flush=True)  # T-314：断言实时进日志
            if not trace.passed and not first_fail_category:
                first_fail_category = CAT_ORACLE

        elif "python" in v:
            body = v["python"]
            script = body if isinstance(body, str) else body.get("script", "")
            trace = AssertionTrace(expr="python 断言脚本")
            import datetime as _datetime
            import io as _io
            import json as _json
            import re as _re
            ctx = {
                "ns": ns,
                "save": lambda k, val: ns.__setitem__(k, val),
                "rctx": rctx,
                "record": record,
                "http": lambda account="default": rctx.http_client(account),
                "db": rctx.db,
                "fn": _fn_namespace(),
                "json": _json, "re": _re, "time": time, "datetime": _datetime, "uuid": _uuid,
                "SkipScenario": SkipScenario,
                "output": None,
            }
            buf = _io.StringIO()
            try:
                from contextlib import redirect_stdout
                with redirect_stdout(buf):
                    exec(compile(script, "<python_assert>", "exec"), ctx)
                trace.passed = True
                if buf.getvalue().strip():
                    trace.message = buf.getvalue().strip()[:200]
            except AssertionError as e:
                trace.passed, trace.message = False, str(e)
            except Exception as e:
                # ENG-T01：python 断言脚本非断言类异常属场景编写错误，原地落 trace，不中断
                trace.passed = False
                trace.message = f"python 断言脚本异常（场景编写错误）: {type(e).__name__}: {e}"
                if not first_fail_category:
                    first_fail_category = CAT_SCENARIO
            record.assertions.append(trace)
            print(format_assertion_log(trace), flush=True)  # T-314：断言实时进日志
            if not trace.passed and not first_fail_category:
                first_fail_category = CAT_ASSERT
    return first_fail_category


# ══════════════════════════════════════════════════════════
# 场景执行
# ══════════════════════════════════════════════════════════

def run_scenario(scenario, rctx, upstream_of="", run_verify=True, extra_ns=None,
                 instance_no=1):
    """执行单场景（flow + verify），返回 ExecutionRecord（含运行时 saved_vars）。

    extra_ns: 依赖实例绑定的命名空间覆盖（{上游场景ID: 该实例的 saved_vars}），
    优先于 shared_ns——独占实例的变量只对绑定的消费者可见。
    """
    record = ExecutionRecord(
        scenario_id=scenario.id, title=scenario.title, covers=scenario.covers,
        tags=scenario.tags, priority=scenario.priority, doc=scenario.doc,
        upstream_of=upstream_of, instance_no=instance_no,
    )
    record.given = {"depends_on": scenario.depends_display, "file": scenario.path}
    if scenario.produces:
        record.given["produces"] = scenario.produces
    started = time.time()
    # ENG-T03 场景级软看门狗：deadline 挂 rctx（step_poll/_run_verifies 检查点共用），
    # 结束时还原 prev——嵌套场景（上游实例）各自独立计时，不跨场景泄漏
    timeout_sec = _scenario_timeout_sec()
    prev_deadline = getattr(rctx, "_scenario_deadline", None)
    rctx._scenario_deadline = started + timeout_sec
    rctx._scenario_timeout_sec = timeout_sec

    # 浅拷贝（ENG-BUG-013 文档化，不改行为）：saved_vars 里的 dict/list 跨场景共享引用，
    # python 步骤原地修改会污染其他场景；深拷贝会破坏 _Instance.export_ns 的传递引用
    # 绑定设计（见其 docstring），故仅文档约束（format_spec §python 浅拷贝注意事项）
    ns = dict(rctx.shared_ns)          # 继承共享命名空间
    if extra_ns:
        ns.update(extra_ns)            # 实例绑定覆盖（exclusive 上游的变量在此注入）
    saved = {}
    last_call_ref = None
    try:
        for step in scenario.flow:
            if not isinstance(step, dict) or len(step) != 1:
                raise ValueError(f"步骤格式错误（应为单键 dict）: {step}")
            step_type, body = next(iter(step.items()))
            body = body or {}
            # T-314：非 call 步骤的轨迹进日志（call 详情由 http_client 锚点承担）
            if step_type != "call":
                brief = ""
                if step_type == "tool" and isinstance(body, dict):
                    brief = f" | use={body.get('use', '')}"
                elif step_type == "db_query" and isinstance(body, dict):
                    brief = f" | sql={str(body.get('sql', ''))[:80]}"
                print(f"[SpecGuard] 步骤 {step_type}{brief}", flush=True)
            handler = rctx.registry.get_step(step_type)
            value = handler(body, rctx, ns, record)
            save_name = body.get("save") if isinstance(body, dict) else None
            if save_name:
                saved[save_name] = value
                ns[save_name] = value
                if step_type == "call":
                    last_call_ref = save_name
            _check_scenario_deadline(rctx, "步骤")   # ENG-T03：步骤边界检查点

        if run_verify and scenario.verify:
            # 仅当断言依赖默认 of（无显式 of 字段）且无 call 步骤时才报错
            needs_default_ref = any(
                (("status" in v and "of" not in v.get("status", {})) or
                 ("json" in v and "of" not in v.get("json", {})))
                for v in scenario.verify
            )
            if last_call_ref is None and needs_default_ref:
                raise ValueError("场景有 status/json 断言但 flow 中没有 save 的 call 步骤")
            fail_cat = _run_verifies(scenario, rctx, ns, record, last_call_ref)
            if fail_cat:
                failed = [a for a in record.assertions if not a.passed]
                record.fail(fail_cat, f"{len(failed)} 条断言失败",
                            evidence=[{"expr": a.expr, "actual": a.actual,
                                       "expected": a.expected, "message": a.message} for a in failed])
            else:
                record.verdict = VERDICT_PASS
        else:
            record.verdict = VERDICT_PASS

    except SkipScenario as e:
        record.verdict = VERDICT_SKIP
        record.skip_reason = str(e)
        record.skip_category = e.category
    except AssertionError as e:
        record.fail(CAT_ASSERT, str(e))
    except (KeyError, ValueError) as e:
        # ENG-BUG-001：未定义变量 / 配置错误（未注册 tool 等）属场景编写错误
        record.fail(CAT_SCENARIO, f"{type(e).__name__}: {e}")
    except ScenarioScriptError as e:
        # ENG-BUG-001：python 步骤脚本异常属场景编写错误
        record.fail(CAT_SCENARIO, str(e))
    except JSONPathError as e:
        # ENG-BUG-001：jsonpath 语法/词法错误属场景编写错误
        record.fail(CAT_SCENARIO, f"jsonpath 语法错误（场景编写错误）: {e}")
    except Exception as e:
        record.fail(CAT_ENV, f"{type(e).__name__}: {e}")

    rctx._scenario_deadline = prev_deadline   # ENG-T03：还原（不泄漏到后续场景/teardown）
    record.duration_ms = int((time.time() - started) * 1000)
    record.saved_vars = saved          # 运行时属性（to_dict 时排除）
    record.run_ns = ns                 # 运行时完整命名空间（供 teardown 插值，不落盘）
    return record




def run_with_deps(scenario, rctx):
    """按依赖闭包执行目标场景。

    - shared 上游 session 内只执行一次，多消费者共享；exclusive 上游按消费者懒重跑新建实例
    - 上游未通过 → 目标场景 BLOCKED（exclusive 实例失败只阻塞绑定它的消费者）
    - prep_only 模式 → 目标场景 SKIP（仅完成环境准备）
    - 目标场景若已作为共享上游完整执行过（含 verify）则复用其记录；
      PASS 的目标场景登记为共享实例供后续场景复用
      （skip_upstream_verify 模式下上游记录未跑 verify，不可作为目标结论复用）
    """
    # 版本仲裁：DRIFT / ORPHANED / 可选依赖缺失 → 不执行（默认不阻塞流水线）
    verdict, reason = _check_dep_versions(scenario, rctx)
    if verdict:
        record = _verdict_record(scenario, verdict, reason)
        rctx.records.append(record)
        return record

    try:
        dep_ns = _resolve_dep_ns(scenario, rctx, scenario.id)
    except _UpstreamFailed as e:
        record = _blocked_record(scenario, e.sid, e.verdict)
        rctx.records.append(record)
        return record

    if rctx.prep_only:
        record = ExecutionRecord(
            scenario_id=scenario.id, title=scenario.title, covers=scenario.covers,
            tags=scenario.tags, priority=scenario.priority, doc=scenario.doc)
        record.verdict = VERDICT_SKIP
        record.skip_reason = "prep-only 模式：仅执行上游环境准备，目标场景未执行"
        record.given = {"depends_on": scenario.depends_display, "file": scenario.path}
        rctx.records.append(record)
        return record

    # 目标场景若已作为共享上游完整执行过（含 verify），直接复用，避免 HTTP+DB 全量重放
    if not rctx.skip_upstream_verify:
        for inst in rctx.instances.get(scenario.id, []):
            if inst.mode == MODE_SHARED:
                return inst.record

    record = run_scenario(scenario, rctx, extra_ns=dep_ns)
    minor_note = getattr(scenario, "_minor_drift_note", None)
    if minor_note:
        record.given["dep_version_note"] = minor_note
        scenario._minor_drift_note = None
    rctx.records.append(record)
    # PASS 的目标场景登记为共享实例：后续场景把它当 shared 上游时复用，不再重跑
    if record.verdict == VERDICT_PASS and not rctx.skip_upstream_verify:
        export_ns = dict(dep_ns)
        export_ns[scenario.id] = record.saved_vars
        inst = _Instance(scenario, record, MODE_SHARED, 1, export_ns)
        rctx.instances.setdefault(scenario.id, []).append(inst)
        rctx.shared_ns[scenario.id] = record.saved_vars
        if scenario.teardown:
            rctx.teardown_stack.append((scenario, inst))
    return record


# ════════════════════════════════════════════════════════
# run_single：plan_executor 引擎直跑入口（薄封装，不改调度语义）
# ════════════════════════════════════════════════════════

def run_single(scenario, rctx):
    """执行单个场景（含依赖闭包），返回 ExecutionRecord。

    plan_executor 引擎直跑的入口，复用 run_with_deps 的依赖解析与实例管理：
    - shared 上游 session 内复用；exclusive 上游按消费者懒重跑
    - 上游未通过 → 本场景 BLOCKED（下游自动跳过）
    - 版本仲裁：DRIFT/ORPHANED/SKIP 按既有语义处理

    Args:
        scenario: Scenario 对象（须在 rctx.graph.by_id 中）
        rctx: RunContext（由调用方装配，含 registry/env/token_provider/graph/db）

    Returns:
        ExecutionRecord（含 verdict / failure / skip_reason / saved_vars 等）
    """
    return run_with_deps(scenario, rctx)


# ════════════════════════════════════════════════════════
# teardown：session 末 LIFO 执行清理步骤（写型场景现场恢复/脏数据治理）
# ════════════════════════════════════════════════════════

def run_teardowns(rctx):
    """LIFO 执行全部已登记实例的 teardown 步骤。

    - 步骤插值使用该实例运行时的完整命名空间（可引用 {{session.id}} 等 flow 产出）
    - teardown 失败不改变场景 verdict，仅记录 trace（清理尽力而为，不阻塞报告）
    - 必须在报告落盘之前调用，teardown 轨迹才能进入 case JSON
    """
    for scenario, inst in reversed(rctx.teardown_stack):
        if inst.torn_down:
            continue
        inst.torn_down = True
        ns = getattr(inst.record, "run_ns", None) or dict(rctx.shared_ns)
        for step in scenario.teardown:
            if not isinstance(step, dict) or len(step) != 1:
                inst.record.steps.append(StepTrace(
                    type="teardown_error", note=f"teardown 步骤格式错误: {step}"))
                continue
            step_type, body = next(iter(step.items()))
            try:
                handler = rctx.registry.get_step(step_type)
                started = time.time()
                before = len(inst.record.steps)
                handler(body or {}, rctx, ns, inst.record)
                elapsed = int((time.time() - started) * 1000)
                if len(inst.record.steps) > before:
                    # 处理器自己追加了 trace → 改名标记为 teardown 阶段
                    for s in inst.record.steps[before:]:
                        s.type = "teardown:" + s.type
                        s.duration_ms = s.duration_ms or elapsed
                else:
                    # 处理器未追加 trace → 主动补一条，保证 teardown 可审计
                    inst.record.steps.append(StepTrace(
                        type=f"teardown:{step_type}", duration_ms=elapsed,
                        note=f"清理步骤 {step_type} 执行完成"))
            except Exception as e:
                inst.record.steps.append(StepTrace(
                    type="teardown_error",
                    note=f"{step_type} 清理失败（不影响场景结论）: {type(e).__name__}: {e}"))
    rctx.leases.release_all()   # session 结束整体释放全部租约
