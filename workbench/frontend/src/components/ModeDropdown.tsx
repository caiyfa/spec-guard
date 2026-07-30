/** ModeDropdown — 模式下拉组件（K-012：取代 ModeBadge 的按钮组+双击语义）
 *
 * 徽章按钮显示当前模式 + 锁定/自动标识，点击展开下拉：
 *   模式列表（点击 = 切换并锁定）+ 「⚡ 自动」（点击 = 解锁，允许自动路由）。
 * 点击外部（backdrop）关闭。
 */

import { useState } from 'react';

const MODE_LABELS: Record<string, string> = {
  generate: '✨ 生成', debug: '🐛 调试', analyze: '🔍 分析', chat: '💬 对话', audit: '🔎 审计',
};

export interface ModeDropdownProps {
  currentMode: string;
  lockedMode: string;
  modes: { name: string; tools: string[] }[];
  onSelectMode: (mode: string) => void;   // 选择模式（切换+锁定）
  onUnlock: () => void;                    // 切回自动路由
}

export default function ModeDropdown({ currentMode, lockedMode, modes, onSelectMode, onUnlock }: ModeDropdownProps) {
  const [open, setOpen] = useState(false);
  const isLocked = !!lockedMode;

  return (
    <div className="relative">
      {/* 徽章按钮 */}
      <button
        onClick={() => setOpen(v => !v)}
        title={isLocked ? '模式已锁定（不会自动切换）' : '自动路由中（按消息内容切换模式）'}
        className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border transition-colors ${
          isLocked
            ? 'bg-info/15 text-info border-info/30 ring-1 ring-info/40'
            : 'bg-surface-2 text-gray-400 border-border hover:text-gray-300'
        }`}
      >
        <span>{MODE_LABELS[currentMode] || currentMode}</span>
        {isLocked ? <span>🔒</span> : <span className="text-[9px] text-gray-600">自动</span>}
        <span className="text-[8px] text-gray-600">{open ? '▲' : '▼'}</span>
      </button>

      {/* 下拉层 */}
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-0 mb-1 z-20 w-40 bg-surface-2 border border-border rounded-lg shadow-xl overflow-hidden">
            {modes.map(m => (
              <button
                key={m.name}
                onClick={() => { onSelectMode(m.name); setOpen(false); }}
                title={`${m.tools.length} 工具（点击切换并锁定）`}
                className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                  currentMode === m.name ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
                }`}
              >
                <span>{MODE_LABELS[m.name] || m.name}</span>
                {lockedMode === m.name && <span className="text-[9px]">🔒</span>}
                {currentMode === m.name && <span className="ml-auto text-[10px]">✓</span>}
              </button>
            ))}
            <div className="border-t border-border/50" />
            <button
              onClick={() => { onUnlock(); setOpen(false); }}
              title="解除锁定，按消息内容自动路由模式"
              className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                !isLocked ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
              }`}
            >
              <span>⚡ 自动</span>
              {!isLocked && <span className="ml-auto text-[10px]">✓</span>}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
