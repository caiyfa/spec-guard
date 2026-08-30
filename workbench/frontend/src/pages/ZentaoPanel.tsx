// 禅道集成面板（S5）：冻结 delta 一键建故事 / 提 BUG 双入口 / 对话草案确认 / 锚点与作业

import { useEffect, useState } from 'react';
import {
  zentaoApi,
  type ZentaoJob,
  type StoryDraft,
  type ExternalRef,
  type EstimateRecord,
} from '../api';

const SEVERITIES = [
  { v: 1, label: '致命' },
  { v: 2, label: '严重' },
  { v: 3, label: '一般' },
  { v: 4, label: '轻微' },
];

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-warn',
  running: 'text-blue-400',
  succeeded: 'text-pass',
  failed: 'text-fail',
  rolled_back: 'text-gray-400',
  draft: 'text-warn',
  created: 'text-pass',
  cancelled: 'text-gray-400',
  suggested: 'text-warn',
  confirmed: 'text-blue-400',
  written_back: 'text-pass',
  rejected: 'text-gray-400',
};

export default function ZentaoPanel() {
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // 区① 冻结 delta 交付
  const [deltas, setDeltas] = useState<{ delta_id: string; frozen: boolean }[]>([]);
  const [selDelta, setSelDelta] = useState('');
  const [storyTitle, setStoryTitle] = useState('');
  const [estimates, setEstimates] = useState<EstimateRecord[]>([]);

  // 区② 提 BUG
  const [runId, setRunId] = useState('');
  const [scenarioId, setScenarioId] = useState('');
  const [spqId, setSpqId] = useState('');
  const [fromRunSev, setFromRunSev] = useState(2);
  const [bugTitle, setBugTitle] = useState('');
  const [bugSteps, setBugSteps] = useState('');
  const [bugSev, setBugSev] = useState(3);

  // 区③ 对话草案
  const [drafts, setDrafts] = useState<StoryDraft[]>([]);

  // 区④ 锚点与作业
  const [refs, setRefs] = useState<ExternalRef[]>([]);
  const [jobs, setJobs] = useState<ZentaoJob[]>([]);
  const [pollBugId, setPollBugId] = useState('');

  const flash = (fn: () => void) => { setError(''); setNotice(''); fn(); };

  const loadDeltas = async () => {
    try { setDeltas((await zentaoApi.frozenDeltas()).deltas); } catch (e: any) { setError(e.message); }
  };
  const loadEstimates = async () => {
    try { setEstimates((await zentaoApi.listEstimates('', '')).estimates); } catch (e: any) { setError(e.message); }
  };
  const loadDrafts = async () => {
    try { setDrafts((await zentaoApi.listStoryDrafts()).drafts); } catch (e: any) { setError(e.message); }
  };
  const loadRefs = async () => {
    try { setRefs((await zentaoApi.listRefs()).refs); } catch (e: any) { setError(e.message); }
  };
  const loadJobs = async () => {
    try { setJobs((await zentaoApi.listJobs()).jobs); } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { flash(() => { loadDeltas(); loadEstimates(); loadDrafts(); loadRefs(); loadJobs(); }); }, []);

  // ── 区① 建故事 / 评估 / 回写 ──
  const handleCreateStory = async () => {
    if (!selDelta) { setError('请选择冻结 delta'); return; }
    try {
      const { job } = await zentaoApi.createStory(selDelta, storyTitle);
      setNotice(`建故事作业 ${job.job_id} → ${job.status}${job.zt_ref ? `，禅道编号 ${job.zt_ref}` : ''}`);
      loadDeltas(); loadRefs(); loadJobs();
    } catch (e: any) { setError(e.message); }
  };

  const handleEstimate = async () => {
    if (!selDelta) { setError('请选择冻结 delta'); return; }
    try {
      const { estimate } = await zentaoApi.estimatePoints(selDelta, selDelta);
      setNotice(`评估完成：${estimate.points} 点，置信度 ${estimate.confidence}（suggested，待产品确认）`);
      loadEstimates();
    } catch (e: any) { setError(e.message); }
  };

  const handleConfirmEstimate = async (id: number, verdict: 'confirm' | 'reject') => {
    try {
      await zentaoApi.confirmEstimate(id, verdict);
      setNotice(`评估 ${verdict === 'confirm' ? '已确认' : '已驳回'}`);
      loadEstimates();
    } catch (e: any) { setError(e.message); }
  };

  const handleWriteback = async (est: EstimateRecord) => {
    const story = est.zt_story || '';
    if (!story) { setError('该评估未关联禅道故事，请先创建故事'); return; }
    try {
      const { job } = await zentaoApi.writebackPoints(story, est.id);
      setNotice(`回写作业 ${job.job_id} → ${job.status}`);
      loadEstimates(); loadJobs();
    } catch (e: any) { setError(e.message); }
  };

  // ── 区② 提 BUG ──
  const handleBugFromRun = async () => {
    if (!runId || !scenarioId) { setError('run_id 与场景 ID 必填'); return; }
    try {
      const { job } = await zentaoApi.createBugFromRun(runId, scenarioId, fromRunSev, '', spqId);
      setNotice(`提单作业 ${job.job_id} → ${job.status}${job.zt_ref ? `，BUG 编号 ${job.zt_ref}` : ''}`);
      loadJobs(); loadRefs();
    } catch (e: any) { setError(e.message); }
  };

  const handleBugManual = async () => {
    if (!bugTitle || !bugSteps) { setError('标题与复现步骤必填'); return; }
    try {
      const { job } = await zentaoApi.createBugManual(bugTitle, bugSteps, bugSev);
      setNotice(`提单作业 ${job.job_id} → ${job.status}${job.zt_ref ? `，BUG 编号 ${job.zt_ref}` : ''}`);
      setBugTitle(''); setBugSteps('');
      loadJobs(); loadRefs();
    } catch (e: any) { setError(e.message); }
  };

  const handlePollBug = async () => {
    if (!pollBugId) { setError('请输入 BUG 编号'); return; }
    try {
      const r = await zentaoApi.pollBug(pollBugId);
      setNotice(`BUG ${r.bug_id} 状态：${r.status}${r.regression_suggested ? '（建议回归验证）' : ''}`);
    } catch (e: any) { setError(e.message); }
  };

  // ── 区③ 草案 ──
  const handleCreateFromDraft = async (draft: StoryDraft) => {
    try {
      const { job } = await zentaoApi.createStoryFromDraft(draft.id);
      setNotice(`草案「${draft.title}」建故事作业 ${job.job_id} → ${job.status}${job.zt_ref ? `，禅道编号 ${job.zt_ref}` : ''}`);
      loadDrafts(); loadRefs(); loadJobs();
    } catch (e: any) { setError(e.message); }
  };

  const handleCancelDraft = async (draft: StoryDraft) => {
    try {
      await zentaoApi.cancelStoryDraft(draft.id);
      setNotice(`草案「${draft.title}」已取消`);
      loadDrafts();
    } catch (e: any) { setError(e.message); }
  };

  // ── 区④ 对账 ──
  const handleReconcile = async () => {
    try {
      const { fixed } = await zentaoApi.reconcile();
      setNotice(`对账完成，补登记 ${fixed.length} 条锚点`);
      loadRefs();
    } catch (e: any) { setError(e.message); }
  };

  const card = 'bg-surface-2 border border-border rounded-lg p-4 mb-4';
  const label = 'block text-fs-body text-gray-400 mb-1';
  const input = 'w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-200 outline-none focus:border-info';
  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const btnDanger = 'px-3 py-1.5 rounded text-fs-body font-medium bg-fail/12 text-fail hover:bg-fail/20 disabled:opacity-40';
  const th = 'text-left text-fs-body text-gray-500 font-normal px-2 py-1 border-b border-border';
  const td = 'px-2 py-1.5 text-fs-body text-gray-300 border-b border-border/50 align-top';

  return (
    <div className="p-4 max-w-[1200px] mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-fs-title font-bold">🔗 禅道集成</h1>
        <div className="text-fs-body text-gray-500">
          写动作需 product/tester 角色 · 创建故事仅 product · Agent 产出草案需人确认
        </div>
      </div>
      {error && <div className="mb-3 px-3 py-2 rounded bg-fail/12 text-fail text-fs-body">{error}</div>}
      {notice && <div className="mb-3 px-3 py-2 rounded bg-pass/12 text-pass text-fs-body">{notice}</div>}

      {/* ── 区① 冻结 delta 交付 ── */}
      <div className={card}>
        <h2 className="text-fs-lead font-semibold mb-3">① 冻结 spec 交付（一键创建禅道故事）</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64">
            <span className={label}>冻结 delta（FREEZE.yaml 在库）</span>
            <select className={input} value={selDelta} onChange={e => setSelDelta(e.target.value)}>
              <option value="">— 选择 —</option>
              {deltas.map(d => <option key={d.delta_id} value={d.delta_id}>{d.delta_id}</option>)}
            </select>
          </div>
          <div className="w-64">
            <span className={label}>故事标题（可留空用 delta 名）</span>
            <input className={input} value={storyTitle} onChange={e => setStoryTitle(e.target.value)}
                   placeholder="如：绩效域落位规则调整" />
          </div>
          <button className={btn} onClick={handleCreateStory} disabled={!selDelta}>创建禅道故事</button>
          <button className={btn} onClick={handleEstimate} disabled={!selDelta}>故事点评估</button>
        </div>
        <div className="mt-3">
          <span className={label}>故事点评估记录（恒 suggested，产品确认后才可回写）</span>
          {estimates.length === 0 ? (
            <div className="text-fs-body text-gray-500">暂无评估记录</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr>
                  <th className={th}>delta</th><th className={th}>故事点</th><th className={th}>置信度</th>
                  <th className={th}>状态</th><th className={th}>禅道故事</th><th className={th}>操作</th>
                </tr>
              </thead>
              <tbody>
                {estimates.map(est => (
                  <tr key={est.id}>
                    <td className={td}>{est.delta_id}</td>
                    <td className={td}>{est.points}</td>
                    <td className={td}>{est.confidence}</td>
                    <td className={`${td} ${STATUS_COLOR[est.status] || ''}`}>{est.status}</td>
                    <td className={td}>{est.zt_story || '—'}</td>
                    <td className={td}>
                      <div className="flex gap-1.5">
                        {est.status === 'suggested' && (
                          <>
                            <button className={btn} onClick={() => handleConfirmEstimate(est.id, 'confirm')}>确认</button>
                            <button className={btnDanger} onClick={() => handleConfirmEstimate(est.id, 'reject')}>驳回</button>
                          </>
                        )}
                        {est.status === 'confirmed' && (
                          <button className={btn} onClick={() => handleWriteback(est)}>回写禅道</button>
                        )}
                        {est.status === 'written_back' && <span className="text-fs-body text-gray-500">已回写</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── 区② 提 BUG 双入口 ── */}
      <div className={card}>
        <h2 className="text-fs-lead font-semibold mb-3">② 提 BUG（双入口，SKIP/BLOCKED 被拒）</h2>
        <div className="grid grid-cols-2 gap-4">
          <div className="border border-border/60 rounded p-3">
            <span className={label}>入口①：执行失败（from-run，verdict=FAIL）</span>
            <input className={`${input} mb-2`} placeholder="run_id（如 EX-9e31916f）" value={runId} onChange={e => setRunId(e.target.value)} />
            <input className={`${input} mb-2`} placeholder="场景 ID（如 IS-RVT-002）" value={scenarioId} onChange={e => setScenarioId(e.target.value)} />
            <input className={`${input} mb-2`} placeholder="SPQ 编号（可选，如 SPQ-005）" value={spqId} onChange={e => setSpqId(e.target.value)} />
            <div className="flex items-center gap-2 mb-2">
              <span className="text-fs-body text-gray-400">严重度</span>
              <select className={`${input} w-24`} value={fromRunSev} onChange={e => setFromRunSev(Number(e.target.value))}>
                {SEVERITIES.map(s => <option key={s.v} value={s.v}>{s.label}</option>)}
              </select>
            </div>
            <button className={btn} onClick={handleBugFromRun} disabled={!runId || !scenarioId}>一键提禅道 BUG</button>
          </div>
          <div className="border border-border/60 rounded p-3">
            <span className={label}>入口②：手工录入（同一通道）</span>
            <input className={`${input} mb-2`} placeholder="BUG 标题" value={bugTitle} onChange={e => setBugTitle(e.target.value)} />
            <textarea className={`${input} mb-2 min-h-[80px]`} placeholder="复现步骤（多行）" value={bugSteps} onChange={e => setBugSteps(e.target.value)} />
            <div className="flex items-center gap-2 mb-2">
              <span className="text-fs-body text-gray-400">严重度</span>
              <select className={`${input} w-24`} value={bugSev} onChange={e => setBugSev(Number(e.target.value))}>
                {SEVERITIES.map(s => <option key={s.v} value={s.v}>{s.label}</option>)}
              </select>
            </div>
            <button className={btn} onClick={handleBugManual} disabled={!bugTitle || !bugSteps}>提交 BUG</button>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span className="text-fs-body text-gray-400">禅道状态回查</span>
          <input className={`${input} w-48`} placeholder="BUG 编号（如 ZT-BUG-9917）" value={pollBugId} onChange={e => setPollBugId(e.target.value)} />
          <button className={btn} onClick={handlePollBug} disabled={!pollBugId}>回查</button>
        </div>
      </div>

      {/* ── 区③ 对话草案 ── */}
      <div className={card}>
        <h2 className="text-fs-lead font-semibold mb-3">③ 对话分析草案（飞书文档/多维表格 → Agent 分析 → 人确认建故事）</h2>
        {drafts.length === 0 ? (
          <div className="text-fs-body text-gray-500">暂无草案。在「对话」中粘贴飞书文档/多维表格链接，Agent 拉取分析后将自动产出草案。</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr>
                <th className={th}>#</th><th className={th}>标题</th><th className={th}>素材来源</th>
                <th className={th}>状态</th><th className={th}>禅道编号</th><th className={th}>操作</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map(d => (
                <tr key={d.id}>
                  <td className={td}>{d.id}</td>
                  <td className={td}>
                    <div className="font-medium">{d.title}</div>
                    <div className="text-fs-body text-gray-500 line-clamp-2 max-w-[420px]">{d.spec}</div>
                  </td>
                  <td className={td}>
                    {(d.source_refs || []).map((s, i) => (
                      <div key={i} className="text-fs-body">
                        {s.type === 'feishu_doc' ? '📄' : s.type === 'feishu_base' ? '📊' : '✍️'} {s.note || s.ref || s.url || s.type}
                      </div>
                    ))}
                  </td>
                  <td className={`${td} ${STATUS_COLOR[d.status] || ''}`}>{d.status}</td>
                  <td className={td}>{d.zt_story || '—'}</td>
                  <td className={td}>
                    <div className="flex gap-1.5">
                      {d.status === 'draft' && (
                        <>
                          <button className={btn} onClick={() => handleCreateFromDraft(d)}>创建禅道故事</button>
                          <button className={btnDanger} onClick={() => handleCancelDraft(d)}>取消</button>
                        </>
                      )}
                      {d.status === 'created' && <span className="text-fs-body text-gray-500">已创建</span>}
                      {d.status === 'cancelled' && <span className="text-fs-body text-gray-500">已取消</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── 区④ 锚点与作业 ── */}
      <div className={card}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-fs-lead font-semibold">④ 外部锚点与作业</h2>
          <button className={btn} onClick={handleReconcile}>对账补登记</button>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <span className={label}>外部锚点（sf_external_refs，M10 血缘链数据源）</span>
            {refs.length === 0 ? (
              <div className="text-fs-body text-gray-500">暂无锚点登记</div>
            ) : (
              <div className="max-h-64 overflow-y-auto border border-border/60 rounded">
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className={th}>外部资产</th><th className={th}>关联</th><th className={th}>登记人</th>
                    </tr>
                  </thead>
                  <tbody>
                    {refs.slice(0, 30).map(r => (
                      <tr key={r.id}>
                        <td className={td}>
                          <span className="text-info">{r.ref}</span>
                          <span className="text-gray-500"> ({r.type})</span>
                        </td>
                        <td className={td}>{r.linked_type}: {r.linked}</td>
                        <td className={td}>{r.registered_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div>
            <span className={label}>最近作业（幂等/重试/审计）</span>
            {jobs.length === 0 ? (
              <div className="text-fs-body text-gray-500">暂无作业</div>
            ) : (
              <div className="max-h-64 overflow-y-auto border border-border/60 rounded">
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className={th}>作业</th><th className={th}>类型</th><th className={th}>状态</th><th className={th}>禅道编号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.slice(0, 20).map(j => (
                      <tr key={j.job_id}>
                        <td className={td}>{j.job_id}</td>
                        <td className={td}>{j.kind}</td>
                        <td className={`${td} ${STATUS_COLOR[j.status] || ''}`}>{j.status}</td>
                        <td className={td}>{j.zt_ref || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
