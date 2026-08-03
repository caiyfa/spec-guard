// GitLog — 工作区 git 提交历史（SourceTree 风格简化版）
// 数据源：/api/workspace/git-log（git log + ls-remote 远程状态，只读）
// 入口：工作区中心 git 型工作区卡片「📜 记录」按钮；顶栏切换工作区自动跟随

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { workspaceApi, WORKSPACE_CHANGED_EVENT } from '../api';
import type { GitLogResponse, GitCommit } from '../api';

const STATUS_STYLE: Record<string, string> = {
  A: 'text-green-400', M: 'text-yellow-400', D: 'text-red-400', R: 'text-blue-400',
};
const STATUS_LABEL: Record<string, string> = { A: '新增', M: '修改', D: '删除', R: '重命名' };

function fmtDate(iso: string): string {
  if (!iso) return '';
  const m = iso.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
  return m ? `${m[1].slice(2)} ${m[2]}` : iso;
}

export default function GitLog() {
  const navigate = useNavigate();
  const [data, setData] = useState<GitLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<GitCommit | null>(null);
  const [syncing, setSyncing] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await workspaceApi.gitLog();
      setData(r);
      setSelected(prev => {
        const hit = r.commits.find(c => c.sha === (prev ? prev.sha : ''));
        return hit || r.commits[0] || null;
      });
    } catch (e: any) {
      setError(e.message || '加载提交历史失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // 顶栏切换工作区 → 联动重载（session 已同步）
  useEffect(() => {
    const onChanged = () => refresh();
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
  }, [refresh]);

  const handleSync = async () => {
    if (!data) return;
    setSyncing(true);
    setError('');
    try {
      const result = await workspaceApi.pull(data.workspace);
      if (!result.ok) {
        setError(`同步失败: ${result.error || '未知错误'}`);
      } else {
        refresh();
      }
    } catch (e: any) {
      setError(`同步失败: ${e.message}`);
    } finally {
      setSyncing(false);
    }
  };

  const remoteNote = (() => {
    if (!data) return null;
    if (!data.remote_known) {
      return <span className="text-[10px] text-gray-600">远程状态不可达（网络/认证失败）</span>;
    }
    if (data.synced) {
      return <span className="text-[10px] text-green-500">✓ 已与远程同步</span>;
    }
    return (
      <span className="flex items-center gap-2">
        <span className="text-[10px] text-warn">
          ⚠ 远程有新提交（本地 {data.local_head} → 远程 {data.remote_head}）
        </span>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="px-2 py-1 text-[10px] bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40"
        >
          {syncing ? '同步中...' : '⟳ 同步'}
        </button>
      </span>
    );
  })();

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/workspace')}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            ← 返回工作区
          </button>
          <div>
            <h2 className="text-lg font-bold text-gray-200">
              📜 提交历史
              {data && <span className="text-sm font-normal text-gray-500 ml-2">{data.workspace} @ {data.branch}</span>}
            </h2>
            {data && (
              <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
                <span className="font-mono">本地 HEAD {data.local_head}</span>
                {remoteNote}
              </p>
            )}
          </div>
        </div>
      </div>

      {error && <div className="mb-2 text-sm text-fail">❌ {error}</div>}
      {!data && !loading && !error && (
        <div className="text-center text-gray-600 text-sm py-10">
          当前工作区不是 git 型或未激活，请在「工作区中心」选择 git 工作区
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* 左：提交时间线 */}
        <div className="flex-1 flex flex-col min-w-0 border border-border rounded-lg bg-surface-2/50">
          <div className="px-3 py-2 border-b border-border text-xs text-gray-500 flex items-center justify-between flex-shrink-0">
            <span>提交</span>
            <span className="text-[10px] text-gray-600">{data?.commits.length || 0} 条</span>
          </div>
          {loading ? (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">加载中…</div>
          ) : (
            <div className="flex-1 overflow-y-auto p-3 space-y-0">
              {data && data.commits.length === 0 && (
                <div className="text-center text-gray-600 text-sm py-10">仓库暂无提交</div>
              )}
              {data?.commits.map((c, i) => {
                const isLocalHead = data.local_head && c.sha.slice(0, 12) === data.local_head;
                const isRemoteHead = data.remote_known && data.remote_head && c.sha.slice(0, 12) === data.remote_head;
                const isMerge = c.parents.length > 1;
                return (
                  <div
                    key={c.sha}
                    onClick={() => setSelected(c)}
                    className={`flex gap-2 cursor-pointer rounded px-2 py-1.5 transition-colors ${
                      selected?.sha === c.sha ? 'bg-info/10' : 'hover:bg-surface-3'
                    }`}
                  >
                    <div className="flex flex-col items-center">
                      <span className={`w-2.5 h-2.5 rounded-full mt-1.5 ${
                        isLocalHead ? 'bg-green-500' : isRemoteHead ? 'bg-blue-500' : isMerge ? 'bg-yellow-500' : 'bg-gray-600'
                      }`} />
                      {i < data.commits.length - 1 && <span className="w-px flex-1 bg-border/60 my-0.5" />}
                    </div>
                    <div className="pb-2 min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-[11px]">
                        <span className="font-mono text-gray-300">{c.short_sha}</span>
                        {isLocalHead && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-green-900/40 text-green-400 border border-green-700/50">本地 HEAD</span>
                        )}
                        {isRemoteHead && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-blue-900/40 text-blue-400 border border-blue-700/50">origin/{data.branch}</span>
                        )}
                        {isMerge && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">merge</span>
                        )}
                        <span className="ml-auto text-[9px] text-gray-600 whitespace-nowrap">{fmtDate(c.date)}</span>
                      </div>
                      <div className="text-xs text-gray-300 truncate mt-0.5" title={c.message}>{c.message}</div>
                      <div className="text-[10px] text-gray-600">{c.author}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 右：commit 详情 */}
        <div className="w-[460px] flex-shrink-0 flex flex-col min-h-0 border border-border rounded-lg bg-surface-2/50">
          {!selected ? (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-sm px-6 text-center">
              选择左侧一条提交查看详情
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <div className="text-sm font-mono text-gray-200 break-all">{selected.sha}</div>
              <div className="text-sm text-gray-300 mt-1.5">{selected.message}</div>
              <div className="text-[11px] text-gray-500 mt-1.5">
                {selected.author} &lt;{selected.email}&gt;
              </div>
              <div className="text-[11px] text-gray-500">
                {fmtDate(selected.date)}
                {selected.parents.length > 1 && ` · 合并提交（${selected.parents.length} 个父提交）`}
              </div>
              {selected.parents.length > 0 && (
                <div className="text-[10px] text-gray-600 mt-0.5 font-mono">
                  parents: {selected.parents.map(p => p.slice(0, 12)).join(' ')}
                </div>
              )}

              <div className="mt-3 text-xs font-medium text-gray-300">
                变更文件（{selected.files.length}）
              </div>
              {selected.files.length === 0 ? (
                <div className="text-[10px] text-gray-600 mt-1">（合并提交或无文件变更）</div>
              ) : (
                <div className="mt-1.5 space-y-1">
                  {selected.files.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 text-[11px] rounded bg-surface-1 border border-border/60 px-2 py-1">
                      <span className={`font-mono w-6 flex-shrink-0 ${STATUS_STYLE[f.status] || 'text-gray-500'}`}>{f.status}</span>
                      <span className="text-gray-300 font-mono truncate flex-1" title={f.path}>{f.path}</span>
                      <span className="text-[9px] text-gray-600 w-7 flex-shrink-0 text-right">{STATUS_LABEL[f.status] || ''}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
