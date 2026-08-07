/**
 * theme.ts — K-043 主题管理（CSS 变量引擎的 JS 侧）
 *
 * - applyTheme：切换 <html data-theme> + localStorage 持久化 + 事件广播
 * - useTheme：React hook（第三方组件按主题切配置：Monaco/高亮/mermaid/React Flow）
 * - JS_THEME_TOKENS：内联样式场景的主题常量表（React Flow 节点/MiniMap 等无法走 CSS 变量的地方）
 */

import { useSyncExternalStore } from 'react';

export const THEME_CHANGED_EVENT = 'sg-theme-changed';
const STORAGE_KEY = 'sg_theme';

export interface ThemeMeta {
  id: string;
  name: string;
  icon: string;
  /** 切换器里的色卡预览 [底色, 卡片, 强调] */
  swatch: [string, string, string];
  dark: boolean;
}

export const THEMES: ThemeMeta[] = [
  { id: 'midnight', name: '暗夜蓝', icon: '🌌', swatch: ['#0d1117', '#161b22', '#58a6ff'], dark: true },
  { id: 'dusk', name: '暮光紫', icon: '🌆', swatch: ['#120e1c', '#1a1428', '#a78bfa'], dark: true },
  { id: 'oled', name: '墨黑', icon: '🌑', swatch: ['#000000', '#0e0e10', '#60cdff'], dark: true },
  { id: 'light', name: '明亮白', icon: '☀️', swatch: ['#f6f8fa', '#ffffff', '#2563eb'], dark: false },
  { id: 'frost', name: '磨砂', icon: '🧊', swatch: ['#101824', '#182232', '#22d3ee'], dark: true },
];

const FALLBACK = THEMES[0];

export function getThemeId(): string {
  const id = localStorage.getItem(STORAGE_KEY) || FALLBACK.id;
  return THEMES.some(t => t.id === id) ? id : FALLBACK.id;
}

export function getThemeMeta(id = getThemeId()): ThemeMeta {
  return THEMES.find(t => t.id === id) || FALLBACK;
}

/** 应用主题（防 FOUC 脚本外的一切切换都走这里） */
export function applyTheme(id: string) {
  const meta = getThemeMeta(id);
  document.documentElement.dataset.theme = meta.id;
  localStorage.setItem(STORAGE_KEY, meta.id);
  window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, { detail: meta.id }));
}

function subscribe(cb: () => void) {
  const h = () => cb();
  window.addEventListener(THEME_CHANGED_EVENT, h);
  return () => window.removeEventListener(THEME_CHANGED_EVENT, h);
}

/** 当前主题 id（响应式） */
export function useThemeId(): string {
  return useSyncExternalStore(subscribe, getThemeId);
}

/** 当前主题元数据（含 dark 标志，第三方组件选配置用） */
export function useTheme(): ThemeMeta {
  return getThemeMeta(useThemeId());
}

/** 初始化（main.tsx 调用；index.html 内联脚本已防 FOUC，这里做对齐兜底） */
export function initTheme() {
  document.documentElement.dataset.theme = getThemeId();
  applyBackground();  // K-044：恢复背景图设置
  // 恢复自定义导航点颜色
  const savedRail = getRailDot();
  if (savedRail) document.documentElement.style.setProperty('--rail-dot', savedRail);
  // 恢复自定义置顶背景颜色
  const savedPinned = getPinnedBg();
  if (savedPinned) document.documentElement.style.setProperty('--pinned-bg', savedPinned);
}

// ── JS 侧主题常量表（无法走 CSS 变量的内联样式场景：React Flow/Monaco/高亮/mermaid）──
export interface JsThemeTokens {
  dark: boolean;
  monaco: 'vs-dark' | 'vs';
  mermaid: 'dark' | 'default';
  codeBg: string;        // 代码块容器底（替代写死的 #0a0e14）
  nodeBg: string;        // DAG 节点底
  nodeSubBg: string;     // DAG 节点次级区
  nodeText: string;      // DAG 节点主文字
  nodeSubText: string;   // DAG 节点次文字
  edgeStroke: string;
  rfBackground: string;  // React Flow 画布点阵色
  minimapBg: string;
  minimapMask: string;
  minimapNode: string;
}

