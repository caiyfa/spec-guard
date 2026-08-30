/**
 * ThemeSwitcher — K-043/K-044 主题与背景设置（K-045：独立弹窗模块 Modal portal 版）
 *
 * 顶栏图标按钮 → Modal（portal 到 body）居中弹窗。
 * 此前两版的教训：①absolute 下拉受页面容器裁剪；②fixed 弹窗被 frost 主题
 * header 的 backdrop-filter 劫持包含块，显示在顶部且被遮挡——portal 根治。
 */

import { useRef, useState, useEffect } from 'react';
import { THEMES, applyTheme, useThemeId, applyBackground, useBg, BG_MAX_BYTES, compressImage, applyRailDot, useRailDot, applyPinnedBg, usePinnedBg } from '../theme';
import Modal from './Modal';

export default function ThemeSwitcher() {
  const [open, setOpen] = useState(false);
  const current = useThemeId();
  const bg = useBg();
  const [bgError, setBgError] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  // 多轮对话导航：图标颜色 + 置顶背景
  const railDot = useRailDot();
  const pinnedBg = usePinnedBg();
  const [dotHex, setDotHex] = useState('#c8c8d2');
  const [pinnedHex, setPinnedHex] = useState('#58a6ff');
  useEffect(() => {
    const toHex = (rgb: string): string => {
      const p = rgb.trim().split(/\s+/);
      if (p.length !== 3) return '';
      return '#' + p.map(n => parseInt(n).toString(16).padStart(2, '0')).join('');
    };
    const dotRgb = railDot || getComputedStyle(document.documentElement).getPropertyValue('--rail-dot').trim();
    const dh = toHex(dotRgb); if (dh) setDotHex(dh);
    const pinnedRgb = pinnedBg || getComputedStyle(document.documentElement).getPropertyValue('--pinned-bg').trim();
    const ph = toHex(pinnedRgb); if (ph) setPinnedHex(ph);
  }, [railDot, pinnedBg, current]);

  const meta = THEMES.find(t => t.id === current);

  const handleBgFile = async (f: File | undefined) => {
    setBgError('');
    if (!f) return;
    if (f.size > BG_MAX_BYTES) {
      setBgError(`图片超过 ${BG_MAX_BYTES / 1024 / 1024}MB，请选择更小的图片`);
      return;
    }
    setUploading(true);
    try {
      // canvas 压缩（≤1920px/jpeg0.82）——原图 dataURL 可达 4MB，直接存 localStorage 会超限丢图
      const dataUrl = await compressImage(f);
      const ok = applyBackground({ image: dataUrl });
      if (!ok) setBgError('图片压缩后仍超出浏览器存储上限，请换更小的图片');
    } catch (e: any) {
      setBgError(`图片处理失败：${e?.message || e}`);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={`主题：${meta?.name}（点击切换）`}
        className="w-7 h-7 flex items-center justify-center rounded-lg text-fs-lead text-gray-400 hover:text-info hover:bg-surface-3"
      >
        {meta?.icon || '🎨'}
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="🎨 外观设置" width={300}>
        {/* 主题列表 */}
        <div className="p-2">
          <div className="px-1.5 py-1 text-fs-aux text-gray-600">界面主题</div>
          {THEMES.map(t => (
            <button key={t.id}
              onClick={() => applyTheme(t.id)}
              className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-fs-body transition-colors ${
                t.id === current ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
              }`}>
              <span className="flex-shrink-0 rounded border border-border/60 overflow-hidden flex" style={{ width: 36, height: 22 }}>
                <span className="h-full" style={{ width: '55%', background: t.swatch[0] }} />
                <span className="h-full" style={{ width: '30%', background: t.swatch[1] }} />
                <span className="h-full" style={{ width: '15%', background: t.swatch[2] }} />
              </span>
              <span className="flex-1 text-left">{t.icon} {t.name}</span>
              {t.id === current && <span>✓</span>}
            </button>
          ))}
        </div>

        {/* K-044：背景图片设置 */}
        <div className="mx-2 mb-2 pt-2 border-t border-border/60 px-1.5 pb-1">
          <div className="flex items-center justify-between py-1">
            <span className="text-fs-aux text-gray-600">背景图片</span>
            <span className="flex gap-2">
              <input ref={fileRef} type="file" accept="image/*" className="hidden"
                onChange={e => handleBgFile(e.target.files?.[0])} />
              <button onClick={() => fileRef.current?.click()} disabled={uploading}
                className="text-fs-body text-info hover:underline disabled:opacity-50">
                {uploading ? '处理中…' : bg.image ? '更换' : '上传'}
              </button>
              {bg.image && (
                <button onClick={() => applyBackground({ image: '' })}
                  className="text-fs-body text-gray-500 hover:text-fail">
                  清除
                </button>
              )}
            </span>
          </div>
          {bg.image && (
            <>
              <label className="flex items-center gap-2 py-1" title="越高图片越透（越看不清）">
                <span className="text-fs-body text-gray-500 w-11">透明度</span>
                <input type="range" min={0} max={100} value={bg.transparency}
                  onChange={e => applyBackground({ transparency: Number(e.target.value) })}
                  className="flex-1 h-1 accent-info" />
                <span className="text-fs-body text-gray-500 w-9 text-right">{bg.transparency}%</span>
              </label>
              <label className="flex items-center gap-2 py-1" title="越高图片越模糊">
                <span className="text-fs-body text-gray-500 w-11">模糊度</span>
                <input type="range" min={0} max={100} value={bg.blurPct}
                  onChange={e => applyBackground({ blurPct: Number(e.target.value) })}
                  className="flex-1 h-1 accent-info" />
                <span className="text-fs-body text-gray-500 w-9 text-right">{bg.blurPct}%</span>
              </label>
            </>
          )}
          {bgError && <div className="text-fs-aux text-fail py-0.5">{bgError}</div>}
          {!bg.image && !bgError && (
            <div className="text-fs-aux text-gray-700 py-0.5">上传后建议搭配「🧊 磨砂」主题</div>
          )}
        </div>

        {/* 多轮对话导航 */}
        <div className="mx-2 mb-2 pt-2 border-t border-border/60 px-1.5 pb-1">
          <div className="px-1.5 py-1 text-fs-aux text-gray-600">对话导航</div>
          {/* 图标颜色 */}
          <div className="flex items-center justify-between py-1 px-1.5">
            <span className="text-fs-body text-gray-500">图标颜色</span>
            <span className="flex items-center gap-2">
              <input type="color" value={dotHex}
                onChange={e => applyRailDot(e.target.value)}
                className="w-5 h-5 rounded cursor-pointer bg-transparent border border-border/60"
                title="多轮对话图标颜色" />
              {railDot && (
                <button onClick={() => applyRailDot('')}
                  className="text-fs-body text-gray-500 hover:text-fail">重置</button>
              )}
            </span>
          </div>
          {/* 置顶背景 */}
          <div className="flex items-center justify-between py-1 px-1.5">
            <span className="text-fs-body text-gray-500">置顶背景</span>
            <span className="flex items-center gap-2">
              <input type="color" value={pinnedHex}
                onChange={e => applyPinnedBg(e.target.value)}
                className="w-5 h-5 rounded cursor-pointer bg-transparent border border-border/60"
                title="置顶消息背景颜色" />
              {pinnedBg && (
                <button onClick={() => applyPinnedBg('')}
                  className="text-fs-body text-gray-500 hover:text-fail">重置</button>
              )}
            </span>
          </div>
        </div>
      </Modal>
    </>
  );
}
