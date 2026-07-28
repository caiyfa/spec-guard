/** SessionTree — Agent 会话树（工作区 > 会话三级层级） */

interface SessionItem {
  id: string;
  workspace: string;
  modified: string;
  emp_no?: string;
  created_at?: string;
  size?: number;
  title?: string;
}

interface Props {
  sessions: SessionItem[];
  currentSessionId: string;
  currentWorkspace: string;
  onSelectSession: (id: string, workspace: string) => void;
  onNewSession: () => void;
}

export default function SessionTree({ sessions, currentSessionId, currentWorkspace, onSelectSession, onNewSession }: Props) {
  // 按工作区分组
  const grouped: Record<string, SessionItem[]> = {};
  for (const s of sessions) {
    const ws = s.workspace || '(未分配)';
    if (!grouped[ws]) grouped[ws] = [];
    grouped[ws].push(s);
  }
  // 每组内按 modified 倒序
  for (const ws of Object.keys(grouped)) {
    grouped[ws].sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));
  }
  // 工作区排序：当前工作区优先，然后字母序
  const workspaceNames = Object.keys(grouped).sort((a, b) => {
    if (a === currentWorkspace) return -1;
    if (b === currentWorkspace) return 1;
    return a.localeCompare(b);
  });

  return (
    <div className="w-60 flex-shrink-0 bg-surface-2 border-r border-border flex flex-col h-full">
      {/* 顶栏 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-[10px] text-gray-500">会话列表</span>
        <button onClick={onNewSession}
          className="text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20">
          + 新会话
        </button>
      </div>

      {/* 树 */}
      <div className="flex-1 overflow-y-auto p-1">
        {workspaceNames.map(ws => (
          <div key={ws} className="mb-2">
            {/* 工作区（二级） */}
            <div className="flex items-center gap-1 px-2 py-1 text-[10px] text-gray-500 font-medium">
              <span>{ws === currentWorkspace ? '📂' : '📁'}</span>
              <span className="truncate">{ws}</span>
              <span className="text-gray-600 ml-auto">{grouped[ws].length}</span>
            </div>
            {/* 会话（三级） */}
            {grouped[ws].map(s => (
              <button key={s.id} onClick={() => onSelectSession(s.id, s.workspace)}
                className={`w-full text-left px-2 py-1 ml-2 rounded text-[10px] transition-colors ${
                  s.id === currentSessionId
                    ? 'bg-info/10 text-info border-l-2 border-info'
                    : 'text-gray-400 hover:bg-surface-3 border-l-2 border-transparent'
                }`}>
                <div className="truncate">{s.title || s.id}</div>
                <div className="text-gray-600 text-[9px] font-mono">{_formatTime(s.modified)}</div>
              </button>
            ))}
          </div>
        ))}
        {sessions.length === 0 && (
          <div className="text-center text-gray-600 text-[10px] py-8">暂无会话</div>
        )}
      </div>
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
