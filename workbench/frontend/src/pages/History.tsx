/** History — 执行记录（K-056：原「历史对比」改版）
 *
 * 按时间倒序展示全部执行情况；点击任务编号展开详情：
 * 触发上下文（trigger.json）+ 单元测试清单（cases）+ 执行日志（output.log）。
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { runsApi, type RunSummary, type FailureEntry } from '../api';
import Attribution from './Attribution';
import Schedules from './Schedules';

interface CaseBrief {
  id: string;
  verdict: string;
  duration_ms?: number;
  // T-310：后端 get_report 从 cases/*.json 聚合的「为什么」（skip_reason / failure.message）
  skip_reason?: string;
  failure?: { category?: string; message?: string };
}

/** T-310：case 行的原因文案（SKIP→skip_reason；FAIL/BLOCKED/ERROR→failure.message） */
function caseReason(c: CaseBrief): string {
  if (c.verdict === 'SKIP' && c.skip_reason) return c.skip_reason;
  if (c.failure?.message) return `${c.failure.category || ''} ${c.failure.message}`.trim();
  return '';
}

const VERDICT_STYLE: Record<string, string> = {
  PASS: 'text-pass', FAIL: 'text-fail', SKIP: 'text-skip', BLOCKED: 'text-blocked', ERROR: 'text-fail',
};

