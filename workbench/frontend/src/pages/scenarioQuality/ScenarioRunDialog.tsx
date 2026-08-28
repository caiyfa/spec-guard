// T-1035 v2：用例试跑对话框——链路范围/轻量选项/执行账号/预检参数输入 → trigger → 进度 → 报告。
// 全面复用 RunControl 既有件：runsApi.trigger/accounts/preflight（T-311/T-312 同款）
// + useRunStream 实时进度 + TrialRunDetailModal 完整报告（与正式执行同一落盘面）。
// 联网执行：真实调用目标环境（默认恒 sit，与 RunControl 一致）。

import { useEffect, useMemo, useState } from 'react';
import Modal from '../../components/Modal';
import { TrialRunDetailModal } from '../../components/TrialRunDetailModal';
import { useRunStream } from '../../hooks/useRunStream';
import { runsApi } from '../../api';
import type { PreflightResult, TrialRunResult } from '../../api';
import type { ScenarioQualityRow } from '../../api/scenarioQuality';

interface Props {
  scenarioId: string;
  scenarios: ScenarioQualityRow[];   // 全库（depends_on 反算上下游闭包）
  onClose: () => void;
}

export default function ScenarioRunDialog({ scenarioId, scenarios, onClose }: Props) {
  // ── 链路闭包（客户端确定性计算，与引擎 depends_on 图同源）──
  const { upstream, downstream } = useMemo(() => {
    const ups = new Map<string, string[]>();
    const downs = new Map<string, string[]>();
    for (const s of scenarios) {
      for (const d of s.depends_on) {
        ups.set(s.id, [...(ups.get(s.id) || []), d.id]);
        downs.set(d.id, [...(downs.get(d.id) || []), s.id]);
      }
    }
    const bfs = (start: string, map: Map<string, string[]>) => {
      const seen = new Set<string>();
      const stack = [start];
      while (stack.length) {
        const cur = stack.pop()!;
        for (const n of map.get(cur) || []) {
          if (n !== start && !seen.has(n)) { seen.add(n); stack.push(n); }
        }
      }
      return [...seen].sort();
    };
    return { upstream: bfs(scenarioId, ups), downstream: bfs(scenarioId, downs) };
  }, [scenarios, scenarioId]);

  const [withDownstream, setWithDownstream] = useState(false);
  const [prepOnly, setPrepOnly] = useState(false);
  const [skipUpstreamVerify, setSkipUpstreamVerify] = useState(false);
  const [strictDeps, setStrictDeps] = useState(false);
  const [account, setAccount] = useState('');
  const [accounts, setAccounts] = useState<Record<string, { ad: string; emp_no: string; type: string }>>({});
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [overrideInputs, setOverrideInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [triggerError, setTriggerError] = useState('');
  const [queued, setQueued] = useState('');
  const [runId, setRunId] = useState('');
  const [finished, setFinished] = useState(false);
  const [showReport, setShowReport] = useState(false);

  // 执行目标：含下游时展开为 "A or B"（上游闭包由引擎依赖调度默认连带）
  const targetIds = useMemo(
    () => (withDownstream ? [scenarioId, ...downstream] : [scenarioId]),
    [withDownstream, scenarioId, downstream]);
  // 预检范围：目标 + 上游闭包（缺失账号/env 键要连准备链一起扫）
  const preflightIds = useMemo(
    () => [...new Set([...targetIds, ...upstream])],
    [targetIds, upstream]);

  useEffect(() => {
    runsApi.accounts()
      .then(r => setAccounts(r.accounts || {}))
      .catch(() => setAccounts({}));
  }, []);

  useEffect(() => {
    let alive = true;
    setPreflightLoading(true);
    runsApi.preflight(preflightIds)
      .then(r => { if (alive) setPreflight(r); })
      .catch(() => { if (alive) setPreflight(null); })
      .finally(() => { if (alive) setPreflightLoading(false); });
    return () => { alive = false; };
  }, [preflightIds]);

  // ── 进度：全局 run 事件流过滤本 run ──
  const { events } = useRunStream();
  const runEvents = useMemo(() => events.filter(e => e.run_id === runId), [events, runId]);
  useEffect(() => {
    if (runId && runEvents.some(e => e.type === 'finished' || e.type === 'aborted')) {
      setFinished(true);
    }
  }, [runEvents, runId]);
  const progressLines = runEvents.filter(e => e.type === 'output' && e.line).slice(-8);

  const collectOverrides = () =>
    Object.entries(overrideInputs)
      .filter(([, v]) => v.trim() !== '')
      .map(([k, v]) => {
        const sep = k.indexOf('::');
        return { kind: k.slice(0, sep), name: k.slice(sep + 2), value: v.trim() };
      });

  const startRun = async () => {
    setBusy(true);
    setTriggerError('');
    try {
      const r = await runsApi.trigger('scenario', targetIds.join(' or '), 'sit', [], {
        prepOnly, skipUpstreamVerify, strictDeps,
        accountOverride: account || undefined,
      }, collectOverrides());
      if (r.queued) setQueued(`已有执行在进行，本次已排队（第 ${r.position ?? '?'} 位）`);
      if (r.run_id) setRunId(r.run_id);
    } catch (e: any) {
      setTriggerError(e.message || '触发失败');
    } finally {
      setBusy(false);
    }
  };

  const trialResult: TrialRunResult = { ok: true, run_id: runId, target: targetIds.join(' or ') };

  return (
    <Modal open onClose={onClose} width={620} title={`试跑 ${scenarioId}`}>
      {/* 链路范围 */}
      <div className="text-sm mb-3">
        <div className="text-xs text-gray-500 mb-1.5">链路范围</div>
        <label className="flex items-center gap-2 py-0.5 cursor-pointer">
          <input type="radio" checked={!withDownstream} onChange={() => setWithDownstream(false)} />
          <span>本用例 + 上游准备链
            <span className="text-xs text-gray-500 ml-1">
              {upstream.length ? `（连带 ${upstream.length} 个上游）` : '（无上游）'}
            </span>
          </span>
        </label>
        <label className="flex items-center gap-2 py-0.5 cursor-pointer">
          <input type="radio" checked={withDownstream} onChange={() => setWithDownstream(true)} />
          <span>上下链路一起跑
            <span className="text-xs text-gray-500 ml-1"
              title={downstream.join('、') || undefined}>
              （上游 {upstream.length} + 下游 {downstream.length}）
            </span>
          </span>
        </label>
        {upstream.length > 0 && (
          <div className="text-[11px] text-gray-600 mt-0.5">上游闭包：{upstream.join('、')}</div>
        )}
        {withDownstream && downstream.length > 0 && (
          <div className="text-[11px] text-gray-600 mt-0.5">下游消费方：{downstream.join('、')}</div>
        )}
      </div>

      {/* 轻量选项 + 账号 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm mb-3">
        <label className="flex items-center gap-1.5 cursor-pointer" title="只跑上游环境准备，不执行本用例">
          <input type="checkbox" checked={prepOnly} onChange={e => setPrepOnly(e.target.checked)} />仅准备
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer" title="上游照跑 flow 准备数据，但跳过其 verify 断言">
          <input type="checkbox" checked={skipUpstreamVerify} onChange={e => setSkipUpstreamVerify(e.target.checked)} />上游不断言
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer" title="上游契约版本漂移/孤儿依赖升格为 FAIL">
          <input type="checkbox" checked={strictDeps} onChange={e => setStrictDeps(e.target.checked)} />严格依赖
        </label>
        <span className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500">执行账号</span>
          <select value={account} onChange={e => setAccount(e.target.value)} className="input text-sm" title="覆盖默认账号别名">
            <option value="">默认（配置账号）</option>
            {Object.entries(accounts).map(([alias, cfg]) => (
              <option key={alias} value={alias}>{alias}（{cfg.ad || cfg.emp_no || alias}）</option>
            ))}
          </select>
        </span>
      </div>

      {/* 依赖预检 + 参数输入（T-311/T-312 同款） */}
      <div className="text-sm mb-3">
        <div className="text-xs text-gray-500 mb-1">依赖扫描（{preflightIds.length} 个场景）</div>
        {preflightLoading && <div className="text-xs text-gray-500">扫描中…</div>}
        {!preflightLoading && preflight && !preflight.has_gaps && (
          <div className="text-xs text-pass">✅ 依赖就绪</div>
        )}
        {!preflightLoading && preflight && preflight.has_gaps && (
          <div className="px-2 py-1.5 bg-fail/5 border border-fail/30 rounded space-y-1.5 max-h-36 overflow-y-auto">
            {preflight.missing_accounts.map(g => (
              <div key={g.account} className="text-[11px]">
                <div className="text-fail">
                  🔑 账号 <span className="font-mono">{g.account}</span> 未配置
                  <span className="text-gray-500">（{g.scenarios.join('、')} → 将 SKIP）</span>
                </div>
                <input
                  value={overrideInputs[`account::${g.account}`] || ''}
                  onChange={e => setOverrideInputs(prev => ({ ...prev, [`account::${g.account}`]: e.target.value }))}
                  placeholder="输入 AD 账号（或 ad:工号）替代配置"
                  className="mt-0.5 w-full bg-surface-3 border border-border rounded px-2 py-0.5 text-[11px] font-mono text-gray-200 focus:border-info outline-none" />
              </div>
            ))}
            {preflight.missing_env.map(g => (
              <div key={g.key} className="text-[11px]">
                <div className="text-warn">🌐 环境键 <span className="font-mono">{g.key}</span> 缺失</div>
                <input
                  value={overrideInputs[`env::${g.key}`] || ''}
                  onChange={e => setOverrideInputs(prev => ({ ...prev, [`env::${g.key}`]: e.target.value }))}
                  placeholder={`输入 ${g.key} 的值`}
                  className="mt-0.5 w-full bg-surface-3 border border-border rounded px-2 py-0.5 text-[11px] font-mono text-gray-200 focus:border-info outline-none" />
              </div>
            ))}
            {preflight.unresolved_upstream.map(g => (
              <div key={g.ref} className="text-[11px] text-warn">
                🔗 跨场景引用 <span className="font-mono">{g.ref}</span> 不在本次依赖闭包（{g.scenarios.join('、')}）
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 触发与进度 */}
      {triggerError && (
        <div className="mb-3 p-2.5 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
          ❌ 试跑触发失败：{triggerError}
        </div>
      )}
      {queued && <div className="mb-3 text-sm text-warn">⏳ {queued}</div>}
      {runId && (
        <div className="mb-3">
          <div className="text-sm mb-1">
            任务号 <span className="font-mono text-info">{runId}</span>
            <span className={`ml-2 text-xs ${finished ? 'text-pass' : 'text-warn'}`}>
              {finished ? '● 已完成' : '● 执行中…'}
            </span>
          </div>
          {progressLines.length > 0 && (
            <div className="bg-surface-1 border border-border rounded p-2 max-h-32 overflow-y-auto">
              {progressLines.map((l, i) => (
                <div key={i} className="text-[11px] font-mono text-gray-400 whitespace-pre-wrap">{l.line}</div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        {finished && runId && (
          <button className="btn-primary text-sm" onClick={() => setShowReport(true)}>
            查看完整报告
          </button>
        )}
        {!runId ? (
          <button className="btn-primary text-sm" onClick={startRun} disabled={busy}>
            {busy ? '触发中…' : '▶ 开始试跑（联网执行）'}
          </button>
        ) : (
          <button className="btn-ghost text-sm" onClick={onClose}>关闭</button>
        )}
      </div>

      {showReport && runId && (
        <TrialRunDetailModal trial={trialResult} onClose={() => setShowReport(false)} />
      )}
    </Modal>
  );
}
