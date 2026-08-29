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
  // T-1039：双菜单分侧——side 标记 live 字段当前归属（'test'|'product'），
  // sides 存放对侧快照；跨菜单切换时交换，同侧 SPA 往返零开销（原语义）
  side: '',
  sides: {} as Record<string, SideSnapshot>,
};

// 按侧快照的字段（连接级 ws/wsState/buffer 与角色级 purposes 不分侧）
export interface SideSnapshot {
  messages: ChatMessage[];
  loading: boolean;
  sessionId: string;
  sessionTitle: string;
  stats: AgentStats | null;
  turnInfo: string;
  error: string;
  planItems: string[];
  ctxUsage: CtxUsage | null;
  readingFeed: DocReadItem[];
  writingFeed: DocWriteItem[];
}

const SIDE_FIELDS = ['messages', 'loading', 'sessionId', 'sessionTitle', 'stats',
  'turnInfo', 'error', 'planItems', 'ctxUsage', 'readingFeed', 'writingFeed'] as const;

function blankSide(): SideSnapshot {
  return {
    messages: [], loading: false, sessionId: '', sessionTitle: '', stats: null,
    turnInfo: '', error: '', planItems: [], ctxUsage: null, readingFeed: [], writingFeed: [],
  };
}

/** T-1039：挂载时把 _store live 字段切到本侧（幂等，首个 useState 初始化器调用）。
 * 异侧切换：stash 对侧 live → 恢复本侧快照（无则空白）→ 清空事件缓冲
 * （缓冲里是异侧会话的事件，灌回本侧空白态即污染；对侧缺失的事件段由
 * AgentChat 挂载自愈补拉 + attach 重放对齐）。返回是否发生了异侧交换。 */
export function ensureSideStore(side: string): boolean {
  if (_store.side === side) return false;
  if (_store.side) {
    const stash = {} as Record<string, unknown>;
    for (const f of SIDE_FIELDS) stash[f] = _store[f];
    _store.sides[_store.side] = stash as unknown as SideSnapshot;
  }
  const mine = _store.sides[side] || blankSide();
  for (const f of SIDE_FIELDS) (_store as any)[f] = mine[f];
  _store.side = side;
  _store.buffer = [];
  return true;
}
