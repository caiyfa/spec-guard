/** 辅助助手页签（设计 2026-08-25 §C2 引入；T-1031 定位升级：SQL 助手 → 通用辅助助手）。
 *
 * 独立 WS 连接（复用 /api/agent/ws，session_id=辅助会话；K-015 按 session_id
 * 隔离，与主连接不冲突）+ 产出物区（write_draft 落盘 + content 缓存）
 * + 📎 引用到主会话（§B6 回流通道）/ ▶ DB 面板（SQL 探索模式：会话内嵌打开）。
 * 主→辅上下文同步由后端 WS 快照注入完成（§B4 + T-1031 查看指针），本组件随每条
 * 消息携带当前活动文件页签（bridge.getViewing）。
 *
 * T-1031 界面一致性：消息渲染与主会话同链——groupMessages 分组 +
 * ToolGroupBlock 折叠工具组 + MessageWithToolbar 回复框 + MarkdownText，
 * 注入块经共享 stripRefBlock 统一剥离；上下文用量条与主会话 ContextPanel 同组件。 */
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { agentApi, modelApi } from '../../api';
import type { ModelConfig } from '../../api';
import { session } from '../../api/core';
import { SqlAuxBridgeCtx } from './contexts';
import { groupMessages } from './groupMessages';
import { CopyButton, MessageWithToolbar, isShortReply } from './MessageWithToolbar';
import { ToolGroupBlock } from './ToolBlocks';
import { ContextPanel } from './ContextPanel';
import { MarkdownText } from './MarkdownText';
import { calcCtxBreakdown, extLabelOf, fmtSize, stripRefBlock } from './utils';
import { DEFAULT_CTX_LIMIT } from './types';
import type { AgentStats, ArtifactInfo, ChatMessage, CtxUsage, GroupedItem } from './types';

interface AuxMessage { role: string; content: string; tool_calls?: any[] }

/** 模型选择持久化键（前端体验基线①：记住上次选择，恢复值失效时诚实回退默认）。 */
const LS_MODEL = 'sg_sql_aux_model';
/** 上下文用量条显隐持久化键（基线①；默认展开）。 */
const LS_SHOW_CTX = 'sg_sql_aux_show_ctx';

/** 用户当前在主界面查看的文件页签（发送时随 WS 消息上报，后端注入查看指针）。 */
interface ViewingFocus { path: string; kind: 'file' | 'draft' }

