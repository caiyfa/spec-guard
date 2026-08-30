// T-060：覆盖缺口三态泳道（🔴 无覆盖 / 🟡 草稿待审 / 🟢 已覆盖）
// 草稿不计覆盖：🟡 与 🔴 同 FR 可并存；「生成下一批」只产草稿不产计划（铁律 6）

import { useCallback, useEffect, useState } from 'react';
import { coverageApi } from '../api';
import type { CoverageGaps, CoverageBacklink } from '../api';

const REASON_LABEL: Record<string, string> = {
  delta_new_p0: 'delta 新增 P0',
  delta_modified: 'delta 修改触及',
  history: '历史缺口',
  edge_conflict: '边界/冲突',
};

const GATE_BADGE: Record<string, { label: string; cls: string }> = {
  approved: { label: '① 已评审', cls: 'bg-green-900/40 text-green-400' },
  pending: { label: '① 待评审', cls: 'bg-yellow-900/40 text-yellow-400' },
  rejected: { label: '① 已驳回', cls: 'bg-red-900/40 text-red-400' },
  pass: { label: '② 校验✓', cls: 'bg-green-900/40 text-green-400' },
  fail: { label: '② 校验✗', cls: 'bg-red-900/40 text-red-400' },
  blocked: { label: '③ 门禁⏸', cls: 'bg-surface-3 text-gray-500' },
};

