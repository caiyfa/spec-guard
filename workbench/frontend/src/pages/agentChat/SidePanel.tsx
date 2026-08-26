import { useEffect } from 'react';
import type { GateCard, ScenarioMeta } from '../../api';
import TodoPanel from '../../components/TodoPanel';
import type { StructuredTodo } from '../../components/TodoPanel';
import FileViewer from '../../components/FileViewer';
import type { DocHunk } from '../../components/FileViewer';
import ReadingPanel from '../../components/ReadingPanel';
import type { DocReadItem } from '../../components/ReadingPanel';
import GateDockPanel from '../GateDockPanel';
import Skills from '../Skills';
import SpecValidation from '../SpecValidation';
import Knowledge from '../Knowledge';
import { FocusGraphTab } from '../../components/FocusGraph';
import type { AgentStats, ChatMessage, ChatReference, CtxUsage, DocWriteItem, FileTab } from './types';
import { ContextPanel } from './ContextPanel';
import { RefPanel } from './RefPanel';
import { InfoPackPanel } from './InfoPackPanel';
import { WritingPanel } from './WritingPanel';
import { DraftArtifactsPanel } from './DraftArtifactsPanel';
import { DepGraphPanel } from './DepGraphPanel';
import { MaterialsRefPanel } from './MaterialsRefPanel';
import { HistoryPanel } from './HistoryPanel';
import { SqlAuxPanel } from './SqlAuxPanel';

// ── 右侧面板组件（引用 + 信息包 + 上下文 + 待办） ──
// ── K-032：右侧页签面板（待办首页 + 信息包页签 + 文件各自页签） ──

// T-932：页签注册表（页签 id 单一事实源）——通用页签所有 purpose 恒显，
// 专用页签由 purpose 的 panels 声明驱动（∩ 本注册表，未知 id 静默忽略）。
// materials 页签 T-933 落地（requirement_interview panels 已声明）。
const SIDE_TABS: { id: string; label: string; scope: 'universal' | 'purpose' }[] = [
  { id: 'todos',   label: '📋 待办',       scope: 'universal' },
  { id: 'gates',   label: '🎛 操作台',     scope: 'universal' },
  { id: 'reading', label: '📖 阅读',       scope: 'universal' },
  // 更新足迹与草稿产物分列两页签（2026-08-26）：足迹条目多时会把草稿产物卡顶出首屏，
  // 草稿产物是评审主入口，前置独立成签
  { id: 'drafts',  label: '📝 草稿产物',   scope: 'universal' },
  { id: 'writing', label: '✏️ 更新足迹',   scope: 'universal' },
  // T-996 菜单收缩收编：技能（只读）/合规校验/知识 收进对话页通用页签
  { id: 'skills',  label: '🛠 技能',       scope: 'universal' },
  { id: 'spec',    label: '📏 合规',       scope: 'universal' },
  { id: 'knowledge', label: '🧠 知识',     scope: 'universal' },
  { id: 'pack',    label: '📦 信息包',     scope: 'purpose' },
  { id: 'focus',   label: '◎ 图谱',        scope: 'purpose' },
  { id: 'materials', label: '📎 材料',     scope: 'purpose' },
  { id: 'deps',    label: '🕸 依赖图',     scope: 'purpose' },
  { id: 'history', label: '📜 提交历史',   scope: 'purpose' },
  { id: 'sql_aux', label: '🧮 SQL 助手', scope: 'purpose' },  // 设计 2026-08-25 §C2
];

