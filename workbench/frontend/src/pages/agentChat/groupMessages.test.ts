import { describe, it, expect } from 'vitest';
import { groupMessages, draftWriteUndo } from './groupMessages';
import type { ChatMessage } from './types';

const user = (content: string): ChatMessage => ({ role: 'user', content });
const text = (content: string): ChatMessage => ({ role: 'assistant', content });
const call = (name: string, args: Record<string, unknown>, content = ''): ChatMessage => ({
  role: 'assistant', content,
  tool_calls: [{ id: `c-${name}`, function: { name, arguments: JSON.stringify(args) } }],
});
const tool = (result: unknown): ChatMessage => ({
  role: 'tool', content: typeof result === 'string' ? result : JSON.stringify(result),
});

describe('draftWriteUndo（T-982 合并工具 + legacy 名）', () => {
  it('legacy write_draft/undo_draft 直判', () => {
    expect(draftWriteUndo('write_draft', {})).toBe('write');
    expect(draftWriteUndo('undo_draft', {})).toBe('undo');
  });
  it('draft 合并工具按 action 判定', () => {
    expect(draftWriteUndo('draft', { action: 'write' })).toBe('write');
    expect(draftWriteUndo('draft', { action: 'undo' })).toBe('undo');
  });
  it('其他工具/其他 action 返回 null', () => {
    expect(draftWriteUndo('draft', { action: 'promote' })).toBeNull();
    expect(draftWriteUndo('scenario', { action: 'list' })).toBeNull();
    expect(draftWriteUndo('draft', null)).toBeNull();
  });
});

describe('groupMessages 分组与步骤锚点', () => {
  it('工具调用按 TOOL_TO_STEP 归组，全部出结果后插入步骤完成提示', () => {
    const g = groupMessages([
      user('生成场景'),
      call('scenario.next_id', {}, '想想要怎么编'),
      tool({ id: 'PP-RC-008' }),
      call('scenario.next_id', {}),
      tool({ id: 'PP-RC-009' }),
      text('完成'),
    ]);
    const types = g.map(i => i.type);
    expect(types).toEqual(['user', 'assistant-text', 'tool-group', 'step-complete', 'assistant-text']);
    const grp = g[2];
    expect(grp.stepLabel).toBe('获取场景 ID');
    expect(grp.tools!.length).toBe(2);
    expect(grp.tools![0].result).toContain('PP-RC-008');
    // 完成提示只插一次且带步骤名
    expect(g[3].content).toBe('获取场景 ID');
    // 思考文本独立气泡（K-024：不藏进折叠工具组）
    expect(g[1].thought).toBe(true);
  });

  it('name.action 键命中步骤（合并工具），legacy 名兼容', () => {
    const g1 = groupMessages([call('scenario', { action: 'next_id' }), tool({})]);
    expect(g1[0].stepLabel).toBe('获取场景 ID');
    const g2 = groupMessages([call('next_scenario_id', {}), tool({})]);
    expect(g2[0].stepLabel).toBe('获取场景 ID');
  });

  it('工具结果按倒序回填到第一个未完成的工具', () => {
    const g = groupMessages([
      call('validate', { a: 1 }),
      tool({ ok: true }),
    ]);
    expect(g[0].tools![0].result).toContain('ok');
  });
});

describe('groupMessages 产物卡片（liveDrafts 口径）', () => {
  const writeYaml = (fn: string) => call('draft', { action: 'write', filename: fn, content: '# 标题一\nbody' });
  const okRes = { ok: true, size: 12 };

  it('draft(action=write) 成功出产物卡片，yaml 不带内容预览', () => {
    const g = groupMessages([writeYaml('a.yaml'), tool(okRes)]);
    const art = g.find(i => i.type === 'artifact');
    expect(art).toBeTruthy();
    expect(art!.artifacts![0].fileName).toBe('a.yaml');
    expect(art!.artifacts![0].title).toBe('标题一');
    expect(art!.artifacts![0].content).toBeUndefined();
  });

  it('undo 后卡片消失（与右侧草稿区同源口径）', () => {
    const g = groupMessages([
      writeYaml('a.yaml'), tool(okRes),
      call('draft', { action: 'undo', filename: 'a.yaml' }), tool({ ok: true }),
    ]);
    expect(g.find(i => i.type === 'artifact')).toBeUndefined();
  });

  it('写结果 ok:false 不出卡片', () => {
    const g = groupMessages([writeYaml('a.yaml'), tool({ ok: false, error: 'x' })]);
    expect(g.find(i => i.type === 'artifact')).toBeUndefined();
  });

  it('非 yaml 产物带内容预览', () => {
    const g = groupMessages([
      call('draft', { action: 'write', filename: 'note.md', content: '# 笔记\n内容' }),
      tool(okRes),
    ]);
    const art = g.find(i => i.type === 'artifact');
    expect(art!.artifacts![0].content).toContain('内容');
  });
});
