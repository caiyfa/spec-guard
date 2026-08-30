// ── 多轮会话导航图标列（独立组件，与消息滚动容器平级） ──
export function ConversationRail({ userMsgs, railPos, activeUserGroupIdx, inViewSet, hoverUserIdx, onHover, onJump }: {
  userMsgs: { groupIdx: number; content: string }[];
  railPos: { idx: number; pct: number }[];
  activeUserGroupIdx: number | null;
  inViewSet: Set<number>;
  hoverUserIdx: number | null;
  onHover: (idx: number | null) => void;
  onJump: (groupIdx: number) => void;
}) {
  if (userMsgs.length < 2) return null;
  return (
    <div className="flex-shrink-0 w-4 relative">
      {/* 连接竖线 */}
      {railPos.length >= 2 && (
        <div className="absolute left-1/2 -translate-x-1/2 top-[15%] bottom-[15%] w-px bg-border/30" />
      )}
      {railPos.map(p => {
        const seq = userMsgs.findIndex(u => u.groupIdx === p.idx) + 1;
        const um = userMsgs.find(u => u.groupIdx === p.idx);
        const isActive = activeUserGroupIdx === p.idx;
        const isInView = inViewSet.has(p.idx);
        return (
          <div key={p.idx} className="absolute left-1/2 -translate-x-1/2" style={{ top: `${p.pct}%`, transform: 'translateY(-50%)' }}>
            <button
              onClick={() => onJump(p.idx)}
              onMouseEnter={() => onHover(p.idx)}
              onMouseLeave={() => onHover(null)}
              title={`第 ${seq} 轮对话`}
              className="flex items-center justify-center h-5 w-5 group"
            >
              <span className={`block rounded-full transition-all duration-150 ${
                isActive ? 'h-3 w-3 bg-pinnedBg ring-2 ring-pinnedBg/30' :
                isInView ? 'h-2.5 w-2.5 bg-railDot/70' :
                'h-2 w-2 bg-railDot group-hover:bg-railDot/80'
              } ${hoverUserIdx === p.idx ? 'scale-125' : ''}`} />
            </button>
            {hoverUserIdx === p.idx && um && (
              <div className="absolute left-6 top-1/2 -translate-y-1/2 z-20 w-72 bg-surface-2 border border-border rounded-lg shadow-xl p-2.5 pointer-events-none">
                <div className="text-fs-aux text-railDot mb-1 font-medium">第 {seq} 轮 · 用户消息</div>
                <div className="text-fs-body text-gray-300 line-clamp-3 break-all">{um.content}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
