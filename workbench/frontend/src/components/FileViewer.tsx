/**
 * FileViewer — 文件内容渲染器
 * - .md/.markdown: react-markdown 渲染
 * - .yaml/.yml: 语法高亮
 * - .html/.htm: iframe srcdoc 渲染
 * - .json: 语法高亮 + 折叠
 * - .csv: 表格渲染
 * - K-030: format 提示（办公文档转换结果）：markdown → react-markdown / text → 纯文本
 * - 其他: 纯文本
 */

import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { getFileExt } from './FileTree';
import OfficeViewer from './OfficeViewer';

// K-036：办公文档走保真预览（SheetJS/pdf 原生/mammoth），不再用转换文本渲染
const OFFICE_EXTS = new Set(['.xlsx', '.pdf', '.docx']);

interface FileViewerProps {
  path: string;
  content: string;
  loading?: boolean;
  format?: 'raw' | 'markdown' | 'text';  // K-030: 后端转换提示（xlsx→markdown 等）
}

export default function FileViewer({ path, content, loading, format }: FileViewerProps) {
  const ext = useMemo(() => getFileExt(path), [path]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500 text-sm">
        读取中...
      </div>
    );
  }

  // K-036：办公文档保真预览（原始字节前端解析，content/format 不再用于这三类）
  if (OFFICE_EXTS.has(ext)) {
    return <OfficeViewer path={path} />;
  }

  // K-030：后端转换提示优先（xlsx→markdown 表格、docx/pdf→文本）
  if (format === 'markdown') {
    return (
      <div className="spec-md h-full overflow-y-auto p-4 text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    );
  }
  if (format === 'text') {
    return (
      <pre className="h-full overflow-auto p-3 text-xs font-mono text-gray-300 bg-gray-900/50 whitespace-pre-wrap block">
        {content}
      </pre>
    );
  }

  // Markdown 渲染
  if (ext === '.md' || ext === '.markdown') {
    return (
      <div className="spec-md h-full overflow-y-auto p-4 text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    );
  }

  // HTML 渲染（iframe sandbox）
  if (ext === '.html' || ext === '.htm') {
    return (
      <iframe
        srcDoc={content}
        sandbox="allow-same-origin"
        className="h-full w-full bg-white border-0"
        title={path}
      />
    );
  }

  // YAML / JSON 语法高亮
  if (ext === '.yaml' || ext === '.yml' || ext === '.json' || ext === '.py' || ext === '.ts' || ext === '.js' || ext === '.tsx') {
    const lang = ext === '.yml' ? 'yaml' : ext.slice(1);
    return (
      <div className="h-full overflow-auto">
        <SyntaxHighlighter
          language={lang}
          style={vscDarkPlus}
          customStyle={{
            margin: 0,
            background: '#0a0e14',
            padding: '16px',
            fontSize: '12px',
            minHeight: '100%',
          }}
          showLineNumbers
        >
          {content}
        </SyntaxHighlighter>
      </div>
    );
  }

  // CSV 表格渲染
  if (ext === '.csv') {
    const lines = content.split('\n').filter(l => l.trim());
    const rows = lines.map(l => l.split(','));
    return (
      <div className="h-full overflow-auto p-3">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>{rows[0]?.map((h, i) => (
              <th key={i} className="text-left text-gray-500 font-medium px-2 py-1.5 border-b border-border bg-surface-3/50">
                {h.trim()}
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.slice(1).map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} className="px-2 py-1.5 border-b border-border/30 text-gray-400">
                    {cell.trim()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // 纯文本
  return (
    <pre className="h-full overflow-auto p-3 text-xs font-mono text-gray-300 bg-gray-900/50 whitespace-pre-wrap block">
      {content}
    </pre>
  );
}
