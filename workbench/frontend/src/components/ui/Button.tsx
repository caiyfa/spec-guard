/** Button — T-1044 U1 原语：按钮三档（B·Paper 形态）。
 *
 *  合并对象：手写按钮群 + 三种危险红（方案 §一 E5）。规格：
 *  - primary：墨色实心（bg-gray-100/text-surface-2，随主题自动反转的「编辑印章」），
 *    每操作区至多 1 个；
 *  - ghost：默认档（描边 + 纸面底）；
 *  - danger：统一软红 bg-fail/12 text-fail border-fail/35（消灭三种危险红）。
 */
import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md';

const VARIANT_CLS: Record<ButtonVariant, string> = {
  primary: 'bg-gray-100 text-surface-2 font-semibold hover:opacity-85',
  ghost: 'border border-border text-gray-300 bg-surface-2 hover:border-gray-500 hover:text-gray-100',
  danger: 'bg-fail/12 text-fail border border-fail/35 font-semibold hover:bg-fail/20',
};

const SIZE_CLS: Record<ButtonSize, string> = {
  sm: 'text-fs-aux px-2.5 py-1 gap-1',
  md: 'text-fs-body px-3.5 py-1.5 gap-1.5',
};

export function Button({ variant = 'ghost', size = 'md', icon, className = '', children, ...rest }: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  children?: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center rounded-md leading-none whitespace-nowrap
        disabled:opacity-40 disabled:cursor-not-allowed ${VARIANT_CLS[variant]} ${SIZE_CLS[size]} ${className}`}
    >
      {icon && <span className="inline-flex w-3.5 h-3.5 flex-shrink-0 items-center justify-center">{icon}</span>}
      {children}
    </button>
  );
}
