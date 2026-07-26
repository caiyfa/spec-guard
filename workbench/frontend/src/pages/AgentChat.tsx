// Agent 对话面板：REST 对话 + 工具调用卡片 + YAML 预览 + 统计

import { useState, useRef, useEffect } from 'react';
import { agentApi } from '../api';

interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
}

interface AgentEvent {
  type: string;
  [key: string]: any;
}

export default function AgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [stats, setStats] = useState<any>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [error, setError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, events]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput('');
    setLoading(true);
    setError('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setEvents([]);

    try {
      const result = await agentApi.chat({
        message: userMsg,
        session_id: sessionId,
        max_turns: 12,
      });
      
      if (result.session_id) setSessionId(result.session_id);
      if (result.stats) setStats(result.stats);
      if (result.events) setEvents(result.events);
      if (result.messages) setMessages(result.messages);
    } catch (e: any) {
      setError(e.message || '对话失败');
    } finally {
      setLoading(false);
    }
  };

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
          与 Agent 对话生成测试场景。Agent 使用 MCP 工具读取 spec、查询注册表、校验并写入草稿。
        </p>
      </div>

      {/* 会话信息 */}
      {sessionId && (
        <div className="mb-2 text-xs text-gray-500 flex items-center gap-3">
          <span>会话: <span className="text-gray-400 font-mono">{sessionId}</span></span>
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
      )}

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto mb-3 p-3 bg-surface-1 rounded-lg border border-border min-h-[300px]">
        {messages.length === 0 && !loading && (
          <div className="text-center text-gray-600 text-sm py-12">
            输入消息开始对话，例如：生成 PP-RC-008 场景
          </div>
        )}
        {messages.map(renderMessage)}
        {loading && (
          <div className="text-center py-4">
            <span className="text-gray-500 text-sm animate-pulse">Agent 思考中...</span>
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
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          rows={2}
          className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none resize-none"
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="px-5 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? '...' : '发送'}
        </button>
      </div>

      {/* 事件流（调试用） */}
      {events.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-gray-500 cursor-pointer">事件流 ({events.length})</summary>
          <div className="mt-2 bg-gray-900 rounded p-2 max-h-40 overflow-y-auto">
            {events.map((e, i) => (
              <div key={i} className="text-xs font-mono text-gray-500 mb-1">
                [{e.type}] {JSON.stringify(e).slice(0, 200)}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
