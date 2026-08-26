import { useEffect, useState } from 'react';
import { workspaceApi } from '../../api';
import type { DocWriteItem } from './types';

function verdictBadge(v: string | null) {
  switch (v) {
    case 'PASS': return <span className="text-[9px] px-1 py-0.5 rounded bg-green-900/25 text-green-400 flex-shrink-0">✅ 校验通过</span>;
    case 'REJECT': return <span className="text-[9px] px-1 py-0.5 rounded bg-red-900/25 text-red-400 flex-shrink-0">❌ 校验未过</span>;
    case 'ERROR': return <span className="text-[9px] px-1 py-0.5 rounded bg-yellow-900/25 text-yellow-400 flex-shrink-0">⚠️ 校验异常</span>;
    case 'SKIP': return <span className="text-[9px] px-1 py-0.5 rounded bg-gray-700/40 text-gray-400 flex-shrink-0">⏭ 门禁跳过</span>;
    default: return null;
  }
}

// 行级 LCS diff（.bak 旧版 vs 当前）：超大文件（>800 行）退化 null 仅展示统计
interface DiffLine { type: 'same' | 'add' | 'del'; text: string }
function diffLines(a: string, b: string): DiffLine[] | null {
  const A = a.split('\n'), B = b.split('\n');
  if (A.length > 800 || B.length > 800) return null;
  const n = A.length, m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push({ type: 'same', text: A[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ type: 'del', text: A[i] }); i++; }
    else { out.push({ type: 'add', text: B[j] }); j++; }
  }
  while (i < n) out.push({ type: 'del', text: A[i++] });
  while (j < m) out.push({ type: 'add', text: B[j++] });
  return out;
}

