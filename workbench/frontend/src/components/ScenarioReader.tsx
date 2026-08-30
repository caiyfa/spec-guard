/** ScenarioReader — T-1023 场景 YAML 结构化阅读视图（只读，给测试人员看）。
 *
 * 区块：头部信息 → 📖 业务语义（given/when/then）→ 🔗 关联需求（covers/related_ac
 * 锚点芯片，点击就地展开 spec 原文）→ ⚙ 执行步骤（注释说明 + 脚本/SQL 折叠）→
 * ✅ 验证（友好断言文案）→ 尾部（requires/depends_on/produces/teardown）。
 * 挂载：FileViewer 场景双视图 + ScenarioFormEditor 阅读模式。
 */
import React, { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { workspaceApi, type AnchorMatch, type AnchorRef } from '../api/workspace';
import {
  buildAnchorHint, describeStep, describeVerify, extractSectionComments,
} from '../utils/scenarioReader';
import Modal from './Modal';
import { useJsTokens } from '../theme';

interface Props {
  data: Record<string, unknown>;
  rawYaml?: string;   // 有原文时可提取步骤注释；缺省时注释区块不显示（诚实降级）
  filePath?: string;  // 锚点同号排序 hint 来源之一
  onOpenFile?: (relPath: string) => void;  // T-1024：有文件页签体系（AgentChat）时「页签打开」入口
}

// ── 小部件 ──

function Chip({ text, tone = 'gray' }: { text: string; tone?: 'gray' | 'info' | 'warn' }) {
  const cls = tone === 'info' ? 'bg-info/15 text-info'
    : tone === 'warn' ? 'bg-yellow-900/30 text-yellow-500'
    : 'bg-surface-3 text-gray-400';
  return <span className={`px-1.5 py-0.5 rounded text-fs-aux ${cls}`}>{text}</span>;
}

function Section({ icon, title, count, children }: {
  icon: string; title: string; count?: number; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-fs-body font-medium text-gray-400 mb-1.5">
        {icon} {title}{count != null && <span className="ml-1 text-fs-micro text-gray-600">({count})</span>}
      </div>
      {children}
    </div>
  );
}

function CodeBlock({ lang, text }: { lang: string; text: string }) {
  const tokens = useJsTokens();
  return (
    <SyntaxHighlighter language={lang} style={tokens.dark ? vscDarkPlus : oneLight}
      customStyle={{ margin: 0, background: tokens.codeBg, padding: '8px', fontSize: '11px', maxHeight: '260px', borderRadius: '4px' }}>
      {text}
    </SyntaxHighlighter>
  );
}

// ── 锚点芯片 + 原文展开 ──

function AnchorChip({ aid, anchor, open, onToggle }: {
  aid: string; anchor: AnchorRef | undefined; open: boolean; onToggle: () => void;
}) {
  // anchor undefined = 仍在加载
  if (anchor === undefined) {
    return <span className="px-1.5 py-0.5 rounded text-fs-aux bg-surface-3 text-gray-600">{aid} …</span>;
  }
  if (!anchor.found) {
    return (
      <span className="px-1.5 py-0.5 rounded text-fs-aux bg-surface-3 text-gray-600"
        title="当前工作区 spec 锚点清单中未找到该编号">
        {aid} <span className="text-gray-700">未找到</span>
      </span>
    );
  }
  const m = anchor.matches[0];
  return (
    <button onClick={onToggle}
      className={`px-1.5 py-0.5 rounded text-fs-aux text-left transition-colors ${
        open ? 'bg-info/25 text-info' : 'bg-info/10 text-info/80 hover:bg-info/20'}`}
      title={`${m.title}\n${m.module}/${m.feature} · 点击${open ? '收起' : '展开'} spec 原文`}>
      <span className="font-mono">{aid}</span>
      <span className="ml-1 text-gray-400">{m.title.replace(/^[A-Z]+-[\w-]+[：:]\s*/, '').slice(0, 24)}</span>
      {anchor.matches.length > 1 && (
        <span className="ml-1 text-fs-micro text-yellow-500/80" title="该编号跨模块同号，展开后可切换候选">
          {anchor.matches.length}处
        </span>
      )}
      <span className="ml-1">{open ? '▾' : '▸'}</span>
    </button>
  );
}

function AnchorSourcePanel({ anchor, onOpenDoc, onOpenFile }: {
  anchor: AnchorRef;
  onOpenDoc: (m: AnchorMatch) => void;
  onOpenFile?: (relPath: string) => void;
}) {
  // T-1025：按相关性分组——score>0 的相关模块默认展示，零相关的全库同号折叠
  const relevant = anchor.matches.filter((c) => (c.score ?? 0) > 0);
  const rest = anchor.matches.filter((c) => (c.score ?? 0) === 0);
  const [showRest, setShowRest] = useState(false);
  const [sel, setSel] = useState(anchor.matches[0]);
  const visible = relevant.length > 0 && !showRest ? relevant : anchor.matches;
  const m = sel;
  if (!m) return null;
  return (
    <div className="mt-1 rounded border border-info/20 bg-surface-2/60 overflow-hidden">
      {anchor.matches.length > 1 && (
        <div className="flex flex-wrap items-center gap-1 px-2 py-1 border-b border-border/50 text-fs-micro">
          <span className="text-gray-600 py-0.5">
            {relevant.length > 0 ? `相关候选 ${relevant.length} 处：` : `同号候选 ${anchor.matches.length} 处：`}
          </span>
          {visible.map((c) => (
            <button key={c.rel} onClick={() => setSel(c)}
              className={`px-1.5 py-0.5 rounded ${c.rel === m.rel ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-500 hover:text-gray-300'}`}>
              {c.module}/{c.feature}
            </button>
          ))}
          {relevant.length > 0 && rest.length > 0 && (
            <button onClick={() => setShowRest(!showRest)}
              className="px-1.5 py-0.5 rounded text-gray-600 hover:text-gray-400"
              title="与当前场景零相关的全库同号编号">
              {showRest ? '收起其余 ◂' : `其余 ${rest.length} 处同号 ▸`}
            </button>
          )}
        </div>
      )}
      <div className="flex items-center gap-2 px-2 py-1 text-fs-micro text-gray-600 border-b border-border/30">
        <span className="flex-1 min-w-0 truncate">
          {m.module}/{m.feature} · {m.rel}:{m.start}-{m.end}
        </span>
        <button onClick={() => onOpenDoc(m)}
          className="px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20 flex-shrink-0"
          title="弹层打开完整 spec 文档（渲染格式，定位到本段）">
          📄 完整文档
        </button>
        {onOpenFile && (
          <button onClick={() => onOpenFile(m.rel)}
            className="px-1.5 py-0.5 rounded bg-surface-3 text-gray-400 hover:text-info flex-shrink-0"
            title="在文件页签中打开 spec 文档">
            页签打开 ›
          </button>
        )}
      </div>
      <pre className="px-2.5 py-1.5 text-fs-body text-gray-300 whitespace-pre-wrap break-all max-h-56 overflow-y-auto"
        style={{ background: 'rgb(var(--code-bg))' }}>
        {m.chunk}
      </pre>
    </div>
  );
}

/** T-1025：markdown 高亮组件工厂——hast node.position 行号落入锚点区间则高亮标记 */
function mkHl(Tag: string, start: number, end: number) {
  return function Hl({ node, children, ...props }: any) {  // eslint-disable-line @typescript-eslint/no-explicit-any
    const line: number | undefined = node?.position?.start?.line;
    const hit = line != null && line >= start && line <= end;
    const cls = hit
      ? `${props.className || ''} bg-info/15 border-l-2 border-info pl-1.5 -ml-1.5 rounded-sm`.trim()
      : props.className;
    return <Tag {...props} className={cls} {...(hit ? { 'data-fr-hit': '1' } : {})}>{children}</Tag>;
  };
}

/** T-1024/T-1025：spec 完整文档弹层（markdown 渲染 + 定位高亮锚点段，三态分离） */
function SpecDocModal({ aid, match, onClose }: { aid: string; match: AnchorMatch; onClose: () => void }) {
  const [content, setContent] = useState('');
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errMsg, setErrMsg] = useState('');
  const containerRef = React.useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    setState('loading'); setContent(''); setErrMsg('');
    workspaceApi.readFile(match.rel)
      .then((r) => { if (alive) { setContent(r.content); setState('ready'); } })
      .catch((e) => { if (alive) { setErrMsg(e instanceof Error ? e.message : '读取失败'); setState('error'); } });
    return () => { alive = false; };
  }, [match.rel]);

  // 渲染完成后滚动到第一个高亮段
  useEffect(() => {
    if (state !== 'ready') return;
    const t = setTimeout(() => {
      containerRef.current?.querySelector('[data-fr-hit]')
        ?.scrollIntoView({ block: 'start' });
    }, 60);
    return () => clearTimeout(t);
  }, [state]);

  const mdComponents = useMemo(() => ({
    p: mkHl('p', match.start, match.end),
    li: mkHl('li', match.start, match.end),
    h1: mkHl('h1', match.start, match.end),
    h2: mkHl('h2', match.start, match.end),
    h3: mkHl('h3', match.start, match.end),
    h4: mkHl('h4', match.start, match.end),
    tr: mkHl('tr', match.start, match.end),
    pre: mkHl('pre', match.start, match.end),
    blockquote: mkHl('blockquote', match.start, match.end),
  }), [match.start, match.end]);

  return (
    <Modal open onClose={onClose} width={860}
      title={`${aid} · ${match.module}/${match.feature} · ${match.rel}`}>
      <div className="px-2 py-1 text-fs-micro text-gray-600 border-b border-border/30 sticky top-0 bg-surface-2 z-10">
        {match.title} · 行 {match.start}-{match.end}（高亮段）
      </div>
      <div ref={containerRef} style={{ height: '66vh' }} className="overflow-y-auto">
        {state === 'loading' && <div className="p-4 text-fs-body text-gray-600">文档加载中…</div>}
        {state === 'error' && <div className="p-4 text-fs-body text-fail">文档读取失败：{errMsg}</div>}
        {state === 'ready' && (
          <div className="spec-md p-4 text-fs-lead">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{content}</ReactMarkdown>
          </div>
        )}
      </div>
    </Modal>
  );
}

