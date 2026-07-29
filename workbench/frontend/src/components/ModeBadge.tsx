/** ModeBadge — 模式徽章组件（H-FE）
 *
 * 显示当前模式 + 自动/锁定标识，支持点击切换/锁定、双击解锁。
 */

const MODE_LABELS: Record<string, string> = {
  generate: '✨生成', debug: '🐛调试', analyze: '🔍分析', chat: '💬对话', audit: '🔎审计',
};

export interface ModeBadgeProps {
  currentMode: string;
  lockedMode: string;
  modes: { name: string; tools: string[] }[];
  onSelectMode: (mode: string) => void;   // 点击模式（切换+锁定）
  onUnlock: () => void;                    // 解锁
}

const MODE_ICONS: Record<string, string> = {
  generate: '✨',
  debug: '🐛',
  analyze: '🔍',
  chat: '💬',
  audit: '🔎',
};

export default function ModeBadge({ currentMode, lockedMode, modes, onSelectMode, onUnlock }: ModeBadgeProps) {
  const currentIcon = MODE_ICONS[currentMode] || '❓';
  const currentLabel = MODE_LABELS[currentMode] || currentMode;
  const isLocked = !!lockedMode;

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {/* 当前模式徽章 */}
      <div
        className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border ${
          isLocked
            ? 'bg-info/15 text-info border-info/30 ring-1 ring-info/40'
            : 'bg-info/10 text-info border-info/20'
        }`}
      >
        <span>{currentIcon}</span>
        <span>{currentLabel}</span>
        {isLocked && <span title="已锁定（双击模式或点解锁按钮解除）">🔒</span>}
        {!isLocked && <span className="text-[9px] text-gray-600" title="自动路由中">自动</span>}
      </div>

      {/* 模式选择器 */}
      {modes.map(m => (
        <button
          key={m.name}
          onClick={() => onSelectMode(m.name)}
          onDoubleClick={onUnlock}
          title={`${m.tools.length} 工具${
            lockedMode === m.name ? '（锁定，双击解锁）' :
            lockedMode ? '（当前锁定: ' + (MODE_LABELS[lockedMode] || lockedMode) + '）' :
            '（点击切换并锁定，双击解锁）'
          }`}
          className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
            currentMode === m.name
              ? 'bg-info/15 text-info border border-info/30'
              : 'bg-surface-2 text-gray-500 border border-border hover:text-gray-300'
          }${lockedMode === m.name ? ' ring-1 ring-info/40' : ''}`}
        >
          {MODE_LABELS[m.name] || m.name}
          {lockedMode === m.name && <span className="ml-0.5">🔒</span>}
        </button>
      ))}

      {/* 解锁按钮 */}
      {isLocked && (
        <button
          onClick={onUnlock}
          className="text-[10px] px-1.5 py-0.5 rounded bg-surface-2 text-gray-500 hover:text-gray-300 border border-border"
          title="解锁模式，允许自动路由"
        >
          🔓 解锁
        </button>
      )}
    </div>
  );
}
