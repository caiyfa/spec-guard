import type { AgentStats, ChatMessage, CtxUsage } from './types';
import { calcCtxBreakdown } from './utils';

// ── 上下文用量面板组件 ──
export function ContextPanel({ ctxUsage, messages, ctxLimit, stats }: { ctxUsage: CtxUsage; messages: ChatMessage[]; ctxLimit: number; stats: AgentStats | null }) {
  const breakdown = calcCtxBreakdown(messages, ctxUsage.prompt_tokens);
  const total = ctxUsage.prompt_tokens + ctxUsage.completion_tokens;
  const pct = Math.round((total / ctxLimit) * 100);
  const fmt = (n: number) => n >= 1000 ? (n / 1000).toFixed(1) + 'K' : String(n);
  const promptTotal = Object.values(breakdown).reduce((a, b) => a + b, 0) || 1;
  const roles = [
    { key: 'system' as const, color: 'bg-blue-500', label: '系统' },
    { key: 'user' as const, color: 'bg-green-500', label: '用户' },
    { key: 'assistant' as const, color: 'bg-purple-500', label: '助手' },
    { key: 'tool' as const, color: 'bg-orange-500', label: '工具' },
  ];
  return (
    <div className="px-3 py-2 border-b border-border">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-gray-300">📊 上下文</span>
        <span className={`text-fs-aux font-mono ${pct > 80 ? 'text-red-400' : pct > 50 ? 'text-yellow-400' : 'text-gray-500'}`}>
          {pct}%
        </span>
      </div>
      {/* K-012: 会话统计（原底部栏指标迁入） */}
      {stats && (
        <div className="text-fs-aux text-gray-600 font-mono mb-1">
          {stats.tps !== undefined && <span title="tokens/sec">⚡{stats.tps}/s </span>}
          {stats.elapsed_time !== undefined && <span title="elapsed time">⏱{stats.elapsed_time}s </span>}
          {(stats.cache_hits !== undefined) && <span title="prompt cache 命中/未命中">cache {stats.cache_hits}/{stats.cache_misses}</span>}
        </div>
      )}
      {/* 堆叠条形图 */}
      <div className="h-2 w-full rounded-full bg-black/40 overflow-hidden flex">
        {roles.map(r => {
          const w = (breakdown[r.key] / ctxLimit) * 100;
          return w > 0 ? (
            <div key={r.key} className={`h-full ${r.color}`} style={{ width: `${Math.min(w, 100)}%` }} />
          ) : null;
        })}
      </div>
      {/* 总量 */}
      <div className="text-fs-aux text-gray-600 font-mono mt-1">
        {fmt(total)} / {fmt(ctxLimit)} tokens
      </div>
      {/* 分角色明细 */}
      <div className="space-y-0.5 mt-1.5">
        {roles.map(r => {
          const val = breakdown[r.key];
          const rolePct = Math.round((val / promptTotal) * 100);
          return (
            <div key={r.key} className="flex items-center gap-1.5 text-fs-aux">
              <span className={`w-2 h-2 rounded-sm ${r.color}`} />
              <span className="text-gray-500 w-8">{r.label}</span>
              <span className="text-gray-400 font-mono flex-1 text-right">{fmt(val)}</span>
              <span className="text-gray-600 font-mono w-7 text-right">{rolePct}%</span>
            </div>
          );
        })}
      </div>
      {/* 输入/输出 */}
      <div className="flex gap-3 mt-1.5 pt-1.5 border-t border-border/50 text-fs-aux text-gray-600 font-mono">
        <span title="输入 tokens">↑ {fmt(ctxUsage.prompt_tokens)}</span>
        <span title="输出 tokens">↓ {fmt(ctxUsage.completion_tokens)}</span>
      </div>
    </div>
  );
}
