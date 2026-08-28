// T-1035：测试用例管理（只读）——用例库全景：需求关联 / 断言深度 / 待完善项一屏可见，不用翻 YAML。
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
  'missing-covers': '缺关联需求', 'invalid-covers': '需求锚点失效',
  shallow: '浅断言', 'no-verify': '无断言', probe: '探针',
};
const ISSUE_CLS: Record<string, string> = {
  'missing-covers': 'bg-yellow-900/40 text-yellow-400',
  'invalid-covers': 'bg-red-900/40 text-red-400',
  shallow: 'bg-yellow-900/40 text-yellow-400',
  'no-verify': 'bg-red-900/40 text-red-400',
  probe: 'bg-red-900/40 text-red-400',
};
// 断言证据：后端从断言内容确定性提取的特征（评级的输入），此处翻译为人话
const EVIDENCE_LABEL: Record<string, string> = {
  http_ok: '成功状态', http_error: '显式拒绝', body_error_code: '错误码',
  error_message: '错误消息', absent: '不泄露', json_field: '响应字段',
  oracle: 'DB 校对断言器', db_proof: '持久层证据', python: 'Python 脚本',
};

const SQ_TABS = [
  { id: 'suites', label: '🗂 套件视图' },
  { id: 'scenarios', label: '📄 用例明细' },
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
  const gotoIssue = (issue: string) => {
    setFilters({ ...EMPTY_FILTERS, issue });
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
        <h1 className="text-xl font-bold">📋 测试用例管理</h1>
        <button onClick={() => refresh(true)} disabled={loading}
          className="btn-ghost text-sm" title="强制重扫用例库（绕过 30s 缓存）">
          {loading ? '扫描中…' : '🔄 刷新'}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        {data
          ? `扫描于 ${data.generated_at} · ${data.root} · 评级口径：深=oracle/DB校对/python 或 db_query；浅=仅状态+字段存在性断言且≤3条；无=verify 为空`
          : '需求关联 / 断言深度 / 待完善项一屏可见'}
      </p>

      {/* 三态：错误横幅 */}
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
          ❌ 加载用例库失败：{error}
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
          用例库为空（未扫描到场景 YAML）——库根目录：{data.root}
        </div>
      )}

      {!error && data && t && t.scenarios > 0 && (
        <>
          {/* 统计卡 */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-4">
            <div className="card-hover p-3">
              <div className="text-xs text-gray-500 mb-1">用例总数</div>
              <div className="text-lg font-semibold">{t.scenarios}<span className="text-xs text-gray-500 ml-1">/ {t.suites} 套件</span></div>
            </div>
            <div className="card-hover p-3 cursor-pointer" title="查看未关联需求的用例"
              onClick={() => gotoIssue('missing-covers')}>
              <div className="text-xs text-gray-500 mb-1">需求关联率</div>
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
            <div className="card-hover p-3 cursor-pointer" title="查看浅断言用例"
              onClick={() => gotoIssue('shallow')}>
              <div className="text-xs text-gray-500 mb-1">浅断言</div>
              <div className="text-lg font-semibold text-warn">{t.grades.shallow}
                <span className="text-xs text-gray-500 ml-1">{t.scenarios ? Math.round(100 * t.grades.shallow / t.scenarios) : 0}%</span></div>
            </div>
            <div className="card-hover p-3 cursor-pointer" title="查看带待完善标记的用例"
              onClick={() => { setFilters(EMPTY_FILTERS); setTab('scenarios'); }}>
              <div className="text-xs text-gray-500 mb-1">待完善用例</div>
              <div className={`text-lg font-semibold ${t.scenarios_with_issues ? 'text-fail' : 'text-pass'}`}>
                {t.scenarios_with_issues}</div>
            </div>
            <div className="card-hover p-3">
              <div className="text-xs text-gray-500 mb-1">需求覆盖</div>
              {data.anchors_available ? (
                <Link to="/lifecycle?tab=coverage" className="text-lg font-semibold text-info hover:underline"
                  title="去覆盖缺口页看需求明细">
                  {t.anchors_covered}/{t.anchors_total}
                  <span className="text-xs text-gray-500 ml-1">缺口 {t.fr_gaps}</span>
                </Link>
              ) : (
                <div className="text-sm text-gray-500" title="当前工作区无 spec 锚点，需求覆盖与锚点失效未评估">未评估</div>
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
                    <th className="px-3 py-2">关联 spec</th>
                    <th className="px-3 py-2 text-right">用例数</th>
                    <th className="px-3 py-2 text-right">需求关联率</th>
                    <th className="px-3 py-2">断言分布（深/中/浅/无）</th>
                    <th className="px-3 py-2 text-right">待完善</th>
                  </tr>
                </thead>
                <tbody>
                  {data.suites.map(s => (
                    <tr key={s.key} onClick={() => gotoSuite(s.key)}
                      className="border-b border-border/50 hover:bg-surface-3 cursor-pointer"
                      title="点击查看该套件用例明细">
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

          {/* 用例明细 */}
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
                  className="input text-sm" title="按待完善类型筛选">
                  <option value="">全部问题</option>
                  {ISSUES.map(i => <option key={i} value={i}>{ISSUE_LABEL[i]}</option>)}
                </select>
                <input value={filters.q} onChange={e => setFilters(f => ({ ...f, q: e.target.value }))}
                  className="input text-sm flex-1 min-w-40" placeholder="搜索用例 ID / 标题…" />
                {(filters.suite || filters.grade || filters.issue || filters.q) && (
                  <button onClick={() => setFilters(EMPTY_FILTERS)} className="btn-ghost text-sm">清空筛选</button>
                )}
              </div>
              <div className="text-xs text-gray-500 mb-2">{filtered.length} / {data.scenarios.length} 个用例</div>
              {filtered.length === 0 ? (
                <div className="py-10 text-center text-gray-500 text-sm">无匹配用例（调整筛选条件试试）</div>
              ) : (
                <div className="bg-surface-2 border border-border rounded-lg overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500 border-b border-border">
                        <th className="px-3 py-2">用例</th>
                        <th className="px-3 py-2">套件</th>
                        <th className="px-3 py-2">关联需求</th>
                        <th className="px-3 py-2 text-right">断言数</th>
                        <th className="px-3 py-2">评级</th>
                        <th className="px-3 py-2">待完善</th>
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
        </>
      )}
    </div>
  );
}

function ScenarioRow({ s, expanded, onToggle }: { s: ScenarioQualityRow; expanded: boolean; onToggle: () => void }) {
  const hasDoc = s.doc_summary.given || s.doc_summary.when || s.doc_summary.then;
  return (
    <>
      <tr onClick={onToggle} className="border-b border-border/50 hover:bg-surface-3 cursor-pointer">
        <td className="px-3 py-2">
          <div className="font-medium">{s.id}</div>
          <div className="text-xs text-gray-500">{s.title}</div>
        </td>
        <td className="px-3 py-2 text-xs text-gray-400">{s.suite}</td>
        <td className="px-3 py-2">
          {s.covers_detail.length === 0 ? <span className="text-gray-600">—</span> : (
            <div className="flex flex-wrap gap-1">
              {s.covers_detail.map(c => (
                <span key={c.fr}
                  title={c.valid
                    ? `${c.fr}：${c.title || '（无标题）'}${c.module ? `（${c.module}）` : ''}`
                    : `${c.fr}：当前工作区锚点表查不到（spec 世代/编号体系可能不匹配）`}
                  className={`px-1.5 py-0.5 rounded text-xs ${c.valid ? 'bg-surface-3' : 'bg-red-900/40 text-red-400'}`}>
                  {c.fr}{!c.valid && ' ⚠'}
                </span>
              ))}
            </div>
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
          <td colSpan={7} className="px-4 py-3 text-xs text-gray-300">
            <div className="space-y-2.5">
              {hasDoc && (
                <div>
                  <div className="text-gray-500">业务语义</div>
                  {s.doc_summary.given && <div className="mt-0.5">· 给定：{s.doc_summary.given}</div>}
                  {s.doc_summary.when && <div className="mt-0.5">· 操作：{s.doc_summary.when}</div>}
                  {s.doc_summary.then && <div className="mt-0.5">· 预期：{s.doc_summary.then}</div>}
                </div>
              )}
              <div>
                <div className="text-gray-500">执行步骤（{s.flow_summary.length}）</div>
                {s.flow_summary.map((l, i) => <div key={i} className="mt-0.5">{i + 1}. {l}</div>)}
              </div>
              <div>
                <div className="text-gray-500">验证断言（{s.verify_summary.length}）</div>
                {s.verify_summary.length > 0
                  ? s.verify_summary.map((l, i) => <div key={i} className="mt-0.5">· {l}</div>)
                  : <div className="mt-0.5 text-fail">无断言——探针/半成品用例</div>}
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-gray-500">断言证据（评级的确定性输入）：</span>
                {s.evidence.length === 0 ? <span className="text-gray-600">无</span> : s.evidence.map(e => (
                  <span key={e} className="px-1.5 py-0.5 rounded bg-surface-3"
                    title={`证据特征 ${e}`}>{EVIDENCE_LABEL[e] || e}</span>
                ))}
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-gray-400">
                <span><span className="text-gray-500">依赖：</span>{s.depends_on.length ? s.depends_on.map(d => `${d.id}(${d.mode})`).join('、') : '—'}</span>
                <span><span className="text-gray-500">tool：</span>{s.tools.length ? s.tools.join('、') : '—'}</span>
                <span><span className="text-gray-500">oracle：</span>{s.oracles.length ? s.oracles.join('、') : '—'}</span>
                <span><span className="text-gray-500">测试维度：</span>{s.dimensions.length ? s.dimensions.join('、') : '—'}</span>
                <span><span className="text-gray-500">优先级：</span>{s.priority}</span>
                <span><span className="text-gray-500">文件：</span>{s.path}</span>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
