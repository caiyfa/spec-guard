// 评分与冻结面板（T-059，S4 前端缺口补丁）：五维评分 QA 确认 + 冻结三闸状态与操作

import { useEffect, useState } from 'react';
import {
  specflowApi,
  zentaoApi,
  type InterviewItem,
  type ScoreItem,
  type GateState,
} from '../api';

const DIM_LABEL: Record<string, string> = {
  logic: '逻辑完整性',
  coverage: '覆盖率',
  boundary: '边界异常',
  precondition: '前置条件',
  clarity: '预期清晰度',
};

const GATE_LABEL: Record<string, string> = {
  product_confirm: '① 产品确认',
  conformance: '② specstd 合规',
  p0_zero: '③ P0 清零',
};

export default function ScoreFreezePanel() {
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // ── 评分区 ──
  const [interviews, setInterviews] = useState<InterviewItem[]>([]);
  const [selIv, setSelIv] = useState('');
  const [scores, setScores] = useState<ScoreItem[]>([]);
  const [specText, setSpecText] = useState('');

  // ── 冻结区 ──
  const [deltas, setDeltas] = useState<{ delta_id: string; frozen: boolean }[]>([]);
  const [selDelta, setSelDelta] = useState('');
  const [gates, setGates] = useState<Record<string, GateState> | null>(null);
  const [freezeAllowed, setFreezeAllowed] = useState(false);

  const flash = (fn: () => void) => { setError(''); setNotice(''); fn(); };

  const loadInterviews = async () => {
    try {
      const { interviews } = await specflowApi.listInterviews();
      setInterviews(interviews);
      if (interviews.length > 0 && !selIv) setSelIv(interviews[0].iv_id);
    } catch (e: any) { setError(e.message); }
  };

  const loadScores = async (ivId: string) => {
    if (!ivId) { setScores([]); return; }
    try {
      const { scores } = await specflowApi.listScores(ivId);
      setScores(scores);
    } catch (e: any) { setError(e.message); }
  };

  const loadDeltas = async () => {
    try {
      const { deltas } = await zentaoApi.frozenDeltas();
      setDeltas(deltas);
    } catch (e: any) { setError(e.message); }
  };

  const loadGates = async (deltaId: string) => {
    if (!deltaId) { setGates(null); return; }
    try {
      const r = await specflowApi.checkGates(deltaId, selIv);
      setGates(r.gates);
      setFreezeAllowed(r.freeze_allowed);
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { flash(() => { loadInterviews(); loadDeltas(); }); }, []);
  useEffect(() => { flash(() => loadScores(selIv)); }, [selIv]);
  useEffect(() => { flash(() => loadGates(selDelta)); }, [selDelta]);

  // ── 评分操作 ──
  const handleEvaluate = async () => {
    if (!selIv) return;
    try {
      const { scores } = await specflowApi.evaluateScores(selIv, specText);
      setNotice(`机打采集完成，产出 ${scores.length} 维 suggested 评分（QA 确认后计入总分）`);
      loadScores(selIv);
    } catch (e: any) { setError(e.message); }
  };

  const handleConfirmScore = async (s: ScoreItem, verdict: 'confirm' | 'reject') => {
    try {
      await specflowApi.confirmScore(s.id, verdict);
      setNotice(`${DIM_LABEL[s.dimension] || s.dimension} ${verdict === 'confirm' ? '已确认' : '已驳回'}`);
      loadScores(selIv);
    } catch (e: any) { setError(e.message); }
  };

  // ── 冻结操作 ──
  const handleGate1 = async () => {
    if (!selDelta) return;
    try {
      await specflowApi.gate1Confirm(selDelta, selIv);
      setNotice('闸① 产品确认已登记');
      loadGates(selDelta);
    } catch (e: any) { setError(e.message); }
  };

  const handleGate2 = async () => {
    if (!selDelta) return;
    try {
      const r = await specflowApi.gate2Conformance(selDelta);
      setNotice(`闸② 合规校验：${r.status}${r.degraded ? '（降级）' : ''}`);
      loadGates(selDelta);
    } catch (e: any) { setError(e.message); }
  };

  const handleFreeze = async () => {
    if (!selDelta) return;
    try {
      const r = await specflowApi.freezeDelta(selDelta, selIv);
      if (r.ok) {
        setNotice(`冻结成功：FREEZE.yaml 已落盘（${r.freeze?.frozen_at || ''}）`);
        loadDeltas();
      } else {
        setError(`冻结失败：${r.error}`);
      }
      loadGates(selDelta);
    } catch (e: any) { setError(e.message); }
  };

  const card = 'bg-surface-2 border border-border rounded-lg p-4 mb-4';
  const label = 'block text-xs text-gray-400 mb-1';
  const input = 'w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-info';
  const btn = 'px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const th = 'text-left text-[11px] text-gray-500 font-normal px-2 py-1 border-b border-border';
  const td = 'px-2 py-1.5 text-xs text-gray-300 border-b border-border/50 align-top';

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-base font-bold">⭐ 评分与冻结</h1>
        <div className="text-[11px] text-gray-500">评分确认/闸①确认/冻结需 product 角色 · 三闸全过才可冻结</div>
      </div>
      {error && <div className="mb-3 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
      {notice && <div className="mb-3 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}

      {/* ── 五维评分 ── */}
      <div className={card}>
        <h2 className="text-sm font-semibold mb-3">五维评分（机打维度 + QA 确认）</h2>
        <div className="flex flex-wrap items-end gap-3 mb-3">
          <div className="w-72">
            <span className={label}>面试（IV-xxx）</span>
            <select className={input} value={selIv} onChange={e => setSelIv(e.target.value)}>
              <option value="">— 选择面试 —</option>
              {interviews.map(iv => (
                <option key={iv.iv_id} value={iv.iv_id}>{iv.iv_id} · {iv.title}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 min-w-[280px]">
            <span className={label}>spec 文本（机打采集输入，可留空）</span>
            <textarea className={`${input} min-h-[44px]`} value={specText}
                      onChange={e => setSpecText(e.target.value)}
                      placeholder="粘贴草案 spec 文本（11 章/边界/前置条件扫描）" />
          </div>
          <button className={btn} onClick={handleEvaluate} disabled={!selIv}>机打采集</button>
        </div>
        {scores.length === 0 ? (
          <div className="text-xs text-gray-500">暂无评分，点击「机打采集」生成 suggested 评分</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr>
                <th className={th}>维度</th><th className={th}>得分</th><th className={th}>来源</th>
                <th className={th}>证据</th><th className={th}>状态</th><th className={th}>操作</th>
              </tr>
            </thead>
            <tbody>
              {scores.map(s => (
                <tr key={s.id}>
                  <td className={td}>{DIM_LABEL[s.dimension] || s.dimension}</td>
                  <td className={td}>{s.score}</td>
                  <td className={td}>{s.source}</td>
                  <td className={td}>
                    <span className="text-[11px] text-gray-500 line-clamp-2 max-w-[360px]">{s.evidence}</span>
                  </td>
                  <td className={td}>
                    <span className={s.status === 'confirmed' ? 'text-green-400' : s.status === 'rejected' ? 'text-gray-500' : 'text-yellow-400'}>
                      {s.status}
                    </span>
                  </td>
                  <td className={td}>
                    <div className="flex gap-1.5">
                      {s.status === 'suggested' && (
                        <>
                          <button className={btn} onClick={() => handleConfirmScore(s, 'confirm')}>确认</button>
                          <button className="px-3 py-1.5 rounded text-xs font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20"
                                  onClick={() => handleConfirmScore(s, 'reject')}>驳回</button>
                        </>
                      )}
                      {s.status !== 'suggested' && <span className="text-[11px] text-gray-600">已处理</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── 冻结三闸 ── */}
      <div className={card}>
        <h2 className="text-sm font-semibold mb-3">冻结三闸（① 产品确认 ② specstd 合规 ③ P0 清零）</h2>
        <div className="flex flex-wrap items-end gap-3 mb-3">
          <div className="w-72">
            <span className={label}>冻结 delta（FREEZE.yaml 在库）</span>
            <select className={input} value={selDelta} onChange={e => setSelDelta(e.target.value)}>
              <option value="">— 选择 delta —</option>
              {deltas.map(d => <option key={d.delta_id} value={d.delta_id}>{d.delta_id}</option>)}
            </select>
          </div>
          <button className={btn} onClick={handleGate1} disabled={!selDelta}>① 产品确认</button>
          <button className={btn} onClick={handleGate2} disabled={!selDelta}>② 合规校验</button>
          <button className={`${btn} ${freezeAllowed ? '' : 'opacity-40'}`} onClick={handleFreeze}
                  disabled={!selDelta || !freezeAllowed}>执行冻结</button>
          <span className="text-xs text-gray-500">
            {freezeAllowed ? <span className="text-green-400">三闸全过，可冻结</span> : '三闸未全过，冻结被拒'}
          </span>
        </div>
        {gates && (
          <div className="grid grid-cols-3 gap-3">
            {Object.entries(gates).map(([key, g]) => (
              <div key={key} className="border border-border/60 rounded p-3">
                <div className="text-xs font-medium mb-1">{GATE_LABEL[key] || key}</div>
                <div className={`text-sm font-bold ${g.status === 'pass' ? 'text-green-400' : 'text-red-400'}`}>
                  {g.status === 'pass' ? '✓ PASS' : '✗ ' + (g.status || 'FAIL')}
                </div>
                {g.errors && g.errors.length > 0 && (
                  <div className="text-[11px] text-red-400 mt-1">{g.errors.join('；')}</div>
                )}
                {g.findings && g.findings.length > 0 && (
                  <div className="text-[11px] text-yellow-400 mt-1 max-h-20 overflow-auto">
                    {g.findings.slice(0, 5).map((f, i) => (
                      <div key={i}>[{f.level}] {f.message}</div>
                    ))}
                  </div>
                )}
                {g.degraded && <div className="text-[11px] text-yellow-400 mt-1">（降级执行）</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
