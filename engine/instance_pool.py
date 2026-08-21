"""实例池与资源租约（T-999c 自 scenario_runner 抽出，行为零变化）。

- LeaseRegistry：session 级资源租约注册表（挂 RunContext，进程结束即消亡）
- 实例池：shared 复用 / exclusive 懒重跑新建（写型场景状态管理核心）
- 依赖仲裁辅助：_check_dep_versions / _verdict_record / _blocked_record

run_scenario 走函数级延迟 import（pool⇄runner 模块级互依会成环）。
"""

from engine.execution_record import (
    CAT_CONTRACT_DRIFT,
    CAT_CONTRACT_ORPHAN,
    CAT_UPSTREAM,
    VERDICT_BLOCKED,
    VERDICT_DRIFT,
    VERDICT_FAIL,
    VERDICT_ORPHANED,
    VERDICT_PASS,
    VERDICT_SKIP,
    ExecutionRecord,
)
from engine.scenario_loader import MODE_SHARED

# ══════════════════════════════════════════════════════════
# 资源租约注册表（session 级，进程结束即消亡）
# ══════════════════════════════════════════════════════════

class LeaseRegistry:
    """session 级资源租约注册表。任何步骤处理器/调度器都可接入。

    resource_type: 资源类型标识（emp_no / session_id / account / config_key / ...）
    key:           资源实例标识
    holder:        持有者（场景 ID + 实例号），用于报告展示与冲突诊断
    租约是 session 级，挂在 RunContext 上，进程结束即消亡。
    """
    def __init__(self):
        self._leases = {}   # {resource_type: {key: holder}}

    def acquire(self, resource_type, key, holder):
        held = self._leases.setdefault(resource_type, {})
        if key in held:
            return False          # 已被租出，调用方决定换候选还是 SKIP
        held[key] = holder
        return True

    def leased_keys(self, resource_type):
        return set(self._leases.get(resource_type, {}))

    def release(self, resource_type, key):        # teardown/实例清理时归还
        self._leases.get(resource_type, {}).pop(key, None)

    def release_all(self):                        # session 结束时整体释放
        self._leases.clear()

    def snapshot(self):                           # 报告落盘用：{type: {key: holder}}
        return {t: dict(keys) for t, keys in self._leases.items()}



# ══════════════════════════════════════════════════════════
# 实例池：shared 复用 / exclusive 新建（写型场景状态管理核心）
# ════════════════════════════════════════════════════════

class _Instance:
    """上游场景的一次执行实例。

    - mode=shared：session 内唯一，所有只读消费者共享
    - mode=exclusive：为单个消费者新建，消费者可变更其状态而不影响其他人
    export_ns：本实例及其依赖闭包的变量快照 {scenario_id: saved_vars}，
    消费者合并后得到“与本实例一致的世界观”（传递引用绑定到同一套实例）。
    """

    def __init__(self, scenario, record, mode, no, export_ns):
        self.scenario = scenario
        self.record = record
        self.mode = mode
        self.no = no                   # 实例序号（1 起，报告区分多实例）
        self.export_ns = export_ns     # {scenario_id: saved_vars}，含传递依赖
        self.torn_down = False


class _UpstreamFailed(Exception):
    """上游实例未通过，携带 (scenario_id, verdict) 供消费者标记 BLOCKED"""

    def __init__(self, sid, verdict):
        self.sid, self.verdict = sid, verdict
        super().__init__(f"{sid}: {verdict}")


def _resolve_dep_ns(scenario, rctx, consumer_id):
    """解析场景的直接依赖 → 合并后的实例绑定命名空间。上游未通过时抛 _UpstreamFailed。"""
    dep_ns = {}
    for dep in scenario.depends_on:
        inst = _acquire_instance(dep["id"], rctx, consumer_id, dep["mode"])
        if inst.record.verdict != VERDICT_PASS:
            raise _UpstreamFailed(dep["id"], inst.record.verdict)
        dep_ns.update(inst.export_ns)
    return dep_ns