// 更新对比弹窗：读当前文件 + .bak 备份做行级 diff（safe_resolve 允许 .specguard/ 与 .bak）
export function DiffOverlay({ item, onClose }: { item: DocWriteItem; onClose: () => void }) {
  const [state, setState] = useState<{ loading: boolean; diff: DiffLine[] | null; error: string; added: number; removed: number }>(
    { loading: true, diff: null, error: '', added: 0, removed: 0 });
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!item.path) {
        if (alive) setState({ loading: false, diff: null, error: '无可对比文件', added: 0, removed: 0 });
        return;
      }
      try {
        const [cur, bak] = await Promise.all([
          workspaceApi.readFile(item.path).catch(() => null),
          workspaceApi.readFile(item.path + '.bak').catch(() => null),
        ]);
        if (!alive) return;
        if (!bak) {
          setState({ loading: false, diff: null, error: '无 .bak 备份（首次创建无对比基线）', added: 0, removed: 0 });
          return;
        }
        const lines = diffLines(bak.content, cur?.content ?? '');
        if (lines === null) {
          setState({ loading: false, diff: null, error: '文件过大（>800 行），仅展示统计', added: 0, removed: 0 });
          return;
        }
        setState({
          loading: false, diff: lines, error: '',
          added: lines.filter(l => l.type === 'add').length,
          removed: lines.filter(l => l.type === 'del').length,
        });
      } catch (e: any) {
        if (alive) setState({ loading: false, diff: null, error: e.message || 'diff 失败', added: 0, removed: 0 });
      }
    })();
    return () => { alive = false; };
  }, [item.path]);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center" onClick={onClose}>
      <div className="bg-surface-2 border border-border rounded-xl w-[760px] max-w-[92vw] max-h-[80vh] flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border flex-shrink-0">
          <span className="text-xs font-medium text-gray-200 truncate flex-1">🔄 更新对比 — <span className="font-mono">{item.label}</span></span>
          <button onClick={onClose} className="px-1.5 text-gray-500 hover:text-gray-300">✕</button>
        </div>
        {state.loading ? (
          <div className="text-[11px] text-gray-600 text-center py-10">对比中…</div>
        ) : state.error ? (
          <div className="text-[11px] text-gray-500 text-center py-10">{state.error}</div>
        ) : (
          <>
            <div className="px-3 py-1.5 text-[10px] text-gray-500 border-b border-border flex-shrink-0">
              <span className="text-green-400">+{state.added}</span> / <span className="text-red-400">-{state.removed}</span> · 旧版（.bak）→ 当前
            </div>
            <div className="flex-1 min-h-0 overflow-auto font-mono text-[11px] leading-relaxed">
              {state.diff!.map((l, i) => (
                <div key={i} className={
                  l.type === 'add' ? 'bg-green-900/25 text-green-300 px-2 whitespace-pre-wrap'
                    : l.type === 'del' ? 'bg-red-900/25 text-red-300 px-2 whitespace-pre-wrap'
                      : 'text-gray-500 px-2 whitespace-pre-wrap'
                }>
                  {l.type === 'add' ? '+ ' : l.type === 'del' ? '- ' : '  '}{l.text}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// 更新足迹单卡（失败原因展示 + 查看/对比/让 Agent 修复）
function WritingCard({ item, onOpen, onDiff, onAskAgent }: {
  item: DocWriteItem;
  onOpen: (item: DocWriteItem) => void;
  onDiff: (item: DocWriteItem) => void;
  onAskAgent?: (item: DocWriteItem) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const findings = item.findings || [];
  const failed = item.verdict === 'REJECT' || item.verdict === 'ERROR';
  const visible = showAll ? findings : findings.slice(0, 3);

  return (
    <div className="rounded-lg border border-border bg-surface-2/70 p-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-mono text-gray-200 truncate flex-1 cursor-pointer hover:text-info"
          onClick={() => onOpen(item)} title={item.path || item.ref || ''}>{item.label}</span>
        {item.writes > 1 && (
          <span className="text-[9px] text-gray-500 flex-shrink-0" title="同文件累计更新次数">×{item.writes}</span>
        )}
        {item.versions && item.versions > 1 && (
          <span className="text-[9px] text-gray-500 flex-shrink-0"
            title={`活动流水版本链：第 ${item.version_no} 版 / 共 ${item.versions} 次（含历史会话）`}>
            v{item.version_no}/{item.versions}
          </span>
        )}
        {verdictBadge(item.verdict)}
      </div>
      <div className="text-[10px] text-gray-600 truncate mt-0.5" title={item.ref}>{item.ref}</div>
      {item.thinking && <div className="text-[10px] text-gray-600 mt-1">💭 {item.thinking}</div>}
      {/* 校验失败原因（与 verdict 同源，Agent 据此定位修复） */}
      {failed && findings.length > 0 && (
        <div className="mt-1.5 text-[10px] rounded bg-red-900/20 px-1.5 py-1 space-y-0.5">
          <div className="text-red-400 font-medium">失败原因（{findings.length} 条）</div>
          {visible.map((f, i) => (
            <div key={i} className="text-red-300/90 break-all">
              <span className="text-red-400/80 font-mono">[{f.rule || f.level || 'RULE'}]</span> {f.message}
            </div>
          ))}
          {findings.length > 3 && (
            <button onClick={() => setShowAll(v => !v)}
              className="text-red-400 hover:text-red-300 underline">
              {showAll ? '收起' : `全部 ${findings.length} 条`}
            </button>
          )}
        </div>
      )}
      <div className="text-[10px] text-gray-500 mt-1 font-mono whitespace-pre-wrap"
        style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
        {item.excerpt}
      </div>
      <div className="flex items-center gap-1.5 mt-1.5">
        <button onClick={() => onOpen(item)}
          className="px-2 py-1 rounded bg-surface-3 text-gray-300 text-[11px] hover:bg-surface-1">查看</button>
        {item.path && (item.tool === 'write_delta_doc' || item.tool === 'write_draft' || item.tool === 'undo_draft') && (
          <button onClick={() => onDiff(item)}
            className="px-2 py-1 rounded bg-surface-3 text-gray-300 text-[11px] hover:bg-surface-1">🔄 对比 .bak</button>
        )}
        {failed && onAskAgent && (
          <button onClick={() => onAskAgent(item)}
            className="ml-auto px-2 py-1 rounded bg-warn/20 text-warn text-[11px] hover:bg-warn/30"
            title="把失败原因带进对话，让 Agent 分析并继续更新">
            🤖 让 Agent 修复
          </button>
        )}
      </div>
    </div>
  );
}

// 更新足迹面板（写型工具 doc_write 汇聚，点击打开文件 / 对比 .bak）
export function WritingPanel({ items, onOpen, onDiff, onAskAgent, onAskAgentBatch, onRefresh }: {
  items: DocWriteItem[];
  onOpen: (item: DocWriteItem) => void;
  onDiff: (item: DocWriteItem) => void;
  onAskAgent?: (item: DocWriteItem) => void;
  onAskAgentBatch?: (items: DocWriteItem[]) => void;
  onRefresh?: () => void;
}) {
  const failed = items.filter(i => i.verdict === 'REJECT' || i.verdict === 'ERROR');
  if (items.length === 0) {
    return (
      <div className="px-2 py-2">
        <div className="px-1 text-xs font-medium text-gray-300">✏️ 更新足迹</div>
        <div className="text-[11px] text-gray-600 text-center py-6 leading-relaxed">
          Agent 尚未更新任何文件。<br />写入草稿 / delta 文档 / 入库后<br />自动出现在这里
        </div>
        {onRefresh && (
          <div className="text-center">
            <button onClick={onRefresh}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-[10px] bg-surface-3 rounded hover:bg-surface-3/70 transition-colors">
              ↻ 刷新
            </button>
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="px-2 py-2 space-y-1.5">
      <div className="flex items-center px-1">
        <div className="text-xs font-medium text-gray-300 flex-1">✏️ 更新足迹（{items.length}）</div>
        {failed.length > 0 && onAskAgentBatch && (
          <button onClick={() => onAskAgentBatch(failed)}
            className="text-[10px] px-1.5 py-0.5 rounded bg-warn/20 text-warn hover:bg-warn/30 mr-1"
            title="把全部失败文件的原因带进对话，Agent 依次读取修复">
            🤖 批量修复（{failed.length}）
          </button>
        )}
        {onRefresh && (
          <button onClick={onRefresh} className="text-[10px] text-gray-500 hover:text-info transition-colors px-1"
            title="重新加载更新足迹">↻</button>
        )}
      </div>
      {items.map(item => (
        <WritingCard key={item.key} item={item} onOpen={onOpen} onDiff={onDiff} onAskAgent={onAskAgent} />
      ))}
    </div>
  );
}
