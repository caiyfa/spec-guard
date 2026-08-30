/** StateView — T-1044 U1 原语：三态分离（B·Paper 形态）。
 *
 *  合并对象：45 处手写「加载中」+ 45 处手写「暂无」（方案 §一 E7，体验基线③）。
 *  规格：loading = shimmer 骨架条（不是 animate-pulse 文字）；empty = 虚线圆形图形 +
 *  衬线标题（B 阅读语言）+ 一句描述 + 可选 CTA；error = fail 徽章 + 原因 + 重试。
 *  文案口径集中：加载中统一「加载中…」。
 */
import type { ReactNode } from 'react';
import { Button } from './Button';
import { StatusBadge } from './StatusBadge';

export function StateView({ loading, error, onRetry, empty, emptyIcon, emptyTitle, emptyDesc, emptyCta, skeletonRows = 3 }: {
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: boolean;
  emptyIcon?: ReactNode;
  emptyTitle?: string;
  emptyDesc?: string;
  emptyCta?: { label: string; onClick: () => void };
  skeletonRows?: number;
}) {
  if (loading) {
    const widths = ['42%', '88%', '73%', '60%', '80%'];
    return (
      <div data-testid="stateview-loading" className="flex flex-col gap-2.5 py-4" aria-label="加载中…">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <div key={i} className="skeleton-bar h-3 rounded" style={{ width: widths[i % widths.length] }} />
        ))}
      </div>
    );
  }
  if (error) {
    return (
      <div data-testid="stateview-error" className="flex flex-col items-center gap-2.5 py-8 text-center">
        <StatusBadge status="fail" label="加载失败" />
        <div className="text-fs-body text-gray-400 max-w-[420px]">{error}</div>
        {onRetry && <Button size="sm" onClick={onRetry}>重试</Button>}
      </div>
    );
  }
  if (empty) {
    return (
      <div data-testid="stateview-empty" className="flex flex-col items-center gap-2.5 py-10 text-center">
        <span className="w-11 h-11 rounded-full border border-dashed border-gray-600 flex items-center justify-center text-gray-500">
          {emptyIcon || (
            <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="4.5" y="4.5" width="15" height="15" rx="2" /><path d="M8.5 12h7" />
            </svg>
          )}
        </span>
        <div className="font-display text-fs-title font-bold text-gray-200">{emptyTitle || '暂无数据'}</div>
        {emptyDesc && <div className="text-fs-aux text-gray-500 max-w-[420px]">{emptyDesc}</div>}
        {emptyCta && <Button variant="primary" size="sm" className="mt-1.5" onClick={emptyCta.onClick}>{emptyCta.label}</Button>}
      </div>
    );
  }
  return null;
}
