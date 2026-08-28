// T-1035：场景库质量看板（只读）——覆盖追溯/断言深度/问题分布一屏可见，不用翻 YAML。
// 评级与问题标记口径唯一事实源在后端 services/scenario_quality.py，本页只渲染。
// 三态分离（加载中/空库/错误）+ tab 与筛选条件 localStorage 记忆（体验基线①③）+ 单点刷新（④）。

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { scenarioQualityApi } from '../api';
import type { QualityGrade, QualityOverview, ScenarioQualityRow } from '../api';

const GRADES: QualityGrade[] = ['deep', 'medium', 'shallow', 'no-verify'];
const ISSUES = ['missing-covers', 'invalid-covers', 'shallow', 'no-verify', 'probe'];

const GRADE_LABEL: Record<QualityGrade, string> = {
  deep: '深断言', medium: '中等', shallow: '浅断言', 'no-verify': '无断言',
};
const GRADE_CLS: Record<QualityGrade, string> = {
  deep: 'bg-green-900/40 text-green-400',
  medium: 'bg-blue-900/40 text-blue-400',
  shallow: 'bg-yellow-900/40 text-yellow-400',
  'no-verify': 'bg-red-900/40 text-red-400',
};
const ISSUE_LABEL: Record<string, string> = {
  'missing-covers': '缺 covers', 'invalid-covers': 'covers 失效',
  shallow: '浅断言', 'no-verify': '无断言', probe: '探针',
};
const ISSUE_CLS: Record<string, string> = {
  'missing-covers': 'bg-yellow-900/40 text-yellow-400',
  'invalid-covers': 'bg-red-900/40 text-red-400',
  shallow: 'bg-yellow-900/40 text-yellow-400',
  'no-verify': 'bg-red-900/40 text-red-400',
  probe: 'bg-red-900/40 text-red-400',
};

const SQ_TABS = [
  { id: 'suites', label: '🗂 套件视图' },
  { id: 'scenarios', label: '📄 场景明细' },
  { id: 'matrix', label: '🧰 能力矩阵' },
] as const;
type SqTab = typeof SQ_TABS[number]['id'];

interface Filters { suite: string; grade: string; issue: string; q: string }
const EMPTY_FILTERS: Filters = { suite: '', grade: '', issue: '', q: '' };

function loadFilters(): Filters {
  try {
    const raw = localStorage.getItem('sg_sq_filters');
    if (raw) {
      const p = JSON.parse(raw);
      return {
        suite: typeof p.suite === 'string' ? p.suite : '',
        grade: GRADES.includes(p.grade) ? p.grade : '',
        issue: ISSUES.includes(p.issue) ? p.issue : '',
        q: typeof p.q === 'string' ? p.q : '',
      };
    }
  } catch { /* 损坏值诚实回退默认 */ }
  return EMPTY_FILTERS;
}

