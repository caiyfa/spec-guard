/** Dashboard — 总览（Tab 切换：运行总览 / 格式规范） */
import { useEffect, useState, useMemo, useRef } from 'react';
import type { JSX } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useJsTokens } from '../theme';
import { scenariosApi, runsApi, referenceApi, type Scenario, type RunSummary } from '../api';

type DashTab = 'overview' | 'spec';

export default function Dashboard() {
  const [tab, setTab] = useState<DashTab>('overview');
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [specMd, setSpecMd] = useState('');
  const [specLoading, setSpecLoading] = useState(false);

  useEffect(() => {
    Promise.all([scenariosApi.list(), runsApi.history(5)])
      .then(([s, h]) => { setScenarios(s); setHistory(h); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (tab === 'spec' && !specMd) {
      setSpecLoading(true);
      referenceApi.yamlFormatSpecMd()
        .then((r) => setSpecMd(r.content))
        .catch(() => setSpecMd('# 加载失败'))
        .finally(() => setSpecLoading(false));
    }
  }, [tab, specMd]);

  const exportMd = () => {
    if (!specMd) return;
    const blob = new Blob([specMd], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'specguard-yaml-format-spec.md';
    a.click();
    URL.revokeObjectURL(url);
  };

  const latest = history[0];
  const stats = latest?.stats;

  return (
    <div className="space-y-4">
      {/* Tab 栏 */}
      <div className="flex items-center gap-1 bg-surface-3 rounded-lg p-1 w-fit">
        {([['overview', '📊 运行总览'], ['spec', '📐 YAML 格式规范']] as const).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-4 py-1.5 rounded-md text-fs-body font-medium transition-colors ${
              tab === key ? 'bg-surface text-info shadow' : 'text-gray-500 hover:text-gray-300'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── 运行总览 ── */}
      {tab === 'overview' && (
        <div className="space-y-6">
          {stats && (
            <div className="grid grid-cols-5 gap-3">
              {[
                { label: '通过', value: stats.pass, color: 'text-pass' },
                { label: '失败', value: stats.fail, color: 'text-fail' },
                { label: '跳过', value: stats.skip, color: 'text-skip' },
                { label: '阻塞', value: stats.blocked, color: 'text-blocked' },
                { label: '总计', value: stats.total, color: 'text-info' },
              ].map((c) => (
                <div key={c.label} className="card-hover">
                  <div className={`text-2xl font-bold font-mono ${c.color}`}>{c.value}</div>
                  <div className="text-fs-body text-gray-500 mt-1">{c.label}</div>
                </div>
              ))}
            </div>
          )}

          {latest && (
            <p className="text-fs-body text-gray-500">
              最近运行：{latest.run_id} · {latest.env} · {latest.started_at}
              {latest.stats.warnings > 0 && ` · ⚠️ ${latest.stats.warnings} 条 WARN`}
            </p>
          )}

          <div className="bg-surface-2 border border-border rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-border text-sm font-medium">
              场景库（{scenarios.length} 个）
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-fs-body text-gray-500 border-b border-border">
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">标题</th>
                  <th className="px-4 py-2">优先级</th>
                  <th className="px-4 py-2">标签</th>
                  <th className="px-4 py-2">依赖</th>
                  <th className="px-4 py-2">FR</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">加载中…</td></tr>
                ) : scenarios.map((s) => (
                  <tr key={s.id} className="border-b border-border/50 hover:bg-surface-3 transition-colors">
                    <td className="px-4 py-2 font-mono text-info text-fs-body">{s.id}</td>
                    <td className="px-4 py-2">{s.title}</td>
                    <td className="px-4 py-2">
                      <span className={`text-fs-body px-1.5 py-0.5 rounded ${s.priority === 'P0' ? 'bg-fail/10 text-fail' : 'bg-surface-3 text-gray-400'}`}>
                        {s.priority}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-fs-body text-gray-400">{s.tags.join(', ')}</td>
                    <td className="px-4 py-2 text-fs-body">
                      {s.depends_on.length > 0 ? (
                        <span className={s.depends_on.some(d => d.mode === 'exclusive') ? 'text-warn' : 'text-gray-500'}>
                          ⛓ {s.depends_on.map(d => d.id).join(', ')}
                        </span>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-2 text-fs-body font-mono text-gray-500">{s.covers.join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── YAML 格式规范 ── */}
      {tab === 'spec' && (
        <SpecTab specMd={specMd} specLoading={specLoading} exportMd={exportMd} />
      )}
    </div>
  );
}

/** 格式规范 Tab 内容（含 TOC + MD 渲染） */
function SpecTab({ specMd, specLoading, exportMd }: {
  specMd: string; specLoading: boolean; exportMd: () => void;
}) {
  const contentRef = useRef<HTMLDivElement>(null);

  return (
    <div className="flex gap-3 h-[calc(100vh-180px)]">
      <TocSidebar md={specMd} contentRef={contentRef} />
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center justify-end mb-2">
          <button onClick={exportMd}
            className="text-fs-aux px-2 py-1 rounded bg-info/10 text-info hover:bg-info/20">
            📥 导出 MD
          </button>
        </div>
        <div ref={contentRef}
          className="flex-1 bg-surface-2 border border-border rounded-lg p-5 overflow-y-auto">
          {specLoading ? (
            <div className="text-gray-500 text-fs-body text-center py-8">加载中…</div>
          ) : specMd ? (
            <div className="spec-md text-[13px] leading-6 text-gray-300">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{specMd}</ReactMarkdown>
            </div>
          ) : (
            <div className="text-gray-500 text-fs-body text-center py-8">切换到格式规范 Tab 加载</div>
          )}
        </div>
      </div>
    </div>
  );
}

/** TOC 大纲侧边栏 */
function TocSidebar({ md, contentRef }: { md: string; contentRef: React.RefObject<HTMLDivElement | null> }) {
  const toc = useMemo(() => extractToc(md), [md]);
  const [activeId, setActiveId] = useState('');

  const scrollTo = (item: { id: string; text: string; level: number }) => {
    setActiveId(item.id);
    // 通过文本内容匹配标题（避免 ID 生成不一致问题）
    const headings = contentRef.current?.querySelectorAll('h1, h2, h3, h4');
    if (!headings) return;
    for (const h of Array.from(headings)) {
      const headingText = (h.textContent || '').replace(/\*\*/g, '').replace(/`/g, '').trim();
      if (headingText === item.text) {
        h.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
    }
  };

  if (!toc.length) return null;

  return (
    <div className="w-[220px] flex-shrink-0 bg-surface-2 border border-border rounded-lg overflow-hidden flex flex-col">
      <div className="px-3 py-2 border-b border-border text-fs-body font-medium text-gray-400 bg-surface-3/50">
        📑 大纲
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {toc.map((item) => (
          <button key={item.id} onClick={() => scrollTo(item)}
            className={`w-full text-left px-3 py-1 text-fs-body transition-colors ${
              activeId === item.id
                ? 'text-info bg-info/10'
                : item.level === 1 ? 'text-gray-300 font-medium hover:text-info' :
                  item.level === 2 ? 'text-gray-400 pl-5 hover:text-info' :
                  'text-gray-500 pl-7 hover:text-info'
            }`}>
            {item.text}
          </button>
        ))}
      </div>
    </div>
  );
}

/** 从 MD 提取 TOC */
function extractToc(md: string): { id: string; text: string; level: number }[] {
  if (!md) return [];
  const items: { id: string; text: string; level: number }[] = [];
  const lines = md.split('\n');
  let idx = 0;
  for (const line of lines) {
    const m = line.match(/^(#{1,4})\s+(.+)/);
    if (m) {
      const level = m[1].length;
      const text = m[2].replace(/\*\*/g, '').replace(/`/g, '').trim();
      items.push({ id: `h-${idx}`, text, level });
      idx++;
    }
  }
  return items;
}



/** 可折叠代码块 */
function CollapsibleCodeBlock({ language, children }: { language: string; children: string }) {
  const [collapsed, setCollapsed] = useState(false);
  const tokens = useJsTokens();  // K-043
  const lines = children.split('\n').length;
  const preview = children.split('\n').slice(0, 3).join('\n');

  return (
    <div className="relative group">
      <div className="flex items-center justify-between px-3 py-1 bg-surface-3/80 rounded-t-lg border border-b-0 border-border">
        <span className="text-fs-aux text-gray-500 font-mono">{language}</span>
        <button onClick={() => setCollapsed(!collapsed)}
          className="text-fs-aux text-gray-500 hover:text-info">
          {collapsed ? `▸ 展开（${lines} 行）` : '▾ 收起'}
        </button>
      </div>
      {collapsed ? (
        <div className="border border-border rounded-b-lg px-3 py-2" style={{ background: tokens.codeBg }}>
          <pre className="text-fs-body text-gray-500 font-mono">{preview}{lines > 3 ? '\n…' : ''}</pre>
        </div>
      ) : (
        <SyntaxHighlighter
          language={language === 'yaml' ? 'yaml' : language}
          style={tokens.dark ? oneDark : oneLight}
          customStyle={{
            margin: 0, borderRadius: '0 0 8px 8px',
            border: 'none',
            fontSize: '11px', lineHeight: '1.5',
          }}
          showLineNumbers
        >
          {children}
        </SyntaxHighlighter>
      )}
    </div>
  );
}

/** react-markdown 自定义组件 */
const mdComponents = {
  // 标题带 data-heading-id（供 TOC 定位）
  h1: ({ children }: { children?: React.ReactNode }) => <HeadingWithId level={1}>{children}</HeadingWithId>,
  h2: ({ children }: { children?: React.ReactNode }) => <HeadingWithId level={2}>{children}</HeadingWithId>,
  h3: ({ children }: { children?: React.ReactNode }) => <HeadingWithId level={3}>{children}</HeadingWithId>,
  h4: ({ children }: { children?: React.ReactNode }) => <HeadingWithId level={4}>{children}</HeadingWithId>,
  // 代码块：语法高亮 + 折叠
  code: ({ className, children }: { className?: string; children?: React.ReactNode }) => {
    const match = /language-(\w+)/.exec(className || '');
    const code = String(children).replace(/\n$/, '');
    if (match) {
      return <CollapsibleCodeBlock language={match[1]}>{code}</CollapsibleCodeBlock>;
    }
    return <code className="bg-surface-3 text-info/80 px-1 py-0.5 rounded text-fs-body font-mono">{children}</code>;
  },
};

/** 带 ID 的标题（供 TOC 滚动定位） */
function HeadingWithId({ level, children }: { level: number; children?: React.ReactNode }) {
  const Tag = `h${level}` as keyof JSX.IntrinsicElements;
  return <Tag>{children}</Tag>;
}
