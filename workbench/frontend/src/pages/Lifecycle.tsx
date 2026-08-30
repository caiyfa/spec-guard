// 单元测试生命周期监控（K-xxx）：以「一条测试」为主线，聚合台账——
// 草稿状态（草稿待评审/更新中）× 库内资产 × 执行史 × 失败修复闭环
// 数据源：/api/lifecycle（SQLite 台账投影聚合，文件仍是真相源）

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { lifecycleApi } from '../api';
import CoveragePanel from './CoveragePanel';
import type { LifecycleItem, LifecycleSummary, LifecycleDetail } from '../api';

const VERDICT_STYLE: Record<string, string> = {
  PASS: 'text-pass', FAIL: 'text-fail', SKIP: 'text-skip', BLOCKED: 'text-blocked', ERROR: 'text-fail',
};
const FAILURE_VERDICTS = ['FAIL', 'ERROR', 'BLOCKED'];

/** 状态徽标样式 */
const STATUS_STYLE: Record<string, string> = {
  in_library: 'bg-pass/12 text-pass border-pass/35',
  draft_pending: 'bg-warn/12 text-warn border-warn/35',
  draft_updating: 'bg-blue-900/40 text-blue-400 border-blue-700/50',
  discarded: 'bg-gray-700/40 text-gray-400 border-gray-600',
  unknown: 'bg-gray-700/40 text-gray-500 border-gray-600',
};

function StatusBadge({ item }: { item: LifecycleItem }) {
  const mark = item.last_verdict && FAILURE_VERDICTS.includes(item.last_verdict) && item.status !== 'discarded'
    ? ' ❌' : '';
  return (
    <span className={`text-fs-aux px-1.5 py-0.5 rounded border whitespace-nowrap ${STATUS_STYLE[item.status] || STATUS_STYLE.unknown}`}>
      {item.status_label}{mark}
    </span>
  );
}

function VerdictDots({ verdicts }: { verdicts: string[] }) {
  if (!verdicts || verdicts.length === 0) return <span className="text-fs-aux text-gray-600">—</span>;
  return (
    <span className="flex gap-0.5 items-center" title={`最近 ${verdicts.length} 次：${verdicts.join(' → ')}`}>
      {verdicts.map((v, i) => (
        <span key={i} className={`w-2 h-2 rounded-full ${
          v === 'PASS' ? 'bg-pass' : FAILURE_VERDICTS.includes(v) ? 'bg-fail' : v === 'SKIP' ? 'bg-skip' : 'bg-gray-600'
        }`} />
      ))}
    </span>
  );
}

function fmtAt(iso: string): string {
  if (!iso) return '';
  const m = iso.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
  return m ? `${m[1].slice(2)} ${m[2]}` : iso;
}

