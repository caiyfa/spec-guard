// 失败归因页：读取运行报告，展示失败场景 + 断言差异 + 归因分类
// T-063：归因 Agent——证据包装配 + 定性建议（suggestion 永不自动转 decided）→ 人确认建档 SPQ

import { useState, useEffect } from 'react';
import { apiRequest, attributionApi } from '../api';
import type { AttributeResult, RunSummary, SpqEntry } from '../api';

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

const KIND_LABEL: Record<string, { label: string; cls: string }> = {
  product_defect: { label: '疑似产品缺陷', cls: 'bg-red-900/40 text-red-400' },
  spec_question: { label: 'spec 质疑', cls: 'bg-yellow-900/40 text-yellow-400' },
  environment: { label: '环境问题', cls: 'bg-orange-900/40 text-orange-400' },
};

const SPQ_STATUS: Record<string, string> = {
  pending: '待定性', in_progress: '处理中', zentao_filed: '已提禅道', closed: '已闭环',
};

export default function Attribution() {
  const [runId, setRunId] = useState('');
  const [report, setReport] = useState<RunReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<any[]>([]);
  // T-063：归因结果（per 失败场景）
  const [attributions, setAttributions] = useState<Record<string, AttributeResult>>({});
  const [attributing, setAttributing] = useState('');
  const [spqList, setSpqList] = useState<SpqEntry[]>([]);
  const [spqMessage, setSpqMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const refreshSpq = () => {
    attributionApi.spqList().then(r => setSpqList(r.entries)).catch(() => {});
  };

  useEffect(() => {
    apiRequest<{ reports?: RunSummary[] }>('/runs/history?limit=10')
      .then(data => setHistory(Array.isArray(data) ? data : (data.reports || [])))
      .catch(() => {});
    refreshSpq();
  }, []);

  const loadReport = async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError('');
    setReport(null);
    try {
      const res = await apiRequest<Record<string, any>>(`/runs/${id}`);
      if (!res) throw new Error('运行报告不存在');
      const data = res;
      // 失败场景：run.json 的 cases 数组（id/verdict/file）过滤，逐文件取断言详情
      // （后端无 cases/.json 聚合端点——单场景详情是 /runs/{id}/cases/{file}）
      const failedCases: FailedCase[] = [];
      for (const c of (data.cases || [])) {
        if (!['FAIL', 'ERROR', 'BLOCKED'].includes(c.verdict)) continue;
        const file = c.file || `${c.id}.json`;
        const detail = await apiRequest<any>(
          `/runs/${id}/cases/${encodeURIComponent(file)}`).catch(() => null);
        failedCases.push({
          scenario_id: c.id || '',
          verdict: c.verdict,
          error: detail?.error || '',
          assertions: detail?.assertions || [],
          steps: detail?.steps || [],
        });
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

  // T-063：触发归因（证据包装配 + 确定性定性建议，仅建议不落台账）
  const handleAttribute = async (scenarioId: string) => {
    if (!report) return;
    setAttributing(scenarioId);
    setError('');
    try {
      const r = await attributionApi.attribute(report.run_id, scenarioId);
      setAttributions(prev => ({ ...prev, [scenarioId]: r }));
    } catch (e: any) {
      setError(`归因失败：${e.message}`);
    } finally {
      setAttributing('');
    }
  };

  // T-063：人拍板建档 SPQ（suggestion 确认后才生效，留痕 decided_by）
  const handleConfirmSpq = async (scenarioId: string, kind: string) => {
    const attr = attributions[scenarioId];
    if (!attr) return;
    if (!window.confirm(
      `确认将 ${scenarioId} 定性为「${KIND_LABEL[kind]?.label || kind}」并建档 SPQ？\n` +
      `留痕 decided_by（当前用户）；建议不自动转 decided——这是人拍板确认。`)) return;
    try {
      await attributionApi.spqCreate({
        title: `${scenarioId} 失败归因：${attr.suggestion.rationale.slice(0, 40)}`,
        run_id: report?.run_id,
        scenario_id: scenarioId,
        fr_refs: [],
        suggestion_kind: attr.suggestion.kind,
        decided_kind: kind,
        comment: attr.evidence.response_snapshot.assertion_failed?.slice(0, 200) || '',
      });
      setSpqMessage({ ok: true, text: `✅ 已建档 SPQ（${scenarioId} → ${KIND_LABEL[kind]?.label}）——台账待讨论闭环` });
      refreshSpq();
    } catch (e: any) {
      setSpqMessage({ ok: false, text: `❌ 建档失败：${e.message}` });
    }
  };

  // T-063：SPQ 状态流转
  const handleSpqTransition = async (spqId: string, status: string) => {
    try {
      await attributionApi.spqPatch(spqId, status);
      refreshSpq();
    } catch (e: any) {
      setSpqMessage({ ok: false, text: `状态流转失败：${e.message}` });
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">🔍 失败归因</h2>
        <p className="text-fs-body text-gray-500 mt-1">读取运行报告，分析失败场景的断言差异与根因分类</p>
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
          <div className="text-fs-body text-gray-500 mb-2">最近运行</div>
          <div className="flex flex-wrap gap-2">
            {history.map((h: any) => (
              <button
                key={h.run_id}
                onClick={() => { setRunId(h.run_id); loadReport(h.run_id); }}
                className="px-2 py-1 bg-surface-2 border border-border rounded text-fs-body text-gray-400 hover:text-info hover:border-info"
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
          {/* T-063：建档消息 */}
          {spqMessage && (
            <div className={`px-3 py-2 rounded-lg text-sm ${spqMessage.ok ? 'bg-green-900/30 text-green-400 border border-green-700/50' : 'bg-red-900/30 text-red-400 border border-red-700/50'}`}>
              {spqMessage.text}
            </div>
          )}
          {/* 概要 */}
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-mono text-gray-400">{report.run_id}</span>
              <span className="text-fs-body text-gray-500">环境: {report.env || 'N/A'}</span>
            </div>
            <div className="flex gap-4 text-fs-body">
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
                    <div className="flex items-center gap-2">
                      <span className={`text-fs-body ${cat.color}`}>{cat.label}</span>
                      {/* T-063：触发归因 */}
                      <button
                        onClick={() => handleAttribute(fc.scenario_id)}
                        disabled={attributing !== ''}
                        className="px-2 py-0.5 bg-surface-3 text-gray-300 rounded text-fs-aux hover:bg-surface-2 disabled:opacity-40"
                        title="装配证据包 + 确定性定性建议（仅建议，人确认才建档）">
                        {attributing === fc.scenario_id ? '归因中…' : '🔍 归因'}
                      </button>
                    </div>
                  </div>
                  {fc.error && (
                    <div className="bg-red-900/20 rounded p-2 mb-2 text-fs-body text-red-300 font-mono">
                      {fc.error}
                    </div>
                  )}
                  {fc.assertions && fc.assertions.length > 0 && (
                    <div className="space-y-1">
                      {fc.assertions.map((a: any, j: number) => (
                        <div key={j} className="text-fs-body text-gray-400 flex items-start gap-2">
                          <span className={a.passed ? 'text-green-500' : 'text-red-500'}>
                            {a.passed ? '✓' : '✗'}
                          </span>
                          <span className="flex-1">{a.type || a.assertion || 'assert'}: {a.detail || a.message || JSON.stringify(a).slice(0, 200)}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* T-063：归因建议 + 证据包 + 人拍板 */}
                  {attributions[fc.scenario_id] && (() => {
                    const attr = attributions[fc.scenario_id];
                    const sug = KIND_LABEL[attr.suggestion.kind] || KIND_LABEL.product_defect;
                    return (
                      <div className="mt-2 space-y-2">
                        <div className="bg-surface-2 rounded p-2 border border-border">
                          <div className="flex items-center gap-2 mb-1">
                            <span className={`text-fs-aux px-1.5 py-0.5 rounded ${sug.cls}`}>
                              Agent 建议：{sug.label}
                            </span>
                            <span className="text-fs-aux text-gray-500">仅建议——人确认才建档</span>
                          </div>
                          <div className="text-fs-body text-gray-400">{attr.suggestion.rationale}</div>
                          {attr.honesty_review?.required && (
                            <div className="mt-1 text-fs-aux px-1.5 py-1 rounded bg-orange-900/30 text-orange-400">
                              ⚠️ 诚实性复核：{attr.honesty_review.conclusion}
                            </div>
                          )}
                          <details className="mt-1.5 text-fs-aux">
                            <summary className="cursor-pointer text-gray-500 hover:text-gray-300">
                              证据包（flow_digest {attr.evidence.flow_digest} · 断言现场）
                            </summary>
                            <div className="mt-1 pl-2 space-y-0.5 text-gray-500">
                              <div>断言失败：{attr.evidence.response_snapshot.assertion_failed || '—'}</div>
                              <div>响应摘录：{(attr.evidence.response_snapshot.body_excerpt || '—').slice(0, 120)}</div>
                              <div>DB 快照：{attr.evidence.db_snapshots.length} 条 · 环境：{attr.evidence.env_fingerprint.env || '—'}</div>
                            </div>
                          </details>
                          {/* 人拍板：确认建档 / 改判 */}
                          <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                            {Object.entries(KIND_LABEL).map(([k, v]) => (
                              <button key={k}
                                onClick={() => handleConfirmSpq(fc.scenario_id, k)}
                                disabled={attributing !== ''}
                                className={`px-2 py-0.5 rounded text-fs-aux ${v.cls} border border-border hover:opacity-80 disabled:opacity-40`}
                                title="人拍板建档 SPQ（留痕 decided_by）">
                                定性：{v.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              );
            })
          )}

          {/* BUG 单草稿 */}
          {report.failed_cases.length > 0 && (
            <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-lg p-3">
              <div className="text-fs-body text-yellow-400 font-medium mb-1">📋 BUG 单草稿</div>
              <div className="text-fs-body text-gray-500">
                以下失败场景可生成 BUG 单草稿，人工确认后才可导出。
              </div>
              <div className="mt-2 space-y-1">
                {report.failed_cases.map((fc, i) => (
                  <div key={i} className="text-fs-body text-gray-400 flex items-center gap-2">
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

      {/* T-063：SPQ 归因台账（独立渲染——不依赖报告加载，T-063 前端需求） */}
      <div className="bg-surface-1 rounded-lg border border-border p-3 mt-3">
        <div className="text-sm text-gray-300 font-medium mb-2">📒 SPQ 归因台账</div>
        {spqList.length === 0 ? (
          <div className="text-fs-body text-gray-600">暂无归因台账条目（归因建议经人拍板后在此建档）</div>
        ) : (
          <div className="space-y-1.5">
            {spqList.map((s) => (
              <div key={s.spq_id} className="px-2 py-1.5 rounded bg-surface-2 border border-border">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-fs-body font-mono text-info">{s.spq_id}</span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-fs-aux text-gray-500">{SPQ_STATUS[s.status] || s.status}</span>
                    {s.status === 'pending' && (
                      <button onClick={() => handleSpqTransition(s.spq_id, 'in_progress')}
                        className="text-fs-aux px-1.5 py-0.5 bg-yellow-900/40 text-yellow-400 rounded hover:bg-yellow-900/60">
                        处理中
                      </button>
                    )}
                    {s.status !== 'closed' && (
                      <button onClick={() => handleSpqTransition(s.spq_id, 'closed')}
                        className="text-fs-aux px-1.5 py-0.5 bg-green-900/40 text-green-400 rounded hover:bg-green-900/60">
                        闭环
                      </button>
                    )}
                  </div>
                </div>
                <div className="text-fs-body text-gray-400 mt-0.5 truncate" title={s.title}>{s.title}</div>
                <div className="text-fs-aux text-gray-600 mt-0.5 flex gap-2 flex-wrap">
                  {s.run_id && <span>← {s.run_id}</span>}
                  {s.scenario_id && <span>{s.scenario_id}</span>}
                  {(s.fr_refs || []).length > 0 && <span>FR: {(s.fr_refs || []).join(',')}</span>}
                  {s.decided_kind && (
                    <span className={KIND_LABEL[s.decided_kind]?.cls || ''}>
                      {KIND_LABEL[s.decided_kind]?.label}
                    </span>
                  )}
                  {s.decided_by && <span>拍板: {s.decided_by}</span>}
                  {(s.info_pack_synced || []).length > 0 && (
                    <span className="text-info/80">⟳ 已入包: {(s.info_pack_synced || []).join(',')}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
