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

import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { load as yamlLoad } from 'js-yaml';
import Editor from '@monaco-editor/react';
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
// T-1024：DocHunk/LocatedTextView 拆至 ./LocatedTextView（ScenarioReader 文档弹层复用），此处再导出保持存量 import 路径
import type { DocHunk } from './LocatedTextView';
import { LocatedTextView } from './LocatedTextView';
export type { DocHunk } from './LocatedTextView';
export { LocatedTextView } from './LocatedTextView';

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

/** T-1027 F1：面板保存结果（AgentChat 把 PUT 响应映射为此处，编辑区内联呈现） */
export interface EditSaveOutcome {
  ok: boolean;
  message?: string;     // 人话结论（含对话感知去向：已注入/执行中暂存/无关联会话）
  verdict?: string;     // 自动格式校验结论（PASS/FAIL/ERROR…）
  summaryError?: number;
  summaryWarn?: number;
  findings?: { level: string; rule: string; message: string }[];
}

/** 编辑区工具条高度外的保存横幅（verdict 配色 + findings 摘录） */
function SaveOutcomeBanner({ outcome }: { outcome: EditSaveOutcome }) {
  const pass = outcome.verdict === 'PASS';
  return (
    <div className={`flex-shrink-0 mx-2 my-1 text-[10px] rounded px-2 py-1 ${
      !outcome.ok ? 'bg-red-900/20 text-red-400'
        : pass ? 'bg-green-900/20 text-green-400' : 'bg-yellow-900/20 text-yellow-500'
    }`}>
      <div className="font-medium">
        {outcome.ok ? `✓ 已保存${outcome.verdict ? ` · 校验 ${outcome.verdict}` : ''}${outcome.summaryError != null ? ` · error ${outcome.summaryError} / warn ${outcome.summaryWarn ?? 0}` : ''}` : '✗ 保存失败'}
        {outcome.message && <span className="font-normal opacity-80"> — {outcome.message}</span>}
      </div>
      {(outcome.findings || []).slice(0, 4).map((f) => (
        <div key={`${f.rule}:${f.message}`} className={f.level === 'ERROR' ? 'text-red-400' : 'opacity-70'}>
          [{f.rule}] {f.message}
        </div>
      ))}
    </div>
  );
}

/** 场景类 YAML（含 flow+doc）默认进结构化阅读视图；非场景 YAML 与解析失败回退原文高亮。
 * T-1027 F1：canEdit+onSaveContent（draft 页签）时第三模式「✏️ 编辑」——Monaco 改 YAML，
 * 保存走回调（PUT /api/drafts，后端自动校验+版本链+对话感知），结果内联回显。 */
