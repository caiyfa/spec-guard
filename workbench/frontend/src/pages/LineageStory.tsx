// 血缘链页（T-073，M10）：四阶段分带 + Q1/Q2 审计追溯
// Q1「这个场景为什么存在」向上 / Q2「这个需求被验证了吗」向下
// 外部锚点虚线渲染（链可跨界，资产不跨界）

import { useEffect, useState } from 'react';
import { lineageApi, type LineageTrace, type LineageNode } from '../api';

const STAGE_META: Record<string, { label: string; color: string; bg: string }> = {
  req: { label: '① 需求 specflow', color: 'text-purple-300', bg: 'bg-purple-900/30 border-purple-500/30' },
  dev_ext: { label: '② 研发·边界外', color: 'text-gray-400', bg: 'bg-gray-800/60 border-gray-600/40' },
  test: { label: '③ 验证 测试侧', color: 'text-cyan-300', bg: 'bg-cyan-900/30 border-cyan-500/30' },
  feedback: { label: '④ 反哺 feedback', color: 'text-amber-300', bg: 'bg-amber-900/30 border-amber-500/30' },
};

const EDGE_LABEL: Record<string, string> = {
  produces: '拍板产出',
  decides: '决策映射',
  contains: '包含/变更',
  covers: '覆盖验证',
  references: '外部引用',
  schedules: '编排',
  executes: '执行',
  feedback: '反哺',
  depends_on: '依赖',
};

// M-03：展示文案长度守卫
const maxLen = (s: string, n = 100) => s.length <= n ? s : s.slice(0, n - 1) + '…';