const DARK_TOKENS: Omit<JsThemeTokens, 'dark' | 'monaco' | 'mermaid' | 'rfBackground'> = {
  codeBg: '#0a0e14', nodeBg: '#161b22', nodeSubBg: '#21262d', nodeText: '#e6edf3', nodeSubText: '#9da7b3',
  edgeStroke: '#2d3646', minimapBg: '#0d1117', minimapMask: 'rgba(13,17,23,0.8)', minimapNode: '#161b22',
};

export const JS_THEME_TOKENS: Record<string, JsThemeTokens> = {
  midnight: { ...DARK_TOKENS, dark: true, monaco: 'vs-dark', mermaid: 'dark', rfBackground: '#2d3646' },
  dusk: {
    ...DARK_TOKENS, dark: true, monaco: 'vs-dark', mermaid: 'dark',
    codeBg: '#0e0a18', nodeBg: '#1a1428', nodeSubBg: '#261e38', nodeText: '#ede9fe', nodeSubText: '#aca4c4',
    edgeStroke: '#3a2f52', minimapBg: '#120e1c', minimapMask: 'rgba(18,14,28,0.8)', minimapNode: '#1a1428',
    rfBackground: '#3a2f52',
  },
  oled: {
    ...DARK_TOKENS, dark: true, monaco: 'vs-dark', mermaid: 'dark',
    codeBg: '#060608', nodeBg: '#0e0e10', nodeSubBg: '#1a1a1e', nodeText: '#f5f5f5', nodeSubText: '#a8a8a8',
    edgeStroke: '#2c2c32', minimapBg: '#000000', minimapMask: 'rgba(0,0,0,0.8)', minimapNode: '#0e0e10',
    rfBackground: '#2c2c32',
  },
  light: {
    dark: false, monaco: 'vs', mermaid: 'default',
    codeBg: '#f6f8fa', nodeBg: '#ffffff', nodeSubBg: '#eef2f6', nodeText: '#1f2937', nodeSubText: '#6b7280',
    edgeStroke: '#d0d7e0', minimapBg: '#ffffff', minimapMask: 'rgba(246,248,250,0.8)', minimapNode: '#eef2f6',
    rfBackground: '#d0d7e0',
  },
  frost: {
    ...DARK_TOKENS, dark: true, monaco: 'vs-dark', mermaid: 'dark',
    codeBg: '#0c121c', nodeBg: '#182232', nodeSubBg: '#24324a', nodeText: '#e0eef7', nodeSubText: '#9eb8c9',
    edgeStroke: '#465a73', minimapBg: '#101824', minimapMask: 'rgba(16,24,36,0.8)', minimapNode: '#182232',
    rfBackground: '#465a73',
  },
};

/** 当前主题的 JS 常量（非 hook，组件内配合 useThemeId 使用） */
export function getJsTokens(id = getThemeId()): JsThemeTokens {
  return JS_THEME_TOKENS[id] || JS_THEME_TOKENS.midnight;
}

/** 响应式 JS 常量 */
export function useJsTokens(): JsThemeTokens {
  return getJsTokens(useThemeId());
}

// ── K-044：自定义背景图（dataURL 持久化 + 透明度/模糊度，均百分比语义）──
const BG_KEYS = { image: 'sg_bg_image', transparency: 'sg_bg_transparency', blurPct: 'sg_bg_blur_pct' } as const;
export const BG_MAX_BYTES = 8 * 1024 * 1024;  // 原图上限（上传时 canvas 压缩到 ≤1920px/jpeg0.82，存的是压缩后）

/** 上传压缩：背景图不需要原图分辨率——缩放至 ≤1920 宽 + JPEG 0.82，dataURL 通常 <500KB，
 *  根治原图 dataURL ~4MB 触发 localStorage QuotaExceededError 静默丢失的问题 */
export function compressImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, 1920 / img.width);
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) { reject(new Error('canvas 不可用')); return; }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL('image/jpeg', 0.82));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('图片解码失败')); };
    img.src = url;
  });
}

export interface BgSetting {
  image: string;
  transparency: number;  // 透明度 0~100：越高图片越看不清（opacity = 1 - t/100）
  blurPct: number;       // 模糊度 0~100：映射到 0~20px
}

export function getBg(): BgSetting {
  return {
    image: localStorage.getItem(BG_KEYS.image) || '',
    transparency: Math.min(100, Math.max(0, parseInt(localStorage.getItem(BG_KEYS.transparency) || '50', 10) || 50)),
    blurPct: Math.min(100, Math.max(0, parseInt(localStorage.getItem(BG_KEYS.blurPct) || '0', 10) || 0)),
  };
}

