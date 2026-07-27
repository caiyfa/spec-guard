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
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/api/runs/stream?token=${encodeURIComponent(session.getToken())}`
    );
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
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