def _acquire_instance(scenario_id, rctx, consumer_id, mode):
    """获取上游场景的可用实例。

    - shared：复用池内共享实例（无则创建）；共享实例永不被独占消费者触碰
    - exclusive：总是新建全新实例（懒重跑），其依赖闭包递归按各自 mode 获取：
      闭包内 shared 上游仍复用缓存，exclusive 上游同样新建（递归独占）
    - ENG-T02 版本仲裁下沉：每一跳取实例前先仲裁（深层 DRIFT/ORPHANED 不再漏检）；
      传递孤儿依赖不抛裸 KeyError，按上游失败语义传播（ENG-BUG-010）
    """
    pool = rctx.instances.setdefault(scenario_id, [])
    if mode == MODE_SHARED:
        for inst in pool:
            if inst.mode == MODE_SHARED:
                return inst
    scenario = rctx.graph.by_id.get(scenario_id)
    if scenario is None:
        # 传递孤儿依赖：此前 by_id[...] 直接 KeyError 冒泡（pytest ERROR 无 verdict）
        raise _UpstreamFailed(scenario_id, VERDICT_ORPHANED)
    verdict, reason = _check_dep_versions(scenario, rctx)   # 每一跳都仲裁（ENG-BUG-002③）
    if verdict:
        record = _verdict_record(scenario, verdict, reason)
        record.upstream_of = consumer_id
        rctx.records.append(record)
        raise _UpstreamFailed(scenario_id, verdict)
    from engine.scenario_runner import run_scenario          # noqa: I001 函数级：防 pool⇄runner 模块环

    dep_ns = _resolve_dep_ns(scenario, rctx, consumer_id)   # 先递归准备它自己的上游

    no = len(pool) + 1
    record = run_scenario(scenario, rctx, upstream_of=consumer_id,
                          run_verify=not rctx.skip_upstream_verify,
                          extra_ns=dep_ns, instance_no=no)
    record.dep_mode = mode
    rctx.records.append(record)

    export_ns = dict(dep_ns)
    export_ns[scenario_id] = record.saved_vars
    inst = _Instance(scenario, record, mode, no, export_ns)
    pool.append(inst)
    if record.verdict == VERDICT_PASS and mode == MODE_SHARED:
        rctx.shared_ns[scenario_id] = record.saved_vars   # 仅共享实例发布到全局
    if scenario.teardown:
        rctx.teardown_stack.append((scenario, inst))       # 失败实例也登记（尽力清理）
    return inst


def _blocked_record(scenario, sid, verdict):
    record = ExecutionRecord(
        scenario_id=scenario.id, title=scenario.title, covers=scenario.covers,
        tags=scenario.tags, priority=scenario.priority, doc=scenario.doc)
    record.verdict = VERDICT_BLOCKED
    record.skip_reason = f"上游场景 {sid} 未通过（{verdict}），本场景未执行"
    # ENG-BUG-001：BLOCKED 场景复用 skip_category 字段承载上游分类（不得调 fail() 改写 verdict）
    record.skip_category = CAT_UPSTREAM
    record.given = {"depends_on": scenario.depends_display, "file": scenario.path}
    return record


def _verdict_record(scenario, verdict, reason):
    record = ExecutionRecord(
        scenario_id=scenario.id, title=scenario.title, covers=scenario.covers,
        tags=scenario.tags, priority=scenario.priority, doc=scenario.doc)
    record.verdict = verdict
    record.skip_reason = reason
    # ENG-T02：DRIFT/ORPHANED/strict-FAIL 填充 failure（不调 fail() 以免 verdict 被改写）——
    # pytest 侧 [unknown] 空消息消失，plan_executor 侧 FAIL 通知路径可用
    if verdict == VERDICT_ORPHANED:
        record.failure = {"category": CAT_CONTRACT_ORPHAN, "message": reason, "evidence": None}
    elif verdict in (VERDICT_DRIFT, VERDICT_FAIL):
        record.failure = {"category": CAT_CONTRACT_DRIFT, "message": reason, "evidence": None}
    record.given = {"depends_on": scenario.depends_display, "file": scenario.path}
    return record


def _check_dep_versions(scenario, rctx):
    """版本仲裁（格式 2.0）：执行前评估依赖边的版本匹配状态。

    返回 (verdict, reason)；全部满足返回 (None, "")。
    - 上游缺失 + optional → SKIP（可选依赖豁免，两种模式一致）
    - 上游缺失 → ORPHANED（strict_deps 下 FAIL）
    - 契约版本 MAJOR 漂移 → DRIFT（strict_deps 下 FAIL）
    - MINOR 漂移 → 放行（调用方记录提示）

    ENG-T02：除 run_with_deps 顶层（目标场景自己的结论）外，_acquire_instance
    对依赖链每一跳调用本函数——深层漂移/孤儿不再漏检。
    """
    from engine.dependency_graph import ORPHAN
    from engine.versioning import MAJOR_DRIFT, MINOR_DRIFT
    minor_notes = []
    for st in rctx.graph.dep_status.get(scenario.id, []):
        status = st["status"]
        if status == ORPHAN:
            if st["optional"]:
                return VERDICT_SKIP, f"可选依赖 {st['id']} 不存在，场景跳过（optional）"
            if rctx.strict_deps:
                return VERDICT_FAIL, f"依赖场景 {st['id']} 不存在（strict_deps 严格模式）"
            return VERDICT_ORPHANED, f"依赖场景 {st['id']} 不存在——上游已删除/改名，请修正 depends_on"
        if status == MAJOR_DRIFT:
            msg = (f"依赖 {st['id']} 契约版本漂移: 期望 {st['version'] or '(未声明)'} "
                   f"实际 v{st['actual']}")
            if rctx.strict_deps:
                return VERDICT_FAIL, msg + "（strict_deps 严格模式）"
            return VERDICT_DRIFT, msg + "——请核对上游契约后 bump 期望版本"
        if status == MINOR_DRIFT:
            minor_notes.append(f"{st['id']}(期望{st['version']}/实际v{st['actual']})")
    if minor_notes:
        scenario._minor_drift_note = "MINOR 漂移放行: " + ", ".join(minor_notes)
    return None, ""
