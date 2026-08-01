/**
 * MermaidBlock — mermaid 图表渲染（K-041）
 *
 * mermaid 体积大（~2MB），动态 import 按需加载；渲染失败回退为源码展示。
 * 深色主题（dark）+ 安全等级 strict（不执行图内脚本）。
 */

import { useEffect, useRef, useState } from 'react';

let _seq = 0;

export default function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });
        const { svg } = await mermaid.render(`mmd-${++_seq}`, code);
        if (alive && ref.current) ref.current.innerHTML = svg;
      } catch (e: any) {
        if (alive) setError(e?.message || String(e));
      }
    })();
    return () => { alive = false; };
  }, [code]);

  if (error) {
    return (
      <div className="my-2">
        <div className="text-[10px] text-fail/80 px-2 py-1 bg-red-900/20 border border-red-700/30 rounded-t">
          mermaid 渲染失败（显示源码）：{error.slice(0, 120)}
        </div>
        <pre className="text-[11px] bg-black/30 rounded-b p-2 overflow-x-auto text-gray-400">{code}</pre>
      </div>
    );
  }
  return <div ref={ref} className="my-2 overflow-x-auto [&_svg]:max-w-full" />;
}