export default function ScenarioQuality() {
  const [data, setData] = useState<QualityOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<SqTab>(() => {
    const q = new URLSearchParams(window.location.search).get('tab');
    const saved = localStorage.getItem('sg_sq_tab');
    const valid = (v: string | null): v is SqTab => SQ_TABS.some(t => t.id === v);
    if (valid(q)) return q;
    if (valid(saved)) return saved;
    return 'suites';
  });
  const [filters, setFilters] = useState<Filters>(loadFilters);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => { localStorage.setItem('sg_sq_tab', tab); }, [tab]);
  useEffect(() => { localStorage.setItem('sg_sq_filters', JSON.stringify(filters)); }, [filters]);

  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    setError('');
    try {
      setData(await scenarioQualityApi.overview(force));
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // 恢复值失效（套件在当前库不存在，如切换工作区后）→ 诚实回退「全部」
  useEffect(() => {
    if (data && filters.suite && !data.suites.some(s => s.key === filters.suite)) {
      setFilters(f => ({ ...f, suite: '' }));
    }
  }, [data, filters.suite]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = filters.q.trim().toLowerCase();
    return data.scenarios.filter(s =>
      (!filters.suite || s.suite === filters.suite) &&
      (!filters.grade || s.grade === filters.grade) &&
      (!filters.issue || s.issues.includes(filters.issue as any)) &&
      (!q || s.id.toLowerCase().includes(q) || s.title.toLowerCase().includes(q)));
  }, [data, filters]);

  const gotoSuite = (key: string) => {
    setFilters(f => ({ ...f, suite: key }));
    setTab('scenarios');
  };
  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const t = data?.totals;

  return (
    <div className="max-w-7xl mx-auto">
      {/* 页头 */}
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-xl font-bold">📋 场景库质量</h1>
        <button onClick={() => refresh(true)} disabled={loading}
          className="btn-ghost text-sm" title="强制重扫场景库（绕过 30s 缓存）">
          {loading ? '扫描中…' : '🔄 刷新'}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        {data
          ? `扫描于 ${data.generated_at} · ${data.root} · 评级口径：深=oracle/DB校对/python 或 db_query；浅=仅状态+字段存在性断言且≤3条；无=verify 为空`
          : '覆盖追溯 / 断言深度 / 问题分布一屏可见'}
      </p>

      {/* 三态：错误横幅 */}
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
          ❌ 加载场景库质量失败：{error}
          <button onClick={() => refresh(true)} className="ml-3 underline">重试</button>
        </div>
      )}

      {/* 三态：加载中 */}
      {loading && !data && !error && (
        <div className="py-16 text-center text-gray-500 text-sm">加载中…</div>
      )}

      {/* 三态：空库（独立文案，不与加载中混用） */}
      {!loading && !error && data && t?.scenarios === 0 && (
        <div className="py-16 text-center text-gray-500 text-sm">
          场景库为空（未扫描到场景 YAML）——场景库根：{data.root}
        </div>
      )}

      {!error && data && t && t.scenarios > 0 && (
        <>
          {/* 统计卡 */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-4">
            <div className="card-hover p-3">
              <div className="text-xs text-gray-500 mb-1">场景总数</div>
              <div className="text-lg font-semibold">{t.scenarios}<span className="text-xs text-gray-500 ml-1">/ {t.suites} 套件</span></div>
            </div>
            <div className="card-hover p-3 cursor-pointer" title="查看缺 covers 的场景"
              onClick={() => { setFilters(f => ({ ...f, issue: 'missing-covers', grade: '', suite: '' })); setTab('scenarios'); }}>
              <div className="text-xs text-gray-500 mb-1">covers 覆盖</div>
              <div className="text-lg font-semibold">
                <span className={t.covers_rate < 50 ? 'text-fail' : 'text-pass'}>{t.covers_rate}%</span>
                <span className="text-xs text-gray-500 ml-1">{t.covers_tagged}/{t.scenarios}</span>
              </div>
            </div>
            <div className="card-hover p-3">
              <div className="text-xs text-gray-500 mb-1">深断言</div>
              <div className="text-lg font-semibold text-pass">{t.grades.deep}
                <span className="text-xs text-gray-500 ml-1">{t.scenarios ? Math.round(100 * t.grades.deep / t.scenarios) : 0}%</span></div>
            </div>
            <div className="card-hover p-3 cursor-pointer" title="查看浅断言场景"
              onClick={() => { setFilters(f => ({ ...f, issue: 'shallow', grade: '', suite: '' })); setTab('scenarios'); }}>
              <div className="text-xs text-gray-500 mb-1">浅断言</div>
              <div className="text-lg font-semibold text-warn">{t.grades.shallow}
                <span className="text-xs text-gray-500 ml-1">{t.scenarios ? Math.round(100 * t.grades.shallow / t.scenarios) : 0}%</span></div>
            </div>
            <div className="card-hover p-3 cursor-pointer" title="查看带问题标记的场景"
              onClick={() => { setFilters(EMPTY_FILTERS); setTab('scenarios'); }}>
              <div className="text-xs text-gray-500 mb-1">问题场景</div>
              <div className={`text-lg font-semibold ${t.scenarios_with_issues ? 'text-fail' : 'text-pass'}`}>
                {t.scenarios_with_issues}</div>
            </div>
            <div className="card-hover p-3">
              <div className="text-xs text-gray-500 mb-1">FR 覆盖</div>
              {data.anchors_available ? (
                <Link to="/lifecycle?tab=coverage" className="text-lg font-semibold text-info hover:underline"
                  title="去覆盖缺口页看 FR 明细">
                  {t.anchors_covered}/{t.anchors_total}
                  <span className="text-xs text-gray-500 ml-1">缺口 {t.fr_gaps}</span>
                </Link>
              ) : (
                <div className="text-sm text-gray-500" title="当前工作区无 spec 锚点，FR 覆盖与 covers 失效未评估">未评估</div>
              )}
            </div>
          </div>

          {/* 页签 */}
          <div className="flex gap-1 mb-4">
            {SQ_TABS.map(tb => (
              <button key={tb.id} onClick={() => setTab(tb.id)}
                className={`px-3 py-1.5 text-sm rounded ${tab === tb.id ? 'bg-info text-white' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
                {tb.label}
              </button>
            ))}
          </div>

          {/* 套件视图 */}
          {tab === 'suites' && (
            <div className="bg-surface-2 border border-border rounded-lg overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b border-border">
                    <th className="px-3 py-2">套件</th>
                    <th className="px-3 py-2">spec</th>
                    <th className="px-3 py-2 text-right">场景数</th>
                    <th className="px-3 py-2 text-right">covers 率</th>
                    <th className="px-3 py-2">评级分布（深/中/浅/无）</th>
                    <th className="px-3 py-2 text-right">问题场景</th>
                  </tr>
                </thead>
                <tbody>
                  {data.suites.map(s => (
                    <tr key={s.key} onClick={() => gotoSuite(s.key)}
                      className="border-b border-border/50 hover:bg-surface-3 cursor-pointer"
                      title="点击查看该套件场景明细">
                      <td className="px-3 py-2">
                        <div className="font-medium">{s.feature || s.key}</div>
                        <div className="text-xs text-gray-500">{s.key}</div>
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-400">
                        {s.spec_ref ? `${s.spec_ref}${s.spec_version ? ` @${s.spec_version}` : ''}` : '—'}
                      </td>
                      <td className="px-3 py-2 text-right">{s.scenarios}</td>
                      <td className={`px-3 py-2 text-right ${s.covers_rate < 50 ? 'text-fail' : 'text-pass'}`}>
                        {s.covers_rate}%
                      </td>
                      <td className="px-3 py-2">
                        <span className="text-pass">{s.grades.deep}</span><span className="text-gray-600"> / </span>
                        <span className="text-info">{s.grades.medium}</span><span className="text-gray-600"> / </span>
                        <span className="text-warn">{s.grades.shallow}</span><span className="text-gray-600"> / </span>
                        <span className="text-fail">{s.grades['no-verify']}</span>
                      </td>
                      <td className={`px-3 py-2 text-right ${s.scenarios_with_issues ? 'text-fail' : 'text-pass'}`}>
                        {s.scenarios_with_issues}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 场景明细 */}
          {tab === 'scenarios' && (
            <>
              <div className="flex flex-wrap gap-2 mb-3">
                <select value={filters.suite} onChange={e => setFilters(f => ({ ...f, suite: e.target.value }))}
                  className="input text-sm" title="按套件筛选">
                  <option value="">全部套件</option>
                  {data.suites.map(s => <option key={s.key} value={s.key}>{s.key}</option>)}
                </select>
                <select value={filters.grade} onChange={e => setFilters(f => ({ ...f, grade: e.target.value }))}
                  className="input text-sm" title="按评级筛选">
                  <option value="">全部评级</option>
                  {GRADES.map(g => <option key={g} value={g}>{GRADE_LABEL[g]}</option>)}
                </select>
                <select value={filters.issue} onChange={e => setFilters(f => ({ ...f, issue: e.target.value }))}
                  className="input text-sm" title="按问题类型筛选">
                  <option value="">全部问题</option>
                  {ISSUES.map(i => <option key={i} value={i}>{ISSUE_LABEL[i]}</option>)}
                </select>
                <input value={filters.q} onChange={e => setFilters(f => ({ ...f, q: e.target.value }))}
                  className="input text-sm flex-1 min-w-40" placeholder="搜索场景 ID / 标题…" />
                {(filters.suite || filters.grade || filters.issue || filters.q) && (
                  <button onClick={() => setFilters(EMPTY_FILTERS)} className="btn-ghost text-sm">清空筛选</button>
                )}
              </div>
              <div className="text-xs text-gray-500 mb-2">{filtered.length} / {data.scenarios.length} 个场景</div>
              {filtered.length === 0 ? (
                <div className="py-10 text-center text-gray-500 text-sm">无匹配场景（调整筛选条件试试）</div>
              ) : (
                <div className="bg-surface-2 border border-border rounded-lg overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500 border-b border-border">
                        <th className="px-3 py-2">场景</th>
                        <th className="px-3 py-2">套件</th>
                        <th className="px-3 py-2">covers</th>
                        <th className="px-3 py-2 text-right">断言数</th>
                        <th className="px-3 py-2">评级</th>
                        <th className="px-3 py-2">问题</th>
                        <th className="px-3 py-2 w-8"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map(s => (
                        <ScenarioRow key={s.id} s={s} expanded={expanded.has(s.id)} onToggle={() => toggleExpand(s.id)} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {/* 能力矩阵 */}
          {tab === 'matrix' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <MatrixCard title="步骤类型" data={data.capability_matrix.steps}
                note="flow 步骤类型使用计数（含未走 tool 信封的遗留直写）" />
              <MatrixCard title="Tool 使用" data={data.capability_matrix.tools}
                note="仅统计被场景实际引用的 tool；已注册未使用（如 oss_download/resolve_account）不列出" />
              <MatrixCard title="oracle 断言器" data={data.capability_matrix.oracles}
                note="verify 中 oracle 断言使用计数" />
              <div className="card p-3">
                <div className="text-xs text-gray-500 mb-2">依赖模式（depends_on 声明条数）</div>
                <div className="flex gap-4 text-sm">
                  <span>shared：<b>{data.capability_matrix.depends.shared ?? 0}</b></span>
                  <span>exclusive：<b>{data.capability_matrix.depends.exclusive ?? 0}</b></span>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MatrixCard({ title, data, note }: { title: string; data: Record<string, number>; note: string }) {
  const entries = Object.entries(data);
  return (
    <div className="card p-3">
      <div className="text-xs text-gray-500 mb-2">{title}（{entries.reduce((a, [, v]) => a + v, 0)}）</div>
      {entries.length === 0 ? (
        <div className="text-sm text-gray-500">无使用记录</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {entries.map(([k, v]) => (
            <span key={k} className="px-2 py-0.5 rounded bg-surface-3 text-sm">{k} <b>{v}</b></span>
          ))}
        </div>
      )}
      <div className="text-xs text-gray-600 mt-2">{note}</div>
    </div>
  );
}

function ScenarioRow({ s, expanded, onToggle }: { s: ScenarioQualityRow; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <tr onClick={onToggle} className="border-b border-border/50 hover:bg-surface-3 cursor-pointer">
        <td className="px-3 py-2">
          <div className="font-medium">{s.id}</div>
          <div className="text-xs text-gray-500">{s.title}</div>
        </td>
        <td className="px-3 py-2 text-xs text-gray-400">{s.suite}</td>
        <td className="px-3 py-2">
          {s.covers.length === 0 ? <span className="text-gray-600">—</span> : (
            <span>
              {s.covers.join(' ')}
              {s.invalid_covers.length > 0 && (
                <span className="ml-1 text-fail" title={`锚点表查不到：${s.invalid_covers.join('、')}`}>⚠</span>
              )}
            </span>
          )}
        </td>
        <td className="px-3 py-2 text-right">{s.verify_count}</td>
        <td className="px-3 py-2">
          <span className={`px-2 py-0.5 rounded text-xs ${GRADE_CLS[s.grade]}`}>{GRADE_LABEL[s.grade]}</span>
        </td>
        <td className="px-3 py-2">
          <div className="flex flex-wrap gap-1">
            {s.issues.map(i => (
              <span key={i} className={`px-1.5 py-0.5 rounded text-xs ${ISSUE_CLS[i]}`}>{ISSUE_LABEL[i]}</span>
            ))}
          </div>
        </td>
        <td className="px-3 py-2 text-gray-500">{expanded ? '▾' : '▸'}</td>
      </tr>
      {expanded && (
        <tr className="border-b border-border/50 bg-surface-1">
          <td colSpan={7} className="px-4 py-3 text-xs text-gray-400">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5">
              <div><span className="text-gray-500">路径：</span>{s.path}</div>
              <div><span className="text-gray-500">断言证据：</span>{s.evidence.length ? s.evidence.join('、') : '—'}</div>
              <div><span className="text-gray-500">步骤：</span>{Object.entries(s.steps).map(([k, v]) => `${k}×${v}`).join('、') || '—'}</div>
              <div><span className="text-gray-500">tool：</span>{s.tools.length ? s.tools.join('、') : '—'}</div>
              <div><span className="text-gray-500">oracle：</span>{s.oracles.length ? s.oracles.join('、') : '—'}</div>
              <div><span className="text-gray-500">依赖：</span>{s.depends_on.length ? s.depends_on.map(d => `${d.id}(${d.mode})`).join('、') : '—'}</div>
              <div><span className="text-gray-500">维度：</span>{s.dimensions.length ? s.dimensions.join('、') : '—'}</div>
              <div><span className="text-gray-500">优先级/标签：</span>{s.priority}{s.tags.length ? ` · ${s.tags.join('、')}` : ''}</div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
