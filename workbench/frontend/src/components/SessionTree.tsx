/** SessionTree — Agent 会话树（T-010 扩展：批量归档/恢复；复选框仅批量模式显示；T-1041 smoke 隔离会话默认隐藏，批量操作内开关查看） */

import { useState } from 'react';
import { filterSmokeSessions } from '../pages/agentChat/utils';

interface SessionItem {
  id: string;
  workspace: string;
  modified: string;
  emp_no?: string;
  owner?: string;           // 会话创建者工号（owner 权限判断依据，admin 聚合视图与本人视图均回填）
  created_at?: string;
  size?: number;
  title?: string;
  archived?: boolean;   // T-010 扩展：归档标记
  smoke?: boolean;      // T-1041 扩展：smoke/ 隔离区冒烟会话（默认隐藏，批量操作内开关查看）
}

/** T-1041：smoke 开关持久化（体验基线①）——记忆用户选择；存储不可用时按次生效，默认隐藏 */
const SMOKE_KEY = 'sg_agent_show_smoke';
const readShowSmoke = () => { try { return localStorage.getItem(SMOKE_KEY) === '1'; } catch { return false; } };
const writeShowSmoke = (v: boolean) => { try { localStorage.setItem(SMOKE_KEY, v ? '1' : '0'); } catch { /* 按次生效 */ } };

interface Props {
  sessions: SessionItem[];
  currentSessionId: string;
  currentWorkspace: string;
  ownEmpNo?: string;              // 当前用户工号（owner 权限：批量模式下仅本人会话可勾选）
  onSelectSession: (id: string, workspace: string) => void;
  onNewSession: () => void;
  collapsed?: boolean;          // K-037：收起为细条
  onToggleCollapse?: () => void;
  onBatchArchive?: (ids: string[], archived: boolean) => void;  // 批量归档/恢复（父组件调 API 后刷新）
}