/** 应用背景到 <html>（vars + data-bg 标记），并广播复用主题事件让 UI 刷新。
 *  返回 false = localStorage 写入失败（超限）——调用方必须提示用户（不得静默丢图） */
export function applyBackground(patch: Partial<BgSetting> = {}): boolean {
  const cur = { ...getBg(), ...patch };
  const el = document.documentElement;
  if (cur.image) {
    el.dataset.bg = '1';
    el.style.setProperty('--bg-image', `url("${cur.image}")`);
  } else {
    delete el.dataset.bg;
    el.style.removeProperty('--bg-image');
  }
  el.style.setProperty('--bg-opacity', String(1 - cur.transparency / 100));
  el.style.setProperty('--bg-blur', `${(cur.blurPct * 0.2).toFixed(1)}px`);
  let persisted = true;
  try {
    if (cur.image) localStorage.setItem(BG_KEYS.image, cur.image);
    else localStorage.removeItem(BG_KEYS.image);
    localStorage.setItem(BG_KEYS.transparency, String(cur.transparency));
    localStorage.setItem(BG_KEYS.blurPct, String(cur.blurPct));
  } catch {
    persisted = false;  // QuotaExceededError：本次会话内仍可见，但刷新会丢——必须告知
  }
  window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, { detail: getThemeId() }));
  return persisted;
}

/** 响应式背景设置（快照取三项存储值拼接，bg 变更即触发重渲） */
export function useBg(): BgSetting {
  useSyncExternalStore(subscribe, () =>
    `${localStorage.getItem(BG_KEYS.image) ? 1 : 0}|${localStorage.getItem(BG_KEYS.transparency)}|${localStorage.getItem(BG_KEYS.blurPct)}`);
  return getBg();
}

// ── 多轮对话导航点自定义颜色 ──
const RAIL_KEY = 'sg_rail_dot';

function hexToRgbTriplet(hex: string): string {
  const m = hex.match(/^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i);
  if (!m) return '';
  return `${parseInt(m[1], 16)} ${parseInt(m[2], 16)} ${parseInt(m[3], 16)}`;
}

function rgbTripletToHex(rgb: string): string {
  const p = rgb.trim().split(/\s+/);
  if (p.length !== 3) return '';
  return '#' + p.map(n => parseInt(n).toString(16).padStart(2, '0')).join('');
}

/** 已保存的自定义颜色（RGB 三元组，空串=未自定义） */
export function getRailDot(): string {
  return localStorage.getItem(RAIL_KEY) || '';
}

/** 设置自定义导航点颜色（hex 输入，空串=重置为主题默认） */
export function applyRailDot(hex: string): void {
  const el = document.documentElement;
  if (hex) {
    const rgb = hexToRgbTriplet(hex);
    if (rgb) {
      el.style.setProperty('--rail-dot', rgb);
      localStorage.setItem(RAIL_KEY, rgb);
    }
  } else {
    el.style.removeProperty('--rail-dot');
    localStorage.removeItem(RAIL_KEY);
  }
  window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, { detail: getThemeId() }));
}

/** 响应式：自定义导航点颜色变化时触发重渲 */
export function useRailDot(): string {
  useSyncExternalStore(subscribe, () => localStorage.getItem(RAIL_KEY) || '');
  return getRailDot();
}

// ── 置顶消息背景自定义颜色 ──
const PINNED_KEY = 'sg_pinned_bg';

/** 已保存的自定义置顶背景颜色（RGB 三元组，空串=未自定义） */
export function getPinnedBg(): string {
  return localStorage.getItem(PINNED_KEY) || '';
}

/** 设置自定义置顶背景颜色（hex 输入，空串=重置为主题默认） */
export function applyPinnedBg(hex: string): void {
  const el = document.documentElement;
  if (hex) {
    const rgb = hexToRgbTriplet(hex);
    if (rgb) {
      el.style.setProperty('--pinned-bg', rgb);
      localStorage.setItem(PINNED_KEY, rgb);
    }
  } else {
    el.style.removeProperty('--pinned-bg');
    localStorage.removeItem(PINNED_KEY);
  }
  window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, { detail: getThemeId() }));
}

/** 响应式：自定义置顶背景颜色变化时触发重渲 */
export function usePinnedBg(): string {
  useSyncExternalStore(subscribe, () => localStorage.getItem(PINNED_KEY) || '');
  return getPinnedBg();
}
