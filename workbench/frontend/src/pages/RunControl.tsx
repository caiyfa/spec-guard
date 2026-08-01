/** RunControl — 执行控制：计划管理 / 触发 / 结构化进度 / 实时日志流 / 终止 / 多用户队列 */
import { useRef, useEffect, useState, useMemo, useCallback } from 'react';
import { runsApi, scenariosApi, plansApi, authApi, type Scenario, type TestPlan, type RunStatus } from '../api';
import { useRunStream } from '../hooks/useRunStream';
import PlanManager from '../components/PlanManager';

const SCOPES = [
  { value: 'all', label: '全量（全部场景）' },
  { value: 'engine_modes', label: '离线引擎自测（无需网络）' },
  { value: 'tag', label: '按标签…' },
  { value: 'scenario', label: '单场景…' },
];

interface ScenarioProgress {
  id: string;
  title: string;
  verdict: 'pending' | 'running' | 'PASSED' | 'FAILED' | 'SKIPPED' | 'ERROR';
}

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
  const [scope, setScope] = useState('all');
  const [target, setTarget] = useState('');
  const [error, setError] = useState('');
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [plans, setPlans] = useState<TestPlan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState('');
  const [showLog, setShowLog] = useState(true);
  const [breakpoints] = useState<Set<string>>(new Set());
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [myEmpNo, setMyEmpNo] = useState('');
  const logRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    scenariosApi.list().then(setScenarios);
  }, []);

  // K-011：计划列表由 PlanManager 加载并回调同步（保留当前选中；首次默认选第一个计划）
  const handlePlansChange = useCallback((p: TestPlan[]) => {
    setPlans(p);
    setSelectedPlan(prev => prev || (p.length ? p[0].id : ''));
  }, []);

  const handleSelectPlan = useCallback((id: string) => {
    setSelectedPlan(id);
    setScope('all');
  }, []);

  // 当前计划对应的场景 ID 集合
  const planScenarioIds = useMemo(() => {
    if (!selectedPlan) return null; // null = 全部
    const plan = plans.find((p) => p.id === selectedPlan);
    if (!plan) return null;
    const ids = (plan.filter?.scenarios || []) as string[];
    return ids.length ? new Set(ids) : null;
  }, [selectedPlan, plans]);

  // 过滤后的场景列表
  const filteredScenarios = useMemo(() => {
    if (!planScenarioIds) return scenarios;
    return scenarios.filter((s) => planScenarioIds.has(s.id));
  }, [scenarios, planScenarioIds]);

  // 从事件中构建场景进度
  const progress = useMemo<ScenarioProgress[]>(() => {
    const verdictMap = new Map<string, ScenarioProgress['verdict']>();
    events.forEach((e) => {
      if (e.scenario_id && e.verdict) {
        verdictMap.set(e.scenario_id, e.verdict as ScenarioProgress['verdict']);
      }
    });
    return filteredScenarios.map((s) => ({
      id: s.id,
      title: s.title,
      verdict: (verdictMap.get(s.id) || 'pending') as ScenarioProgress['verdict'],
    }));
  }, [events, filteredScenarios]);

  // 自动滚动
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  const trigger = async () => {
    setError('');
    clear();
    try {
      let result: { ok: boolean; queued?: boolean; position?: number } | undefined;
      if (selectedPlan && scope === 'all') {
        result = await plansApi.run(selectedPlan);
      } else if (breakpoints.size > 0) {
        // 有断点 → 用 trigger API 带断点
        const bpList = [...breakpoints];
        result = await runsApi.trigger(scope, target, 'sit', bpList);
      } else {
        result = await runsApi.trigger(scope, target);
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

  const abort = async () => { try { await runsApi.abort(); } catch { /* */ } };

  const counts = useMemo(() => ({
    passed: progress.filter((p) => p.verdict === 'PASSED').length,
    failed: progress.filter((p) => p.verdict === 'FAILED').length,
    skipped: progress.filter((p) => p.verdict === 'SKIPPED').length,
    total: progress.length,
  }), [progress]);

  const vColor: Record<string, string> = {
    pending: 'text-gray-600',
    running: 'text-info animate-pulse',
    PASSED: 'text-pass',
    FAILED: 'text-fail',
    SKIPPED: 'text-skip',
    ERROR: 'text-fail',
  };
  const vIcon: Record<string, string> = {
    pending: '○', running: '◉', PASSED: '✓', FAILED: '✗', SKIPPED: '⊘', ERROR: '✗',
  };

  return (
    <div className="space-y-4 h-full flex flex-col">
      <h2 className="text-lg font-semibold">▶️ 执行控制</h2>

      {/* 触发面板 */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* 计划选择器 */}
        <select value={selectedPlan} onChange={(e) => handleSelectPlan(e.target.value)}
          className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-sm">
          <option value="">全部场景</option>
          {plans.map((p) => <option key={p.id} value={p.id}>📋 {p.name}</option>)}
        </select>
        {!selectedPlan && (
          <>
            <select value={scope} onChange={(e) => setScope(e.target.value)}
              className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-sm">
              {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            {(scope === 'tag' || scope === 'scenario' || scope === 'module') && (
              <input value={target} onChange={(e) => setTarget(e.target.value)}
                placeholder={scope === 'tag' ? 'P0 / permission / snapshot' : 'PP-RC-005'}
                className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-sm w-48" />
            )}
          </>
        )}
        <button onClick={trigger} disabled={running && !isPaused}
          className="px-4 py-1.5 rounded-md text-sm font-medium bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30 disabled:opacity-40">
          {isPaused ? '⏸ 已暂停' : running ? '⏳ 执行中…' : '🚀 触发执行'}
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
        <label className="text-xs text-gray-500 flex items-center gap-1">
          <input type="checkbox" checked={showLog} onChange={(e) => setShowLog(e.target.checked)} /> 日志
        </label>
      </div>

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

      {/* 进度统计 */}
      {progress.some((p) => p.verdict !== 'pending') && (
        <div className="flex gap-4 text-sm">
          <span className="text-pass">✓ {counts.passed} 通过</span>
          <span className="text-fail">✗ {counts.failed} 失败</span>
          <span className="text-skip">⊘ {counts.skipped} 跳过</span>
          <span className="text-gray-500">{counts.passed + counts.failed + counts.skipped}/{counts.total}</span>
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* 计划管理（K-011：从原场景管理页迁入） */}
        <PlanManager
          selectedPlan={selectedPlan}
          onSelect={handleSelectPlan}
          onPlansChange={handlePlansChange}
        />

        {/* 场景进度面板 */}
        <div className="w-[320px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border text-xs font-medium bg-surface-2">场景进度</div>
          <div className="flex-1 overflow-y-auto">
            {progress.map((p) => (
              <div key={p.id}
                className={`flex items-center gap-2 px-3 py-1.5 text-xs border-b border-border/30 ${p.verdict === 'running' ? 'bg-info/5' : ''}`}>
                <span className={`${vColor[p.verdict]} w-4 text-center`}>{vIcon[p.verdict]}</span>
                <span className="font-mono text-gray-400 w-24 truncate">{p.id}</span>
                <span className="text-gray-500 truncate flex-1">{p.title}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 日志流 */}
        {showLog && (
          <div ref={logRef}
            className="flex-1 min-w-0 border border-border rounded-lg p-4 overflow-y-auto font-mono text-xs leading-5" style={{ background: 'rgb(var(--code-bg))' }}>
            {events.length === 0 ? (
              <p className="text-gray-600">等待执行…</p>
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
                return <div key={i} className={cls}>{line}</div>;
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}
