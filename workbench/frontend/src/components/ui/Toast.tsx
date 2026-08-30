/** Toast — T-1044 U1 原语：单例 Toast 容器（B·Paper 形态）。
 *
 *  合并对象：散落的手写 banner（方案 §一 E7）。规格：浮起的纸条
 *  （bg-surface-2 + 边框 + 主题阴影，不动用状态色铺底）；状态用图形符表达；
 *  自动 3.6s 消失，可手动关。用法：
 *    根组件挂一次 <ToastContainer />；任意处调 toast.ok/fail/info('文案')。
 */
import { useEffect, useState } from 'react';
import { STATUS_GLYPHS, type BadgeStatus } from './StatusBadge';

export interface ToastItem { id: number; kind: BadgeStatus; text: string }

type Listener = (items: ToastItem[]) => void;
let seq = 0;
let items: ToastItem[] = [];
const listeners = new Set<Listener>();

function emit() {
  listeners.forEach(fn => fn(items));
}
function push(kind: BadgeStatus, text: string) {
  const id = ++seq;
  items = [...items, { id, kind, text }];
  emit();
  window.setTimeout(() => dismiss(id), 3600);
}
function dismiss(id: number) {
  items = items.filter(t => t.id !== id);
  emit();
}

/** 全局 Toast API（不挂容器时静默丢弃——诚实降级不炸页面） */
export const toast = {
  ok: (text: string) => push('pass', text),
  fail: (text: string) => push('fail', text),
  info: (text: string) => push('info', text),
  warn: (text: string) => push('warn', text),
};

const KIND_TEXT: Record<string, string> = {
  pass: 'text-pass', fail: 'text-fail', info: 'text-info', warn: 'text-warn',
  skip: 'text-skip', blocked: 'text-blocked', neutral: 'text-gray-400',
};

export function ToastContainer() {
  const [list, setList] = useState<ToastItem[]>(items);
  useEffect(() => {
    const fn: Listener = v => setList([...v]);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);
  if (!list.length) return null;
  return (
    <div data-testid="toast-container" className="fixed bottom-4 right-4 z-[200] flex flex-col gap-2 w-80">
      {list.map(t => (
        <div
          key={t.id}
          role="status"
          className="flex items-start gap-2.5 rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-fs-body text-gray-300"
          style={{ boxShadow: 'var(--shadow)' }}
        >
          <svg viewBox="0 0 24 24" className={`w-4 h-4 flex-shrink-0 mt-px ${KIND_TEXT[t.kind]}`} aria-hidden="true">
            {STATUS_GLYPHS[t.kind]}
          </svg>
          <span className="flex-1 leading-5">{t.text}</span>
          <button
            aria-label="关闭"
            onClick={() => dismiss(t.id)}
            className="text-gray-600 hover:text-gray-300 leading-none flex-shrink-0"
          >✕</button>
        </div>
      ))}
    </div>
  );
}