export function SidePanel({ ctxUsage, planItems, structuredTodos, loading, messages, ctxLimit, stats, scenarioMeta, onUpdateMeta, onError, references, onViewFile, fileTabs, activeTab, onSelectTab, onCloseTab, width, onCollapse, maximized, onToggleMaximize, draftFiles, readingFeed, onOpenDocRead, onRefreshReadingFeed, writingFeed, onOpenDocWrite, onOpenDiff, onAskAgentFix, onAskAgentBatch, onRefreshWritingFeed, sessionId, workspace, onCiteToMain, onAskAgentGuide, purposePanels }: {
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
  onRefreshReadingFeed?: () => void;
  writingFeed: DocWriteItem[];  // S0.6：更新足迹（doc_write 事件汇聚，时间倒序）
  onOpenDocWrite: (item: DocWriteItem) => void;
  onOpenDiff: (item: DocWriteItem) => void;
  onAskAgentFix?: (item: DocWriteItem) => void;
  onAskAgentBatch?: (items: DocWriteItem[]) => void;
  onRefreshWritingFeed?: () => void;
  sessionId: string;  // GateDock：操作台按会话反查面试上下文（sf_interviews 绑定）
  workspace: string;              // §C2：SQL 助手 spawn/WS 用
  onCiteToMain: (draftFilename: string) => void;  // §B6：辅助会话产出「引用到主会话」回流
  onAskAgentGuide?: (card: GateCard) => void;  // GateDock：「🤖 帮我」L1 引导
  purposePanels?: string[];  // T-932：当前 purpose 声明的专用页签 id（未声明 → 仅通用集）
}) {
  const isFileTab = activeTab.startsWith('file:');
  const activeFile = isFileTab ? fileTabs.find(t => `file:${t.path}` === activeTab) : null;

  // T-932：装配——通用恒显 + purpose 声明的专用（∩ 注册表）；pack 保持信息包存在才显
  const purposePanelSet = new Set(purposePanels || []);
  const visibleTabs = SIDE_TABS
    .filter(t => t.scope === 'universal' || purposePanelSet.has(t.id))
    .filter(t => t.id !== 'pack' || !!scenarioMeta);
  const labelOf = (id: string) => {
    if (id === 'reading' && readingFeed.length > 0) return `📖 阅读(${readingFeed.length})`;
    if (id === 'drafts' && draftFiles.length > 0) return `📝 草稿产物(${draftFiles.length})`;
    if (id === 'writing' && writingFeed.length > 0) return `✏️ 更新足迹(${writingFeed.length})`;
    if (id === 'pack' && scenarioMeta) return `📦 信息包(${scenarioMeta.info_pack.length})`;
    return SIDE_TABS.find(t => t.id === id)?.label || id;
  };
  // 活动页签被装配隐藏（如切方向后专用页签不再可见）→ 回落到待办
  useEffect(() => {
    const hidden = SIDE_TABS.find(t =>
      t.id === activeTab && t.scope === 'purpose' && !purposePanelSet.has(t.id));
    if (hidden) onSelectTab('todos');
  }, [activeTab, purposePanels, onSelectTab]);

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
    >      {/* 页签条（K-032：参考编辑器页签样式；T-932 注册表装配） */}
      <div className="flex items-center border-b border-border overflow-x-auto flex-shrink-0">
        {visibleTabs.map(t => tabBtn(t.id, labelOf(t.id)))}
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
        {activeTab === 'gates' && (
          <GateDockPanel sessionId={sessionId} onAskAgent={onAskAgentGuide || (() => {})} onError={onError} />
        )}
        {activeTab === 'skills' && <Skills />}
        {activeTab === 'spec' && <SpecValidation />}
        {activeTab === 'knowledge' && <Knowledge />}
        {activeTab === 'focus' && <FocusGraphTab messages={messages} />}
        {activeTab === 'materials' && (
          <MaterialsRefPanel sessionId={sessionId} references={references} onError={onError} />
        )}
        {activeTab === 'reading' && (
          <ReadingPanel items={readingFeed} onOpen={onOpenDocRead} onRefresh={onRefreshReadingFeed} />
        )}
        {activeTab === 'pack' && scenarioMeta && (
          <InfoPackPanel meta={scenarioMeta} onUpdate={onUpdateMeta} onError={onError}
            onViewFile={(p) => onViewFile(p)} defaultOpen />
        )}
        {activeTab === 'drafts' && (
          <DraftArtifactsPanel draftFiles={draftFiles} onViewFile={onViewFile} onError={onError} />
        )}
        {activeTab === 'writing' && (
          <WritingPanel items={writingFeed} onOpen={onOpenDocWrite} onDiff={onOpenDiff} onAskAgent={onAskAgentFix} onAskAgentBatch={onAskAgentBatch} onRefresh={onRefreshWritingFeed} />
        )}
        {activeTab === 'deps' && (
          <DepGraphPanel draftFiles={draftFiles} onError={onError} />
        )}
        {activeTab === 'history' && (
          <HistoryPanel onError={onError} />
        )}
        {activeTab === 'sql_aux' && (
          <SqlAuxPanel mainSessionId={sessionId} workspace={workspace} onCiteToMain={onCiteToMain} />
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
