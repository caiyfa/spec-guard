/** AgentChat — 左侧会话树 + 中间对话区 + 右侧面板（K-012 简洁化：底部仅模式/模型下拉 + 输入框） */

import { useState, useRef, useEffect, useCallback, useMemo, memo, createContext, useContext, isValidElement } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { useSearchParams, useNavigate } from 'react-router';
import { ReactFlow, Background, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import ScenarioNode from '../components/ScenarioNode';
import { layoutDagByELK } from '../utils/elkLayout';
import { useJsTokens } from '../theme';
import { session, agentApi, scenarioApi, modelApi, workspaceApi, draftsApi, scenariosApi } from '../api';
import type { ScenarioMeta, ModelConfig, DraftItem, InfoPackFreshness, ValidateReport, TrialRunResult, DagData } from '../api';
import SessionTree from '../components/SessionTree';
import TodoPanel from '../components/TodoPanel';
import type { StructuredTodo } from '../components/TodoPanel';
import FileViewer from '../components/FileViewer';
import type { DocHunk } from '../components/FileViewer';
import ReadingPanel from '../components/ReadingPanel';
import type { DocReadItem } from '../components/ReadingPanel';

interface ChatReference {
  type: 'info_pack' | 'file' | 'draft';
  path: string;          // file=相对路径 / draft=文件名 / info_pack=SG-META-xxxx
  sha: string;           // 引用时的内容指纹（info_pack 为 ""）
  label?: string;        // K-015: 展示名（信息包为场景名，持久化 refs 无此字段时回退 path）
  missing?: boolean;
}

interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
  reasoning_content?: string;
  references?: ChatReference[];  // K-013: @引用（持久化在 user 消息上）
}

/** K-013：消息展示时剥离 <references> 注入块（内容已在引用面板呈现） */
function stripRefBlock(content: string): string {
  return content.replace(/^<references>[\s\S]*?<\/references>\s*/, '');
}

interface AgentStats {
  total_tokens?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  elapsed_time?: number;
  tps?: number;
  is_mock?: boolean;
  model?: string;
  cache_hits?: number;
  cache_misses?: number;
}

// ── 上下文用量（per-turn，来自 LLM API usage） ──
interface CtxUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

// ── 模型上下文窗口默认值 ──
const DEFAULT_CTX_LIMIT = 128000;

// ── 按角色估算 token 分布（参考 opencode 的 chars/4 方法） ──
function calcCtxBreakdown(messages: ChatMessage[], actualPromptTokens: number): Record<string, number> {
  const est: Record<string, number> = { system: 0, user: 0, assistant: 0, tool: 0 };
  for (const msg of messages) {
    const role = msg.role in est ? msg.role : 'system';
    const content = msg.content || '';
    const toolArgs = (msg.tool_calls || []).reduce((s, tc) => s + (tc.function.arguments || '').length, 0);
    est[role] += Math.ceil((content.length + toolArgs) / 4);
  }
  const total = Object.values(est).reduce((a, b) => a + b, 0);
  if (total > 0 && actualPromptTokens > 0) {
    const scale = actualPromptTokens / total;
    for (const k in est) est[k] = Math.round(est[k] * scale);
  }
  return est;
}

interface SlashCommand {
  cmd: string;
  label: string;
  desc: string;
  type: 'skill' | 'mode' | 'action';
  skillName?: string;   // 技能名（cmd 与技能名不一致时指定，如 /dag → dag-orchestration）
}

const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: '/generate-scenario', label: '场景生成技能', desc: '使用场景生成技能分析需求', type: 'skill' },
  { cmd: '/validate-conformance', label: '合规校验技能', desc: '校验场景 YAML 格式合规性', type: 'skill' },
  { cmd: '/debug-failure', label: '失败分析技能', desc: '分析运行报告中的失败场景', type: 'skill' },
  { cmd: '/dag', label: 'DAG 编排', desc: '对话中编排场景依赖（建议/加边/删边/复核）', type: 'skill', skillName: 'dag-orchestration' },
  { cmd: '/new', label: '新会话', desc: '开始新的对话会话', type: 'action' },
  { cmd: '/clear', label: '清空对话', desc: '清空当前消息列表', type: 'action' },
  { cmd: '/undo', label: '撤销写入', desc: '撤销最后一次草稿写入（从 .bak 恢复）', type: 'action' },
  { cmd: '/export', label: '导出会话', desc: '导出当前会话为 JSON 文件', type: 'action' },
];

// ── 消息分组类型 ──
interface ToolItem {
  name: string;
  args: string;
  result?: string;
}
// ── 会话产物（write_draft 落盘文件 / 大段 markdown 文档），对话流内可点击预览 ──
interface ArtifactInfo {
  title: string;       // 卡片主标题（md 首标题；fallback 文件名）
  fileName?: string;   // 已落盘文件名（yaml 点击开草稿预览；非 yaml 需带 content 走内容预览——draftsApi 仅支持 yaml）
  size?: number;       // 字节数（write_draft 结果真实字节）
  lines?: number;      // 行数（代码块卡片）
  content?: string;    // 未落盘/非 yaml 内容（点击开 memo: 内容预览页签）
  formatLabel?: string; // 无 fileName 时的格式标签（如 Markdown）
}
interface GroupedItem {
  type: 'user' | 'assistant-text' | 'tool-group' | 'step-complete' | 'artifact';
  content?: string;
  tools?: ToolItem[];
  stepLabel?: string;   // 关联的待办步骤名称
  stepIdx?: number;    // 步骤索引
  thought?: boolean;    // K-024: 工具调用前的思考文本（轻量样式，常驻可见）
  references?: ChatReference[];  // K-013: user 消息携带的 @引用
  artifacts?: ArtifactInfo[];    // 产物卡片（工具组之后，独立于折叠组常驻可见）
}

// ── 产物预览上下文（会话级：draft 内容匹配 + 预览回调，注入 MarkdownText 渲染树）──
interface ArtifactCtxValue {
  onPreviewDraft: (fileName: string) => void;
  onPreviewContent: (title: string, content: string) => void;
  matchDraft: (contentTrim: string) => string | undefined;
}
const ArtifactCtx = createContext<ArtifactCtxValue | null>(null);

const fmtSize = (n?: number) => n === undefined ? '' : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`;

/** md 文本首个标题（产物卡片主标题用） */
function firstMdTitle(text: string): string | null {
  const m = /^#{1,3}\s+(.+)$/m.exec(text);
  return m ? m[1].replace(/[#*`[\]]/g, '').trim() : null;
}

/** 扩展名 → 格式标签 */
function extLabelOf(name?: string): string {
  if (!name) return '';
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  if (ext === '.yaml' || ext === '.yml') return 'YAML';
  if (ext === '.md' || ext === '.markdown') return 'Markdown';
  return ext.replace('.', '').toUpperCase();
}

// ── 用途选择卡片（T-010：使命卡片——单击直达，身份色体系）──
interface PurposeCardDef {
  id: string;
  title: string;
  icon: string;
  color: string;
  chips: string[];
  description: string;
}

const PURPOSE_COLORS: Record<string, { border: string; bg: string; text: string; badge: string }> = {
  test: { border: 'border-info/40', bg: 'bg-info/5', text: 'text-info', badge: 'bg-info/15 text-info' },
  req: { border: 'border-purple-500/40', bg: 'bg-purple-900/10', text: 'text-purple-300', badge: 'bg-purple-900/30 text-purple-300' },
};

function getPurposeStyle(colorKey: string) {
  return PURPOSE_COLORS[colorKey] || { border: 'border-border', bg: 'bg-surface-2/40', text: 'text-gray-300', badge: 'bg-surface-3 text-gray-400' };
}

function PurposeCards({ purposes, onPick }: { purposes: PurposeCardDef[]; onPick: (id: string) => void }) {
  return (
    <div className="flex items-center justify-center min-h-[320px] px-4">
      <div className="flex gap-6 max-w-2xl w-full">
        {purposes.map(p => {
          const style = getPurposeStyle(p.color);
          return (
            <button key={p.id} onClick={() => onPick(p.id)}
              className={`flex-1 flex flex-col items-center gap-3 p-6 rounded-xl border-2 ${style.border} ${style.bg} hover:shadow-lg hover:scale-[1.02] transition-all duration-200 cursor-pointer text-center`}>
              <span className="text-3xl">{p.icon}</span>
              <span className={`text-base font-bold ${style.text}`}>{p.title}</span>
              <p className="text-[11px] text-gray-400 leading-relaxed">{p.description}</p>
              {p.chips && p.chips.length > 0 && (
                <div className="flex flex-wrap gap-1.5 justify-center mt-1">
                  {p.chips.map((chip, ci) => (
                    <span key={ci} className={`text-[10px] px-2 py-0.5 rounded-full ${style.badge}`}>{chip}</span>
                  ))}
                </div>
              )}
              <span className="text-xs text-gray-500 mt-2 border-t border-border/50 pt-2 w-full text-center">点击卡片直接开启会话</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── 产物卡片（对话流内统一的可点击文件/文档入口，点击在右侧页签预览）──
function ArtifactCard({ artifact }: { artifact: ArtifactInfo }) {
  const ctx = useContext(ArtifactCtx);
  const metaParts = [
    artifact.fileName && artifact.fileName !== artifact.title ? artifact.fileName : '',
    artifact.lines !== undefined ? `${artifact.lines} 行` : '',
    fmtSize(artifact.size),
    extLabelOf(artifact.fileName) || artifact.formatLabel || '',
  ].filter(Boolean);
  // draftsApi 仅支持 yaml 草稿：非 yaml 产物带 content 走 memo 内容预览
  const isYamlDraft = !!artifact.fileName && /\.ya?ml$/i.test(artifact.fileName);
  return (
    <button
      onClick={() => {
        if (!ctx) return;
        if (isYamlDraft) ctx.onPreviewDraft(artifact.fileName!);
        else if (artifact.content) ctx.onPreviewContent(artifact.title, artifact.content);
        else if (artifact.fileName) ctx.onPreviewDraft(artifact.fileName);
      }}
      title={artifact.fileName ? `预览草稿 ${artifact.fileName}` : '预览文档'}
      className="w-full flex items-center gap-2.5 border border-border bg-surface-2/40 rounded-lg px-3 py-2 hover:border-info/40 hover:bg-surface-2/70 transition-colors text-left group"
    >
      <span className="text-base flex-shrink-0">📄</span>
      <span className="flex-1 min-w-0">
        <span className="block text-sm text-gray-200 truncate">{artifact.title}</span>
        <span className="block text-[10px] text-gray-500 truncate">{metaParts.join(' · ')}</span>
      </span>
      <span className="text-xs text-info/70 flex-shrink-0 group-hover:text-info">预览 ›</span>
    </button>
  );
}

// ── pre 渲染：大段 markdown 代码块 → 产物卡片（language-markdown/md 且 ≥8 非空行）；其余保持源码框 ──
function PreBlock({ children }: { children?: ReactNode }) {
  const ctx = useContext(ArtifactCtx);
  const codeEl = isValidElement(children) ? children as React.ReactElement<{ className?: string; children?: ReactNode }> : null;
  const cls = codeEl?.props?.className || '';
  const raw = codeEl ? codeEl.props.children : children;
  const text = Array.isArray(raw) ? raw.join('') : String(raw ?? '');
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
    <pre className="text-[11px] bg-black/30 rounded p-3 overflow-x-auto max-h-80 my-2.5 text-gray-400 whitespace-pre-wrap">{children}</pre>
  );
}

// ── Markdown 渲染（react-markdown + remark-gfm：标题/列表/表格/任务列表/引用/删除线全支持，
//    替代自研简易渲染器——LLM 输出的结构化排版此前大量丢失，长文本挤成一段）──
const MD_COMPONENTS: Components = {
  h1: ({ children }: { children?: ReactNode }) => <h1 className="text-lg font-bold text-gray-100 mt-4 mb-2">{children}</h1>,
  h2: ({ children }: { children?: ReactNode }) => <h2 className="text-base font-semibold text-gray-100 mt-3.5 mb-1.5 pb-1 border-b border-border/40">{children}</h2>,
  h3: ({ children }: { children?: ReactNode }) => <h3 className="text-sm font-semibold text-gray-200 mt-3 mb-1">{children}</h3>,
  h4: ({ children }: { children?: ReactNode }) => <h4 className="text-xs font-semibold text-gray-300 mt-2 mb-1">{children}</h4>,
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
    <div className="overflow-x-auto my-2.5"><table className="w-full text-[11px] border-collapse">{children}</table></div>
  ),
  th: ({ children }: { children?: ReactNode }) => <th className="border border-border px-2.5 py-1 text-left text-gray-300">{children}</th>,
  td: ({ children }: { children?: ReactNode }) => <td className="border border-border px-2.5 py-1 text-gray-400">{children}</td>,
  // 代码块：块级由 PreBlock 接管（大段 markdown → 产物卡片；其余黑底源码框），行内黄字
  pre: ({ children }: { children?: ReactNode }) => <PreBlock>{children}</PreBlock>,
  code: ({ className, children }: { className?: string; children?: ReactNode }) => {
    const inline = !className && !String(children).includes('\n');
    return inline
      ? <code className="text-[11px] text-yellow-400/80 bg-black/30 rounded px-0.5">{children}</code>
      : <code className="block">{children}</code>;
  },
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="border-l-2 border-info/30 pl-3 my-2.5 text-gray-400">{children}</blockquote>
  ),
  hr: () => <hr className="border-border my-3" />,
  // remark-gfm 任务列表 checkbox（LLM 输出「- [ ] 待办」时可用）
  input: (props) => <input {...props} className="accent-info mr-1" />,
};

const MarkdownText = memo(function MarkdownText({ content }: { content: string }) {
  return (
    <div className="text-sm text-gray-200">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{content}</ReactMarkdown>
    </div>
  );
});

// ── 提取 <plan> 标签 ──
function extractPlan(content: string): string[] | null {
  const match = content.match(/<plan>([\s\S]*?)<\/plan>/);
  if (!match) return null;
  return match[1].split('\n').map(l => l.trim()).filter(l => l);
}

// ── 去除 <plan> 标签后的内容 ──
function stripPlan(content: string): string {
  return content.replace(/<plan>[\s\S]*?<\/plan>/g, '').trim();
}

// ── 默认计划（K-023 去模式化：统一任务骨架）+ 工具→步骤映射 ──
// K-xxx：DEFAULT_PLANS 仅作「工具调用分组锚点」（groupMessages 把工具归到步骤展示），
// 不再预填待办区——待办由模型 todo_write / <plan> 输出，避免「刚发消息就出写死待办」
// 后半段为编排/验证类工具的分组锚点（dag-orchestration 技能链路）
const DEFAULT_PLANS: string[] = [
  '读取基础信息包和需求文档',
  '查询注册表（tool / oracle）',
  '参考已有场景结构',
  '获取场景 ID',
  '生成场景 YAML',
  '校验场景',
  '写入草稿',
  '分析依赖建议',
  '落地依赖边',
  'DAG 复核',
  '试执行验证',
  'DB 证据查询',
];

// 工具名 → 待办步骤序号映射（供 groupMessages 把工具调用归到对应步骤展示）
const TOOL_TO_STEP: Record<string, number> = {
  read_info_pack: 0, read_spec: 0, list_spec_files: 0,
  query_registry: 1,
  list_scenarios: 2, read_scenario: 2,
  next_scenario_id: 3,
  validate: 5,
  write_draft: 6, promote_draft: 6, promote_drafts: 6,
  add_to_info_pack: 0,
  undo_draft: 6,
  // 归因/调试类工具 → DB 证据查询步骤
  read_run_report: 11, db_evidence: 11, read_run_log: 11,
  list_failures: 11, list_executions: 11,
  // K-xxx：DAG 编排链路分组锚点
  suggest_deps: 7,
  edit_dependency: 8,
  check_dag: 9,
  run_scenario: 10,
};

// ── 将扁平消息列表分组（按待办步骤关联 + 完成提示） ──
function groupMessages(messages: ChatMessage[]): GroupedItem[] {
  const groups: GroupedItem[] = [];
  let currentToolGroup: GroupedItem | null = null;
  let lastStepIdx = -1;  // 上一个工具组对应的步骤索引

  // 产物卡片口径与右侧草稿产物区一致（sessionDrafts 同源）：undo_draft 后卡片不再出现
  const liveDrafts = new Set<string>();
  for (const m of messages) {
    if (m.role !== 'assistant' || !m.tool_calls) continue;
    for (const tc of m.tool_calls) {
      try {
        const args = JSON.parse(tc.function.arguments);
        if (tc.function.name === 'write_draft' && args.filename) liveDrafts.add(args.filename);
        else if (tc.function.name === 'undo_draft' && args.filename) liveDrafts.delete(args.filename);
      } catch { /* 参数解析失败忽略 */ }
    }
  }

  const flushToolGroup = () => {
    if (currentToolGroup) {
      groups.push(currentToolGroup);
      // 如果该步骤所有工具都已完成，插入步骤完成提示
      if (currentToolGroup.stepIdx !== undefined && currentToolGroup.stepIdx > lastStepIdx) {
        const allDone = (currentToolGroup.tools || []).every(t => t.result !== undefined);
        if (allDone && currentToolGroup.stepLabel) {
          groups.push({ type: 'step-complete', content: currentToolGroup.stepLabel, stepIdx: currentToolGroup.stepIdx });
          lastStepIdx = currentToolGroup.stepIdx;
        }
      }
      // write_draft 产物卡片（独立于折叠工具组常驻可见，点击右侧页签预览）
      const artifacts: ArtifactInfo[] = [];
      for (const t of currentToolGroup.tools || []) {
        if (t.name !== 'write_draft' || !t.result) continue;
        const args = tryParseJson(t.args);
        const res = tryParseJson(t.result);
        const fn = args?.filename;
        if (!fn || !liveDrafts.has(fn) || res?.ok === false) continue;
        const content = typeof args?.content === 'string' ? args.content : '';
        const isYaml = /\.ya?ml$/i.test(fn);
        artifacts.push({
          fileName: fn,
          title: (content && firstMdTitle(content)) || fn,
          size: typeof res?.size === 'number' ? res.size : undefined,
          content: isYaml ? undefined : content || undefined,  // 非 yaml 产物走内容预览
        });
      }
      if (artifacts.length) groups.push({ type: 'artifact', artifacts });
      currentToolGroup = null;
    }
  };

  for (const msg of messages) {
    if (msg.role === 'system') continue;

    if (msg.role === 'user') {
      flushToolGroup();
      groups.push({ type: 'user', content: msg.content, references: msg.references });
    } else if (msg.role === 'assistant') {
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        const cleanContent = msg.content ? stripPlan(msg.content) : '';
        // K-024：思考文本提升为独立可见气泡——此前塞进 tools[0].assistantText 藏进
        // 折叠的工具组（工具跑完用户只剩一行「7/7 工具」，完全看不到为什么调用；
        // 生产会话取证：100 轮带思考文本的工具调用全部不可见）
        if (cleanContent) {
          flushToolGroup();  // 保证时序：上一工具组 → 思考 → 新工具组
          groups.push({ type: 'assistant-text', content: cleanContent, thought: true });
        }
        // 根据第一个工具名推断步骤
        const firstName = msg.tool_calls[0].function.name;
        const stepIdx = TOOL_TO_STEP[firstName];
        const stepLabel = stepIdx !== undefined ? DEFAULT_PLANS[stepIdx] : undefined;
        // 如果步骤变化了，先 flush 上一组
        if (currentToolGroup && stepIdx !== undefined && currentToolGroup.stepIdx !== undefined && stepIdx !== currentToolGroup.stepIdx) {
          flushToolGroup();
        }
        if (!currentToolGroup) currentToolGroup = { type: 'tool-group', tools: [], stepIdx, stepLabel };
        // 如果新组的 stepIdx 更高，更新（可能同一步骤多次调用）
        if (stepIdx !== undefined && (currentToolGroup.stepIdx === undefined || stepIdx > currentToolGroup.stepIdx)) {
          currentToolGroup.stepIdx = stepIdx;
          currentToolGroup.stepLabel = DEFAULT_PLANS[stepIdx];
        }
        for (let i = 0; i < msg.tool_calls.length; i++) {
          currentToolGroup.tools!.push({
            name: msg.tool_calls[i].function.name,
            args: msg.tool_calls[i].function.arguments,
          });
        }
      } else {
        flushToolGroup();
        const cleanContent = msg.content ? stripPlan(msg.content) : '';
        if (cleanContent) {
          groups.push({ type: 'assistant-text', content: cleanContent });
        }
      }
    } else if (msg.role === 'tool') {
      if (currentToolGroup && currentToolGroup.tools!.length > 0) {
        for (let i = currentToolGroup.tools!.length - 1; i >= 0; i--) {
          if (!currentToolGroup.tools![i].result) {
            currentToolGroup.tools![i].result = msg.content;
            break;
          }
        }
      }
    }
  }
  flushToolGroup();
  return groups;
}

// ── K-024：工具参数/结果的友好渲染 ──
function tryParseJson(text: string): any {
  try { return JSON.parse(text); } catch { return undefined; }
}

/** 长文本截断 + 展开/收起 */
function TruncText({ text, limit = 120, className = 'text-gray-400' }: { text: string; limit?: number; className?: string }) {
  const [open, setOpen] = useState(false);
  if (text.length <= limit) return <span className={`${className} break-all`}>{text}</span>;
  return (
    <span className={`${className} break-all`}>
      {open ? text : text.slice(0, limit) + '…'}
      <button onClick={(e) => { e.stopPropagation(); setOpen(!open); }} className="text-info/80 hover:text-info ml-1">
        {open ? '收起' : '展开'}
      </button>
    </span>
  );
}

/** 单个值渲染（标量/对象自适应） */
function SmartValue({ value }: { value: any }) {
  if (value === null || value === undefined) return <span className="text-gray-600">null</span>;
  if (typeof value === 'boolean') return <span className={value ? 'text-green-400' : 'text-red-400'}>{String(value)}</span>;
  if (typeof value === 'number') return <span className="text-yellow-300/80">{String(value)}</span>;
  if (typeof value === 'object') return <TruncText text={JSON.stringify(value, null, 0)} limit={150} />;
  return <TruncText text={String(value)} />;
}

/** JSON 对象 → 键值行；非 JSON → 原文截断 */
function KeyValueView({ text }: { text: string }) {
  const parsed = tryParseJson(text);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const entries = Object.entries(parsed);
    if (entries.length === 0) return <span className="text-gray-600">{'{}'}</span>;
    return (
      <div className="space-y-0.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex gap-1.5 items-start">
            <span className="text-info/70 flex-shrink-0">{k}:</span>
            <SmartValue value={v} />
          </div>
        ))}
      </div>
    );
  }
  if (Array.isArray(parsed)) {
    return (
      <div className="space-y-0.5">
        <div className="text-gray-500">数组 · 共 {parsed.length} 项</div>
        {parsed.slice(0, 3).map((item, i) => (
          <div key={i} className="text-gray-500 truncate">{JSON.stringify(item)?.slice(0, 120)}</div>
        ))}
        {parsed.length > 3 && <div className="text-gray-600">…</div>}
      </div>
    );
  }
  return <TruncText text={text} limit={300} />;
}

