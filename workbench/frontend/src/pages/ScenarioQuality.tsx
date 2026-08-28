// T-1035：测试用例管理——用例库全景：需求关联 / 断言深度 / 待完善项一屏可见，不用翻 YAML。
// 评级与问题标记口径唯一事实源在后端 services/scenario_quality.py，本页只渲染。
// 行点击开详情弹层（结构化查看/编辑 + 试跑，见 scenarioQuality/ScenarioDetailModal）。
// 三态分离 + tab 与筛选条件 localStorage 记忆（体验基线①③）+ 单点刷新（④）。

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { scenarioQualityApi } from '../api';
import type { QualityGrade, QualityOverview, ParallelSafety, ShapeContract } from '../api';
import { GRADE_CLS, GRADE_LABEL, ISSUE_CLS, ISSUE_LABEL } from './scenarioQuality/labels';
import ScenarioDetailModal from './scenarioQuality/ScenarioDetailModal';

const GRADES: QualityGrade[] = ['deep', 'medium', 'shallow', 'no-verify'];
const ISSUES = ['missing-covers', 'invalid-covers', 'shallow', 'no-verify', 'probe'];

const SQ_TABS = [
  { id: 'suites', label: '🗂 套件视图' },
  { id: 'scenarios', label: '📄 用例明细' },
  { id: 'shape', label: '🔗 形状契约' },
  { id: 'parallel', label: '🚦 并行安全' },
] as const;
type SqTab = typeof SQ_TABS[number]['id'];

const FINDING_TYPE_LABEL: Record<string, string> = {
  'unresolved-ref': '引用路径未出现过',
  'removed-path': '路径消失（漂移）',
  'added-paths': '新增字段',
};

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

interface Props {
  role?: string;   // App.tsx 注入（SystemConfig 同款）；编辑/试跑仅 admin/tester（与后端 RBAC 一致）
}

