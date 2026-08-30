/** icons — T-1044 U2：动作图标共享集（B·Paper duotone，内联 SVG 自绘，零依赖）。
 *
 *  图标策略 A（方案 §二）：页签/菜单 emoji 保留为情绪位；**动作与状态退出 emoji**。
 *  本文件是动作图标唯一事实源：stroke 1.5 圆角笔帽 + 关键形淡填（印刷 duotone），
 *  24 视窗设计，13~16px 使用清晰。色随 currentColor。
 */
import type { ReactNode } from 'react';

const GLYPHS: Record<string, ReactNode> = {
  export: (<><path d="M12 4v10.5M8 10.5l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /><path d="M5 19.5h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>),
  focus: (<path d="M9 4.5H4.5V9M15 4.5h4.5V9M9 19.5H4.5V15M15 19.5h4.5V15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />),
  collapseLeft: (<path d="M10.5 6L5 12l5.5 6M18 6l-5.5 6L18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />),
  collapseRight: (<path d="M13.5 6L19 12l-5.5 6M6 6l5.5 6L6 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />),
  panel: (<><rect x="3.5" y="5" width="17" height="14" rx="1.5" fill="currentColor" opacity=".1" /><rect x="3.5" y="5" width="17" height="14" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M14.5 5v14" stroke="currentColor" strokeWidth="1.5" /></>),
  close: (<path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />),
  copy: (<><rect x="9" y="9" width="11" height="11" rx="1.8" fill="currentColor" opacity=".1" /><rect x="9" y="9" width="11" height="11" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M15 5.5V5a1.5 1.5 0 0 0-1.5-1.5h-8A1.5 1.5 0 0 0 4 5v8a1.5 1.5 0 0 0 1.5 1.5H6" fill="none" stroke="currentColor" strokeWidth="1.5" /></>),
  pin: (<><path d="M9 4h6l-.7 6.2 3.2 3.3v2H6.5v-2l3.2-3.3L9 4z" fill="currentColor" opacity=".14" /><path d="M9 4h6l-.7 6.2 3.2 3.3v2H6.5v-2l3.2-3.3L9 4z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M12 15.5V21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>),
  refresh: (<><path d="M19 12a7 7 0 1 1-2-4.9" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /><path d="M19 4v4.5h-4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></>),
  locate: (<><circle cx="12" cy="12" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /><circle cx="12" cy="12" r="1.2" fill="currentColor" /></>),
  more: (<g fill="currentColor" opacity=".85"><rect x="4" y="4" width="4.4" height="4.4" rx="1" /><rect x="9.8" y="4" width="4.4" height="4.4" rx="1" /><rect x="15.6" y="4" width="4.4" height="4.4" rx="1" /><rect x="4" y="9.8" width="4.4" height="4.4" rx="1" /><rect x="9.8" y="9.8" width="4.4" height="4.4" rx="1" /><rect x="15.6" y="9.8" width="4.4" height="4.4" rx="1" /><rect x="4" y="15.6" width="4.4" height="4.4" rx="1" /><rect x="9.8" y="15.6" width="4.4" height="4.4" rx="1" /><rect x="15.6" y="15.6" width="4.4" height="4.4" rx="1" /></g>),
  plus: (<path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />),
  send: (<><path d="M20 4L4 11.2l5.8 2L12 19l8-15z" fill="currentColor" opacity=".1" /><path d="M20 4L4 11.2l5.8 2L12 19l8-15z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M9.8 13.2L14.5 8.5" stroke="currentColor" strokeWidth="1.5" /></>),
  search: (<><circle cx="11" cy="11" r="5.5" fill="currentColor" opacity=".08" /><circle cx="11" cy="11" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M15.2 15.2L20 20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>),
  file: (<><path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5l-5-5z" fill="currentColor" opacity=".08" /><path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5l-5-5z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M13.5 3.5V8.5H18.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></>),
  maximize: (<><path d="M9 4.5H4.5V9M15 4.5h4.5V9M9 19.5H4.5V15M15 19.5h4.5V15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /><path d="M4.5 4.5L9 9M19.5 4.5L15 9M4.5 19.5L9 15M19.5 19.5L15 15" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" opacity=".55" /></>),
  minimize: (<path d="M4.5 9h5V4.5M19.5 9h-5V4.5M4.5 15h5v4.5M19.5 15h-5v4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />),
};

export type IconName = keyof typeof GLYPHS;

export function Icon({ name, size = 14, className = '' }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={`flex-shrink-0 ${className}`} aria-hidden="true">
      {GLYPHS[name]}
    </svg>
  );
}
