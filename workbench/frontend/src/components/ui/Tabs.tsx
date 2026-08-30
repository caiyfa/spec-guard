/** Tabs — T-1044 U1 原语：全站唯一下划线页签（B·Paper 形态）。
 *
 *  合并对象：4 种页签做法（方案 §一 E4）。规格：下划线式为全站唯一
 *  （segment 仅数据页保留，不在本原语内）；选中 = 前景色 + 墨色 2px 下划线
 *  （B 语言：强调色不滥用，计数丸才用 info 淡填）；计数丸收进签内不贴边。
 */
import type { ReactNode } from 'react';

export interface TabItem {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  count?: number;         // 0/undefined 不显示
  title?: string;
  closable?: boolean;     // 文件页签类：显示 ✕（点击触发 onClose，不触发选中）
  onClose?: () => void;
}

export function Tabs({ items, activeId, onChange, bordered = true, className = '' }: {
  items: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  /** 底部分割线（拼接多条页签带时关闭，由外层统一描线） */
  bordered?: boolean;
  className?: string;
}) {
  return (
    <div role="tablist" className={`flex items-center ${bordered ? 'border-b border-border' : ''} ${className}`}>
      {items.map(t => {
        const on = t.id === activeId;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={on}
            title={t.title}
            onClick={() => onChange(t.id)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 text-fs-body whitespace-nowrap flex-shrink-0
              border-b-2 -mb-px transition-colors
              ${on ? 'border-gray-100 text-gray-100 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-200'}`}
          >
            {t.icon && <span className="inline-flex w-3 h-3 items-center justify-center">{t.icon}</span>}
            <span className="max-w-[140px] truncate">{t.label}</span>
            {!!t.count && t.count > 0 && (
              <span className={`text-fs-micro rounded-full px-1.5 py-px leading-none
                ${on ? 'bg-info/12 text-info' : 'bg-gray-600/15 text-gray-400'}`}>
                {t.count > 99 ? '99+' : t.count}
              </span>
            )}
            {t.closable && (
              <span
                role="button"
                aria-label={`关闭 ${t.title || t.label}`}
                onClick={e => { e.stopPropagation(); t.onClose?.(); }}
                className="text-gray-600 hover:text-fail ml-0.5 leading-none"
              >✕</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
