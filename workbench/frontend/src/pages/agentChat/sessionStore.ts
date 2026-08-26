import type { AgentStats, ChatMessage, CtxUsage, DocWriteItem } from './types';
import type { DocReadItem } from '../../components/ReadingPanel';

// ── 模块级会话存储（跨导航保持 WebSocket 和会话状态） ──
export const _store = {
  ws: null as WebSocket | null,
  mounted: false,
  buffer: [] as any[],
  everConnected: false,  // K-xxx: 是否建立过连接（区分首连与重连，重连触发增量补拉）
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
  writingFeed: [] as DocWriteItem[],  // S0.6：更新足迹（写型工具 doc_write 汇聚）
  // 验收缺陷 2 复验修复（2026-08-25）：用途清单跨导航缓存——SPA 跳回（如 DB 面板
  // 「交给 SQL 助手」）不走 restoreSession，purposes 为空会致 purpose 页签不装配。
  purposes: [] as { id: string; title: string; icon: string; color: string; chips: string[]; description: string; panels: string[] }[],
};
