// topicList.ts — 话题列表筛选/排序纯函数（T-1001 F2：卡片平铺改列表，
// 话题多时可搜索定位）。纯函数无副作用，单测见 topicList.test.ts。

import type { FeishuTopic, FeishuTopicDraft } from '../api';

export type TopicLike = FeishuTopic | FeishuTopicDraft;

export type TopicSortKey =
  | 'time-desc'    // 时间新→旧（默认）
  | 'time-asc'     // 时间旧→新
  | 'msgs-desc'    // 消息数多→少
  | 'priority';    // 优先级 high→normal→low（同级按时间新→旧）

export const TOPIC_SORT_OPTIONS: { key: TopicSortKey; label: string }[] = [
  { key: 'time-desc', label: '时间 新→旧' },
  { key: 'time-asc', label: '时间 旧→新' },
  { key: 'msgs-desc', label: '消息数 多→少' },
  { key: 'priority', label: '优先级 高→低' },
];

// 优先级排序权重（与 T-991 assignLanes 口径一致：high 先行；无值按 normal）
const PRIORITY_RANK: Record<string, number> = { high: 0, normal: 1, low: 2 };

function startTs(t: TopicLike): string {
  return String(t.window?.[0] || '');
}

// 状态/分类/闲聊过滤 + 关键词搜索（标题/摘要/关键词，大小写不敏感，多词 AND）
export function filterTopics<T extends TopicLike>(items: T[], opts: {
  status?: string;        // 'all' 或 draft/confirmed/rejected
  category?: string;      // 'all' 或五分类
  hideChat?: boolean;     // 闲聊默认过滤（拍板③）
  query?: string;
}): T[] {
  const q = (opts.query || '').trim().toLowerCase();
  const terms = q ? q.split(/\s+/).filter(Boolean) : [];
  return items.filter(t => {
    if (opts.status && opts.status !== 'all'
        && (t as FeishuTopic).status !== opts.status
        && ((t as FeishuTopic).status || 'draft') !== opts.status) return false;
    if (opts.category && opts.category !== 'all'
        && (t.category || 'routine') !== opts.category) return false;
    if (opts.hideChat && (t.category || 'routine') === 'chat') return false;
    if (terms.length) {
      const hay = [t.title, t.summary, ...(t.keywords || [])]
        .join('\n').toLowerCase();
      if (!terms.every(term => hay.includes(term))) return false;
    }
    return true;
  });
}

// 排序（稳定：Array.prototype.sort 各引擎均已稳定）
export function sortTopics<T extends TopicLike>(items: T[], key: TopicSortKey): T[] {
  const arr = [...items];
  switch (key) {
    case 'time-asc':
      return arr.sort((a, b) => startTs(a).localeCompare(startTs(b)));
    case 'msgs-desc':
      return arr.sort((a, b) => (b.message_count || 0) - (a.message_count || 0)
        || startTs(b).localeCompare(startTs(a)));
    case 'priority':
      return arr.sort((a, b) => {
        const pr = (PRIORITY_RANK[(a as FeishuTopic).priority || 'normal'] ?? 1)
          - (PRIORITY_RANK[(b as FeishuTopic).priority || 'normal'] ?? 1);
        if (pr !== 0) return pr;
        return startTs(b).localeCompare(startTs(a));
      });
    case 'time-desc':
    default:
      return arr.sort((a, b) => startTs(b).localeCompare(startTs(a)));
  }
}

export function filterAndSortTopics<T extends TopicLike>(
  items: T[], opts: Parameters<typeof filterTopics>[1], sortKey: TopicSortKey,
): T[] {
  return sortTopics(filterTopics(items, opts), sortKey);
}
