// 反哺闭环：台账管理 + 通知配置（T-996 二合一：webhook CRUD 统一走 /api/notify/configs）

import { useState, useEffect } from 'react';
import NotifyConfigs from './NotifyConfigs';

const BASE = '/api';

interface LedgerEntry {
  spq_id: string;
  title: string;
  source: string;
  status: string;
  scenario_id: string;
  created_at: string;
  updated_at: string;
}

export default function Feedback() {
  const [tab, setTab] = useState<'ledger' | 'notify'>(() => {
    const q = new URLSearchParams(window.location.search).get('tab');
    const saved = localStorage.getItem('sg_feedback_tab');
    return q === 'notify' || (!q && saved === 'notify') ? 'notify' : 'ledger';
  });
  useEffect(() => { localStorage.setItem('sg_feedback_tab', tab); }, [tab]);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // 新建台账
  const [newTitle, setNewTitle] = useState('');
  const [newScenario, setNewScenario] = useState('');
  const [newSource, setNewSource] = useState('loop_b');

  const loadLedger = async () => {
    try {
      const res = await fetch(`${BASE}/feedback/ledger`);
      const data = await res.json();
      setEntries(data.entries || []);
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { loadLedger(); }, []);

  const createEntry = async () => {
    if (!newTitle) { setError('请输入标题'); return; }
    try {
      await fetch(`${BASE}/feedback/ledger`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle, source: newSource, scenario_id: newScenario }),
      });
      setNewTitle(''); setNewScenario('');
      loadLedger();
      setSuccess('台账条目已创建');
    } catch (e: any) { setError(e.message); }
  };

  const transition = async (spqId: string, status: string) => {
    try {
      await fetch(`${BASE}/feedback/ledger/${spqId}/transition`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      loadLedger();
    } catch (e: any) { setError(e.message); }
  };

  const statusColor = (s: string) => ({
    pending: 'text-warn',
    in_progress: 'text-info',
    closed: 'text-pass',
  }[s] || 'text-gray-400');

  const statusLabel = (s: string) => ({
    pending: '待讨论',
    in_progress: '研发修改中',
    closed: '已闭环',
  }[s] || s);

  return (
    <div className="flex flex-col h-full max-w-4xl">
      <div className="mb-4">
        <h2 className="font-display text-fs-title font-semibold text-gray-200">🔄 反哺闭环</h2>
        <p className="text-fs-body text-gray-500 mt-1">SPQ 台账管理 + 群聊 webhook 通知配置（用例级 fail/drift/skip 与计划级事件统一在此维护）</p>
      </div>

      {error && <div className="bg-fail/12 border border-fail/35 rounded p-2 mb-3 text-fail text-fs-lead" onClick={() => setError('')}>{error}</div>}
      {success && <div className="bg-pass/12 border border-pass/35 rounded p-2 mb-3 text-pass text-fs-lead" onClick={() => setSuccess('')}>{success}</div>}

      {/* Tab */}
      <div className="flex gap-2 mb-4">
        <button onClick={() => setTab('ledger')} className={`px-3 py-1.5 text-fs-lead rounded ${tab === 'ledger' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>台账 ({entries.length})</button>
        <button onClick={() => setTab('notify')} className={`px-3 py-1.5 text-fs-lead rounded ${tab === 'notify' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>通知配置</button>
      </div>

      {tab === 'ledger' && (
        <div className="flex-1 overflow-y-auto space-y-3">
          {/* 新建 */}
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="text-fs-body text-gray-500 mb-2">新建台账条目</div>
            <div className="flex gap-2 mb-2">
              <input value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="标题" className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
              <input value={newScenario} onChange={e => setNewScenario(e.target.value)} placeholder="场景 ID（可选）" className="w-40 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
              <select value={newSource} onChange={e => setNewSource(e.target.value)} className="bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300">
                <option value="loop_a">循环 A</option>
                <option value="loop_b">循环 B</option>
              </select>
            </div>
            <button onClick={createEntry} className="px-3 py-1 bg-info text-white rounded text-fs-lead hover:bg-info/90">创建</button>
          </div>

          {/* 列表 */}
          {entries.length === 0 ? (
            <div className="text-center text-gray-600 text-fs-lead py-8">暂无台账条目</div>
          ) : entries.map(e => (
            <div key={e.spq_id} className="bg-surface-1 rounded-lg border border-border p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-fs-lead font-mono text-info">{e.spq_id}</span>
                <span className={`text-fs-body ${statusColor(e.status)}`}>{statusLabel(e.status)}</span>
              </div>
              <div className="text-fs-lead text-gray-300">{e.title}</div>
              {e.scenario_id && <div className="text-fs-body text-gray-600 mt-1">场景: {e.scenario_id}</div>}
              <div className="text-fs-body text-gray-600 mt-1">来源: {e.source === 'loop_a' ? '循环 A' : '循环 B'} · 创建: {e.created_at}</div>
              <div className="flex gap-1 mt-2">
                {e.status === 'pending' && <button onClick={() => transition(e.spq_id, 'in_progress')} className="px-2 py-0.5 text-fs-body bg-info/12 text-info rounded">→ 研发修改中</button>}
                {e.status === 'in_progress' && <button onClick={() => transition(e.spq_id, 'closed')} className="px-2 py-0.5 text-fs-body bg-pass/12 text-pass rounded">→ 已闭环</button>}
                {e.status !== 'pending' && <button onClick={() => transition(e.spq_id, 'pending')} className="px-2 py-0.5 text-fs-body bg-warn/12 text-warn rounded">→ 待讨论</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'notify' && (
        <div className="flex-1 overflow-y-auto">
          <NotifyConfigs embedded />
        </div>
      )}
    </div>
  );
}