/** 单次执行详情（上下文 + 场景 + 日志） */
function RunDetail({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [context, setContext] = useState<Record<string, unknown> | null>(null);
  const [log, setLog] = useState('');
  const [logTotal, setLogTotal] = useState(0);

  // 「🗄 查 DB 证据」（设计 2026-08-25 §A4 入口②）：读 case 详情提取首个含 sql 的步骤，跳 DB 面板执行
  const lookupDbSql = async (caseId: string) => {
    try {
      const detail = await runsApi.getCase(runId, `cases/${caseId}.json`);
      const steps = (detail?.steps || []) as any[];
      const dbStep = steps.find((s: any) => s.type === 'db_query' || s.sql);
      const sql = dbStep?.sql || '';
      if (!sql) {
        setError('该 case 不含 db_query 步骤（无 SQL 可校对）');
        return;
      }
      navigate(`/db-console?sql=${encodeURIComponent(sql)}`);
    } catch (e: any) {
      setError(e.message || '读取 case 详情失败');
    }
  };
  const [showLog, setShowLog] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setDetail(null); setContext(null); setLog(''); setError('');
    runsApi.get(runId).then((d) => setDetail(d as Record<string, unknown>)).catch((e) => setError(e.message));
    runsApi.context(runId).then((r) => setContext(r.context)).catch(() => {});
    runsApi.log(runId, 800).then((r) => { setLog(r.log); setLogTotal(r.total_lines); })
      .catch(() => setLog('（K-050 之前的运行无 output.log 落盘）'));
  }, [runId]);

  const cases = useMemo(() => ((detail?.cases || []) as CaseBrief[]), [detail]);

  return (
    <div className="space-y-3">
      {error && <div className="text-fs-lead text-fail">❌ {error}</div>}

      {/* 触发上下文 */}
      <div className="bg-surface-2 border border-border rounded-lg p-3">
        <div className="text-fs-body font-medium text-gray-400 mb-2">执行上下文</div>
        {context ? (
          <div className="grid grid-cols-[88px_1fr] gap-y-1.5 gap-x-3 text-fs-body">
            <span className="text-gray-500">环境</span>
            <span className="font-mono text-gray-200">{String(context.env || 'sit')}</span>
            <span className="text-gray-500">选中场景</span>
            <span className="text-gray-200">
              {((context.selected_scenarios || []) as string[]).length > 0
                ? ((context.selected_scenarios || []) as string[]).join('、')
                : String(context.target || '（范围执行）')}
            </span>
            <span className="text-gray-500">执行账号</span>
            <span className="text-gray-200">
              {context.account_override
                ? <span className="text-info">{String(context.account_override)}（执行时选择）</span>
                : '场景声明（default）'}
            </span>
            <span className="text-gray-500">轻量选项</span>
            <span className="text-gray-200">
              {[context.prep_only && '仅准备', context.skip_upstream_verify && '上游不断言',
                context.strict_deps && '严格依赖'].filter(Boolean).join(' · ') || '无'}
            </span>
            <span className="text-gray-500">触发人</span>
            <span className="text-gray-200">{String(context.emp_no || '—')} · 工作区 {String(context.workspace || '—')}</span>
          </div>
        ) : (
          <div className="text-fs-body text-gray-600">（K-053 之前的运行无 trigger.json 上下文）</div>
        )}
      </div>

      {/* 单元测试清单 */}
      <div className="bg-surface-2 border border-border rounded-lg p-3">
        <div className="text-fs-body font-medium text-gray-400 mb-2">单元测试（{cases.length}）</div>
        <div className="space-y-0.5 max-h-48 overflow-y-auto">
          {cases.map((c, i) => (
            <div key={i} className="py-0.5">
              <div className="flex items-center gap-2 text-fs-body">
                <span className={`font-medium w-14 ${VERDICT_STYLE[c.verdict] || 'text-gray-400'}`}>{c.verdict}</span>
                <span className="font-mono text-gray-300">{c.id}</span>
                {['FAIL', 'BLOCKED', 'ERROR'].includes(c.verdict) && (
                  <button type="button"
                    onClick={() => lookupDbSql(c.id)}
                    className="text-fs-aux text-gray-500 hover:text-info ml-2"
                    title="从 case 详情取 db_query SQL，跳 DB 证据面板执行">
                    🗄 查 DB 证据
                  </button>
                )}
                {!!c.duration_ms && <span className="text-gray-600 ml-auto">{(c.duration_ms / 1000).toFixed(1)}s</span>}
              </div>
              {caseReason(c) && (
                <div className="pl-[4.5rem] text-fs-aux text-gray-500 truncate" title={caseReason(c)}>
                  {caseReason(c)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* T-203：断点批次详情（{run_id}-bN 的 case，T-120 归组后的可读面） */}
      {((detail?.batches || []) as { dir: string; cases: CaseBrief[] }[]).map((b) => (
        <div key={b.dir} className="bg-surface-2 border border-border rounded-lg p-3">
          <div className="text-fs-body font-medium text-gray-400 mb-2">批次 {b.dir.replace(/^.*-b/, '#')}（{b.cases.length}）</div>
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {b.cases.map((c, i) => (
              <div key={i} className="py-0.5">
                <div className="flex items-center gap-2 text-fs-body">
                  <span className={`font-medium w-14 ${VERDICT_STYLE[c.verdict] || 'text-gray-400'}`}>{c.verdict}</span>
                  <span className="font-mono text-gray-300">{c.id}</span>
                  {!!c.duration_ms && <span className="text-gray-600 ml-auto">{(c.duration_ms / 1000).toFixed(1)}s</span>}
                </div>
                {caseReason(c) && (
                  <div className="pl-[4.5rem] text-fs-aux text-gray-500 truncate" title={caseReason(c)}>
                    {caseReason(c)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* 执行日志 */}
      <div className="bg-surface-2 border border-border rounded-lg overflow-hidden">
        <button onClick={() => setShowLog(!showLog)}
          className="w-full px-3 py-2 flex items-center text-fs-body text-gray-400 hover:text-info">
          <span className="font-medium">执行日志（{logTotal} 行）</span>
          <span className="ml-auto">{showLog ? '▾ 收起' : '▸ 展开'}</span>
        </button>
        {showLog && (
          <pre className="px-3 py-2 text-fs-body text-gray-400 font-mono max-h-96 overflow-y-auto border-t border-border"
            style={{ background: 'rgb(var(--code-bg))' }}>
            {log || '加载中…'}
          </pre>
        )}
      </div>
    </div>
  );
}

function RunRecords() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [copiedId, setCopiedId] = useState('');
  // T-121：失败索引台账（K-052）——「场景 × 任务号 × 原因」查询 + 一键重试
  const [failures, setFailures] = useState<FailureEntry[]>([]);
  const [failureFilter, setFailureFilter] = useState('');
  const [showFailures, setShowFailures] = useState(false);

  useEffect(() => {
    runsApi.history(50).then((r) => {
      const sorted = [...r].sort((x, y) => String(y.started_at).localeCompare(String(x.started_at)));
      setRuns(sorted);
    });
    runsApi.failures('', 30).then(setFailures).catch(() => {});
  }, []);

  const copyRunId = async (id: string) => {
    try { await navigator.clipboard.writeText(id); } catch { /* */ }
    setCopiedId(id); setTimeout(() => setCopiedId(''), 1500);
  };

  const queryFailures = async (scenarioId: string) => {
    setFailureFilter(scenarioId);
    setFailures(await runsApi.failures(scenarioId, 30).catch(() => []));
  };

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div className="flex items-center gap-3">
        <h2 className="font-display text-fs-title font-semibold">🗂 执行记录</h2>
        <button
          onClick={() => setShowFailures(!showFailures)}
          className={`text-fs-body px-2.5 py-1 rounded border ${
            showFailures ? 'bg-fail/15 border-fail/40 text-fail' : 'bg-surface-2 border-border text-gray-400 hover:text-fail'}`}
          title="按场景查最近失败原因（K-052 失败索引台账）">
          ✗ 失败台账（{failures.length}）
        </button>
      </div>
      <p className="text-fs-body text-gray-500 -mt-2">按时间倒序；点击任务编号展开执行上下文 / 单元测试 / 执行日志。</p>

      {/* T-121：失败索引台账——场景 × 任务号 × 失败原因 + 一键重试 */}
      {showFailures && (
        <div className="border border-fail/25 bg-fail/5 rounded-lg px-3 py-2.5 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-fs-body font-medium text-fail">失败台账（场景 × 任务号 × 原因）</span>
            <input
              value={failureFilter}
              onChange={(e) => queryFailures(e.target.value.trim())}
              placeholder="🔍 按场景 ID 过滤…"
              className="w-44 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body"
            />
            <button onClick={() => queryFailures('')}
              className="text-fs-aux text-gray-500 hover:text-info">清除</button>
            <span className="ml-auto text-fs-aux text-gray-500">{failures.length} 条（最近 30）</span>
          </div>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {failures.length === 0 && <div className="text-fs-body text-gray-600">暂无失败记录</div>}
            {failures.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-fs-body bg-surface-2/60 rounded px-2 py-1">
                <span className="text-fail font-medium w-14">{f.verdict}</span>
                <span className="font-mono text-gray-300">{f.scenario_id}</span>
                <span className="text-gray-500 font-mono text-fs-aux">{f.run_id}</span>
                <span className="text-gray-600 truncate flex-1" title={f.message}>{f.category || '—'} · {f.message.slice(0, 60)}</span>
                <span className="text-gray-600 text-fs-aux font-mono">{f.finished_at}</span>
                <button
                  onClick={() => window.location.href = `/run?ids=${f.scenario_id}`}
                  className="text-info hover:underline flex-shrink-0"
                  title={`重试 ${f.scenario_id}（跳执行控制预选）`}>↻ 重试</button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
        {runs.length === 0 && <div className="text-center text-gray-600 text-fs-lead py-10">暂无执行记录</div>}
        {runs.map((r) => {
          const open = selected === r.run_id;
          const total = r.stats.total || (r.stats.pass + r.stats.fail + r.stats.skip + r.stats.blocked);
          return (
            <div key={r.run_id} className={`border rounded-lg overflow-hidden ${open ? 'border-info/50' : 'border-border'}`}>
              <button
                onClick={() => setSelected(open ? '' : r.run_id)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                  open ? 'bg-info/10' : 'bg-surface-2 hover:bg-surface-3'}`}
              >
                <span className="font-mono text-fs-lead text-info">{r.run_id}</span>
                <span
                  onClick={(e) => { e.stopPropagation(); copyRunId(r.run_id); }}
                  className="text-gray-500 hover:text-info text-fs-body cursor-pointer"
                  title="复制任务编号">
                  {copiedId === r.run_id ? <span className="text-pass">✓</span> : '📋'}
                </span>
                <span className="text-fs-body text-gray-500 font-mono">{r.env}</span>
                <span className="flex gap-2 text-fs-body ml-2">
                  <span className="text-pass">✓{r.stats.pass}</span>
                  {r.stats.fail > 0 && <span className="text-fail">✗{r.stats.fail}</span>}
                  {r.stats.skip > 0 && <span className="text-skip">⊘{r.stats.skip}</span>}
                  {r.stats.blocked > 0 && <span className="text-blocked">⊗{r.stats.blocked}</span>}
                  <span className="text-gray-600">/{total}</span>
                </span>
                <span className="text-fs-body text-gray-600 ml-auto font-mono">{String(r.started_at || '')}</span>
                <span className="text-gray-500 text-fs-body">{open ? '▾' : '▸'}</span>
              </button>
              {open && (
                <div className="border-t border-border p-3 bg-surface-1">
                  <RunDetail runId={r.run_id} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── T-996：执行中心三 tab（执行记录 + 失败归因 + 定时任务），?tab= 深链 + localStorage 记忆 ──
const EXEC_TABS = [
  { id: 'records', label: '📜 执行记录' },
  { id: 'attribution', label: '🧭 失败归因' },
  { id: 'schedules', label: '⏰ 定时任务' },
] as const;
type ExecTab = typeof EXEC_TABS[number]['id'];

export default function History() {
  const [tab, setTab] = useState<ExecTab>(() => {
    const q = new URLSearchParams(window.location.search).get('tab');
    const saved = localStorage.getItem('sg_exec_tab');
    const valid = (v: string | null): v is ExecTab => EXEC_TABS.some(t => t.id === v);
    if (valid(q)) return q;
    if (valid(saved)) return saved;
    return 'records';
  });
  useEffect(() => { localStorage.setItem('sg_exec_tab', tab); }, [tab]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 mb-4 flex-shrink-0">
        {EXEC_TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-fs-lead rounded ${tab === t.id ? 'bg-info text-white' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'records' && <RunRecords />}
        {tab === 'attribution' && <Attribution />}
        {tab === 'schedules' && <Schedules />}
      </div>
    </div>
  );
}
