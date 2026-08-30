/**
 * MyActivity — 我的活动（T-1000 F3，按当前登录 emp 过滤）
 *
 * 四页签：我的产出（product_index，含溯源跳会话）/ 我的会话（agent/sessions）/
 *         我的工具调用（audit 本人查自己，T-1000 已放开）/ 我的执行（runs history 本人）。
 */

import { useCallback, useEffect, useState } from 'react';
import { agentApi, auditApi, productsApi, runsApi, type ProductRecord } from '../api';
import { chatRouteForPurpose } from './agentChat/utils';

const TYPE_LABELS: Record<string, string> = {
  draft: '📝 草稿',
  scenario: '🧩 场景',
  plan: '📋 计划',
  doc: '📄 文档',
};

const TABS = [
  { id: 'products', label: '📦 我的产出' },
  { id: 'sessions', label: '💬 我的会话' },
  { id: 'tools', label: '🛠 工具调用' },
  { id: 'runs', label: '▶️ 场景执行' },
] as const;
type TabId = typeof TABS[number]['id'];

export default function MyActivity() {
  const [tab, setTab] = useState<TabId>(() => {
    const q = new URLSearchParams(window.location.search).get('tab');
    const saved = localStorage.getItem('sg_activity_tab');
    const valid = (v: string | null): v is TabId => TABS.some(t => t.id === v);
    if (valid(q)) return q;
    if (valid(saved)) return saved;
    return 'products';
  });
  useEffect(() => { localStorage.setItem('sg_activity_tab', tab); }, [tab]);

  const [error, setError] = useState('');
  const [products, setProducts] = useState<ProductRecord[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [calls, setCalls] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [typeFilter, setTypeFilter] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (tab === 'products') {
        const r = await productsApi.mine({ type: typeFilter || undefined, limit: 200 });
        setProducts(r.products);
      } else if (tab === 'sessions') {
        const r = await agentApi.listSessions();
        setSessions(r.sessions || []);
      } else if (tab === 'tools') {
        const r = await auditApi.list({ limit: 100 });
        setCalls(r.calls || []);
      } else {
        const r = await runsApi.history(50);
        setRuns(r || []);
      }
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [tab, typeFilter]);

  useEffect(() => { load(); }, [load]);

  // T-1039：跳会话按用途分流双菜单（产品用途→/agent-product）；无用途信息时
  // 默认 /agent，AgentChat 路由守卫会按会话真实用途改道
  const openSession = (sid: string, purpose?: string) => {
    if (sid) window.location.href = `${chatRouteForPurpose(purpose || '')}?session=${encodeURIComponent(sid)}`;
  };

  return (
    <div className="flex flex-col h-full max-w-5xl">
      <div className="mb-4">
        <h2 className="text-fs-title font-bold text-gray-200">🧭 我的活动</h2>
        <p className="text-fs-body text-gray-500 mt-1">我的产出/会话/工具调用/执行历史（仅本人数据，产出可溯源到产出会话）</p>
      </div>

      <div className="flex gap-1 mb-3 flex-shrink-0">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-fs-lead rounded ${tab === t.id ? 'bg-info text-white' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="bg-fail/12 border border-fail/35 rounded p-2 mb-3 text-fail text-fs-lead flex-shrink-0" onClick={() => setError('')}>{error}</div>}
      {loading && <div className="text-fs-body text-gray-500 mb-2 flex-shrink-0">加载中…</div>}

      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'products' && (
          <div className="space-y-2">
            <div className="flex gap-1 flex-shrink-0">
              {['', 'draft', 'scenario', 'plan'].map(t => (
                <button key={t} onClick={() => setTypeFilter(t)}
                  className={`px-2 py-1 text-fs-body rounded ${typeFilter === t ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-500'}`}>
                  {t === '' ? '全部' : TYPE_LABELS[t] || t}
                </button>
              ))}
            </div>
            {products.length === 0 && !loading && (
              <div className="text-center text-gray-600 text-fs-lead py-8">暂无产出记录（草稿/场景/计划产生后自动登记）</div>
            )}
            {products.map(p => (
              <div key={p.id} className="bg-surface-1 rounded-lg border border-border p-3">
                <div className="flex items-center gap-2">
                  <span className="text-fs-body px-1.5 py-0.5 rounded bg-surface-3 text-gray-400">{TYPE_LABELS[p.product_type] || p.product_type}</span>
                  <span className="text-fs-lead text-gray-200 font-mono truncate">{p.product_path}</span>
                  <span className="text-fs-aux text-gray-600 ml-auto">{p.created_at}</span>
                </div>
                <div className="text-fs-body text-gray-600 mt-1">
                  {p.workspace && <span>工作区: {p.workspace}</span>}
                  {p.fr_anchor && <span className="ml-2">FR: {p.fr_anchor}</span>}
                </div>
                {p.session_id && (
                  <button onClick={() => openSession(p.session_id)}
                    className="mt-1.5 px-2 py-0.5 text-fs-body bg-info/15 text-info rounded hover:bg-info/25">
                    🔗 溯源：打开产出会话
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === 'sessions' && (
          <div className="space-y-2">
            {sessions.length === 0 && !loading && (
              <div className="text-center text-gray-600 text-fs-lead py-8">暂无会话</div>
            )}
            {sessions.map((s: any) => (
              <div key={s.session_id || s.id} className="bg-surface-1 rounded-lg border border-border p-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-fs-lead text-gray-200 truncate">{s.title || s.session_id || s.id}</div>
                  <div className="text-fs-body text-gray-600">
                    {s.updated_at || s.created_at || ''}{s.workspace ? ` · ${s.workspace}` : ''}
                  </div>
                </div>
                <button onClick={() => openSession(s.session_id || s.id, s.purpose)}
                  className="px-2 py-1 text-fs-body bg-info/15 text-info rounded hover:bg-info/25 flex-shrink-0">
                  打开
                </button>
              </div>
            ))}
          </div>
        )}

        {tab === 'tools' && (
          <div className="bg-surface-1 rounded-lg border border-border overflow-hidden">
            <table className="w-full text-fs-body">
              <thead>
                <tr className="text-left text-gray-500 border-b border-border">
                  <th className="px-3 py-2">时间</th>
                  <th className="px-3 py-2">工具</th>
                  <th className="px-3 py-2">判定</th>
                  <th className="px-3 py-2">摘要</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c: any) => (
                  <tr key={c.id} className="border-b border-border/50 text-gray-400">
                    <td className="px-3 py-1.5 font-mono whitespace-nowrap">{c.created_at}</td>
                    <td className="px-3 py-1.5 font-mono">{c.tool_name}</td>
                    <td className={`px-3 py-1.5 ${c.verdict === 'ok' ? 'text-pass' : 'text-fail'}`}>{c.verdict}</td>
                    <td className="px-3 py-1.5 truncate max-w-[20rem]">{c.args_digest || '—'}</td>
                  </tr>
                ))}
                {calls.length === 0 && !loading && (
                  <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-600">暂无工具调用记录</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'runs' && (
          <div className="space-y-2">
            {runs.length === 0 && !loading && (
              <div className="text-center text-gray-600 text-fs-lead py-8">暂无执行记录</div>
            )}
            {runs.map((r: any) => (
              <div key={r.run_id} className="bg-surface-1 rounded-lg border border-border p-3 flex items-center gap-3">
                <span className="text-fs-lead font-mono text-info">{r.run_id}</span>
                <span className="text-fs-body text-gray-500">{r.system} · {r.env}</span>
                <span className="text-fs-body text-gray-600">{r.started_at}</span>
                {r.stats && (
                  <span className="text-fs-body text-gray-500 ml-auto">
                    ✅{r.stats.pass ?? 0} ❌{r.stats.fail ?? 0} ⏭{r.stats.skip ?? 0}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
