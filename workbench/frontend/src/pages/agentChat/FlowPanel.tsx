import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi } from '../../api';
import type { FlowTraceResult, FlowTraceStage } from '../../api';

/** 🧭 路径 面板（T-1042）：golden flow 基线 vs 会话实际走径——对话进行中实时跑偏扫描。
 *
 *  数据源：GET /agent/sessions/{id}/flow-trace（会话 JSONL 每轮增量落盘，
 *  轮询已落盘行即得当前态，无需 WS 埋新事件）。刷新策略：会话切换即拉 +
 *  每 5s 静默轮询（页签不可见时暂停）+ 手动 ↻（体验基线④长操作单点刷新）。
 *  三态分离（体验基线③）：加载中 / 无数据（空会话、非生成会话诚实标注）/ 错误。
 */
const POLL_MS = 5000;

const STATUS_META: Record<string, { dot: string; text: string; cn: string }> = {
  in_order: { dot: 'bg-green-500', text: 'text-green-400', cn: '顺序正确' },
  out_of_order: { dot: 'bg-yellow-500', text: 'text-yellow-400', cn: '乱序' },
  missing: { dot: 'bg-red-500', text: 'text-red-400', cn: '缺失' },
  skipped: { dot: 'bg-gray-600', text: 'text-gray-500', cn: '跳过' },
};

export function FlowPanel({ sessionId, onError }: { sessionId: string; onError?: (m: string) => void }) {
  const [trace, setTrace] = useState<FlowTraceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;

  const load = useCallback(async (silent = false) => {
    const sid = sessionRef.current;
    if (!sid) return;
    if (!silent) setLoading(true);
    try {
      const r = await agentApi.getFlowTrace(sid);
      // 会话已切换的过期响应不采纳（竞态防护）
      if (sessionRef.current !== sid) return;
      setTrace(r);
      setFailed(null);
    } catch (e) {
      if (!silent) {
        const msg = e instanceof Error ? e.message : String(e);
        setFailed(msg);
        onError?.(msg);
      }
    } finally {
      if (sessionRef.current === sid && !silent) setLoading(false);
    }
  }, [onError]);

  // 会话切换即拉 + 静默轮询（页签不可见暂停）
  useEffect(() => {
    setTrace(null);
    setFailed(null);
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load(true);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [sessionId, load]);

  if (!sessionId) {
    return <div className="text-xs text-gray-600 text-center py-6">暂无会话——发起对话后可实时查看路径跑偏</div>;
  }
  if (loading && !trace) {
    return <div className="text-xs text-gray-500 text-center py-6">路径重放加载中…</div>;
  }
  if (failed && !trace) {
    return (
      <div className="text-xs text-red-400 px-3 py-4">
        路径重放失败：{failed} <button className="underline ml-1" onClick={() => load()}>重试</button>
      </div>
    );
  }
  if (!trace) return null;

  if (!trace.available) {
    return (
      <div className="px-3 py-4 text-xs text-gray-500 space-y-2">
        <div>⚠ 当前无法给出路径重放：{trace.reason}</div>
        <button className="text-info underline" onClick={() => load()}>↻ 重试</button>
      </div>
    );
  }

  const nDev = (trace.deviations || []).length;
  return (
    <div className="px-3 py-2 text-xs space-y-2" data-testid="flow-panel">
      {/* 头：flow 名 + 差异数 + 手动刷新 */}
      <div className="flex items-center justify-between border-b border-border pb-1.5">
        <span className="text-gray-400">
          {trace.flow_title || 'golden flow'} · 步数 {trace.n_tool_calls ?? 0} ·
          {!trace.is_generate && <span className="text-gray-600"> 非生成会话（基线仅供参考）</span>}
        </span>
        <span className="flex items-center gap-2">
          {nDev > 0 ? <span className="text-yellow-400 font-semibold">跑偏 {nDev}</span>
            : <span className="text-green-400">无跑偏</span>}
          <button className="text-gray-500 hover:text-info" title="立即刷新" onClick={() => load()}>↻</button>
        </span>
      </div>

      {/* 阶段四态列表 */}
      <div className="space-y-1">
        {(trace.stages || []).map((s: FlowTraceStage, i: number) => {
          const m = STATUS_META[s.status] || STATUS_META.skipped;
          return (
            <div key={s.key} className="flex items-center gap-2" title={s.note || m.cn}>
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${m.dot}`} />
              <span className={`flex-shrink-0 ${m.text}`}>{i + 1}. {s.label}</span>
              <span className="text-gray-600 truncate">
                {s.first_step ? `第${s.first_step}步${s.times > 1 ? `·×${s.times}` : ''}` : s.required ? '未调用' : '—'}
              </span>
            </div>
          );
        })}
      </div>

      {/* 跑偏点（带步号证据） */}
      {nDev > 0 && (
        <div className="border-t border-border pt-1.5 space-y-1">
          <div className="text-yellow-400 font-semibold">跑偏点</div>
          {(trace.deviations || []).map((d, i) => (
            <div key={i} className="text-gray-400 leading-5">⚠ {d}</div>
          ))}
        </div>
      )}

      {/* 计划外工具 */}
      {(trace.extras || []).length > 0 && (
        <div className="border-t border-border pt-1.5 text-gray-500">
          计划外旁支：{trace.extras?.join('、')}
        </div>
      )}

      <div className="text-[10px] text-gray-600 border-t border-border pt-1.5">
        🟩 顺序正确 · 🟨 乱序 · 🟥 缺失必需 · ⬜ 跳过可选；每 5s 自动刷新（进行中的 run 实时可见）
      </div>
    </div>
  );
}
