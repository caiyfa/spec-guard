/**
 * TrialRunDetailModal — 试跑执行详情弹窗（K-046 增强）
 *
 * 试跑结束后「查看结果」点开：读取 .specguard/reports/{run_id}/ 报告面
 * （run.json + cases/*.json + output.log——与执行记录/归因页同一 API，试跑与
 * 正式执行同一落盘面），完整展示执行过程：步骤轨迹（请求/响应/耗时/trace_id）、
 * 权限预言、DB 校对 SQL 与结果、断言明细、失败归类——不再只有一行错误文字。
 */
import { useEffect, useState } from 'react';
import Modal from './Modal';
import { runsApi } from '../api';
import type { TrialRunResult } from '../api';
import { SqlResultTable } from './SqlResultTable';

// ── 数据结构（engine/execution_record.py 落盘面，宽松可选）──
interface CaseStep {
  type: string;
  request?: Record<string, any>;
  response_status?: number | null;
  duration_ms?: number;
  body_excerpt?: any;
  trace_id?: string;
  response_headers?: Record<string, string>;
  response_body?: any;
  note?: string;
}
interface DbTrace {
  purpose?: string; sql?: string; rows?: number; truncated?: boolean; excerpt?: Record<string, unknown>[];
}
interface OracleTrace { purpose?: string; scope?: string; raw_status?: string; raw_message?: string }
interface AssertionTrace {
  expr?: string; passed?: boolean; actual?: any; expected?: any; message?: string; warnings?: unknown[];
}
interface CaseDetail {
  scenario_id: string;
  title?: string;
  verdict: string;
  duration_ms?: number;
  covers?: string[];
  doc?: { given?: string; when?: string; then?: string; note?: string };
  given?: { account?: string; depends_on?: string[]; file?: string };
  steps?: CaseStep[];
  oracle_traces?: OracleTrace[];
  db_traces?: DbTrace[];
  assertions?: AssertionTrace[];
  failure?: { category?: string; message?: string; evidence?: any };
  skip_reason?: string;
  skip_category?: string;
  upstream_of?: string;
  instance_no?: number;
  dep_mode?: string;
  saved_vars?: Record<string, any>;
}
interface RunCaseBrief {
  id: string; title?: string; verdict: string; duration_ms?: number;
  covers?: string[]; file?: string;
}
interface RunDoc {
  run_id: string; env?: string; system?: string;
  started_at?: string; finished_at?: string;
  stats?: { pass?: number; fail?: number; skip?: number; blocked?: number; total?: number; warnings?: number };
  cases?: RunCaseBrief[];
}

const VERDICT_BADGE: Record<string, string> = {
  PASS: 'bg-pass/12 text-pass',
  FAIL: 'bg-fail/12 text-fail',
  ERROR: 'bg-fail/12 text-fail',
  BLOCKED: 'bg-warn/12 text-warn',
  SKIP: 'bg-warn/12 text-warn',
  DRIFT: 'bg-warn/12 text-warn',
  ORPHANED: 'bg-warn/12 text-warn',
};

const STEP_ICON: Record<string, string> = {
  call: '📡', db_query: '🗄', fetch_permission: '🔑', python: '🐍',
  set_var: '📌', select_emp: '👤', 'poll:done': '⏳', random: '🎲',
  save: '💾', teardown_error: '⚠️',
};
const STEP_LABEL: Record<string, string> = {
  call: '接口调用', db_query: 'DB 查询', fetch_permission: '权限预言',
  python: '脚本', set_var: '设置变量', select_emp: '选人',
  'poll:done': '轮询完成', random: '随机', save: '保存变量', teardown_error: 'teardown 异常',
};

const pretty = (v: unknown): string => {
  if (v == null) return '';
  try { return typeof v === 'string' ? v : JSON.stringify(v, null, 2); } catch { return String(v); }
};

