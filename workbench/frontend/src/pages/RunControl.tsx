/** RunControl — 执行控制（K-050）：场景多选直跑 / 执行上下文确认 / 任务编号 / 日志专注模式
 *
 * K-046：计划依赖是过时的纯前端设计（后端 runs/trigger 本就支持 scope=scenario 直跑）。
 * K-050：测试计划区块整体移除——执行只需要「选场景 → 确认上下文 → 跑」；
 *        确认执行后进入日志专注模式（选择区收起，执行日志放大）。
 * ?ids=A,B,C 预选（DAG 框选「执行选中」的落点）。
 */
import { useRef, useEffect, useState, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { runsApi, scenariosApi, authApi, settingsApi, type Scenario, type RunStatus, type PreflightResult } from '../api';
import { useRunStream } from '../hooks/useRunStream';
import Modal from '../components/Modal';
import { StatusBadge } from '../components/ui/StatusBadge';

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
  const [showLog, setShowLog] = useState(true);
  // T-119：断点集合有写入路径（确认弹窗设置；此前恒空，断点功能只能手改计划 YAML）。
  // T-105：DAG 页「批量设断点」经 ?bps= 预置
  const [breakpoints, setBreakpoints] = useState<Set<string>>(() =>
    new Set((searchParams.get('bps') || '').split(',').map(s => s.trim()).filter(Boolean)));
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [myEmpNo, setMyEmpNo] = useState('');
  const logRef = useRef<HTMLDivElement>(null);

  // ── K-046：选择优先的状态模型 ──
  // ?ids= 预选（DAG 编排「执行选中」跳转的落点）
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() =>
    new Set((searchParams.get('ids') || '').split(',').map(s => s.trim()).filter(Boolean)));
  const [moduleFilter, setModuleFilter] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [prepOnly, setPrepOnly] = useState(false);
  const [skipUpstreamVerify, setSkipUpstreamVerify] = useState(false);
  // K-056：执行时账号选择（确认弹窗提供，不必改系统设置）
  const [accountOptions, setAccountOptions] = useState<Record<string, { ad: string; emp_no: string; type: string }>>({});
  const [accountOverride, setAccountOverride] = useState('');  // '' = 场景声明的 default
  // 高级模式（按范围执行：tag/单场景表达式/全量/引擎自测）
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [scope, setScope] = useState('all');
  const [target, setTarget] = useState('');
  // K-049：触发前执行上下文确认（不是点一下就直接跑）
  const [showConfirm, setShowConfirm] = useState(false);
  // T-311：执行前依赖预检——弹窗前先扫描闭包内账号/env 键/跨场景引用（EX-92a9252f 教训）
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  // T-312：预检缺失项的用户输入值（key=`${kind}::${name}` → 输入值；仅提交有值的项）
  const [overrideInputs, setOverrideInputs] = useState<Record<string, string>>({});
  // K-050：日志专注模式——确认执行后选择区收起，执行日志放大
  const [logFocus, setLogFocus] = useState(false);
  // K-052：任务号一键复制反馈
  const [copied, setCopied] = useState(false);

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
  // T-204：看门狗超时（确认弹窗可见；修改入口在设置页「执行」Tab）
  const [runTimeoutSec, setRunTimeoutSec] = useState(0);
  useEffect(() => {
    scenariosApi.list().then(setScenarios);
    scenariosApi.dag().then((d) => setDagEdges(d.edges || [])).catch(() => {});
    runsApi.accounts().then((r) => setAccountOptions(r.accounts || {})).catch(() => {});
    settingsApi.getRunTimeout().then((r) => setRunTimeoutSec(r.timeout_sec)).catch(() => {});
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

  const toggleId = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // T-119：断点切换——断点场景=执行顺序中「在该场景前暂停」
  const toggleBreakpoint = useCallback((id: string) => {
    setBreakpoints(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
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

  /** T-311：确认弹窗打开前先扫描依赖（闭包内账号/env 键/跨场景引用），扫描完再弹 */
  const openConfirm = async () => {
    setPreflight(null);
    setOverrideInputs({});  // T-312：新一次扫描清空上次输入
    if (selectedIds.size === 0) { setShowConfirm(true); return; }
    setPreflightLoading(true);
    try {
      const r = await runsApi.preflight([...selectedIds]);
      setPreflight(r.error ? null : r);
    } catch { setPreflight(null); }
    finally { setPreflightLoading(false); setShowConfirm(true); }
  };

  /** T-312：有输入的覆盖项 → [{kind, name, value}]（空值不提交） */
  const collectOverrides = () =>
    Object.entries(overrideInputs)
      .filter(([, v]) => v.trim() !== '')
      .map(([k, v]) => {
        const sep = k.indexOf('::');
        return { kind: k.slice(0, sep), name: k.slice(sep + 2), value: v.trim() };
      });

  /** K-049：触发分两步——先弹执行上下文确认，用户确认后才真正触发 */
  const doTrigger = async () => {
    setShowConfirm(false);
    setError('');
    clear();
    try {
      let result: { ok: boolean; queued?: boolean; position?: number } | undefined;
      const light = { prepOnly, skipUpstreamVerify, accountOverride };
      const overrides = collectOverrides();  // T-312：预检缺失项的输入值
      if (selectedIds.size > 0) {
        // K-046：勾选直跑（后端原生支持 "A or B" 的 pytest -k 表达式）
        const expr = [...selectedIds].join(' or ');
        result = breakpoints.size > 0
          ? await runsApi.trigger('scenario', expr, 'sit', [...breakpoints], light, overrides)
          : await runsApi.trigger('scenario', expr, 'sit', [], light, overrides);
      } else {
        // 高级模式：按范围执行
        result = breakpoints.size > 0
          ? await runsApi.trigger(scope, target, 'sit', [...breakpoints], light, overrides)
          : await runsApi.trigger(scope, target, 'sit', [], light, overrides);
      }
      if (result?.queued) {
        setError(`已有执行进行中，已加入队列（第 ${result.position} 位）`);
        const s = await runsApi.status();
        setRunStatus(s);
      } else if (result?.ok) {
        setLogFocus(true);  // K-050：确认执行后进入日志专注模式
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

  // T-1044 U3 P2：verdict 符号列改状态圆点（✓✗⊘◉ 文本符退役，与 FlowPanel 圆点同语言）
  const vDot: Record<string, string> = {
    running: 'bg-info animate-pulse', PASSED: 'bg-pass', FAILED: 'bg-fail', SKIPPED: 'bg-skip', ERROR: 'bg-fail',
  };
  const VerdictDot = ({ v }: { v: string }) => (
    <span title={v || '未运行'} className={`w-2 h-2 rounded-full inline-block flex-shrink-0 ${vDot[v] || 'bg-gray-700'}`} />
  );

  // K-050：当前任务编号（从 started 事件提取，日志头部展示）
  const currentRunId = useMemo(() => {
    const started = events.filter((e) => e.type === 'started');
    const last = started[started.length - 1] as { run_id?: string } | undefined;
    return last?.run_id || '';
  }, [events]);

  // K-052：任务号一键复制（排障报号零成本）
  const copyRunId = useCallback(async () => {
    if (!currentRunId) return;
    try {
      await navigator.clipboard.writeText(currentRunId);
    } catch {
      // 剪贴板 API 不可用（非安全上下文）时降级
      const ta = document.createElement('textarea');
      ta.value = currentRunId;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [currentRunId]);

  const triggerLabel = selectedIds.size > 0
    ? `🚀 执行选中（${selectedIds.size}）`
    : '🚀 触发执行';

  return (
    <div className="space-y-4 h-full flex flex-col">
      <h2 className="text-fs-title font-semibold">▶️ 执行控制</h2>

      {/* 触发面板（K-050：选择优先，无计划耦合，高级范围模式折叠） */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* K-046：轻量执行选项（conftest 原生支持，runner 透传） */}
        <label className="text-fs-body text-gray-500 flex items-center gap-1"
          title="只跑上游环境准备（prep 场景），跳过消费场景">
          <input type="checkbox" checked={prepOnly} onChange={(e) => setPrepOnly(e.target.checked)} /> 仅准备
        </label>
        <label className="text-fs-body text-gray-500 flex items-center gap-1"
          title="上游场景只跑 flow 不做 verify 断言（加快闭包执行）">
          <input type="checkbox" checked={skipUpstreamVerify} onChange={(e) => setSkipUpstreamVerify(e.target.checked)} /> 上游不断言
        </label>
        <button onClick={openConfirm} disabled={(running && !isPaused) || (selectedIds.size === 0 && !showAdvanced) || preflightLoading}
          className="px-4 py-1.5 rounded-md text-fs-lead font-medium bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30 disabled:opacity-40">
          {preflightLoading ? '🔍 扫描依赖中…' : isPaused ? '⏸ 已暂停' : running ? '⏳ 执行中…' : triggerLabel}
        </button>
        {isPaused && (
          <button onClick={resume}
            className="px-4 py-1.5 rounded-md text-fs-lead font-medium bg-info/20 text-info border border-info/30 hover:bg-info/30 animate-pulse">
            ▶ 放行继续
          </button>
        )}
        {running && !isPaused && (
          <button onClick={abort}
            className="px-4 py-1.5 rounded-md text-fs-lead font-medium bg-fail/20 text-fail border border-fail/30 hover:bg-fail/30">
            ⏹ 终止
          </button>
        )}
        <span className={`text-fs-body ${connected ? 'text-pass' : 'text-fail'}`}>
          {connected ? '● 已连接' : '○ 未连接'}
        </span>
        {/* K-046 补：执行上下文——环境 + 闭包预览（实际要跑什么，触发前可见） */}
        {selectedIds.size > 0 && (
          <details className="text-fs-body text-gray-500">
            <summary className="cursor-pointer hover:text-info">
              环境 sit · 闭包共 {closureInfo.total}（选中 {selectedIds.size}
              {closureInfo.upstream.length > 0 ? ` + 上游 ${closureInfo.upstream.length}` : ''}）
            </summary>
            {closureInfo.upstream.length > 0 && (
              <div className="mt-1 px-2 py-1.5 bg-surface-2 border border-border rounded max-w-md">
                <div className="text-fs-aux text-gray-600 mb-1">连带上游（先执行）：</div>
                <div className="flex flex-wrap gap-1">
                  {closureInfo.upstream.map((id) => (
                    <span key={id} className="px-1 py-0.5 rounded bg-info/10 text-info/90 font-mono text-fs-aux">{id}</span>
                  ))}
                </div>
              </div>
            )}
          </details>
        )}
        <label className="text-fs-body text-gray-500 flex items-center gap-1">
          <input type="checkbox" checked={showLog} onChange={(e) => setShowLog(e.target.checked)} /> 日志
        </label>
        <button onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-fs-body text-gray-500 hover:text-info ml-auto">
          {showAdvanced ? '▾ 收起高级' : '▸ 高级（按范围执行）'}
        </button>
      </div>

      {/* 高级模式：按范围执行（tag / 单场景表达式 / 全量 / 引擎自测） */}
      {showAdvanced && (
        <div className="flex items-center gap-3 flex-wrap border border-border rounded-lg px-3 py-2 bg-surface-2">
          <span className="text-fs-body text-gray-500">按范围执行：</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)}
            className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-fs-lead">
            {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          {(scope === 'tag' || scope === 'scenario' || scope === 'module') && (
            <input value={target} onChange={(e) => setTarget(e.target.value)}
              placeholder={scope === 'tag' ? 'P0 / permission / snapshot' : 'PP-RC-005'}
              className="bg-surface-3 border border-border rounded-md px-3 py-1.5 text-fs-lead w-48" />
          )}
          <span className="text-fs-aux text-gray-600">勾选列表非空时优先按勾选项直跑；清空勾选后此处生效</span>
        </div>
      )}

      {error && <p className="text-fs-lead text-fail">{error}</p>}

      {/* 多用户执行归属与队列（M8） */}
      {(currentOwner || queue.length > 0) && (
        <div className="border border-border rounded-lg px-3 py-2 bg-surface-2 space-y-1.5">
          {currentOwner && (
            <div className="text-fs-body text-gray-400">
              当前执行：<span className="text-info font-medium">{currentOwner}</span>
              {currentOwner === myEmpNo && <span className="text-gray-600">（我）</span>}
              {runStatus?.current_workspace && <span className="text-gray-600"> · 工作区 {runStatus.current_workspace}</span>}
            </div>
          )}
          {queue.length > 0 && (
            <div className="space-y-1">
              <div className="text-fs-body text-gray-500">排队中（{queue.length}）：</div>
              {queue.map((q, i) => (
                <div key={q.id} className="flex items-center gap-2 text-fs-body">
                  <span className="text-gray-600 font-mono">#{i + 1}</span>
                  <span className={q.emp_no === myEmpNo ? 'text-info' : 'text-gray-400'}>
                    {q.emp_no}{q.emp_no === myEmpNo && '（我）'}
                  </span>
                  <span className="text-gray-600">{q.scope}{q.target ? ` · ${q.target.slice(0, 40)}` : ''}</span>
                  <span className="text-gray-700 font-mono text-fs-aux">{q.created_at}</span>
                  {(q.emp_no === myEmpNo || runStatus?.current_emp_no === myEmpNo) && (
                    <button onClick={() => cancelQueued(q.id)}
                      className="text-fail/80 hover:text-fail text-fs-aux">取消</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 断点命中面板（T-1044 U3 P2：描边卡归档 border-info/35 bg-info/10；🔴✅ 退役改圆点/StatusBadge） */}
      {isPaused && breakpointHit && (
        <div className="border border-info/35 bg-info/10 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3">
            <span className="w-3 h-3 rounded-full bg-fail animate-pulse flex-shrink-0" title="断点命中" />
            <div>
              <div className="text-fs-lead font-medium text-info">
                断点命中：{breakpointHit.paused_at}
              </div>
              <div className="text-fs-body text-gray-400">
                批次 {breakpointHit.batch_index + 1}/{breakpointHit.total_batches} ·
                已完成 {breakpointHit.completed?.length || 0} 个场景
              </div>
            </div>
            <button onClick={resume}
              className="ml-auto px-4 py-1.5 rounded-md text-fs-body bg-info/15 text-info hover:bg-info/25">
              ▶ 放行继续
            </button>
          </div>

          {/* 上下文 */}
          {breakpointHit.context && (
            <div className="grid grid-cols-2 gap-3">
              {/* 已完成场景 */}
              <div className="bg-surface-2 rounded-lg p-3">
                <div className="mb-1.5"><StatusBadge size="sm" status="pass" label={`已完成 ${breakpointHit.context.completed_count}`} /></div>
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {(breakpointHit.context.completed || []).map((sid: string) => (
                    <div key={sid} className="text-fs-aux font-mono text-pass/70 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-pass flex-shrink-0" />{sid}
                    </div>
                  ))}
                </div>
              </div>
              {/* 最近 verdict */}
              <div className="bg-surface-2 rounded-lg p-3">
                <div className="text-fs-body text-gray-400 font-medium mb-1.5">📊 最近结果</div>
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {(breakpointHit.context.recent_verdicts || []).map((v: { scenario_id: string; verdict: string }, i: number) => (
                    <div key={i} className="text-fs-aux font-mono text-gray-400 flex items-center gap-1.5">
                      <VerdictDot v={v.verdict} />{v.scenario_id}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 输出尾部 */}
          {breakpointHit.context?.output_tail && (
            <details className="rounded-lg" style={{ background: 'rgb(var(--code-bg))' }}>
              <summary className="px-3 py-1.5 text-fs-aux text-gray-500 cursor-pointer">📄 最近输出（{breakpointHit.context.output_tail.length} 行）</summary>
              <pre className="px-3 py-2 text-fs-aux text-gray-400 font-mono max-h-32 overflow-y-auto">
                {breakpointHit.context.output_tail.join('\n')}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* 进度统计（本次选中场景） */}
      {[...verdictMap.keys()].some((id) => selectedIds.has(id)) && (
        <div className="flex gap-4 text-fs-lead">
          <StatusBadge size="sm" status="pass" label={`${counts.passed} 通过`} />
          <StatusBadge size="sm" status="fail" label={`${counts.failed} 失败`} />
          <StatusBadge size="sm" status="skip" label={`${counts.skipped} 跳过`} />
          <span className="text-gray-500">{counts.passed + counts.failed + counts.skipped}/{selectedIds.size}</span>
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* K-050：日志专注模式——选择区收起为窄条，点击返回 */}
        {logFocus && (
          <button
            onClick={() => setLogFocus(false)}
            className="w-10 flex-shrink-0 border border-border rounded-lg bg-surface-2 hover:bg-surface-3 flex flex-col items-center justify-center gap-2 text-gray-500 hover:text-info"
            title="返回场景选择"
          >
            <span className="text-fs-lead">«</span>
            <span className="text-fs-aux [writing-mode:vertical-rl]">{selectedIds.size} 已选</span>
          </button>
        )}

        {/* K-046：场景多选列表（选择 + 进度一体）；K-050：专注模式下隐藏 */}
        {!logFocus && (
        <div className="w-[380px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border bg-surface-2 space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-fs-body font-medium">场景选择（{selectedIds.size} 已选）</span>
              <button onClick={() => setSelectedIds(new Set(filteredScenarios.map(s => s.id)))}
                className="text-fs-aux text-info hover:underline ml-auto">全选当前</button>
              <button onClick={() => setSelectedIds(new Set())}
                className="text-fs-aux text-gray-500 hover:text-fail">清空</button>
            </div>
            <div className="flex gap-1.5">
              <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
                placeholder="🔍 ID / 标题"
                className="flex-1 min-w-0 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body" />
              <select value={moduleFilter} onChange={(e) => setModuleFilter(e.target.value)}
                className="bg-surface-3 border border-border rounded px-1.5 py-1 text-fs-body max-w-[120px]">
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
                  className={`flex items-center gap-2 px-3 py-1.5 text-fs-body border-b border-border/30 cursor-pointer hover:bg-surface-3/50 ${checked ? 'bg-info/5' : ''}`}>
                  <input type="checkbox" checked={checked} onChange={() => toggleId(s.id)} />
                  <span className="w-4 flex justify-center flex-shrink-0"><VerdictDot v={v} /></span>
                  <span className="font-mono text-gray-400 w-28 truncate inline-flex items-center gap-1">
                    {breakpoints.has(s.id) && <span className="w-1.5 h-1.5 rounded-full bg-fail flex-shrink-0" title="断点" />}
                    {s.id}
                  </span>
                  <span className="text-gray-500 truncate flex-1">{s.title}</span>
                  {/* T-320：场景最后更新时间（YAML mtime） */}
                  {s.updated_at && (
                    <span className="text-gray-600 text-fs-aux shrink-0" title={`最后更新 ${s.updated_at}`}>
                      {s.updated_at.slice(5)}
                    </span>
                  )}
                </label>
              );
            })}
            {filteredScenarios.length === 0 && (
              <div className="text-center text-gray-600 text-fs-body py-8">无匹配场景</div>
            )}
          </div>
        </div>
        )}

        {/* 日志流（K-050：头部含任务编号 + 专注切换；专注模式下占满宽度） */}
        {showLog && (
          <div className="flex-1 min-w-0 border border-border rounded-lg overflow-hidden flex flex-col">
            <div className="px-3 py-1.5 border-b border-border bg-surface-2 flex items-center gap-2 text-fs-body">
              <span className="text-gray-500 font-medium">执行日志</span>
              {currentRunId && (
                <span className="flex items-center gap-1">
                  <span className="font-mono text-info" title="任务编号：报告目录与日志文件同名，排错时报此编号">
                    {currentRunId}
                  </span>
                  <button onClick={copyRunId}
                    className="text-gray-500 hover:text-info"
                    title="复制任务编号">
                    {copied ? <span className="text-pass">✓</span> : '📋'}
                  </button>
                </span>
              )}
              <button onClick={() => setLogFocus(!logFocus)}
                className="ml-auto text-gray-500 hover:text-info"
                title={logFocus ? '退出专注，返回场景选择' : '专注日志（收起选择区）'}>
                {logFocus ? '⤡ 退出专注' : '⤢ 专注日志'}
              </button>
            </div>
            <div ref={logRef}
              className="flex-1 overflow-y-auto p-4 font-mono text-fs-body leading-5" style={{ background: 'rgb(var(--code-bg))' }}>
            {events.length === 0 ? (
              <p className="text-gray-600">勾选场景后点击「执行选中」；或在高级模式按范围执行…</p>
            ) : (
              events.map((e, i) => {
                if (e.type === 'started') return <div key={i} className="text-info mt-2">▶ {e.cmd}</div>;
                if (e.type === 'finished') return e.aborted
                  ? <div key={i} className="text-skip mt-2">■ 已终止（断点暂停中取消）</div>
                  : <div key={i} className="text-pass mt-2">■ 完成 (exit={e.returncode})</div>;
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
          </div>
        )}
      </div>

      {/* K-049：执行上下文确认弹窗——触发前看清「用什么上下文、实际跑什么」 */}
      <Modal open={showConfirm} onClose={() => setShowConfirm(false)} title="确认执行上下文" width={440}>
        <div className="space-y-3 text-fs-lead">
          <div className="grid grid-cols-[88px_1fr] gap-y-2 gap-x-3">
            <span className="text-gray-500">执行方式</span>
            <span className="text-gray-200">
              {selectedIds.size > 0
                ? '☑️ 勾选直跑（pytest -k 表达式）'
                : `🎯 范围执行：${SCOPES.find(s => s.value === scope)?.label || scope}${target ? ` · ${target}` : ''}`}
            </span>
            <span className="text-gray-500">环境</span>
            <span className="text-gray-200 font-mono">sit</span>
            {/* K-056：执行时账号选择（不再只能改系统设置） */}
            <span className="text-gray-500">执行账号</span>
            <span>
              <select value={accountOverride} onChange={(e) => setAccountOverride(e.target.value)}
                className="bg-surface-3 border border-border rounded px-2 py-1 text-fs-lead text-gray-200">
                <option value="">场景声明（default）</option>
                {Object.entries(accountOptions).map(([alias, info]) => (
                  <option key={alias} value={alias}>
                    {alias}{info.type === 'internal' ? '（internal token）' : info.emp_no ? `（${info.emp_no}）` : ''}
                  </option>
                ))}
              </select>
              {accountOverride && accountOptions[accountOverride] && (
                <span className="ml-2 text-fs-aux text-info">
                  场景 as: default 将以 {accountOptions[accountOverride].ad || accountOverride} 执行
                </span>
              )}
            </span>
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
            {/* T-311：执行前依赖预检——弹窗前扫描闭包内账号/env 键/跨场景引用（EX-92a9252f 教训） */}
            {selectedIds.size > 0 && (
              <>
                <span className="text-gray-500">依赖扫描</span>
                <span className="text-fs-body">
                  {preflightLoading ? <span className="text-gray-500">扫描中…</span> : !preflight ? (
                    <span className="text-gray-500">未扫描</span>
                  ) : preflight.has_gaps ? (
                    <span className="text-warn">⚠️ 有缺失（账号 {preflight.missing_accounts.length} · 环境键 {preflight.missing_env.length} · 跨场景引用 {preflight.unresolved_upstream.length} · 未知插值 {(preflight.unresolved_templates_gaps || []).length} · fixtures {(preflight.missing_files || []).length}）</span>
                  ) : (
                    <span className="text-pass">✅ 依赖就绪（账号 {preflight.accounts.length} · 环境键 {preflight.env_keys.length} · 上游引用 {preflight.upstream_refs.length}）</span>
                  )}
                </span>
              </>
            )}
            {preflight && preflight.has_gaps && (
              <div className="col-span-2 px-2 py-1.5 bg-fail/5 border border-fail/30 rounded space-y-1.5 max-h-36 overflow-y-auto">
                {preflight.missing_accounts.map((g) => (
                  <div key={g.account} className="text-fs-body">
                    <div className="text-fail">
                      🔑 账号 <span className="font-mono">{g.account}</span> 未在环境配置 accounts 定义
                      <span className="text-gray-500">（{g.scenarios.join('、')} → 将 SKIP）</span>
                    </div>
                    {/* T-312：直接输入 AD 账号替代改配置文件 */}
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <input
                        value={overrideInputs[`account::${g.account}`] || ''}
                        onChange={(e) => setOverrideInputs(prev => ({ ...prev, [`account::${g.account}`]: e.target.value }))}
                        placeholder={`输入 AD 账号（或 ad:工号）替代配置`}
                        className="flex-1 bg-surface-3 border border-border rounded px-2 py-0.5 text-fs-body font-mono text-gray-200 focus:border-info outline-none" />
                      {!!overrideInputs[`account::${g.account}`]?.trim() && (
                        <span className="text-pass shrink-0">✓ 覆盖执行</span>
                      )}
                    </div>
                  </div>
                ))}
                {preflight.missing_env.map((g) => (
                  <div key={g.key} className="text-fs-body">
                    <div className="text-warn">
                      🌐 环境键 <span className="font-mono">{g.key}</span> 缺失
                      <span className="text-gray-500">（{g.scenarios.join('、')}）</span>
                    </div>
                    {/* T-312：直接输入值替代改配置文件 */}
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <input
                        value={overrideInputs[`env::${g.key}`] || ''}
                        onChange={(e) => setOverrideInputs(prev => ({ ...prev, [`env::${g.key}`]: e.target.value }))}
                        placeholder={`输入 ${g.key} 的值`}
                        className="flex-1 bg-surface-3 border border-border rounded px-2 py-0.5 text-fs-body font-mono text-gray-200 focus:border-info outline-none" />
                      {!!overrideInputs[`env::${g.key}`]?.trim() && (
                        <span className="text-pass shrink-0">✓ 覆盖执行</span>
                      )}
                    </div>
                  </div>
                ))}
                {preflight.unresolved_upstream.map((g) => (
                  <div key={g.ref} className="text-fs-body text-warn">
                    🔗 跨场景引用 <span className="font-mono">{g.ref}</span> 不在本次依赖闭包
                    <span className="text-gray-500">（{g.scenarios.join('、')} → 运行期变量未定义）</span>
                  </div>
                ))}
                {(preflight.unresolved_templates_gaps || []).map((g) => (
                  <div key={g.tpl} className="text-fs-body text-warn">
                    ❓ 插值 <span className="font-mono">{`{{${g.tpl}}}`}</span> 无法解析（非 fn/env/上游/本场景变量）
                    <span className="text-gray-500">（{g.scenarios.join('、')} → 运行期变量未定义）</span>
                  </div>
                ))}
                {/* T-502：fixtures 文件引用——缺失 = 仓库缺陷（预检阻断，无覆盖输入框） */}
                {(preflight.missing_files || []).map((g) => (
                  <div key={g.file} className="text-fs-body">
                    <div className="text-fail">
                      📎 fixtures 文件 <span className="font-mono">{g.file}</span> 不存在
                      <span className="text-gray-500">（{g.scenarios.join('、')} → 仓库缺陷，预检阻断）</span>
                    </div>
                  </div>
                ))}
                {(preflight.unknown_file_refs_gaps || []).map((g) => (
                  <div key={g.file} className="text-fs-body text-warn">
                    ❓ 文件引用 <span className="font-mono">{g.file}</span> 含插值，静态不可判
                    <span className="text-gray-500">（{g.scenarios.join('、')} → 运行期按实际值判定）</span>
                  </div>
                ))}
                <p className="text-fs-aux text-gray-500 pt-0.5">
                  账号/环境键缺失执行时按诚实语义 SKIP 不报 FAIL，可直接在上方输入值覆盖执行（仅本次运行生效，不改配置文件）；📎 fixtures 缺失为仓库缺陷（文件应随 git 提交），不提供输入覆盖——请补齐文件后重试。
                </p>
              </div>
            )}
            {/* T-204：看门狗超时（修改入口在设置页「执行」Tab） */}
            <span className="text-gray-500">看门狗</span>
            <span className="text-gray-200">
              {runTimeoutSec > 0
                ? <span className="font-mono">{Math.floor(runTimeoutSec / 60)} 分 {runTimeoutSec % 60} 秒（超时自动终止）</span>
                : '未启用（0 = 不设超时）'}
            </span>
            {/* T-119：断点设置——按选中顺序列出，勾选=在该场景前暂停（后端已支持分批执行） */}
            {selectedIds.size > 0 && (
              <span className="text-gray-500">断点</span>
            )}
            {selectedIds.size > 0 && (
              <div className="space-y-1">
                {[...selectedIds].map((sid, idx) => (
                  <label key={sid} className="flex items-center gap-2 text-fs-body cursor-pointer hover:opacity-80">
                    <input type="checkbox" checked={breakpoints.has(sid)}
                      onChange={() => toggleBreakpoint(sid)} />
                    <span className="text-gray-600 font-mono text-fs-aux">#{idx + 1}</span>
                    <span className="font-mono">{sid}</span>
                    {breakpoints.has(sid) && <span className="text-info text-fs-aux">🔴 在此前暂停</span>}
                  </label>
                ))}
                {breakpoints.size > 0 && (
                  <button onClick={() => setBreakpoints(new Set())}
                    className="text-fs-aux text-gray-500 hover:text-fail">清除全部断点</button>
                )}
              </div>
            )}
            {(prepOnly || skipUpstreamVerify) && (              <>
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
              <div className="text-fs-aux text-gray-600 mb-1">连带上游（先于选中场景执行）：</div>
              <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
                {closureInfo.upstream.map((id) => (
                  <span key={id} className="px-1 py-0.5 rounded bg-info/10 text-info/90 font-mono text-fs-aux">{id}</span>
                ))}
              </div>
            </div>
          )}
          <p className="text-fs-body text-gray-500 leading-relaxed">
            引擎按依赖闭包执行；执行日志包含每次接口调用的 method/path/status 与响应体
            <span className="text-info"> ifelc-trace_id</span>（网关全链追踪 ID，排查 BUG 直接可用）。
            执行真实调用目标环境，会产生真实测试数据。
          </p>
          <div className="flex gap-2 pt-1">
            <button onClick={doTrigger}
              className="flex-1 py-2 rounded-md text-fs-lead font-medium bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30">
              🚀 确认执行
            </button>
            <button onClick={() => setShowConfirm(false)}
              className="px-4 py-2 rounded-md text-fs-lead bg-surface-3 text-gray-400 hover:bg-surface-2">
              取消
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