export default function LineageStory() {
  const [nodeInput, setNodeInput] = useState('');
  const [trace, setTrace] = useState<LineageTrace | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  // ── T-074：断链校验 ──
  const [checkResult, setCheckResult] = useState<{ warnings: { rule: string; node: string; message: string }[]; checked_at: string } | null>(null);
  const [checkError, setCheckError] = useState('');

  const runCheck = async (rebuild: boolean) => {
    setCheckError('');
    try {
      const r = await lineageApi.check(rebuild);
      setCheckResult(r);
    } catch (e) {
      setCheckError(String(e));
    }
  };
  useEffect(() => {
    runCheck(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runTrace = async (dir: 'up' | 'down' | 'both') => {
    const node = nodeInput.trim();
    if (!node) {
      setError('请输入起始节点 ID（如 PP-RC-005 / FR-012）');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const r = await lineageApi.trace(node, dir);
      setTrace(r);
    } catch (e) {
      setError(String(e));
      setTrace(null);
    } finally {
      setLoading(false);
    }
  };

  // 按阶段分带（保持 trace 返回顺序）
  const staged = (trace?.path ?? []).reduce<Record<string, LineageNode[]>>((acc, n) => {
    const key = n.stage || 'req';
    (acc[key] = acc[key] || []).push(n);
    return acc;
  }, {});

  const edgeMap = new Map((trace?.edges ?? []).map(e => [`${e.from}→${e.to}`, e.type]));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-base font-bold">🔗 血缘链</h2>
        <span className="text-[11px] text-gray-500">审计动线：Q1 场景为什么存在 / Q2 需求被验证了吗（确定性图遍历，无 LLM）</span>
      </div>

      {/* 追溯输入 */}
      <div className="flex items-center gap-2 flex-wrap">
        <input
          value={nodeInput}
          onChange={e => setNodeInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') runTrace('both'); }}
          placeholder="节点 ID：PP-RC-005 / FR-012 / SPQ-001 / D-012 / IV-003…"
          className="bg-surface-2 border border-border rounded px-3 py-1.5 text-sm text-gray-200 w-80"
        />
        <button
          onClick={() => runTrace('up')}
          className="text-xs bg-purple-900/50 text-purple-200 px-3 py-1.5 rounded hover:bg-purple-900/70"
          title="审计 Q1：这个场景为什么存在？"
        >
          Q1 向上追溯 ⬆
        </button>
        <button
          onClick={() => runTrace('down')}
          className="text-xs bg-cyan-900/50 text-cyan-200 px-3 py-1.5 rounded hover:bg-cyan-900/70"
          title="审计 Q2：这个需求被验证了吗？"
        >
          Q2 向下追溯 ⬇
        </button>
        <button
          onClick={() => runTrace('both')}
          className="text-xs bg-surface-3 text-gray-300 px-3 py-1.5 rounded hover:bg-surface-3/70"
        >
          双向 ↕
        </button>
        {loading && <span className="text-xs text-gray-500">追溯中…</span>}
      </div>

      {error && <div className="text-xs text-red-400 bg-red-900/20 px-3 py-2 rounded">{error}</div>}

      {/* 四阶段分带 */}
      {trace && (
        <div className="space-y-3">
          <p className="text-[11px] text-gray-500">
            {trace.direction === 'up' && `⬆ 向上追溯链（Q1：${trace.root} 为什么存在）`}
            {trace.direction === 'down' && `⬇ 向下追溯链（Q2：${trace.root} 被验证了吗）`}
            {trace.direction === 'both' && `↕ 双向追溯链（${trace.root}）`}
            {trace.truncated && ' · ⚠ 已达最大深度'}
          </p>
          {(['req', 'dev_ext', 'test', 'feedback'] as const).map(stage => {
            const nodes = staged[stage] || [];
            if (nodes.length === 0) return null;
            const meta = STAGE_META[stage];
            return (
              <div key={stage} className={`rounded-lg border p-3 ${meta.bg}`}>
                <p className={`text-[11px] font-medium mb-2 ${meta.color}`}>
                  {meta.label}（{nodes.length}）
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                  {nodes.map((n, i) => {
                    const prev = i > 0 ? nodes[i - 1].id : null;
                    const edgeType = prev ? edgeMap.get(`${prev}→${n.id}`) : null;
                    return (
                      <div key={n.id} className="flex items-center gap-2">
                        {edgeType && (
                          <span className="text-[10px] text-gray-600" title={edgeType}>
                            —{EDGE_LABEL[edgeType] || edgeType}→
                          </span>
                        )}
                        <span
                          className={`text-xs px-2 py-1 rounded border ${
                            n.external
                              ? 'border-dashed border-gray-500/60 text-gray-400 bg-gray-900/40'
                              : n.type === 'fr' || n.type === 'ac'
                                ? 'border-purple-500/40 text-purple-200 bg-purple-900/30'
                                : 'border-border text-gray-300 bg-surface-3'
                          }`}
                          title={`${n.type} · ${n.title || ''}`}
                        >
                          {n.id}
                          {n.external && n.url && (
                            <a href={n.url} target="_blank" rel="noreferrer" className="ml-1 text-info">↗</a>
                          )}
                          {!n.external && n.status && (
                            <span className="ml-1 text-[9px] text-gray-500">[{n.status}]</span>
                          )}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* 追溯链文本 */}
          <div className="rounded-lg bg-surface-2 border border-border p-3">
            <p className="text-[11px] text-gray-500 mb-1.5">追溯链文本</p>
            <p className="text-xs text-gray-300 break-all font-mono">
              {trace.path.map(n => (n.external ? `${n.id}（外部锚点）` : n.id)).join(' → ')}
            </p>
          </div>
        </div>
      )}

      {/* 断链检查（T-074） */}
      <div className="rounded-lg bg-surface-2 border border-border p-3">
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-300 font-medium">⚠ 断链检查（BL-01~BL-06 · 落笔即挂链纪律）</p>
          <button
            onClick={() => runCheck(true)}
            className="text-xs bg-info/10 text-info px-2.5 py-1 rounded hover:bg-info/20"
          >
            重跑校验
          </button>
        </div>
        {checkError && <p className="text-[11px] text-yellow-400 mt-2">{checkError}</p>}
        {checkResult && (
          <div className="mt-2">
            <p className="text-[11px] text-gray-500">
              {checkResult.warnings.length === 0
                ? '✓ 无断链（全部产物已挂链）'
                : `发现 ${checkResult.warnings.length} 处断链（WARNING 级，不阻断流水线）`}
            </p>
            {checkResult.warnings.length > 0 && (
              <div className="mt-2 space-y-1">
                {checkResult.warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-[11px] bg-red-900/10 border border-red-500/20 rounded px-2 py-1">
                    <span className="text-red-300 font-mono whitespace-nowrap">{w.rule}</span>
                    <span className="text-gray-300 font-mono whitespace-nowrap">{w.node}</span>
                    <span className="text-gray-500">{w.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 使用说明 */}
      {!trace && (
        <div className="rounded-lg bg-surface-2 border border-border p-3 text-[11px] text-gray-500 space-y-1">
          <p>💡 审计动线示例：</p>
          <p>· Q1 从场景 ID 向上：<b className="text-gray-300">PP-RC-005</b> → FR → delta → 决策 D-xxx → 面试 IV-xxx（场景存在的理由 = 那轮面试的那个 P0 决策）</p>
          <p>· Q2 从 FR ID 向下：<b className="text-gray-300">FR-012</b> → 场景 → 计划 → 执行报告 → SPQ（需求被验证了吗，失败是否已反哺）</p>
          <p>· 虚线节点 = 研发侧外部锚点（禅道故事/BUG/PR），只读跳转外链，链可跨界、资产不跨界</p>
        </div>
      )}
    </div>
  );
}
