/** History — 执行记录（K-056：原「历史对比」改版）
 *
 * 按时间倒序展示全部执行情况；点击任务编号展开详情：
 * 触发上下文（trigger.json）+ 单元测试清单（cases）+ 执行日志（output.log）。
 */
import { useEffect, useMemo, useState } from 'react';
import { runsApi, type RunSummary } from '../api';

interface CaseBrief {
  id: string;
  verdict: string;
  duration_ms?: number;
}

const VERDICT_STYLE: Record<string, string> = {
  PASS: 'text-pass', FAIL: 'text-fail', SKIP: 'text-skip', BLOCKED: 'text-blocked', ERROR: 'text-fail',
};

/** 单次执行详情（上下文 + 场景 + 日志） */
function RunDetail({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [context, setContext] = useState<Record<string, unknown> | null>(null);
  const [log, setLog] = useState('');
  const [logTotal, setLogTotal] = useState(0);
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
      {error && <div className="text-sm text-fail">❌ {error}</div>}

      {/* 触发上下文 */}
      <div className="bg-surface-2 border border-border rounded-lg p-3">
        <div className="text-xs font-medium text-gray-400 mb-2">执行上下文</div>
        {context ? (
          <div className="grid grid-cols-[88px_1fr] gap-y-1.5 gap-x-3 text-xs">
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
          <div className="text-xs text-gray-600">（K-053 之前的运行无 trigger.json 上下文）</div>
        )}
      </div>

      {/* 单元测试清单 */}
      <div className="bg-surface-2 border border-border rounded-lg p-3">
        <div className="text-xs font-medium text-gray-400 mb-2">单元测试（{cases.length}）</div>
        <div className="space-y-0.5 max-h-48 overflow-y-auto">
          {cases.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className={`font-medium w-14 ${VERDICT_STYLE[c.verdict] || 'text-gray-400'}`}>{c.verdict}</span>
              <span className="font-mono text-gray-300">{c.id}</span>
              {!!c.duration_ms && <span className="text-gray-600 ml-auto">{(c.duration_ms / 1000).toFixed(1)}s</span>}
            </div>
          ))}
        </div>
      </div>

      {/* 执行日志 */}
      <div className="bg-surface-2 border border-border rounded-lg overflow-hidden">
        <button onClick={() => setShowLog(!showLog)}
          className="w-full px-3 py-2 flex items-center text-xs text-gray-400 hover:text-info">
          <span className="font-medium">执行日志（{logTotal} 行）</span>
          <span className="ml-auto">{showLog ? '▾ 收起' : '▸ 展开'}</span>
        </button>
        {showLog && (
          <pre className="px-3 py-2 text-[11px] text-gray-400 font-mono max-h-96 overflow-y-auto border-t border-border"
            style={{ background: 'rgb(var(--code-bg))' }}>
            {log || '加载中…'}
          </pre>
        )}
      </div>
    </div>
  );
}

export default function History() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [copiedId, setCopiedId] = useState('');

  useEffect(() => {
    runsApi.history(50).then((r) => {
      const sorted = [...r].sort((x, y) => String(y.started_at).localeCompare(String(x.started_at)));
      setRuns(sorted);
    });
  }, []);

  const copyRunId = async (id: string) => {
    try { await navigator.clipboard.writeText(id); } catch { /* */ }
    setCopiedId(id); setTimeout(() => setCopiedId(''), 1500);
  };

  return (
    <div className="space-y-4 h-full flex flex-col">
      <h2 className="text-lg font-semibold">🗂 执行记录</h2>
      <p className="text-xs text-gray-500 -mt-2">按时间倒序；点击任务编号展开执行上下文 / 单元测试 / 执行日志。</p>

      <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
        {runs.length === 0 && <div className="text-center text-gray-600 text-sm py-10">暂无执行记录</div>}
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
                <span className="font-mono text-sm text-info">{r.run_id}</span>
                <span
                  onClick={(e) => { e.stopPropagation(); copyRunId(r.run_id); }}
                  className="text-gray-500 hover:text-info text-xs cursor-pointer"
                  title="复制任务编号">
                  {copiedId === r.run_id ? <span className="text-pass">✓</span> : '📋'}
                </span>
                <span className="text-xs text-gray-500 font-mono">{r.env}</span>
                <span className="flex gap-2 text-xs ml-2">
                  <span className="text-pass">✓{r.stats.pass}</span>
                  {r.stats.fail > 0 && <span className="text-fail">✗{r.stats.fail}</span>}
                  {r.stats.skip > 0 && <span className="text-skip">⊘{r.stats.skip}</span>}
                  {r.stats.blocked > 0 && <span className="text-blocked">⊗{r.stats.blocked}</span>}
                  <span className="text-gray-600">/{total}</span>
                </span>
                <span className="text-[11px] text-gray-600 ml-auto font-mono">{String(r.started_at || '')}</span>
                <span className="text-gray-500 text-xs">{open ? '▾' : '▸'}</span>
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