export default function ScenarioQuality({ role }: Props) {
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
  const [detailId, setDetailId] = useState<string | null>(null);
  const [shapeData, setShapeData] = useState<ShapeContract | null>(null);
  const [shapeError, setShapeError] = useState('');
  const [parallelData, setParallelData] = useState<ParallelSafety | null>(null);
  const [parallelError, setParallelError] = useState('');

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

  // 形状契约/并行安全：首次进入页签时懒加载（各自 60s 后端缓存，refresh 走按钮）
  const loadShape = useCallback(async (force = false) => {
    setShapeError('');
    try { setShapeData(await scenarioQualityApi.shapeContract(force)); }
    catch (e: any) { setShapeError(e.message || '加载失败'); }
  }, []);
  const loadParallel = useCallback(async (force = false) => {
    setParallelError('');
    try { setParallelData(await scenarioQualityApi.parallelSafety(force)); }
    catch (e: any) { setParallelError(e.message || '加载失败'); }
  }, []);
  useEffect(() => { if (tab === 'shape' && !shapeData && !shapeError) loadShape(); },
    [tab, shapeData, shapeError, loadShape]);
  useEffect(() => { if (tab === 'parallel' && !parallelData && !parallelError) loadParallel(); },
    [tab, parallelData, parallelError, loadParallel]);

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

  const detailRow = useMemo(
    () => (detailId && data ? data.scenarios.find(s => s.id === detailId) || null : null),
    [detailId, data]);

  const gotoSuite = (key: string) => {
    setFilters(f => ({ ...f, suite: key }));
    setTab('scenarios');
  };
  const gotoIssue = (issue: string) => {
    setFilters({ ...EMPTY_FILTERS, issue });
    setTab('scenarios');
  };

  const canRun = role === 'admin' || role === 'tester';
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
                        <th className="px-3 py-2 w-10"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map(s => (
                        <tr key={s.id} onClick={() => setDetailId(s.id)}
                          className="border-b border-border/50 hover:bg-surface-3 cursor-pointer"
                          title="点击打开详情（结构化查看/编辑/试跑）">
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
                          <td className="px-3 py-2 text-gray-500 text-xs">详情 ›</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
          {/* 形状契约（T-1037） */}
          {tab === 'shape' && (
            <>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs text-gray-500">
                  {shapeData
                    ? `形状基线来自最近 ${shapeData.n_runs} 个执行 run（response_body 落盘面派生）· 口径：新增字段放行（INFO）；被引用路径消失才报警；引用路径从未出现=疑似幻觉路径`
                    : '按 API 聚合的响应形状事实与消费方引用完整性'}
                </p>
                <button className="btn-ghost text-xs" onClick={() => loadShape(true)}>🔄 重扫</button>
              </div>
              {shapeError && (
                <div className="mb-3 p-3 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
                  ❌ 形状契约分析失败：{shapeError}
                  <button className="ml-3 underline" onClick={() => loadShape(true)}>重试</button>
                </div>
              )}
              {!shapeData && !shapeError && (
                <div className="py-10 text-center text-gray-500 text-sm">加载中…</div>
              )}
              {shapeData && shapeData.findings.length > 0 && (
                <div className="mb-4 bg-surface-2 border border-border rounded-lg overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500 border-b border-border">
                        <th className="px-3 py-2">级别</th>
                        <th className="px-3 py-2">类型</th>
                        <th className="px-3 py-2">API</th>
                        <th className="px-3 py-2">说明</th>
                        <th className="px-3 py-2">消费方</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shapeData.findings.map((f, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="px-3 py-2">
                            <span className={`px-1.5 py-0.5 rounded text-xs ${f.level === 'WARN' ? 'bg-red-900/40 text-red-400' : 'bg-surface-3 text-gray-400'}`}>
                              {f.level}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-xs">{FINDING_TYPE_LABEL[f.type] || f.type}</td>
                          <td className="px-3 py-2 text-xs font-mono">{f.api}</td>
                          <td className="px-3 py-2 text-xs text-gray-300">{f.message}</td>
                          <td className="px-3 py-2 text-xs text-gray-500">{f.consumers?.join('、') || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {shapeData && shapeData.findings.length === 0 && (
                <div className="mb-4 text-sm text-pass">✅ 未发现形状契约问题（引用完整、无被引用路径漂移）</div>
              )}
              {shapeData && (
                <div className="bg-surface-2 border border-border rounded-lg overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500 border-b border-border">
                        <th className="px-3 py-2">API（METHOD path）</th>
                        <th className="px-3 py-2 text-right">样本 run</th>
                        <th className="px-3 py-2 text-right">字段数</th>
                        <th className="px-3 py-2 text-right">被引用路径</th>
                        <th className="px-3 py-2">重要性</th>
                        <th className="px-3 py-2">所属场景</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shapeData.apis.map(a => (
                        <tr key={a.api} className="border-b border-border/50">
                          <td className="px-3 py-2 font-mono text-xs">{a.api}</td>
                          <td className="px-3 py-2 text-right">{a.runs}</td>
                          <td className="px-3 py-2 text-right">{a.fields}</td>
                          <td className="px-3 py-2 text-right">{a.refs}</td>
                          <td className="px-3 py-2">
                            {a.importance >= 3 ? <span className="text-fail">●●●</span>
                              : a.importance === 2 ? <span className="text-warn">●●</span>
                              : a.importance === 1 ? <span className="text-info">●</span>
                              : <span className="text-gray-600">○</span>}
                            <span className="text-xs text-gray-500 ml-1">{a.category}</span>
                          </td>
                          <td className="px-3 py-2 text-xs text-gray-500">{a.owner_scenarios.join('、') || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {/* 并行安全（T-1038） */}
          {tab === 'parallel' && (
            <>
              <p className="text-xs text-gray-500 mb-2">
                当前调度仍为串行——本页是 V3 并行执行（T-802）的静态前置判定：
                读-读并行安全、沾写全局互斥（保守模型，produces/consumes 落地后按资源粒度细化）。
              </p>
              {parallelError && (
                <div className="mb-3 p-3 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
                  ❌ 并行安全分析失败：{parallelError}
                  <button className="ml-3 underline" onClick={() => loadParallel(true)}>重试</button>
                </div>
              )}
              {!parallelData && !parallelError && (
                <div className="py-10 text-center text-gray-500 text-sm">加载中…</div>
              )}
              {parallelData && (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                    <div className="card-hover p-3">
                      <div className="text-xs text-gray-500 mb-1">读场景（可全并行）</div>
                      <div className="text-lg font-semibold text-pass">{parallelData.totals.readers}</div>
                    </div>
                    <div className="card-hover p-3">
                      <div className="text-xs text-gray-500 mb-1">写场景（全局互斥）</div>
                      <div className="text-lg font-semibold text-warn">{parallelData.totals.writers}</div>
                    </div>
                    <div className="card-hover p-3">
                      <div className="text-xs text-gray-500 mb-1">最大理论并行度</div>
                      <div className="text-lg font-semibold text-info">{parallelData.totals.max_parallelism}</div>
                    </div>
                    <div className="card-hover p-3">
                      <div className="text-xs text-gray-500 mb-1">判定模型</div>
                      <div className="text-xs text-gray-400">{parallelData.totals.model}</div>
                    </div>
                  </div>
                  <div className="bg-surface-2 border border-border rounded-lg overflow-x-auto mb-4">
                    <div className="px-3 py-2 text-xs text-gray-500 border-b border-border">串行瓶颈（写场景，按被依赖数排序）</div>
                    <table className="w-full text-sm">
                      <tbody>
                        {parallelData.writers.map(w => (
                          <tr key={w.id} className="border-b border-border/50">
                            <td className="px-3 py-2 font-medium">{w.id}<span className="text-xs text-gray-500 ml-2">{w.title}</span></td>
                            <td className="px-3 py-2 text-xs text-gray-400">{w.category}</td>
                            <td className="px-3 py-2 text-xs text-gray-400">被依赖 {w.dependents}</td>
                            <td className="px-3 py-2 text-xs text-gray-400">{w.priority}</td>
                            <td className="px-3 py-2 text-xs text-gray-500">账号：{w.accounts.join('、') || '—'}</td>
                          </tr>
                        ))}
                        {parallelData.writers.length === 0 && (
                          <tr><td className="px-3 py-3 text-sm text-pass">无写场景——全库读-读可并行</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  <div className="bg-surface-2 border border-border rounded-lg overflow-x-auto">
                    <div className="px-3 py-2 text-xs text-gray-500 border-b border-border">读层（两两可并行，{parallelData.readers.length} 个）</div>
                    <table className="w-full text-sm">
                      <tbody>
                        {parallelData.readers.slice(0, 30).map(r => (
                          <tr key={r.id} className="border-b border-border/50">
                            <td className="px-3 py-2 font-medium">{r.id}<span className="text-xs text-gray-500 ml-2">{r.title}</span></td>
                            <td className="px-3 py-2 text-xs text-gray-400">{r.category}</td>
                            <td className="px-3 py-2 text-xs text-gray-500">账号：{r.accounts.join('、') || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {parallelData.readers.length > 30 && (
                      <div className="px-3 py-2 text-xs text-gray-600">…其余 {parallelData.readers.length - 30} 个略</div>
                    )}
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}

      {/* 用例详情弹层（结构化查看/编辑 + 试跑） */}
      {detailRow && (
        <ScenarioDetailModal
          row={detailRow}
          scenarios={data?.scenarios || []}
          anchorsAvailable={data.anchors_available}
          invalidCoversCount={t.issues['invalid-covers'] || 0}
          canRun={canRun}
          onClose={() => setDetailId(null)}
          onSaved={() => refresh(true)}
        />
      )}
    </div>
  );
}
