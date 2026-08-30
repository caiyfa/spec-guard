import { useEffect, useRef } from 'react';

// T-1026：「更多」面板选择器——低频页签聚合入口（对标 VS Code 侧栏「打开标签页」空态卡片网格）。
// 纯展示组件：页签清单/计数/激活态由 SidePanel 装配传入，选择后回调并由父级关闭；
// 自身只负责外点关闭与 Escape 关闭。

export interface MorePanelItem {
  id: string;
  emoji: string;   // 注册表 label 首段（emoji + 空格 + 名称）
  name: string;
  count?: number;  // 足迹类页签活动计数（阅读/更新足迹），0 不显示
}

export function MorePanelsMenu({ items, activeId, onSelect, onClose }: {
  items: MorePanelItem[];
  activeId?: string;  // 当前激活的低频页签（卡片高亮）
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  return (
    <div ref={ref} data-testid="more-panels-menu"
      className="absolute right-2 top-full mt-1 z-50 w-72 max-w-[calc(100%-1rem)] rounded-lg border border-border bg-surface-1 shadow-xl p-4">
      <div className="text-center">
        <div className="text-sm font-semibold text-gray-200">打开面板</div>
        <div className="text-fs-body text-gray-500 mt-0.5">低频页签收在此处，选择要在侧边面板中打开的页签。</div>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(80px,1fr))] gap-2 mt-3">
        {items.map(t => (
          <button key={t.id}
            onClick={() => { onSelect(t.id); onClose(); }}
            className={`relative flex flex-col items-center gap-1 rounded-md border px-1 py-2.5 transition-colors ${
              activeId === t.id
                ? 'border-info bg-surface-3/60 text-gray-200'
                : 'border-border bg-surface-2/60 text-gray-400 hover:border-gray-600 hover:text-gray-200'
            }`}>
            <span className="text-base leading-none">{t.emoji}</span>
            <span className="text-fs-body leading-tight text-center">{t.name}</span>
            {!!t.count && t.count > 0 && (
              <span className="absolute top-1 right-1 min-w-[16px] px-1 rounded-full bg-info/20 text-info text-fs-aux leading-4 text-center">
                {t.count > 99 ? '99+' : t.count}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
