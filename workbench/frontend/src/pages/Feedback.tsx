// 反哺闭环：台账管理 + 飞书通知配置

import { useState, useEffect } from 'react';

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

interface WebhookEntry {
  id: string;
  system: string;
  scenario_pattern: string;
  masked_url: string;
  events: string[];
  created_at: string;
}

export default function Feedback() {
  const [tab, setTab] = useState<'ledger' | 'notify'>('ledger');
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookEntry[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // 新建台账
  const [newTitle, setNewTitle] = useState('');
  const [newScenario, setNewScenario] = useState('');
  const [newSource, setNewSource] = useState('loop_b');

  // 注册 webhook
  const [whSystem, setWhSystem] = useState('tdm');
  const [whPattern, setWhPattern] = useState('PP-*');
  const [whUrl, setWhUrl] = useState('');
  const [whEvents, setWhEvents] = useState<string[]>(['fail']);

  const loadLedger = async () => {
    try {
      const res = await fetch(`${BASE}/feedback/ledger`);
      const data = await res.json();
      setEntries(data.entries || []);
    } catch (e: any) { setError(e.message); }
  };

  const loadWebhooks = async () => {
    try {
      const res = await fetch(`${BASE}/feedback/notify`);
      const data = await res.json();
      setWebhooks(data.webhooks || []);
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { loadLedger(); loadWebhooks(); }, []);

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

  const registerWebhook = async () => {
    if (!whUrl) { setError('请输入 webhook URL'); return; }
    try {
      const res = await fetch(`${BASE}/feedback/notify`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system: whSystem, scenario_pattern: whPattern, url: whUrl, events: whEvents }),
      });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || '注册失败'); }
      setWhUrl('');
      loadWebhooks();
      setSuccess('webhook 已注册');
    } catch (e: any) { setError(e.message); }
  };

  const unregisterWebhook = async (id: string) => {
    try {
      await fetch(`${BASE}/feedback/notify/${id}`, { method: 'DELETE' });
      loadWebhooks();
    } catch (e: any) { setError(e.message); }
  };

  const toggleEvent = (ev: string) => {
    setWhEvents(prev => prev.includes(ev) ? prev.filter(e => e !== ev) : [...prev, ev]);
  };

  const statusColor = (s: string) => ({
    pending: 'text-yellow-400',
    in_progress: 'text-blue-400',
    closed: 'text-green-400',
  }[s] || 'text-gray-400');

  const statusLabel = (s: string) => ({
    pending: '待讨论',
    in_progress: '研发修改中',
    closed: '已闭环',
  }[s] || s);

  return (
    <div className="flex flex-col h-full max-w-4xl">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">🔄 反哺闭环</h2>
        <p className="text-xs text-gray-500 mt-1">SPQ 台账管理 + 飞书 webhook 通知配置</p>
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-3 text-red-400 text-sm" onClick={() => setError('')}>{error}</div>}
      {success && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 mb-3 text-green-400 text-sm" onClick={() => setSuccess('')}>{success}</div>}

      {/* Tab */}
      <div className="flex gap-2 mb-4">
        <button onClick={() => setTab('ledger')} className={`px-3 py-1.5 text-sm rounded ${tab === 'ledger' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>台账 ({entries.length})</button>
        <button onClick={() => setTab('notify')} className={`px-3 py-1.5 text-sm rounded ${tab === 'notify' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>通知配置 ({webhooks.length})</button>
      </div>

      {tab === 'ledger' && (
        <div className="flex-1 overflow-y-auto space-y-3">
          {/* 新建 */}
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="text-xs text-gray-500 mb-2">新建台账条目</div>
            <div className="flex gap-2 mb-2">
              <input value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="标题" className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              <input value={newScenario} onChange={e => setNewScenario(e.target.value)} placeholder="场景 ID（可选）" className="w-40 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              <select value={newSource} onChange={e => setNewSource(e.target.value)} className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300">
                <option value="loop_a">循环 A</option>
                <option value="loop_b">循环 B</option>
              </select>
            </div>
            <button onClick={createEntry} className="px-3 py-1 bg-info text-white rounded text-sm hover:bg-info/90">创建</button>
          </div>

          {/* 列表 */}
          {entries.length === 0 ? (
            <div className="text-center text-gray-600 text-sm py-8">暂无台账条目</div>
          ) : entries.map(e => (
            <div key={e.spq_id} className="bg-surface-1 rounded-lg border border-border p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-mono text-info">{e.spq_id}</span>
                <span className={`text-xs ${statusColor(e.status)}`}>{statusLabel(e.status)}</span>
              </div>
              <div className="text-sm text-gray-300">{e.title}</div>
              {e.scenario_id && <div className="text-xs text-gray-600 mt-1">场景: {e.scenario_id}</div>}
              <div className="text-xs text-gray-600 mt-1">来源: {e.source === 'loop_a' ? '循环 A' : '循环 B'} · 创建: {e.created_at}</div>
              <div className="flex gap-1 mt-2">
                {e.status === 'pending' && <button onClick={() => transition(e.spq_id, 'in_progress')} className="px-2 py-0.5 text-xs bg-blue-900/30 text-blue-400 rounded">→ 研发修改中</button>}
                {e.status === 'in_progress' && <button onClick={() => transition(e.spq_id, 'closed')} className="px-2 py-0.5 text-xs bg-green-900/30 text-green-400 rounded">→ 已闭环</button>}
                {e.status !== 'pending' && <button onClick={() => transition(e.spq_id, 'pending')} className="px-2 py-0.5 text-xs bg-yellow-900/30 text-yellow-400 rounded">→ 待讨论</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'notify' && (
        <div className="flex-1 overflow-y-auto space-y-3">
          {/* 注册 */}
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="text-xs text-gray-500 mb-2">注册飞书 webhook</div>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <input value={whSystem} onChange={e => setWhSystem(e.target.value)} placeholder="系统 (tdm)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              <input value={whPattern} onChange={e => setWhPattern(e.target.value)} placeholder="场景 pattern (PP-*)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              <input value={whUrl} onChange={e => setWhUrl(e.target.value)} placeholder="webhook URL" className="col-span-2 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
            </div>
            <div className="flex gap-2 mb-2">
              {['fail', 'drift', 'skip'].map(ev => (
                <button key={ev} onClick={() => toggleEvent(ev)} className={`px-2 py-0.5 text-xs rounded ${whEvents.includes(ev) ? 'bg-info text-white' : 'bg-surface-3 text-gray-500'}`}>{ev}</button>
              ))}
            </div>
            <button onClick={registerWebhook} className="px-3 py-1 bg-info text-white rounded text-sm hover:bg-info/90">注册</button>
          </div>

          {/* 列表 */}
          {webhooks.length === 0 ? (
            <div className="text-center text-gray-600 text-sm py-8">暂无 webhook 配置</div>
          ) : webhooks.map(w => (
            <div key={w.id} className="bg-surface-1 rounded-lg border border-border p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-mono text-gray-400">{w.id}</span>
                <button onClick={() => unregisterWebhook(w.id)} className="text-xs text-red-400 hover:text-red-300">注销</button>
              </div>
              <div className="text-sm text-gray-300 mt-1">{w.system} · {w.scenario_pattern}</div>
              <div className="text-xs text-gray-600 font-mono mt-1">{w.masked_url}</div>
              <div className="flex gap-1 mt-1">
                {w.events.map(ev => <span key={ev} className="text-xs px-1.5 py-0.5 bg-surface-3 rounded text-gray-500">{ev}</span>)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
