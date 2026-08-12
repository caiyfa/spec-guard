/** SessionTree — Agent 会话树（T-010 扩展：批量归档/恢复；复选框仅批量模式显示） */

import { useState } from 'react';

interface SessionItem {
  id: string;
  workspace: string;
  modified: string;
  emp_no?: string;
  created_at?: string;
  size?: number;
  title?: string;
  archived?: boolean;   // T-010 扩展：归档标记
}

interface Props {
  sessions: SessionItem[];
  currentSessionId: string;
  currentWorkspace: string;
  onSelectSession: (id: string, workspace: string) => void;
  onNewSession: () => void;
  collapsed?: boolean;          // K-037：收起为细条
  onToggleCollapse?: () => void;
  onBatchArchive?: (ids: string[], archived: boolean) => void;  // 批量归档/恢复（父组件调 API 后刷新）
}

export default function SessionTree({ sessions, currentSessionId, currentWorkspace, onSelectSession, onNewSession, collapsed, onToggleCollapse, onBatchArchive }: Props) {
  // 批量模式（复选框仅在批量模式下显示）+ 选择集 + 已归档折叠态
  const [batchMode, setBatchMode] = useState(false);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [showArchived, setShowArchived] = useState(false);
  const [busy, setBusy] = useState(false);

  // K-037：收起态——细条（展开按钮 + 新会话 + 竖排标题）
  if (collapsed) {
    return (
      <div className="w-9 flex-shrink-0 bg-surface-2 border-r border-border flex flex-col items-center py-2 gap-1.5">
        <button onClick={onToggleCollapse} title="展开会话列表"
          className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs">
          »
        </button>
        <button onClick={onNewSession} title="新会话"
          className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-sm">
          ＋
        </button>
        <span className="text-[9px] text-gray-600 mt-1" style={{ writingMode: 'vertical-rl' }}>会话列表</span>
      </div>
    );
  }

  // 按工作区分组（空 workspace 归「会话」组——不渲染标题，保持列表干净）
  const grouped: Record<string, { active: SessionItem[]; archived: SessionItem[]; hasWs: boolean }> = {};
  for (const s of sessions) {
    const ws = s.workspace || '__plain__';
    if (!grouped[ws]) grouped[ws] = { active: [], archived: [], hasWs: !!s.workspace };
    (s.archived ? grouped[ws].archived : grouped[ws].active).push(s);
  }
  // 每组内按 modified 倒序
  for (const ws of Object.keys(grouped)) {
    grouped[ws].active.sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));
    grouped[ws].archived.sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));
  }
  // 工作区排序：当前工作区优先，然后字母序（无标题组最后）
  const workspaceNames = Object.keys(grouped).sort((a, b) => {
    if (a === currentWorkspace) return -1;
    if (b === currentWorkspace) return 1;
    if (a === '__plain__') return 1;
    if (b === '__plain__') return -1;
    return a.localeCompare(b);
  });

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = { ...prev };
      if (next[id]) delete next[id];
      else next[id] = true;
      return next;
    });
  };

  const toggleSelectAll = (ids: string[], on: boolean) => {
    setSelected(prev => {
      const next = { ...prev };
      for (const id of ids) {
        if (on) next[id] = true;
        else delete next[id];
      }
      return next;
    });
  };

  const selectedCount = Object.keys(selected).length;

  const handleBatch = async (archived: boolean) => {
    const ids = Object.keys(selected);
    if (!ids.length || !onBatchArchive) return;
    setBusy(true);
    try {
      await onBatchArchive(ids, archived);
      setSelected({});  // 成功后清空选择（父组件刷新列表）
    } finally {
      setBusy(false);
    }
  };

  const renderRow = (s: SessionItem) => (
    <div key={s.id} className="flex items-center gap-1">
      {batchMode && (
        <input
          type="checkbox"
          checked={!!selected[s.id]}
          onChange={() => toggleSelect(s.id)}
          onClick={e => e.stopPropagation()}
          className="accent-info flex-shrink-0 ml-2"
          title={s.archived ? '选择以批量恢复' : '选择以批量归档'}
        />
      )}
      <button onClick={() => onSelectSession(s.id, s.workspace)}
        className={`w-full text-left px-2 py-1 rounded text-[10px] transition-colors ${
          s.id === currentSessionId
            ? 'bg-info/10 text-info border-l-2 border-info'
            : 'text-gray-400 hover:bg-surface-3 border-l-2 border-transparent'
        }`}>
        <div className="truncate flex items-center gap-1">
          <span className="truncate">{s.title || s.id}</span>
          {s.workspace && s.workspace !== currentWorkspace && (
            <span className="text-gray-600 text-[8px] flex-shrink-0">[{s.workspace}]</span>
          )}
        </div>
        <div className="text-gray-600 text-[9px] font-mono">{_formatTime(s.modified)}</div>
      </button>
    </div>
  );

  // 组渲染：未归档平铺（无标题）；已归档折叠为一行计数（点击展开）
  const renderGroup = (g: { active: SessionItem[]; archived: SessionItem[]; hasWs: boolean }, wsKey: string, wsLabel: string) => {
    const active = g.active;
    const archived = g.archived;
    if (!active.length && !archived.length) return null;
    const activeIds = active.map(s => s.id);
    const allActiveSelected = activeIds.length > 0 && activeIds.every(id => !!selected[id]);
    return (
      <div key={wsKey} className="mb-1.5">
        {/* 工作区标题（空 workspace 组不显示，保持干净） */}
        {g.hasWs && (
          <div className="flex items-center gap-1 px-2 py-1 text-[10px] text-gray-500 font-medium">
            {batchMode && active.length > 0 && (
              <input
                type="checkbox"
                checked={allActiveSelected}
                onChange={e => toggleSelectAll(activeIds, e.target.checked)}
                className="accent-info flex-shrink-0"
                title={allActiveSelected ? '取消全选' : '全选本工作区'}
              />
            )}
            <span className="truncate">{wsLabel}</span>
            <span className="text-gray-600 ml-auto">{active.length}{archived.length > 0 ? ` +${archived.length}` : ''}</span>
          </div>
        )}
        {/* 未归档会话：直接平铺 */}
        {active.map(renderRow)}
        {/* 已归档：折叠行（仅当存在时） */}
        {archived.length > 0 && (
          <>
            <button
              onClick={() => setShowArchived(v => !v)}
              className="w-full flex items-center gap-1 px-2 py-1 ml-1.5 rounded text-[10px] text-gray-500 hover:text-gray-300 hover:bg-surface-3 transition-colors">
              <span className="text-gray-600 text-[9px]">{showArchived ? '▼' : '▶'}</span>
              <span>🗄 已归档</span>
              <span className="text-gray-600 ml-auto">{archived.length}</span>
            </button>
            {showArchived && archived.map(renderRow)}
          </>
        )}
      </div>
    );
  };

  return (
    <div className="w-60 flex-shrink-0 bg-surface-2 border-r border-border flex flex-col h-full">
      {/* 顶栏 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="flex items-center gap-1 text-[10px] text-gray-500">
          <button onClick={onToggleCollapse} title="收起会话列表"
            className="w-4 h-4 rounded text-gray-600 hover:text-info hover:bg-surface-3 text-[10px] leading-none">
            «
          </button>
          会话列表
        </span>
        <button onClick={onNewSession}
          className="text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20">
          + 新会话
        </button>
      </div>

      {/* 树：未归档平铺 + 已归档折叠 */}
      <div className="flex-1 overflow-y-auto p-1">
        {workspaceNames.map(wsKey => {
          const g = grouped[wsKey];
          const label = wsKey === '__plain__' ? '会话' : wsKey;
          return renderGroup(g, wsKey, label);
        })}
        {sessions.length === 0 && (
          <div className="text-center text-gray-600 text-[10px] py-8">暂无会话</div>
        )}
      </div>

      {/* 底部操作区：批量模式切换 + 批量操作条 */}
      {batchMode ? (
        <div className="flex-shrink-0 border-t border-border p-2 flex items-center gap-1.5">
          <span className="text-[10px] text-gray-400 flex-shrink-0">已选 {selectedCount}</span>
          <button
            onClick={() => handleBatch(true)}
            disabled={busy || selectedCount === 0}
            className="flex-1 text-[10px] px-1.5 py-1 rounded bg-amber-900/30 text-amber-300 hover:bg-amber-900/50 disabled:opacity-40"
            title="归档选中会话（列表瘦身，文件保留可恢复）">
            🗄 归档
          </button>
          <button
            onClick={() => handleBatch(false)}
            disabled={busy || selectedCount === 0}
            className="flex-1 text-[10px] px-1.5 py-1 rounded bg-info/10 text-info hover:bg-info/20 disabled:opacity-40"
            title="恢复选中会话">
            ↺ 恢复
          </button>
          <button
            onClick={() => { setBatchMode(false); setSelected({}); }}
            className="text-[10px] px-1.5 py-1 rounded text-gray-500 hover:text-gray-300"
            title="退出批量操作">
            ✕ 完成
          </button>
        </div>
      ) : (
        <div className="flex-shrink-0 border-t border-border p-2">
          <button
            onClick={() => setBatchMode(true)}
            className="w-full text-[10px] px-1.5 py-1 rounded bg-surface-3 text-gray-400 hover:text-gray-200 hover:bg-surface-3/80 transition-colors"
            title="进入批量操作：勾选多个会话归档/恢复">
            ⚡ 批量操作
          </button>
        </div>
      )}
    </div>
  );
}

function _formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch { return iso; }
}