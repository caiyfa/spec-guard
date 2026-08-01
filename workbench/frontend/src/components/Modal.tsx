/**
 * Modal — K-045 通用弹窗模块（portal 到 document.body）
 *
 * 为什么必须 portal：fixed 定位会被祖先的 transform/filter/backdrop-filter
 * 「劫持」为包含块（frost 主题的 header 有 backdrop-filter）——弹窗会相对
 * header 定位并显示在顶部被裁剪。portal 到 body 后彻底脱离任何祖先上下文。
 *
 * 用法：
 *   <Modal open={open} onClose={...} title="标题" width={288}>内容</Modal>
 */

import { useEffect } from 'react';
import { createPortal } from 'react-dom';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  width?: number;
  children: React.ReactNode;
}

export default function Modal({ open, onClose, title, width = 320, children }: ModalProps) {
  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      style={{ background: 'rgb(var(--overlay) / 0.55)' }}
      onClick={onClose}
    >
      <div
        className="bg-surface-2 border border-border rounded-2xl max-h-[85vh] overflow-y-auto"
        style={{ width, boxShadow: 'var(--shadow)' }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {title && (
          <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-border/60 sticky top-0 bg-surface-2 z-10">
            <span className="text-xs font-medium text-gray-300">{title}</span>
            <button onClick={onClose} className="text-gray-600 hover:text-gray-300 text-sm leading-none">✕</button>
          </div>
        )}
        {children}
      </div>
    </div>,
    document.body,
  );
}
