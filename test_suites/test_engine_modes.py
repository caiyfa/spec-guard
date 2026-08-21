"""引擎依赖模式离线自测：shared/exclusive 实例语义 + teardown + 命名空间绑定。

不依赖 SIT 网络/DB/账号——用桩步骤驱动引擎，可在任何机器直接运行：
    python -m pytest -k engine_modes -v
"""

import os

import pytest

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engine.registry import Registry                                  # noqa: E402
from engine.scenario_loader import (                                  # noqa: E402
    Scenario, ScenarioLoadError, _normalize_depends,
    MODE_SHARED, MODE_EXCLUSIVE,
)
from engine.dependency_graph import DependencyGraph                   # noqa: E402
from engine.execution_record import StepTrace                          # noqa: E402
from engine.scenario_runner import (                                  # noqa: E402
    RunContext, run_with_deps, run_teardowns, render,
    LeaseRegistry, SkipScenario,
    VERDICT_PASS, VERDICT_SKIP, VERDICT_BLOCKED,
)


# ── 测试装备 ──────────────────────────────────────────────

def make_rctx(scenarios, counters):
    """构建离线运行上下文：produce 步骤计数产出、read 步骤读命名空间、boom 步骤必失败"""
    reg = Registry()

    def step_produce(body, rctx, ns, record):
        key = body.get("key", "default")
        counters[key] = counters.get(key, 0) + 1
        return {"val": counters[key]}

    def step_read(body, rctx, ns, record):
        return render(body["expr"], ns)

    def step_boom(body, rctx, ns, record):
        raise RuntimeError("预期内失败")

    def step_teardown_log(body, rctx, ns, record):
        counters.setdefault("teardown_order", []).append(
            render(body.get("tag", ""), ns))

    reg.step("produce", step_produce)
    reg.step("read", step_read)
    reg.step("boom", step_boom)
    reg.step("teardown_log", step_teardown_log)

    graph = DependencyGraph(scenarios)
    return RunContext(registry=reg, env_config={}, token_provider=None,
                      graph=graph, run_dir=".")


def sc(sid, deps=None, flow=None, teardown=None):
    return Scenario(id=sid, title=sid,
                    depends_on=_normalize_depends(deps or [], sid),
                    flow=flow or [{"produce": {"key": sid, "save": "out"}}],
                    teardown=teardown or [])


# ── shared / exclusive 语义 ───────────────────────────────

