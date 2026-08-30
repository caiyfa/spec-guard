/**
 * MermaidBlock — mermaid 图表渲染（K-041）
 *
 * mermaid 体积大（~2MB），动态 import 按需加载；渲染失败回退为源码展示。
 * 深色主题（dark）+ 安全等级 strict（不执行图内脚本）。
 * fit: contain（默认，SVG 压缩适配容器宽）/ natural（保持原始尺寸，容器双向滚动——
 *      网状拓扑图压缩后文字不可读，FlowPanel 🧭 用此档）
 */

import { useEffect, useRef, useState } from 'react';
import { useTheme } from '../theme';

let _seq = 0;

export default function MermaidBlock({ code, fit = 'contain' }: { code: string; fit?: 'contain' | 'natural' }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const theme = useTheme();  // K-043：mermaid 主题跟随（dark/default）

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({ startOnLoad: false, theme: theme.dark ? 'dark' : 'default', securityLevel: 'strict' });
        const { svg } = await mermaid.render(`mmd-${++_seq}`, code);
        if (alive && ref.current) {
          ref.current.innerHTML = svg;
          // natural 档：mermaid SVG 无 width 属性（默认 100% 容器宽），按 viewBox 钉原始尺寸，
          // 容器 overflow-auto 滚动——网状拓扑图压缩后文字不可读（🧭 FlowPanel）
          if (fit === 'natural') {
            const svgEl = ref.current.querySelector('svg');
            const vb = svgEl?.viewBox?.baseVal;
            if (svgEl && vb && vb.width > 0) {
              svgEl.style.width = `${vb.width}px`;
              svgEl.style.height = 'auto';
              svgEl.style.maxWidth = 'none';
            }
            // 初始视口水平居中（回边绕线区在两侧，主链大致居中），纵向回顶
            const scroller = ref.current;
            scroller.scrollLeft = Math.max(0, (scroller.scrollWidth - scroller.clientWidth) / 2);
            scroller.scrollTop = 0;
          }
        }
      } catch (e: any) {
        if (alive) setError(e?.message || String(e));
      }
    })();
    return () => { alive = false; };
  }, [code, theme.dark, fit]);

  if (error) {
    return (
      <div className="my-2">
        <div className="text-fs-aux text-fail/80 px-2 py-1 bg-fail/12 border border-fail/35 rounded-t">
          mermaid 渲染失败（显示源码）：{error.slice(0, 120)}
        </div>
        <pre className="text-fs-body bg-overlay/30 rounded-b p-2 overflow-x-auto text-gray-400">{code}</pre>
      </div>
    );
  }
  const cls = fit === 'natural'
    ? 'my-2 overflow-auto [&_svg]:max-w-none'
    : 'my-2 overflow-x-auto [&_svg]:max-w-full';
  return <div ref={ref} className={cls} />;
}
