/**
 * ImageLightbox — 图片大图预览弹层（时间轴缩略图点击就地放大，不跳新标签页）
 *
 * 与 Modal 同约定：portal 到 document.body（fixed 定位会被祖先的
 * transform/backdrop-filter 劫持为包含块，frost 主题 header 尤甚）。
 * 关闭三通道：ESC / 点遮罩 / ✕；图片等比放大至 92vw × 82vh。
 */

import { useEffect } from 'react';
import { createPortal } from 'react-dom';

interface ImageLightboxProps {
  url: string;
  caption?: string;
  onClose: () => void;
}

export default function ImageLightbox({ url, caption, onClose }: ImageLightboxProps) {
  // ESC 快速关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-6"
      style={{ background: 'rgb(var(--overlay) / 0.8)' }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="relative" onClick={e => e.stopPropagation()}>
        <button
          onClick={onClose}
          className="absolute -top-7 right-0 text-lg leading-none text-gray-400 hover:text-white"
          title="关闭（Esc）"
        >✕</button>
        <img
          src={url}
          alt="图片大图"
          className="max-w-[92vw] max-h-[82vh] rounded-lg shadow-2xl"
        />
        {caption && (
          <div className="mt-2 text-center text-fs-body text-gray-300">{caption}</div>
        )}
      </div>
    </div>,
    document.body,
  );
}
