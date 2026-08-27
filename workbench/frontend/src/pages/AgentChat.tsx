/** AgentChat — 左侧会话树 + 中间对话区 + 右侧面板（K-012 简洁化：底部仅模式/模型下拉 + 输入框）
 *  T-995：面板/输入区/消息渲染等子组件按职责拆至 ./agentChat/，本文件只保留会话状态机与布局装配。 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { session, agentApi, authApi, scenarioApi, modelApi, workspaceApi, draftsApi } from '../api';
import type { ScenarioMeta, ModelConfig, GateCard } from '../api';
import SessionTree from '../components/SessionTree';
import type { StructuredTodo } from '../components/TodoPanel';
import type { DocHunk, EditSaveOutcome } from '../components/FileViewer';
import type { DocReadItem } from '../components/ReadingPanel';
import type { ChatReference, ChatMessage, AgentStats, CtxUsage, GroupedItem, DocWriteItem, FileTab } from './agentChat/types';
import { DEFAULT_CTX_LIMIT, PURPOSE_TITLE_FALLBACK } from './agentChat/types';
import { ArtifactCtx, GateDockCtx, SqlAuxBridgeCtx } from './agentChat/contexts';
import type { ArtifactCtxValue, SqlAuxBridgeValue } from './agentChat/contexts';
import { DbPanel } from './agentChat/DbPanel';
import { stripRefBlock, extractPlan, filterTreeSessions } from './agentChat/utils';
import { groupMessages, draftWriteUndo } from './agentChat/groupMessages';
import { MarkdownText } from './agentChat/MarkdownText';
import { ArtifactCard } from './agentChat/ArtifactCard';
import { PurposeCards } from './agentChat/PurposeCards';
import { ToolGroupBlock } from './agentChat/ToolBlocks';
import { CopyButton, isShortReply, MessageWithToolbar } from './agentChat/MessageWithToolbar';
import { ConversationRail } from './agentChat/ConversationRail';
import { ChatInput } from './agentChat/ChatInput';
import { SidePanel } from './agentChat/SidePanel';
import { DiffOverlay } from './agentChat/WritingPanel';
import { _store } from './agentChat/sessionStore';

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
  const [writingFeed, setWritingFeed] = useState<DocWriteItem[]>(_store.writingFeed);  // S0.6
  // 更新对比弹窗（.bak diff）
  const [diffItem, setDiffItem] = useState<DocWriteItem | null>(null);
  // S0.6：外部注入对话输入框的文本（「让 Agent 修复」带失败原因）
  const [quickText, setQuickText] = useState('');

  const [sessions, setSessions] = useState<any[]>([]);
  const [sessionsVersion, setSessionsVersion] = useState(0);
  // T-010: 用途选择（使命卡片）
  // 验收缺陷 2 复验修复：初始值从 _store 恢复（SPA 跳回时 purpose 页签立即可装配）；
  // setPurposes 包装同步 _store，跨导航不丢。
  const [purposes, setPurposesState] = useState<{ id: string; title: string; icon: string; color: string; chips: string[]; description: string; panels: string[] }[]>(_store.purposes || []);
  const setPurposes = useCallback((list: { id: string; title: string; icon: string; color: string; chips: string[]; description: string; panels: string[] }[]) => {
    _store.purposes = list;
    setPurposesState(list);
  }, []);
  const [showPurposePicker, setShowPurposePicker] = useState(false);
  const [pickedPurpose, setPickedPurpose] = useState(() => localStorage.getItem('sg_picked_purpose') || '');
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [currentModelId, setCurrentModelId] = useState('');
  const [scenarioMeta, setScenarioMeta] = useState<ScenarioMeta | null>(null);
  const [streamingText, setStreamingText] = useState('');  // K-012: 流式生成中的文本
  // K-032：文件页签（取代 modal 弹窗）+ 活动页签（'todos' | 'pack' | `file:{path}`）
  const [fileTabs, setFileTabs] = useState<FileTab[]>([]);
  const [activeSideTab, setActiveSideTab] = useState('todos');
  const [citeDraft, setCiteDraft] = useState('');  // §B6：辅助会话产出引用预填（ChatInput pendingRef）

  // SQL 探索模式（设计 2026-08-26）：DB 面板会话内嵌打开——主会话最小化为细条，
  // SQL 助手（SidePanel）居左撑宽、内嵌 DbPanel 居右；双向联动不走页面跳转。
  // 桥沿用 GateDockCtx 注入模式（SqlAuxPanel 埋在 SidePanel 深处，props 不穿链）
  const [dbExplore, setDbExplore] = useState(false);
  const [dbPendingSql, setDbPendingSql] = useState('');  // 左栏「▶ DB 面板」带来的回填 SQL
  const auxSendRef = useRef<(t: string) => void>(() => {});  // SqlAuxPanel 上报的 send
  const sqlAuxBridge = useMemo<SqlAuxBridgeValue>(() => ({
    register: (fn) => { auxSendRef.current = fn; },
    openDbPanel: (sql) => { setSideMax(false); setDbPendingSql(sql); setDbExplore(true); },
  }), []);
  // DB 面板「交给 SQL 助手」：直发左栏辅助会话（同时确保左栏页签切回 sql_aux）
  const handToAux = useCallback((sql: string) => {
    setActiveSideTab('sql_aux');
    auxSendRef.current(sql);
  }, []);

  // DB 面板转来：激活 SQL 助手页签（§C3；pending 由 SqlAuxPanel 在 WS 就绪后消费）
  useEffect(() => {
    if (!sessionStorage.getItem('sg_sql_aux_send')) return;
    (async () => {
      // 竞态防护（验收缺陷 2 复验修复）：purposes 未就绪时先拉取再激活——否则
      // SidePanel 回落 guard 会在 purpose 页签未装配时把 activeTab 重置为 todos
      if (!_store.purposes?.length) {
        try {
          const pr = await agentApi.listPurposes();
          setPurposes(pr.purposes || []);
        } catch { /* 页签缺省为通用集，激活仍尝试 */ }
      }
      setActiveSideTab('sql_aux');
      setSideCollapsed(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
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
          const da = draftWriteUndo(tc.function.name, args);  // T-982：draft action 判定
          if (da === 'write' && args.filename) files.set(args.filename, order++);
          else if (da === 'undo' && args.filename) files.delete(args.filename);
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
  const sessionIdRef = useRef('');  // K-xxx: WS onopen 重连补拉需要最新 sessionId（避开闭包过期）
  const wsPingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);  // WS 健康检测定时器
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
      // T-010 扩展：一次拉全（含归档），SessionTree 内部分组显示
      const r = await agentApi.listSessions('', '', true);
      setSessions(filterTreeSessions(r.sessions || []));  // 辅助会话不进会话树（§B5）
    } catch { setSessions([]); }
  }, []);

  // T-010 扩展：批量归档/恢复（后端只处理本人会话，非本人跳过）
  const [notice, setNotice] = useState('');  // 绿色成功提示（区别于红色错误）
  const [reconnecting, setReconnecting] = useState(false);  // WS 自动重连中（非错误，低入侵提示）
  const handleBatchArchive = useCallback(async (ids: string[], archived: boolean) => {
    try {
      const r = await agentApi.batchArchive(ids, archived, currentWorkspace);
      setSessionsVersion(v => v + 1);
      const skipNote = r.skipped?.length ? `，${r.skipped.length} 个未生效（仅本人会话可管理）` : '';
      setNotice(`${archived ? '🗄 已归档' : '↺ 已恢复'} ${r.processed} 个会话${skipNote}`);
      setTimeout(() => setNotice(''), 3000);
    } catch (e: any) {
      setError(e.message || '批量操作失败');
    }
  }, [currentWorkspace]);

  // owner 权限：当前用户工号（批量模式下仅本人会话可勾选）
  const [ownEmpNo, setOwnEmpNo] = useState('');
  useEffect(() => {
    authApi.me().then(u => setOwnEmpNo(u.emp_no)).catch(() => {});
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
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);
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
  useEffect(() => { _store.writingFeed = writingFeed; }, [writingFeed]);

  // WebSocket（跨导航保持，不随组件卸载关闭）
  // 使用 ref 存储最新的事件处理函数，避免闭包过期
  const wsHandlerRef = useRef<(event: any) => void>(() => {});
  wsHandlerRef.current = (event: any) => {
    // T-1021: 事件会话过滤——事件带 session_id 且与当前会话不符 → 丢弃
    // （防 attach 残留流/旧会话 run 污染切换后的会话 UI，顺带修不同会话
    // 并发 run 事件混流；state/started 例外：新建会话首事件必须放行，
    // 否则 sessionId 无法建立）
    if (event.session_id && sessionIdRef.current
      && event.session_id !== sessionIdRef.current
      && !(event.type === 'state' && event.status === 'started')) {
      return;
    }
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
          const updated = {
            ...old, turn: event.turn ?? old.turn, size: event.size ?? old.size,
            excerpt: event.excerpt || old.excerpt, label: event.label || old.label,
            thinking: event.thinking || old.thinking, hunks: mergedHunks, reads: old.reads + 1,
          };
          // T-511 修复：已有卡片再次读取后移到列表头部（保持「最近阅读排最前」）
          next.splice(idx, 1);
          next.unshift(updated);
          return next;
        });
        break;
      }
      case 'doc_write': {
        // S0.6 更新足迹：写型工具成功——同文件去重（最新内容/verdict 覆盖，次数累计），新卡 prepend
        const key = event.path || event.ref || `${event.tool}:unknown`;
        setWritingFeed(prev => {
          const hunks: DocHunk[] = (event.hunks || []).map((h: any) => ({
            title: h.title || '', start: h.start || 1, end: h.end || 1, note: h.note,
          }));
          const card: DocWriteItem = {
            key, tool: event.tool || '', ref: event.ref || '', path: event.path || null,
            turn: event.turn ?? 0, size: event.size ?? 0, excerpt: event.excerpt || '',
            label: event.label || event.tool || '', thinking: event.thinking || '',
            verdict: event.verdict || null,
            findings: (event.findings || []).map((f: any) => ({
              level: f.level || '', rule: f.rule || '', message: f.message || '',
            })),
            hunks, writes: 1,
          };
          const idx = prev.findIndex(i => i.key === key);
          if (idx === -1) return [card, ...prev];
          const old = prev[idx];
          const mergedHunks = [...old.hunks];
          for (const h of hunks) {
            if (!mergedHunks.some(o => o.start === h.start && o.end === h.end && o.title === h.title)) {
              mergedHunks.push(h);
            }
          }
          const next = [...prev];
          const updated = {
            ...old, turn: event.turn ?? old.turn, size: event.size ?? old.size,
            excerpt: event.excerpt || old.excerpt, label: event.label || old.label,
            thinking: event.thinking || old.thinking,
            verdict: event.verdict || old.verdict,
            findings: (event.findings || []).length > 0 ? (event.findings || []).map((f: any) => ({
              level: f.level || '', rule: f.rule || '', message: f.message || '',
            })) : old.findings || [],
            hunks: mergedHunks,
            writes: (old.writes || 1) + 1,
          };
          next.splice(idx, 1);
          next.unshift(updated);
          return next;
        });
        break;
      }
      case 'attached': {
        // T-1021: attach 确认。run 已结束（attach 前刚完成的竞态）→ 解除 loading
        // 并全量拉取对齐（done 可能已落盘但从未送达本页）
        if (!event.run_in_progress) {
          setLoading(false);
          setStreamingText('');
          setTurnInfo('');
          if (event.session_id && event.session_id === sessionIdRef.current) {
            agentApi.getSession(event.session_id, currentWorkspace)
              .then(r => {
                const msgs = r.messages || [];
                setMessages(prev => (msgs.length >= prev.length ? msgs : prev));
                setSessionsVersion(v => v + 1);
              })
              .catch(() => { });
          }
        }
        break;
      }
      case 'replay_batch': {
        // T-1021: 回放批次——逐条走既有事件管线（重建 run 进行中的 UI 现场）
        if (event.session_id && event.session_id !== sessionIdRef.current) break;
        for (const ev of (event.events || [])) wsHandlerRef.current(ev);
        break;
      }
      case 'done':
        setStats(event.stats || null);
        if (event.session_id) {
          setSessionId(event.session_id);
          localStorage.setItem('sg_agent_session', event.session_id);
        }
        if (event.title) setSessionTitle(event.title);
        // T-1021: done 携带全量 messages——attach/回放路径的对齐兑底
        // （发送方路径 messages 由事件流维护，两者等长，替换无害）
        if (Array.isArray(event.messages) && event.messages.length) {
          setMessages(prev => (event.messages.length >= prev.length ? event.messages : prev));
        }
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
          setReconnecting(false);
          setError(prev => prev.startsWith('连接已断开') ? '' : prev);
        }
        // K-xxx: 重连成功后增量补拉——断连期间后端 run 可能已继续执行并落盘（断连不打断），
        // 页面未刷新时本地 messages 缺尾部回复，静默拉取补齐（只多不少才替换）。
        // 2.5s 延迟：给后台落盘留窗口；拉取失败不影响现有显示。
        if (_store.everConnected && sessionIdRef.current) {
          const sid = sessionIdRef.current;
          const wsp = session.getWorkspace();
          window.setTimeout(async () => {
            try {
              const r = await agentApi.getSession(sid, wsp);
              const msgs = r.messages || [];
              setMessages(prev => (msgs.length > prev.length ? msgs : prev));
              setSessionsVersion(v => v + 1);
              // T-1021: 断连期间 run 仍在执行 → attach 续上实时流
              // （attach 时已完成的竞态由后端 attached(run_in_progress=false) 兜底对齐）
              if (r.run_in_progress) {
                setLoading(true);
                const wsNow = wsRef.current;
                if (wsNow && wsNow.readyState === WebSocket.OPEN) {
                  wsNow.send(JSON.stringify({ type: 'attach', session_id: sid }));
                }
              }
            } catch { /* 静默 */ }
          }, 2500);
        }
        // T-1021: WS 就绪前挂起的 attach（刷新页面后 restoreSession 先于 WS open）
        if (pendingAttachRef.current) {
          const sid = pendingAttachRef.current;
          pendingAttachRef.current = '';
          ws.send(JSON.stringify({ type: 'attach', session_id: sid }));
        }
        _store.everConnected = true;
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
          if (reconnectAttemptsRef.current < 3) {
            // 前 3 次用低入侵的 reconnecting 状态（非红色错误栏）
            setReconnecting(true);
            const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 10000);
            reconnectAttemptsRef.current += 1;
            window.setTimeout(() => { if (_store.mounted) setWsReconnect(v => v + 1); }, delay);
          } else if (reconnectAttemptsRef.current < 5) {
            // 第 4-5 次：升级为 error 提示
            setError('连接已断开，正在自动重连…');
            setReconnecting(false);
            const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 10000);
            reconnectAttemptsRef.current += 1;
            window.setTimeout(() => { if (_store.mounted) setWsReconnect(v => v + 1); }, delay);
          } else {
            setReconnecting(false);
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
          purpose: 'test_workbench',
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
        const msg = `定时任务运行失败，请分析运行 ${debugRunId} 的失败原因。使用 attribution(action=report) 工具读取运行报告，定位失败场景和错误根因，给出修复建议。`;
        setLoading(true); setError(''); setPlanItems([]);  // K-xxx：待办不再预填固定模板——由模型 todo_write/<plan> 输出，避免「刚发消息就出写死待办」 setCtxUsage(null);
        setMessages(prev => [...prev, { role: 'user', content: msg }]);
        ws.send(JSON.stringify({
          message: msg, session_id: '', max_turns: 50,
          workspace: currentWorkspace, scenario_id: '',
          model_id: currentModelId,
          purpose: 'test_workbench',
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
        setReconnecting(true);
        setWsReconnect(v => v + 1);
      }
    }, 5000);  // 每 5 秒检查
    return () => clearInterval(timer);
  }, [loading]);

  // K-xxx: WS 前台健康检测——WS 打开时每 30s 发 ping，检测半开连接
  // 同时发起 idle 检测：连续 60s 无任何事件判定断连
  useEffect(() => {
    if (wsState !== 'open') {
      // WS 未打开时清除定时器
      if (wsPingIntervalRef.current) {
        clearInterval(wsPingIntervalRef.current);
        wsPingIntervalRef.current = null;
      }
      return;
    }
    // 每 30s 检测空闲 + 发 ping 保活
    wsPingIntervalRef.current = setInterval(() => {
      const idle = Date.now() - lastEventTimeRef.current;
      if (idle > 60000) {
        // 60s 无任何事件——判定连接断开（空闲期只有后端心跳 /20s 和 uvicorn ping/20s）
        // 不触发 loading（不在 run 中），直接静默重连
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          // 主动关闭旧连接，触发 onclose → 自动重连
          (ws as any)._intentional = false;  // 确保 onclose 走重连逻辑
          ws.close();
        }
        return;
      }
      // 发 ping 探测（后端只占用了 receive_json 消息队列，不阻塞）
      try {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      } catch {
        // 静默失败，await onclose 触发重连
      }
    }, 30000);
    return () => {
      if (wsPingIntervalRef.current) {
        clearInterval(wsPingIntervalRef.current);
        wsPingIntervalRef.current = null;
      }
    };
  }, [wsState]);

  // 发送消息
  // 返回是否真正发出——ChatInput 据此决定清空输入框（发送被拒时保留草稿）
  // T-010: 拉取可见用途并决定是否显示选择卡片（单用途自动锁定；多用途弹卡片；失败静默降级）
  const fetchAndShowPurposes = useCallback(async (): Promise<boolean> => {
    try {
      const r = await agentApi.listPurposes();
      const list = r.purposes || [];
      setPurposes(list);
      if (list.length === 1) {
        // 单用途：跳过选择直接锁定
        setPickedPurpose(list[0].id);
        localStorage.setItem('sg_picked_purpose', list[0].id);
        setShowPurposePicker(false);
        return true;
      } else if (list.length > 1) {
        // 多用途：展示使命卡片，等用户拍板
        setShowPurposePicker(true);
        setPickedPurpose('');
        localStorage.removeItem('sg_picked_purpose');
        return false;
      }
      setShowPurposePicker(false);
      return true;  // 无用途定义：不拦截（存量兼容）
    } catch {
      setShowPurposePicker(false);
      return true;  // 拉取失败：不拦截，避免功能不可用
    }
  }, []);

  const handleSend = useCallback((text: string, refs: ChatReference[]): boolean => {
    const userMsg = text.trim();
    const ws = wsRef.current;
    if (!userMsg || loading) return false;
    // T-010: 新会话必须先选用途——未选使命直接发送会创建无用途会话（工具集不锁定、提示词不装配），此处拦截并弹卡片
    if (!sessionId && !pickedPurpose) {
      setError('请先选择会话用途（测试工作台 / 产品工作台）再开始对话');
      fetchAndShowPurposes();
      return false;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setReconnecting(true);
      setError('连接已断开，消息未发送，重连后请重发');
      reconnectAttemptsRef.current = 0;
      setWsReconnect(v => v + 1);
      return false;
    }
    setLoading(true); setError(''); setTurnInfo(''); setPlanItems([]);
    const msgRefs = refs.length ? [...refs] : undefined;
    // K-015：发送时才落实 info_pack 关联（右侧信息包面板随发送出现）。
    // 注意：setScenarioId 是异步 setState，本轮 ws.send 必须用同步计算值
    // （此前用闭包旧值 scenarioId，后端收到旧场景 ID → 新上传的信息包被忽略）
    const packRef = msgRefs?.find(r => r.type === 'info_pack');
    let sidToSend = scenarioId;
    if (packRef && packRef.path !== scenarioId) {
      autoSentRef.current = true;  // 不触发向导自动发送
      sidToSend = packRef.path;
      setScenarioId(packRef.path);
      scenarioApi.getMeta(packRef.path).then(setScenarioMeta).catch(() => {});
      expandSideTo('pack');  // K-037：面板收起时随发送自动展开到信息包页签
    }
    setMessages(prev => [...prev, { role: 'user', content: userMsg, references: msgRefs }]);
    ws.send(JSON.stringify({
      message: userMsg, session_id: sessionId, max_turns: 50,
      workspace: currentWorkspace, scenario_id: sidToSend,
      model_id: currentModelId,
      purpose: pickedPurpose,
      references: (msgRefs || []).map(r => ({ type: r.type, id: r.path, path: r.path })),
      context: { current_page: currentPage, editing_scenario_id: sidToSend },
    }));
    return true;
  }, [loading, sessionId, pickedPurpose, currentWorkspace, scenarioId, currentModelId, currentPage, expandSideTo, fetchAndShowPurposes]);

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
    setActiveSideTab(prev => {
      if (prev === `file:${path}`) {
        if (readingFeed.length > 0) return 'reading';
        if (writingFeed.length > 0) return 'writing';  // 足迹/草稿分签后更新足迹独立成页
        return 'todos';
      }
      return prev;
    });
  }, [readingFeed, writingFeed]);

  // T-1027 F1/F2：草稿面板编辑保存——PUT /api/drafts（带 session_id），后端自动格式校验
  // + user_edit 版本链 + 对话感知注入；结果映射为 EditSaveOutcome 由编辑区内联回显
  const handleSaveDraftFile = useCallback(async (filename: string, content: string): Promise<EditSaveOutcome> => {
    try {
      const r = await draftsApi.update(filename, content, sessionId || undefined);
      if (!r.ok) return { ok: false, message: '保存失败（后端返回未确认）' };
      // 页签内容对齐落盘版本：结构化/原文视图立即反映新内容
      setFileTabs(prev => prev.map(t => t.path === filename && t.kind === 'draft' ? { ...t, content } : t));
      const v = r.validate;
      let message = '对话已感知本次编辑与校验结论';
      if (r.percept?.mode === 'pending') message = '会话执行中——本次编辑将在下一条消息发送前自动告知对话';
      else if (r.percept?.mode === 'off') message = r.percept.reason === 'session_not_found' ? '会话不存在，编辑未同步到对话' : '已保存';
      return {
        ok: true, message,
        verdict: v?.verdict,
        summaryError: v?.summary?.error ?? 0,
        summaryWarn: v?.summary?.warn ?? 0,
        findings: (v?.findings || []).map(f => ({ level: f.level, rule: f.rule, message: f.message })),
      };
    } catch (e: any) {
      return { ok: false, message: e?.message || '保存失败', findings: [] };
    }
  }, [sessionId]);

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

  // S0.6：更新足迹点击——write_draft/undo_draft 走草稿读取（私有区仅 draftsApi 可达，
  // yaml 限定）；write_delta_doc/promote 有工作区相对路径 → file: 页签；其余 memo 兜底
  const openDocWrite = useCallback((item: DocWriteItem) => {
    if (item.tool === 'write_draft' || item.tool === 'undo_draft') {
      openFileViewer(item.ref, 'draft', { hunks: item.hunks, fallback: item.excerpt });
    } else if (item.path) {
      openFileViewer(item.path, 'file', { hunks: item.hunks, fallback: item.excerpt });
    } else {
      openContentViewer(item.label || item.ref, item.excerpt, { hunks: item.hunks });
    }
  }, [openFileViewer, openContentViewer]);

  // S0.6：更新对比（.bak 旧版 vs 当前，行级 diff 弹窗）
  const openDiff = useCallback((item: DocWriteItem) => {
    setDiffItem(item);
  }, []);

  // S0.6：让 Agent 修复——失败文件 + 原因（findings）直接发送，不经过输入框确认
  const askAgentFix = useCallback((item: DocWriteItem) => {
    const findings = (item.findings || [])
      .map(f => `- ${f.level || ''}${f.rule ? ` ${f.rule}` : ''}: ${f.message}`)
      .join('\n');
    const target = item.path || item.ref || item.label;
    handleSend(
      `请修复 ${target} 的 conformance 校验失败：\n${findings}\n` +
      `请先读取相关文件分析失败原因，再继续更新（写入后校验 verdict 随结果返回）。`,
      [],
    );
  }, [handleSend]);

  // S0.6：批量修复全部失败文件——合并所有 ❌ 的 path + findings 一次注入
  const askAgentBatch = useCallback((items: DocWriteItem[]) => {
    const lines = items.map(item => {
      const target = item.path || item.ref || item.label;
      const reasons = (item.findings || [])
        .slice(0, 5)  // 每个文件最多带 5 条，防止消息过长
        .map(f => `    - ${f.level || ''}${f.rule ? ` ${f.rule}` : ''}: ${f.message}`)
        .join('\n');
      return `- ${target}：\n${reasons}`;
    }).join('\n');
    handleSend(
      `以下文件 conformance 校验失败（${items.length} 个）：\n${lines}\n` +
      `请按以下步骤处理：\n` +
      `1. 分析根因：读取各文件的失败原因，识别共同模式和关联性——多个文件是否因同一原因（如缺少公共文件）而失败？是否是写入顺序导致的中间状态（后续写入已补全）？\n` +
      `2. 制定计划：区分「真实缺陷需修复」与「中间状态需补写缺失文件」。列出写入顺序（如缺 proposal.md 就先写它）。\n` +
      `3. 按序执行：用 write_delta_doc 补写缺失文件或修复缺陷；每写入一个观察校验结果（verdict 随返回呈现）。` +
      `先分析，后执行。不要不看原因就直接重写已有文件。`,
      [],
    );
  }, [handleSend]);

  // GateDock：操作台「🤖 帮我」L1 引导——解释闸门语义 + 指导操作（分档接管：不代执行）
  const askAgentGuide = useCallback((card: GateCard) => {
    handleSend(
      `[操作台引导] 请帮我理解并指导完成「${card.title}」：\n` +
      `- 对象：${card.ref_id}\n- 当前状态：${card.summary}\n` +
      `请解释这个闸门的意义、操作后果，并告诉我下一步应该怎么做。` +
      `只需引导说明，不要代我执行写操作。`,
      [],
    );
  }, [handleSend]);

  // 撤回用户消息：移除该消息及之后全部内容，同时清空足迹（足迹=本轮运行依据）
  const handleRetract = useCallback((msgIdx: number) => {
    setMessages(prev => prev.slice(0, msgIdx));
    setReadingFeed([]);
    setWritingFeed([]);
  }, []);

  // 会话内 write_draft 内容映射（大段 md 代码块 → 落盘文件匹配，产物卡片去重用）
  const draftContents = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of messages) {
      if (m.role !== 'assistant' || !m.tool_calls) continue;
      for (const tc of m.tool_calls) {
        try {
          const args = JSON.parse(tc.function.arguments);
          if (draftWriteUndo(tc.function.name, args) !== 'write') continue;  // T-982
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

  // T-1021: attach 运行中会话（断连/刷新后续上实时流）。WS 未就绪时挂起，
  // onopen 后补发；detach 用于切会话时退出旧会话的 attach 订阅（后端对
  // 游离 detach 静默忽略，可盲发）。
  const pendingAttachRef = useRef('');
  const sendAttach = useCallback((sid: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'attach', session_id: sid }));
      return true;
    }
    pendingAttachRef.current = sid;
    return false;
  }, []);
  const sendDetach = useCallback(() => {
    pendingAttachRef.current = '';
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'detach' }));
    }
  }, []);

  // K-012: 恢复会话（会话项点击 / 页面刷新自动恢复共用）
  const restoreSession = useCallback(async (id: string, ws: string) => {
    // T-1021: 切会话前退出旧会话的 attach 订阅（若有）
    sendDetach();
    // 验收缺陷修复（2026-08-25）：恢复路径补 purposes 拉取——purpose 页签依赖
    // purposes.panels 装配，此前仅新建会话/发送拦截路径拉取，刷新/跨页跳回恢复后
    // purpose 页签（deps/history/sql_aux）整体消失。幂等低成本（listPurposes 轻量 GET）。
    try {
      const pr = await agentApi.listPurposes();
      setPurposes(pr.purposes || []);
    } catch { /* 页签降级为通用集 */ }
    const r = await agentApi.getSession(id, ws);
    const msgs = r.messages || [];
    // T-1021: run 进行中——截断到基线（丢弃 run 期间已落盘的部分消息，attach
    // 回放事件流将重建它们，天然去重），进入 loading 并 attach 续上实时流；
    // 不在执行中则解除可能残留的 loading（上一会话 run 中切来）
    const running = !!r.run_in_progress;
    if (running) {
      const bl = typeof r.run_baseline_len === 'number' ? r.run_baseline_len : 0;
      setMessages(msgs.length > bl ? msgs.slice(0, bl) : msgs);
    } else {
      setMessages(msgs);
      setLoading(false);
    }
    setSessionId(id);
    setReadingFeed(r.reading_feed || []);  // T-511: 阅读足迹从后端重建（跨刷新保持）
    setWritingFeed(r.writing_feed || []);  // S0.6: 更新足迹从后端重建（跨刷新保持）
    // T-010: 恢复会话时带出锁定用途（会话列表含 purpose 字段；找不到时保持现状）
    try {
      const lst = await agentApi.listSessions(ws, '', true);
      const meta = (lst.sessions || []).find((s: any) => s.id === id);
      const p = meta?.purpose || '';
      if (p) {
        setPickedPurpose(p);
        localStorage.setItem('sg_picked_purpose', p);
      }
    } catch { /* 恢复用途失败不阻塞会话加载 */ }
    setPlanItems([]);
    setStructuredTodos([]);  // H-FE: 清空结构化待办
    setReadingFeed([]);  // T-511：足迹=本轮运行依据，恢复历史会话时清空（不持久化）
    setWritingFeed([]);  // S0.6：同阅读足迹语义——恢复历史会话时清空，可手动 ↻ 刷新
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
    // T-1021: run 进行中——进入 loading 并 attach 续上实时流（回放重建执行现场）
    if (running) {
      setLoading(true);
      setTurnInfo('↻ 恢复执行现场…');
      sendAttach(id);
    }
  }, [sendAttach, sendDetach]);

  const handleSelectSession = async (id: string, ws: string) => {
    try {
      await restoreSession(id, ws);
      localStorage.setItem('sg_agent_session', id);
    } catch { setError('加载会话失败'); }
  };

  const handleRefreshReading = useCallback(async () => {
    if (!sessionId || !currentWorkspace) return;
    try {
      const r = await agentApi.getSession(sessionId, currentWorkspace);
      setReadingFeed(r.reading_feed || []);
    } catch { /* 静默 */ }
  }, [sessionId, currentWorkspace]);

  const handleRefreshWriting = useCallback(async () => {
    if (!sessionId || !currentWorkspace) return;
    try {
      const r = await agentApi.getSession(sessionId, currentWorkspace);
      setWritingFeed(r.writing_feed || []);
    } catch { /* 静默 */ }
  }, [sessionId, currentWorkspace]);

  // K-012: 页面刷新/服务重启后自动恢复上次会话（_store 为空时才补拉，SPA 内导航不触发）
  // T-1000: ?session= 深链优先（「我的活动」产出溯源/会话列表跳入）
  useEffect(() => {
    if (messages.length > 0 || scenarioId || debugRunId) return;
    const urlSid = new URLSearchParams(window.location.search).get('session');
    const savedId = urlSid || localStorage.getItem('sg_agent_session');
    if (!savedId) return;
    restoreSession(savedId, currentWorkspace)
      .catch(() => { if (!urlSid) localStorage.removeItem('sg_agent_session'); });  // 会话已不存在则清键静默降级
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNewSession = async () => {
    // T-1021: 新会话退出旧会话 attach 订阅并解除残留 loading（旧 run 后台继续落盘）
    sendDetach();
    setLoading(false);
    setTurnInfo('');
    setSessionId(''); setSessionTitle(''); setMessages([]); setStats(null); setError(''); setPlanItems([]);
    setStructuredTodos([]);  // H-FE: 清空结构化待办
    setReadingFeed([]);  // T-511：足迹=本轮运行依据，新会话清空
    setStreamingText('');
    // K-032：新会话同步清理信息包关联与文件页签
    setScenarioId(''); setScenarioMeta(null);
    setFileTabs([]); setActiveSideTab('todos');
    localStorage.removeItem('sg_agent_session');
    // T-010: 获取用途列表并决定是否显示选择卡片
    await fetchAndShowPurposes();
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
            <div className="flex items-center gap-1.5 mt-1">
              <CopyButton text={stripRefBlock(item.content || '')} className="text-[10px] text-info/40 hover:text-info" />
              {item.msgIdx !== undefined && (
                <button onClick={() => handleRetract(item.msgIdx!)}
                  className="text-[10px] text-gray-500 hover:text-red-400"
                  title="撤回该消息及后续内容">
                  撤回
                </button>
              )}
            </div>
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
      // 工具调用后的收尾短句（如「等你的拍板 ⏳」）：不套预览/文本重框，轻量气泡直渲，
      // 避免短句紧贴工具行下方被误读为「组件把多余内容识别进去」
      if (isShortReply(item.content || '')) {
        return (
          <div key={idx} className="mb-2 ml-1 border-l-2 border-border/50 pl-3 py-0.5 flex items-center gap-1.5">
            <div className="flex-1 min-w-0">
              <MarkdownText content={item.content || ''} />
            </div>
            <CopyButton text={item.content || ''} className="text-[10px] text-gray-500 hover:text-info flex-shrink-0" />
          </div>
        );
      }
      return (
        <div key={idx} className="mb-3 ml-1 border-l-2 border-border/50 pl-3 py-0.5">
          <MessageWithToolbar content={item.content || ''} />
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
          ownEmpNo={ownEmpNo}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onBatchArchive={handleBatchArchive}
          collapsed={sessCollapsed}
          onToggleCollapse={toggleSessCollapsed}
        />
      )}

      {/* 中间+右侧（SqlAuxBridgeCtx：SQL 助手↔内嵌 DB 面板会话内联动桥） */}
      <SqlAuxBridgeCtx.Provider value={sqlAuxBridge}>
      <div className="flex-1 flex min-w-0">
        {/* 对话区（K-039：面板最大化 / SQL 探索模式时 display:none 隐藏——不卸载，WS/滚动/输入状态全保留） */}
        <div className={`flex-1 flex flex-col min-w-0 ${sideMax || dbExplore ? 'hidden' : ''}`}>
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
            {pickedPurpose && (() => {
              const pt = purposes.find(p => p.id === pickedPurpose)?.title || PURPOSE_TITLE_FALLBACK[pickedPurpose];
              if (!pt) return null;
              const isReq = pickedPurpose === 'requirement_interview';
              return (
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${isReq ? 'bg-purple-900/30 text-purple-300' : 'bg-info/15 text-info'}`}>
                  {pt}
                </span>
              );
            })()}
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
              <GateDockCtx.Provider value={{ onAskAgent: askAgentGuide, onError: setError }}>
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
              {reconnecting && (
                <div className="bg-yellow-900/20 border border-yellow-700/30 rounded p-1.5 mb-2 flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 bg-yellow-400 rounded-full animate-pulse" />
                  <span className="text-yellow-300 text-xs">连接已断开，正在自动重连…</span>
                </div>
              )}
              {error && (
                <div className="bg-red-900/20 border border-red-700/30 rounded p-2 mb-2">
                  <span className="text-red-400 text-sm">❌ {error}</span>
                </div>
              )}
              {notice && (
                <div className="bg-green-900/20 border border-green-700/30 rounded p-2 mb-2">
                  <span className="text-green-400 text-sm">✓ {notice}</span>
                </div>
              )}
              </ArtifactCtx.Provider>
</GateDockCtx.Provider>
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
            quickText={quickText}
            onQuickTextHandled={() => setQuickText('')}
            sessionId={sessionId}
            onMaterialUploaded={() => expandSideTo('materials')}
            pendingRef={citeDraft ? { type: 'draft', path: citeDraft } : null}
            onPendingRefConsumed={() => setCiteDraft('')}
          />
        </div>

        {/* SQL 探索模式：主会话最小化为细条（K-037 细条同款视觉语言；点击恢复主对话区） */}
        {dbExplore && (
          <div className="w-9 flex-shrink-0 border-r border-border bg-surface-2/50 flex flex-col items-center py-2 gap-1.5">
            <button onClick={() => setDbExplore(false)} title="返回主会话（主对话区已最小化，WS/滚动状态保留）"
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs">💬</button>
            <span className="text-[9px] text-gray-600" style={{ writingMode: 'vertical-rl' }}>主会话</span>
          </div>
        )}

        {/* K-037：右侧面板（可收起为细条；收起时拖拽柄隐藏；SQL 探索模式强制完整展开居左） */}
        {sideCollapsed && !dbExplore ? (
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
            <button onClick={() => expandSideTo('drafts')} title={`草稿产物（${sessionDrafts.length}）`}
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs relative">
              📝
              {sessionDrafts.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 text-[8px] text-info">{sessionDrafts.length}</span>
              )}
            </button>
            <button onClick={() => expandSideTo('writing')} title={`更新足迹（${writingFeed.length}）`}
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs relative">
              ✏️
              {writingFeed.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 text-[8px] text-info">{writingFeed.length}</span>
              )}
            </button>
            <button onClick={() => expandSideTo('history')} title="提交历史 / 推送远端"
              className="w-6 h-6 rounded text-gray-500 hover:text-info hover:bg-surface-3 text-xs">
              📜
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
            {/* K-033：右侧拖拽柄（左缘拖动调宽面板；K-039 最大化 / SQL 探索模式时隐藏） */}
            {!sideMax && !dbExplore && (
              <div
                onMouseDown={startSideDrag}
                className="w-1 flex-shrink-0 cursor-col-resize hover:bg-info/40 active:bg-info/60 transition-colors"
                title="拖拽调整面板宽度"
              />
            )}

            {/* 右侧：K-032 页签面板（待办/信息包/文件页签）；SQL 探索模式撑宽 45% 为左栏主体 */}
            <SidePanel ctxUsage={ctxUsage} planItems={planItems} structuredTodos={structuredTodos} loading={loading} messages={messages} ctxLimit={ctxLimit} stats={stats} scenarioMeta={scenarioMeta} onUpdateMeta={setScenarioMeta} onError={setError} references={allRefs} onViewFile={openFileViewer} fileTabs={fileTabs} activeTab={activeSideTab} onSelectTab={setActiveSideTab} onCloseTab={closeFileTab} width={dbExplore ? '45%' : sideMax ? '100%' : sideWidth} onCollapse={dbExplore ? () => setDbExplore(false) : () => { setSideMax(false); toggleSideCollapsed(); }} maximized={sideMax} onToggleMaximize={dbExplore ? undefined : toggleSideMax} draftFiles={sessionDrafts} readingFeed={readingFeed} onOpenDocRead={openDocRead} onRefreshReadingFeed={handleRefreshReading} writingFeed={writingFeed} onOpenDocWrite={openDocWrite} onOpenDiff={openDiff} onAskAgentFix={askAgentFix} onAskAgentBatch={askAgentBatch} onRefreshWritingFeed={handleRefreshWriting} sessionId={sessionId} workspace={currentWorkspace} onCiteToMain={(fn: string) => setCiteDraft(fn)} onAskAgentGuide={askAgentGuide} purposePanels={purposes.find(p => p.id === pickedPurpose)?.panels || []} onSaveDraft={handleSaveDraftFile} />
          </>
        )}

        {/* SQL 探索模式右栏：内嵌 DB 证据面板（initialSql 回填自动执行；草稿/历史与独立页互通） */}
        {dbExplore && (
          <DbPanel initialSql={dbPendingSql} onClose={() => setDbExplore(false)} onHandToAux={handToAux} />
        )}
      </div>
      </SqlAuxBridgeCtx.Provider>

      {/* S0.6：更新对比弹窗（.bak 旧版 vs 当前） */}
      {diffItem && <DiffOverlay item={diffItem} onClose={() => setDiffItem(null)} />}
    </div>
  );
}
