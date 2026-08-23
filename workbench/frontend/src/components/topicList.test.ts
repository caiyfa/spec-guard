// topicList.test.ts — 话题列表筛选/排序纯函数单测（T-1001 F2）。

import { describe, expect, it } from 'vitest';
import { filterTopics, sortTopics, filterAndSortTopics } from './topicList';
import type { FeishuTopic } from '../api';

function topic(p: Partial<FeishuTopic>): FeishuTopic {
  return {
    id: 'tp:aaa-20260807-01', title: '', summary: '', chat_sha8: 'aaa',
    window: ['2026-08-07T10:00', '2026-08-07T10:30'],
    message_count: 1, participants_count: 1, source: 'chats/aaa/20260807.md',
    ...p,
  } as FeishuTopic;
}

const ITEMS = [
  topic({ id: 'a', title: '导出权限过滤', summary: '按 corpCode 过滤',
    keywords: ['权限'], message_count: 2, status: 'draft',
    window: ['2026-08-07T10:00', '2026-08-07T10:30'] }),
  topic({ id: 'b', title: '午饭去哪吃', summary: '食堂讨论', category: 'chat',
    message_count: 8, status: 'confirmed',
    window: ['2026-08-07T12:00', '2026-08-07T12:40'] }),
  topic({ id: 'c', title: '导出性能优化', summary: '分页导出', keywords: ['导出'],
    priority: 'high', message_count: 5, status: 'confirmed',
    window: ['2026-08-06T09:00', '2026-08-06T09:20'] }),
];

describe('filterTopics', () => {
  it('无过滤条件全量通过', () => {
    expect(filterTopics(ITEMS, {})).toHaveLength(3);
  });

  it('status 过滤（缺省视为 draft）', () => {
    expect(filterTopics(ITEMS, { status: 'draft' }).map(t => t.id)).toEqual(['a']);
    expect(filterTopics(ITEMS, { status: 'confirmed' }).map(t => t.id)).toEqual(['b', 'c']);
    expect(filterTopics(ITEMS, { status: 'all' })).toHaveLength(3);
  });

  it('category 过滤（缺省视为 routine）+ hideChat', () => {
    expect(filterTopics(ITEMS, { category: 'chat' }).map(t => t.id)).toEqual(['b']);
    expect(filterTopics(ITEMS, { hideChat: true }).map(t => t.id)).toEqual(['a', 'c']);
  });

  it('关键词搜索命中标题/摘要/关键词（大小写不敏感）', () => {
    expect(filterTopics(ITEMS, { query: '导出' }).map(t => t.id)).toEqual(['a', 'c']);
    expect(filterTopics(ITEMS, { query: 'corpCode' }).map(t => t.id)).toEqual(['a']);
    expect(filterTopics(ITEMS, { query: '权限' }).map(t => t.id)).toEqual(['a']);
    expect(filterTopics(ITEMS, { query: '不存在词' })).toHaveLength(0);
  });

  it('多词 AND 语义', () => {
    expect(filterTopics(ITEMS, { query: '导出 性能' }).map(t => t.id)).toEqual(['c']);
    expect(filterTopics(ITEMS, { query: '导出 午饭' })).toHaveLength(0);
  });
});

describe('sortTopics', () => {
  it('time-desc 默认：时间新→旧', () => {
    expect(sortTopics(ITEMS, 'time-desc').map(t => t.id)).toEqual(['b', 'a', 'c']);
  });

  it('time-asc：时间旧→新', () => {
    expect(sortTopics(ITEMS, 'time-asc').map(t => t.id)).toEqual(['c', 'a', 'b']);
  });

  it('msgs-desc：消息数多→少（同数按时间新→旧）', () => {
    expect(sortTopics(ITEMS, 'msgs-desc').map(t => t.id)).toEqual(['b', 'c', 'a']);
  });

  it('priority：high 先行，同级时间新→旧', () => {
    expect(sortTopics(ITEMS, 'priority').map(t => t.id)).toEqual(['c', 'b', 'a']);
  });
});

describe('filterAndSortTopics 组合', () => {
  it('先筛后排（闲聊过滤 + 时间旧→新）', () => {
    const out = filterAndSortTopics(ITEMS, { hideChat: true }, 'time-asc');
    expect(out.map(t => t.id)).toEqual(['c', 'a']);
  });
});