export function SqlAuxPanel({ mainSessionId, workspace, onCiteToMain, onPreview }: {
  mainSessionId: string;
  workspace: string;
  onCiteToMain: (draftFilename: string) => void;  // 「引用到主会话」——AgentChat 持有回调
  onPreview?: (path: string, kind?: 'file' | 'draft') => void;  // 产物卡预览 → 右侧文件页签
}) {
  const [auxSid, setAuxSid] = useState('');
  const [messages, setMessages] = useState<AuxMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>('closed');
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [currentModelId, setCurrentModelId] = useState(() => localStorage.getItem(LS_MODEL) || '');
  const [ctxUsage, setCtxUsage] = useState<CtxUsage | null>(null);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [showCtx, setShowCtx] = useState(() => localStorage.getItem(LS_SHOW_CTX) !== '0');
  // 错误行独立于消息链（红字提示，下一条消息发送或下次成功响应即清除）
  const [auxError, setAuxError] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const sidRef = useRef('');
  const sendRef = useRef<(t: string) => void>(() => {});
  const scrollRef = useRef<HTMLDivElement>(null);  // 滚动跟随锚点

  // 模型列表：恢复上次选择，失效时回退默认（基线①：不报错不空白）
  useEffect(() => {
    modelApi.list().then(r => {
      const list = r.models || [];
      setModels(list);
      const saved = localStorage.getItem(LS_MODEL) || '';
      if (saved && list.some(m => m.id === saved)) return;
      const def = list.find(m => m.is_default);
      setCurrentModelId(def ? def.id : (list[0]?.id || ''));
    }).catch(() => { /* 模型列表拉不到时省略下拉，走后端默认模型 */ });
  }, []);
  const onModelChange = useCallback((id: string) => {
    setCurrentModelId(id);
    localStorage.setItem(LS_MODEL, id);
  }, []);

  // 上下文窗口上限（与主会话同口径：当前模型的 max_context_tokens，缺省回退默认值）
  const ctxLimit = parseInt(models.find(m => m.id === currentModelId)?.max_context_tokens || '') || DEFAULT_CTX_LIMIT;
  // 用量条标题里的分角色明细（悬停可见；数字为 chars/4 估算 + 实测 prompt 校准）
  const ctxBreakdownTitle = useMemo(() => {
    if (!ctxUsage) return '';
    const est = calcCtxBreakdown(messages as ChatMessage[], ctxUsage.prompt_tokens);
    return `系统 ${est.system} · 用户 ${est.user} · 助手 ${est.assistant} · 工具 ${est.tool} tokens`;
  }, [ctxUsage, messages]);

  // SQL 探索模式桥（AgentChat 提供）：上报 send 供内嵌 DB 面板「交给辅助助手」直接调用；
  // getViewing 让每次发送携带用户正在看的文件页签；无桥时「▶ DB 面板」回退跳独立页
  const bridge = useContext(SqlAuxBridgeCtx);

  // 消息/加载态变化时滚动到底部（与主会话 AgentChat 同语义——跟随最新内容位置）
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, loading]);

  // 消息分组（与主会话同一 groupMessages 链：工具折叠组/思考文本/产物卡片）
  const grouped = useMemo(() => groupMessages(messages as ChatMessage[]), [messages]);

  // 产出物：write_draft 足迹收集（与主会话 sessionDrafts 同语义）+ content 缓存
  const artifacts = useMemo(() => {
    const files = new Map<string, string>();
    for (const m of messages) {
      if (m.role !== 'assistant' || !m.tool_calls) continue;
      for (const tc of m.tool_calls) {
        try {
          const args = JSON.parse(tc.function?.arguments || '{}');
          const isWrite = tc.function?.name === 'write_draft'
            || (tc.function?.name === 'draft' && args.action === 'write');
          if (isWrite && args.filename) files.set(String(args.filename), String(args.content || ''));
        } catch { /* ignore */ }
      }
    }
    return [...files.entries()];
  }, [messages]);

  /** 发送payload 统一构造：focus 指针随每条消息携带（主界面正打开的文件页签）。 */
  const buildSendPayload = useCallback((text: string): Record<string, unknown> => {
    const viewing: ViewingFocus | null = bridge?.getViewing?.() ?? null;
    return {
      message: text, session_id: sidRef.current, workspace,
      model_id: currentModelId, max_turns: 50,
      ...(viewing ? { focus_path: viewing.path, focus_kind: viewing.kind } : {}),
    };
  }, [bridge, workspace, currentModelId]);

  const send = useCallback((text: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim() || loading) return;
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    // model_id/max_turns 对齐主会话（max_turns:50）；focus_* 指向用户正在看的文件页签
    ws.send(JSON.stringify(buildSendPayload(text)));
    setInput('');
  }, [loading, buildSendPayload]);
  sendRef.current = send;

  // 清空上下文：后端清空消息（meta 保留）+ 重置父快照指纹——下一轮重新注入完整
  // <parent_context>，主会话关键信息不丢（§B4 每轮注入语义）；本地同步清空用量统计
  const clearContext = useCallback(async () => {
    if (!auxSid || loading || clearing) return;
    setClearing(true);
    try {
      await agentApi.clearSessionMessages(auxSid, workspace);
      setMessages([]);
      setCtxUsage(null);
      setStats(null);
    } catch (e: any) {
      setAuxError(`❌ 清空失败：${e.message || '请稍后重试'}`);
    } finally {
      setClearing(false);
    }
  }, [auxSid, loading, clearing, workspace]);

  // send 变化（loading/workspace 闭包刷新）时同步注册到桥——内嵌 DB 面板「交给辅助助手」经此直达；
  // 卸载/重注册前置空，避免调到已卸载组件的闭包
  useEffect(() => {
    bridge?.register(send);
    return () => bridge?.register(() => {});
  }, [bridge, send]);

  // 会话绑定跟随主会话（验收缺陷 B 修复）：mainSessionId 变化即重新解析——后端
  // spawn 幂等（同父+purpose 直接复用既有 aux），无需本地缓存绑定；旧实现以
  // sidRef 守卫粘死首个解析结果，切换主会话后永远停留在旧辅助会话上。
  const ensureSession = useCallback(async () => {
    if (!mainSessionId) return;
    try {
      const r = await agentApi.spawnSession({
        parent_session_id: mainSessionId, purpose: 'sql_assistant', workspace,
      });
      if (sidRef.current === r.session_id) return;   // 同一配对会话不重复拉历史
      sidRef.current = r.session_id;
      setAuxSid(r.session_id);
      setMessages([]); setCtxUsage(null); setStats(null);   // 换绑先清旧态再对齐历史
      const s = await agentApi.getSession(r.session_id, workspace);
      if (sidRef.current !== r.session_id) return;   // await 期间主会话又切换，弃用本次结果
      const history = (s.messages || []).map((m: any) => ({
        role: m.role, content: m.content || '', tool_calls: m.tool_calls,
      }));
      setMessages(history);
      // pending 消费挪到 WS onopen（验收缺陷 2 修复：ws 未 open 时 send 被拒会丢消息）
    } catch { /* spawn 失败下次激活重试 */ }
  }, [mainSessionId, workspace]);

  useEffect(() => { ensureSession(); }, [ensureSession]);

  // WS 连接（auxSid 就绪即建；done 后拉全量对齐——工具结果/快照完整性优先于增量拼接）
  useEffect(() => {
    if (!auxSid) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/api/agent/ws?token=${encodeURIComponent(session.getToken())}&workspace=${encodeURIComponent(workspace)}`);
    wsRef.current = ws;
    setWsState('connecting');
    ws.onopen = () => {
      setWsState('open');
      // DB 面板「交给辅助助手」中转消息：ws 就绪后消费（验收缺陷 2 修复——
      // 原在 ensureSession 里以 history.length===0 为条件，已有历史时不发且 ws 未就绪）
      const pending = sessionStorage.getItem('sg_sql_aux_send');
      if (pending) {
        sessionStorage.removeItem('sg_sql_aux_send');
        setTimeout(() => sendRef.current(pending), 100);
      }
    };
    ws.onclose = () => { setWsState('closed'); wsRef.current = null; };
    ws.onmessage = (ev) => {
      const e = JSON.parse(ev.data);
      if (e.type === 'assistant_delta') {
        setMessages(prev => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === 'assistant') last.content += e.delta;
          else next.push({ role: 'assistant', content: e.delta });
          return next;
        });
      } else if (e.type === 'tool_call') {
        setMessages(prev => [...prev, {
          role: 'assistant', content: '',
          tool_calls: [{ function: e.tool_call?.function || { name: '', arguments: '{}' } }],
        }]);
      } else if (e.type === 'assistant' && e.usage) {
        // T-1031：每轮 assistant 事件带 usage → 上下文用量条实时刷新（与主会话同源）
        setCtxUsage({
          prompt_tokens: e.usage.prompt_tokens || 0,
          completion_tokens: e.usage.completion_tokens || 0,
          total_tokens: e.usage.total_tokens || 0,
        });
      } else if (e.type === 'done') {
        if (e.stats) setStats(e.stats);
        agentApi.getSession(sidRef.current, workspace).then(s => {
          setMessages((s.messages || []).map((m: any) => ({
            role: m.role, content: m.content || '', tool_calls: m.tool_calls,
          })));
        }).catch(() => {});
        setLoading(false);
        setAuxError('');
      } else if (e.type === 'error') {
        setLoading(false);
        setAuxError(e.message || '执行失败');
      }
    };
    return () => { ws.close(); wsRef.current = null; };
  }, [auxSid, workspace]);

  const toggleShowCtx = useCallback(() => {
    setShowCtx(v => {
      localStorage.setItem(LS_SHOW_CTX, v === true ? '0' : '1');
      return !v;
    });
  }, []);

  // ── 渲染（与主会话 renderGrouped 同款分支；面板窄版样式微缩） ──
  const renderGrouped = (item: GroupedItem, idx: number) => {
    if (item.type === 'user') {
      return (
        <div key={idx} className={`${idx > 0 ? 'mt-3' : ''} mb-2 flex justify-end`}>
          <div className="max-w-[85%] rounded-lg rounded-br-sm px-2.5 py-1.5 text-fs-body bg-info/10 text-info/90 border border-info/20 whitespace-pre-wrap break-words">
            {stripRefBlock(item.content || '')}
            <div className="flex items-center gap-1 mt-1">
              <CopyButton text={stripRefBlock(item.content || '')} className="text-fs-aux text-info/40 hover:text-info" />
            </div>
          </div>
        </div>
      );
    }
    if (item.type === 'assistant-text') {
      if (item.thought) {
        return (
          <div key={idx} className="mb-2 px-1.5 py-1 border-l-2 border-info/30 text-fs-body text-gray-400 italic">
            <MarkdownText content={item.content || ''} />
          </div>
        );
      }
      if (isShortReply(item.content || '')) {
        return (
          <div key={idx} className="mb-2 ml-1 border-l-2 border-border/50 pl-2 py-0.5 flex items-center gap-1.5">
            <div className="flex-1 min-w-0 text-fs-body">
              <MarkdownText content={item.content || ''} />
            </div>
            <CopyButton text={item.content || ''} className="text-fs-aux text-gray-500 hover:text-info flex-shrink-0" />
          </div>
        );
      }
      return (
        <div key={idx} className="mb-3 ml-1 border-l-2 border-border/50 pl-2 py-0.5">
          <MessageWithToolbar content={item.content || ''} />
        </div>
      );
    }
    if (item.type === 'artifact' && item.artifacts) {
      return (
        <div key={idx} className="mb-2 ml-1 space-y-1">
          {item.artifacts.map((a: ArtifactInfo, ai) =>
            <ArtifactRow key={ai} artifact={a} onPreview={onPreview} compact />)}
        </div>
      );
    }
    if (item.type === 'step-complete') {
      return (
        <div key={idx} className="mb-2 flex items-center gap-2 px-2 py-1 bg-green-900/10 border border-green-700/20 rounded text-fs-body">
          <span className="text-green-500">✅</span>
          <span className="text-green-400/80">完成：{item.content}</span>
        </div>
      );
    }
    if (item.type === 'tool-group' && item.tools) {
      return <ToolGroupBlock key={idx} tools={item.tools} stepLabel={item.stepLabel} />;
    }
    return null;
  };

  return (
    <div className="flex flex-col h-full text-fs-body">
      <div className="flex items-center gap-2 py-1 text-fs-aux text-gray-500 border-b border-border flex-shrink-0">
        <span className={wsState === 'open' ? 'text-green-500' : 'text-red-400'}>{wsState === 'open' ? '●' : '○'}</span>
        <span className="whitespace-nowrap">辅助助手（辅助会话）</span>
        {auxSid && <span className="font-mono text-gray-600 truncate flex-1" title={auxSid}>{auxSid}</span>}
        {models.length > 0 && (
          <select
            value={currentModelId}
            onChange={e => onModelChange(e.target.value)}
            className="bg-surface-2 border border-border rounded px-1 py-0.5 text-fs-aux text-gray-400 font-mono max-w-[120px] flex-shrink-0"
            title="切换辅助会话模型（下一轮生效）">
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.is_default ? '★ ' : ''}{m.name || m.model}</option>
            ))}
          </select>
        )}
        {/* 📊 上下文用量开关（T-1031 与主会话同款 ContextPanel；有数据前置灰不隐藏入口） */}
        <button onClick={toggleShowCtx}
          disabled={!ctxUsage}
          className={`px-1 flex-shrink-0 ${showCtx && ctxUsage ? 'text-info' : 'text-gray-400 hover:text-info'} disabled:opacity-40`}
          title={ctxUsage ? `${ctxBreakdownTitle}\n↑输入 ${ctxUsage.prompt_tokens} / ↓输出 ${ctxUsage.completion_tokens}` : '发送首条消息后显示上下文用量'}>
          📊
        </button>
        <button onClick={clearContext}
          disabled={!auxSid || loading || clearing || messages.length === 0}
          className="px-1.5 py-0.5 rounded border border-border text-gray-400 hover:text-info disabled:opacity-40 flex-shrink-0 whitespace-nowrap"
          title="清空辅助会话消息（主会话不受影响；主会话最新快照会在下一条消息自动重新注入）">
          {clearing ? '清空中…' : '🧹 清空'}
        </button>
      </div>

      {showCtx && ctxUsage && (
        <ContextPanel ctxUsage={ctxUsage} messages={messages as ChatMessage[]} ctxLimit={ctxLimit} stats={stats} />
      )}

      <div className="flex-1 overflow-y-auto py-2 space-y-2 min-h-0">
        {messages.length === 0 && !loading && (
          <div className="text-gray-600">
            向辅助助手提问：场景/草稿解读、数据校对 SQL、失败归因、Spec 锚点解释……先读内容本体再回答。
            <div className="mt-1 text-gray-700">主会话最新快照与你正在查看的文件页签会随每条消息自动注入——清空上下文后也不丢。</div>
          </div>
        )}
        {grouped.map(renderGrouped)}
        {loading && <div className="text-gray-500 animate-pulse">辅助助手思考中…</div>}
        {auxError && (
          <div className="text-red-400 text-fs-body">❌ {auxError}</div>
        )}
        <div ref={scrollRef} />
      </div>

      {artifacts.length > 0 && (
        <div className="border-t border-border pt-1 mt-1 space-y-1 flex-shrink-0">
          <div className="text-fs-aux text-gray-500">产物区（{artifacts.length}）· write_draft 落盘，点击「引用」回流主会话</div>
          {artifacts.map(([fn, content]) => (
            <ArtifactRow key={fn} artifact={{
              fileName: fn,
              title: fn,
              size: content ? new Blob([content]).size : undefined,
              content: content || undefined,
            }} onPreview={onPreview}
              actions={
                <>
                  <button onClick={() => onCiteToMain(fn)}
                    className="text-fs-aux px-1.5 py-0.5 rounded border border-info/40 text-info hover:bg-info/10 flex-shrink-0"
                    title="把 @draft 引用预填进主会话输入框（发送后主会话 Agent 可读该文件）">
                    📎 引用
                  </button>
                  <button
                    onClick={() => {
                      if (bridge) {
                        // SQL 探索模式：会话内嵌打开（左 辅助助手 / 右 DB 面板），回填自动执行
                        bridge.openDbPanel(content || '');
                      } else {
                        window.open(`/db-console?sql=${encodeURIComponent(content || '')}`, '_self');
                      }
                    }}
                    className="text-fs-aux px-1.5 py-0.5 rounded border border-border text-gray-400 hover:text-info flex-shrink-0"
                    title="在会话内打开 DB 证据面板回填执行（主会话自动最小化）">▶ DB</button>
                </>
              } />
          ))}
        </div>
      )}

      <div className="border-t border-border pt-1 flex gap-1 flex-shrink-0">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
          placeholder="问点什么…（Enter 发送）"
          className="flex-1 bg-surface-2 border border-border rounded px-2 py-1 text-fs-body resize-none"
          rows={2}
        />
        <button onClick={() => send(input)} disabled={loading || !auxSid || wsState !== 'open'}
          className="px-2 rounded bg-info/20 text-info border border-info/40 disabled:opacity-50">发送</button>
      </div>
    </div>
  );
}

/** 产物行（write_draft 落盘文件）：文件名 + 格式/大小徽标 + 可选动作区。
 *  主区默认「预览 ›」（开右侧文件页签，T-1024 双视图承接 .sql/.md/.yaml）；
 *  底部产物区传入 actions（📎 引用 / ▶ DB），对话流内嵌产物组只带预览。 */
function ArtifactRow({ artifact, onPreview, actions, compact }: {
  artifact: ArtifactInfo;
  onPreview?: (path: string, kind?: 'file' | 'draft') => void;
  actions?: ReactNode;
  compact?: boolean;
}) {
  const metaParts = [
    fmtSize(artifact.size),
    extLabelOf(artifact.fileName),
  ].filter(Boolean);
  return (
    <div className={`flex items-center gap-2 ${compact ? 'border border-border rounded px-2 py-1 hover:border-info/40' : ''}`}>
      <span className="flex-shrink-0">📄</span>
      <span className="min-w-0 flex-1 truncate font-mono text-gray-300" title={artifact.fileName}>
        {artifact.title !== artifact.fileName ? `${artifact.title}（${artifact.fileName}）` : artifact.fileName}
      </span>
      {metaParts.length > 0 && <span className="text-fs-micro text-gray-600 flex-shrink-0">{metaParts.join(' · ')}</span>}
      <button onClick={() => onPreview?.(artifact.fileName!, 'draft')}
        disabled={!onPreview || !artifact.fileName}
        className="text-fs-aux text-info/80 hover:text-info flex-shrink-0 disabled:opacity-40"
        title="在右侧文件页签预览该草稿">预览 ›</button>
      {actions}
    </div>
  );
}

export default SqlAuxPanel;
