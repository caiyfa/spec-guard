// topicList.test.ts — 话题列表筛选/排序纯函数单测（T-1001 F2 + 追修：
// dedupeTopics 同 id 去重 / collectKeywords 词频 / tags 标签筛选）。

import { describe, expect, it } from 'vitest';
import { filterTopics, sortTopics, filterAndSortTopics, dedupeTopics,
  collectKeywords, buildTagIndex, groupTagFacets } from './topicList';
import type { FeishuTopic, FeishuTagRegistry } from '../api';

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

describe('dedupeTopics（T-1001 追修：candidates/confirmed 同 id 双份去重）', () => {
  it('同 id 后值覆盖先值、位置保持首次（Map 语义，与页头 byId 同口径）', () => {
    const old = topic({ id: 'x', title: 'facts 副本', summary: '旧' });
    const fresh = topic({ id: 'x', title: '_topics 副本', summary: '新', status: 'confirmed' });
    const other = topic({ id: 'y', title: '独立卡' });
    const out = dedupeTopics([old, other, fresh]);
    expect(out).toHaveLength(2);
    expect(out[0].title).toBe('_topics 副本');   // 位置首次、值取后
    expect(out[1].id).toBe('y');
  });

  it('无 id 条目原样保留（不折叠）', () => {
    const a = topic({ id: '' as string, title: '无id甲' });
    const b = topic({ id: '' as string, title: '无id乙' });
    expect(dedupeTopics([a, b])).toHaveLength(2);
  });

  it('无重复时原样返回', () => {
    expect(dedupeTopics(ITEMS)).toHaveLength(3);
  });
});

describe('collectKeywords（标签芯片词频）', () => {
  it('按词频降序、同频按字符序（localeCompare 口径）', () => {
    const items = [
      topic({ id: 'k1', keywords: ['导出', 'beta'] }),
      topic({ id: 'k2', keywords: ['导出', 'alpha'] }),
      topic({ id: 'k3', keywords: ['导出'] }),
    ];
    expect(collectKeywords(items)).toEqual([
      { kw: '导出', n: 3 }, { kw: 'alpha', n: 1 }, { kw: 'beta', n: 1 },
    ]);
  });

  it('空 keywords 不产生条目', () => {
    expect(collectKeywords([topic({ id: 'e' })])).toEqual([]);
  });
});

describe('filterTopics tags 标签筛选（AND 语义）', () => {
  const TAGGED = [
    topic({ id: 't1', keywords: ['导出', '权限'] }),
    topic({ id: 't2', keywords: ['导出'] }),
    topic({ id: 't3', keywords: ['权限'] }),
  ];

  it('空标签集不筛选', () => {
    expect(filterTopics(TAGGED, { tags: [] })).toHaveLength(3);
  });

  it('单标签命中 keywords', () => {
    expect(filterTopics(TAGGED, { tags: ['导出'] }).map(t => t.id)).toEqual(['t1', 't2']);
  });

  it('多标签 AND（须全部命中）', () => {
    expect(filterTopics(TAGGED, { tags: ['导出', '权限'] }).map(t => t.id)).toEqual(['t1']);
  });

  it('未命中任何话题返回空（诚实空态，不兜底放开）', () => {
    expect(filterTopics(TAGGED, { tags: ['不存在标签'] })).toHaveLength(0);
  });
});

// ══════════════════════════════════════════════════════════
// tag-taxonomy：词表索引（别名归一 / 域分组）
// ══════════════════════════════════════════════════════════

const REG: FeishuTagRegistry = {
  version: 1,
  tags: {
    '权限': { aliases: ['数据权限', '权限需求'], domain: '平台权限', status: 'active' },
    'Bug#140594': { aliases: ['Bug 140594', '140594'], domain: '', status: 'active' },
    '新指标': { aliases: [], domain: '', status: 'pending' },
  },
  domains: { '平台权限': { status: 'active' } },
};

describe('buildTagIndex + collectKeywords 别名归一（tag-taxonomy）', () => {
  it('别名归并到主标签下聚合计数（同卡多个别名只计一次）', () => {
    const idx = buildTagIndex(REG);
    const items = [
      topic({ id: 'a', keywords: ['数据权限'] }),
      topic({ id: 'b', keywords: ['权限需求', '权限'] }),
      topic({ id: 'c', keywords: ['Bug 140594', '140594'] }),
    ];
    expect(collectKeywords(items, idx)).toEqual([
      { kw: '权限', n: 2 }, { kw: 'Bug#140594', n: 1 },
    ]);
  });

  it('无索引时原样词频（向后兼容）', () => {
    const items = [topic({ id: 'a', keywords: ['数据权限'] })];
    expect(collectKeywords(items)).toEqual([{ kw: '数据权限', n: 1 }]);
  });

  it('查找键忽略空白与大小写（与后端 _norm_key 同口径）', () => {
    const idx = buildTagIndex(REG);
    expect(idx.canonOf('bug140594')).toBe('Bug#140594');
    expect(idx.canonOf(' 权限 ')).toBe('权限');
    expect(idx.canonOf('未登记词')).toBe('未登记词');
    expect(idx.statusOf('新指标')).toBe('pending');
    expect(idx.domainOf('数据权限')).toBe('平台权限');
  });
});

describe('filterTopics tags 经别名索引匹配（tag-taxonomy）', () => {
  it('话题携带别名关键词也命中主标签筛选', () => {
    const idx = buildTagIndex(REG);
    const items = [
      topic({ id: 'a', keywords: ['数据权限'] }),
      topic({ id: 'b', keywords: ['同步'] }),
    ];
    expect(filterTopics(items, { tags: ['权限'], tagIndex: idx })
      .map(t => t.id)).toEqual(['a']);
  });
});

describe('groupTagFacets 按域分组（tag-taxonomy 两级展示）', () => {
  it('按域聚合总量降序、未分组殿后；组内计数降序并携带状态', () => {
    const idx = buildTagIndex(REG);
    const facets = [
      { kw: '权限', n: 2 },        // domain 平台权限
      { kw: '同步', n: 5 },        // 未登记 → 未分组
      { kw: 'Bug#140594', n: 3 },  // domain ''
      { kw: '新指标', n: 1 },      // pending, domain ''
    ];
    const groups = groupTagFacets(facets, idx);
    expect(groups.map(g => g.domain)).toEqual(['平台权限', '']);
    expect(groups[0].total).toBe(2);
    expect(groups[0].items[0]).toEqual({ kw: '权限', n: 2, status: 'active' });
    expect(groups[1].items.map(i => i.kw)).toEqual(['同步', 'Bug#140594', '新指标']);
    expect(groups[1].items.find(i => i.kw === '新指标')?.status).toBe('pending');
  });

  it('全域为空（词表未建档）→ 单一未分组组（调用方退化为平铺）', () => {
    const groups = groupTagFacets([{ kw: '同步', n: 1 }], buildTagIndex(null));
    expect(groups).toHaveLength(1);
    expect(groups[0].domain).toBe('');
  });
});
