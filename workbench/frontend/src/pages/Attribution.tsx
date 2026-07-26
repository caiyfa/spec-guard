// 失败归因页：读取运行报告，展示失败场景 + 断言差异 + 归因分类

import { useState, useEffect } from 'react';

const BASE = '/api';

interface FailedCase {
  scenario_id: string;
  verdict: string;
  error: string;
  assertions: any[];
  steps: any[];
}

interface RunReport {
  run_id: string;
  env: string;
  stats: any;
  total_cases: number;
  failed_cases: FailedCase[];
  report_md_preview: string;
}

export default function Attribution() {
  const [runId, setRunId] = useState('');
  const [report, setReport] = useState<RunReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<any[]>([]);

  useEffect(() => {
    fetch(`${BASE}/runs/history?limit=10`)
      .then(r => r.json())
      .then(data => setHistory(data.reports || data || []))
      .catch(() => {});
  }, []);

  const loadReport = async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError('');
    setReport(null);
    try {
      const res = await fetch(`${BASE}/runs/${id}`);
      if (!res.ok) throw new Error('运行报告不存在');
      const data = await res.json();
      // 也获取 cases 详情
      const casesRes = await fetch(`${BASE}/runs/${id}/cases/.json`).catch(() => null);
      let failedCases: FailedCase[] = [];
      if (casesRes && casesRes.ok) {
        const casesData = await casesRes.json();
        if (casesData.cases) {
          failedCases = casesData.cases.filter((c: any) =>
            ['FAIL', 'ERROR', 'BLOCKED'].includes(c.verdict)
          );
        }
      }
      setReport({
        run_id: id,
        env: data.env || '',
        stats: data.stats || {},
        total_cases: data.stats?.total || 0,
        failed_cases: failedCases,
        report_md_preview: '',
      });
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const categorize = (verdict: string) => {
    const categories: Record<string, { label: string; color: string }> = {
      FAIL: { label: '场景缺陷', color: 'text-red-400' },
      ERROR: { label: '环境异常', color: 'text-yellow-400' },
      BLOCKED: { label: '上游阻塞', color: 'text-orange-400' },
    };
    return categories[verdict] || { label: verdict, color: 'text-gray-400' };
  };

  return (
    <div className="flex flex-col h-full">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">🔍 失败归因</h2>
        <p className="text-xs text-gray-500 mt-1">读取运行报告，分析失败场景的断言差异与根因分类</p>
      </div>

      {/* 运行选择 */}
      <div className="flex gap-2 mb-4">
        <input
          value={runId}
          onChange={e => setRunId(e.target.value)}
          placeholder="运行 ID（如 2026-07-22_133056）"
          className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none"
          onKeyDown={e => e.key === 'Enter' && loadReport(runId)}
        />
        <button
          onClick={() => loadReport(runId)}
          disabled={loading || !runId}
          className="px-4 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40"
        >
          {loading ? '...' : '分析'}
        </button>
      </div>

      {/* 历史运行列表 */}
      {history.length > 0 && !report && (
        <div className="mb-4">
          <div className="text-xs text-gray-500 mb-2">最近运行</div>
          <div className="flex flex-wrap gap-2">
            {history.map((h: any) => (
              <button
                key={h.run_id}
                onClick={() => { setRunId(h.run_id); loadReport(h.run_id); }}
                className="px-2 py-1 bg-surface-2 border border-border rounded text-xs text-gray-400 hover:text-info hover:border-info"
              >
                {h.run_id}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-3">
          <span className="text-red-400 text-sm">❌ {error}</span>
        </div>
      )}

      {/* 归因报告 */}
      {report && (
        <div className="flex-1 overflow-y-auto space-y-3">
          {/* 概要 */}
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-mono text-gray-400">{report.run_id}</span>
              <span className="text-xs text-gray-500">环境: {report.env || 'N/A'}</span>
            </div>
            <div className="flex gap-4 text-xs">
              <span className="text-gray-400">总场景: {report.total_cases}</span>
              <span className="text-red-400">失败: {report.failed_cases.length}</span>
            </div>
          </div>

          {/* 失败场景列表 */}
          {report.failed_cases.length === 0 ? (
            <div className="text-center text-gray-600 text-sm py-8">
              无失败场景（或未获取到 cases 详情）
            </div>
          ) : (
            report.failed_cases.map((fc, i) => {
              const cat = categorize(fc.verdict);
              return (
                <div key={i} className="bg-surface-1 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-mono text-info">{fc.scenario_id}</span>
                    <span className={`text-xs ${cat.color}`}>{cat.label}</span>
                  </div>
                  {fc.error && (
                    <div className="bg-red-900/20 rounded p-2 mb-2 text-xs text-red-300 font-mono">
                      {fc.error}
                    </div>
                  )}
                  {fc.assertions && fc.assertions.length > 0 && (
                    <div className="space-y-1">
                      {fc.assertions.map((a: any, j: number) => (
                        <div key={j} className="text-xs text-gray-400 flex items-start gap-2">
                          <span className={a.passed ? 'text-green-500' : 'text-red-500'}>
                            {a.passed ? '✓' : '✗'}
                          </span>
                          <span className="flex-1">{a.type || a.assertion || 'assert'}: {a.detail || a.message || JSON.stringify(a).slice(0, 200)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}

          {/* BUG 单草稿 */}
          {report.failed_cases.length > 0 && (
            <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-lg p-3">
              <div className="text-xs text-yellow-400 font-medium mb-1">📋 BUG 单草稿</div>
              <div className="text-xs text-gray-500">
                以下失败场景可生成 BUG 单草稿，人工确认后才可导出。
              </div>
              <div className="mt-2 space-y-1">
                {report.failed_cases.map((fc, i) => (
                  <div key={i} className="text-xs text-gray-400 flex items-center gap-2">
                    <input type="checkbox" className="accent-yellow-500" />
                    <span>{fc.scenario_id}</span>
                    <span className="text-gray-600">— {categorize(fc.verdict).label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
