/** WebSocket 实时执行流 Hook（多用户：token 经 query 参数认证） */
import { useEffect, useRef, useState, useCallback } from 'react';
import { session } from '../api';

export interface StreamEvent {
  type: 'status' | 'output' | 'started' | 'finished' | 'aborted';
  line?: string;
  verdict?: string;
  scenario_id?: string;
  run_id?: string;
  status?: string;
  returncode?: number;
  aborted?: boolean;  // T-111: 断点暂停中被 abort 的 finished 消息标记
  cmd?: string;
  started_at?: string;
  finished_at?: string;
}

export function useRunStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // T-123：token 不再走 query 参数（URL 明文会留在访问日志/代理记录）——连接后首帧认证
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/runs/stream`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: 'auth', token: session.getToken() }));
    };
    ws.onclose = () => {
      setConnected(false);
      // 自动重连
      setTimeout(() => setEvents([]), 1000);
    };
    ws.onmessage = (e) => {
      const msg: StreamEvent = JSON.parse(e.data);
      setEvents((prev) => [...prev.slice(-500), msg]);
      if (msg.type === 'started') setRunning(true);
      if (msg.type === 'finished' || msg.type === 'aborted') setRunning(false);
      if (msg.type === 'status' && msg.status === 'running') setRunning(true);
    };

    return () => ws.close();
  }, []);

  const clear = useCallback(() => setEvents([]), []);

  return { events, connected, running, clear };
}
