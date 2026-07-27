// Agent 对话面板（V7 修复：WebSocket 实时流——工具调用卡片随循环逐条呈现）

import { useState, useRef, useEffect, useCallback } from 'react';
import { session } from '../api';

interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
}

interface AgentStats {
  total_tokens?: number;
  is_mock?: boolean;
  model?: string;
  cache_hits?: number;
  cache_misses?: number;
}

export default function AgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [turnInfo, setTurnInfo] = useState('');
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [error, setError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turnInfo]);

  // 建立 WebSocket（页面生命周期内复用）
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/api/agent/ws?token=${encodeURIComponent(session.getToken())}`
    );
    wsRef.current = ws;
    ws.onopen = () => setWsState('open');
    ws.onclose = () => setWsState('closed');
    ws.onerror = () => setWsState('closed');

    ws.onmessage = (e) => {
      const event = JSON.parse(e.data);
      switch (event.type) {
        case 'state':
          if (event.status === 'started' && event.session_id) {
            setSessionId(event.session_id);
          } else if (event.fused) {
            setTurnInfo(`⚠️ 已达最大轮次 ${event.max_turns}，熔断转人工`);
          } else if (typeof event.turn === 'number') {
            setTurnInfo(`轮次 ${event.turn + 1}/${event.max_turns}`);
          }
          break;
        case 'assistant':
          if (event.message) {
            setMessages(prev => [...prev, event.message]);
          }
          break;
        case 'tool_call':
          setMessages(prev => [...prev, { role: 'tool', content: String(event.result ?? '') }]);
          break;
        case 'done':
          setStats(event.stats || null);
          if (event.session_id) setSessionId(event.session_id);
          setTurnInfo('');
          setLoading(false);
          break;
        case 'error':
          setError(event.message || 'Agent 异常');
          setLoading(false);
          break;
      }
    };

    return () => ws.close();
  }, []);

  const handleSend = useCallback(() => {
    const userMsg = input.trim();
    const ws = wsRef.current;
    if (!userMsg || loading || !ws || ws.readyState !== WebSocket.OPEN) return;
    setInput('');
    setLoading(true);
    setError('');
    setTurnInfo('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    ws.send(JSON.stringify({ message: userMsg, session_id: sessionId, max_turns: 12 }));
  }, [input, loading, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const renderMessage = (msg: ChatMessage, idx: number) => {
    if (msg.role === 'system') return null;

    const isUser = msg.role === 'user';
    const isTool = msg.role === 'tool';
    const isAssistant = msg.role === 'assistant';

    return (
      <div key={idx} className={`mb-3 ${isUser ? 'text-right' : ''}`}>
        <div className={`inline-block max-w-[85%] rounded-lg px-3 py-2 text-sm ${
          isUser ? 'bg-info/15 text-info' :
          isTool ? 'bg-gray-800 text-gray-300 font-mono text-xs' :
          'bg-surface-3 text-gray-200'
        }`}>
          {isAssistant && msg.tool_calls ? (
            <div className="space-y-2">
              {msg.content && <div>{msg.content}</div>}
              {msg.tool_calls.map((tc, i) => (
                <div key={i} className="bg-gray-900 rounded p-2 border border-gray-700">
                  <span className="text-yellow-400 text-xs font-mono">🔧 {tc.function.name}</span>
                  <pre className="text-gray-500 text-xs mt-1 overflow-x-auto">{tc.function.arguments}</pre>
                </div>
              ))}
            </div>
          ) : (
            <div className={isTool ? 'whitespace-pre-wrap max-h-60 overflow-y-auto' : 'whitespace-pre-wrap'}>
              {msg.content}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full max-w-4xl mx-auto">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">🤖 Agent 场景生成</h2>
        <p className="text-xs text-gray-500 mt-1">
          与 Agent 对话生成测试场景。工具调用过程实时可见；产物落 drafts/，经「📝 草稿评审」三道闸入库。
        </p>
      </div>

      {/* 会话信息 */}
      <div className="mb-2 text-xs text-gray-500 flex items-center gap-3">
        <span className={wsState === 'open' ? 'text-green-500' : 'text-red-400'}>
          {wsState === 'open' ? '● 已连接' : '○ 未连接'}
        </span>
        {sessionId && (
          <>
            <span>·</span>
            <span>会话: <span className="text-gray-400 font-mono">{sessionId}</span></span>
          </>
        )}
        {stats && (
          <>
            <span>·</span>
            <span>Tokens: {stats.total_tokens || 0}</span>
            <span>·</span>
            <span className={stats.is_mock ? 'text-yellow-500' : 'text-green-500'}>
              {stats.is_mock ? 'MOCK 模式' : 'LIVE'} ({stats.model})
            </span>
          </>
        )}
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto mb-3 p-3 bg-surface-1 rounded-lg border border-border min-h-[300px]">
        {messages.length === 0 && !loading && (
          <div className="text-center text-gray-600 text-sm py-12">
            输入消息开始对话，例如：生成 PP-RC-008 场景
          </div>
        )}
        {messages.map(renderMessage)}
        {loading && (
          <div className="text-center py-2">
            <span className="text-gray-500 text-sm animate-pulse">
              Agent 工作中… {turnInfo && <span className="text-gray-600 font-mono ml-2">{turnInfo}</span>}
            </span>
          </div>
        )}
        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-2">
            <span className="text-red-400 text-sm">❌ {error}</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="flex gap-2">
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={wsState === 'open' ? '输入消息... (Enter 发送, Shift+Enter 换行)' : 'WebSocket 未连接，请刷新页面'}
          rows={2}
          className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none resize-none"
          disabled={loading || wsState !== 'open'}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim() || wsState !== 'open'}
          className="px-5 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? '...' : '发送'}
        </button>
      </div>
    </div>
  );
}
