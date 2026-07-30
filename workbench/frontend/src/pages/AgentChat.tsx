/** AgentChat — 左侧会话树 + 中间对话区 + 右侧待办面板 + 底部选择器 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { session, agentApi, scenarioApi, modelApi } from '../api';
import type { AgentMode, AgentSkill, ScenarioMeta, ModelConfig } from '../api';
import SessionTree from '../components/SessionTree';
import ModeBadge from '../components/ModeBadge';
import TodoPanel from '../components/TodoPanel';
import type { StructuredTodo } from '../components/TodoPanel';

const MODE_LABELS: Record<string, string> = {
  generate: '✨生成', debug: '🐛调试', analyze: '🔍分析', chat: '💬对话', audit: '🔎审计',
};

interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
  reasoning_content?: string;
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
}

const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: '/generate-scenario', label: '场景生成技能', desc: '使用场景生成技能分析需求', type: 'skill' },
  { cmd: '/validate-conformance', label: '合规校验技能', desc: '校验场景 YAML 格式合规性', type: 'skill' },
  { cmd: '/debug-failure', label: '失败分析技能', desc: '分析运行报告中的失败场景', type: 'skill' },
  { cmd: '/mode:generate', label: '切换到生成模式', desc: '场景生成模式（10 工具）', type: 'mode' },
  { cmd: '/mode:debug', label: '切换到调试模式', desc: '场景调试模式（8 工具）', type: 'mode' },
  { cmd: '/mode:analyze', label: '切换到分析模式', desc: '只读分析模式（6 工具）', type: 'mode' },
  { cmd: '/mode:chat', label: '切换到对话模式', desc: '自由对话模式（0 工具）', type: 'mode' },
  { cmd: '/mode:audit', label: '切换到审计模式', desc: 'Spec 审计模式（7 工具）', type: 'mode' },
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
  assistantText?: string;
}
interface ModeSwitchEvent {
  id: number;
  from: string;
  to: string;
  reason: string;
  source: string;
  auto: boolean;
  msgIndex: number;  // messages.length at the time of switch
}

interface GroupedItem {
  type: 'user' | 'assistant-text' | 'tool-group' | 'step-complete' | 'mode-switch';
  content?: string;
  tools?: ToolItem[];
  stepLabel?: string;   // 关联的待办步骤名称
  stepIdx?: number;    // 步骤索引
  modeSwitch?: ModeSwitchEvent;  // 模式切换事件
}

// ── 简易 Markdown 渲染 ──
function MarkdownText({ content }: { content: string }) {
  // 分割代码块
  const parts = content.split(/(```[\s\S]*?```)/g);
  return (
    <div className="text-sm text-gray-200">
      {parts.map((part, i) => {
        if (part.startsWith('```')) {
          const lines = part.replace(/^```\w*\n?/, '').replace(/```$/, '').split('\n');
          return <pre key={i} className="text-[11px] bg-black/30 rounded p-2 overflow-x-auto max-h-80 my-1 text-gray-400">{lines.join('\n')}</pre>;
        }
        // 渲染行级 markdown
        const lines = part.split('\n');
        const elements: JSX.Element[] = [];
          let inTable = false;
          let tableRows: string[][] = [];
          let listItems: string[] = [];

          const flushTable = () => {
            if (tableRows.length > 0) {
              elements.push(
                <table key={`t${elements.length}`} className="w-full text-[11px] my-1 border-collapse">
                  <thead>
                    <tr>{tableRows[0].map((h, hi) => <th key={hi} className="border border-border px-1.5 py-0.5 text-left text-gray-300">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {tableRows.slice(2).map((row, ri) => (
                      <tr key={ri}>{row.map((c, ci) => <td key={ci} className="border border-border px-1.5 py-0.5 text-gray-400">{c}</td>)} </tr>
                    ))}
                  </tbody>
                </table>
              );
              tableRows = [];
            }
          };
          const flushList = () => {
            if (listItems.length > 0) {
              elements.push(
                <ul key={`l${elements.length}`} className="list-disc pl-4 my-0.5">
                  {listItems.map((li, li2) => <li key={li2} className="text-gray-300">{renderInlineMd(li)}</li>)}
                </ul>
              );
              listItems = [];
            }
          };

          for (const line of lines) {
            const trimmed = line.trim();
            // 表格行
            if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
              flushList();
              inTable = true;
              tableRows.push(trimmed.split('|').slice(1, -1).map(c => c.trim()));
              continue;
            } else if (inTable) {
              flushTable();
              inTable = false;
            }
            // 分隔线
            if (/^---+$/.test(trimmed)) { flushList(); elements.push(<hr key={`h${elements.length}`} className="border-border my-1" />); continue; }
            // 标题
            const h2 = trimmed.match(/^##\s+(.*)/); if (h2) { flushList(); elements.push(<h3 key={`h${elements.length}`} className="text-sm font-semibold text-gray-200 mt-1.5 mb-0.5">{renderInlineMd(h2[1])}</h3>); continue; }
            const h3 = trimmed.match(/^###\s+(.*)/); if (h3) { flushList(); elements.push(<h4 key={`h${elements.length}`} className="text-xs font-semibold text-gray-300 mt-1 mb-0.5">{renderInlineMd(h3[1])}</h4>); continue; }
            // 列表项
            const li = trimmed.match(/^[-*]\s+(.*)/); if (li) { listItems.push(li[1]); continue; }
            const ol = trimmed.match(/^\d+\.\s+(.*)/); if (ol) { listItems.push(ol[1]); continue; }
            // 空行
            if (!trimmed) { flushList(); continue; }
            // 普通段落
            flushList();
            elements.push(<p key={`p${elements.length}`} className="text-gray-200 leading-relaxed">{renderInlineMd(trimmed)}</p>);
          }
          flushTable();
          flushList();
        return <div key={i}>{elements}</div>;
      })}
    </div>
  );
}

// 渲染行内 Markdown（粗体、代码、链接）
function renderInlineMd(text: string): JSX.Element {
  const parts: JSX.Element[] = [];
  let remaining = text;
  let key = 0;
  while (remaining) {
    // 粗体 **text**
    const bold = remaining.match(/^(.*?)\*\*(.+?)\*\*/s);
    if (bold) {
      if (bold[1]) parts.push(<span key={key++}>{bold[1]}</span>);
      parts.push(<strong key={key++} className="font-semibold text-gray-100">{bold[2]}</strong>);
      remaining = remaining.slice(bold[0].length);
      continue;
    }
    // 行内代码 `code`
    const code = remaining.match(/^(.*?)`(.+?)`/s);
    if (code) {
      if (code[1]) parts.push(<span key={key++}>{code[1]}</span>);
      parts.push(<code key={key++} className="text-[11px] text-yellow-400/80 bg-black/30 rounded px-0.5">{code[2]}</code>);
      remaining = remaining.slice(code[0].length);
      continue;
    }
    parts.push(<span key={key++}>{remaining}</span>);
    break;
  }
  return <>{parts}</>;
}

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

