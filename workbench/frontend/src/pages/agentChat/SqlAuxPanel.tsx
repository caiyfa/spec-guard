/** SQL 助手页签（设计 2026-08-25 §C2）——辅助会话迷你对话。
 *
 * 独立 WS 连接（复用 /api/agent/ws，session_id=辅助会话；K-015 按 session_id
 * 隔离，与主连接不冲突）+ 产出物区（write_draft 落盘的 .sql + content 缓存）
 * + 📎 引用到主会话（§B6 回流通道）/ ▶ DB 面板（§C3 互跳，Task 15 实装）。
 * 主→辅上下文同步由后端 WS 快照注入完成（§B4），本组件零感知。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi } from '../../api';
import { session } from '../../api/core';
import { SqlResultTable, parseDbEvidenceResult } from '../../components/SqlResultTable';

interface AuxMessage { role: string; content: string; tool_calls?: any[] }

export function SqlAuxPanel({ mainSessionId, workspace, onCiteToMain }: {
  mainSessionId: string;
  workspace: string;
  onCiteToMain: (draftFilename: string) => void;  // 「引用到主会话」——AgentChat 持有回调
}) {
  const [auxSid, setAuxSid] = useState('');
  const [messages, setMessages] = useState<AuxMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>('closed');
  const wsRef = useRef<WebSocket | null>(null);
  const sidRef = useRef('');
  const sendRef = useRef<(t: string) => void>(() => {});

  // 产出物：write_draft 足迹收集（与主会话 sessionDrafts 同语义）+ content 缓存（Task 15 跳 DB 用）
  const artifacts = (() => {
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
  })();

  const send = useCallback((text: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim() || loading) return;
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    ws.send(JSON.stringify({ message: text, session_id: sidRef.current, workspace }));
    setInput('');
  }, [loading, workspace]);
  sendRef.current = send;

  // 激活即 spawn（幂等）+ 恢复历史 + DB 面板 pending 转发（Task 15）
  const ensureSession = useCallback(async () => {
    if (!mainSessionId || sidRef.current) return;
    try {
      const r = await agentApi.spawnSession({
        parent_session_id: mainSessionId, purpose: 'sql_assistant', workspace,
      });
      sidRef.current = r.session_id;
      setAuxSid(r.session_id);
      localStorage.setItem(`sg_sql_aux_${mainSessionId}`, r.session_id);
      const s = await agentApi.getSession(r.session_id, workspace);
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
      // DB 面板「交给 SQL 助手」中转消息：ws 就绪后消费（验收缺陷 2 修复——
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
      } else if (e.type === 'done') {
        agentApi.getSession(sidRef.current, workspace).then(s => {
          setMessages((s.messages || []).map((m: any) => ({
            role: m.role, content: m.content || '', tool_calls: m.tool_calls,
          })));
        }).catch(() => {});
        setLoading(false);
      } else if (e.type === 'error') {
        setLoading(false);
        setMessages(prev => [...prev, { role: 'system', content: `❌ ${e.message}` }]);
      }
    };
    return () => { ws.close(); wsRef.current = null; };
  }, [auxSid, workspace]);

  return (
    <div className="flex flex-col h-full text-xs">
      <div className="flex items-center gap-2 py-1 text-[10px] text-gray-500 border-b border-border flex-shrink-0">
        <span className={wsState === 'open' ? 'text-green-500' : 'text-red-400'}>{wsState === 'open' ? '●' : '○'}</span>
        <span>SQL 助手（辅助会话·不进主对话）</span>
        {auxSid && <span className="font-mono text-gray-600 truncate">{auxSid}</span>}
      </div>

      <div className="flex-1 overflow-y-auto py-2 space-y-2 min-h-0">
        {messages.length === 0 && (
          <div className="text-gray-600">
            输入需求生成 SQL（如「为主会话当前场景写等效计数 SQL」）——表关系解释与设计理由随 SQL 一并给出。
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i}>
            {m.role === 'user' && <div className="bg-info/10 rounded p-1.5 text-gray-200 whitespace-pre-wrap">{m.content}</div>}
            {m.role === 'assistant' && <div className="text-gray-300 whitespace-pre-wrap pl-1">{m.content}</div>}
            {m.role === 'tool' && (() => {
              const dbData = parseDbEvidenceResult(m.content);
              return dbData
                ? <SqlResultTable rows={dbData.rows} row_count={dbData.row_count} />
                : <div className="text-gray-600 pl-1 font-mono text-[10px] truncate" title={m.content}>{m.content.slice(0, 100)}</div>;
            })()}
          </div>
        ))}
        {loading && <div className="text-gray-500 animate-pulse">SQL 助手思考中…</div>}
      </div>

      {artifacts.length > 0 && (
        <div className="border-t border-border pt-1 mt-1 space-y-1 flex-shrink-0">
          <div className="text-[10px] text-gray-500">产出物（write_draft 落盘）</div>
          {artifacts.map(([fn]) => (
            <div key={fn} className="flex items-center gap-2">
              <span className="font-mono text-gray-300 truncate flex-1" title={fn}>📄 {fn}</span>
              <button onClick={() => onCiteToMain(fn)}
                className="text-[10px] px-1.5 py-0.5 rounded border border-info/40 text-info hover:bg-info/10 flex-shrink-0"
                title="把 @draft 引用预填进主会话输入框（发送后主会话 Agent 可读该 SQL）">
                📎 引用到主会话
              </button>
              <button
                onClick={() => {
                  const sqlText = artifacts.find(([f]) => f === fn)?.[1] || '';
                  window.open(`/db-console?sql=${encodeURIComponent(sqlText)}`, '_self');
                }}
                className="text-[10px] px-1.5 py-0.5 rounded border border-border text-gray-400 hover:text-info flex-shrink-0"
                title="带 SQL 跳 DB 证据面板回填执行">▶ DB 面板</button>
            </div>
          ))}
        </div>
      )}

      <div className="border-t border-border pt-1 flex gap-1 flex-shrink-0">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
          placeholder="描述 SQL 需求…（Enter 发送）"
          className="flex-1 bg-surface-2 border border-border rounded px-2 py-1 text-xs resize-none"
          rows={2}
        />
        <button onClick={() => send(input)} disabled={loading || !auxSid || wsState !== 'open'}
          className="px-2 rounded bg-info/20 text-info border border-info/40 disabled:opacity-50">发送</button>
      </div>
    </div>
  );
}

export default SqlAuxPanel;
