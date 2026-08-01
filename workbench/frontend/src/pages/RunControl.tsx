/** RunControl — 执行控制（K-046 轻量化）：场景多选直跑 / 计划可选装载 / 轻量选项 / 实时日志流 / 多用户队列
 *
 * K-046：计划依赖是过时的纯前端设计（后端 runs/trigger 本就支持 scope=scenario 直跑）。
 * 现在默认视图 = 场景多选列表，勾选即跑；计划降级为「从计划装载」快捷方式
 * （装载后未改动选择 → 走 plansApi.run 保留计划归档；改动过 → ad-hoc 直跑）。
 * ?ids=A,B,C 预选（DAG 框选「执行选中」的落点）。
 */
import { useRef, useEffect, useState, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { runsApi, scenariosApi, plansApi, authApi, type Scenario, type TestPlan, type RunStatus } from '../api';
import { useRunStream } from '../hooks/useRunStream';
import PlanManager from '../components/PlanManager';
import Modal from '../components/Modal';

const SCOPES = [
  { value: 'all', label: '全量（全部场景）' },
  { value: 'engine_modes', label: '离线引擎自测（无需网络）' },
  { value: 'tag', label: '按标签…' },
  { value: 'scenario', label: '单场景…' },
];

interface BreakpointHitEvent {
  type: string;
  paused_at: string;
  batch_index: number;
  total_batches: number;
  completed: string[];
  context: {
    completed_count: number;
    completed: string[];
    recent_verdicts: { scenario_id: string; verdict: string }[];
    output_tail: string[];
  };
}

export default function RunControl() {
  const { events, connected, running, clear } = useRunStream();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState('');
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [plans, setPlans] = useState<TestPlan[]>([]);
  const [showLog, setShowLog] = useState(true);
  const [breakpoints] = useState<Set<string>>(new Set());
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [myEmpNo, setMyEmpNo] = useState('');
  const logRef = useRef<HTMLDivElement>(null);

  // ── K-046：选择优先的状态模型 ──
  // ?ids= 预选（DAG 编排「执行选中」跳转的落点）
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() =>
    new Set((searchParams.get('ids') || '').split(',').map(s => s.trim()).filter(Boolean)));
  const [loadedPlanId, setLoadedPlanId] = useState('');   // 从哪个计划装载的（空=手动选择）
  const [selDirty, setSelDirty] = useState(false);        // 装载后是否改动过选择
  const [moduleFilter, setModuleFilter] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [prepOnly, setPrepOnly] = useState(false);
  const [skipUpstreamVerify, setSkipUpstreamVerify] = useState(false);
  // 高级模式（按范围执行：tag/单场景表达式/全量/引擎自测）
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [scope, setScope] = useState('all');
  const [target, setTarget] = useState('');
  // K-049：触发前执行上下文确认（不是点一下就直接跑）
  const [showConfirm, setShowConfirm] = useState(false);

  // 队列状态轮询（M8：当前执行归属 + 排队列表）
  useEffect(() => {
    authApi.me().then(u => setMyEmpNo(u.emp_no)).catch(() => {});
    let alive = true;
    const poll = async () => {
      try {
        const s = await runsApi.status();
        if (alive) setRunStatus(s);
      } catch { /* 忽略轮询错误 */ }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const queue = useMemo(() => (runStatus?.queue || []).filter(q => q.status === 'queued'), [runStatus]);
  const currentOwner = runStatus?.current_emp_no || '';

  const cancelQueued = async (id: number) => {
    try {
      await runsApi.cancelQueued(id);
      const s = await runsApi.status();
      setRunStatus(s);
    } catch { /* 权限错误等静默 */ }
  };

  // 从事件中提取断点命中信息
  const breakpointHit = useMemo(() => {
    const hit = events.filter((e) => (e as unknown as { type: string }).type === 'breakpoint_hit');
    return hit.length ? (hit[hit.length - 1] as unknown as BreakpointHitEvent) : null;
  }, [events]);

  const isPaused = !!breakpointHit;

  const [dagEdges, setDagEdges] = useState<{ source: string; target: string }[]>([]);
  useEffect(() => {
    scenariosApi.list().then(setScenarios);
    scenariosApi.dag().then((d) => setDagEdges(d.edges || [])).catch(() => {});
  }, []);

  // ── K-046 补：执行上下文（闭包预览）──
  // 引擎按依赖闭包执行：选中的场景会连带其全部上游 prep。让「实际要跑什么」在触发前可见。
  const closureInfo = useMemo(() => {
    const ups = new Map<string, string[]>();
    dagEdges.forEach((e) => {
      if (!ups.has(e.target)) ups.set(e.target, []);
      ups.get(e.target)!.push(e.source);
    });
    const upstream = new Set<string>();
    const stack = [...selectedIds];
    while (stack.length) {
      const cur = stack.pop()!;
      (ups.get(cur) || []).forEach((u) => {
        if (!selectedIds.has(u) && !upstream.has(u)) { upstream.add(u); stack.push(u); }
      });
    }
    return { upstream: [...upstream].sort(), total: selectedIds.size + upstream.size };
  }, [dagEdges, selectedIds]);

  // K-011：计划列表由 PlanManager 加载并回调同步（K-046：不再默认选中第一个计划）
  const handlePlansChange = useCallback((p: TestPlan[]) => setPlans(p), []);

  /** K-046：从计划装载 = 把 plan.filter.scenarios 填入勾选（未改动 → 触发时走计划路径） */
  const handleLoadPlan = useCallback((id: string) => {
    setLoadedPlanId(id);
    if (!id) return;
    const plan = plans.find((p) => p.id === id);
    const ids = (plan?.filter?.scenarios || []) as string[];
    setSelectedIds(new Set(ids));
    setSelDirty(false);
  }, [plans]);

  const toggleId = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
    setSelDirty(true);
  }, []);

  // 模块清单
  const modules = useMemo(() => {
    const set = new Set<string>();
    scenarios.forEach((s) => { if (s.module) set.add(s.module); });
    return [...set].sort();
  }, [scenarios]);

  // 列表过滤（模块 + 搜索；选择状态独立于过滤）
  const filteredScenarios = useMemo(() => {
    let list = scenarios;
    if (moduleFilter) list = list.filter((s) => s.module === moduleFilter);
    const q = searchQ.trim().toLowerCase();
    if (q) list = list.filter((s) => s.id.toLowerCase().includes(q) || (s.title || '').toLowerCase().includes(q));
    return list;
  }, [scenarios, moduleFilter, searchQ]);

  // 运行事件 → verdict 映射（进度图标叠加在选择列表上）
  const verdictMap = useMemo(() => {
    const m = new Map<string, string>();
    events.forEach((e) => {
      if (e.scenario_id && e.verdict) m.set(e.scenario_id, e.verdict);
    });
    return m;
  }, [events]);

  // 进度统计（仅统计本次选中的场景）
  const counts = useMemo(() => {
    let passed = 0, failed = 0, skipped = 0;
    selectedIds.forEach((id) => {
      const v = verdictMap.get(id);
      if (v === 'PASSED') passed++;
      else if (v === 'FAILED' || v === 'ERROR') failed++;
      else if (v === 'SKIPPED') skipped++;
    });
    return { passed, failed, skipped };
  }, [selectedIds, verdictMap]);

  // 自动滚动
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  /** K-049：触发分两步——先弹执行上下文确认，用户确认后才真正触发 */
  const doTrigger = async () => {
    setShowConfirm(false);
    setError('');
    clear();
    try {
      let result: { ok: boolean; queued?: boolean; position?: number } | undefined;
      const light = { prepOnly, skipUpstreamVerify };
      if (loadedPlanId && !selDirty) {
        // 计划装载且未改动 → 走计划路径（保留 covers 闸/计划 env/断点/报告归档）
        result = await plansApi.run(loadedPlanId);
      } else if (selectedIds.size > 0) {
        // K-046：勾选直跑（后端原生支持 "A or B" 的 pytest -k 表达式）
        const expr = [...selectedIds].join(' or ');
        result = breakpoints.size > 0
          ? await runsApi.trigger('scenario', expr, 'sit', [...breakpoints], light)
          : await runsApi.trigger('scenario', expr, 'sit', [], light);
      } else {
        // 高级模式：按范围执行
        result = breakpoints.size > 0
          ? await runsApi.trigger(scope, target, 'sit', [...breakpoints], light)
          : await runsApi.trigger(scope, target, 'sit', [], light);
      }
      if (result?.queued) {
        setError(`已有执行进行中，已加入队列（第 ${result.position} 位）`);
        const s = await runsApi.status();
        setRunStatus(s);
      }
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '触发失败'); }
  };

  const resume = async () => {
    try { await runsApi.resume(); } catch { /* */ }
  };

  // K-047：终止失败（如无执行中任务）要显式报错，不再静默
  const abort = async () => {
    try { await runsApi.abort(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : '终止失败'); }
  };

  const vColor: Record<string, string> = {
    running: 'text-info animate-pulse',
    PASSED: 'text-pass',
    FAILED: 'text-fail',
    SKIPPED: 'text-skip',
    ERROR: 'text-fail',
  };
  const vIcon: Record<string, string> = {
    running: '◉', PASSED: '✓', FAILED: '✗', SKIPPED: '⊘', ERROR: '✗',
  };

  const triggerLabel = loadedPlanId && !selDirty
    ? `🚀 执行计划（${selectedIds.size} 场景）`
    : selectedIds.size > 0
      ? `🚀 执行选中（${selectedIds.size}）`
      : '🚀 触发执行';

  return (
    <div className="space-y-4 h-full flex flex-col">
      <h2 className="text-lg font-semibold">▶️ 执行控制</h2>

      {/* 触发面板（K-046：选择优先，计划为可选装载，高级范围模式折叠） */}
      <div className="flex items-center gap-3 flex-wrap">
        <select value={loadedPlanId} onChange={(e) => handleLoadPlan(e.target.value)}
          className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-sm"
          title="可选：从测试计划装载场景清单（装载后未改动 → 走计划执行路径）">
          <option value="">手动选择场景</option>
          {plans.map((p) => <option key={p.id} value={p.id}>📋 从计划装载：{p.name}</option>)}
        </select>
        {loadedPlanId && selDirty && (
          <span className="text-[10px] text-warn" title="选择已被手动修改，触发时将按勾选项直跑而非计划路径">
            ⚠️ 已改动选择，将直跑勾选项
          </span>
        )}
        {/* K-046：轻量执行选项（conftest 原生支持，runner 透传） */}
        <label className="text-xs text-gray-500 flex items-center gap-1"
          title="只跑上游环境准备（prep 场景），跳过消费场景">
          <input type="checkbox" checked={prepOnly} onChange={(e) => setPrepOnly(e.target.checked)} /> 仅准备
        </label>
        <label className="text-xs text-gray-500 flex items-center gap-1"
          title="上游场景只跑 flow 不做 verify 断言（加快闭包执行）">
          <input type="checkbox" checked={skipUpstreamVerify} onChange={(e) => setSkipUpstreamVerify(e.target.checked)} /> 上游不断言
        </label>
        <button onClick={() => setShowConfirm(true)} disabled={(running && !isPaused) || (!loadedPlanId && selectedIds.size === 0 && !showAdvanced)}
          className="px-4 py-1.5 rounded-md text-sm font-medium bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30 disabled:opacity-40">
          {isPaused ? '⏸ 已暂停' : running ? '⏳ 执行中…' : triggerLabel}
        </button>
        {isPaused && (
          <button onClick={resume}
            className="px-4 py-1.5 rounded-md text-sm font-medium bg-info/20 text-info border border-info/30 hover:bg-info/30 animate-pulse">
            ▶ 放行继续
          </button>
        )}
        {running && !isPaused && (
          <button onClick={abort}
            className="px-4 py-1.5 rounded-md text-sm font-medium bg-fail/20 text-fail border border-fail/30 hover:bg-fail/30">
            ⏹ 终止
          </button>
        )}
        <span className={`text-xs ${connected ? 'text-pass' : 'text-fail'}`}>
          {connected ? '● 已连接' : '○ 未连接'}
        </span>
        {/* K-046 补：执行上下文——环境 + 闭包预览（实际要跑什么，触发前可见） */}
        {selectedIds.size > 0 && (
          <details className="text-xs text-gray-500">
            <summary className="cursor-pointer hover:text-info">
              环境 sit · 闭包共 {closureInfo.total}（选中 {selectedIds.size}
              {closureInfo.upstream.length > 0 ? ` + 上游 ${closureInfo.upstream.length}` : ''}）
            </summary>
            {closureInfo.upstream.length > 0 && (
              <div className="mt-1 px-2 py-1.5 bg-surface-2 border border-border rounded max-w-md">
                <div className="text-[10px] text-gray-600 mb-1">连带上游（先执行）：</div>
                <div className="flex flex-wrap gap-1">
                  {closureInfo.upstream.map((id) => (
                    <span key={id} className="px-1 py-0.5 rounded bg-info/10 text-info/90 font-mono text-[10px]">{id}</span>
                  ))}
                </div>
              </div>
            )}
          </details>
        )}
        <label className="text-xs text-gray-500 flex items-center gap-1">
          <input type="checkbox" checked={showLog} onChange={(e) => setShowLog(e.target.checked)} /> 日志
        </label>
        <button onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-xs text-gray-500 hover:text-info ml-auto">
          {showAdvanced ? '▾ 收起高级' : '▸ 高级（按范围执行）'}
        </button>
      </div>

      {/* 高级模式：按范围执行（tag / 单场景表达式 / 全量 / 引擎自测） */}
      {showAdvanced && (
        <div className="flex items-center gap-3 flex-wrap border border-border rounded-lg px-3 py-2 bg-surface-2">
          <span className="text-xs text-gray-500">按范围执行：</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)}
            className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-sm">
            {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          {(scope === 'tag' || scope === 'scenario' || scope === 'module') && (
            <input value={target} onChange={(e) => setTarget(e.target.value)}
              placeholder={scope === 'tag' ? 'P0 / permission / snapshot' : 'PP-RC-005'}
              className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-sm w-48" />
          )}
          <span className="text-[10px] text-gray-600">勾选列表非空时优先按勾选项直跑；清空勾选后此处生效</span>
        </div>
      )}

      {error && <p className="text-sm text-fail">{error}</p>}

      {/* 多用户执行归属与队列（M8） */}
      {(currentOwner || queue.length > 0) && (
        <div className="border border-border rounded-lg px-3 py-2 bg-surface-2 space-y-1.5">
          {currentOwner && (
            <div className="text-xs text-gray-400">
              当前执行：<span className="text-info font-medium">{currentOwner}</span>
              {currentOwner === myEmpNo && <span className="text-gray-600">（我）</span>}
              {runStatus?.current_workspace && <span className="text-gray-600"> · 工作区 {runStatus.current_workspace}</span>}
            </div>
          )}
          {queue.length > 0 && (
            <div className="space-y-1">
              <div className="text-[11px] text-gray-500">排队中（{queue.length}）：</div>
              {queue.map((q, i) => (
                <div key={q.id} className="flex items-center gap-2 text-xs">
                  <span className="text-gray-600 font-mono">#{i + 1}</span>
                  <span className={q.emp_no === myEmpNo ? 'text-info' : 'text-gray-400'}>
                    {q.emp_no}{q.emp_no === myEmpNo && '（我）'}
                  </span>
                  <span className="text-gray-600">{q.scope}{q.target ? ` · ${q.target.slice(0, 40)}` : ''}</span>
                  <span className="text-gray-700 font-mono text-[10px]">{q.created_at}</span>
                  {(q.emp_no === myEmpNo || runStatus?.current_emp_no === myEmpNo) && (
                    <button onClick={() => cancelQueued(q.id)}
                      className="text-fail/80 hover:text-fail text-[10px]">取消</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 断点命中面板 */}
      {isPaused && breakpointHit && (
        <div className="border border-info/40 bg-info/5 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-lg">🔴</span>
            <div>
              <div className="text-sm font-medium text-info">
                断点命中：{breakpointHit.paused_at}
              </div>
              <div className="text-[11px] text-gray-400">
                批次 {breakpointHit.batch_index + 1}/{breakpointHit.total_batches} ·
                已完成 {breakpointHit.completed?.length || 0} 个场景
              </div>
            </div>
            <button onClick={resume}
              className="ml-auto px-4 py-1.5 rounded text-xs bg-info/20 text-info hover:bg-info/30">
              ▶ 放行继续
            </button>
          </div>

          {/* 上下文 */}
          {breakpointHit.context && (
            <div className="grid grid-cols-2 gap-3">
              {/* 已完成场景 */}
              <div className="bg-surface-2 rounded-lg p-3">
                <div className="text-[11px] text-gray-400 font-medium mb-1.5">✅ 已完成（{breakpointHit.context.completed_count}）</div>
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {(breakpointHit.context.completed || []).map((sid: string) => (
                    <div key={sid} className="text-[10px] font-mono text-pass/70">✓ {sid}</div>
                  ))}
                </div>
              </div>
              {/* 最近 verdict */}
              <div className="bg-surface-2 rounded-lg p-3">
                <div className="text-[11px] text-gray-400 font-medium mb-1.5">📊 最近结果</div>
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {(breakpointHit.context.recent_verdicts || []).map((v: { scenario_id: string; verdict: string }, i: number) => (
                    <div key={i} className={`text-[10px] font-mono ${
                      v.verdict === 'PASSED' ? 'text-pass' : v.verdict === 'FAILED' ? 'text-fail' : 'text-skip'
                    }`}>
                      {v.verdict === 'PASSED' ? '✓' : v.verdict === 'FAILED' ? '✗' : '⊘'} {v.scenario_id}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 输出尾部 */}
          {breakpointHit.context?.output_tail && (
            <details className="rounded-lg" style={{ background: 'rgb(var(--code-bg))' }}>
              <summary className="px-3 py-1.5 text-[10px] text-gray-500 cursor-pointer">📄 最近输出（{breakpointHit.context.output_tail.length} 行）</summary>
              <pre className="px-3 py-2 text-[10px] text-gray-400 font-mono max-h-32 overflow-y-auto">
                {breakpointHit.context.output_tail.join('\n')}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* 进度统计（本次选中场景） */}
      {[...verdictMap.keys()].some((id) => selectedIds.has(id)) && (
        <div className="flex gap-4 text-sm">
          <span className="text-pass">✓ {counts.passed} 通过</span>
          <span className="text-fail">✗ {counts.failed} 失败</span>
          <span className="text-skip">⊘ {counts.skipped} 跳过</span>
          <span className="text-gray-500">{counts.passed + counts.failed + counts.skipped}/{selectedIds.size}</span>
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* 计划管理（K-011：从原场景管理页迁入；K-046：仅作装载与管理，不再是执行前提） */}
        <PlanManager
          selectedPlan={loadedPlanId}
          onSelect={handleLoadPlan}
          onPlansChange={handlePlansChange}
        />

        {/* K-046：场景多选列表（选择 + 进度一体） */}
        <div className="w-[380px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border bg-surface-2 space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium">场景选择（{selectedIds.size} 已选）</span>
              <button onClick={() => { setSelectedIds(new Set(filteredScenarios.map(s => s.id))); setSelDirty(true); }}
                className="text-[10px] text-info hover:underline ml-auto">全选当前</button>
              <button onClick={() => { setSelectedIds(new Set()); setSelDirty(true); }}
                className="text-[10px] text-gray-500 hover:text-fail">清空</button>
            </div>
            <div className="flex gap-1.5">
              <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
                placeholder="🔍 ID / 标题"
                className="flex-1 min-w-0 bg-surface-3 border border-border rounded px-2 py-1 text-[11px]" />
              <select value={moduleFilter} onChange={(e) => setModuleFilter(e.target.value)}
                className="bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px] max-w-[120px]">
                <option value="">全部模块</option>
                {modules.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {filteredScenarios.map((s) => {
              const v = verdictMap.get(s.id) || '';
              const checked = selectedIds.has(s.id);
              return (
                <label key={s.id}
                  className={`flex items-center gap-2 px-3 py-1.5 text-xs border-b border-border/30 cursor-pointer hover:bg-surface-3/50 ${checked ? 'bg-info/5' : ''}`}>
                  <input type="checkbox" checked={checked} onChange={() => toggleId(s.id)} />
                  <span className={`${vColor[v] || 'text-gray-700'} w-4 text-center`}>{vIcon[v] || '○'}</span>
                  <span className="font-mono text-gray-400 w-28 truncate">{s.id}</span>
                  <span className="text-gray-500 truncate flex-1">{s.title}</span>
                </label>
              );
            })}
            {filteredScenarios.length === 0 && (
              <div className="text-center text-gray-600 text-xs py-8">无匹配场景</div>
            )}
          </div>
        </div>

        {/* 日志流 */}
        {showLog && (
          <div ref={logRef}
            className="flex-1 min-w-0 border border-border rounded-lg p-4 overflow-y-auto font-mono text-xs leading-5" style={{ background: 'rgb(var(--code-bg))' }}>
            {events.length === 0 ? (
              <p className="text-gray-600">勾选场景后点击「执行选中」；或从计划装载整组执行…</p>
            ) : (
              events.map((e, i) => {
                if (e.type === 'started') return <div key={i} className="text-info mt-2">▶ {e.cmd}</div>;
                if (e.type === 'finished') return <div key={i} className="text-pass mt-2">■ 完成 (exit={e.returncode})</div>;
                if (e.type === 'aborted') return <div key={i} className="text-skip mt-2">■ 已终止</div>;
                if (e.type !== 'output') return null;
                const line = e.line || '';
                let cls = 'text-gray-400';
                if (e.verdict === 'PASSED') cls = 'text-pass';
                else if (e.verdict === 'FAILED') cls = 'text-fail';
                else if (e.verdict === 'SKIPPED') cls = 'text-skip';
                else if (line.includes('ERROR')) cls = 'text-fail';
                else if (line.startsWith('=')) cls = 'text-gray-500';
                else if (line.includes('[SpecGuard]')) cls = 'text-info/80';
                return <div key={i} className={cls}>{line}</div>;
              })
            )}
          </div>
        )}
      </div>

      {/* K-049：执行上下文确认弹窗——触发前看清「用什么上下文、实际跑什么」 */}
      <Modal open={showConfirm} onClose={() => setShowConfirm(false)} title="确认执行上下文" width={440}>
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-[88px_1fr] gap-y-2 gap-x-3">
            <span className="text-gray-500">执行方式</span>
            <span className="text-gray-200">
              {loadedPlanId && !selDirty
                ? `📋 计划路径：${plans.find(p => p.id === loadedPlanId)?.name || loadedPlanId}`
                : selectedIds.size > 0
                  ? '☑️ 勾选直跑（pytest -k 表达式）'
                  : `🎯 范围执行：${SCOPES.find(s => s.value === scope)?.label || scope}${target ? ` · ${target}` : ''}`}
            </span>
            <span className="text-gray-500">环境</span>
            <span className="text-gray-200 font-mono">sit</span>
            <span className="text-gray-500">执行范围</span>
            <span className="text-gray-200">
              {selectedIds.size > 0 ? (
                <>
                  选中 <span className="text-info font-medium">{selectedIds.size}</span> 个场景
                  {closureInfo.upstream.length > 0 && (
                    <>，闭包连带 <span className="text-warn">{closureInfo.upstream.length}</span> 个上游（共 {closureInfo.total}）</>
                  )}
                </>
              ) : '按范围执行时的全部命中场景'}
            </span>
            {(prepOnly || skipUpstreamVerify) && (
              <>
                <span className="text-gray-500">轻量选项</span>
                <span className="text-warn">
                  {prepOnly && '仅准备（只跑上游 prep）'}{prepOnly && skipUpstreamVerify && ' · '}
                  {skipUpstreamVerify && '上游不断言'}
                </span>
              </>
            )}
          </div>
          {closureInfo.upstream.length > 0 && (
            <div className="px-2 py-1.5 bg-surface-2 border border-border rounded">
              <div className="text-[10px] text-gray-600 mb-1">连带上游（先于选中场景执行）：</div>
              <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
                {closureInfo.upstream.map((id) => (
                  <span key={id} className="px-1 py-0.5 rounded bg-info/10 text-info/90 font-mono text-[10px]">{id}</span>
                ))}
              </div>
            </div>
          )}
          <p className="text-[11px] text-gray-500 leading-relaxed">
            引擎按依赖闭包执行；执行日志包含每次接口调用的 method/path/status 与响应体
            <span className="text-info"> ifelc-trace_id</span>（网关全链追踪 ID，排查 BUG 直接可用）。
            执行真实调用目标环境，会产生真实测试数据。
          </p>
          <div className="flex gap-2 pt-1">
            <button onClick={doTrigger}
              className="flex-1 py-2 rounded-md text-sm font-medium bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30">
              🚀 确认执行
            </button>
            <button onClick={() => setShowConfirm(false)}
              className="px-4 py-2 rounded-md text-sm bg-surface-3 text-gray-400 hover:bg-surface-2">
              取消
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
