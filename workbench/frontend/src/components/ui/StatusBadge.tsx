/** StatusBadge — T-1044 U1 原语：六状态唯一徽章（B·Paper 形态）。
 *
 *  合并对象：现网 ≥6 种徽章做法（方案 §一 E3）。规格：淡填 12% 无描边药丸 +
 *  duotone 图形符（状态退出 emoji，方案 §二.2）；颜色只来自 6 个状态变量，
 *  深/浅主题自适应（fs-aux 档，方案 §3.1）。neutral 用于「未运行/待触发」。
 */
import type { ReactNode } from 'react';

export type BadgeStatus = 'pass' | 'fail' | 'skip' | 'blocked' | 'warn' | 'info' | 'neutral';

/** 统一图形符（duotone：淡填底 + 全彩笔形，stroke 1.5 / 24 视窗）——非 emoji */
export const STATUS_GLYPHS: Record<BadgeStatus, ReactNode> = {
  pass: (<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14" /><path d="M7.8 12.4l2.7 2.7 5.7-6.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></>),
  fail: (<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14" /><path d="M9 9l6 6M15 9l-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></>),
  skip: (<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14" /><path d="M8 12h8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></>),
  blocked: (<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14" /><circle cx="12" cy="12" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M8.3 8.3l7.4 7.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>),
  warn: (<><path d="M12 4.2L21 20H3L12 4.2z" fill="currentColor" opacity=".14" /><path d="M12 9.8v4.8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /><circle cx="12" cy="17" r=".9" fill="currentColor" /></>),
  info: (<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14" /><path d="M12 11v5.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /><circle cx="12" cy="7.8" r=".9" fill="currentColor" /></>),
  neutral: (<><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".12" /><circle cx="12" cy="12" r="3" fill="currentColor" opacity=".55" /></>),
};

const STATUS_CLS: Record<BadgeStatus, string> = {
  pass: 'bg-pass/12 text-pass',
  fail: 'bg-fail/12 text-fail',
  skip: 'bg-skip/12 text-skip',
  blocked: 'bg-blocked/12 text-blocked',
  warn: 'bg-warn/12 text-warn',
  info: 'bg-info/12 text-info',
  neutral: 'bg-gray-600/15 text-gray-400',
};

export function StatusBadge({ status, label, size = 'md', title, className = '' }: {
  status: BadgeStatus;
  label: ReactNode;
  size?: 'sm' | 'md';
  title?: string;
  className?: string;
}) {
  const sizeCls = size === 'sm' ? 'text-fs-micro px-1.5 py-0.5 gap-1' : 'text-fs-aux px-2 py-1 gap-1.5';
  const iconCls = size === 'sm' ? 'w-2.5 h-2.5' : 'w-3 h-3';
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full font-semibold whitespace-nowrap leading-none ${STATUS_CLS[status]} ${sizeCls} ${className}`}
    >
      <svg viewBox="0 0 24 24" className={`${iconCls} flex-shrink-0`} aria-hidden="true">{STATUS_GLYPHS[status]}</svg>
      {label}
    </span>
  );
}
