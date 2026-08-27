/**
 * FileViewer — 文件内容渲染器
 * - .md/.markdown: react-markdown 渲染 + K-041 mermaid 图表 + 标题大纲导航
 * - .yaml/.yml: 语法高亮 + K-041 结构大纲（点击跳行）；
 *   T-1023：场景类 YAML（含 flow+doc）默认进 ScenarioReader 结构化阅读视图，可切回原文
 * - .html/.htm: iframe srcdoc 渲染
 * - .json/.py/.ts 等: 语法高亮
 * - .csv: 表格渲染
 * - K-036: 办公文档（xlsx/pdf/docx）走 OfficeViewer 保真预览
 * - K-030: format 提示（办公文档转换结果）：markdown → react-markdown / text → 纯文本
 * - 其他: 纯文本
 */

import React, { useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { load as yamlLoad } from 'js-yaml';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { getFileExt } from './FileTree';
import OfficeViewer from './OfficeViewer';
import MermaidBlock from './MermaidBlock';
import ScenarioReader from './ScenarioReader';
import { isScenarioDoc } from '../utils/scenarioReader';
import { useJsTokens } from '../theme';

// K-036：办公文档走保真预览（SheetJS/pdf 原生/mammoth），不再用转换文本渲染
const OFFICE_EXTS = new Set(['.xlsx', '.pdf', '.docx']);

// ── T-511 依据透明：doc_read 使用位置（hunk）定位渲染 ──

/** agent 阅读足迹的一个使用位置：行区间 1-based 闭区间 + 意义标注 */
export interface DocHunk {
  title: string;
  start: number;
  end: number;
  note?: string;      // 结构化来源：read_spec(anchor=FR-009)
  thinking?: string;  // K-024 思考文本（agent 为什么看这段）
}

/** 带行号 + 行区间高亮 + 「▲ n/N 处 ▼」git-diff 式导航的文本视图（打开即定位） */
function LocatedTextView({ content, hunks }: { content: string; hunks: DocHunk[] }) {
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

// ── K-041：大纲工具 ──

interface OutlineItem { level: number; text: string; anchor: string }

function slugify(s: string): string {
  return s.trim().toLowerCase()
    .replace(/[\s　]+/g, '-')
    .replace(/[^\w一-龥-]/g, '');
}

/** 提取 markdown 标题（跳过代码块内的 # 行） */
function extractMdHeadings(md: string): OutlineItem[] {
  const out: OutlineItem[] = [];
  let inCode = false;
  for (const line of md.split('\n')) {
    if (line.trim().startsWith('```')) { inCode = !inCode; continue; }
    if (inCode) continue;
    const m = /^(#{1,4})\s+(.+)$/.exec(line);
    if (m) out.push({ level: m[1].length, text: m[2].replace(/[#*`[\]]/g, '').trim(), anchor: `md-${slugify(m[2])}` });
  }
  return out;
}

/** 提取 yaml 结构大纲（顶层 + 二级键，正则保留行号——比 js-yaml 解析更适合跳转） */
function extractYamlOutline(text: string): OutlineItem[] {
  const out: OutlineItem[] = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith('#') || line.trim().startsWith('- ')) continue;
    const m = /^(\s{0,4})([\w一-龥'" -]+):(\s|$)/.exec(line);
    if (m) {
      out.push({
        level: m[1].length === 0 ? 1 : 2,
        text: m[2].replace(/['"]/g, ''),
        anchor: `yl-${i + 1}`,
      });
    }
  }
  return out;
}

/** ReactMarkdown children → 纯文本（生成标题锚点 id 用） */
function flattenText(node: unknown): string {
  if (node == null) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(flattenText).join('');
  if (typeof node === 'object' && 'props' in (node as any)) return flattenText((node as any).props?.children);
  return '';
}

/** 大纲侧栏 */
function OutlinePanel({ items, onJump }: { items: OutlineItem[]; onJump: (anchor: string) => void }) {
  return (
    <div className="w-40 flex-shrink-0 border-l border-border overflow-y-auto py-2 bg-surface-2/30">
      <div className="px-2 pb-1 text-[10px] text-gray-600 border-b border-border/50">大纲</div>
      {items.map((it, i) => (
        <button key={i} onClick={() => onJump(it.anchor)}
          className={`w-full text-left px-2 py-0.5 text-[11px] truncate text-gray-500 hover:text-info hover:bg-surface-3 transition-colors ${
            it.level === 1 ? 'font-medium text-gray-400' : ''
          }`}
          style={{ paddingLeft: 8 + (it.level - 1) * 12 }}
          title={it.text}>
          {it.text}
        </button>
      ))}
      {items.length === 0 && <div className="px-2 py-2 text-[10px] text-gray-700">无标题结构</div>}
    </div>
  );
}

/** K-041：md 渲染（mermaid + 标题锚点 + 大纲） */
function MarkdownViewer({ content }: { content: string }) {
  const [showOutline, setShowOutline] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const headings = useMemo(() => extractMdHeadings(content), [content]);

  const components = useMemo(() => {
    const mkHeading = (Tag: 'h1' | 'h2' | 'h3' | 'h4') =>
      function Heading({ children }: { children?: React.ReactNode }) {
        return <Tag id={`md-${slugify(flattenText(children))}`}>{children}</Tag>;
      };
    return {
      h1: mkHeading('h1'), h2: mkHeading('h2'), h3: mkHeading('h3'), h4: mkHeading('h4'),
      // mermaid 代码块 → 图表渲染（其余保持默认）
      pre(props: any) {
        const child = Array.isArray(props.children) ? props.children[0] : props.children;
        const cls: string = child?.props?.className || '';
        if (cls.includes('language-mermaid')) {
          return <MermaidBlock code={String(child.props.children ?? '').replace(/\n$/, '')} />;
        }
        return <pre {...props} />;
      },
    };
  }, []);

  return (
    <div className="h-full flex min-h-0 relative">
      <div ref={containerRef} className="spec-md flex-1 min-w-0 h-full overflow-y-auto p-4 text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{content}</ReactMarkdown>
      </div>
      {showOutline && headings.length > 1 && (
        <OutlinePanel items={headings}
          onJump={a => containerRef.current?.querySelector(`#${CSS.escape(a)}`)?.scrollIntoView({ block: 'start' })} />
      )}
      <button onClick={() => setShowOutline(v => !v)} title={showOutline ? '隐藏大纲' : '显示大纲'}
        className="absolute top-2 right-2 z-10 text-[10px] px-1.5 py-0.5 rounded bg-surface-2/80 border border-border text-gray-500 hover:text-info">
        {showOutline ? '»' : '≡'}
      </button>
    </div>
  );
}

/** K-041：yaml 渲染（语法高亮 + 行锚点 + 结构大纲） */
function YamlViewer({ content }: { content: string }) {  const [showOutline, setShowOutline] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const outline = useMemo(() => extractYamlOutline(content), [content]);
  const tokens = useJsTokens();  // K-043：高亮主题与代码底色跟随主题

  return (
    <div className="h-full flex min-h-0 relative">
      <div ref={containerRef} className="flex-1 min-w-0 h-full overflow-auto">
        <SyntaxHighlighter
          language="yaml"
          style={tokens.dark ? vscDarkPlus : oneLight}
          customStyle={{ margin: 0, background: tokens.codeBg, padding: '16px', fontSize: '12px', minHeight: '100%' }}
          showLineNumbers
          wrapLines
          lineProps={(n: number) => ({ id: `yl-${n}` }) as any}
        >
          {content}
        </SyntaxHighlighter>
      </div>
      {showOutline && outline.length > 1 && (
        <OutlinePanel items={outline}
          onJump={a => containerRef.current?.querySelector(`#${a}`)?.scrollIntoView({ block: 'start' })} />
      )}
      <button onClick={() => setShowOutline(v => !v)} title={showOutline ? '隐藏大纲' : '显示大纲'}
        className="absolute top-2 right-2 z-10 text-[10px] px-1.5 py-0.5 rounded bg-surface-2/80 border border-border text-gray-500 hover:text-info">
        {showOutline ? '»' : '≡'}
      </button>
    </div>
  );
}

// ── T-1023：场景 YAML 双视图（结构化阅读 ⇄ 原文） ──

const SCENARIO_MODE_KEY = 'sg_fileview_scenario_yaml_mode';

/** 场景类 YAML（含 flow+doc）默认进结构化阅读视图；非场景 YAML 与解析失败回退原文高亮 */
function ScenarioYamlView({ path, content }: { path: string; content: string }) {
  const data = useMemo(() => {
    try { return yamlLoad(content) as unknown; } catch { return null; }
  }, [content]);
  const [mode, setMode] = useState<'read' | 'raw'>(() =>
    (typeof localStorage !== 'undefined' && localStorage.getItem(SCENARIO_MODE_KEY)) === 'raw' ? 'raw' : 'read');

  if (!isScenarioDoc(data)) return <YamlViewer content={content} />;

  const switchMode = (m: 'read' | 'raw') => {
    setMode(m);
    try { localStorage.setItem(SCENARIO_MODE_KEY, m); } catch { /* 隐私模式等写失败无害 */ }
  };

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border flex-shrink-0">
        <div className="flex bg-surface-3 rounded overflow-hidden">
          {(['read', 'raw'] as const).map((m) => (
            <button key={m} onClick={() => switchMode(m)}
              className={`px-2.5 py-1 text-[10px] transition-colors ${mode === m ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-gray-300'}`}>
              {m === 'read' ? '📖 结构化' : '📄 原文'}
            </button>
          ))}
        </div>
        <span className="text-[10px] text-gray-600">场景 YAML · 结构化视图为只读摘要</span>
      </div>
      <div className="flex-1 min-h-0">
        {mode === 'read'
          ? <ScenarioReader data={data} rawYaml={content} filePath={path} />
          : <YamlViewer content={content} />}
      </div>
    </div>
  );
}

interface FileViewerProps {
  path: string;
  content: string;
  loading?: boolean;
  format?: 'raw' | 'markdown' | 'text';  // K-030: 后端转换提示（xlsx→markdown 等）
  hunks?: DocHunk[];  // T-511: doc_read 使用位置——带 hunks 时统一走行号定位渲染
}

export default function FileViewer({ path, content, loading, format, hunks }: FileViewerProps) {
  const ext = useMemo(() => getFileExt(path), [path]);
  const tokens = useJsTokens();  // K-043

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500 text-sm">
        读取中...
      </div>
    );
  }

  // T-511：带使用位置（hunks）的阅读足迹打开——行号 + 高亮 + 多处导航，优先于排版渲染
  // T-xxx：.md/.yaml 文件不走 LocatedTextView（行号 + 纯文本），走 Markdown/YAML 渲染
  if (hunks && hunks.length > 0 && !OFFICE_EXTS.has(ext) && ext !== '.md' && ext !== '.yaml' && ext !== '.yml') {
    return <LocatedTextView content={content} hunks={hunks} />;
  }

  // K-036：办公文档保真预览（原始字节前端解析，content/format 不再用于这三类）
  if (OFFICE_EXTS.has(ext)) {
    return <OfficeViewer path={path} />;
  }

  // K-030：后端转换提示优先（办公文档以外的转换结果）
  if (format === 'markdown') {
    return <MarkdownViewer content={content} />;
  }
  if (format === 'text') {
    return (
      <pre className="h-full overflow-auto p-3 text-xs font-mono text-gray-300 bg-gray-900/50 whitespace-pre-wrap block">
        {content}
      </pre>
    );
  }

  // Markdown 渲染（K-041：mermaid + 大纲）
  if (ext === '.md' || ext === '.markdown') {
    return <MarkdownViewer content={content} />;
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

  // YAML（K-041：结构大纲；T-1023：场景类 YAML 双视图）
  if (ext === '.yaml' || ext === '.yml') {
    return <ScenarioYamlView path={path} content={content} />;
  }
  if (ext === '.json' || ext === '.py' || ext === '.ts' || ext === '.js' || ext === '.tsx') {
    const lang = ext.slice(1);
    return (
      <div className="h-full overflow-auto">
        <SyntaxHighlighter
          language={lang}
          style={tokens.dark ? vscDarkPlus : oneLight}
          customStyle={{
            margin: 0,
            background: tokens.codeBg,
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