export default function CoveragePanel() {
  const [gaps, setGaps] = useState<CoverageGaps | null>(null);
  const [moduleFilter, setModuleFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [backlink, setBacklink] = useState<CoverageBacklink | null>(null);
  const [batchFrs, setBatchFrs] = useState<string[]>([]);
  const [sourceDelta, setSourceDelta] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await coverageApi.gaps(moduleFilter);
      setGaps(data);
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 加载覆盖缺口失败：${e.message}` });
    } finally {
      setLoading(false);
    }
  }, [moduleFilter]);

  useEffect(() => { refresh(); }, [refresh]);

  const showBacklink = async (fr: string) => {
    try {
      setBacklink(await coverageApi.backlink(fr));
    } catch {
      setBacklink(null);
    }
  };

  const handleNextBatch = async () => {
    if (batchFrs.length === 0) return;
    if (!window.confirm(
      `「生成下一批」将按缺口圈定 ${batchFrs.length} 个 FR 生成草稿骨架（${batchFrs.join('、')}）。\n` +
      `全部产物走三闸（人工评审→格式校验→发布门禁），不产生任何计划。\n确认生成？`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const r = await coverageApi.nextBatch(batchFrs, sourceDelta);
      setMessage({
        ok: r.rejected.length === 0,
        text: `✅ 已生成 ${r.produced.length} 份草稿${r.rejected.length ? `；拒绝 ${r.rejected.length} 份（${r.rejected.map(x => x.fr + ':' + x.reason).join('、')}）` : ''}——去「草稿评审」页走三闸`,
      });
      setBatchFrs([]);
      await refresh();
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 生成失败：${e.message}` });
    } finally {
      setBusy(false);
    }
  };

  const laneCard = (items: any[], color: string, empty: string) => (
    <div className="flex-1 min-w-0 bg-surface-1 rounded-lg border border-border p-3">
      <div className="text-fs-body text-gray-500 mb-2">{empty}（{items.length}）</div>
      <div className="space-y-1.5">
        {items.map((it) => (
          <div key={it.fr + (it.draft_id || '')}
            className="px-2 py-1.5 rounded border border-border bg-surface-2 cursor-pointer hover:border-info/60"
            onClick={() => showBacklink(it.fr)}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-fs-body font-mono text-gray-200">{it.fr}</span>
              <span className={`text-fs-micro px-1 py-0.5 rounded ${color}`}>{it.reason ? (REASON_LABEL[it.reason] || it.reason) : '已覆盖'}</span>
            </div>
            <div className="text-fs-aux text-gray-500 truncate mt-0.5">{it.name}</div>
            {it.draft_id && (
              <div className="flex items-center gap-1 mt-1 flex-wrap">
                <span className="text-fs-micro font-mono text-gray-400">d:{it.draft_id}</span>
                {it.gates && (
                  <>
                    <span className={`text-fs-micro px-1 rounded ${GATE_BADGE[it.gates.g1]?.cls || ''}`}>{GATE_BADGE[it.gates.g1]?.label}</span>
                    <span className={`text-fs-micro px-1 rounded ${GATE_BADGE[it.gates.g2]?.cls || ''}`}>{GATE_BADGE[it.gates.g2]?.label}</span>
                    <span className={`text-fs-micro px-1 rounded ${GATE_BADGE[it.gates.g3]?.cls || ''}`}>{GATE_BADGE[it.gates.g3]?.label}</span>
                  </>
                )}
              </div>
            )}
            {it.scenarios && (
              <div className="text-fs-aux text-gray-500 mt-0.5 truncate">
                covers ← {it.scenarios.join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-fs-title font-bold text-gray-200">🧭 覆盖缺口</h2>
        <input
          value={moduleFilter}
          onChange={e => setModuleFilter(e.target.value)}
          placeholder="模块过滤（如 system-settings/inventory-activity）"
          className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-body text-gray-300 placeholder-gray-600 focus:border-info outline-none"
        />
        <button onClick={refresh} disabled={loading}
          className="px-3 py-1.5 bg-surface-3 text-gray-200 rounded text-fs-lead hover:bg-surface-2 disabled:opacity-40">
          {loading ? '…' : '刷新'}
        </button>
      </div>

      {message && (
        <div className={`px-3 py-2 rounded-lg text-fs-lead ${message.ok ? 'bg-green-900/30 text-green-400 border border-green-700/50' : 'bg-red-900/30 text-red-400 border border-red-700/50'}`}>
          {message.text}
        </div>
      )}

      {gaps && (
        <>
          <div className="text-fs-body text-gray-500">
            真实基线 FR 总数：<span className="text-gray-300">{gaps.fr_total}</span>
            {' '}· 指纹 <span className="font-mono text-gray-600">{gaps.fingerprint}</span>
            {' '}· 草稿不计覆盖（🟡 与 🔴 同 FR 可并存）
          </div>

          {/* T-981：测试维度分布（按 doc.dimensions 聚合；0 计数 = 测试设计盲区） */}
          {gaps.dimensions && (
            <div className="bg-surface-1 rounded-lg border border-border p-3">
              <div className="text-fs-body text-gray-500 mb-2">
                测试维度分布（场景库按 doc.dimensions 聚合，0 = 盲区）
                {gaps.dimensions.unassigned.length > 0 && (
                  <span className="ml-2 text-yellow-400/80">
                    ⚠ {gaps.dimensions.unassigned.length} 个场景未标注 dimensions：
                    <span className="font-mono">{gaps.dimensions.unassigned.join(', ')}</span>
                  </span>
                )}
              </div>
              <div className="flex gap-2 flex-wrap">
                {gaps.dimensions.lanes.map(d => (
                  <div key={d.dimension}
                    className={`px-2 py-1.5 rounded border text-fs-body ${d.count > 0 ? 'border-border bg-surface-2' : 'border-dashed border-border/60 opacity-60'}`}
                    title={d.count > 0
                      ? `${d.label}\n${d.scenarios.join(', ')}\n覆盖 FR：${d.frs.join(', ') || '（无）'}`
                      : `${d.label}\n（无场景——测试设计盲区）`}>
                    <span className="text-gray-400">{d.dimension}</span>
                    <span className={`ml-1.5 font-mono ${d.count > 0 ? 'text-info' : 'text-gray-600'}`}>{d.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-3 flex-1 min-h-0">
            {laneCard(gaps.lanes.gap, 'bg-red-900/50 text-red-400', '🔴 无覆盖')}
            {laneCard(gaps.lanes.draft, 'bg-yellow-900/50 text-yellow-400', '🟡 草稿待审')}
            {laneCard(gaps.lanes.covered, 'bg-green-900/50 text-green-400', '🟢 已覆盖')}
          </div>

          {/* 建议顺序 + 生成下一批 */}
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="text-fs-body text-gray-400 mb-2">
              建议补齐顺序（确定性排序：delta 新增 P0 &gt; 修改触及 &gt; 历史缺口）：
              <span className="ml-2 font-mono text-info">
                {gaps.suggested_order.length ? gaps.suggested_order.map((fr, i) => `${i + 1}.${fr}`).join(' → ') : '（无缺口）'}
              </span>
            </div>
            {gaps.suggested_order.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-fs-body text-gray-500">生成下一批：</span>
                <select
                  multiple
                  value={batchFrs}
                  onChange={e => setBatchFrs(Array.from(e.target.selectedOptions).map(o => o.value))}
                  className="bg-surface-2 border border-border rounded px-2 py-1 text-fs-body text-gray-300 min-w-48 h-16"
                  title="Ctrl/Shift 多选要圈定的缺口 FR（人确认后执行）">
                  {gaps.suggested_order.map(fr => (
                    <option key={fr} value={fr}>{fr}</option>
                  ))}
                </select>
                <input
                  value={sourceDelta}
                  onChange={e => setSourceDelta(e.target.value)}
                  placeholder="source_delta（挂链，如 extend-void-scope）"
                  className="bg-surface-2 border border-border rounded px-2 py-1 text-fs-body text-gray-300 w-48 placeholder-gray-600"
                />
                <button
                  onClick={handleNextBatch}
                  disabled={busy || batchFrs.length === 0}
                  className="px-3 py-1.5 bg-info text-white rounded text-fs-lead hover:bg-info/90 disabled:opacity-40"
                  title="只产草稿不产计划（铁律 6）；产物走三闸后入库">
                  {busy ? '生成中…' : '⚙ 生成下一批'}
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {/* FR backlink 信息条 */}
      {backlink && (
        <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-lg p-3">
          <div className="flex items-center justify-between">
            <span className="text-fs-body font-mono text-yellow-400">
              covers ← {backlink.fr} {backlink.title ? `· ${backlink.title}` : ''}
            </span>
            <button onClick={() => setBacklink(null)} className="text-gray-500 text-fs-body hover:text-gray-300">✕</button>
          </div>
          <div className="mt-2 space-y-1 text-fs-body text-gray-400">
            <div>场景：{backlink.scenarios.length ? backlink.scenarios.map(s => s.id).join(', ') : '（无）'}</div>
            <div>草稿：{backlink.drafts.length ? backlink.drafts.map(d => `${d.draft_id}（${d.scenario_id}）`).join(', ') : '（无）'}</div>
            <div>最近执行：{backlink.recent_runs.length ? backlink.recent_runs.map(r => `${r.run_id}:${r.verdict}`).join(', ') : '（无）'}</div>
            {backlink.deltas.length > 0 && <div>delta：{backlink.deltas.join(', ')}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