export default function SessionTree({ sessions, currentSessionId, currentWorkspace, ownEmpNo, onSelectSession, onNewSession, collapsed, onToggleCollapse, onBatchArchive }: Props) {
  // 批量模式（复选框仅在批量模式下显示）+ 选择集 + 已归档折叠态
  const [batchMode, setBatchMode] = useState(false);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [showArchived, setShowArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  // T-1041：smoke 会话展示开关（持久化；展示范围锁定批量模式内，退出即恢复隐藏）
  const [showSmoke, setShowSmoke] = useState(readShowSmoke);
  const toggleShowSmoke = () => setShowSmoke(v => { writeShowSmoke(!v); return !v; });

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
        <span className="text-fs-micro text-gray-600 mt-1" style={{ writingMode: 'vertical-rl' }}>会话列表</span>
      </div>
    );
  }

  // 按工作区分组（空 workspace 归「会话」组——不渲染标题，保持列表干净）
  // T-1041：smoke 隔离会话默认隐藏；仅批量模式内开关打开时放行（供批量勾选清理）
  const visibleSessions = filterSmokeSessions(sessions, batchMode && showSmoke);
  const grouped: Record<string, { active: SessionItem[]; archived: SessionItem[]; hasWs: boolean }> = {};
  for (const s of visibleSessions) {
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
  // 已归档：跨工作区聚合（列表最底部统一区，按修改时间倒序）
  const allArchived = Object.values(grouped)
    .flatMap(g => g.archived)
    .sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));

  // owner 权限：无法识别归属（无 owner/无 ownEmpNo）视为本人可操作；否则仅本人会话可勾选
  // （旧会话 emp_no 可能缺失，用后端回填的 owner=目录名 判断）
  const isOwn = (s: SessionItem) => !ownEmpNo || !s.owner || s.owner === ownEmpNo;

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = { ...prev };
      if (next[id]) delete next[id];
      else next[id] = true;
      return next;
    });
  };

  const toggleSelectAll = (items: SessionItem[], on: boolean) => {
    setSelected(prev => {
      const next = { ...prev };
      for (const s of items) {
        if (!isOwn(s)) continue;  // 非本人会话不可批量勾选
        if (on) next[s.id] = true;
        else delete next[s.id];
      }
      return next;
    });
  };

  const selectedCount = Object.keys(selected).length;

  const handleBatch = async (archived: boolean) => {
    // 只提交本人会话（非本人已被禁用勾选，此处兜底过滤）
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

  const renderRow = (s: SessionItem) => {
    const own = isOwn(s);
    return (
      <div key={s.id} className="flex items-center gap-1">
        {batchMode && (
          <input
            type="checkbox"
            checked={!!selected[s.id]}
            disabled={!own}
            onChange={() => toggleSelect(s.id)}
            onClick={e => e.stopPropagation()}
            className="accent-info flex-shrink-0 ml-2 disabled:opacity-25"
            title={!own ? '他人会话，仅创建者可管理' : s.archived ? '选择以批量恢复' : '选择以批量归档'}
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
            {s.smoke && (
              <span className="text-gray-500 text-fs-micro flex-shrink-0" title="smoke 隔离区冒烟会话（验收/调试产物）">🧪</span>
            )}
            {s.workspace && s.workspace !== currentWorkspace && (
              <span className="text-gray-600 text-fs-micro flex-shrink-0">[{s.workspace}]</span>
            )}
            {batchMode && !own && (
              <span className="text-gray-600 text-fs-micro flex-shrink-0" title="他人会话，仅创建者可管理">🔒</span>
            )}
          </div>
          <div className="text-gray-600 text-fs-micro font-mono">{_formatTime(s.modified)}</div>
        </button>
      </div>
    );
  };

  // 组渲染：仅未归档平铺（已归档聚合到整个列表最底部）
  const renderGroup = (g: { active: SessionItem[]; archived: SessionItem[]; hasWs: boolean }, wsKey: string, wsLabel: string) => {
    const active = g.active;
    if (!active.length) return null;
    const ownActive = active.filter(isOwn);  // 组头全选只统计本人会话（非本人不可勾选）
    const activeIds = ownActive.map(s => s.id);
    const allActiveSelected = activeIds.length > 0 && activeIds.every(id => !!selected[id]);
    return (
      <div key={wsKey} className="mb-1.5">
        {/* 工作区标题（空 workspace 组不显示，保持干净） */}
        {g.hasWs && (
          <div className="flex items-center gap-1 px-2 py-1 text-[10px] text-gray-500 font-medium">
            {batchMode && ownActive.length > 0 && (
              <input
                type="checkbox"
                checked={allActiveSelected}
                onChange={e => toggleSelectAll(ownActive, e.target.checked)}
                className="accent-info flex-shrink-0"
                title={allActiveSelected ? '取消全选' : '全选本工作区（仅本人会话）'}
              />
            )}
            <span className="truncate">{wsLabel}</span>
            <span className="text-gray-600 ml-auto">{active.length}</span>
          </div>
        )}
        {/* 未归档会话：直接平铺 */}
        {active.map(renderRow)}
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

      {/* 树：未归档平铺 + 列表最底部统一已归档区 */}
      <div className="flex-1 overflow-y-auto p-1">
        {workspaceNames.map(wsKey => {
          const g = grouped[wsKey];
          const label = wsKey === '__plain__' ? '会话' : wsKey;
          return renderGroup(g, wsKey, label);
        })}
        {visibleSessions.length === 0 && (
          <div className="text-center text-gray-600 text-[10px] py-8">暂无会话</div>
        )}
        {/* 已归档：跨工作区聚合到列表最底部 */}
        {allArchived.length > 0 && (
          <div className="mt-2 pt-1.5 border-t border-border/40">
            <button
              onClick={() => setShowArchived(v => !v)}
              className="w-full flex items-center gap-1 px-2 py-1.5 rounded text-[10px] text-gray-500 hover:text-gray-300 hover:bg-surface-3 transition-colors">
              <span className="text-gray-600 text-fs-micro">{showArchived ? '▼' : '▶'}</span>
              <span>🗄 已归档</span>
              <span className="text-gray-600 ml-auto">{allArchived.length}</span>
            </button>
            {showArchived && allArchived.map(renderRow)}
          </div>
        )}
      </div>

      {/* 底部操作区：批量模式切换 + 批量操作条 */}
      {batchMode ? (
        <div className="flex-shrink-0 border-t border-border p-2 flex items-center gap-1.5">
          <span className="text-[10px] text-gray-400 flex-shrink-0">已选 {selectedCount}</span>
          <button
            onClick={toggleShowSmoke}
            className={`text-[10px] px-1.5 py-1 rounded flex-shrink-0 transition-colors ${showSmoke ? 'bg-purple-900/40 text-purple-300' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}
            title={showSmoke ? 'smoke 隔离会话展示中：点击隐藏' : '显示 smoke 隔离区冒烟会话（验收/调试产物，可勾选批量归档）'}>
            🧪 smoke{showSmoke ? ' ✓' : ''}
          </button>
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