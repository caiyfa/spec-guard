import { useCallback, useEffect, useState } from 'react';
import { rebaseApi } from '../../api';

// 🔧 rebase 中断恢复面板——冲突列表 + 三选解决 + 完成/放弃（界面化，无需下终端）
export function RebasePanel({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<{ in_progress: boolean; onto: string; conflicts: { path: string; segments: number }[] } | null>(null);
  const [detail, setDetail] = useState<{ path: string; segments: { ours: string; theirs: string }[] } | null>(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    rebaseApi.status().then(r => {
      setStatus(r);
      if (!r.in_progress) onChanged();  // rebase 已结束（abort/continue 后）刷新外层
    }).catch(() => {});
  }, [onChanged]);

  useEffect(() => { load(); }, [load]);

  const openDetail = (path: string) => {
    if (detail?.path === path) { setDetail(null); return; }
    rebaseApi.conflict(path).then(r => setDetail({ path, segments: r.segments })).catch((e: any) => setMsg({ ok: false, text: e.message || '读取冲突失败' }));
  };

  const handleResolve = async (path: string, resolution: 'ours' | 'theirs' | 'smart') => {
    setBusy(path);
    setMsg(null);
    try {
      const r = await rebaseApi.resolve(path, resolution);
      setMsg({ ok: true, text: `✅ ${path} 已解决（${resolution}），剩余 ${r.remaining.length} 个冲突` });
      setDetail(null);
      load();
    } catch (e: any) {
      setMsg({ ok: false, text: `❌ ${e.message || '解决失败'}` });
    } finally {
      setBusy('');
    }
  };

  const handleAbort = async () => {
    if (!window.confirm('确认放弃 rebase？将回到 rebase 前的原始状态（本地提交保留，autostash 自动还原）。')) return;
    setBusy('abort');
    try {
      await rebaseApi.abort();
      setMsg({ ok: true, text: '✅ 已放弃 rebase，回到原始状态' });
      onChanged();
    } catch (e: any) {
      setMsg({ ok: false, text: `❌ ${e.message || '操作失败'}` });
    } finally {
      setBusy('');
    }
  };

  const handleContinue = async () => {
    setBusy('continue');
    try {
      const r = await rebaseApi.continue();
      setMsg({ ok: true, text: `✅ ${r.note || 'rebase 完成'}` });
      onChanged();
    } catch (e: any) {
      setMsg({ ok: false, text: `❌ ${e.message || '操作失败'}` });
    } finally {
      setBusy('');
    }
  };

  if (!status) return null;
  const remaining = status.conflicts.length;

  return (
    <div className="rounded-lg border border-red-800/50 bg-red-900/10 p-2 space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-medium text-red-300 flex-1">⚠️ rebase 中断（onto {status.onto || '?'}）</span>
        <button onClick={handleAbort} disabled={!!busy}
          className="px-2 py-1 rounded text-[10px] text-gray-400 hover:text-red-300 border border-border disabled:opacity-40">
          {busy === 'abort' ? '处理中…' : '↩️ 放弃 rebase'}
        </button>
      </div>

      {remaining > 0 ? (
        <>
          <div className="text-[10px] text-gray-500">{remaining} 个文件冲突待解决（点击展开查看两侧内容）：</div>
          {status.conflicts.map(c => (
            <div key={c.path} className="rounded border border-border bg-surface-2/70">
              <div className="flex items-center gap-1.5 px-2 py-1.5 cursor-pointer hover:bg-surface-3/50"
                onClick={() => openDetail(c.path)}>
                <span className="text-[10px] font-mono text-gray-300 truncate flex-1">{c.path}</span>
                <span className="text-[9px] text-warn flex-shrink-0">{c.segments} 段冲突</span>
                <span className="text-[9px] text-gray-600">{detail?.path === c.path ? '▲' : '▼'}</span>
              </div>
              {detail?.path === c.path && (
                <div className="px-2 pb-2 space-y-2 border-t border-border">
                  {detail.segments.map((seg, i) => (
                    <div key={i} className="mt-2">
                      <div className="text-[9px] text-gray-500 mb-0.5">冲突段 {i + 1}</div>
                      <div className="rounded bg-blue-900/20 px-1.5 py-1 mb-1">
                        <div className="text-[9px] text-blue-400 mb-0.5">远端版本（rebase 目标）</div>
                        <pre className="text-[10px] font-mono text-blue-200/80 whitespace-pre-wrap break-all max-h-32 overflow-auto">{seg.ours.trim()}</pre>
                      </div>
                      <div className="rounded bg-green-900/20 px-1.5 py-1">
                        <div className="text-[9px] text-green-400 mb-0.5">本地提交版本</div>
                        <pre className="text-[10px] font-mono text-green-200/80 whitespace-pre-wrap break-all max-h-32 overflow-auto">{seg.theirs.trim()}</pre>
                      </div>
                    </div>
                  ))}
                  <div className="flex gap-1.5 mt-2">
                    <button onClick={() => handleResolve(c.path, 'ours')} disabled={!!busy}
                      className="px-2 py-1 rounded bg-blue-900/30 text-blue-300 text-[10px] hover:bg-blue-900/50 disabled:opacity-40">取远端版本</button>
                    <button onClick={() => handleResolve(c.path, 'theirs')} disabled={!!busy}
                      className="px-2 py-1 rounded bg-green-900/30 text-green-300 text-[10px] hover:bg-green-900/50 disabled:opacity-40">取本地提交</button>
                    <button onClick={() => handleResolve(c.path, 'smart')} disabled={!!busy}
                      className="px-2 py-1 rounded bg-info/20 text-info text-[10px] hover:bg-info/30 disabled:opacity-40"
                      title="以本地提交为基础，保留远端独有的新增行（编号等价自动识别）">
                      {busy === c.path ? '合并中…' : '✨ 智能合并'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </>
      ) : (
        <button onClick={handleContinue} disabled={!!busy}
          className="w-full px-3 py-2 rounded bg-pass/20 text-pass border border-pass/30 text-sm hover:bg-pass/30 disabled:opacity-40">
          {busy === 'continue' ? '提交中…' : '✅ 冲突已全部解决，完成 rebase'}
        </button>
      )}

      {msg && (
        <div className={`text-[10px] rounded px-1.5 py-1 ${msg.ok ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