/** 结果渲染：validate 报告特渲（verdict + findings），其余走键值/文本 */
function ResultView({ result }: { result: string }) {
  const parsed = tryParseJson(result);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) && 'verdict' in parsed) {
    const findings = Array.isArray(parsed.findings) ? parsed.findings : [];
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className={parsed.verdict === 'PASS' ? 'text-green-400 font-medium' : 'text-red-400 font-medium'}>
            {parsed.verdict}
          </span>
          {parsed.scenario && <span className="text-gray-500">{parsed.scenario}</span>}
          {parsed.summary && (
            <span className="text-gray-600">error {parsed.summary.error ?? 0} / warn {parsed.summary.warn ?? 0}</span>
          )}
        </div>
        {findings.length > 0 && (
          <div className="space-y-0.5">
            {findings.slice(0, 5).map((f: any, i: number) => (
              <div key={i} className={f.level === 'ERROR' ? 'text-red-400' : 'text-gray-500'}>
                [{f.level}·{f.rule}] <TruncText text={String(f.message ?? '')} limit={150} />
              </div>
            ))}
            {findings.length > 5 && <div className="text-gray-600">…共 {findings.length} 条</div>}
          </div>
        )}
      </div>
    );
  }
  return <KeyValueView text={result} />;
}

// ── 单个工具调用块（可折叠，一行式） ──
function ToolCallBlock({ tool }: { tool: ToolItem }) {
  const [expanded, setExpanded] = useState(false);
  const hasResult = tool.result !== undefined;
  const isError = hasResult && (tool.result!.includes('"error"') || tool.result!.includes('ERROR') || tool.result!.includes('❌'));
  // 结果摘要：取首个非空行（截断），内联在头部行——工具点固定一行，不再独占两行
  const resultPreview = hasResult
    ? (tool.result!.split('\n').map(l => l.trim()).find(l => l && !l.startsWith('{') && !l.startsWith('[')) || tool.result!).substring(0, 60)
    : '';

  return (
    <div className="border border-border rounded text-xs">
      {/* 工具头部 - 始终可见（状态 + 名称 + 结果摘要同一行） */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2 py-1 hover:bg-surface-3 transition-colors text-left"
        title={hasResult ? (isError ? '执行失败，点击查看详情' : '执行成功，点击查看详情') : '执行中…'}
      >
        <span className="text-gray-600 text-[10px]">{expanded ? '▼' : '▶'}</span>
        <span className="text-yellow-500/80 font-mono">🔧</span>
        <span className="text-gray-400 font-mono">{tool.name}</span>
        {hasResult && (
          <span className={isError ? 'text-red-400' : 'text-green-500/70'}>
            {isError ? '❌' : '✅'}
          </span>
        )}
        {!hasResult && <span className="text-yellow-500/50 animate-pulse">⏳</span>}
        {/* 结果摘要内联（代替原第二行预览） */}
        {hasResult && resultPreview && (
          <span className={`flex-1 truncate text-[10px] ${isError ? 'text-red-400/80' : 'text-gray-500'}`}>{resultPreview}</span>
        )}
      </button>
      {/* 展开内容（K-024：键值化友好渲染，不再直接甩原始 JSON） */}
      {expanded && (
        <div className="px-2 pb-2 space-y-1.5">
          <div>
            <div className="text-gray-600 text-[10px] mb-0.5">参数</div>
            <div className="text-[11px] bg-black/30 rounded p-1.5 overflow-x-auto max-h-60">
              <KeyValueView text={tool.args} />
            </div>
          </div>
          {hasResult && (
            <div>
              <div className="text-gray-600 text-[10px] mb-0.5">结果</div>
              <div className={`text-[11px] bg-black/30 rounded p-1.5 overflow-x-auto max-h-72 ${isError ? 'text-red-400' : ''}`}>
                <ResultView result={tool.result!} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 工具组块（按工具名自描述分组，整体可折叠） ──
function ToolGroupBlock({ tools, stepLabel }: { tools: ToolItem[]; stepLabel?: string }) {
  const [groupExpanded, setGroupExpanded] = useState(false);
  const allDone = tools.every(t => t.result !== undefined);
  const hasError = tools.some(t => t.result && (t.result.includes('"error"') || t.result.includes('ERROR') || t.result.includes('❌')));
  const successCount = tools.filter(t => t.result && !(t.result.includes('"error"') || t.result.includes('ERROR') || t.result.includes('❌'))).length;
  // 工具名自描述：从组内工具自身取名称，不依赖外部映射表
  const uniqueNames = [...new Set(tools.map(t => t.name))];
  const toolLabel = uniqueNames.length === 1
    ? uniqueNames[0]
    : uniqueNames.length <= 3
      ? uniqueNames.join(' · ')
      : `${uniqueNames.slice(0, 2).join(' · ')} +${uniqueNames.length - 2}`;

  return (
    <div className="mb-3">
      {/* 工具组标题栏（可折叠整个组） */}
      <button
        onClick={() => setGroupExpanded(!groupExpanded)}
        className="w-full flex items-center gap-2 px-2 py-1 text-xs text-gray-500 hover:text-gray-300 transition-colors text-left"
      >
        <span className="text-[10px]">{groupExpanded ? '▼' : '▶'}</span>
        <span className="text-gray-400 font-mono">{toolLabel}</span>
        {stepLabel && stepLabel !== toolLabel && (
          <span className="text-[10px] text-gray-600">· {stepLabel}</span>
        )}
        <span className="text-[10px] text-gray-600">
          {allDone ? `${successCount}/${tools.length} 工具` : `${tools.length} 工具 执行中…`}
        </span>
        {allDone && (
          <span className={hasError ? 'text-red-400 text-[10px]' : 'text-green-500/70 text-[10px]'}>
            {hasError ? '⚠️' : '✅'}
          </span>
        )}
        {!allDone && <span className="text-yellow-500/50 text-[10px] animate-pulse">⏳</span>}
      </button>
      {/* 展开时显示各工具调用（思考文本已在组外独立展示，K-024） */}
      {groupExpanded && (
        <div className="space-y-1 ml-2">
          {tools.map((tool, ti) => (
            <ToolCallBlock key={ti} tool={tool} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 上下文用量面板组件 ──
function ContextPanel({ ctxUsage, messages, ctxLimit, stats }: { ctxUsage: CtxUsage; messages: ChatMessage[]; ctxLimit: number; stats: AgentStats | null }) {
  const breakdown = calcCtxBreakdown(messages, ctxUsage.prompt_tokens);
  const total = ctxUsage.prompt_tokens + ctxUsage.completion_tokens;
  const pct = Math.round((total / ctxLimit) * 100);
  const fmt = (n: number) => n >= 1000 ? (n / 1000).toFixed(1) + 'K' : String(n);
  const promptTotal = Object.values(breakdown).reduce((a, b) => a + b, 0) || 1;
  const roles = [
    { key: 'system' as const, color: 'bg-blue-500', label: '系统' },
    { key: 'user' as const, color: 'bg-green-500', label: '用户' },
    { key: 'assistant' as const, color: 'bg-purple-500', label: '助手' },
    { key: 'tool' as const, color: 'bg-orange-500', label: '工具' },
  ];
  return (
    <div className="px-3 py-2 border-b border-border">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-gray-300">📊 上下文</span>
        <span className={`text-[10px] font-mono ${pct > 80 ? 'text-red-400' : pct > 50 ? 'text-yellow-400' : 'text-gray-500'}`}>
          {pct}%
        </span>
      </div>
      {/* K-012: 会话统计（原底部栏指标迁入） */}
      {stats && (
        <div className="text-[10px] text-gray-600 font-mono mb-1">
          {stats.tps !== undefined && <span title="tokens/sec">⚡{stats.tps}/s </span>}
          {stats.elapsed_time !== undefined && <span title="elapsed time">⏱{stats.elapsed_time}s </span>}
          {(stats.cache_hits !== undefined) && <span title="prompt cache 命中/未命中">cache {stats.cache_hits}/{stats.cache_misses}</span>}
        </div>
      )}
      {/* 堆叠条形图 */}
      <div className="h-2 w-full rounded-full bg-black/40 overflow-hidden flex">
        {roles.map(r => {
          const w = (breakdown[r.key] / ctxLimit) * 100;
          return w > 0 ? (
            <div key={r.key} className={`h-full ${r.color}`} style={{ width: `${Math.min(w, 100)}%` }} />
          ) : null;
        })}
      </div>
      {/* 总量 */}
      <div className="text-[10px] text-gray-600 font-mono mt-1">
        {fmt(total)} / {fmt(ctxLimit)} tokens
      </div>
      {/* 分角色明细 */}
      <div className="space-y-0.5 mt-1.5">
        {roles.map(r => {
          const val = breakdown[r.key];
          const rolePct = Math.round((val / promptTotal) * 100);
          return (
            <div key={r.key} className="flex items-center gap-1.5 text-[10px]">
              <span className={`w-2 h-2 rounded-sm ${r.color}`} />
              <span className="text-gray-500 w-8">{r.label}</span>
              <span className="text-gray-400 font-mono flex-1 text-right">{fmt(val)}</span>
              <span className="text-gray-600 font-mono w-7 text-right">{rolePct}%</span>
            </div>
          );
        })}
      </div>
      {/* 输入/输出 */}
      <div className="flex gap-3 mt-1.5 pt-1.5 border-t border-border/50 text-[10px] text-gray-600 font-mono">
        <span title="输入 tokens">↑ {fmt(ctxUsage.prompt_tokens)}</span>
        <span title="输出 tokens">↓ {fmt(ctxUsage.completion_tokens)}</span>
      </div>
    </div>
  );
}

// ── 新鲜度徽标 ──
function FreshBadge({ status }: { status: string }) {
  if (status === 'fresh') return <span className="text-pass text-[9px]" title="与引用时一致">✓</span>;
  if (status === 'stale') return <span className="text-yellow-400 text-[9px]" title="内容已变更">⚠️</span>;
  if (status === 'missing') return <span className="text-fail text-[9px]" title="文件已删除">✗</span>;
  return null;
}

// ── 引用面板（K-013：会话中 @引用的内容 + 新鲜度） ──
function RefPanel({ refs, onView }: {
  refs: ChatReference[];
  onView: (path: string, kind: 'file' | 'draft') => void;
}) {
  const [open, setOpen] = useState(true);
  const [status, setStatus] = useState<Record<string, string>>({});
  const refsKey = refs.map(r => `${r.type}:${r.path}:${r.sha}`).join('|');

  // 逐条比对新鲜度（file 走 file-hash 端点；draft 走 .specguard/drafts 路径哈希，失败置 unknown）
  useEffect(() => {
    let alive = true;
    (async () => {
      const next: Record<string, string> = {};
      for (const r of refs) {
        const k = `${r.type}:${r.path}`;
        if (r.type === 'info_pack' || !r.sha) { next[k] = ''; continue; }
        try {
          const hashPath = r.type === 'draft' ? `.specguard/drafts/${r.path}` : r.path;
          const h = await workspaceApi.fileHash(hashPath);
          next[k] = h.sha === r.sha ? 'fresh' : 'stale';
        } catch { next[k] = 'missing'; }
      }
      if (alive) setStatus(next);
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refsKey]);

  if (refs.length === 0) return null;
  return (
    <div className="px-3 py-2 border-b border-border">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between text-xs font-medium text-gray-300 hover:text-gray-100">
        <span>🔗 引用（{refs.length}）</span>
        <span className="text-[9px] text-gray-600">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="mt-1.5 max-h-40 overflow-y-auto space-y-0.5">
          {refs.map((r, i) => (
            <div key={i}
              onClick={() => r.type !== 'info_pack' && onView(r.path, r.type === 'draft' ? 'draft' : 'file')}
              className={`flex items-center gap-1.5 px-1 py-0.5 rounded text-[10px] ${r.type !== 'info_pack' ? 'cursor-pointer hover:bg-surface-3' : ''}`}>
              <span>{r.type === 'info_pack' ? '📦' : r.type === 'draft' ? '📝' : '📄'}</span>
              <span className="font-mono text-gray-400 truncate flex-1" title={r.path}>{r.label || r.path}</span>
              <FreshBadge status={status[`${r.type}:${r.path}`] || ''} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── 基础信息包面板（K-013：条目化 + 新鲜度徽标 + 变更发现补入） ──
function InfoPackPanel({ meta, onUpdate, onError, onViewFile, defaultOpen = false }: {
  meta: ScenarioMeta;
  onUpdate: (m: ScenarioMeta) => void;
  onError: (msg: string) => void;
  onViewFile: (path: string) => void;
  defaultOpen?: boolean;  // K-032：页签内直接展开
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [freshness, setFreshness] = useState<InfoPackFreshness | null>(null);
  const [uploading, setUploading] = useState(false);  // K-033
  const fileInputRef = useRef<HTMLInputElement>(null);  // K-033

  // K-033：上传材料到信息包（xlsx/docx/pdf 后端自动转文本可读）
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';  // 允许重复选同一文件
    if (!file) return;
    setUploading(true);
    try {
      const updated = await scenarioApi.uploadInfoPackFile(meta.id, file);
      onUpdate(updated);
    } catch (err) {
      onError(`上传失败: ${err instanceof Error ? err.message : err}`);
    } finally {
      setUploading(false);
    }
  };

  const loadFreshness = useCallback(() => {
    scenarioApi.infoPackFreshness(meta.id).then(setFreshness).catch(() => setFreshness(null));
  }, [meta.id]);
  useEffect(() => { loadFreshness(); }, [loadFreshness, meta.updated_at]);

  const statusOf = (p: string) => freshness?.files.find(f => f.path === p)?.status || '';
  const outside = freshness?.outside_changes || [];

  const handleAddOutside = async (path: string) => {
    try {
      const updated = await scenarioApi.updateInfoPack(
        meta.id, [...meta.info_pack.map(e => e.path), path]);
      onUpdate(updated);
    } catch { onError('补入文件失败'); }
  };

  return (
    <div className="px-3 py-2 border-b border-border">
      <div className="flex items-center justify-between">
        <button onClick={() => setOpen(v => !v)}
          className="flex-1 flex items-center justify-between text-xs font-medium text-gray-300 hover:text-gray-100">
          <span>
            📦 基础信息包（{meta.info_pack.length}）
            {freshness && freshness.stale_count > 0 && (
              <span className="text-yellow-400 text-[9px] ml-1">⚠️ {freshness.stale_count} 项已变更</span>
            )}
          </span>
          <span className="text-[9px] text-gray-600">{open ? '▲' : '▼'}</span>
        </button>
        {/* K-033：直接上传材料到信息包（不再只能 git 拉取） */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="ml-1 text-[10px] px-1.5 py-0.5 rounded border border-border text-gray-500 hover:text-info hover:border-info/40 disabled:opacity-40"
          title="上传材料到信息包（xlsx/docx/pdf/md/csv 等，≤20MB）"
        >
          {uploading ? '上传中…' : '⬆ 上传'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={handleUpload}
        />
      </div>
      {open && (
        <div className="mt-1.5">
          <div className="max-h-40 overflow-y-auto">
            {meta.info_pack.map(entry => (
              <div key={entry.path} className="flex items-center gap-1 group">
                <FreshBadge status={statusOf(entry.path)} />
                <span className="text-[10px]">📄</span>
                <span onClick={() => onViewFile(entry.path)}
                  className="text-[10px] font-mono text-gray-500 flex-1 truncate cursor-pointer hover:text-info"
                  title={`${entry.path}\nsha: ${entry.sha || '-'}\n添加: ${entry.added_at || '-'}`}>
                  {entry.path}
                </span>
                <button onClick={async () => {
                  const newFiles = meta.info_pack.map(e => e.path).filter(f => f !== entry.path);
                  try {
                    const updated = await scenarioApi.updateInfoPack(meta.id, newFiles);
                    onUpdate(updated);
                  } catch { onError('移除文件失败'); }
                }} className="text-red-500 text-[10px] opacity-0 group-hover:opacity-100">✕</button>
              </div>
            ))}
          </div>
          {/* K-013: git 变更发现——信息包外的相关变更/新增文件，一键补入 */}
          {outside.length > 0 && (
            <div className="mt-2 pt-2 border-t border-border/50">
              <div className="text-[9px] text-yellow-400/80 mb-1">
                ⚠️ {outside.length} 个相关文件已变更/新增（{freshness?.base_commit}→{freshness?.head_commit}），未在信息包中：
              </div>
              <div className="max-h-24 overflow-y-auto space-y-0.5">
                {outside.map(p => (
                  <div key={p} className="flex items-center gap-1">
                    <span onClick={() => onViewFile(p)}
                      className="text-[10px] font-mono text-gray-500 flex-1 truncate cursor-pointer hover:text-info">{p}</span>
                    <button onClick={() => handleAddOutside(p)}
                      className="text-[9px] text-info hover:underline flex-shrink-0">+ 补入</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 草稿产物区（K-xxx：草稿评审融合进 Agent 对话——写入草稿后直接在右侧校验/试跑/入库） ──
interface DraftCardState {
  validate?: ValidateReport;
  validating?: boolean;
  trial?: TrialRunResult;
  running?: boolean;
  promotedTo?: string;   // 已入库目标路径（入库后草稿已移入场景库，drafts 下不再存在）
  scenarioId?: string;   // 入库成功时返回的场景 ID（refresh 后 drafts 列表已无此草稿，需本地留存）
  discarded?: boolean;
}

function DraftArtifactsPanel({ draftFiles, onViewFile, onError }: {
  draftFiles: string[];                          // 本次会话 Agent 写入的草稿文件名（write_draft 检测）
  onViewFile: (path: string, kind?: 'file' | 'draft') => void;
  onError: (msg: string) => void;
}) {
  const navigate = useNavigate();
  const [metaMap, setMetaMap] = useState<Record<string, DraftItem>>({});
  const [modules, setModules] = useState<string[]>([]);
  // K-xxx：草稿依赖建议计数（suggest_deps 确定性引擎，草稿评审页可一键采纳）
  const [suggCount, setSuggCount] = useState<Record<string, number>>({});
  const [state, setState] = useState<Record<string, DraftCardState>>({});
  // K-xxx：drafts 列表查不到的文件（入库/废弃/刷新后）——用 conflict 预检判定去向：
  // ID 命中场景库 = 已入库（本地 promotedTo 状态刷新后丢失），未命中 = 已废弃/删除
  const [resolved, setResolved] = useState<Record<string, { existing: { id: string; path: string; module: string } | null } | null>>({});
  // 入库弹窗
  const [dialog, setDialog] = useState<{ file: string; open: boolean }>({ file: '', open: false });
  const [dlgModule, setDlgModule] = useState('');
  const [dlgCustom, setDlgCustom] = useState('');
  const [dlgReplace, setDlgReplace] = useState(false);
  const [dlgConflict, setDlgConflict] = useState<{ existing: { id: string; path: string; module: string } | null; count: number } | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [dlgError, setDlgError] = useState('');

  const refresh = useCallback(() => {
    draftsApi.list().then(r => {
      const m: Record<string, DraftItem> = {};
      for (const d of r.drafts || []) m[d.filename] = d;
      setMetaMap(m);
    }).catch(() => {});
    draftsApi.modules().then(r => setModules(r.modules || [])).catch(() => {});
    // K-xxx：依赖建议计数（按 consumer 场景 ID 聚合）
    draftsApi.suggestDeps().then(r => {
      const c: Record<string, number> = {};
      for (const s of r.suggestions || []) c[s.consumer] = (c[s.consumer] || 0) + 1;
      setSuggCount(c);
    }).catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // K-xxx：草稿去向判定——drafts 列表无此文件且本地无已入库状态时，查冲突预检区分「已入库/已删除」
  const draftsKey = draftFiles.join('|');
  useEffect(() => {
    let alive = true;
    (async () => {
      const next: Record<string, { existing: { id: string; path: string; module: string } | null } | null> = {};
      for (const f of draftFiles) {
        if (state[f]?.promotedTo || metaMap[f] || f in resolved) continue;
        try {
          const r = await draftsApi.conflict(f);
          if (alive) next[f] = { existing: r.existing };
        } catch { if (alive) next[f] = null; }
      }
      if (alive && Object.keys(next).length > 0) setResolved(prev => ({ ...prev, ...next }));
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftsKey, metaMap]);

  const setOne = (file: string, patch: Partial<DraftCardState>) =>
    setState(prev => ({ ...prev, [file]: { ...prev[file], ...patch } }));

  const handleValidate = async (file: string) => {
    setOne(file, { validating: true, validate: undefined });
    try {
      const r = await draftsApi.validate(file);
      setOne(file, { validate: r });
    } catch (e: any) {
      setOne(file, { validate: { verdict: 'ERROR', findings: [{ level: 'ERROR', rule: 'HTTP', message: e.message || '校验失败' }] } });
    } finally {
      setOne(file, { validating: false });
    }
  };

  const handleTrial = async (file: string) => {
    if (!window.confirm(`试跑将真实调用目标环境（按依赖闭包执行，会产生真实测试数据）。\n确认试跑 ${file}？`)) return;
    setOne(file, { running: true, trial: undefined });
    try {
      const r = await draftsApi.trialRun(file);
      setOne(file, { trial: r });
    } catch (e: any) {
      setOne(file, { trial: { ok: false, error: e.message || '试跑失败' } });
    } finally {
      setOne(file, { running: false });
    }
  };

  /** K-xxx：入库弹窗——预检 ID 冲突，冲突时自动选中既有模块并勾选覆盖 */
  const openPromote = async (file: string) => {
    setDialog({ file, open: true });
    setDlgModule('');
    setDlgCustom('');
    setDlgReplace(false);
    setDlgConflict(null);
    setDlgError('');
    try {
      const c = await draftsApi.conflict(file);
      setDlgConflict(c);
      if (c.existing) {
        setDlgModule(c.existing.module);   // 既有场景所在模块
        setDlgReplace(true);               // 覆盖更新语义
      }
    } catch { /* 预检失败不阻塞弹窗（入库时后端仍会拦） */ }
  };

  const handlePromote = async () => {
    const file = dialog.file;
    const module = dlgModule === '__new__' ? dlgCustom.trim() : dlgModule;
    if (!module) { setDlgError('请选择入库模块'); return; }
    setPromoting(true);
    setDlgError('');
    try {
      const r = await draftsApi.promote(file, module, dlgReplace);
      setOne(file, { promotedTo: r.target || module, scenarioId: r.scenario_id || '' });
      setDialog({ file: '', open: false });
      refresh();
    } catch (e: any) {
      setDlgError(e.message || '入库失败');
    } finally {
      setPromoting(false);
    }
  };

  const handleDiscard = async (file: string) => {
    if (!window.confirm(`确认废弃 ${file}？（移入 drafts/_trash/，可人工恢复）`)) return;
    try {
      await draftsApi.discard(file);
      setOne(file, { discarded: true });
      refresh();
    } catch (e: any) {
      onError(`废弃失败：${e.message || ''}`);
    }
  };

  const busyAll = promoting;

  return (
    <div className="px-2 py-2 space-y-2">
      <div className="px-1 text-xs font-medium text-gray-300">📝 草稿产物（Agent 会话内评审）</div>
      {draftFiles.length === 0 && (
        <div className="text-[11px] text-gray-600 text-center py-8 leading-relaxed">
          Agent 尚未写入草稿。<br />写入后自动出现在这里，<br />可直接查看 / 校验 / 试跑 / 入库
        </div>
      )}
      {draftFiles.map(file => {
        const meta = metaMap[file];
        const st = state[file] || {};
        if (st.discarded) return null;
        // 去向判定：① 本会话已入库 → ② 刷新后无本地状态，conflict 预检命中库内 = 已入库 → ③ 未命中 = 已删除
        const libHit = st.promotedTo
          ? { path: st.promotedTo, scenarioId: st.scenarioId || '' }
          : (resolved[file]?.existing
              ? { path: resolved[file]!.existing!.path, scenarioId: resolved[file]!.existing!.id }
              : null);
        const gone = !st.promotedTo && !meta && resolved[file] !== undefined && !resolved[file]?.existing;
        const checking = !st.promotedTo && !meta && resolved[file] === undefined;
        return (
          <div key={file} className="rounded-lg border border-border bg-surface-2/70 p-2">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-mono text-gray-200 truncate flex-1" title={file}>{file}</span>
              {meta?.stale && (
                <span className="text-[9px] text-yellow-400 flex-shrink-0" title="来源信息包存在已变更文件，草稿可能过时">⚠️</span>
              )}
              {meta && suggCount[meta.scenario_id] > 0 && !st.promotedTo && (
                <span className="text-[9px] text-info flex-shrink-0" title={`${suggCount[meta.scenario_id]} 条依赖建议——到草稿评审页可一键采纳`}>
                  💡{suggCount[meta.scenario_id]}
                </span>
              )}
            </div>
            <div className="text-[10px] truncate" title={meta?.title || libHit?.path || ''}>
              {libHit ? (
                <span className="text-green-400/90">✅ 已在场景库 · {libHit.scenarioId} · {libHit.path}</span>
              ) : gone ? (
                <span className="text-gray-600">草稿已不存在（已废弃或删除）</span>
              ) : checking ? (
                <span className="text-gray-600">检测草稿去向…</span>
              ) : meta
                ? `${meta.scenario_id || ''}${meta.title ? ` · ${meta.title}` : ''}`
                : '（草稿文件不存在或已删除）'}
            </div>

            {/* 校验结果 */}
            {st.validate && (
              <div className={`mt-1.5 text-[10px] rounded px-1.5 py-1 ${
                st.validate.verdict === 'PASS' ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'
              }`}>
                <div className="font-medium">
                  {st.validate.verdict}
                  {st.validate.summary && ` · error ${st.validate.summary.error ?? 0} / warn ${st.validate.summary.warn ?? 0}`}
                </div>
                {(st.validate.findings || []).slice(0, 4).map((f, i) => (
                  <div key={i} className={f.level === 'ERROR' ? 'text-red-400' : 'text-gray-500'}>
                    [{f.rule}] {f.message}
                  </div>
                ))}
              </div>
            )}
            {/* 试跑结果 */}
            {st.trial && (
              <div className={`mt-1.5 text-[10px] rounded px-1.5 py-1 ${
                st.trial.ok ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'
              }`}>
                {st.trial.ok
                  ? `✅ 试跑通过（${st.trial.verdict || ''}${st.trial.env ? ` @${st.trial.env}` : ''}）`
                  : `❌ 试跑失败：${st.trial.error || st.trial.reason || '未知错误'}`}
              </div>
            )}

            {/* 已入库（本会话或刷新后检出）：草稿已移入场景库，只留 DAG 跳转，不再提供草稿级操作 */}
            {libHit ? (
              <div className="flex items-center gap-1 mt-2">
                <button
                  onClick={() => navigate(`/dag?focus=${encodeURIComponent(libHit.scenarioId)}`)}
                  className="px-2 py-1 rounded bg-info/20 text-info text-[11px] hover:bg-info/30"
                  title="入库不是终点：到 DAG 编排里查看节点 / 连线 / 执行">
                  🕸 DAG 编排
                </button>
                <span className="ml-auto text-[9px] text-gray-600">
                  试跑/校验请到执行控制页选中该场景运行
                </span>
              </div>
            ) : gone ? (
              <div className="mt-2 text-[9px] text-gray-600">
                如需重新生成，请让 Agent 用 next_scenario_id 取新 ID
              </div>
            ) : (
              <div className="flex flex-wrap gap-1 mt-2">
                <button onClick={() => onViewFile(file, 'draft')} disabled={busyAll}
                  className="px-2 py-1 rounded bg-surface-3 text-gray-300 text-[11px] hover:bg-surface-1 disabled:opacity-40">查看</button>
                <button onClick={() => handleValidate(file)} disabled={busyAll}
                  className="px-2 py-1 rounded bg-surface-3 text-gray-300 text-[11px] hover:bg-surface-1 disabled:opacity-40">
                  {st.validating ? '校验中…' : '① 校验'}
                </button>
                <button onClick={() => handleTrial(file)} disabled={busyAll}
                  className="px-2 py-1 rounded bg-warn/20 text-warn text-[11px] hover:bg-warn/30 disabled:opacity-40">
                  {st.running ? '试跑中…' : '▶ 试跑'}
                </button>
                <button onClick={() => openPromote(file)} disabled={busyAll || !!st.promotedTo}
                  className="px-2 py-1 rounded bg-info text-white text-[11px] hover:bg-info/90 disabled:opacity-40">⬆ 入库</button>
                <button onClick={() => handleDiscard(file)} disabled={busyAll || !!st.promotedTo}
                  className="ml-auto px-2 py-1 rounded text-gray-500 text-[11px] hover:text-red-400 disabled:opacity-40">废弃</button>
              </div>
            )}
          </div>
        );
      })}

      {/* 入库弹窗（模块选择 + 覆盖勾选 + 冲突预检提示） */}
      {dialog.open && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center"
          onClick={() => !promoting && setDialog({ file: '', open: false })}>
          <div className="bg-surface-2 border border-border rounded-xl p-4 w-[440px] max-w-[92vw] shadow-2xl"
            onClick={e => e.stopPropagation()}>
            <div className="text-sm font-medium text-gray-200 mb-2">⬆ 入库评审 — <span className="font-mono">{dialog.file}</span></div>
            {dlgConflict?.existing && (
              <div className="mb-2 text-[11px] rounded bg-yellow-900/30 text-yellow-400 px-2 py-1.5 leading-relaxed">
                ⚠️ 场景 ID <span className="font-mono">{dlgConflict.existing.id}</span> 已存在于
                <span className="font-mono"> {dlgConflict.existing.path}</span>
                <div className="mt-0.5">已自动选中该模块并勾选「覆盖」（覆盖更新会备份原文件，失败自动回滚）；新增场景请改用 next_scenario_id 换新 ID。</div>
              </div>
            )}
            <div className="text-[11px] text-gray-500 mb-1">入库模块（scenarios/ 下）</div>
            <select value={dlgModule} onChange={e => { setDlgModule(e.target.value); setDlgError(''); }}
              className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-300 mb-2">
              {modules.length === 0 && <option value="">（无已有模块）</option>}
              {modules.map(m => <option key={m} value={m}>{m}</option>)}
              <option value="__new__">＋ 新建模块…</option>
            </select>
            {dlgModule === '__new__' && (
              <input value={dlgCustom} onChange={e => setDlgCustom(e.target.value)}
                placeholder="新模块路径（如 system-settings/tag-library）"
                className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-300 mb-2" />
            )}
            <label className="flex items-center gap-2 text-[12px] text-gray-400 mb-2 cursor-pointer select-none">
              <input type="checkbox" checked={dlgReplace} onChange={e => setDlgReplace(e.target.checked)} />
              覆盖同名场景（原文件备份 + 失败自动回滚）
            </label>
            {dlgError && <div className="mb-2 text-[11px] text-red-400">❌ {dlgError}</div>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setDialog({ file: '', open: false })} disabled={promoting}
                className="px-3 py-1.5 rounded bg-surface-3 text-gray-300 text-sm disabled:opacity-40">取消</button>
              <button onClick={handlePromote} disabled={promoting}
                className="px-3 py-1.5 rounded bg-info text-white text-sm disabled:opacity-40">
                {promoting ? '入库中…（校验→基线→门禁）' : '确认入库'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 会话依赖图面板（K-xxx：Agent 对话内直接看依赖——草稿 + 直接上下游闭包的图形化视图） ──
const nodeTypes = { scenario: ScenarioNode };

/** 边状态配色（与 DagEditor 一致：match 低调灰 / minor 蓝 / major 琥珀 / orphan 红虚线） */
const EDGE_STATUS_STYLE: Record<string, { stroke: string; dash?: string }> = {
  match: { stroke: '' },
  minor_drift: { stroke: '#58a6ff' },
  major_drift: { stroke: '#d29922' },
  orphan: { stroke: '#f85149', dash: '6 4' },
};

function DepGraphPanel({ draftFiles, onError }: {
  draftFiles: string[];
  onError: (msg: string) => void;
}) {
  const navigate = useNavigate();
  const tokens = useJsTokens();
  const [dag, setDag] = useState<DagData | null>(null);
  const [draftMeta, setDraftMeta] = useState<Record<string, DraftItem>>({});
  const [draftNodes, setDraftNodes] = useState<{ id: string; data: Record<string, unknown> }[]>([]);
  const [draftEdges, setDraftEdges] = useState<{ source: string; target: string; label?: string; status?: string }[]>([]);
  const [cycles, setCycles] = useState<string[][]>([]);
  const [loading, setLoading] = useState(true);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [d, dl, drift] = await Promise.all([
          scenariosApi.dag(), draftsApi.list(), scenariosApi.drift(),
        ]);
        if (!alive) return;
        setDag(d);
        const m: Record<string, DraftItem> = {};
        for (const x of dl.drafts || []) m[x.filename] = x;
        setDraftMeta(m);
        setCycles(drift.cycles || []);
        // 会话相关草稿 → 独立节点 + 解析 depends_on 构建草稿边（草稿未入库，不在场景库 DAG 中）
        const nodes: { id: string; data: Record<string, unknown> }[] = [];
        const edges: { source: string; target: string; label?: string; status?: string }[] = [];
        for (const f of draftFiles) {
          const meta = m[f];
          const sid = meta?.scenario_id || f.replace(/\.ya?ml$/i, '');
          nodes.push({ id: sid, data: { label: sid, title: meta?.title || '', isDraft: true } });
          try {
            const r = await draftsApi.read(f);
            for (const dep of r.depends_on || []) {
              edges.push({ source: dep, target: sid, label: '', status: 'match' });
            }
          } catch { /* 草稿已入库/废弃读不到时跳过，节点仍保留 */ }
        }
        if (alive) { setDraftNodes(nodes); setDraftEdges(edges); }
      } catch (e: any) {
        if (alive) onError(`依赖图加载失败: ${e.message || ''}`);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftFiles.join('|')]);

  // 会话相关场景 = 草稿 scenario_id ∪ 直接依赖邻居（保持边可见）
  const scope = useMemo(() => {
    if (!dag && draftNodes.length === 0) return { seed: new Set<string>(), nodes: [] as { id: string; data: Record<string, unknown> }[], edges: [] as { source: string; target: string; label?: string; status?: string }[] };
    const seed = new Set<string>();
    draftFiles.forEach(f => {
      const meta = draftMeta[f];
      if (meta?.scenario_id) seed.add(meta.scenario_id);
      else seed.add(f.replace(/\.ya?ml$/i, ''));  // 文件名兜底 = 场景 ID
    });
    const keep = new Set(seed);
    const allEdges = [...(dag?.edges || []), ...draftEdges];
    allEdges.forEach(e => {
      if (seed.has(e.source) || seed.has(e.target)) { keep.add(e.source); keep.add(e.target); }
    });
    const dagNodes = dag?.nodes || [];
    const dagIds = new Set(dagNodes.map(n => n.id));
    // 草稿已入库时 DAG 已有同 ID 节点（含完整 label/title/category），不重复追加
    const allNodes = [...dagNodes, ...draftNodes.filter(n => !dagIds.has(n.id))];
    return {
      seed,
      nodes: allNodes.filter(n => keep.has(n.id)),
      edges: allEdges.filter(e => keep.has(e.source) && keep.has(e.target)),
    };
  }, [dag, draftMeta, draftFiles, draftNodes, draftEdges]);

  // ELK 布局 → React Flow 节点/边（会话闭包通常小图，懒加载 elkjs 成本可接受）
  useEffect(() => {
    if (scope.nodes.length === 0) { setRfNodes([]); setRfEdges([]); return; }
    let alive = true;
    (async () => {
      try {
        const pos = await layoutDagByELK(scope.nodes.map(n => ({ id: n.id })), scope.edges as Edge[]);
        if (!alive) return;
        setRfNodes(scope.nodes.map(n => ({
          id: n.id,
          type: 'scenario',
          position: { x: pos.get(n.id)?.x ?? 0, y: pos.get(n.id)?.y ?? 0 },
          data: n.data,
        })));
        setRfEdges(scope.edges.map((e, i) => {
          const st = EDGE_STATUS_STYLE[e.status || 'match'] || EDGE_STATUS_STYLE.match;
          return {
            id: `e${i}`,
            source: e.source,
            target: e.target,
            label: e.label || undefined,
            style: {
              stroke: st.stroke || tokens.edgeStroke,
              strokeDasharray: st.dash,
            },
          };
        }));
      } catch { /* ELK 布局失败：保持空画布，统计行仍可见 */ }
    })();
    return () => { alive = false; };
  }, [scope, tokens]);

  const cycleSets = useMemo(() => cycles.map(c => new Set(c)), [cycles]);

  return (
    <div className="px-2 py-2 space-y-2">
      <div className="px-1 text-xs font-medium text-gray-300">🕸 依赖图（会话相关闭包）</div>
      {loading ? (
        <div className="text-[11px] text-gray-600 text-center py-8">加载中…</div>
      ) : (!dag && draftNodes.length === 0) || scope.nodes.length === 0 ? (
        <div className="text-[11px] text-gray-600 text-center py-8 leading-relaxed">
          会话还没有草稿 / 场景。<br />Agent 写完草稿后，这里自动显示<br />它与其他测试的依赖关系
        </div>
      ) : (
        <>
          <div className="px-1 text-[10px] text-gray-600">
            {scope.nodes.length} 个场景 · {scope.edges.length} 条依赖边
            {cycleSets.length > 0 && <span className="text-fail"> · ⛔ {cycleSets.length} 条环</span>}
          </div>
          {/* 图形化画布（只读查看，不跳转 DAG 编排） */}
          <div className="h-72 border border-border rounded-lg overflow-hidden" style={{ background: tokens.rfBackground }}>
            {rfNodes.length > 0 ? (
              <ReactFlow
                nodes={rfNodes}
                edges={rfEdges}
                nodeTypes={nodeTypes}
                nodesDraggable={false}
                nodesConnectable={false}
                fitView
                minZoom={0.2}
                maxZoom={1.5}
                proOptions={{ hideAttribution: true }}
              >
                <Background color={tokens.rfBackground} gap={20} />
              </ReactFlow>
            ) : (
              <div className="text-[11px] text-gray-600 text-center py-8">布局中…</div>
            )}
          </div>
          <div className="px-1 pt-1">
            <button onClick={() => navigate('/dag')}
              className="w-full px-2 py-1.5 rounded border border-border text-[11px] text-info hover:border-info/40">
              🕸 打开 DAG 编排（选择子集）
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── 右侧面板组件（引用 + 信息包 + 上下文 + 待办） ──
// ── K-032：右侧页签面板（待办首页 + 信息包页签 + 文件各自页签） ──
interface FileTab {
  path: string;
  kind: 'file' | 'draft';
  content: string;
  format?: 'raw' | 'markdown' | 'text';
  loading: boolean;
  hunks?: DocHunk[];  // T-511：阅读足迹打开时携带的使用位置（行区间定位+高亮）
}

function SidePanel({ ctxUsage, planItems, structuredTodos, loading, messages, ctxLimit, stats, scenarioMeta, onUpdateMeta, onError, references, onViewFile, fileTabs, activeTab, onSelectTab, onCloseTab, width, onCollapse, maximized, onToggleMaximize, draftFiles, readingFeed, onOpenDocRead }: {
  ctxUsage: CtxUsage | null;
  planItems: string[];
  structuredTodos: StructuredTodo[];
  loading: boolean;
  messages: ChatMessage[];
  ctxLimit: number;
  stats: AgentStats | null;
  scenarioMeta: ScenarioMeta | null;
  onUpdateMeta: (m: ScenarioMeta) => void;
  onError: (msg: string) => void;
  references: ChatReference[];
  onViewFile: (path: string, kind?: 'file' | 'draft') => void;
  fileTabs: FileTab[];
  activeTab: string;
  onSelectTab: (id: string) => void;
  onCloseTab: (path: string) => void;
  width: number | string;  // K-033：拖拽调宽（父组件托管）；K-039：最大化时 '100%'
  onCollapse?: () => void;  // K-037：收起为细条（父组件托管）
  maximized?: boolean;          // K-039：面板最大化（吃掉会话区）
  onToggleMaximize?: () => void;
  draftFiles: string[];         // K-xxx：会话内 Agent 写入的草稿（产物区）
  readingFeed: DocReadItem[];   // T-511：阅读足迹（doc_read 事件汇聚，时间倒序）
  onOpenDocRead: (item: DocReadItem, hunk?: DocHunk) => void;
}) {
  const isFileTab = activeTab.startsWith('file:');
  const activeFile = isFileTab ? fileTabs.find(t => `file:${t.path}` === activeTab) : null;

  const tabBtn = (id: string, label: string, closable = false, path = '') => (
    <button
      key={id}
      onClick={() => onSelectTab(id)}
      className={`flex items-center gap-1 px-2.5 py-1.5 text-[11px] border-b-2 whitespace-nowrap transition-colors ${
        activeTab === id
          ? 'border-info text-gray-200 bg-surface-3/50'
          : 'border-transparent text-gray-500 hover:text-gray-300'
      }`}
      title={path || label}
    >
      <span className="max-w-[120px] truncate">{label}</span>
      {closable && (
        <span
          onClick={(e) => { e.stopPropagation(); onCloseTab(path); }}
          className="text-gray-600 hover:text-red-400 ml-0.5"
        >✕</span>
      )}
    </button>
  );

  return (
    <div
      className="flex-shrink-0 border-l border-border bg-surface-2/50 flex flex-col min-h-0"
      style={{ width }}
    >      {/* 页签条（K-032：参考编辑器页签样式） */}
      <div className="flex items-center border-b border-border overflow-x-auto flex-shrink-0">
        {tabBtn('todos', '📋 待办')}
        {tabBtn('reading', readingFeed.length > 0 ? `📖 阅读(${readingFeed.length})` : '📖 阅读')}
        {scenarioMeta && tabBtn('pack', `📦 信息包(${scenarioMeta.info_pack.length})`)}
        {tabBtn('drafts', `📝 草稿产物(${draftFiles.length})`)}
        {tabBtn('deps', '🕸 依赖图')}
        {fileTabs.map(t => tabBtn(`file:${t.path}`, `📄 ${t.path.split('/').pop()}`, true, t.path))}
        {onToggleMaximize && (
          <button onClick={onToggleMaximize} title={maximized ? '还原面板' : '最大化面板（占满会话区）'}
            className="ml-auto px-2 py-1.5 text-[11px] text-gray-600 hover:text-info flex-shrink-0">
            {maximized ? '⤡' : '⤢'}
          </button>
        )}
        {onCollapse && (
          <button onClick={onCollapse} title="收起面板"
            className={`${onToggleMaximize ? '' : 'ml-auto '}px-2 py-1.5 text-[11px] text-gray-600 hover:text-info flex-shrink-0`}>
            »
          </button>
        )}
      </div>

      {/* 页签内容 */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTab === 'todos' && (
          <>
            {references.length > 0 && <RefPanel refs={references} onView={onViewFile} />}
            {(planItems.length > 0 || structuredTodos.length > 0) && (
              <TodoPanel todos={structuredTodos} planItems={planItems} loading={loading} />
            )}
            {ctxUsage && <ContextPanel ctxUsage={ctxUsage} messages={messages} ctxLimit={ctxLimit} stats={stats} />}
            {references.length === 0 && planItems.length === 0 && structuredTodos.length === 0 && !ctxUsage && (
              <div className="text-xs text-gray-600 text-center py-6">暂无上下文与待办</div>
            )}
          </>
        )}
        {activeTab === 'reading' && (
          <ReadingPanel items={readingFeed} onOpen={onOpenDocRead} />
        )}
        {activeTab === 'pack' && scenarioMeta && (
          <InfoPackPanel meta={scenarioMeta} onUpdate={onUpdateMeta} onError={onError}
            onViewFile={(p) => onViewFile(p)} defaultOpen />
        )}
        {activeTab === 'drafts' && (
          <DraftArtifactsPanel draftFiles={draftFiles} onViewFile={onViewFile} onError={onError} />
        )}
        {activeTab === 'deps' && (
          <DepGraphPanel draftFiles={draftFiles} onError={onError} />
        )}
        {activeFile && (
          <div className="h-full min-h-0 flex flex-col">
            <div className="px-3 py-1.5 border-b border-border text-[10px] font-mono text-gray-500 truncate flex-shrink-0"
              title={activeFile.path}>
              {activeFile.path}
            </div>
            <div className="flex-1 min-h-0">
              <FileViewer path={activeFile.path} content={activeFile.content}
                loading={activeFile.loading} format={activeFile.format} hunks={activeFile.hunks} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 模块级会话存储（跨导航保持 WebSocket 和会话状态） ──
const _store = {
  ws: null as WebSocket | null,
  mounted: false,
  buffer: [] as any[],
  // 会话状态快照
  messages: [] as ChatMessage[],
  loading: false,
  sessionId: '',
  sessionTitle: '',
  stats: null as AgentStats | null,
  turnInfo: '',
  error: '',
  planItems: [] as string[],
  ctxUsage: null as CtxUsage | null,
  wsState: 'connecting' as 'connecting' | 'open' | 'closed',
  readingFeed: [] as DocReadItem[],  // T-511：阅读足迹（跨导航保持，与 messages 同生命周期）
};

// ── 复制按钮（独立组件，自管理反馈状态） ──
function CopyButton({ text, className }: { text: string; className?: string }) {
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

// ── 多轮会话导航图标列（独立组件，与消息滚动容器平级） ──
function ConversationRail({ userMsgs, railPos, activeUserGroupIdx, inViewSet, hoverUserIdx, onHover, onJump }: {
  userMsgs: { groupIdx: number; content: string }[];
  railPos: { idx: number; pct: number }[];
  activeUserGroupIdx: number | null;
  inViewSet: Set<number>;
  hoverUserIdx: number | null;
  onHover: (idx: number | null) => void;
  onJump: (groupIdx: number) => void;
}) {
  if (userMsgs.length < 2) return null;
  return (
    <div className="flex-shrink-0 w-4 relative">
      {/* 连接竖线 */}
      {railPos.length >= 2 && (
        <div className="absolute left-1/2 -translate-x-1/2 top-[15%] bottom-[15%] w-px bg-border/30" />
      )}
      {railPos.map(p => {
        const seq = userMsgs.findIndex(u => u.groupIdx === p.idx) + 1;
        const um = userMsgs.find(u => u.groupIdx === p.idx);
        const isActive = activeUserGroupIdx === p.idx;
        const isInView = inViewSet.has(p.idx);
        return (
          <div key={p.idx} className="absolute left-1/2 -translate-x-1/2" style={{ top: `${p.pct}%`, transform: 'translateY(-50%)' }}>
            <button
              onClick={() => onJump(p.idx)}
              onMouseEnter={() => onHover(p.idx)}
              onMouseLeave={() => onHover(null)}
              title={`第 ${seq} 轮对话`}
              className="flex items-center justify-center h-5 w-5 group"
            >
              <span className={`block rounded-full transition-all duration-150 ${
                isActive ? 'h-3 w-3 bg-pinnedBg ring-2 ring-pinnedBg/30' :
                isInView ? 'h-2.5 w-2.5 bg-railDot/70' :
                'h-2 w-2 bg-railDot group-hover:bg-railDot/80'
              } ${hoverUserIdx === p.idx ? 'scale-125' : ''}`} />
            </button>
            {hoverUserIdx === p.idx && um && (
              <div className="absolute left-6 top-1/2 -translate-y-1/2 z-20 w-72 bg-surface-2 border border-border rounded-lg shadow-xl p-2.5 pointer-events-none">
                <div className="text-[10px] text-railDot mb-1 font-medium">第 {seq} 轮 · 用户消息</div>
                <div className="text-xs text-gray-300 line-clamp-3 break-all">{um.content}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── @候选类型（ChatInput 内部使用）──
interface AtCandidate { type: 'info_pack' | 'file' | 'draft'; id: string; label: string; hint: string }

// ── ChatInput 组件（独立子组件，打字不触发父组件重渲染）──
interface ChatInputProps {
  wsState: 'connecting' | 'open' | 'closed';
  loading: boolean;
  models: ModelConfig[];
  currentModelId: string;
  onSend: (text: string, references: ChatReference[]) => boolean;  // 返回是否真正发出（ true 时输入框清空）
  onStop: () => void;
  onNewSession: () => void;
  onClearMessages: () => void;
  onExportSession: () => void;
  onModelChange: (id: string) => void;
}

function ChatInput({
  wsState, loading, models, currentModelId,
  onSend, onStop, onNewSession, onClearMessages, onExportSession, onModelChange,
}: ChatInputProps) {
  const [input, setInput] = useState('');
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState('');
  const [slashIndex, setSlashIndex] = useState(0);
  const [atOpen, setAtOpen] = useState(false);
  const [atQuery, setAtQuery] = useState('');
  const [atIndex, setAtIndex] = useState(0);
  const [atMetas, setAtMetas] = useState<ScenarioMeta[]>([]);
  const [atDrafts, setAtDrafts] = useState<DraftItem[]>([]);
  const [atFileResults, setAtFileResults] = useState<{ path: string; preview: string }[]>([]);
  const [references, setReferences] = useState<ChatReference[]>([]);
  const [attaching, setAttaching] = useState(false);
  const attachInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 斜杠命令过滤
  const filteredCommands = useMemo(() => {
    if (!slashQuery) return SLASH_COMMANDS;
    return SLASH_COMMANDS.filter(c => c.cmd.includes(slashQuery) || c.label.includes(slashQuery));
  }, [slashQuery]);

  // @候选
  const atCandidates = useMemo<AtCandidate[]>(() => {
    const q = atQuery.toLowerCase();
    const list: AtCandidate[] = [];
    for (const m of atMetas) {
      if (!q || m.id.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q)) {
        list.push({ type: 'info_pack', id: m.id, label: `📦 ${m.name || m.id}`, hint: `信息包 · ${m.info_pack?.length || 0} 文件` });
      }
    }
    for (const d of atDrafts) {
      if (!q || d.filename.toLowerCase().includes(q) || (d.title || '').toLowerCase().includes(q)) {
        list.push({ type: 'draft', id: d.filename, label: `📝 ${d.title || d.filename}`, hint: `草稿 · ${d.filename}` });
      }
    }
    for (const f of atFileResults) {
      list.push({ type: 'file', id: f.path, label: `📄 ${f.path}`, hint: '工作区文件' });
    }
    return list.slice(0, 20);
  }, [atMetas, atDrafts, atFileResults, atQuery]);

  // 输入框高度自适应
  useEffect(() => {
    const ta = inputRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 128)}px`;
  }, [input]);

  // @候选懒加载
  const atLoadedRef = useRef(false);
  useEffect(() => {
    if (!atOpen || atLoadedRef.current) return;
    atLoadedRef.current = true;
    scenarioApi.listMeta().then(r => setAtMetas(r.metas || [])).catch(() => {});
    draftsApi.list().then(r => setAtDrafts(r.drafts || [])).catch(() => {});
  }, [atOpen]);

  // @文件搜索（防抖，≥2 字符）
  useEffect(() => {
    if (!atOpen || atQuery.length < 2) { setAtFileResults([]); return; }
    const timer = setTimeout(() => {
      workspaceApi.search(atQuery)
        .then(r => setAtFileResults((r.results || []).map(x => ({ path: x.path, preview: x.preview }))))
        .catch(() => setAtFileResults([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [atOpen, atQuery]);

  const handleInputChange = (value: string) => {
    setInput(value);
    if (value.startsWith('/') && !value.includes(' ')) {
      setSlashOpen(true); setSlashQuery(value); setSlashIndex(0);
    } else {
      setSlashOpen(false);
    }
    const atMatch = value.match(/@([^\s@]*)$/);
    if (atMatch) {
      setAtOpen(true); setAtQuery(atMatch[1]); setAtIndex(0);
    } else {
      setAtOpen(false);
    }
  };

  const handleAtSelect = (c: { type: 'info_pack' | 'file' | 'draft'; id: string }) => {
    setInput(prev => prev.replace(/@[^\s@]*$/, ''));
    setAtOpen(false);
    if (c.type === 'info_pack') {
      const m = atMetas.find(x => x.id === c.id);
      setReferences(prev => [
        ...prev.filter(r => r.type !== 'info_pack'),
        { type: 'info_pack', path: c.id, sha: '', label: m?.name || c.id },
      ]);
    } else {
      setReferences(prev => prev.some(r => r.type === c.type && r.path === c.id)
        ? prev : [...prev, { type: c.type, path: c.id, sha: '' }]);
    }
    inputRef.current?.focus();
  };

  const handleSlashSelect = (cmd: SlashCommand) => {
    setSlashOpen(false); setInput('');
    if (cmd.type === 'action') {
      if (cmd.cmd === '/new') { onNewSession(); }
      else if (cmd.cmd === '/clear') { onClearMessages(); }
      else if (cmd.cmd === '/undo') {
        onSend('请使用 undo_draft 工具撤销最后一次草稿写入。如果不知道文件名，请先查看 drafts 目录。', []);
      } else if (cmd.cmd === '/export') { onExportSession(); }
    } else if (cmd.type === 'skill') {
      const skillName = cmd.skillName || cmd.cmd.replace('/', '');
      setInput(`请使用 ${skillName} 技能${skillName === 'dag-orchestration' ? '编排场景依赖' : ''}：`);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (atOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setAtIndex(i => Math.min(i + 1, atCandidates.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setAtIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (atCandidates[atIndex]) handleAtSelect(atCandidates[atIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setAtOpen(false); return; }
    }
    if (slashOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIndex(i => Math.min(i + 1, filteredCommands.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSlashIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (filteredCommands[slashIndex]) handleSlashSelect(filteredCommands[slashIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setSlashOpen(false); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  };

  // 发送成功（onSend 返回 true）才清空输入框——发送被拒（断连/加载中）时保留草稿
  const doSend = () => {
    if (onSend(input.trim(), references)) setInput('');
  };

  const handleAttachFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setAttaching(true);
    try {
      const meta = await scenarioApi.autoCreateInfoPack(Array.from(files));
      setReferences(prev => [
        ...prev.filter(r => r.type !== 'info_pack'),
        { type: 'info_pack', path: meta.id, sha: '', label: `${meta.name}（${(meta.info_pack || []).length} 个文件）` },
      ]);
      setAtMetas(prev => [meta, ...prev.filter(m => m.id !== meta.id)]);
    } catch {
      // 附件上传失败静默处理
    } finally {
      setAttaching(false);
      if (attachInputRef.current) attachInputRef.current.value = '';
    }
  };

  return (
    <div className="flex-shrink-0 border-t border-border p-3 relative">
      {/* slash 命令弹出层 */}
      {slashOpen && filteredCommands.length > 0 && (
        <div className="absolute bottom-full left-3 right-3 mb-1 bg-surface-2 border border-border rounded-lg shadow-xl max-h-60 overflow-y-auto z-10">
          {filteredCommands.map((c, i) => (
            <button key={c.cmd} onClick={() => handleSlashSelect(c)}
              className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-colors ${
                i === slashIndex ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
              }`}>
              <span className="font-mono text-xs text-info/70">{c.cmd}</span>
              <span className="text-xs">{c.label}</span>
              <span className="text-[10px] text-gray-600 ml-auto">{c.desc}</span>
            </button>
          ))}
        </div>
      )}

      {/* @引用候选层 */}
      {atOpen && atCandidates.length > 0 && (
        <div className="absolute bottom-full left-3 right-3 mb-1 bg-surface-2 border border-border rounded-lg shadow-xl max-h-60 overflow-y-auto z-10">
          {atCandidates.map((c, i) => (
            <button key={`${c.type}:${c.id}`} onClick={() => handleAtSelect(c)}
              className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                i === atIndex ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
              }`}>
              <span className="text-xs truncate">{c.label}</span>
              <span className="text-[10px] text-gray-600 ml-auto flex-shrink-0">{c.hint}</span>
            </button>
          ))}
        </div>
      )}

      {/* 已选引用 chips */}
      {references.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {references.map((r, i) => (
            <span key={`${r.type}:${r.path}`}
              className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info border border-info/30 font-mono">
              {r.type === 'info_pack' ? '📦' : r.type === 'draft' ? '📝' : '📄'} {r.label || r.path}
              <button onClick={() => setReferences(prev => prev.filter((_, j) => j !== i))}
                className="text-info/60 hover:text-fail">✕</button>
            </span>
          ))}
        </div>
      )}

      {/* 输入框 + 附件 + 发送/停止按钮 */}
      <div className="flex gap-2 items-end">
        <input
          ref={attachInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={e => handleAttachFiles(e.target.files)}
        />
        <button
          onClick={() => attachInputRef.current?.click()}
          disabled={attaching || loading || wsState !== 'open'}
          title="上传附件（自动创建信息包并关联到本轮对话）"
          className="w-10 h-10 flex-shrink-0 bg-surface-2 border border-border text-gray-400 rounded-full flex items-center justify-center hover:text-info hover:border-info/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {attaching ? <span className="animate-spin text-sm">⏳</span> : <span className="text-lg">📎</span>}
        </button>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={wsState === 'open' ? '输入消息... (Enter 发送, / 命令, @ 引用)' : 'WebSocket 未连接'}
          rows={1}
          className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none resize-none max-h-32"
          disabled={loading || wsState !== 'open'}
        />
        {loading ? (
          <button
            onClick={onStop}
            title="打断会话"
            className="w-10 h-10 flex-shrink-0 bg-red-600 text-white rounded-full flex items-center justify-center hover:bg-red-500 transition-colors"
          >
            <span className="text-lg">■</span>
          </button>
        ) : (
          <button
            onClick={doSend}
            disabled={!input.trim() || wsState !== 'open'}
            className="w-10 h-10 flex-shrink-0 bg-info text-white rounded-full flex items-center justify-center hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ↑
          </button>
        )}
      </div>

      {/* 底部模型选择器 */}
      <div className="flex items-center gap-2 mt-2">
        {models.length > 0 && (
          <select
            value={currentModelId}
            onChange={e => onModelChange(e.target.value)}
            className="bg-surface-2 border border-border rounded px-2 py-0.5 text-[10px] text-gray-400 font-mono"
          >
            {models.map(m => (
              <option key={m.id} value={m.id}>
                {m.is_default ? '★ ' : ''}{m.name || m.model}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}

export default function AgentChat() {
  const [searchParams] = useSearchParams();
  // K-013：scenarioId 状态化——@信息包 引用可在对话中关联场景（不再只能从场景管理页进入）
  const [scenarioId, setScenarioId] = useState(searchParams.get('scenario_id') || '');
  // H-5#3: 通知链接带 context 打开（debug_run_id 触发自动调试消息）
  const debugRunId = searchParams.get('debug_run_id') || '';

  // 从模块存储恢复状态（跨导航保持会话）
  const [messages, setMessages] = useState<ChatMessage[]>(_store.messages);
  const [loading, setLoading] = useState(_store.loading);
  const [sessionId, setSessionId] = useState(_store.sessionId);
  const [sessionTitle, setSessionTitle] = useState(_store.sessionTitle);
  const [stats, setStats] = useState<AgentStats | null>(_store.stats);
  const [turnInfo, setTurnInfo] = useState(_store.turnInfo);
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>(_store.wsState);
  const [error, setError] = useState(_store.error);
  const [planItems, setPlanItems] = useState<string[]>(_store.planItems);
  const [ctxUsage, setCtxUsage] = useState<CtxUsage | null>(_store.ctxUsage);
  const [readingFeed, setReadingFeed] = useState<DocReadItem[]>(_store.readingFeed);  // T-511

  const [sessions, setSessions] = useState<any[]>([]);
  const [sessionsVersion, setSessionsVersion] = useState(0);
  // T-010: 用途选择（使命卡片）
  const [purposes, setPurposes] = useState<{ id: string; title: string; icon: string; color: string; chips: string[]; description: string }[]>([]);
  const [showPurposePicker, setShowPurposePicker] = useState(false);
  const [pickedPurpose, setPickedPurpose] = useState(() => localStorage.getItem('sg_picked_purpose') || '');
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [currentModelId, setCurrentModelId] = useState('');
  const [scenarioMeta, setScenarioMeta] = useState<ScenarioMeta | null>(null);
  const [streamingText, setStreamingText] = useState('');  // K-012: 流式生成中的文本
  // K-032：文件页签（取代 modal 弹窗）+ 活动页签（'todos' | 'pack' | `file:{path}`）
  const [fileTabs, setFileTabs] = useState<FileTab[]>([]);
  const [activeSideTab, setActiveSideTab] = useState('todos');
  // K-037：会话列表 / 右侧面板 独立收起展开（localStorage 持久化）
  const [sessCollapsed, setSessCollapsed] = useState(() => localStorage.getItem('sg_sess_collapsed') === '1');
  const [sideCollapsed, setSideCollapsed] = useState(() => localStorage.getItem('sg_side_collapsed') === '1');
  const toggleSessCollapsed = useCallback(() =>
    setSessCollapsed(v => { localStorage.setItem('sg_sess_collapsed', v ? '0' : '1'); return !v; }), []);
  const toggleSideCollapsed = useCallback(() =>
    setSideCollapsed(v => { localStorage.setItem('sg_side_collapsed', v ? '0' : '1'); return !v; }), []);
  const expandSideTo = useCallback((tab: string) => {
    setActiveSideTab(tab);
    setSideCollapsed(false);
    localStorage.setItem('sg_side_collapsed', '0');
  }, []);
  // K-xxx：会话内 Agent 写入的草稿（write_draft 收集 / undo_draft 撤销）→ 右侧「草稿产物」区
  const sessionDrafts = useMemo(() => {
    const files = new Map<string, number>();
    let order = 0;
    for (const m of messages) {
      if (m.role !== 'assistant' || !m.tool_calls) continue;
      for (const tc of m.tool_calls) {
        try {
          const args = JSON.parse(tc.function.arguments);
          if (tc.function.name === 'write_draft' && args.filename) files.set(args.filename, order++);
          else if (tc.function.name === 'undo_draft' && args.filename) files.delete(args.filename);
        } catch { /* 参数解析失败忽略（工具结果渲染已展示原文） */ }
      }
    }
    return [...files.entries()].sort((a, b) => a[1] - b[1]).map(([f]) => f);
  }, [messages]);
  // K-xxx：Agent 新写入草稿 → 自动切到产物区（用户已主动切到其他页签时不打扰）
  const prevDraftCount = useRef(0);
  useEffect(() => {
    if (sessionDrafts.length > prevDraftCount.current && activeSideTab === 'todos') {
      setActiveSideTab('drafts');
    }
    prevDraftCount.current = sessionDrafts.length;
  }, [sessionDrafts, activeSideTab]);
  // K-039：一键占满——专注模式（会话区全宽）/ 面板最大化（吃掉会话区）
  const [focusMode, setFocusMode] = useState(false);
  const [sideMax, setSideMax] = useState(false);
  const preFocusRef = useRef<{ sess: boolean; side: boolean } | null>(null);
  const toggleFocusMode = useCallback(() => {
    setFocusMode(v => {
      if (!v) {
        // 进入专注：记住两侧状态并全部收起（专注是临时态，恢复时不改持久偏好）
        preFocusRef.current = { sess: sessCollapsed, side: sideCollapsed };
        setSessCollapsed(true); setSideCollapsed(true); setSideMax(false);
      } else {
        const p = preFocusRef.current;
        if (p) { setSessCollapsed(p.sess); setSideCollapsed(p.side); }
      }
      return !v;
    });
  }, [sessCollapsed, sideCollapsed]);
  const toggleSideMax = useCallback(() => {
    setSideMax(v => {
      if (!v) { setSideCollapsed(false); setFocusMode(false); }  // 最大化必展开面板
      return !v;
    });
  }, []);
  // K-033：右侧拖拽调宽（localStorage 持久化）
  const [sideWidth, setSideWidth] = useState(() => {
    const saved = parseInt(localStorage.getItem('sg_side_width') || '');
    return Number.isFinite(saved) && saved >= 220 ? saved : 288;
  });
  const sideWidthRef = useRef(sideWidth);
  sideWidthRef.current = sideWidth;
  useEffect(() => { localStorage.setItem('sg_side_width', String(sideWidth)); }, [sideWidth]);

  // K-033：拖拽柄（左缘拖动调宽，范围 220 ~ 70% 视口）
  const startSideDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = sideWidthRef.current;
    const onMove = (ev: MouseEvent) => {
      const w = Math.min(Math.max(startW + (startX - ev.clientX), 220), window.innerWidth * 0.7);
      setSideWidth(Math.round(w));
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, []);
  const [wsReconnect, setWsReconnect] = useState(0);
  // H-FE: 结构化待办（来自 todo_update 事件）
  const [structuredTodos, setStructuredTodos] = useState<StructuredTodo[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);  // K-018: WS 自动重连退避计数
  const autoSentRef = useRef(false);
  const debugSentRef = useRef(false);  // H-5#3: 调试链接自动发送
  const lastEventTimeRef = useRef(Date.now());  // TCP 半开连接防护：最后收到事件的时间
  const currentWorkspace = session.getWorkspace();

  // ── 多轮会话导航（置顶栏 + 用户消息定位图标列）──
  const msgBoxRef = useRef<HTMLDivElement>(null);            // 消息列表滚动容器
  const [pinnedDismissed, setPinnedDismissed] = useState(false);  // 置顶栏手动收起
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null);  // 定位高亮的 user 消息 groupIdx
  const [hoverUserIdx, setHoverUserIdx] = useState<number | null>(null);  // hover 悬浮的 user 消息 groupIdx
  const [inViewSet, setInViewSet] = useState<Set<number>>(new Set());  // 当前视口内的用户消息 groupIdx
  const [activeUserGroupIdx, setActiveUserGroupIdx] = useState<number | null>(null);  // 当前视口活跃的用户消息 groupIdx（动态置顶）
  const highlightTimerRef = useRef<number | null>(null);     // 高亮淡出定时器
  const lastPinnedRef = useRef('');                          // 上一次置顶的用户消息内容（自动恢复判定）

  // H-2: 推导当前页面（从 URL path 提取，供路由上下文使用）
  const currentPage = useMemo(() => {
    const path = window.location.pathname;
    if (path.includes('/execution')) return 'execution';
    if (path.includes('/editor')) return 'editor';
    if (path.includes('/dag')) return 'dag';
    if (path.includes('/feedback')) return 'feedback';
    if (path.includes('/agent')) return 'chat';
    return '';
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const r = await agentApi.listSessions('');
      setSessions(r.sessions || []);
    } catch { setSessions([]); }
  }, []);

  useEffect(() => {
    modelApi.list().then(r => {
      setModels(r.models || []);
      const def = r.models?.find(m => m.is_default);
      if (def) setCurrentModelId(def.id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (scenarioId) {
      scenarioApi.getMeta(scenarioId).then(m => setScenarioMeta(m)).catch(() => {});
    }
  }, [scenarioId]);

  useEffect(() => { loadSessions(); }, [loadSessions, sessionsVersion]);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turnInfo, streamingText]);

  // 同步状态到模块存储（跨导航保持）
  useEffect(() => { _store.messages = messages; }, [messages]);
  useEffect(() => { _store.loading = loading; }, [loading]);
  useEffect(() => { _store.sessionId = sessionId; }, [sessionId]);
  useEffect(() => { _store.sessionTitle = sessionTitle; }, [sessionTitle]);
  useEffect(() => { _store.stats = stats; }, [stats]);
  useEffect(() => { _store.turnInfo = turnInfo; }, [turnInfo]);
  useEffect(() => { _store.wsState = wsState; }, [wsState]);
  useEffect(() => { _store.error = error; }, [error]);
  useEffect(() => { _store.planItems = planItems; }, [planItems]);
  useEffect(() => { _store.ctxUsage = ctxUsage; }, [ctxUsage]);
  useEffect(() => { _store.readingFeed = readingFeed; }, [readingFeed]);

  // WebSocket（跨导航保持，不随组件卸载关闭）
  // 使用 ref 存储最新的事件处理函数，避免闭包过期
  const wsHandlerRef = useRef<(event: any) => void>(() => {});
  wsHandlerRef.current = (event: any) => {
    switch (event.type) {
      case 'state':
        if (event.status === 'started' && event.session_id) {
          setSessionId(event.session_id);
          localStorage.setItem('sg_agent_session', event.session_id);  // K-012: 持久化供刷新/重启恢复
          setSessionsVersion(v => v + 1);
        } else if (event.status === 'preparing') {
          setTurnInfo('⚙ 正在初始化…');
        } else if (event.fused) {
          setTurnInfo(`⚠️ 熔断 ${event.max_turns}`);
        } else if (typeof event.turn === 'number') {
          setTurnInfo(`${event.turn + 1}/${event.max_turns}`);
        }
        break;
      case 'assistant_delta':
        // K-012: 流式增量文本（整块 assistant 到达时替换）
        setStreamingText(prev => prev + (event.delta || ''));
        break;
      case 'assistant':
        setStreamingText('');  // 整块消息到达，流式气泡被正式消息替换
        if (event.message) {
          const content = event.message.content || '';
          const plan = extractPlan(content);
          if (plan) setPlanItems(plan);
          setMessages(prev => [...prev, event.message]);
        }
        if (event.usage) {
          setCtxUsage({
            prompt_tokens: event.usage.prompt_tokens || 0,
            completion_tokens: event.usage.completion_tokens || 0,
            total_tokens: event.usage.total_tokens || 0,
          });
        }
        break;
      case 'tool_call_start':
        // K-018：工具执行前置提示——长工具（promote 跑发布门禁等）执行期间不再死寂
        setTurnInfo(`⚙ ${event.tool || 'tool'}`);
        break;
      case 'tool_call':
        setTurnInfo('');
        setMessages(prev => [...prev, { role: 'tool', content: String(event.result ?? '') }]);
        break;
      case 'doc_read': {
        // T-511 依据透明：阅读足迹——同文件去重合并 hunks，时间倒序（新卡 prepend）
        const key = event.path || event.ref || `${event.tool}:unknown`;
        setReadingFeed(prev => {
          const hunks: DocHunk[] = (event.hunks || []).map((h: any) => ({
            title: h.title || '', start: h.start || 1, end: h.end || 1,
            note: h.note, thinking: event.thinking || undefined,
          }));
          const idx = prev.findIndex(i => i.key === key);
          if (idx === -1) {
            return [{
              key, tool: event.tool || '', ref: event.ref || '', path: event.path || null,
              turn: event.turn ?? 0, size: event.size ?? 0, excerpt: event.excerpt || '',
              label: event.label || event.tool || '', thinking: event.thinking || '',
              hunks, reads: 1,
            }, ...prev];
          }
          const old = prev[idx];
          const mergedHunks = [...old.hunks];
          for (const h of hunks) {
            if (!mergedHunks.some(o => o.start === h.start && o.end === h.end && o.title === h.title)) {
              mergedHunks.push(h);
            }
          }
          const next = [...prev];
          next[idx] = {
            ...old, turn: event.turn ?? old.turn, size: event.size ?? old.size,
            excerpt: event.excerpt || old.excerpt, label: event.label || old.label,
            thinking: event.thinking || old.thinking, hunks: mergedHunks, reads: old.reads + 1,
          };
          return next;
        });
        break;
      }
      case 'done':
        setStats(event.stats || null);
        if (event.session_id) {
          setSessionId(event.session_id);
          localStorage.setItem('sg_agent_session', event.session_id);
        }
        if (event.title) setSessionTitle(event.title);
        setTurnInfo('');
        setStreamingText('');
        setLoading(false);
        setSessionsVersion(v => v + 1);
        break;
      case 'todo_update':
        // H-FE: 结构化待办更新（todo_update 事件）
        if (event.todos) {
          setStructuredTodos(event.todos.map((t: any) => ({
            id: t.id || '',
            title: t.title || '',
            status: t.status || 'pending',
            mode: t.mode || '',
          })));
        }
        break;
      case 'heartbeat':
        // 后端心跳——连接正常（lastEventTimeRef 已在 onmessage 中更新）
        break;
      case 'title_update':
        if (event.title) {
          setSessionTitle(event.title);
          setSessionsVersion(v => v + 1);
        }
        break;
      case 'error':
        setError(event.message || 'Agent 异常');
        setStreamingText('');
        setLoading(false);
        break;
    }
  };

  useEffect(() => {
    _store.mounted = true;

    // 处理缓冲区中的事件（组件卸载期间收到的）
    if (_store.buffer.length > 0) {
      const buf = _store.buffer;
      _store.buffer = [];
      buf.forEach(e => wsHandlerRef.current(e));
    }

    // 复用已有 WebSocket 或创建新的
    if (!_store.ws || _store.ws.readyState === WebSocket.CLOSED) {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(
        `${protocol}//${window.location.host}/api/agent/ws?token=${encodeURIComponent(session.getToken())}&workspace=${encodeURIComponent(currentWorkspace)}`
      );
      _store.ws = ws;
      wsRef.current = ws;
      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        _store.wsState = 'open';
        if (_store.mounted) {
          setWsState('open');
          setError(prev => prev.startsWith('连接已断开') ? '' : prev);
        }
      };
      ws.onclose = () => {
        _store.wsState = 'closed';
        if ((ws as any)._intentional) return;  // 手动打断：handleStop 已处理重连
        if (_store.mounted) {
          setWsState('closed');
          // K-018：断线时进行中的 run 已丢失——解除 loading 卡死并自动重连（指数退避）。
          // 此前 onclose 只改状态不重连，handleSend 静默丢弃消息（「一直没响应」主因之一）
          setLoading(false);
          setStreamingText('');
          if (reconnectAttemptsRef.current < 5) {
            setError('连接已断开，正在自动重连…');
            const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 10000);
            reconnectAttemptsRef.current += 1;
            window.setTimeout(() => { if (_store.mounted) setWsReconnect(v => v + 1); }, delay);
          } else {
            setError('连接已断开，自动重连失败——请刷新页面或检查后端服务');
          }
        }
      };
      ws.onerror = () => { _store.wsState = 'closed'; if (_store.mounted) setWsState('closed'); };
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        lastEventTimeRef.current = Date.now();  // 任何事件都更新——用于半开连接检测
        if (_store.mounted) {
          wsHandlerRef.current(event);
        } else {
          _store.buffer.push(event);
        }
      };
    } else {
      // 复用已有 WebSocket，更新 ref
      wsRef.current = _store.ws;
      if (_store.mounted) setWsState(_store.wsState);
    }

    return () => {
      _store.mounted = false;
      // 不关闭 WebSocket — 保持会话活跃
    };
  }, [wsReconnect]);

  // 场景上下文自动发送
  useEffect(() => {
    if (scenarioId && wsState === 'open' && !autoSentRef.current && scenarioMeta) {
      autoSentRef.current = true;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        const msg = `请分析基础信息包中的文件，提取 FR/AC 锚点，生成测试场景 YAML 草稿。场景名称：${scenarioMeta.name}，模块：${scenarioMeta.module}`;
        setLoading(true); setError(''); setPlanItems([]);  // K-xxx：待办不再预填固定模板——由模型 todo_write/<plan> 输出，避免「刚发消息就出写死待办」 setCtxUsage(null);
        setMessages(prev => [...prev, { role: 'user', content: msg }]);
        ws.send(JSON.stringify({
          message: msg, session_id: '', max_turns: 50,
          workspace: currentWorkspace, scenario_id: scenarioId,
          model_id: currentModelId,
          context: { current_page: currentPage, editing_scenario_id: scenarioId },
        }));
      }
    }
  }, [scenarioId, wsState, scenarioMeta, currentWorkspace, currentModelId, currentPage]);

  // H-5#3: 通知链接自动打开调试（debug_run_id 触发）
  useEffect(() => {
    if (debugRunId && wsState === 'open' && !debugSentRef.current) {
      debugSentRef.current = true;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        const msg = `定时任务运行失败，请分析运行 ${debugRunId} 的失败原因。使用 read_run_report 工具读取运行报告，定位失败场景和错误根因，给出修复建议。`;
        setLoading(true); setError(''); setPlanItems([]);  // K-xxx：待办不再预填固定模板——由模型 todo_write/<plan> 输出，避免「刚发消息就出写死待办」 setCtxUsage(null);
        setMessages(prev => [...prev, { role: 'user', content: msg }]);
        ws.send(JSON.stringify({
          message: msg, session_id: '', max_turns: 50,
          workspace: currentWorkspace, scenario_id: '',
          model_id: currentModelId,
          context: {
            current_page: 'execution',
            last_run_failed: true,
            editing_scenario_id: '',
          },
        }));
      }
    }
  }, [debugRunId, wsState, currentWorkspace, currentModelId]);

  // TCP 半开连接防护：loading 期间定期检测，长时间无事件则判定连接断开并自动重连
  useEffect(() => {
    if (!loading) return;
    const timer = setInterval(() => {
      const idle = Date.now() - lastEventTimeRef.current;
      if (idle > 30000) {  // 30 秒无任何事件（3 个心跳周期）——判定连接断开
        setLoading(false);
        setStreamingText('');
        setError('连接已断开，正在自动重连…');
        setWsReconnect(v => v + 1);
      }
    }, 5000);  // 每 5 秒检查
    return () => clearInterval(timer);
  }, [loading]);

  // 发送消息
  // 返回是否真正发出——ChatInput 据此决定清空输入框（发送被拒时保留草稿）
  const handleSend = useCallback((text: string, refs: ChatReference[]): boolean => {
    const userMsg = text.trim();
    const ws = wsRef.current;
    if (!userMsg || loading) return false;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setError('连接已断开，正在尝试重连…（消息未发送，重连后请重发）');
      reconnectAttemptsRef.current = 0;
      setWsReconnect(v => v + 1);
      return false;
    }
    setLoading(true); setError(''); setTurnInfo(''); setPlanItems([]);
    const msgRefs = refs.length ? [...refs] : undefined;
    // K-015：发送时才落实 info_pack 关联（右侧信息包面板随发送出现）
    const packRef = msgRefs?.find(r => r.type === 'info_pack');
    if (packRef && packRef.path !== scenarioId) {
      autoSentRef.current = true;  // 不触发向导自动发送
      setScenarioId(packRef.path);
      scenarioApi.getMeta(packRef.path).then(setScenarioMeta).catch(() => {});
      expandSideTo('pack');  // K-037：面板收起时随发送自动展开到信息包页签
    }
    setMessages(prev => [...prev, { role: 'user', content: userMsg, references: msgRefs }]);
    ws.send(JSON.stringify({
      message: userMsg, session_id: sessionId, max_turns: 50,
      workspace: currentWorkspace, scenario_id: scenarioId,
      model_id: currentModelId,
      purpose: pickedPurpose,
      references: (msgRefs || []).map(r => ({ type: r.type, id: r.path, path: r.path })),
      context: { current_page: currentPage, editing_scenario_id: scenarioId },
    }));
    return true;
  }, [loading, sessionId, pickedPurpose, currentWorkspace, scenarioId, currentModelId, currentPage, expandSideTo]);

  // T-402: 打断会话（真打断——先调用 cancel API，再关 WS）
  const handleStop = useCallback(() => {
    // 先调用 cancel API 设置后端 cancellation 标志（不等待，静默失败）
    const sid = sessionId || localStorage.getItem('sg_agent_session');
    if (sid) {
      agentApi.cancelSession(sid).catch(() => {});
    }
    if (wsRef.current) {
      (wsRef.current as any)._intentional = true;  // K-018: 标记手动关闭，避免 onclose 重复调度重连
      wsRef.current.close();
    }
    setLoading(false);
    setTurnInfo('');
    setError('');
    setStreamingText('');
    setWsReconnect(v => v + 1);
  }, [sessionId]);

  // K-032: 打开引用文件——新增/激活右侧文件页签（取代 modal 弹窗）
  // T-511：opts.hunks 携带阅读足迹使用位置（行区间定位+高亮）；opts.fallback
  // 为 read-file 失败时的兜底内容（仓库根/sg:// 等 read-file 不可达路径 → 展示摘录）
  const openFileViewer = useCallback(async (path: string, kind: 'file' | 'draft' = 'file',
    opts?: { hunks?: DocHunk[]; fallback?: string }) => {
    const tabId = `file:${path}`;
    setActiveSideTab(tabId);
    setSideCollapsed(false);  // K-037：面板收起时打开文件自动展开
    localStorage.setItem('sg_side_collapsed', '0');
    setSideWidth(w => Math.max(w, 460));  // K-033：文件页签自动至少 460 宽（xlsx 表格）
    // 已打开过 → 直接激活（保留已加载内容，hunks 更新为最新足迹）
    let already = false;
    setFileTabs(prev => {
      if (prev.some(t => t.path === path)) {
        already = true;
        return prev.map(t => t.path === path ? { ...t, hunks: opts?.hunks ?? t.hunks } : t);
      }
      return [...prev, { path, kind, content: '', loading: true, hunks: opts?.hunks }];
    });
    if (already) return;
    try {
      const r = kind === 'draft' ? await draftsApi.read(path) : await workspaceApi.readFile(path);
      setFileTabs(prev => prev.map(t =>
        t.path === path ? { ...t, content: r.content, loading: false, format: (r as any).format } : t));
    } catch {
      if (opts?.fallback) {
        // T-511：read-file 不可达（越界/仓库根/已删除）→ 摘录兜底展示，不再移除页签
        setFileTabs(prev => prev.map(t =>
          t.path === path ? { ...t, content: opts.fallback!, loading: false, format: 'text' } : t));
      } else {
        setFileTabs(prev => prev.filter(t => t.path !== path));
        setActiveSideTab('todos');
        setError(`读取文件失败: ${path}`);
      }
    }
  }, []);

  // K-032: 关闭文件页签（关闭当前活动页签时回落到待办页）
  const closeFileTab = useCallback((path: string) => {
    setFileTabs(prev => prev.filter(t => t.path !== path));
    setActiveSideTab(prev => prev === `file:${path}` ? 'todos' : prev);
  }, []);

  // 未落盘内容预览（对话内大段 md 代码块 → 虚拟 memo: 页签，FileViewer 按 .md 渲染）
  // T-511：opts.hunks 阅读足迹定位（memo 内容为摘录时 hunk 行区间按内容行数收敛）
  const openContentViewer = useCallback((title: string, content: string, opts?: { hunks?: DocHunk[] }) => {
    const safe = title.replace(/[^\w一-龥-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'doc';
    const path = `memo:${safe}.md`;
    const maxLine = content.split('\n').length;
    const hunks = opts?.hunks?.map(h => ({
      ...h, start: Math.min(h.start, maxLine), end: Math.min(h.end, maxLine),
    }));
    setActiveSideTab(`file:${path}`);
    setSideCollapsed(false);
    localStorage.setItem('sg_side_collapsed', '0');
    setSideWidth(w => Math.max(w, 460));
    setFileTabs(prev => prev.some(t => t.path === path)
      ? prev.map(t => (t.path === path ? { ...t, content, loading: false, hunks } : t))
      : [...prev, { path, kind: 'file', content, loading: false, hunks }]);
  }, []);

  // T-511：阅读足迹点击——path 可打开 → file: 页签带 hunks 定位（read-file 失败摘录兜底）；
  // path 为空（read_scenario/read_info_pack/sg://）→ memo 页签展示摘录
  const openDocRead = useCallback((item: DocReadItem, hunk?: DocHunk) => {
    const hunks = hunk ? [hunk] : item.hunks;
    if (item.path) {
      openFileViewer(item.path, 'file', { hunks, fallback: item.excerpt });
    } else {
      openContentViewer(item.label || item.ref, item.excerpt, { hunks });
    }
  }, [openFileViewer, openContentViewer]);

  // 会话内 write_draft 内容映射（大段 md 代码块 → 落盘文件匹配，产物卡片去重用）
  const draftContents = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of messages) {
      if (m.role !== 'assistant' || !m.tool_calls) continue;
      for (const tc of m.tool_calls) {
        if (tc.function.name !== 'write_draft') continue;
        try {
          const args = JSON.parse(tc.function.arguments);
          if (args.filename && typeof args.content === 'string') map.set(args.content.trim(), args.filename);
        } catch { /* 参数解析失败忽略 */ }
      }
    }
    return map;
  }, [messages]);

  // 产物预览上下文（产物卡片 / 大段 md 代码块卡片共用）
  const artifactCtxValue = useMemo<ArtifactCtxValue>(() => ({
    onPreviewDraft: (fileName: string) => { openFileViewer(fileName, 'draft'); },
    onPreviewContent: openContentViewer,
    matchDraft: (contentTrim: string) => draftContents.get(contentTrim),
  }), [openFileViewer, openContentViewer, draftContents]);

  // K-012: 恢复会话（会话项点击 / 页面刷新自动恢复共用）
  const restoreSession = useCallback(async (id: string, ws: string) => {
    const r = await agentApi.getSession(id, ws);
    const msgs = r.messages || [];
    setMessages(msgs);
    setSessionId(id);
    setPlanItems([]);
    setStructuredTodos([]);  // H-FE: 清空结构化待办
    setReadingFeed([]);  // T-511：足迹=本轮运行依据，恢复历史会话时清空（不持久化）
    setStreamingText('');
    // 从历史消息中提取 plan
    for (const m of msgs) {
      if (m.role === 'assistant' && m.content) {
        const plan = extractPlan(m.content);
        if (plan) setPlanItems(plan);
      }
    }
    // K-032③：恢复信息包关联——scenarioId 此前只从 URL 参数初始化，
    // 服务重启/刷新后为空 → 引用 chip 在（消息 refs 持久化）但信息包文件看不到。
    // 从消息 refs 中找到最近一个 info_pack 引用恢复关联（getMeta 由 scenarioId effect 触发）
    for (let i = msgs.length - 1; i >= 0; i--) {
      const pack = (msgs[i].references || []).find((ref: any) => ref.type === 'info_pack');
      if (pack) {
        autoSentRef.current = true;  // 恢复语义，不触发场景向导自动发送
        setScenarioId(pack.path);
        break;
      }
    }
  }, []);

  const handleSelectSession = async (id: string, ws: string) => {
    try {
      await restoreSession(id, ws);
      localStorage.setItem('sg_agent_session', id);
    } catch { setError('加载会话失败'); }
  };

  // K-012: 页面刷新/服务重启后自动恢复上次会话（_store 为空时才补拉，SPA 内导航不触发）
  useEffect(() => {
    if (messages.length > 0 || scenarioId || debugRunId) return;
    const savedId = localStorage.getItem('sg_agent_session');
    if (!savedId) return;
    restoreSession(savedId, currentWorkspace)
      .catch(() => localStorage.removeItem('sg_agent_session'));  // 会话已不存在则清键静默降级
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNewSession = async () => {
    setSessionId(''); setSessionTitle(''); setMessages([]); setStats(null); setError(''); setPlanItems([]);
    setStructuredTodos([]);  // H-FE: 清空结构化待办
    setReadingFeed([]);  // T-511：足迹=本轮运行依据，新会话清空
    setStreamingText('');
    // K-032：新会话同步清理信息包关联与文件页签
    setScenarioId(''); setScenarioMeta(null);
    setFileTabs([]); setActiveSideTab('todos');
    localStorage.removeItem('sg_agent_session');
    // T-010: 获取用途列表并决定是否显示选择卡片
    try {
      const r = await agentApi.listPurposes();
      const list = r.purposes || [];
      if (list.length === 1) {
        // 单用途：跳过选择直接锁定
        setPickedPurpose(list[0].id);
        localStorage.setItem('sg_picked_purpose', list[0].id);
        setShowPurposePicker(false);
      } else if (list.length > 1) {
        // 多用途：展示使命卡片
        setPurposes(list);
        setShowPurposePicker(true);
        setPickedPurpose('');
        localStorage.removeItem('sg_picked_purpose');
      }
    } catch {
      setShowPurposePicker(false);
    }
  };

  const handleExportSession = async () => {
    if (!sessionId) return;
    try {
      const data = await agentApi.exportSession(sessionId, currentWorkspace);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `session_${sessionId}.json`; a.click();
      URL.revokeObjectURL(url);
    } catch { setError('导出失败'); }
  };

  // 分组消息
  const grouped = useMemo(() => groupMessages(messages), [messages]);

  // ── 多轮会话导航：置顶最近一条用户消息 + 左侧定位图标列 ──
  const userMsgs = useMemo(() => {
    const out: { groupIdx: number; content: string }[] = [];
    grouped.forEach((g, i) => {
      if (g.type === 'user') out.push({ groupIdx: i, content: stripRefBlock(g.content || '') });
    });
    return out;
  }, [grouped]);

  const lastUserMsg = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') return messages[i];
    }
    return null;
  }, [messages]);
  // 动态置顶：当前视口活跃阶段的用户消息（而非永远取最后一条）
  const pinnedText = useMemo(() => {
    if (activeUserGroupIdx !== null) {
      const g = grouped[activeUserGroupIdx];
      if (g && g.type === 'user') return stripRefBlock(g.content || '');
    }
    return lastUserMsg ? stripRefBlock(lastUserMsg.content || '') : '';
  }, [activeUserGroupIdx, grouped, lastUserMsg]);

  // K-013: 聚合会话中全部 @引用（右侧引用面板，按 type+path 去重）
  const allRefs = useMemo(() => {
    const seen = new Set<string>();
    const out: ChatReference[] = [];
    for (const m of messages) {
      for (const r of (m.references || [])) {
        const k = `${r.type}:${r.path}`;
        if (!seen.has(k)) { seen.add(k); out.push(r); }
      }
    }
    return out;
  }, [messages]);

  // 模型上下文窗口限制（ctx 用量展示在右侧 ContextPanel，K-012 底部栏不再重复）
  const currentModel = models.find(m => m.id === currentModelId);
  const ctxLimit = parseInt(currentModel?.max_context_tokens || '') || DEFAULT_CTX_LIMIT;

  // 图标列固定位置：以容器中线对称展开（15%~85% 均匀分布），不随滚动变化
  const railPos = useMemo(() => {
    const n = userMsgs.length;
    if (n === 0) return [] as { idx: number; pct: number }[];
    return userMsgs.map((u, i) => ({
      idx: u.groupIdx,
      pct: n === 1 ? 50 : 15 + (i / (n - 1)) * 70,
    }));
  }, [userMsgs]);

  // 滚动时仅更新活跃阶段与可见状态（图标位置固定不变）
  const computeRailState = useCallback(() => {
    const box = msgBoxRef.current;
    if (!box || userMsgs.length === 0) { setActiveUserGroupIdx(null); setInViewSet(new Set()); return; }
    const boxTop = box.getBoundingClientRect().top;
    let active: number | null = null;
    const inView = new Set<number>();
    if (box.scrollHeight <= box.clientHeight) {
      active = userMsgs.length > 0 ? userMsgs[userMsgs.length - 1].groupIdx : null;
      userMsgs.forEach(u => inView.add(u.groupIdx));
    } else {
      for (const u of userMsgs) {
        const el = box.querySelector<HTMLElement>(`[data-user-idx="${u.groupIdx}"]`);
        if (!el) continue;
        const relTop = el.getBoundingClientRect().top - boxTop + box.scrollTop;
        if (relTop <= box.scrollTop + 40) active = u.groupIdx;
        if (relTop >= box.scrollTop - 4 && relTop <= box.scrollTop + box.clientHeight + 4) inView.add(u.groupIdx);
      }
    }
    setActiveUserGroupIdx(active);
    setInViewSet(inView);
  }, [userMsgs]);

  // 滚动/resize 时更新活跃阶段与可见状态（rAF 节流；图标位置固定不变）
  useEffect(() => {
    const box = msgBoxRef.current;
    if (!box) return;
    let raf = 0;
    const onResizeScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; computeRailState(); });
    };
    box.addEventListener('scroll', onResizeScroll, { passive: true });
    window.addEventListener('resize', onResizeScroll);
    computeRailState();
    return () => {
      box.removeEventListener('scroll', onResizeScroll);
      window.removeEventListener('resize', onResizeScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [computeRailState]);

  // 点击图标 → 滚动定位 + 1.5s 高亮闪烁后淡出
  const handleJumpToUser = (groupIdx: number) => {
    const box = msgBoxRef.current;
    const el = box?.querySelector<HTMLElement>(`[data-user-idx="${groupIdx}"]`);
    if (!box || !el) return;
    const relTop = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    box.scrollTo({ top: Math.max(relTop - 8, 0), behavior: 'smooth' });
    setHighlightIdx(groupIdx);
    if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = window.setTimeout(() => setHighlightIdx(null), 1500);
  };

  // 组件卸载清理高亮定时器
  useEffect(() => () => {
    if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current);
  }, []);

  // 置顶栏自动恢复：活跃阶段切换时重新展开；会话清空/切换时重置高亮
  useEffect(() => {
    const cur = pinnedText;
    if (cur && cur !== lastPinnedRef.current) {
      lastPinnedRef.current = cur;
      setPinnedDismissed(false);
    }
    if (!cur && lastPinnedRef.current) {
      lastPinnedRef.current = '';
      setPinnedDismissed(false);
    }
    setHighlightIdx(null);
  }, [activeUserGroupIdx, pinnedText]);

  // 渲染分组消息
  const renderGrouped = (item: GroupedItem, idx: number) => {
    if (item.type === 'user') {
      return (
        <div key={idx} data-user-idx={idx}
          className={`${idx > 0 ? 'mt-4' : ''} mb-2 flex justify-end transition-all duration-500 ${highlightIdx === idx ? 'ring-1 ring-info bg-info/10 rounded-lg' : ''}`}>
          <div className="max-w-[80%] rounded-lg rounded-br-sm px-3 py-1.5 text-sm bg-info/10 text-info/90 border border-info/20">
            {item.references && item.references.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-1">
                {item.references.map((r, i) => (
                  <span key={i} className="text-[9px] px-1 py-0.5 rounded bg-info/15 border border-info/30 font-mono text-info/80">
                    {r.type === 'info_pack' ? '📦' : r.type === 'draft' ? '📝' : '📄'} {r.label || r.path}
                  </span>
                ))}
              </div>
            )}
            {stripRefBlock(item.content || '')}
            <CopyButton text={stripRefBlock(item.content || '')} className="text-[10px] text-info/40 hover:text-info mt-0.5" />
          </div>
        </div>
      );
    }
    if (item.type === 'assistant-text') {
      // K-024：思考文本（工具调用前的意图说明）用轻量样式——常驻可见但视觉上轻于正式回复
      if (item.thought) {
        return (
          <div key={idx} className="mb-2 px-2 py-1 border-l-2 border-info/30 text-xs text-gray-400 italic">
            <MarkdownText content={item.content || ''} />
          </div>
        );
      }
      return (
        <div key={idx} className="mb-3 ml-1 border-l-2 border-border/50 pl-3 py-0.5">
          <MarkdownText content={item.content || ''} />
        </div>
      );
    }
    // artifact: 会话产物卡片（write_draft 落盘文件，点击右侧页签预览）
    if (item.type === 'artifact' && item.artifacts) {
      return (
        <div key={idx} className="mb-3 ml-1 space-y-1.5">
          {item.artifacts.map((a, ai) => <ArtifactCard key={ai} artifact={a} />)}
        </div>
      );
    }
    // step-complete: 步骤完成提示
    if (item.type === 'step-complete') {
      return (
        <div key={idx} className="mb-3 flex items-center gap-2 px-2 py-1 bg-green-900/10 border border-green-700/20 rounded text-xs">
          <span className="text-green-500">✅</span>
          <span className="text-green-400/80">完成：{item.content}</span>
        </div>
      );
    }
    // tool-group: 按步骤分组的工具调用
    if (item.type === 'tool-group' && item.tools) {
      return (
        <ToolGroupBlock key={idx} tools={item.tools} stepLabel={item.stepLabel} />
    );
    }
    return null;
  };

  return (
    <div className="flex h-full">
      {/* 左侧：会话树（K-037：可收起为细条；K-039：面板最大化时整列隐藏） */}
      {!sideMax && (
        <SessionTree
          sessions={sessions}
          currentSessionId={sessionId}
          currentWorkspace={currentWorkspace}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          collapsed={sessCollapsed}
          onToggleCollapse={toggleSessCollapsed}
        />
      )}

      {/* 中间+右侧 */}
      <div className="flex-1 flex min-w-0">
        {/* 对话区（K-039：面板最大化时 display:none 隐藏——不卸载，WS/滚动/输入状态全保留） */}
        <div className={`flex-1 flex flex-col min-w-0 ${sideMax ? 'hidden' : ''}`}>
          {/* 顶部信息栏 */}
          <div className="flex-shrink-0 px-4 py-1.5 border-b border-border flex items-center gap-3 text-[10px] text-gray-500">
            {/* K-037：会话列表切换（细条收起时的另一入口） */}
            <button onClick={toggleSessCollapsed} title={sessCollapsed ? '展开会话列表' : '收起会话列表'}
              className="text-gray-500 hover:text-info transition-colors px-1 rounded hover:bg-surface-3">
              {sessCollapsed ? '»' : '«'} 会话
            </button>
            <span className={wsState === 'open' ? 'text-green-500' : 'text-red-400'}>
              {wsState === 'open' ? '●' : '○'}
            </span>
            {pickedPurpose && (pickedPurpose === 'requirement_interview' || pickedPurpose === '需求面试') && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/30 text-purple-300">需求面试</span>
            )}
            {pickedPurpose && pickedPurpose === 'test_workbench' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-info/15 text-info">测试工作台</span>
            )}
            {sessionTitle && <span className="text-gray-300 font-medium">{sessionTitle}</span>}
            {sessionId && (
              <>
              <span className="font-mono text-gray-600">{sessionId}</span>
              <button onClick={handleExportSession} className="text-gray-500 hover:text-info transition-colors" title="导出会话 JSON">
                📥 导出
              </button>
              </>
            )}
            {stats && (
              <>
                <span>·</span>
                <span className={stats.is_mock ? 'text-yellow-500' : 'text-green-500'}>
                  {stats.is_mock ? 'MOCK' : 'LIVE'} ({stats.model})
                </span>
              </>
            )}
            <div className="ml-auto">{turnInfo}</div>
            {/* K-039：专注模式（一键收起两侧，会话区占满；再点恢复原布局） */}
            <button onClick={toggleFocusMode} title={focusMode ? '退出专注，恢复两侧面板' : '专注模式：收起两侧，会话区占满'}
              className={`transition-colors px-1 rounded hover:bg-surface-3 ${focusMode ? 'text-info' : 'text-gray-500 hover:text-info'}`}>
              {focusMode ? '⤡ 退出专注' : '⤢ 专注'}
            </button>
            {/* K-037：右侧面板切换 */}
            <button onClick={toggleSideCollapsed} title={sideCollapsed ? '展开面板（待办/信息包/文件）' : '收起面板'}
              className="text-gray-500 hover:text-info transition-colors px-1 rounded hover:bg-surface-3">
              面板 {sideCollapsed ? '«' : '»'}
            </button>
          </div>

          {/* 多轮会话导航：最近一条用户消息置顶（可收起，新消息到达自动恢复） */}
          {pinnedText && !pinnedDismissed && (
            <div className="flex-shrink-0 mx-4 mt-2 px-3 py-1.5 rounded-lg bg-pinnedBg/15 border border-pinnedBg/40 flex items-center gap-2 text-xs">
              <span className="text-pinnedBg flex-shrink-0">📌</span>
              <span className="flex-1 truncate text-gray-300" title={pinnedText}>{pinnedText}</span>
              <CopyButton text={pinnedText} className="text-gray-500 hover:text-info flex-shrink-0" />
              <button onClick={() => setPinnedDismissed(true)} title="收起置顶"
                className="text-gray-500 hover:text-info flex-shrink-0 px-1 rounded hover:bg-surface-3">✕</button>
            </div>
          )}

          {/* 消息列表 + 导航图标列（flex 行：rail 独立于滚动容器） */}
          <div className="flex flex-1 min-h-0">
            <ConversationRail
              userMsgs={userMsgs}
              railPos={railPos}
              activeUserGroupIdx={activeUserGroupIdx}
              inViewSet={inViewSet}
              hoverUserIdx={hoverUserIdx}
              onHover={setHoverUserIdx}
              onJump={handleJumpToUser}
            />
            <div ref={msgBoxRef} className="flex-1 overflow-y-auto px-4 py-3">
              <ArtifactCtx.Provider value={artifactCtxValue}>
              {grouped.length === 0 && !loading && (
                showPurposePicker && purposes.length > 0 ? (
                  <PurposeCards purposes={purposes} onPick={(id) => {
                    setPickedPurpose(id);
                    localStorage.setItem('sg_picked_purpose', id);
                    setShowPurposePicker(false);
                  }} />
                ) : (
                  <div className="text-center text-gray-600 text-sm py-12">
                    输入消息开始对话，或输入 / 查看可用命令
                  </div>
                )
              )}
              {grouped.map(renderGrouped)}
              {/* K-012: 流式生成中气泡（整块 assistant 到达时被正式消息替换） */}
              {streamingText && (
                <div className="mb-3 ml-1 border-l-2 border-border/50 pl-3 py-0.5">
                  <MarkdownText content={streamingText} />
                  <span className="inline-block w-2 h-3.5 bg-info/70 animate-pulse rounded-sm" />
                </div>
              )}
              {error && (
                <div className="bg-red-900/20 border border-red-700/30 rounded p-2 mb-2">
                  <span className="text-red-400 text-sm">❌ {error}</span>
                </div>
              )}
              </ArtifactCtx.Provider>
              <div ref={messagesEndRef} />
            </div>
          </div>

          <ChatInput
            wsState={wsState}
            loading={loading}
            models={models}
            currentModelId={currentModelId}
            onSend={handleSend}
            onStop={handleStop}
            onNewSession={handleNewSession}
            onClearMessages={() => { setMessages([]); setStats(null); setPlanItems([]); }}
            onExportSession={handleExportSession}
            onModelChange={setCurrentModelId}
          />
        </div>

        {/* K-037：右侧面板（可收起为细条；收起时拖拽柄隐藏） */}
        {sideCollapsed ? (
          <div className="w-9 flex-shrink-0 border-l border-border bg-surface-2/50 flex flex-col items-center py-2 gap-1.5">
            <button onClick={toggleSideCollapsed} title="展开面板"
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs">
              «
            </button>
            <button onClick={() => expandSideTo('todos')} title="待办"
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs">
              📋
            </button>
            <button onClick={() => expandSideTo('reading')} title={`阅读足迹（${readingFeed.length}）`}
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs relative">
              📖
              {readingFeed.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 text-[8px] text-info">{readingFeed.length}</span>
              )}
            </button>
            {scenarioMeta && (
              <button onClick={() => expandSideTo('pack')} title={`信息包（${scenarioMeta.info_pack.length}）`}
                className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs">
                📦
              </button>
            )}
            {fileTabs.length > 0 && (
              <button onClick={() => expandSideTo(activeSideTab.startsWith('file:') ? activeSideTab : `file:${fileTabs[fileTabs.length - 1].path}`)}
                title={`文件页签（${fileTabs.length}）`}
                className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs relative">
                📄
                <span className="absolute -top-0.5 -right-0.5 text-[8px] text-info">{fileTabs.length}</span>
              </button>
            )}
          </div>
        ) : (
          <>
            {/* K-033：右侧拖拽柄（左缘拖动调宽面板；K-039：最大化时隐藏） */}
            {!sideMax && (
              <div
                onMouseDown={startSideDrag}
                className="w-1 flex-shrink-0 cursor-col-resize hover:bg-info/40 active:bg-info/60 transition-colors"
                title="拖拽调整面板宽度"
              />
            )}

            {/* 右侧：K-032 页签面板（待办/信息包/文件页签） */}
            <SidePanel ctxUsage={ctxUsage} planItems={planItems} structuredTodos={structuredTodos} loading={loading} messages={messages} ctxLimit={ctxLimit} stats={stats} scenarioMeta={scenarioMeta} onUpdateMeta={setScenarioMeta} onError={setError} references={allRefs} onViewFile={openFileViewer} fileTabs={fileTabs} activeTab={activeSideTab} onSelectTab={setActiveSideTab} onCloseTab={closeFileTab} width={sideMax ? '100%' : sideWidth} onCollapse={() => { setSideMax(false); toggleSideCollapsed(); }} maximized={sideMax} onToggleMaximize={toggleSideMax} draftFiles={sessionDrafts} readingFeed={readingFeed} onOpenDocRead={openDocRead} />
          </>
        )}
      </div>
    </div>
  );
}