// ── 主组件 ──

// T-1027 F3：区块分页签（此前五个区块自上而下堆叠，评审时不知看哪里）。
// 头部信息常驻；分签选择 localStorage 持久化，恢复值失效回退首个可用签（体验基线①）。
type ReaderTabId = 'semantic' | 'anchors' | 'flow' | 'verify' | 'tail';
const READER_TAB_KEY = 'sg_scenario_reader_tab';
const READER_TABS: { id: ReaderTabId; icon: string; label: string }[] = [
  { id: 'semantic', icon: '📖', label: '业务语义' },
  { id: 'anchors',  icon: '🔗', label: '关联需求' },
  { id: 'flow',     icon: '⚙',  label: '执行步骤' },
  { id: 'verify',   icon: '✅', label: '验证断言' },
  { id: 'tail',     icon: '🧩', label: '依赖与产出' },
];

export default function ScenarioReader({ data, rawYaml, filePath, onOpenFile }: Props) {
  const doc = (data.doc || {}) as Record<string, unknown>;
  const covers = Array.isArray(doc.covers) ? doc.covers.map(String) : [];
  const relatedAc = Array.isArray(doc.related_ac) ? doc.related_ac.map(String) : [];
  const anchorIds = useMemo(() => [...covers, ...relatedAc], [covers.join(','), relatedAc.join(',')]);  // eslint-disable-line react-hooks/exhaustive-deps
  const hint = useMemo(() => buildAnchorHint(data, filePath), [data, filePath]);

  // ── 锚点原文（一次拉取全部，组件内缓存） ──
  const [refs, setRefs] = useState<Record<string, AnchorRef>>({});
  const [refsError, setRefsError] = useState('');
  const [openAnchor, setOpenAnchor] = useState<string | null>(null);
  const [docView, setDocView] = useState<{ aid: string; match: AnchorMatch } | null>(null);  // T-1024 文档弹层
  useEffect(() => {
    setRefs({}); setRefsError(''); setOpenAnchor(null);
    if (!anchorIds.length) return;
    let alive = true;
    workspaceApi.anchorRefs(anchorIds, hint)
      .then((r) => {
        if (!alive) return;
        const map: Record<string, AnchorRef> = {};
        for (const ref of r.refs || []) map[ref.id] = ref;
        setRefs(map);
      })
      .catch((e) => { if (alive) setRefsError(e instanceof Error ? e.message : '锚点原文加载失败'); });
    return () => { alive = false; };
  }, [anchorIds, hint]);

  // ── 步骤/断言与注释对齐（注释数量与步骤数不一致时整体弃用，诚实降级） ──
  const flow = Array.isArray(data.flow) ? data.flow : [];
  const verify = Array.isArray(data.verify) ? data.verify : [];
  const flowComments = useMemo(() => {
    if (!rawYaml) return [];
    const c = extractSectionComments(rawYaml, 'flow');
    return c.length === flow.length ? c : [];
  }, [rawYaml, flow.length]);
  const verifyComments = useMemo(() => {
    if (!rawYaml) return [];
    const c = extractSectionComments(rawYaml, 'verify');
    return c.length === verify.length ? c : [];
  }, [rawYaml, verify.length]);

  const requires = (data.requires || {}) as Record<string, unknown>;
  const dependsOn = Array.isArray(data.depends_on) ? data.depends_on : [];
  const produces = Array.isArray(data.produces) ? data.produces : [];
  const teardown = Array.isArray(data.teardown) ? data.teardown : [];
  const tags = Array.isArray(data.tags) ? data.tags.map(String) : [];
  const dimensions = Array.isArray(doc.dimensions) ? doc.dimensions.map(String) : [];

  // ── 分签装配（空区块不出签；持久化值失效回退首签） ──
  const hasSemantic = !!((doc.given || doc.when || doc.then || doc.note));
  const hasAnchors = anchorIds.length > 0;
  const hasTail = Object.keys(requires).length > 0 || dependsOn.length > 0
    || produces.length > 0 || teardown.length > 0;
  const availableTabs = useMemo(() => READER_TABS.filter((t) => ({
    semantic: hasSemantic,
    anchors: hasAnchors,
    flow: flow.length > 0,
    verify: verify.length > 0,
    tail: hasTail,
  } as Record<ReaderTabId, boolean>)[t.id]), [hasSemantic, hasAnchors, flow.length, verify.length, hasTail]);

  const [activeTab, setActiveTab] = useState<ReaderTabId>(() => {
    try {
      const stored = localStorage.getItem(READER_TAB_KEY) as ReaderTabId | null;
      if (stored && READER_TABS.some(t => t.id === stored)) return stored;
    } catch { /* 隐私模式 */ }
    return 'semantic';
  });
  // 活动签失效（该文档无此区块/存储值越界）→ 回退首个可用签，不空白不报错
  useEffect(() => {
    if (!availableTabs.some(t => t.id === activeTab)) {
      setActiveTab(availableTabs[0]?.id ?? 'semantic');
    }
  }, [availableTabs, activeTab]);
  const selectTab = (id: ReaderTabId) => {
    setActiveTab(id);
    try { localStorage.setItem(READER_TAB_KEY, id); } catch { /* 隐私模式写失败无害 */ }
  };

  const tabCountOf = (id: ReaderTabId): number | undefined =>
    id === 'flow' && flow.length > 0 ? flow.length
      : id === 'verify' && verify.length > 0 ? verify.length
        : id === 'anchors' && hasAnchors ? anchorIds.length
          : undefined;

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* ── 头部（常驻）：id/版本/优先级/tags/dimensions + 标题 ── */}
      <div className="px-4 pt-3 pb-1 flex-shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-fs-lead text-info">{String(data.id || '')}</span>
          {!!data.version && <Chip text={`v${String(data.version)}`} />}
          {!!data.priority && <Chip text={String(data.priority)} tone={data.priority === 'P0' ? 'warn' : 'gray'} />}
          {tags.map((t) => <Chip key={t} text={t} />)}
          {dimensions.map((t) => <Chip key={t} text={`◆${t}`} />)}
        </div>
        {!!data.title && <div className="mt-1 text-fs-lead text-gray-200">{String(data.title)}</div>}
      </div>

      {/* ── 区块页签条 ── */}
      {availableTabs.length > 1 && (
        <div className="flex items-center gap-1 px-3 pb-1.5 pt-0.5 border-b border-border flex-shrink-0 overflow-x-auto">
          {availableTabs.map((t) => {
            const n = tabCountOf(t.id);
            return (
              <button key={t.id} onClick={() => selectTab(t.id)}
                title={`${t.label}${n != null ? `（${n} 条）` : ''}`}
                className={`px-2 py-1 rounded text-fs-aux whitespace-nowrap transition-colors ${
                  activeTab === t.id ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-gray-300 hover:bg-surface-3'
                }`}>
                {t.icon} {t.label}
                {n != null && <span className="ml-0.5 opacity-70">{n}</span>}
              </button>
            );
          })}
        </div>
      )}

      {/* ── 活动区块内容 ── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 pt-3">
        <div className="max-w-3xl space-y-5">

          {activeTab === 'semantic' && (
            <>
              {(!!doc.given || !!doc.when || !!doc.then) && (
                <Section icon="📖" title="业务语义">
                  <div className="rounded-lg border border-border bg-surface-2/70 px-3 py-2.5 space-y-1.5 text-fs-body">
                    {!!doc.given && (
                      <div className="flex gap-2"><span className="text-gray-600 flex-shrink-0 w-10">Given</span>
                        <span className="text-gray-300 whitespace-pre-wrap">{String(doc.given)}</span></div>
                    )}
                    {!!doc.when && (
                      <div className="flex gap-2"><span className="text-gray-600 flex-shrink-0 w-10">When</span>
                        <span className="text-gray-300 whitespace-pre-wrap">{String(doc.when)}</span></div>
                    )}
                    {!!doc.then && (
                      <div className="flex gap-2"><span className="text-gray-600 flex-shrink-0 w-10">Then</span>
                        <span className="text-gray-300 whitespace-pre-wrap">{String(doc.then)}</span></div>
                    )}
                  </div>
                </Section>
              )}
              {!!doc.note && (
                <details className="rounded border border-border/60 bg-surface-2/50 px-3 py-1.5">
                  <summary className="text-fs-body text-gray-500 cursor-pointer">📝 编写备注（关键决策）</summary>
                  <div className="mt-1.5 text-fs-body text-gray-400 whitespace-pre-wrap">{String(doc.note)}</div>
                </details>
              )}
            </>
          )}

          {activeTab === 'anchors' && hasAnchors && (
            <Section icon="🔗" title="关联需求（点击展开 spec 原文）">
              <div className="space-y-1.5">
                {covers.length > 0 && (
                  <div className="flex items-start gap-2 flex-wrap">
                    <span className="text-fs-aux text-gray-600 py-0.5 flex-shrink-0">covers</span>
                    {covers.map((aid) => (
                      <AnchorChip key={aid} aid={aid} anchor={refs[aid]}
                        open={openAnchor === aid}
                        onToggle={() => setOpenAnchor(openAnchor === aid ? null : aid)} />
                    ))}
                  </div>
                )}
                {relatedAc.length > 0 && (
                  <div className="flex items-start gap-2 flex-wrap">
                    <span className="text-fs-aux text-gray-600 py-0.5 flex-shrink-0">验收标准</span>
                    {relatedAc.map((aid) => (
                      <AnchorChip key={aid} aid={aid} anchor={refs[aid]}
                        open={openAnchor === aid}
                        onToggle={() => setOpenAnchor(openAnchor === aid ? null : aid)} />
                    ))}
                  </div>
                )}
                {refsError && <div className="text-fs-aux text-fail">锚点原文加载失败：{refsError}</div>}
                {openAnchor && refs[openAnchor]?.found && (
                  <AnchorSourcePanel anchor={refs[openAnchor]}
                    onOpenDoc={(match) => setDocView({ aid: openAnchor, match })}
                    onOpenFile={onOpenFile} />
                )}
              </div>
            </Section>
          )}

          {activeTab === 'flow' && flow.length > 0 && (
            <Section icon="⚙" title="执行步骤" count={flow.length}>
              <div className="space-y-1.5">
                {flow.map((s, i) => {
                  const d = describeStep(s);
                  const comment = flowComments[i] || '';
                  return (
                    <div key={i} className="rounded-lg border border-border bg-surface-2/70 px-3 py-2">
                      <div className="flex items-center gap-2 text-fs-body">
                        <span className="text-gray-600 text-fs-aux w-4 flex-shrink-0">{i + 1}</span>
                        <span>{d.icon}</span>
                        <span className="text-gray-500 flex-shrink-0">{d.typeLabel}</span>
                        <span className="text-gray-200 font-mono text-fs-body break-all">{d.title}</span>
                        {d.save && (
                          <span className="ml-auto text-fs-micro text-gray-600 flex-shrink-0"
                            title={`结果存为变量，后续步骤以 {{${d.save}.…}} 引用`}>→ {d.save}</span>
                        )}
                      </div>
                      {comment && (
                        <div className="mt-1 ml-6 text-fs-body text-gray-500 whitespace-pre-wrap border-l-2 border-info/20 pl-2">
                          {comment}
                        </div>
                      )}
                      {d.lines.length > 0 && (
                        <div className="mt-0.5 ml-6 text-fs-aux text-gray-600 space-y-0">
                          {d.lines.map((l, j) => <div key={j} className="break-all">{l}</div>)}
                        </div>
                      )}
                      {d.code && (
                        <details className="mt-1 ml-6">
                          <summary className="text-fs-aux text-gray-600 cursor-pointer hover:text-info">
                            查看{d.code.lang === 'sql' ? ' SQL' : d.code.lang === 'python' ? '脚本' : '报文'}
                          </summary>
                          <div className="mt-1"><CodeBlock lang={d.code.lang} text={d.code.text} /></div>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {activeTab === 'verify' && verify.length > 0 && (
            <Section icon="✅" title="验证断言" count={verify.length}>
              <div className="rounded-lg border border-border bg-surface-2/70 px-3 py-2 space-y-1.5">
                {verify.map((v, i) => {
                  const d = describeVerify(v);
                  const comment = verifyComments[i] || '';
                  return (
                    <div key={i} className="text-fs-body">
                      <div className="flex items-start gap-1.5">
                        <span className="flex-shrink-0">{d.icon}</span>
                        <span className="text-gray-300 break-all flex-1">{d.text}</span>
                      </div>
                      {comment && <div className="ml-5 text-fs-aux text-gray-600 whitespace-pre-wrap">{comment}</div>}
                      {d.code && (
                        <details className="ml-5 mt-0.5">
                          <summary className="text-fs-aux text-gray-600 cursor-pointer hover:text-info">查看明细</summary>
                          <div className="mt-1"><CodeBlock lang={d.code.lang} text={d.code.text} /></div>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {activeTab === 'tail' && hasTail && (
            <div className="rounded-lg border border-border/60 bg-surface-2/50 px-3 py-2 text-fs-aux text-gray-600 space-y-1">
              {!!(Array.isArray(requires.accounts) && requires.accounts.length) && (
                <div>所需账号：{(requires.accounts as unknown[]).map(String).join('、')}</div>
              )}
              {!!(Array.isArray(requires.env) && requires.env.length) && (
                <div>环境配置：{(requires.env as unknown[]).map(String).join('、')}</div>
              )}
              {dependsOn.length > 0 && (
                <div>上游依赖：{dependsOn.map((d) => (typeof d === 'string' ? d : String((d as Record<string, unknown>).id || ''))).join('、')}</div>
              )}
              {produces.length > 0 && (
                <div>对外产出：{produces.map((p) => Object.keys(p as Record<string, unknown>)[0] || '').filter(Boolean).join('、')}</div>
              )}
              {teardown.length > 0 && <div>清理步骤：{teardown.length} 步</div>}
            </div>
          )}
        </div>
      </div>

      {docView && <SpecDocModal aid={docView.aid} match={docView.match} onClose={() => setDocView(null)} />}
    </div>
  );
}
