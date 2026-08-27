/** LocatedTextView — 带行号 + 行区间高亮 + 「▲ n/N 处 ▼」git-diff 式导航的文本视图（打开即定位）。
 *
 * T-1024 自 FileViewer.tsx 拆出独立文件：ScenarioReader 的「打开完整文档」弹层复用
 * （FileViewer 同时 import ScenarioReader，直接互引会成循环依赖）。
 * FileViewer.tsx 再导出本模块保持存量 import 路径不变。
 */
/* oxlint-disable react-in-jsx-scope -- 项目用现代 JSX transform（jsx: react-jsx），无需 React 在作用域；
   默认导入 React 反被 tsc noUnusedLocals 判未使用（与存量文件的告警同根，新文件不再背债） */
import { useMemo, useRef, useState } from 'react';

/** agent 阅读足迹/锚点定位的一个使用位置：行区间 1-based 闭区间 + 意义标注 */
export interface DocHunk {
  title: string;
  start: number;
  end: number;
  note?: string;      // 结构化来源：read_spec(anchor=FR-009)
  thinking?: string;  // K-024 思考文本（agent 为什么看这段）
}

export function LocatedTextView({ content, hunks }: { content: string; hunks: DocHunk[] }) {
  const [active, setActive] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => content.split('\n'), [content]);
  const cur = hunks[Math.min(active, hunks.length - 1)];

  // 行 → 所属 hunk 索引（高亮强度区分：当前 hunk 亮、其余 hunk 淡）
  const lineHunk = useMemo(() => {
    const map = new Map<number, number>();
    hunks.forEach((h, i) => {
      for (let n = Math.max(1, h.start); n <= Math.min(lines.length, h.end); n++) map.set(n, i);
    });
    return map;
  }, [hunks, lines.length]);

  // 挂载与切换 hunk 时滚动到位
  const jump = (idx: number) => {
    setActive(idx);
    const n = hunks[idx]?.start;
    if (n) containerRef.current?.querySelector(`#lv-${n}`)?.scrollIntoView({ block: 'start' });
  };
  // 首次挂载即定位到第一个 hunk
  const mounted = useRef(false);
  if (!mounted.current && hunks.length > 0) {
    mounted.current = true;
    setTimeout(() => jump(0), 0);
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* 多处导航条（git-diff 式跳上处/下处） */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border flex-shrink-0 text-[11px]">
        <button onClick={() => jump((active - 1 + hunks.length) % hunks.length)} title="上一处"
          className="px-1.5 py-0.5 rounded bg-surface-3 text-gray-400 hover:text-info">▲</button>
        <span className="text-gray-400">{active + 1}/{hunks.length} 处</span>
        <button onClick={() => jump((active + 1) % hunks.length)} title="下一处"
          className="px-1.5 py-0.5 rounded bg-surface-3 text-gray-400 hover:text-info">▼</button>
        {cur && (
          <span className="text-gray-500 truncate" title={cur.thinking ? `💭 ${cur.thinking}` : cur.note}>
            {cur.title} · 行{cur.start}-{cur.end}
            {cur.note && <span className="text-gray-600"> · {cur.note}</span>}
            {cur.thinking && <span className="text-gray-600"> · 💭 {cur.thinking}</span>}
          </span>
        )}
      </div>
      <div ref={containerRef} className="flex-1 min-h-0 overflow-auto py-2 bg-gray-900/50">
        {lines.map((line, i) => {
          const n = i + 1;
          const hi = lineHunk.get(n);
          const cls = hi === undefined ? ''
            : hi === active ? 'bg-info/15 border-l-2 border-info'
            : 'bg-info/5 border-l-2 border-transparent';
          return (
            <div key={n} id={`lv-${n}`} className={`flex ${cls}`}>
              <span className="w-10 flex-shrink-0 text-right pr-2 text-gray-600 select-none">{n}</span>
              <span className="flex-1 min-w-0 whitespace-pre-wrap break-all text-gray-300">{line || ' '}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