/** 单步轨迹：一行概要 + details 展开请求/响应详情 */
function StepItem({ index, s }: { index: number; s: CaseStep }) {
  const icon = STEP_ICON[s.type] || '⚙️';
  const typeLabel = STEP_LABEL[s.type] || s.type;
  const req = s.request || {};
  const isCall = s.type === 'call' && req.path;
  const desc = isCall
    ? `${req.method || 'GET'} ${req.path}${req.as ? `（${req.as}）` : ''}`
    : (s.note || typeLabel);
  const status = s.response_status ?? 0;
  const statusOk = status >= 200 && status < 300;
  const hasDetail = isCall || s.response_body != null || (s.request && Object.keys(s.request).length > 0);
  return (
    <div className="py-1 border-b border-border/40 last:border-b-0">
      <div className="flex items-center gap-2 text-fs-body leading-relaxed">
        <span className="text-gray-600 font-mono w-4 text-right flex-shrink-0">{index}.</span>
        <span className="flex-shrink-0" title={typeLabel}>{icon}</span>
        <span className="font-mono text-gray-200 flex-1 min-w-0 break-all">{desc}</span>
        {!!status && (
          <span className={`font-mono flex-shrink-0 ${statusOk ? 'text-pass' : 'text-fail'}`}>{status}</span>
        )}
        {!!s.duration_ms && <span className="text-gray-600 flex-shrink-0">{s.duration_ms}ms</span>}
      </div>
      {s.trace_id && (
        <div className="pl-7 text-fs-micro text-gray-600 font-mono truncate" title={s.trace_id}>trace: {s.trace_id}</div>
      )}
      {hasDetail && (
        <details className="pl-7">
          <summary className="cursor-pointer text-fs-micro text-gray-500 hover:text-gray-300 select-none">请求/响应详情</summary>
          <div className="mt-1 space-y-1">
            {Object.keys(req).length > 0 && (
              <div>
                <div className="text-fs-micro text-gray-500">请求</div>
                <pre className="px-2 py-1 rounded text-fs-aux font-mono text-gray-400 whitespace-pre-wrap break-all max-h-40 overflow-y-auto"
                  style={{ background: 'rgb(var(--code-bg))' }}>{pretty(req)}</pre>
              </div>
            )}
            {(s.body_excerpt != null || s.response_body != null) && (
              <div>
                <div className="text-fs-micro text-gray-500">响应</div>
                <pre className="px-2 py-1 rounded text-fs-aux font-mono text-gray-400 whitespace-pre-wrap break-all max-h-40 overflow-y-auto"
                  style={{ background: 'rgb(var(--code-bg))' }}>{pretty(s.body_excerpt ?? s.response_body)}</pre>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

/** 单场景执行卡：失败分析 + 原始内容 + 步骤轨迹 + 权限预言 + DB 校对 + 断言 + 变量 */
function CaseCard({ brief, detail, loading, open, onToggle }: {
  brief: RunCaseBrief; detail: CaseDetail | null; loading: boolean; open: boolean; onToggle: () => void;
}) {
  const steps = detail?.steps || [];
  const dbTraces = detail?.db_traces || [];
  const oracles = detail?.oracle_traces || [];
  const assertions = detail?.assertions || [];
  const savedVars = detail?.saved_vars || {};
  return (
    <div className={`rounded-lg border ${open ? 'border-info/40' : 'border-border'} bg-surface-2/70 overflow-hidden`}>
      <button onClick={onToggle} className="w-full px-2.5 py-2 flex items-center gap-2 text-left hover:bg-surface-3/50">
        <span className={`px-1.5 py-0.5 rounded text-fs-aux font-medium flex-shrink-0 ${VERDICT_BADGE[brief.verdict] || 'bg-surface-3 text-gray-400'}`}>
          {brief.verdict}
        </span>
        <span className="font-mono text-fs-body text-gray-200 flex-shrink-0">{brief.id}</span>
        <span className="text-fs-body text-gray-500 truncate flex-1" title={brief.title || detail?.title || ''}>
          {brief.title || detail?.title || ''}
        </span>
        {!!detail?.upstream_of && (
          <span className="text-fs-micro text-gray-600 flex-shrink-0" title={`作为 ${detail.upstream_of} 的上游执行（${detail.dep_mode || 'shared'}）`}>
            上游
          </span>
        )}
        {!!(detail?.instance_no && detail.instance_no > 1) && (
          <span className="text-fs-micro text-gray-600 flex-shrink-0">#{detail.instance_no}</span>
        )}
        {!!(brief.duration_ms || detail?.duration_ms) && (
          <span className="text-fs-micro text-gray-600 flex-shrink-0">{((brief.duration_ms || detail?.duration_ms || 0) / 1000).toFixed(1)}s</span>
        )}
        <span className="text-gray-500 text-fs-aux flex-shrink-0">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="border-t border-border/60 px-2.5 py-2 space-y-2.5">
          {/* 失败/跳过分析（FAIL 归类 + 原因；SKIP 原因） */}
          {detail?.failure?.message && (
            <div className="rounded bg-fail/12 border border-fail/35 px-2 py-1.5 text-fs-body">
              <div className="text-fail">
                <span className="font-mono text-fs-micro px-1 py-0.5 rounded bg-fail/12 mr-1">{detail.failure.category || 'fail'}</span>
                {detail.failure.message}
              </div>
              {detail.failure.evidence != null && (
                <pre className="mt-1 px-2 py-1 rounded text-fs-aux font-mono text-fail/80 whitespace-pre-wrap break-all max-h-32 overflow-y-auto"
                  style={{ background: 'rgb(var(--code-bg))' }}>{pretty(detail.failure.evidence)}</pre>
              )}
            </div>
          )}
          {!detail?.failure?.message && detail?.skip_reason && (
            <div className="rounded bg-warn/12 border border-warn/35 px-2 py-1.5 text-fs-body text-warn">
              SKIP（{detail.skip_category || 'uncategorized'}）：{detail.skip_reason}
            </div>
          )}

          {/* 原始内容（doc 层给人看） */}
          {(detail?.doc?.given || detail?.doc?.when || detail?.doc?.then) && (
            <div className="text-fs-body space-y-0.5">
              <div className="text-gray-500 text-fs-micro">原始内容</div>
              {detail.doc?.given && <div className="text-gray-400"><span className="text-gray-600">Given </span>{detail.doc.given}</div>}
              {detail.doc?.when && <div className="text-gray-400"><span className="text-gray-600">When </span>{detail.doc.when}</div>}
              {detail.doc?.then && <div className="text-gray-400"><span className="text-gray-600">Then </span>{detail.doc.then}</div>}
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-fs-aux text-gray-600">
                {detail?.given?.account && <span>账号：{detail.given.account}</span>}
                {!!(detail?.covers || []).length && <span>覆盖：{(detail.covers || []).join(', ')}</span>}
              </div>
            </div>
          )}

          {/* 执行过程（步骤轨迹） */}
          {steps.length > 0 && (
            <div>
              <div className="text-gray-500 text-fs-micro mb-0.5">执行过程（{steps.length} 步）</div>
              <div className="rounded border border-border/60 px-2 py-1">
                {steps.map((s, i) => <StepItem key={i} index={i + 1} s={s} />)}
              </div>
            </div>
          )}
          {!detail && loading && <div className="text-fs-body text-gray-600">用例快照加载中…</div>}
          {!detail && !loading && <div className="text-fs-body text-gray-600">用例快照读取失败（cases/{brief.id}.json）</div>}

          {/* 权限预言 */}
          {oracles.length > 0 && (
            <div>
              <div className="text-gray-500 text-fs-micro mb-0.5">权限预言（{oracles.length}）</div>
              <div className="space-y-1">
                {oracles.map((o, i) => (
                  <div key={i} className="rounded border border-border/60 px-2 py-1 text-fs-aux font-mono">
                    <div className="text-gray-300">{o.purpose || 'oracle'}</div>
                    {o.scope && <div className="text-gray-500 break-all">{o.scope}</div>}
                    {o.raw_message && <div className="text-warn/80 break-all">{o.raw_message}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* DB 校对 */}
          {dbTraces.length > 0 && (
            <div>
              <div className="text-gray-500 text-fs-micro mb-0.5">DB 校对（{dbTraces.length}）</div>
              <div className="space-y-2">
                {dbTraces.map((d, i) => (
                  <div key={i} className="rounded border border-border/60 px-2 py-1.5">
                    {d.sql && (
                      <pre className="px-2 py-1 rounded text-fs-aux font-mono text-gray-400 whitespace-pre-wrap break-all max-h-32 overflow-y-auto mb-1"
                        style={{ background: 'rgb(var(--code-bg))' }}>{d.sql}</pre>
                    )}
                    {(d.excerpt || []).length > 0
                      ? <SqlResultTable rows={d.excerpt || []} truncated={d.truncated} row_count={d.rows} />
                      : <div className="text-fs-aux text-gray-600">{d.rows ?? 0} 行（无摘录）</div>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 断言明细 */}
          {assertions.length > 0 && (
            <div>
              <div className="text-gray-500 text-fs-micro mb-0.5">断言（{assertions.length}）</div>
              <div className="space-y-0.5">
                {assertions.map((a, i) => (
                  <div key={i} className="text-fs-body flex items-start gap-1.5">
                    <span className={a.passed ? 'text-pass' : 'text-fail'}>{a.passed ? '✓' : '✗'}</span>
                    <span className="flex-1 min-w-0">
                      <span className="text-gray-300 break-all">{a.expr || 'assert'}</span>
                      {!a.passed && (a.expected != null || a.actual != null) && (
                        <span className="text-gray-500 font-mono text-fs-aux">
                          {' '}期望 {pretty(a.expected)} · 实际 {pretty(a.actual)}
                        </span>
                      )}
                      {a.message && <span className="text-fail/80">（{a.message}）</span>}
                      {!!(a.warnings || []).length && <span className="text-warn/80"> ⚠️ {pretty(a.warnings)}</span>}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 变量快照（save 产出，排查插值用） */}
          {Object.keys(savedVars).length > 0 && (
            <details>
              <summary className="cursor-pointer text-fs-micro text-gray-500 hover:text-gray-300 select-none">💾 变量快照（{Object.keys(savedVars).length} 个）</summary>
              <pre className="mt-1 px-2 py-1 rounded text-fs-aux font-mono text-gray-400 whitespace-pre-wrap break-all max-h-48 overflow-y-auto"
                style={{ background: 'rgb(var(--code-bg))' }}>{pretty(savedVars)}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

export function TrialRunDetailModal({ trial, onClose }: { trial: TrialRunResult; onClose: () => void }) {
  const runId = trial.run_id || '';
  const [run, setRun] = useState<RunDoc | null>(null);
  const [cases, setCases] = useState<Record<string, CaseDetail>>({});
  const [casesLoading, setCasesLoading] = useState(true);  // 快照异步加载中（区分"加载中"与"读取失败"）
  const [log, setLog] = useState('');
  const [logLines, setLogLines] = useState(0);
  const [loadError, setLoadError] = useState('');
  const [openCaseId, setOpenCaseId] = useState('');
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    if (!runId) return;
    let alive = true;
    setRun(null); setCases({}); setCasesLoading(true); setLog(''); setLogLines(0); setLoadError(''); setOpenCaseId('');
    (async () => {
      try {
        const r = await runsApi.get(runId) as unknown as RunDoc;
        if (!alive) return;
        setRun(r);
        // 默认展开第一个非 PASS 用例（全 PASS 展开第一条）
        const briefs = r.cases || [];
        const firstBad = briefs.find(c => c.verdict !== 'PASS');
        setOpenCaseId(firstBad ? firstBad.id : (briefs[0]?.id || ''));
        // 并行拉取全部用例快照（单场景详情 API；失败不阻塞其余）
        const details = await Promise.all(briefs.map(c =>
          runsApi.getCase(runId, c.file || `cases/${c.id}.json`).catch(() => null)));
        if (!alive) return;
        const m: Record<string, CaseDetail> = {};
        briefs.forEach((c, i) => { if (details[i]) m[c.id] = details[i] as CaseDetail; });
        setCases(m);
        setCasesLoading(false);
      } catch (e: any) {
        if (alive) { setLoadError(e?.message || '报告读取失败'); setCasesLoading(false); }
      }
    })();
    runsApi.log(runId, 500).then(r => { if (alive) { setLog(r.log); setLogLines(r.total_lines); } }).catch(() => {});
    return () => { alive = false; };
  }, [runId]);

  const pass = trial.ok;
  const stats = run?.stats;

  return (
    <Modal open onClose={onClose} title={`🔍 试跑执行详情 — ${runId || '（无任务号）'}`} width={920}>
      <div className="p-3 space-y-3 text-fs-lead">
        {/* 概要 */}
        <div className="flex flex-wrap items-center gap-2">
          <span className={`px-2 py-1 rounded text-fs-body font-medium ${pass ? 'bg-pass/12 text-pass' : 'bg-fail/12 text-fail'}`}>
            {pass ? '✓ 试跑通过' : `✗ 试跑${trial.verdict && trial.verdict !== 'FAIL' ? trial.verdict : '失败'}`}
          </span>
          {runId && <span className="font-mono text-fs-body text-gray-400 select-all">{runId}</span>}
          {(trial.env || run?.env) && <span className="text-fs-body text-gray-500 font-mono">@{(trial.env || run?.env) || ''}</span>}
          {run?.system && <span className="text-fs-body text-gray-500 font-mono">{run.system}</span>}
          {run?.started_at && <span className="text-fs-aux text-gray-600 font-mono ml-auto">{run.started_at}{run.finished_at ? ` → ${run.finished_at}` : ''}</span>}
        </div>
        {stats && (
          <div className="flex gap-3 text-fs-body">
            <span className="text-pass">✓ {stats.pass ?? 0}</span>
            {!!stats.fail && <span className="text-fail">✗ {stats.fail}</span>}
            {!!stats.skip && <span className="text-warn">⊘ {stats.skip}</span>}
            {!!stats.blocked && <span className="text-warn">⊗ {stats.blocked}</span>}
            <span className="text-gray-600">/ {stats.total ?? 0} 条记录（含上游准备）</span>
          </div>
        )}
        {!pass && trial.error && (
          <div className="rounded bg-fail/12 border border-fail/35 px-2.5 py-2 text-fs-body text-fail break-all">
            {trial.error}
          </div>
        )}
        {loadError && (
          <div className="rounded bg-fail/12 border border-fail/35 px-2.5 py-2 text-fs-body text-fail">
            报告读取失败：{loadError}（任务号 {runId} 可发给 Agent 排查）
          </div>
        )}

        {/* 用例执行卡列表 */}
        {(run?.cases || []).map(c => (
          <CaseCard
            key={c.id}
            brief={c}
            detail={cases[c.id] || null}
            loading={casesLoading}
            open={openCaseId === c.id}
            onToggle={() => setOpenCaseId(openCaseId === c.id ? '' : c.id)}
          />
        ))}
        {!run && !loadError && <div className="text-center text-gray-600 text-fs-body py-6">报告加载中…</div>}

        {/* 执行日志 */}
        {log && (
          <div className="rounded-lg border border-border overflow-hidden">
            <button onClick={() => setShowLog(!showLog)}
              className="w-full px-2.5 py-2 flex items-center text-fs-body text-gray-400 hover:text-info">
              <span className="font-medium">执行日志（{logLines} 行）</span>
              <span className="ml-auto">{showLog ? '▾ 收起' : '▸ 展开'}</span>
            </button>
            {showLog && (
              <pre className="px-2.5 py-2 text-fs-aux text-gray-400 font-mono max-h-72 overflow-y-auto border-t border-border whitespace-pre-wrap break-all"
                style={{ background: 'rgb(var(--code-bg))' }}>{log}</pre>
            )}
          </div>
        )}

        {trial.report_dir && (
          <div className="text-fs-aux text-gray-600 break-all">报告目录：{trial.report_dir}</div>
        )}
      </div>
    </Modal>
  );
}
