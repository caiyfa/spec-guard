/** IconButton — T-1044 U2：图标按钮统一 ghost 档（B·Paper 形态）。
 *
 *  规格：26×26 方形 ghost（hover 浮底），active 态 info 淡填（表示「已启用」）；
 *  必须给 label（同时作 aria-label 与 title——图标按钮无可见文字，可达性兜底）。
 */
import type { ButtonHTMLAttributes, ReactNode } from 'react';

export function IconButton({ label, active, className = '', children, ...rest }: {
  label: string;
  active?: boolean;
  children: ReactNode;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'>) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={`w-[26px] h-[26px] rounded-md inline-flex items-center justify-center flex-shrink-0 transition-colors
        disabled:opacity-40 disabled:cursor-not-allowed
        ${active ? 'text-info bg-info/10' : 'text-gray-500 hover:text-gray-100 hover:bg-surface-3'} ${className}`}
    >
      {children}
    </button>
  );
}