def test_shared_upstream_runs_once():
    """两个 shared 消费者 → 上游只执行一次，变量共享"""
    counters = {}
    up = sc("UP")
    c1 = sc("C1", deps=["UP"], flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    c2 = sc("C2", deps=["UP"], flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    rctx = make_rctx([up, c1, c2], counters)

    r1 = run_with_deps(c1, rctx)
    r2 = run_with_deps(c2, rctx)
    assert counters["UP"] == 1, "shared 上游应只执行一次"
    assert r1.verdict == r2.verdict == VERDICT_PASS
    assert r1.saved_vars["got"] == r2.saved_vars["got"] == 1


def test_exclusive_creates_fresh_instance():
    """独占消费者各得一份全新实例；shared 实例不被独占触碰"""
    counters = {}
    up = sc("UP")
    shared_c = sc("SC", deps=["UP"], flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    e1 = sc("E1", deps=[{"id": "UP", "mode": "exclusive"}],
            flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    e2 = sc("E2", deps=[{"id": "UP", "mode": "exclusive"}],
            flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    rctx = make_rctx([up, shared_c, e1, e2], counters)

    rs = run_with_deps(shared_c, rctx)   # 共享实例 #1
    r1 = run_with_deps(e1, rctx)         # 独占实例 #2
    r2 = run_with_deps(e2, rctx)         # 独占实例 #3

    assert counters["UP"] == 3, "1 shared + 2 exclusive 应共执行 3 次"
    assert rs.saved_vars["got"] == 1, "shared 消费者绑定共享实例"
    assert r1.saved_vars["got"] == 2 and r2.saved_vars["got"] == 3, "独占消费者各绑定独立实例"
    # 实例池状态：UP 有 3 个实例，模式正确
    pool = rctx.instances["UP"]
    assert [i.mode for i in pool] == [MODE_SHARED, MODE_EXCLUSIVE, MODE_EXCLUSIVE]


def test_shared_consumer_after_exclusive_still_stable():
    """独占消费发生后，后续 shared 消费者仍复用共享实例（值不漂移）"""
    counters = {}
    up = sc("UP")
    e1 = sc("E1", deps=[{"id": "UP", "mode": "exclusive"}],
            flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    c1 = sc("C1", deps=["UP"], flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    c2 = sc("C2", deps=["UP"], flow=[{"read": {"expr": "{{UP.out.val}}", "save": "got"}}])
    rctx = make_rctx([up, e1, c1, c2], counters)

    run_with_deps(c1, rctx)              # 共享实例 val=1
    run_with_deps(e1, rctx)              # 独占实例 val=2
    r = run_with_deps(c2, rctx)
    assert r.saved_vars["got"] == 1, "shared 消费者不应看到独占实例的数据"
    assert counters["UP"] == 2


def test_transitive_instance_binding():
    """传递绑定：B 独占 A，C 依赖 B → C 引用 {{A.x}} 时绑定到 B 那份 A 实例"""
    counters = {}
    a = sc("A")
    b = sc("B", deps=[{"id": "A", "mode": "exclusive"}],
           flow=[{"read": {"expr": "{{A.out.val}}", "save": "a_val"}}])
    c = sc("C", deps=["B"],
           flow=[{"read": {"expr": "{{A.out.val}}", "save": "a_seen"}},
                 {"read": {"expr": "{{B.a_val}}", "save": "b_saw"}}])
    rctx = make_rctx([a, b, c], counters)

    r = run_with_deps(c, rctx)
    assert r.verdict == VERDICT_PASS
    assert r.saved_vars["a_seen"] == r.saved_vars["b_saw"], \
        "C 看到的 A 必须与 B 消费的是同一份实例"


def test_upstream_failure_blocks_consumer():
    """上游失败 → 消费者 BLOCKED；独占实例失败只阻塞绑定它的消费者"""
    counters = {}
    bad = sc("BAD", flow=[{"boom": {}}])
    c = sc("C", deps=["BAD"])
    rctx = make_rctx([bad, c], counters)
    r = run_with_deps(c, rctx)
    assert r.verdict == VERDICT_BLOCKED
    assert "BAD" in r.skip_reason


def test_target_reuses_shared_instance():
    """场景既是上游又被收集为目标 → 只执行一次（复用共享实例记录）"""
    counters = {}
    up = sc("UP")
    c = sc("C", deps=["UP"])
    rctx = make_rctx([up, c], counters)
    run_with_deps(c, rctx)               # UP 作为上游执行
    r = run_with_deps(up, rctx)          # UP 又被收集为目标
    assert counters["UP"] == 1, "目标场景应复用共享实例，不得双跑"
    assert r.verdict == VERDICT_PASS


# ── teardown ─────────────────────────────────────────────

def test_teardown_lifo_with_instance_vars():
    """teardown LIFO 执行，插值绑定各实例自己的变量"""
    counters = {}
    up = sc("UP", teardown=[{"teardown_log": {"tag": "UP#{{out.val}}"}}])
    e1 = sc("E1", deps=[{"id": "UP", "mode": "exclusive"}])
    e2 = sc("E2", deps=[{"id": "UP", "mode": "exclusive"}])
    rctx = make_rctx([up, e1, e2], counters)

    run_with_deps(e1, rctx)              # UP 实例 val=1
    run_with_deps(e2, rctx)              # UP 实例 val=2
    run_teardowns(rctx)
    assert counters["teardown_order"] == ["UP#2", "UP#1"], \
        "teardown 应 LIFO 且各实例用自己的变量插值"
    # teardown 轨迹落入实例记录
    traces = [s.type for inst in rctx.instances["UP"] for s in inst.record.steps]
    assert any(t.startswith("teardown:") for t in traces)


def test_teardown_failure_does_not_change_verdict():
    """teardown 失败仅记录 trace，不改变场景 verdict"""
    counters = {}
    up = sc("UP", teardown=[{"boom": {}}])
    c = sc("C", deps=["UP"])
    rctx = make_rctx([up, c], counters)
    run_with_deps(c, rctx)
    run_teardowns(rctx)
    inst = rctx.instances["UP"][0]
    assert inst.record.verdict == VERDICT_PASS
    assert any(s.type == "teardown_error" for s in inst.record.steps)


# ── loader 归一化 ─────────────────────────────────────────

def test_depends_normalization():
    """归一化契约（格式 2.0）：每项带 mode/version/optional"""
    deps = _normalize_depends(["A", {"id": "B", "mode": "exclusive"}, {"id": "C"}], "t")
    assert deps == [{"id": "A", "mode": MODE_SHARED, "version": None, "optional": False},
                    {"id": "B", "mode": MODE_EXCLUSIVE, "version": None, "optional": False},
                    {"id": "C", "mode": MODE_SHARED, "version": None, "optional": False}]


def test_depends_normalization_version_and_optional():
    """格式 2.0：version 期望与 optional 可选依赖透传"""
    deps = _normalize_depends(
        [{"id": "A", "version": "^1"}, {"id": "B", "mode": "exclusive", "version": "1.2", "optional": True}], "t")
    assert deps[0]["version"] == "^1"
    assert deps[1] == {"id": "B", "mode": MODE_EXCLUSIVE, "version": "1.2", "optional": True}


def test_depends_invalid_mode_rejected():
    with pytest.raises(ScenarioLoadError):
        _normalize_depends([{"id": "A", "mode": "monopoly"}], "t")


# ── LeaseRegistry 单元测试 ───────────────────────────────

def test_lease_registry_acquire_conflict():
    """同一资源键被租出后，第二次 acquire 返回 False"""
    reg = LeaseRegistry()
    assert reg.acquire("emp_no", "E001", "S1#1") is True
    assert reg.acquire("emp_no", "E001", "S2#1") is False
    assert reg.leased_keys("emp_no") == {"E001"}


def test_lease_registry_release():
    """release 后可重新租出"""
    reg = LeaseRegistry()
    reg.acquire("emp_no", "E001", "S1#1")
    reg.release("emp_no", "E001")
    assert reg.leased_keys("emp_no") == set()
    assert reg.acquire("emp_no", "E001", "S2#1") is True


def test_lease_registry_release_all():
    """release_all 清空全部租约"""
    reg = LeaseRegistry()
    reg.acquire("emp_no", "E001", "S1#1")
    reg.acquire("emp_no", "E002", "S2#1")
    reg.acquire("account", "A001", "S1#1")
    reg.release_all()
    assert reg.leased_keys("emp_no") == set()
    assert reg.leased_keys("account") == set()


def test_lease_registry_unknown_type_empty():
    """未注册的资源类型返回空集合"""
    reg = LeaseRegistry()
    assert reg.leased_keys("unknown_type") == set()


# ── 工号池租约集成测试 ───────────────────────────────────

class _StubPool:
    """测试用工号池桩：无 DB 校验，支持 exclude 参数"""
    def __init__(self, candidates):
        self._candidates = candidates

    def select(self, role, exclude=None):
        exclude = exclude or set()
        available = [c for c in self._candidates if c not in exclude]
        if not available:
            raise SkipScenario(
                f"工号池角色 {role} 候选均已被独占租出（{len(exclude)} 个被租）",
                category="pool_leased_out")
        return {"no": available[0], "role": role, "check_value": None}


def _make_rctx_with_pool(candidates):
    """构建含 select_emp 步骤的离线上下文（stub 工号池，无 DB）"""
    from systems.tdm.steps import make_select_emp
    reg = Registry()
    reg.step("select_emp", make_select_emp(_StubPool(candidates), None))
    graph = DependencyGraph([])
    return RunContext(registry=reg, env_config={}, token_provider=None,
                      graph=graph, run_dir=".")


def _sc_select(sid, role, exclusive=False):
    body = {"role": role, "save": "emp"}
    if exclusive:
        body["exclusive"] = True
    return Scenario(id=sid, title=sid,
                    depends_on=[], flow=[{"select_emp": body}], teardown=[])


def test_exclusive_select_emp_gets_different_emp_no():
    """两个 exclusive: true 同角色场景得到不同工号"""
    rctx = _make_rctx_with_pool(["E001", "E002", "E003"])
    e1 = _sc_select("E1", "snapshot_rich", exclusive=True)
    e2 = _sc_select("E2", "snapshot_rich", exclusive=True)
    r1 = run_with_deps(e1, rctx)
    r2 = run_with_deps(e2, rctx)
    assert r1.verdict == r2.verdict == VERDICT_PASS
    assert r1.saved_vars["emp"]["no"] != r2.saved_vars["emp"]["no"], \
        "两个独占消费者应得到不同工号"


def test_pool_leased_out_triggers_skip():
    """候选工号全部被租出 → SKIP（不是 FAIL），skip_category=pool_leased_out"""
    rctx = _make_rctx_with_pool(["E001", "E002"])   # 仅 2 个候选
    e1 = _sc_select("E1", "r", exclusive=True)      # 租 E001
    e2 = _sc_select("E2", "r", exclusive=True)      # 租 E002
    c1 = _sc_select("C1", "r", exclusive=True)      # 无候选 → SKIP
    run_with_deps(e1, rctx)
    run_with_deps(e2, rctx)
    r = run_with_deps(c1, rctx)
    assert r.verdict == VERDICT_SKIP, "候选耗尽应为 SKIP，不是 FAIL"
    assert r.skip_category == "pool_leased_out"


def test_release_allows_reacquire():
    """teardown 后 release_all，后续场景可再次租到工号"""
    rctx = _make_rctx_with_pool(["E001", "E002"])
    e1 = _sc_select("E1", "r", exclusive=True)
    e2 = _sc_select("E2", "r", exclusive=True)
    run_with_deps(e1, rctx)
    run_with_deps(e2, rctx)
    rctx.leases.release_all()                       # 模拟 teardown 后归还
    c1 = _sc_select("C1", "r", exclusive=True)
    r = run_with_deps(c1, rctx)
    assert r.verdict == VERDICT_PASS, "release 后应能成功租到工号"


def test_shared_select_emp_ignores_lease():
    """shared（非 exclusive）的 select_emp 不受租约限制，可复用已被独占的工号"""
    rctx = _make_rctx_with_pool(["E001", "E002"])
    e1 = _sc_select("E1", "r", exclusive=True)      # 租 E001
    c1 = _sc_select("C1", "r", exclusive=False)     # shared：不排除已租工号
    r1 = run_with_deps(e1, rctx)
    r2 = run_with_deps(c1, rctx)
    assert r1.verdict == r2.verdict == VERDICT_PASS
    assert r2.saved_vars["emp"]["no"] == "E001", \
        "shared select_emp 应不受租约限制，选中第一个候选（即使已被独占）"


# ── U-1: DB 断言支持 ─────────────────────────────────────

class _StubDb:
    """测试用 DB 桩：返回预置查询结果"""
    def __init__(self, rows):
        self._rows = rows
    def query(self, sql):
        return self._rows
    def scalar(self, sql, params=()):
        return self._rows[0][list(self._rows[0].keys())[0]] if self._rows else None


def _make_rctx_with_db(rows):
    """构建含 db_query + call 的离线上下文（stub DB）"""
    reg = Registry()
    from engine.scenario_runner import step_db_query, step_call
    reg.step("db_query", step_db_query)
    reg.step("call", step_call)
    graph = DependencyGraph([])
    rctx = RunContext(registry=reg, env_config={"default_service": "tdm", "tdm_base": "http://stub"},
                      token_provider=None, graph=graph, run_dir=".")
    rctx.db = _StubDb(rows)
    return rctx


def test_db_query_result_assertable():
    """U-1: db_query 裸数组可被 json 断言直接消费"""
    rows = [
        {"total_score": None, "rank_overall": "A", "emp_no": "90024713"},
        {"total_score": 85.5, "rank_overall": "B", "emp_no": "90001063"},
    ]
    rctx = _make_rctx_with_db(rows)
    sc = Scenario(
        id="DB-ASSERT-001", title="DB 断言测试",
        depends_on=[],
        flow=[{"db_query": {"sql": "SELECT * FROM t", "save": "rows"}}],
        verify=[
            {"json": {"of": "rows", "path": "$[0].total_score", "eq": None}},
            {"json": {"of": "rows", "path": "$[0].rank_overall", "not_null": True}},
            {"json": {"of": "rows", "path": "$", "len_eq": 2}},
        ],
    )
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS, f"DB 断言应通过: {[a.message for a in r.assertions if not a.passed]}"


def test_db_query_assertion_failure():
    """U-1: db_query 断言失败时正确标记 FAIL"""
    rows = [{"total_score": 100, "rank_overall": "A"}]
    rctx = _make_rctx_with_db(rows)
    sc = Scenario(
        id="DB-ASSERT-002", title="DB 断言失败测试",
        depends_on=[],
        flow=[{"db_query": {"sql": "SELECT * FROM t", "save": "rows"}}],
        verify=[
            {"json": {"of": "rows", "path": "$[0].total_score", "eq": None}},  # 应为 100 不是 None
        ],
    )
    r = run_with_deps(sc, rctx)
    assert r.verdict != VERDICT_PASS, "断言不匹配时应 FAIL"


# ── U-2: poll 轮询 ─────────────────────────────────────

class _StubHttpClient:
    """测试用 HTTP 客户端桩：前 N 次返回处理中，之后返回 DONE"""
    def __init__(self, done_after=3):
        self.call_count = 0
        self.done_after = done_after

    def request(self, method, path, **kwargs):
        self.call_count += 1
        class FakeResp:
            def __init__(self, status, json_data):
                self.status_code = status
                self._json = json_data
                self.headers = {}
            def json(self):
                return self._json
        if self.call_count < self.done_after:
            return FakeResp(200, {"data": {"status": "PROCESSING"}})
        return FakeResp(200, {"data": {"status": "DONE", "result": "ok"}})


def _make_rctx_with_poll_client(client):
    """构建含 poll 步骤的离线上下文"""
    from engine.scenario_runner import step_poll
    reg = Registry()
    reg.step("poll", step_poll)
    graph = DependencyGraph([])
    rctx = RunContext(registry=reg, env_config={"default_service": "tdm", "tdm_base": "http://stub"},
                      token_provider=None, graph=graph, run_dir=".")
    rctx._clients[("tdm", "default")] = client  # K-055：client 缓存键改 (service, account)
    # 预置账号配置
    rctx.env["accounts"] = {"default": {"ad": "test", "emp_no": "90000000"}}
    return rctx


def test_poll_exits_when_condition_met():
    """U-2: poll 在条件满足时退出并返回末次响应"""
    client = _StubHttpClient(done_after=3)
    rctx = _make_rctx_with_poll_client(client)
    sc = Scenario(
        id="POLL-001", title="轮询成功",
        depends_on=[],
        flow=[{"poll": {
            "call": {"method": "GET", "path": "/api/task/result"},
            "until": [{"json": {"path": "$.data.status", "eq": "DONE"}}],
            "interval_ms": 10,
            "timeout_ms": 5000,
            "save": "result",
        }}],
        verify=[
            {"json": {"of": "result", "path": "$.data.status", "eq": "DONE"}},
            {"json": {"of": "result", "path": "$.data.result", "eq": "ok"}},
        ],
    )
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS
    assert client.call_count == 3, f"应在第 3 轮退出，实际 {client.call_count} 轮"
    poll_traces = [s for s in r.steps if s.type.startswith("poll:")]
    assert len(poll_traces) >= 3, f"应有至少 3 条轮询 trace，实际 {len(poll_traces)}"


def test_poll_timeout_fails():
    """U-2: poll 超时按 on_timeout=fail 产出 AssertionError"""
    client = _StubHttpClient(done_after=999)  # 永远不完
    rctx = _make_rctx_with_poll_client(client)
    sc = Scenario(
        id="POLL-002", title="轮询超时",
        depends_on=[],
        flow=[{"poll": {
            "call": {"method": "GET", "path": "/api/task/result"},
            "until": [{"json": {"path": "$.data.status", "eq": "DONE"}}],
            "interval_ms": 10,
            "timeout_ms": 50,
            "on_timeout": "fail",
            "save": "result",
        }}],
        verify=[],
    )
    r = run_with_deps(sc, rctx)
    assert r.verdict != VERDICT_PASS, "超时应 FAIL"


def test_poll_timeout_skip():
    """U-2: poll 超时按 on_timeout=skip 产出 SkipScenario"""
    client = _StubHttpClient(done_after=999)
    rctx = _make_rctx_with_poll_client(client)
    sc = Scenario(
        id="POLL-003", title="轮询超时跳过",
        depends_on=[],
        flow=[{"poll": {
            "call": {"method": "GET", "path": "/api/task/result"},
            "until": [{"json": {"path": "$.data.status", "eq": "DONE"}}],
            "interval_ms": 10,
            "timeout_ms": 50,
            "on_timeout": "skip",
            "save": "result",
        }}],
        verify=[],
    )
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_SKIP, "on_timeout=skip 时应 SKIP"


# ── random 随机步骤 ──────────────────────────────────────

def _make_rctx_with_random():
    from engine.scenario_runner import step_random
    reg = Registry()
    reg.step("random", step_random)
    # T-972：领域词库不再引擎内置——测试自注册所需池（生产由 systems/tdm 注入）
    reg.pools.update({
        "activity_name": ["年度干部盘点", "半年度人才盘点", "季度绩效盘点"],
        "person_name": ["张超", "李明", "王芳"],
    })
    graph = DependencyGraph([])
    return RunContext(registry=reg, env_config={}, token_provider=None,
                      graph=graph, run_dir=".")


def test_random_number_in_range():
    """random number 在指定范围内"""
    rctx = _make_rctx_with_random()
    sc = Scenario(id="RND-001", title="随机数",
                  depends_on=[],
                  flow=[{"random": {"type": "number", "min": 10, "max": 20, "save": "num"}}],
                  verify=[])
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS
    assert 10 <= r.saved_vars["num"] <= 20


def test_random_text_from_pool():
    """random text 从词库选取自然语言文本"""
    rctx = _make_rctx_with_random()
    sc = Scenario(id="RND-002", title="随机文本",
                  depends_on=[],
                  flow=[{"random": {"type": "text", "pool": "activity_name", "save": "name"}}],
                  verify=[])
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS
    assert len(r.saved_vars["name"]) > 2  # 自然语言文本不为空
    assert "盘点" in r.saved_vars["name"]  # activity_name 词库都含"盘点"


def test_random_text_with_suffix():
    """random text 带随机后缀保证唯一性"""
    rctx = _make_rctx_with_random()
    sc = Scenario(id="RND-003", title="随机文本带后缀",
                  depends_on=[],
                  flow=[{"random": {"type": "text", "pool": "person_name", "suffix": True, "save": "name"}}],
                  verify=[])
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS
    name = r.saved_vars["name"]
    assert "-" in name, f"应含随机后缀: {name}"
    parts = name.split("-")
    assert len(parts) == 2 and parts[1].isdigit()


def test_random_uuid():
    """random uuid 生成短 UUID"""
    rctx = _make_rctx_with_random()
    sc = Scenario(id="RND-004", title="随机UUID",
                  depends_on=[],
                  flow=[{"random": {"type": "uuid", "save": "id"}}],
                  verify=[])
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS
    assert len(r.saved_vars["id"]) == 8


def test_random_pick_from_items():
    """random pick 从自定义列表随机选"""
    rctx = _make_rctx_with_random()
    sc = Scenario(id="RND-005", title="随机选取",
                  depends_on=[],
                  flow=[{"random": {"type": "pick", "items": ["A", "B", "C"], "save": "val"}}],
                  verify=[])
    r = run_with_deps(sc, rctx)
    assert r.verdict == VERDICT_PASS
    assert r.saved_vars["val"] in ["A", "B", "C"]


# ── REQ-1: 数组下标插值 ──────────────────────────────────

from engine.scenario_runner import render as _render_fn


def test_resolve_array_index():
    """REQ-1: 插值支持数组下标 rows[0].field"""
    ns = {
        "rows": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}],
        "resp": {"json": {"data": {"records": [{"id": 100}, {"id": 200}]}}},
    }
    assert _render_fn("{{rows[0].id}}", ns) == 1
    assert _render_fn("{{rows[0].name}}", ns) == "first"
    assert _render_fn("{{rows[-1].id}}", ns) == 2
    assert _render_fn("{{resp.json.data.records[0].id}}", ns) == 100
    assert _render_fn("{{resp.json.data.records[1].id}}", ns) == 200


def test_resolve_dotted_path_unchanged():
    """REQ-1: 存量点号路径回归不变"""
    ns = {"emp": {"no": "90024713", "name": "张超"}, "session": {"json": {"data": {"id": 42}}}}
    assert _render_fn("{{emp.no}}", ns) == "90024713"
    assert _render_fn("{{emp.name}}", ns) == "张超"
    assert _render_fn("{{session.json.data.id}}", ns) == 42


def test_resolve_embedded_string():
    """REQ-1: 嵌入字符串拼接正确"""
    ns = {"resp": {"json": {"data": {"records": [{"id": 99}]}}}}
    result = _render_fn("/api/persons/{{resp.json.data.records[0].id}}/lock", ns)
    assert result == "/api/persons/99/lock"


# ── REQ-2: fn 函数 ──────────────────────────────────────

def test_fn_timestamp():
    """REQ-2: fn.timestamp 渲染为秒级时间戳"""
    val = _render_fn("{{fn.timestamp}}", {})
    assert isinstance(val, str)
    assert val.isdigit()
    assert int(val) > 1700000000  # 2023 年后


def test_fn_date():
    """REQ-2: fn.date 渲染为 YYYYMMDD"""
    val = _render_fn("{{fn.date}}", {})
    assert isinstance(val, str)
    assert len(val) == 8
    assert val.isdigit()


def test_fn_uuid_short():
    """REQ-2: fn.uuid_short 渲染为 8 位 hex"""
    val = _render_fn("{{fn.uuid_short}}", {})
    assert isinstance(val, str)
    assert len(val) == 8


def test_fn_embedded():
    """REQ-2: fn 嵌入字符串拼接"""
    val = _render_fn("SG导入校验-{{fn.timestamp}}", {})
    assert val.startswith("SG导入校验-")
    assert val.split("-")[1].isdigit()


def test_fn_monotonic():
    """REQ-2: 两次独立渲染单调不减"""
    v1 = int(_render_fn("{{fn.timestamp}}", {}))
    v2 = int(_render_fn("{{fn.timestamp}}", {}))
    assert v2 >= v1


# ── REQ-3: env vars 暴露 ──────────────────────────────────

def test_env_vars_exposed():
    """REQ-3: env yaml vars 段经 {{env.vars.*}} 引用"""
    reg = Registry()
    graph = DependencyGraph([])
    env_config = {
        "default_resource_code": "TEST_RC",
        "vars": {
            "fixture_corp": {"code": "1002", "name": "远东租赁"},
            "fixture_emp_nos": ["90024713", "90027339"],
        },
    }
    rctx = RunContext(registry=reg, env_config=env_config, token_provider=None,
                      graph=graph, run_dir=".")
    ns = rctx.shared_ns
    assert _render_fn("{{env.resource_code}}", ns) == "TEST_RC"
    assert _render_fn("{{env.vars.fixture_corp.code}}", ns) == "1002"
    assert _render_fn("{{env.vars.fixture_corp.name}}", ns) == "远东租赁"
    # list 整体替换（render 完全匹配分支）
    assert _render_fn("{{env.vars.fixture_emp_nos}}", ns) == ["90024713", "90027339"]


def test_env_vars_empty_when_missing():
    """REQ-3: env yaml 无 vars 段时渲染为空 dict 不报错"""
    reg = Registry()
    graph = DependencyGraph([])
    rctx = RunContext(registry=reg, env_config={}, token_provider=None,
                      graph=graph, run_dir=".")
    ns = rctx.shared_ns
    assert ns["env"]["vars"] == {}
