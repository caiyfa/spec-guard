// topicList.ts — 话题列表筛选/排序纯函数（T-1001 F2：卡片平铺改列表，
// 话题多时可搜索定位）。纯函数无副作用，单测见 topicList.test.ts。

import type { FeishuTopic, FeishuTopicDraft } from '../api';

export type TopicLike = FeishuTopic | FeishuTopicDraft;

// T-1001 追修：candidates（私有区 _topics.yaml，含 confirmed 状态卡）与
// confirmed（共享区 facts 事实源，确认时提升写入）同 id 双份——拼接后同
// key 撞车会撕裂 React 渲染（搜索/排序看似不生效的根因）。去重口径与
// FeishuPool 页头 byId 一致：同 id 后值覆盖先值、位置保持首次；调用方按
// [...confirmed, ...candidates] 传入即 candidates 副本（_topics.yaml 状态制
// 单一事实源，rev/status 权威）胜出。无 id 的条目（理论外）原样保留。
export function dedupeTopics<T extends TopicLike>(items: T[]): T[] {
  const pos = new Map<string, number>();
  const out: T[] = [];
  items.forEach(t => {
    const id = String((t as FeishuTopic).id || '');
    if (!id) { out.push(t); return; }
    const at = pos.get(id);
    if (at === undefined) { pos.set(id, out.length); out.push(t); }
    else out[at] = t;
  });
  return out;
}

// T-1001 追修（标签筛选）：汇总话题关键词词频（降序，同频按字符序）——
// 供标签芯片行展示；调用方传入「其他过滤已生效」的集合（分面计数口径）。
export function collectKeywords(items: TopicLike[]): { kw: string; n: number }[] {
  const freq = new Map<string, number>();
  items.forEach(t => (t.keywords || []).forEach(k => {
    if (k) freq.set(k, (freq.get(k) || 0) + 1);
  }));
  return [...freq.entries()]
    .map(([kw, n]) => ({ kw, n }))
    .sort((a, b) => b.n - a.n || a.kw.localeCompare(b.kw));
}

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
// + 标签筛选（T-1001 追修：选中标签须全部落在话题 keywords 里，AND 语义）
export function filterTopics<T extends TopicLike>(items: T[], opts: {
  status?: string;        // 'all' 或 draft/confirmed/rejected
  category?: string;      // 'all' 或五分类
  hideChat?: boolean;     // 闲聊默认过滤（拍板③）
  query?: string;
  tags?: string[];        // 选中标签集合（空=不筛选）
}): T[] {
  const q = (opts.query || '').trim().toLowerCase();
  const terms = q ? q.split(/\s+/).filter(Boolean) : [];
  const tags = opts.tags || [];
  return items.filter(t => {
    if (opts.status && opts.status !== 'all'
        && (t as FeishuTopic).status !== opts.status
        && ((t as FeishuTopic).status || 'draft') !== opts.status) return false;
    if (opts.category && opts.category !== 'all'
        && (t.category || 'routine') !== opts.category) return false;
    if (opts.hideChat && (t.category || 'routine') === 'chat') return false;
    if (tags.length) {
      const kws = t.keywords || [];
      if (!tags.every(tag => kws.includes(tag))) return false;
    }
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