function ScenarioYamlView({ path, content, onOpenFile, canEdit, onSaveContent }: {
  path: string; content: string; onOpenFile?: (relPath: string) => void;
  canEdit?: boolean; onSaveContent?: (content: string) => Promise<EditSaveOutcome>;
}) {
  // 结构化解析基于「已落盘」内容（savedText）：编辑中不随击键反复重解析，保存后自动跟随
  const data = useMemo(() => {
    try { return yamlLoad(content) as unknown; } catch { return null; }
  }, [content]);
  const [mode, setMode] = useState<'read' | 'raw' | 'edit'>(() =>
    (typeof localStorage !== 'undefined' && localStorage.getItem(SCENARIO_MODE_KEY)) === 'raw' ? 'raw' : 'read');
  // 编辑缓冲：savedText 跟随最近一次落盘内容；dirty 由两者差异派生（外层内容刷新自动收敛）
  const [savedText, setSavedText] = useState(content);
  const [draftText, setDraftText] = useState(content);
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<EditSaveOutcome | null>(null);
  const tokens = useJsTokens();

  useEffect(() => {
    setSavedText(content);
    if (draftText === savedText) setDraftText(content);  // 未动笔才跟随外部刷新，防覆盖输入
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content]);

  const editable = !!(canEdit && onSaveContent);
  const isScenario = !!isScenarioDoc(data);
  // 模式归一化：内容不是场景结构时「结构化」不可用（持久化残留 read → 落回原文）
  const effectiveMode = !isScenario && mode === 'read' ? 'raw' : mode;

  if (!editable && !isScenario) return <YamlViewer content={content} />;

  const dirty = draftText !== savedText;
  const switchMode = (m: 'read' | 'raw' | 'edit') => {
    if (m === 'edit' && !editable) return;
    if (m === 'edit') { setDraftText(savedText); setOutcome(null); }
    setMode(m);
    if (m === 'read' || m === 'raw') {
      try { localStorage.setItem(SCENARIO_MODE_KEY, m); } catch { /* 隐私模式等写失败无害 */ }
    }
  };
  const handleSave = async () => {
    if (!onSaveContent || saving) return;
    setSaving(true); setOutcome(null);
    try {
      const r = await onSaveContent(draftText);
      setOutcome(r);
      if (r.ok) setSavedText(draftText);
    } finally {
      setSaving(false);
    }
  };

  const modeList = [
    ...(isScenario ? ['read'] as const : []),
    ...(['raw'] as const),
    ...(editable ? ['edit'] as const : []),
  ];

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border flex-shrink-0">
        <div className="flex bg-surface-3 rounded overflow-hidden">
          {modeList.map((m) => (
            <button key={m} onClick={() => switchMode(m)}
              className={`px-2.5 py-1 text-[10px] transition-colors ${effectiveMode === m ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-gray-300'}`}>
              {m === 'read' ? '📖 结构化' : m === 'raw' ? '📄 原文' : '✏️ 编辑'}
            </button>
          ))}
        </div>
        {effectiveMode === 'edit' ? (
          <div className="ml-auto flex items-center gap-1.5">
            {dirty && <span className="text-[10px] text-warn">未保存修改</span>}
            <button onClick={() => switchMode('raw')} disabled={saving}
              className="px-2 py-0.5 rounded text-[10px] bg-surface-3 text-gray-400 hover:text-gray-200 disabled:opacity-40">↩ 取消</button>
            <button onClick={handleSave} disabled={!dirty || saving} title="保存到草稿沙箱（自动格式校验 + 对话感知）"
              className="px-2.5 py-0.5 rounded text-[10px] bg-pass/25 text-pass hover:bg-pass/35 disabled:opacity-40">
              {saving ? '保存中…' : '💾 保存并校验'}
            </button>
          </div>
        ) : (
          <span className="text-[10px] text-gray-600">{isScenario ? '场景 YAML · 结构化视图为只读摘要' : '草稿 YAML'}{editable ? ' · 可在「✏️ 编辑」中修改草稿' : ''}</span>
        )}
      </div>
      <div className="flex-1 min-h-0 flex flex-col">
        {effectiveMode === 'edit' && onSaveContent ? (
          <>
            <div className="flex-1 min-h-0">
              <Editor language="yaml" theme={tokens.monaco} value={draftText}
                onChange={(v) => { setDraftText(v || ''); setOutcome(null); }}
                options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }} />
            </div>
            {outcome && <SaveOutcomeBanner outcome={outcome} />}
          </>
        ) : effectiveMode === 'read' && isScenario
          ? <ScenarioReader data={data} rawYaml={savedText} filePath={path} onOpenFile={onOpenFile} />
          : <YamlViewer content={savedText} />}
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
  onOpenFile?: (relPath: string) => void;  // T-1024: 结构化视图内「打开关联文档」回调
  canEdit?: boolean;  // T-1027 F1: draft 页签可编辑（新增「✏️ 编辑」模式）
  onSaveContent?: (content: string) => Promise<EditSaveOutcome>;  // T-1027 F1: 保存回调（AgentChat 落 draftsApi.update）
}

export default function FileViewer({ path, content, loading, format, hunks, onOpenFile, canEdit, onSaveContent }: FileViewerProps) {
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

  // YAML（K-041：结构大纲；T-1023：场景类 YAML 双视图；T-1027：draft 可编辑）
  if (ext === '.yaml' || ext === '.yml') {
    return <ScenarioYamlView path={path} content={content} onOpenFile={onOpenFile}
      canEdit={canEdit} onSaveContent={onSaveContent} />;
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
