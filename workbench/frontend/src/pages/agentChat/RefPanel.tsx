import { useEffect, useState } from 'react';
import { workspaceApi } from '../../api';
import type { ChatReference } from './types';

// ── 新鲜度徽标 ──
export function FreshBadge({ status }: { status: string }) {
  if (status === 'fresh') return <span className="text-pass text-fs-micro" title="与引用时一致">✓</span>;
  if (status === 'stale') return <span className="text-yellow-400 text-fs-micro" title="内容已变更">⚠️</span>;
  if (status === 'missing') return <span className="text-fail text-fs-micro" title="文件已删除">✗</span>;
  return null;
}

// ── 引用面板（K-013：会话中 @引用的内容 + 新鲜度） ──
export function RefPanel({ refs, onView }: {
  refs: ChatReference[];
  onView: (path: string, kind: 'file' | 'draft') => void;
}) {
  const [open, setOpen] = useState(true);
  const [status, setStatus] = useState<Record<string, string>>({});
  const refsKey = refs.map(r => `${r.type}:${r.path}:${r.sha}`).join('|');

  // 逐条比对新鲜度（file 走 file-hash 端点；draft 走 .specguard/drafts 路径哈希，失败置 unknown）
  useEffect(() => {
    let alive = true;
    (async () => {
      const next: Record<string, string> = {};
      for (const r of refs) {
        const k = `${r.type}:${r.path}`;
        if (r.type === 'info_pack' || !r.sha) { next[k] = ''; continue; }
        try {
          const hashPath = r.type === 'draft' ? `.specguard/drafts/${r.path}` : r.path;
          const h = await workspaceApi.fileHash(hashPath);
          next[k] = h.sha === r.sha ? 'fresh' : 'stale';
        } catch { next[k] = 'missing'; }
      }
      if (alive) setStatus(next);
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refsKey]);

  if (refs.length === 0) return null;
  return (
    <div className="px-3 py-2 border-b border-border">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between text-fs-body font-medium text-gray-300 hover:text-gray-100">
        <span>🔗 引用（{refs.length}）</span>
        <span className="text-fs-micro text-gray-600">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="mt-1.5 max-h-40 overflow-y-auto space-y-0.5">
          {refs.map((r, i) => (
            <div key={i}
              onClick={() => r.type !== 'info_pack' && onView(r.path, r.type === 'draft' ? 'draft' : 'file')}
              className={`flex items-center gap-1.5 px-1 py-0.5 rounded text-fs-aux ${r.type !== 'info_pack' ? 'cursor-pointer hover:bg-surface-3' : ''}`}>
              <span>{r.type === 'info_pack' ? '📦' : r.type === 'draft' ? '📝' : '📄'}</span>
              <span className="font-mono text-gray-400 truncate flex-1" title={r.path}>{r.label || r.path}</span>
              <FreshBadge status={status[`${r.type}:${r.path}`] || ''} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
