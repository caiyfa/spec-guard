import { isValidElement, memo, useContext } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import GateCardView, { GateExecCard } from '../../components/GateCardView';
import type { GateCard } from '../../api';
import { ArtifactCtx, GateDockCtx } from './contexts';
import { ArtifactCard } from './ArtifactCard';
import { firstMdTitle } from './utils';

// ── pre 渲染：大段 markdown 代码块 → 产物卡片（language-markdown/md 且 ≥8 非空行）；其余保持源码框 ──
function PreBlock({ children }: { children?: ReactNode }) {
  const ctx = useContext(ArtifactCtx);
  const gateCtx = useContext(GateDockCtx);
  const codeEl = isValidElement(children) ? children as React.ReactElement<{ className?: string; children?: ReactNode }> : null;
  const cls = codeEl?.props?.className || '';
  const raw = codeEl ? codeEl.props.children : children;
  const text = Array.isArray(raw) ? raw.join('') : String(raw ?? '');
  // GateDock 二期：```gate-card 围栏 → 渲染闸门操作卡（与操作台页签同一组件）
  if (/language-gate-card(\s|$)/.test(cls)) {
    try {
      const card = JSON.parse(text) as GateCard;
      return (
        <div className="my-2.5">
          <GateCardView card={card} onAskAgent={gateCtx?.onAskAgent} onError={gateCtx?.onError} />
        </div>
      );
    } catch {
      return <pre className="text-fs-body bg-overlay/30 rounded p-3 overflow-x-auto max-h-80 my-2.5 text-fail whitespace-pre-wrap">gate-card JSON 解析失败：{text}</pre>;
    }
  }
  // GateDock 三期：```gate-exec 围栏 → 代执行确认卡（白名单硬编码，人确认才执行）
  if (/language-gate-exec(\s|$)/.test(cls)) {
    return <div className="my-2.5"><GateExecCard text={text} /></div>;
  }
  if (ctx && /language-(markdown|md)(\s|$)/.test(cls)) {
    const lines = text.split('\n').filter(l => l.trim()).length;
    if (lines >= 8) {
      const draftName = ctx.matchDraft(text.trim());
      return (
        <ArtifactCard artifact={{
          title: firstMdTitle(text) || draftName || 'Markdown 文档',
          fileName: draftName,
          lines,
          content: text,   // 始终携带：匹配到 .md 落盘文件时走内容预览（draftsApi 仅支持 yaml）
          formatLabel: 'Markdown',
        }} />
      );
    }
  }
  return (
    <pre className="text-fs-body bg-overlay/30 rounded p-3 overflow-x-auto max-h-80 my-2.5 text-gray-400 whitespace-pre-wrap">{children}</pre>
  );
}

// ── Markdown 渲染（react-markdown + remark-gfm：标题/列表/表格/任务列表/引用/删除线全支持，
//    替代自研简易渲染器——LLM 输出的结构化排版此前大量丢失，长文本挤成一段）──
const MD_COMPONENTS: Components = {
  h1: ({ children }: { children?: ReactNode }) => <h1 className="text-fs-title font-bold text-gray-100 mt-4 mb-2">{children}</h1>,
  h2: ({ children }: { children?: ReactNode }) => <h2 className="text-fs-title font-semibold text-gray-100 mt-3.5 mb-1.5 pb-1 border-b border-border/40">{children}</h2>,
  h3: ({ children }: { children?: ReactNode }) => <h3 className="text-fs-lead font-semibold text-gray-200 mt-3 mb-1">{children}</h3>,
  h4: ({ children }: { children?: ReactNode }) => <h4 className="text-fs-body font-semibold text-gray-300 mt-2 mb-1">{children}</h4>,
  p: ({ children }: { children?: ReactNode }) => <p className="text-gray-200 leading-7 my-2">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => <ul className="list-disc pl-4 my-2 space-y-1">{children}</ul>,
  ol: ({ children }: { children?: ReactNode }) => <ol className="list-decimal pl-4 my-2 space-y-1">{children}</ol>,
  li: ({ children }: { children?: ReactNode }) => <li className="text-gray-300">{children}</li>,
  strong: ({ children }: { children?: ReactNode }) => <strong className="font-semibold text-gray-100">{children}</strong>,
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-info underline hover:opacity-80">{children}</a>
  ),
  // 表格：LLM 常用表格做对比/清单（版本仲裁、边变更、步骤清单）
  table: ({ children }: { children?: ReactNode }) => (
    <div className="overflow-x-auto my-2.5"><table className="w-full text-fs-body border-collapse">{children}</table></div>
  ),
  th: ({ children }: { children?: ReactNode }) => <th className="border border-border px-2.5 py-1 text-left text-gray-300">{children}</th>,
  td: ({ children }: { children?: ReactNode }) => <td className="border border-border px-2.5 py-1 text-gray-400">{children}</td>,
  // 代码块：块级由 PreBlock 接管（大段 markdown → 产物卡片；其余黑底源码框），行内黄字
  pre: ({ children }: { children?: ReactNode }) => <PreBlock>{children}</PreBlock>,
  code: ({ className, children }: { className?: string; children?: ReactNode }) => {
    const inline = !className && !String(children).includes('\n');
    return inline
      ? <code className="text-fs-body text-warn/80 bg-overlay/30 rounded px-0.5">{children}</code>
      : <code className="block">{children}</code>;
  },
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="border-l-2 border-info/30 pl-3 my-2.5 text-gray-400">{children}</blockquote>
  ),
  hr: () => <hr className="border-border my-3" />,
  // remark-gfm 任务列表 checkbox（LLM 输出「- [ ] 待办」时可用）
  input: (props) => <input {...props} className="accent-info mr-1" />,
};

export const MarkdownText = memo(function MarkdownText({ content }: { content: string }) {
  return (
    <div className="text-fs-lead text-gray-200">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{content}</ReactMarkdown>
    </div>
  );
});
