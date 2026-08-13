/**
 * ReadingPanel — 📖 阅读足迹面板（S0.5 · T-511 依据透明）
 *
 * agent 调用读型文档工具（read_spec/read_scenario/read_run_report/read_run_log/
 * read_info_pack）后由 runtime 发 doc_read 事件汇聚而来：时间倒序文件卡片，
 * 同文件去重合并多个使用位置（hunk）；点击卡片/hunk 打开 file: 页签即定位
 * （行区间高亮 + ▲ n/N 处 ▼ 导航，见 FileViewer LocatedTextView）。
 *
 * 意义标注双来源（确定性，无 LLM 总结）：① 工具名+关键参数（note/label）
 * ② K-024 思考文本（thinking，💭 行）。
 */

import type { DocHunk } from './FileViewer';

export interface DocReadItem {
  key: string;            // 去重键：path || ref
  tool: string;
  ref: string;            // 原始定位参数（path/id/run_id/scenario_id）
  path: string | null;    // 可经 read-file 打开的工作区相对路径；null → memo 兜底
  turn: number;
  size: number;
  excerpt: string;
  label: string;          // 意义标注①人类可读形态（查阅 spec.md / 引用需求条目 FR-009）
  thinking: string;       // 意义标注②：最近一次读取时的思考文本
  hunks: DocHunk[];       // 使用位置（多次读取不同章节各自成 hunk）
  reads: number;          // 累计读取次数
}

function formatSize(n: number): string {
  if (n >= 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${n}B`;
}

export default function ReadingPanel({ items, onOpen, onRefresh }: {
  items: DocReadItem[];
  onOpen: (item: DocReadItem, hunk?: DocHunk) => void;
  onRefresh?: () => void;
}) {
  if (items.length === 0) {
    return (
      <div className="text-xs text-gray-600 text-center py-6 px-4 space-y-3">
        <div>暂无阅读足迹——agent 调用读型文档工具后自动汇聚到这里</div>
        {onRefresh && (
          <button onClick={onRefresh}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[10px] bg-surface-3 rounded hover:bg-surface-3/70 transition-colors">
            ↻ 刷新
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="p-2 space-y-2">
      {/* 刷新按钮（右上） */}
      {onRefresh && (
        <div className="flex justify-end -mb-1">
          <button onClick={onRefresh}
            className="text-[10px] text-gray-500 hover:text-info transition-colors px-1"
            title="重新加载阅读足迹">↻</button>
        </div>
      )}
      {items.map((item) => (
        <div key={item.key}
          className="rounded-lg border border-border bg-surface-2/70 p-2 hover:border-info/40 transition-colors">
          {/* 标题行：意义标注 + 读取次数 */}
          <div className="flex items-center gap-1.5 cursor-pointer" onClick={() => onOpen(item)}>
            <span className="text-[11px] text-gray-200 font-medium truncate flex-1" title={item.label}>
              {item.label}
            </span>
            {item.reads > 1 && (
              <span className="text-[9px] text-info bg-info/10 rounded px-1 flex-shrink-0">×{item.reads}</span>
            )}
          </div>
          {/* 文件路径 */}
          <div className="text-[10px] font-mono text-gray-500 truncate mt-0.5" title={item.ref}>
            {item.path || item.ref}
          </div>
          {/* 元信息：工具 · 轮次 · 大小 */}
          <div className="text-[10px] text-gray-600 mt-0.5">
            {item.tool} · 第{item.turn + 1}轮 · {formatSize(item.size)}
          </div>
          {/* 意义标注②：K-024 思考文本 */}
          {item.thinking && (
            <div className="text-[10px] text-gray-500 mt-1 truncate" title={item.thinking}>
              💭 {item.thinking}
            </div>
          )}
          {/* 使用位置（hunk）清单：多次读取不同章节各自成条 */}
          <div className="mt-1.5 space-y-1">
            {item.hunks.map((h, i) => (
              <button key={i} onClick={() => onOpen(item, h)}
                className="w-full text-left px-1.5 py-1 rounded bg-surface-3/60 hover:bg-surface-3 text-[10px] text-gray-400 hover:text-info transition-colors"
                title={`${h.note || ''}${h.thinking ? `\n💭 ${h.thinking}` : ''}`}>
                <span className="truncate block">{h.title}</span>
                <span className="text-gray-600">行{h.start}-{h.end}{h.note ? ` · ${h.note}` : ''}</span>
              </button>
            ))}
          </div>
          {/* 头部摘录（前 3 行；T-512 章节分支跳过 --- 标头行，直接展示段落摘要） */}
          {item.excerpt && (
            <pre className="mt-1.5 text-[10px] font-mono text-gray-600 bg-gray-900/40 rounded p-1.5 overflow-hidden whitespace-pre-wrap break-all max-h-16">
              {item.excerpt.split('\n')
                .filter((l, i) => !(i === 0 && /^--- .+ · .+ · 行\d+-\d+ ---$/.test(l)))
                .slice(0, 3).join('\n')}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