function LifecycleBoard() {
  const navigate = useNavigate();
  const [items, setItems] = useState<LifecycleItem[]>([]);
  const [summary, setSummary] = useState<LifecycleSummary | null>(null);
  const [modules, setModules] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // 筛选
  const [filter, setFilter] = useState<'all' | 'draft' | 'updating' | 'in_library' | 'discarded' | 'failed' | 'loop'>('all');
  const [module, setModule] = useState('');
  const [keyword, setKeyword] = useState('');
  // 详情
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<LifecycleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await lifecycleApi.list();
      setItems(r.items || []);
      setSummary(r.summary || null);
      const mods = Array.from(new Set((r.items || []).map(i => i.module).filter(Boolean))).sort();
      setModules(mods);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const loadDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    setDetail(null);
    try {
      setDetail(await lifecycleApi.detail(id));
    } catch (e: any) {
      setError(`详情加载失败: ${e.message || ''}`);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const filtered = useMemo(() => {
    return items.filter(it => {
      if (filter === 'draft' && it.status !== 'draft_pending') return false;
      if (filter === 'updating' && it.status !== 'draft_updating') return false;
      if (filter === 'in_library' && it.status !== 'in_library') return false;
      if (filter === 'discarded' && it.status !== 'discarded') return false;
      if (filter === 'failed' && !(it.last_verdict && FAILURE_VERDICTS.includes(it.last_verdict))) return false;
      if (filter === 'loop' && !(it.closed_loops > 0)) return false;
      if (module && it.module !== module) return false;
      if (keyword && !(`${it.id} ${it.title}`.toLowerCase().includes(keyword.toLowerCase()))) return false;
      return true;
    });
  }, [items, filter, module, keyword]);

  const statsCards: { label: string; value: number; cls?: string; filter: typeof filter }[] = [
    { label: '测试总数', value: summary?.total || 0, filter: 'all' },
    { label: '已入库', value: summary?.in_library || 0, filter: 'in_library' },
    { label: '草稿待评审', value: summary?.draft_pending || 0, cls: 'text-warn', filter: 'draft' },
    { label: '更新中', value: summary?.draft_updating || 0, cls: 'text-blue-400', filter: 'updating' },
    { label: '7 天内失败', value: summary?.recent_failed_7d || 0, cls: 'text-fail', filter: 'failed' },
    { label: '修复闭环', value: summary?.closed_loops || 0, cls: 'text-pass', filter: 'loop' },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-fs-title font-bold text-gray-200">🧬 测试生命周期</h2>
          <p className="text-fs-body text-gray-500 mt-0.5">
            一条测试的完整历程：草稿 → 入库 → 执行 → 失败 → 修复闭环（台账聚合，文件仍是真相源）
          </p>
        </div>
      </div>

      {/* 统计卡 */}
      <div className="grid grid-cols-6 gap-2 mb-3">
        {statsCards.map(c => (
          <button key={c.label} onClick={() => setFilter(c.filter)}
            className={`rounded-lg border p-2.5 text-left transition-colors ${
              filter === c.filter ? 'border-info bg-info/10' : 'border-border bg-surface-2 hover:bg-surface-3'
            }`}>
            <div className={`text-xl font-bold ${c.cls || 'text-gray-200'}`}>{c.value}</div>
            <div className="text-fs-aux text-gray-500">{c.label}</div>
          </button>
        ))}
      </div>

      {/* 筛选栏 */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {([['all', '全部'], ['failed', '❌ 最近失败'], ['draft', '📝 草稿待评审'], ['updating', '🔄 更新中'], ['loop', '✅ 有闭环']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)}
            className={`px-2.5 py-1 rounded text-fs-body ${
              filter === k ? 'bg-info/20 text-info' : 'bg-surface-2 text-gray-400 hover:text-gray-200'
            }`}>
            {label}
          </button>
        ))}
        <select value={module} onChange={e => setModule(e.target.value)}
          className="ml-auto bg-surface-2 border border-border rounded px-2 py-1 text-fs-body text-gray-300">
          <option value="">全部模块</option>
          {modules.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <input value={keyword} onChange={e => setKeyword(e.target.value)}
          placeholder="搜索 ID / 标题…"
          className="bg-surface-2 border border-border rounded px-2 py-1 text-fs-body text-gray-300 w-48" />
      </div>

      {error && <div className="mb-2 text-fs-lead text-fail">❌ {error}</div>}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* 左：生命周期列表 */}
        <div className="flex-1 flex flex-col min-w-0">
          {loading ? (
            <div className="text-center text-gray-600 text-fs-lead py-10">加载中…</div>
          ) : (
            <div className="flex-1 overflow-y-auto space-y-1">
              {filtered.length === 0 && (
                <div className="text-center text-gray-600 text-fs-lead py-10">无匹配测试</div>
              )}
              {filtered.map(it => (
                <button key={it.id} onClick={() => loadDetail(it.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                    selectedId === it.id
                      ? 'border-info bg-info/10'
                      : 'border-border bg-surface-2 hover:bg-surface-3'
                  }`}>
                  <div className="flex items-center gap-2">
                    <span className="text-fs-lead font-mono text-gray-200">{it.id}</span>
                    <StatusBadge item={it} />
                    {it.closed_loops > 0 && (
                      <span className="text-fs-micro text-pass" title={`${it.closed_loops} 次失败修复闭环`}>🔄×{it.closed_loops}</span>
                    )}
                    <VerdictDots verdicts={it.recent_verdicts} />
                    <span className="ml-auto text-fs-aux text-gray-600 whitespace-nowrap">
                      {it.last_run_id ? `${fmtAt(it.last_run_at)} · ${it.last_run_id}` : '未执行过'}
                    </span>
                  </div>
                  <div className="text-fs-body text-gray-500 truncate mt-0.5">
                    {it.title || ''}
                    {it.module && <span className="text-gray-600"> · {it.module}</span>}
                    {it.draft_filename && <span className="text-yellow-600/80"> · 📝 {it.draft_filename}</span>}
                  </div>
                  {it.last_failure && (
                    <div className="text-fs-aux text-fail/80 truncate mt-0.5"
                      title={`${it.last_failure.run_id} · ${it.last_failure.message}`}>
                      ❌ {it.last_failure.category || 'failed'} · {it.last_failure.message}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 右：生命周期详情 */}
        <div className="w-[420px] flex-shrink-0 flex flex-col min-h-0 border border-border rounded-lg bg-surface-2/50">
          {!selectedId ? (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-fs-lead px-6 text-center">
              选择左侧一条测试，查看完整生命周期时间线
            </div>
          ) : detailLoading ? (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-fs-lead">加载详情…</div>
          ) : detail ? (
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-gray-200">{detail.id}</span>
                <span className={`text-fs-aux px-1.5 py-0.5 rounded border ${STATUS_STYLE[detail.status] || STATUS_STYLE.unknown}`}>
                  {detail.status_label}
                </span>
              </div>
              <div className="text-fs-body text-gray-500 mt-0.5">{detail.title}</div>
              <div className="text-fs-aux text-gray-600 mt-0.5">
                {detail.module && `模块 ${detail.module} · `}v{detail.version || '—'}
                {detail.file_path && ` · ${detail.file_path}`}
              </div>

              {/* 快捷操作 */}
              <div className="flex gap-1.5 mt-2 flex-wrap">
                <button onClick={() => navigate(`/dag?focus=${encodeURIComponent(detail.id)}`)}
                  className="px-2 py-1 rounded bg-info/20 text-info text-fs-body hover:bg-info/30">
                  🕸 DAG 编排
                </button>
                <button onClick={() => navigate('/run')}
                  className="px-2 py-1 rounded bg-warn/20 text-warn text-fs-body hover:bg-warn/30">
                  ▶ 测试执行
                </button>
                {detail.draft_status === 'draft' && (
                  <button onClick={() => navigate('/drafts')}
                    className="px-2 py-1 rounded bg-warn/12 text-warn text-fs-body hover:bg-warn/12/60">
                    📝 草稿评审
                  </button>
                )}
              </div>

              {/* 时间线 */}
              <div className="mt-3 text-fs-body font-medium text-gray-300">生命周期时间线</div>
              <div className="mt-1.5 space-y-0">
                {detail.timeline.length === 0 && <div className="text-fs-aux text-gray-600">暂无事件</div>}
                {detail.timeline.map((e, i) => (
                  <div key={i} className="flex gap-2">
                    <div className="flex flex-col items-center">
                      <span className={`w-2 h-2 rounded-full mt-1.5 ${
                        e.type === 'loop_closed' ? 'bg-pass'
                        : e.type === 'promoted' ? 'bg-pass'
                        : e.type === 'discarded' ? 'bg-gray-500'
                        : e.type === 'draft_updated' ? 'bg-warn'
                        : e.verdict === 'PASS' ? 'bg-pass'
                        : FAILURE_VERDICTS.includes(e.verdict || '') ? 'bg-fail'
                        : 'bg-gray-600'
                      }`} />
                      {i < detail.timeline.length - 1 && <span className="w-px flex-1 bg-border/60 my-0.5" />}
                    </div>
                    <div className="pb-2.5 min-w-0">
                      <div className="flex items-center gap-1.5 text-fs-body">
                        <span className="text-gray-300">{e.label}</span>
                        {e.verdict && (
                          <span className={`font-medium ${VERDICT_STYLE[e.verdict] || 'text-gray-400'}`}>{e.verdict}</span>
                        )}
                      </div>
                      {e.detail && <div className="text-fs-aux text-gray-600 truncate" title={e.detail}>{e.detail}</div>}
                      <div className="text-fs-micro text-gray-700">{fmtAt(e.at || '')}</div>
                    </div>
                  </div>
                ))}
              </div>

              {/* 执行历史 */}
              <div className="mt-3 text-fs-body font-medium text-gray-300">执行历史（{detail.runs.length}）</div>
              <div className="mt-1.5 space-y-1">
                {detail.runs.length === 0 && <div className="text-fs-aux text-gray-600">暂无执行记录</div>}
                {detail.runs.map(r => (
                  <div key={r.run_id} className="rounded bg-surface-2 border border-border/60 px-2 py-1.5">
                    <div className="flex items-center gap-2 text-fs-body">
                      <span className={`font-medium ${VERDICT_STYLE[r.verdict] || 'text-gray-400'}`}>{r.verdict}</span>
                      <span className="font-mono text-gray-400">{r.run_id}</span>
                      <span className="ml-auto text-fs-aux text-gray-600">{r.duration_ms}ms · {fmtAt(r.finished_at)}</span>
                    </div>
                    {r.message && <div className="text-fs-aux text-fail/80 truncate mt-0.5" title={r.message}>{r.message}</div>}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-fs-lead">加载详情…</div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── T-996：覆盖与生命周期一页两 tab（生命周期台账 + 覆盖缺口），?tab= 深链 + localStorage 记忆 ──
const LC_TABS = [
  { id: 'lifecycle', label: '🧪 测试生命周期' },
  { id: 'coverage', label: '🕳 覆盖缺口' },
] as const;
type LcTab = typeof LC_TABS[number]['id'];

export default function Lifecycle() {
  const [tab, setTab] = useState<LcTab>(() => {
    const q = new URLSearchParams(window.location.search).get('tab');
    const saved = localStorage.getItem('sg_lifecycle_tab');
    const valid = (v: string | null): v is LcTab => LC_TABS.some(t => t.id === v);
    if (valid(q)) return q;
    if (valid(saved)) return saved;
    return 'lifecycle';
  });
  useEffect(() => { localStorage.setItem('sg_lifecycle_tab', tab); }, [tab]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 mb-4 flex-shrink-0">
        {LC_TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-fs-lead rounded ${tab === t.id ? 'bg-info text-white' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'lifecycle' && <LifecycleBoard />}
        {tab === 'coverage' && <CoveragePanel />}
      </div>
    </div>
  );
}
