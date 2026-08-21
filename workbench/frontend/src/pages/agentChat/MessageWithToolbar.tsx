import { useState } from 'react';
import { MarkdownText } from './MarkdownText';

// ── 复制按钮（独立组件，自管理反馈状态） ──
export function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        }).catch(() => {});
      }}
      title={copied ? '已复制' : '复制内容'}
      className={className || 'text-gray-500 hover:text-info flex-shrink-0 px-1 rounded hover:bg-surface-3'}
    >
      {copied ? '✓' : '📋'}
    </button>
  );
}

// ── assistant 消息内容框：内部顶部工具栏（预览/文本双按钮 + 复制），内容区独立背景 ──
export function MessageWithToolbar({ content }: { content: string }) {
  const [view, setView] = useState<'preview' | 'text'>('preview');
  const tabBtn = (active: boolean) =>
    `px-2 py-0.5 rounded text-[11px] transition-colors ${active ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-info hover:bg-surface-3'}`;
  return (
    <div className="rounded-lg border border-border/60 bg-surface-2/40 overflow-hidden">
      {/* 内容框内部顶部工具栏 */}
      <div className="flex items-center gap-1 px-2 py-1 border-b border-border/50 bg-surface-3/40">
        <button onClick={() => setView('preview')} className={tabBtn(view === 'preview')} title="Markdown 渲染效果">
          👁 预览
        </button>
        <button onClick={() => setView('text')} className={tabBtn(view === 'text')} title="原始 Markdown 源码">
          📝 文本
        </button>
        <span className="flex-1" />
        <CopyButton text={content}
          className="w-6 h-6 flex items-center justify-center rounded bg-surface-3 text-gray-400 hover:text-info hover:bg-surface-1 text-xs border border-border/50 flex-shrink-0" />
      </div>
      {/* 内容区（预览 = Markdown 渲染 / 文本 = 原始源码，独立深色背景） */}
      {view === 'preview' ? (
        <div className="px-3 py-2 bg-gray-900/30">
          <MarkdownText content={_unwrapTextBlock(content)} />
        </div>
      ) : (
        <pre className="text-xs font-mono text-gray-300 bg-gray-900/50 rounded-b-lg p-3 overflow-x-auto whitespace-pre-wrap break-all max-h-96 overflow-y-auto">
          {content}
        </pre>
      )}
    </div>
  );
}

/** 解包「摘要 + 代码块 + 后续」模式：去掉外层 ```text/```markdown fences，
 *  使代码块内的 Markdown 内容得以正常渲染（而非以 <pre><code> 显示）。 */
function _unwrapTextBlock(content: string): string {
  return content.replace(/^```(?:text|markdown)\n([\s\S]*?)\n```\s*/gm, '$1');
}