// ── 默认计划（按模式推断） + 工具→步骤映射 ──
const DEFAULT_PLANS: Record<string, string[]> = {
  generate: [
    '读取基础信息包和需求文档',
    '查询注册表（tool / oracle）',
    '参考已有场景结构',
    '获取场景 ID',
    '生成场景 YAML',
    '校验场景',
    '写入草稿',
  ],
  debug: [
    '读取运行报告',
    '分析失败场景',
    '读取场景和需求',
    '查询 DB 证据',
    '定位根因并给出修复建议',
  ],
  analyze: [
    '读取需求和场景',
    '分析覆盖完整性',
    '输出分析报告',
  ],
  chat: [],
};

// 工具名 → 待办步骤序号映射（供 groupMessages 把工具调用归到对应步骤展示）
const TOOL_TO_STEP: Record<string, number> = {
  read_info_pack: 0, read_spec: 0, list_spec_files: 0,
  query_registry: 1,
  list_scenarios: 2, read_scenario: 2,
  next_scenario_id: 3,
  validate: 5,
  write_draft: 6,
  add_to_info_pack: 0,
  undo_draft: 6,
  read_run_report: 0,
  db_evidence: 3,
};

// ── 将扁平消息列表分组（按待办步骤关联 + 完成提示） ──
function groupMessages(messages: ChatMessage[]): GroupedItem[] {
  const groups: GroupedItem[] = [];
  let currentToolGroup: GroupedItem | null = null;
  let lastStepIdx = -1;  // 上一个工具组对应的步骤索引

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
      currentToolGroup = null;
    }
  };

  for (const msg of messages) {
    if (msg.role === 'system') continue;

    if (msg.role === 'user') {
      flushToolGroup();
      groups.push({ type: 'user', content: msg.content });
    } else if (msg.role === 'assistant') {
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        // 根据第一个工具名推断步骤
        const firstName = msg.tool_calls[0].function.name;
        const stepIdx = TOOL_TO_STEP[firstName];
        const stepLabel = stepIdx !== undefined ? DEFAULT_PLANS.generate?.[stepIdx] : undefined;
        // 如果步骤变化了，先 flush 上一组
        if (currentToolGroup && stepIdx !== undefined && currentToolGroup.stepIdx !== undefined && stepIdx !== currentToolGroup.stepIdx) {
          flushToolGroup();
        }
        if (!currentToolGroup) currentToolGroup = { type: 'tool-group', tools: [], stepIdx, stepLabel };
        // 如果新组的 stepIdx 更高，更新（可能同一步骤多次调用）
        if (stepIdx !== undefined && (currentToolGroup.stepIdx === undefined || stepIdx > currentToolGroup.stepIdx)) {
          currentToolGroup.stepIdx = stepIdx;
          currentToolGroup.stepLabel = DEFAULT_PLANS.generate?.[stepIdx];
        }
        const cleanContent = msg.content ? stripPlan(msg.content) : '';
        for (let i = 0; i < msg.tool_calls.length; i++) {
          currentToolGroup.tools!.push({
            name: msg.tool_calls[i].function.name,
            args: msg.tool_calls[i].function.arguments,
            assistantText: i === 0 && cleanContent ? cleanContent : undefined,
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

// ── 单个工具调用块（可折叠） ──
function ToolCallBlock({ tool }: { tool: ToolItem }) {
  const [expanded, setExpanded] = useState(false);
  const hasResult = tool.result !== undefined;
  const resultPreview = hasResult ? tool.result!.substring(0, 100) : '';
  const isError = hasResult && (tool.result!.includes('"error"') || tool.result!.includes('ERROR') || tool.result!.includes('❌'));

  return (
    <div className="border border-border rounded text-xs">
      {/* 工具头部 - 始终可见 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2 py-1 hover:bg-surface-3 transition-colors text-left"
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
      </button>
      {/* 展开内容 */}
      {expanded && (
        <div className="px-2 pb-2 space-y-1">
          {tool.assistantText && (
            <div className="text-gray-300 text-xs mb-1">{tool.assistantText}</div>
          )}
          <div>
            <div className="text-gray-600 text-[10px] mb-0.5">参数</div>
            <pre className="text-gray-500 text-[11px] bg-black/30 rounded p-1.5 overflow-x-auto max-h-40">{tool.args}</pre>
          </div>
          {hasResult && (
            <div>
              <div className="text-gray-600 text-[10px] mb-0.5">结果</div>
              <pre className={`text-[11px] bg-black/30 rounded p-1.5 overflow-x-auto max-h-60 ${isError ? 'text-red-400' : 'text-gray-400'}`}>{tool.result}</pre>
            </div>
          )}
        </div>
      )}
      {/* 折叠时的简要结果预览 */}
      {!expanded && hasResult && resultPreview && (
        <div className="px-2 pb-1 text-gray-600 text-[10px] truncate">{resultPreview}</div>
      )}
    </div>
  );
}

// ── 工具组块（按待办步骤分组，整体可折叠） ──
function ToolGroupBlock({ tools, stepLabel }: { tools: ToolItem[]; stepLabel?: string }) {
  const [groupExpanded, setGroupExpanded] = useState(false);
  const allDone = tools.every(t => t.result !== undefined);
  const hasError = tools.some(t => t.result && (t.result.includes('"error"') || t.result.includes('ERROR') || t.result.includes('❌')));
  const successCount = tools.filter(t => t.result && !(t.result.includes('"error"') || t.result.includes('ERROR') || t.result.includes('❌'))).length;

  return (
    <div className="mb-2">
      {/* 步骤标题栏（可折叠整个组） */}
      <button
        onClick={() => setGroupExpanded(!groupExpanded)}
        className="w-full flex items-center gap-2 px-2 py-1 text-xs text-gray-500 hover:text-gray-300 transition-colors text-left"
      >
        <span className="text-[10px]">{groupExpanded ? '▼' : '▶'}</span>
        {stepLabel && <span className="text-gray-400">{stepLabel}</span>}
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
      {/* 展开时显示各工具调用 */}
      {groupExpanded && (
        <div className="space-y-1 ml-2">
          {tools[0]?.assistantText && (
            <div className="text-xs text-gray-400 px-1 py-0.5">{tools[0].assistantText}</div>
          )}
          {tools.map((tool, ti) => (
            <ToolCallBlock key={ti} tool={tool} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 上下文用量面板组件 ──
function ContextPanel({ ctxUsage, messages, ctxLimit }: { ctxUsage: CtxUsage; messages: ChatMessage[]; ctxLimit: number }) {
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

// ── 右侧面板组件（上下文 + 待办） ──
function SidePanel({ ctxUsage, planItems, structuredTodos, loading, currentMode, messages, ctxLimit }: {
  ctxUsage: CtxUsage | null;
  planItems: string[];
  structuredTodos: StructuredTodo[];
  loading: boolean;
  currentMode: string;
  messages: ChatMessage[];
  ctxLimit: number;
}) {
  if (!ctxUsage && planItems.length === 0 && structuredTodos.length === 0) return null;
  return (
    <div className="w-56 flex-shrink-0 border-l border-border bg-surface-2/50 flex flex-col">
      {ctxUsage && <ContextPanel ctxUsage={ctxUsage} messages={messages} ctxLimit={ctxLimit} />}
      {(planItems.length > 0 || structuredTodos.length > 0) && (
        <TodoPanel todos={structuredTodos} planItems={planItems} loading={loading} currentMode={currentMode} />
      )}
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
};

export default function AgentChat() {
  const [searchParams] = useSearchParams();
  const scenarioId = searchParams.get('scenario_id') || '';
  const initialMode = searchParams.get('mode') || 'generate';
  // H-5#3: 通知链接带 context 打开（debug_run_id 触发 debug 路由）
  const debugRunId = searchParams.get('debug_run_id') || '';

  // 从模块存储恢复状态（跨导航保持会话）
  const [messages, setMessages] = useState<ChatMessage[]>(_store.messages);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(_store.loading);
  const [sessionId, setSessionId] = useState(_store.sessionId);
  const [sessionTitle, setSessionTitle] = useState(_store.sessionTitle);
  const [stats, setStats] = useState<AgentStats | null>(_store.stats);
  const [turnInfo, setTurnInfo] = useState(_store.turnInfo);
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>(_store.wsState);
  const [error, setError] = useState(_store.error);
  const [planItems, setPlanItems] = useState<string[]>(_store.planItems);
  const [ctxUsage, setCtxUsage] = useState<CtxUsage | null>(_store.ctxUsage);

  const [sessions, setSessions] = useState<any[]>([]);
  const [sessionsVersion, setSessionsVersion] = useState(0);
  const [modes, setModes] = useState<AgentMode[]>([]);
  const [currentMode, setCurrentMode] = useState(initialMode);
  const [skills, setSkills] = useState<AgentSkill[]>([]);
  const [showSkills, setShowSkills] = useState(false);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [currentModelId, setCurrentModelId] = useState('');
  const [scenarioMeta, setScenarioMeta] = useState<ScenarioMeta | null>(null);
  const [showInfoPack, setShowInfoPack] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  const [slashQuery, setSlashQuery] = useState('');
  const [wsReconnect, setWsReconnect] = useState(0);
  // H-2: 模式锁定与切换事件
  const [lockedMode, setLockedMode] = useState('');  // 非空 = 锁定的模式名
  const [modeSwitches, setModeSwitches] = useState<ModeSwitchEvent[]>([]);
  const modeSwitchIdRef = useRef(0);
  // H-FE: 结构化待办（来自 todo_update 事件）
  const [structuredTodos, setStructuredTodos] = useState<StructuredTodo[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const autoSentRef = useRef(false);
  const debugSentRef = useRef(false);  // H-5#3: 调试链接自动发送
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const currentWorkspace = session.getWorkspace();

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

  const filteredCommands = useMemo(() => {
    if (!slashQuery) return SLASH_COMMANDS;
    return SLASH_COMMANDS.filter(c => c.cmd.includes(slashQuery) || c.label.includes(slashQuery));
  }, [slashQuery]);

  const loadSessions = useCallback(async () => {
    try {
      const r = await agentApi.listSessions('');
      setSessions(r.sessions || []);
    } catch { setSessions([]); }
  }, []);

  useEffect(() => {
    agentApi.getModes().then(r => setModes(r.modes || [])).catch(() => {});
    agentApi.getSkills().then(r => setSkills(r.skills || [])).catch(() => {});
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
  }, [messages, turnInfo]);

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

  // WebSocket（跨导航保持，不随组件卸载关闭）
  // 使用 ref 存储最新的事件处理函数，避免闭包过期
  const wsHandlerRef = useRef<(event: any) => void>(() => {});
  wsHandlerRef.current = (event: any) => {
    switch (event.type) {
      case 'state':
        if (event.status === 'started' && event.session_id) {
          setSessionId(event.session_id);
          setSessionsVersion(v => v + 1);
        } else if (event.fused) {
          setTurnInfo(`⚠️ 熔断 ${event.max_turns}`);
        } else if (typeof event.turn === 'number') {
          setTurnInfo(`${event.turn + 1}/${event.max_turns}`);
        }
        break;
      case 'assistant':
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
      case 'tool_call':
        setMessages(prev => [...prev, { role: 'tool', content: String(event.result ?? '') }]);
        break;
      case 'done':
        setStats(event.stats || null);
        if (event.session_id) setSessionId(event.session_id);
        if (event.title) setSessionTitle(event.title);
        setTurnInfo('');
        setLoading(false);
        setSessionsVersion(v => v + 1);
        break;
      case 'mode_switch':
        // H-2: 处理模式自动切换事件
        if (!lockedMode) {
          setCurrentMode(event.to || 'chat');
        }
        setModeSwitches(prev => [...prev, {
          id: ++modeSwitchIdRef.current,
          from: event.from || '',
          to: event.to || '',
          reason: event.reason || '',
          source: event.source || '',
          auto: event.auto !== false,
          msgIndex: messages.length,
        }]);
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
      case 'error':
        setError(event.message || 'Agent 异常');
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
      ws.onopen = () => { _store.wsState = 'open'; if (_store.mounted) setWsState('open'); };
      ws.onclose = () => { _store.wsState = 'closed'; if (_store.mounted) setWsState('closed'); };
      ws.onerror = () => { _store.wsState = 'closed'; if (_store.mounted) setWsState('closed'); };
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
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
        setLoading(true); setError(''); setPlanItems(DEFAULT_PLANS[currentMode] || []); setCtxUsage(null);
        setMessages(prev => [...prev, { role: 'user', content: msg }]);
        ws.send(JSON.stringify({
          message: msg, session_id: '', max_turns: 50,
          workspace: currentWorkspace, mode: currentMode, scenario_id: scenarioId,
          model_id: currentModelId,
          context: { current_page: currentPage, editing_scenario_id: scenarioId, locked_mode: lockedMode },
        }));
      }
    }
  }, [scenarioId, wsState, scenarioMeta, currentWorkspace, currentMode, currentModelId, currentPage, lockedMode]);

  // H-5#3: 通知链接自动打开调试（debug_run_id 触发）
  useEffect(() => {
    if (debugRunId && wsState === 'open' && !debugSentRef.current) {
      debugSentRef.current = true;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        // 设置 debug 模式 + 路由上下文（last_run_failed=true 触发 H-2 路由器自动 debug）
        setCurrentMode('debug');
        setLockedMode('');  // 不锁定，允许路由器自动路由
        const msg = `定时任务运行失败，请分析运行 ${debugRunId} 的失败原因。使用 read_run_report 工具读取运行报告，定位失败场景和错误根因，给出修复建议。`;
        setLoading(true); setError(''); setPlanItems(DEFAULT_PLANS['debug'] || []); setCtxUsage(null);
        setMessages(prev => [...prev, { role: 'user', content: msg }]);
        ws.send(JSON.stringify({
          message: msg, session_id: '', max_turns: 50,
          workspace: currentWorkspace, mode: 'debug', scenario_id: '',
          model_id: currentModelId,
          context: {
            current_page: 'execution',
            last_run_failed: true,
            editing_scenario_id: '',
            locked_mode: '',
          },
        }));
      }
    }
  }, [debugRunId, wsState, currentWorkspace, currentModelId]);

  // 发送消息
  const handleSend = useCallback(() => {
    const userMsg = input.trim();
    const ws = wsRef.current;
    if (!userMsg || loading || !ws || ws.readyState !== WebSocket.OPEN) return;
    setInput(''); setSlashOpen(false);
    setLoading(true); setError(''); setTurnInfo(''); setPlanItems(DEFAULT_PLANS[currentMode] || []); setCtxUsage(null);
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    ws.send(JSON.stringify({
      message: userMsg, session_id: sessionId, max_turns: 50,
      workspace: currentWorkspace, mode: currentMode, scenario_id: scenarioId,
      model_id: currentModelId,
      context: { current_page: currentPage, editing_scenario_id: scenarioId, locked_mode: lockedMode },
    }));
  }, [input, loading, sessionId, currentWorkspace, currentMode, scenarioId, currentModelId, currentPage, lockedMode]);

  // 打断会话
  const handleStop = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    setLoading(false);
    setTurnInfo('');
    setError('');
    setWsReconnect(v => v + 1);
  }, []);

  // 斜杠命令处理
  const handleSlashSelect = (cmd: SlashCommand) => {
    setSlashOpen(false); setInput('');
    if (cmd.type === 'mode') {
      const newMode = cmd.cmd.replace('/mode:', '');
      setCurrentMode(newMode);
      setLockedMode(newMode);  // 斜杠命令切换也锁定
    } else if (cmd.type === 'action') {
      if (cmd.cmd === '/new') {
        setSessionId(''); setSessionTitle(''); setMessages([]); setStats(null); setPlanItems([]);
      } else if (cmd.cmd === '/clear') {
        setMessages([]); setStats(null); setPlanItems([]);
      } else if (cmd.cmd === '/undo') {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          const msg = '请使用 undo_draft 工具撤销最后一次草稿写入。如果不知道文件名，请先查看 drafts 目录。';
          setLoading(true); setError('');
          setMessages(prev => [...prev, { role: 'user', content: msg }]);
          ws.send(JSON.stringify({
            message: msg, session_id: sessionId, max_turns: 3,
            workspace: currentWorkspace, mode: currentMode, scenario_id: scenarioId,
            model_id: currentModelId,
            context: { current_page: currentPage, editing_scenario_id: scenarioId, locked_mode: lockedMode },
          }));
        }
      } else if (cmd.cmd === '/export') {
        handleExportSession();
      }
    } else if (cmd.type === 'skill') {
      const skillName = cmd.cmd.replace('/', '');
      setInput(`请使用 ${skillName} 技能：`);
      inputRef.current?.focus();
    }
  };

  const handleInputChange = (value: string) => {
    setInput(value);
    if (value.startsWith('/') && !value.includes(' ')) {
      setSlashOpen(true); setSlashQuery(value); setSlashIndex(0);
    } else {
      setSlashOpen(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (slashOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIndex(i => Math.min(i + 1, filteredCommands.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSlashIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (filteredCommands[slashIndex]) handleSlashSelect(filteredCommands[slashIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setSlashOpen(false); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleSelectSession = async (id: string, ws: string) => {
    try {
      const r = await agentApi.getSession(id, ws);
      setMessages(r.messages || []);
      setSessionId(id);
      setPlanItems([]);
      setModeSwitches([]);  // H-2: 清空模式切换记录
      setStructuredTodos([]);  // H-FE: 清空结构化待办
      // 从历史消息中提取 plan
      for (const m of (r.messages || [])) {
        if (m.role === 'assistant' && m.content) {
          const plan = extractPlan(m.content);
          if (plan) setPlanItems(plan);
        }
      }
    } catch { setError('加载会话失败'); }
  };

  const handleNewSession = () => {
    setSessionId(''); setSessionTitle(''); setMessages([]); setStats(null); setError(''); setPlanItems([]);
    setModeSwitches([]);  // H-2: 清空模式切换记录
    setStructuredTodos([]);  // H-FE: 清空结构化待办
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

  // 分组消息（H-2: 插入模式切换卡片）
  const grouped = useMemo(() => {
    const groups = groupMessages(messages);
    if (modeSwitches.length === 0) return groups;
    // 在适当位置插入模式切换卡片
    // 简化策略：按 msgIndex 找到对应分组位置插入
    const result: GroupedItem[] = [];
    let msgIdx = 0;
    let switchIdx = 0;
    for (const g of groups) {
      // 计算当前组对应的 message 索引增量
      if (g.type === 'user') msgIdx++;
      else if (g.type === 'assistant-text') msgIdx++;
      else if (g.type === 'tool-group') msgIdx += (g.tools?.length || 0) + 1;  // assistant + tool results
      // 检查是否有切换事件应在此处插入
      while (switchIdx < modeSwitches.length && modeSwitches[switchIdx].msgIndex <= msgIdx) {
        result.push({ type: 'mode-switch', modeSwitch: modeSwitches[switchIdx] });
        switchIdx++;
      }
      result.push(g);
    }
    // 剩余的切换事件追加到末尾
    while (switchIdx < modeSwitches.length) {
      result.push({ type: 'mode-switch', modeSwitch: modeSwitches[switchIdx] });
      switchIdx++;
    }
    return result;
  }, [messages, modeSwitches]);

  // 上下文大小 + 模型上下文窗口限制
  const estimatedTokens = messages.reduce((sum, m) => sum + Math.ceil((m.content?.length || 0) / 4), 0);
  const ctxTokens = stats?.total_tokens || estimatedTokens;
  const ctxSize = `${ctxTokens >= 1000 ? (ctxTokens / 1000).toFixed(1) + 'K' : ctxTokens} ctx`;
  const currentModel = models.find(m => m.id === currentModelId);
  const ctxLimit = parseInt(currentModel?.max_context_tokens || '') || DEFAULT_CTX_LIMIT;

  // 渲染分组消息
  const renderGrouped = (item: GroupedItem, idx: number) => {
    if (item.type === 'user') {
      return (
        <div key={idx} className="mb-2 flex justify-end">
          <div className="max-w-[80%] rounded-lg rounded-br-sm px-3 py-1.5 text-sm bg-info/10 text-info/90 border border-info/20">
            {item.content}
          </div>
        </div>
      );
    }
    if (item.type === 'assistant-text') {
      return (
        <div key={idx} className="mb-2 px-1 py-1">
          <MarkdownText content={item.content || ''} />
        </div>
      );
    }
    // step-complete: 步骤完成提示
    if (item.type === 'step-complete') {
      return (
        <div key={idx} className="mb-2 flex items-center gap-2 px-2 py-1 bg-green-900/10 border border-green-700/20 rounded text-xs">
          <span className="text-green-500">✅</span>
          <span className="text-green-400/80">完成：{item.content}</span>
        </div>
      );
    }
    // mode-switch: 模式切换卡片（H-2）
    if (item.type === 'mode-switch' && item.modeSwitch) {
      const ms = item.modeSwitch;
      const fromLabel = MODE_LABELS[ms.from] || ms.from;
      const toLabel = MODE_LABELS[ms.to] || ms.to;
      return (
        <div key={idx} className="mb-2 flex items-center gap-2 px-3 py-1.5 bg-info/5 border border-info/20 rounded text-xs">
          <span className="text-info/60">🔄</span>
          <span className="text-gray-400">{fromLabel}</span>
          <span className="text-gray-600">→</span>
          <span className="text-info font-medium">{toLabel}</span>
          {ms.auto && <span className="text-[10px] text-gray-600 ml-1">（自动）</span>}
          <span className="text-[10px] text-gray-500 ml-auto">{ms.reason}</span>
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
      {/* 左侧：会话树 */}
      <SessionTree
        sessions={sessions}
        currentSessionId={sessionId}
        currentWorkspace={currentWorkspace}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
      />

      {/* 中间+右侧 */}
      <div className="flex-1 flex min-w-0">
        {/* 对话区 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 顶部信息栏 */}
          <div className="flex-shrink-0 px-4 py-1.5 border-b border-border flex items-center gap-3 text-[10px] text-gray-500">
            <span className={wsState === 'open' ? 'text-green-500' : 'text-red-400'}>
              {wsState === 'open' ? '●' : '○'}
            </span>
            {sessionTitle && <span className="text-gray-300 font-medium">{sessionTitle}</span>}
            {sessionId && <span className="font-mono text-gray-600">{sessionId}</span>}
            {sessionId && (
              <button onClick={handleExportSession} className="text-gray-500 hover:text-info transition-colors" title="导出会话 JSON">
                📥 导出
              </button>
            )}
            {stats && (
              <>
                <span>·</span>
                <span className={stats.is_mock ? 'text-yellow-500' : 'text-green-500'}>
                  {stats.is_mock ? 'MOCK' : 'LIVE'} ({stats.model})
                </span>
              </>
            )}
            {scenarioMeta && (
              <>
                <span>·</span>
                <button onClick={() => setShowInfoPack(!showInfoPack)} className="text-gray-400 hover:text-gray-200">
                  📦 基础信息包({scenarioMeta.info_pack.length}) {showInfoPack ? '▲' : '▼'}
                </button>
              </>
            )}
            <div className="ml-auto">{turnInfo}</div>
          </div>

          {/* 基础信息包展开 */}
          {showInfoPack && scenarioMeta && (
            <div className="flex-shrink-0 px-4 py-2 bg-surface-2 border-b border-border max-h-32 overflow-y-auto">
              {scenarioMeta.info_pack.map(path => (
                <div key={path} className="flex items-center gap-1 group">
                  <span className="text-[10px]">📄</span>
                  <span className="text-[10px] font-mono text-gray-500 flex-1 truncate">{path}</span>
                  <button onClick={async () => {
                    const newFiles = scenarioMeta.info_pack.filter(f => f !== path);
                    try {
                      const updated = await scenarioApi.updateInfoPack(scenarioMeta.id, newFiles);
                      setScenarioMeta(updated);
                    } catch { setError('移除文件失败'); }
                  }} className="text-red-500 text-[10px] opacity-0 group-hover:opacity-100">✕</button>
                </div>
              ))}
            </div>
          )}

          {/* 消息列表 — 统一背景 */}
          <div className="flex-1 overflow-y-auto px-4 py-3">
            {grouped.length === 0 && !loading && (
              <div className="text-center text-gray-600 text-sm py-12">
                输入消息开始对话，或输入 / 查看可用命令
              </div>
            )}
            {grouped.map(renderGrouped)}
            {error && (
              <div className="bg-red-900/20 border border-red-700/30 rounded p-2 mb-2">
                <span className="text-red-400 text-sm">❌ {error}</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* 底部输入区 */}
          <div className="flex-shrink-0 border-t border-border p-3 relative">
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

            {/* 输入框 + 发送/停止按钮 */}
            <div className="flex gap-2 items-end">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => handleInputChange(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={wsState === 'open' ? '输入消息... (Enter 发送, / 查看命令)' : 'WebSocket 未连接'}
                rows={1}
                className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none resize-none max-h-32"
                disabled={loading || wsState !== 'open'}
              />
              {/* 发送按钮 / 停止按钮 */}
              {loading ? (
                <button
                  onClick={handleStop}
                  title="打断会话"
                  className="w-10 h-10 flex-shrink-0 bg-red-600 text-white rounded-full flex items-center justify-center hover:bg-red-500 transition-colors"
                >
                  <span className="text-lg">■</span>
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || wsState !== 'open'}
                  className="w-10 h-10 flex-shrink-0 bg-info text-white rounded-full flex items-center justify-center hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  ↑
                </button>
              )}
            </div>

            {/* 底部选择器栏 */}
            <div className="flex items-center gap-1 mt-2 flex-wrap">
              <ModeBadge
                currentMode={currentMode}
                lockedMode={lockedMode}
                modes={modes}
                onSelectMode={(mode) => {
                  setCurrentMode(mode);
                  setLockedMode(mode);
                }}
                onUnlock={() => setLockedMode('')}
              />
              <span className="text-gray-700">|</span>
              {models.length > 0 && (
                <select
                  value={currentModelId}
                  onChange={e => setCurrentModelId(e.target.value)}
                  className="bg-surface-2 border border-border rounded px-2 py-0.5 text-[10px] text-gray-400 font-mono"
                >
                  {models.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.is_default ? '★ ' : ''}{m.name || m.model}
                    </option>
                  ))}
                </select>
              )}
              <span className="text-gray-700">|</span>
              {skills.length > 0 && (
                <button onClick={() => setShowSkills(!showSkills)}
                  className="text-[10px] px-2 py-0.5 rounded bg-surface-2 text-gray-500 hover:text-gray-300 border border-border">
                  📋 技能({skills.length}) {showSkills ? '▲' : '▼'}
                </button>
              )}
              <div className="ml-auto flex items-center gap-2 text-[10px] text-gray-600 font-mono">
                {stats && stats.tps !== undefined && <span title="tokens/sec">⚡ {stats.tps}/s</span>}
                {stats && stats.prompt_tokens !== undefined && <span title="prompt/completion tokens">↑{stats.prompt_tokens} ↓{stats.completion_tokens}</span>}
                {stats && stats.elapsed_time !== undefined && <span title="elapsed time">⏱ {stats.elapsed_time}s</span>}
                <span>{ctxSize}</span>
              </div>
            </div>

            {showSkills && skills.length > 0 && (
              <div className="mt-1 bg-surface-2 border border-border rounded-lg p-2 max-h-32 overflow-y-auto">
                {skills.map(s => (
                  <div key={s.name} className="px-2 py-0.5">
                    <span className="text-[10px] text-info font-mono">{s.name}</span>
                    <span className="text-[10px] text-gray-500 ml-2">{s.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右侧：上下文用量 + 待办面板 */}
        <SidePanel ctxUsage={ctxUsage} planItems={planItems} structuredTodos={structuredTodos} loading={loading} currentMode={currentMode} messages={messages} ctxLimit={ctxLimit} />
      </div>
    </div>
  );
}
