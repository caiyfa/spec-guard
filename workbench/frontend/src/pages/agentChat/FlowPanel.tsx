import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi } from '../../api';
import type { FlowTraceResult, FlowTraceStage } from '../../api';
import MermaidBlock from '../../components/MermaidBlock';  // K-041：主题跟随 mermaid 渲染（渲染失败回退源码）

/** 🧭 路径 面板（T-1042）：golden flow 基线 vs 会话实际走径——对话进行中实时跑偏扫描。
 *
 *  数据源：GET /agent/sessions/{id}/flow-trace（会话 JSONL 每轮增量落盘，
 *  轮询已落盘行即得当前态，无需 WS 埋新事件）。刷新策略：会话切换即拉 +
 *  每 5s 静默轮询（页签不可见时暂停）+ 手动 ↻（体验基线④长操作单点刷新）。
 *  三态分离（体验基线③）：加载中 / 无数据（空会话、非生成会话诚实标注）/ 错误。
 */
const POLL_MS = 5000;
/** 视图模式持久化（体验基线①）：focus=聚焦当前阶段（其余折叠）/ full=完整拓扑 */
const VIEW_KEY = 'sg_flow_view';

const STATUS_META: Record<string, { dot: string; text: string; cn: string }> = {
  in_order: { dot: 'bg-green-500', text: 'text-green-400', cn: '顺序正确' },
  out_of_order: { dot: 'bg-yellow-500', text: 'text-yellow-400', cn: '乱序' },
  missing: { dot: 'bg-red-500', text: 'text-red-400', cn: '缺失' },
  skipped: { dot: 'bg-gray-600', text: 'text-gray-500', cn: '跳过' },
};

/** 问题节点清单（定位按钮跳转目标）：⚠fail 调用 / 乱序 / 缺失必需 */
function issueStages(stages: FlowTraceStage[]): FlowTraceStage[] {
  return (stages || []).filter(s =>
    (s.fails ?? 0) > 0 || s.status === 'out_of_order' || (s.status === 'missing' && s.required));
}

/** 定位闪烁动画（SVG g 元素脉冲，1.6s ×2 后自动移除 class） */
const FLASH_CSS = `
.flow-flash { animation: sgFlowFlash 1.6s ease-in-out 2; }
@keyframes sgFlowFlash { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
`;

export function FlowPanel({ sessionId, onError }: { sessionId: string; onError?: (m: string) => void }) {
  const [trace, setTrace] = useState<FlowTraceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<string>(() => localStorage.getItem(VIEW_KEY) || 'focus');
  const [locateIdx, setLocateIdx] = useState(0);
  const graphRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;

  const switchView = (mode: string) => {
    setViewMode(mode);
    localStorage.setItem(VIEW_KEY, mode);  // 进入即恢复上次选择（体验基线①）
  };

  // 快速定位错误节点：循环跳转（scrollIntoView 平滑滚动 + 闪烁脉冲）
  const locateIssue = () => {
    const issues = issueStages(trace?.stages || []);
    if (!issues.length || !graphRef.current) return;
    const target = issues[locateIdx % issues.length];
    setLocateIdx((locateIdx + 1) % issues.length);
    const stageIdx = (trace?.stages || []).findIndex(s => s.key === target.key);
    const sid = `S${stageIdx + 1}`;
    const g = graphRef.current.querySelector(`[data-id="${sid}"]`)
      || graphRef.current.querySelector(`[id^="flowchart-${sid}-"]`);
    if (g) {
      g.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
      g.classList.remove('flow-flash');
      requestAnimationFrame(() => g.classList.add('flow-flash'));
      window.setTimeout(() => g.classList.remove('flow-flash'), 3400);
    }
  };

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
    setLocateIdx(0);
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
  const issues = issueStages(trace.stages || []);
  const cur = trace.current_stage;
  const graph = (viewMode === 'focus' && trace.mermaid_focused) ? trace.mermaid_focused : trace.mermaid;
  return (
    <div className="px-3 py-2 text-xs space-y-2" data-testid="flow-panel">
      <style>{FLASH_CSS}</style>
      {/* 头：flow 名 + 当前阶段 + 差异数 + 手动刷新 */}
      <div className="flex items-center justify-between border-b border-border pb-1.5">
        <span className="text-gray-400">
          {trace.flow_title || 'golden flow'} · 步数 {trace.n_tool_calls ?? 0}
          {cur && <> · 当前 <span className="text-info font-semibold">{cur.label}{cur.first_step ? `（第${cur.first_step}步）` : ''}</span></>}
          {!trace.is_generate && <span className="text-gray-600"> · 非生成会话（基线仅供参考）</span>}
        </span>
        <span className="flex items-center gap-2">
          {nDev > 0 ? <span className="text-yellow-400 font-semibold">跑偏 {nDev}</span>
            : <span className="text-green-400">无跑偏</span>}
          <button className="text-gray-500 hover:text-info" title="立即刷新" onClick={() => load()}>↻</button>
        </span>
      </div>

      {/* 图形视图：golden flow 条件拓扑图（网状——MermaidBlock natural 档保持原始尺寸
          横向滚动不压缩文字；主题跟随，渲染失败回退源码）。
          控制条：◎聚焦/⛶全图切换（聚焦=当前阶段±邻域其余折叠）+ ⚠错误节点定位 */}
      {graph && (
        <div data-testid="flow-graph" className="border border-border rounded bg-surface-3/40 p-1.5">
          <div className="flex items-center justify-between pb-1 text-[10px]">
            <span className="flex items-center gap-1">
              <button
                className={`px-1.5 py-0.5 rounded ${viewMode === 'focus' ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-info'}`}
                title="聚焦当前阶段：其余阶段折叠为占位（问题节点不折叠）"
                onClick={() => switchView('focus')}
                disabled={!trace.mermaid_focused}
              >◎ 聚焦</button>
              <button
                className={`px-1.5 py-0.5 rounded ${viewMode === 'full' ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-info'}`}
                title="完整拓扑全图"
                onClick={() => switchView('full')}
              >⛶ 全图</button>
            </span>
            {issues.length > 0 && (
              <button
                className="px-1.5 py-0.5 rounded text-warn hover:bg-warn/15"
                title="快速定位错误节点（点击循环跳转）"
                onClick={locateIssue}
                data-testid="flow-locate"
              >⚠ 定位 {(locateIdx % issues.length) + 1}/{issues.length}</button>
            )}
          </div>
          <div ref={graphRef}>
            <MermaidBlock code={graph} fit="natural" />
          </div>
        </div>
      )}

      {/* 阶段四态列表（图形的证据面：步号/次数/工具） */}
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
